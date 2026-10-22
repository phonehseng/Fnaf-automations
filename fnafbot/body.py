"""The brain's interface to the REAL game (the simulator has the same methods).

RealBody turns the brain's requests ("face left", "press the right light",
"what does camera 4B show?") into mouse actions and screen readings, and
keeps the night clock.

The night clock
    Every game timer counts from the first frame of the night, which is the
    first frame where the office HUD is visible. Measured on the live game,
    power changes then land 0.01 - 0.03 s after each whole second. The clock
    keeps refining itself from those power changes (see _calibrate()), so the
    brain can time actions to a couple of frames.
"""

from __future__ import annotations

import ctypes
import logging
import time

import cv2
import numpy as np

from fnafbot import layout
from fnafbot.controller import Controller, LEFT, RIGHT
from fnafbot.vision import Vision

log = logging.getLogger(__name__)

# How long the HUD must be missing before we decide the night has ended
# (6 AM screen, a jumpscare, or the power-out sequence).
HUD_GONE_SECONDS = 1.5

# Typical delay between a game frame and our screenshot of it.
CAPTURE_LATENCY = 0.015

# Doorway brightness (0-255 gray) above which the hall light counts as on.
LIT_THRESHOLD = 11.0
DOORWAY_REGION = {LEFT: (slice(150, 600), slice(0, 300)), RIGHT: (slice(150, 600), slice(980, 1280))}


class StopRequested(Exception):
    """Raised when the user presses the stop hotkey."""


def _precise_timers() -> None:
    """Ask Windows for 1 ms sleep resolution (default is ~15.6 ms)."""
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except OSError:
        pass


class RealBody:
    def __init__(self, controller: Controller, vision: Vision, stop_flag=lambda: False) -> None:
        _precise_timers()
        self.ctl = controller
        self.vision = vision
        self.stop_flag = stop_flag
        self.t0 = 0.0                       # perf_counter() at the night's first frame
        self.t0_upper_bound = 0.0           # best proven upper bound on the true night start
        self.last_hud_seen = 0.0
        self.last_power: int | None = None
        self.over = False
        self.facing: str | None = None
        # Alternate between two click spots per button (see layout.py note on
        # double-clicks).
        self._toggle: dict[str, bool] = {}

    # ------------------------------------------------------------------
    # Clock
    # ------------------------------------------------------------------

    def start_clock(self, timeout: float = 60.0) -> None:
        """Wait for the night's first frame and start the clock there."""
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            self._check_stop()
            frame = self.ctl.window.grab()
            if self.vision.hud_visible(frame):
                self.t0 = time.perf_counter() - CAPTURE_LATENCY
                self.t0_upper_bound = self.t0 + CAPTURE_LATENCY
                self.last_hud_seen = time.perf_counter()
                log.info("Night started (clock running)")
                return
        raise RuntimeError("The night did not start (no HUD seen)")

    def now(self) -> float:
        return time.perf_counter() - self.t0

    def _calibrate(self, seen_at: float) -> None:
        """Refine the clock from a power change seen at ``seen_at``.

        Power only changes exactly on whole seconds of the night clock (tick
        k happens at night_start + k). We can only see a change AFTER it
        happened, so each sighting proves: night_start <= seen_at - k.
        The tightest such bound (minus our typical capture delay) is the best
        estimate of the night start.
        """
        k = round(seen_at - self.t0)
        bound = seen_at - k
        if abs(bound - self.t0) > 0.06:
            return  # not a whole-second power charge (e.g. Foxy's bang): ignore
        if bound < self.t0_upper_bound:
            self.t0_upper_bound = bound
            new_t0 = bound - CAPTURE_LATENCY
            log.debug("Clock refined by %+.3f s", new_t0 - self.t0)
            self.t0 = new_t0

    def _observe(self) -> np.ndarray:
        """Grab a frame, update HUD-based state (power, night over, clock)."""
        self._check_stop()
        frame = self.ctl.window.grab()
        hud = self.vision.read_hud(frame)
        stamp = time.perf_counter()
        if hud.visible:
            self.last_hud_seen = stamp
            if hud.power is not None:
                if self.last_power is not None and hud.power != self.last_power:
                    self._calibrate(stamp)
                self.last_power = hud.power
            self.ctl.hud = hud
        elif stamp - self.last_hud_seen > HUD_GONE_SECONDS:
            self.over = True
        return frame

    def wait_until(self, t: float) -> None:
        """Idle until night-time ``t``, watching the HUD meanwhile."""
        while not self.over:
            remaining = t - self.now()
            if remaining <= 0:
                return
            if remaining > 0.04:
                self._observe()
                time.sleep(min(0.01, max(0.0, t - self.now() - 0.03)))
            else:
                # Last few milliseconds: spin for precision.
                while self.now() < t:
                    pass
                return

    def night_over(self) -> bool:
        if not self.over and time.perf_counter() - self.last_hud_seen > 0.3:
            self._observe()
        return self.over

    def _check_stop(self) -> None:
        if self.stop_flag():
            raise StopRequested()

    # ------------------------------------------------------------------
    # Office
    # ------------------------------------------------------------------

    def face(self, side: str) -> None:
        self._check_stop()
        self.ctl.face(side)
        self.facing = side

    def press(self, kind: str, side: str) -> None:
        """Click a door or light button (the controller waits out the game's
        click cooldown). Alternates between two spots on the button."""
        self._check_stop()
        key = f"{kind}-{side}"
        alternate = self._toggle[key] = not self._toggle.get(key, False)
        if kind == "light":
            if side == LEFT:
                spot = layout.LEFT_LIGHT_BUTTON_OFF if alternate else layout.LEFT_LIGHT_BUTTON
            else:
                spot = layout.RIGHT_LIGHT_BUTTON_OFF if alternate else layout.RIGHT_LIGHT_BUTTON
        else:
            base = layout.LEFT_DOOR_BUTTON if side == LEFT else layout.RIGHT_DOOR_BUTTON
            spot = (base[0], base[1] + (18 if alternate else 0))
        self.ctl.press(spot)
        log.debug("pressed %s %s at %.3f", kind, side, self.now())

    def _lit(self, frame: np.ndarray, side: str) -> bool:
        rows, cols = DOORWAY_REGION[side]
        return float(cv2.cvtColor(frame[rows, cols], cv2.COLOR_BGR2GRAY).mean()) > LIT_THRESHOLD

    def look_doorway(self, side: str) -> tuple[bool, bool]:
        """Look at the lit doorway. Returns (someone there, light was on).
        Frames where the light flickered dark are skipped."""
        look = self.vision.bonnie_at_left_door if side == LEFT else self.vision.chica_at_right_window
        deadline = time.perf_counter() + 0.15
        while time.perf_counter() < deadline:
            frame = self.ctl.window.grab()
            if self.vision.current_camera(frame) is not None:
                # The monitor is up, so this is not the office: never judge a
                # doorway from a camera picture.
                log.warning("look_doorway: the camera is showing, not the office")
                return False, False
            if self._lit(frame, side):
                present, margin = look(frame)
                log.info("doorway %s: %s (margin %.1f)", side, "OCCUPIED" if present else "empty", margin)
                if present or margin > 2.0:
                    return present, True
        return False, False

    def light_is_on(self, side: str) -> bool:
        """Lights flicker dark for single frames, so look at three frames."""
        return any(self._lit(self.ctl.window.grab(), side) for _ in range(3))

    # ------------------------------------------------------------------
    # Camera
    # ------------------------------------------------------------------

    def camera_up(self) -> bool:
        self._check_stop()
        return self.ctl.camera_up()

    def camera_down(self) -> bool:
        return self.ctl.camera_down()

    def select_camera(self, camera: str) -> None:
        self._check_stop()
        if self.ctl.selected_camera != camera:
            self.ctl.mouse.click(*layout.CAMERA_BUTTONS[camera])
            self.ctl.selected_camera = camera

    def read_camera(self, camera: str) -> dict:
        """Read a camera picture: {'occupants', 'foxy_stage', 'visible'}."""
        deadline = time.perf_counter() + 0.4
        while time.perf_counter() < deadline:
            if self.vision.current_camera(self.ctl.window.grab()) == camera:
                break
        time.sleep(layout.CAMERA_SWITCH_SECONDS)
        frames = [self.ctl.window.grab() for _ in range(2)]
        reading = self.vision.read_camera(frames, camera)
        log.info("camera %s: %s foxy=%s margin=%.2f", camera, "".join(sorted(reading.occupants)) or "-",
                 reading.foxy_stage, reading.margin)
        return {
            "occupants": set(reading.occupants),
            "foxy_stage": reading.foxy_stage,
            "visible": reading.confident,
        }

    def power(self) -> int:
        return self.last_power if self.last_power is not None else 0
