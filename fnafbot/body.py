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

from fnafbot import config, layout
from fnafbot.controller import Controller, LEFT, RIGHT
from fnafbot.vision import Vision

log = logging.getLogger(__name__)

# How long the HUD must be missing before we decide the night has ended
# (6 AM screen, a jumpscare, or the power-out sequence).
HUD_GONE_SECONDS = 1.5

# Typical delay between a game frame and our screenshot of it.
CAPTURE_LATENCY = 0.015

# Doorway brightness (0-255 gray) above which the hall light counts as on
# (only used to tell whether a light is still on before switching it off).
LIT_THRESHOLD = 11.0

# A doorway reading is only trusted if the best-matching game picture fits
# better than the runner-up by at least this much (0-255 colour error).
# Measured on live frames: correct answers had margins of 2.8 - 29.
DOORWAY_MIN_MARGIN = 1.5
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

    def start_clock_at(self, first_hud_frame: float) -> None:
        """Start the clock from an already-detected first HUD frame
        (``first_hud_frame`` is a time.perf_counter() value)."""
        self.t0 = first_hud_frame
        self.t0_upper_bound = first_hud_frame + CAPTURE_LATENCY
        self.last_hud_seen = time.perf_counter()
        log.info("Night started (clock running)")

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
        """Look at the doorway with its light on. Returns (someone there, light was on).

        Each frame is classified as dark / empty / occupied by comparing it
        with the game's own pictures (vision.doorway_state). Dark frames
        (light not on yet, or one of its flickers) are skipped - "dark" is
        never taken to mean "empty". Every decision is saved as a small
        picture in logs/doorway/ so it can be checked afterwards.
        """
        deadline = time.perf_counter() + 0.2
        while time.perf_counter() < deadline:
            frame = self.ctl.window.grab()
            if self.vision.current_camera(frame) is not None:
                # The monitor is up, so this is not the office: never judge a
                # doorway from a camera picture.
                log.warning("look_doorway: the camera is showing, not the office")
                return False, False
            state, margin = self.vision.doorway_state(frame, side)
            if state == "dark" or margin < DOORWAY_MIN_MARGIN:
                continue
            log.info("doorway %s: %s (margin %.1f)", side, state.upper(), margin)
            self._save_evidence(frame, f"{side}_{state}_{margin:.1f}")
            return state == "occupied", True
        log.info("doorway %s: no lit frame (light did not come on?)", side)
        return False, False

    def _save_evidence(self, frame: np.ndarray, label: str) -> None:
        """Keep a small copy of the frame a decision was based on."""
        try:
            config.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
            small = cv2.resize(frame, (640, 360), interpolation=cv2.INTER_AREA)
            cv2.imwrite(str(config.EVIDENCE_DIR / f"{self.now():07.2f}s_{label}.jpg"), small,
                        [cv2.IMWRITE_JPEG_QUALITY, 70])
        except OSError:
            log.debug("could not save evidence frame", exc_info=True)

    def light_is_on(self, side: str) -> bool:
        """Read the LIGHT button's lamp (it does not flicker, unlike the hall)."""
        return self.vision.light_lamp_on(self.ctl.window.grab(), side)

    # ------------------------------------------------------------------
    # Camera
    # ------------------------------------------------------------------

    def camera_up(self) -> bool:
        self._check_stop()
        ok = self.ctl.camera_up()
        # A freshly raised camera also starts with a burst of static.
        self._switched_at = time.perf_counter()
        return ok

    def camera_down(self) -> bool:
        return self.ctl.camera_down()

    def select_camera(self, camera: str) -> None:
        self._check_stop()
        if self.ctl.selected_camera != camera:
            self.ctl.mouse.click(*layout.CAMERA_BUTTONS[camera])
            self.ctl.selected_camera = camera
            self._switched_at = time.perf_counter()

    def read_camera(self, camera: str) -> dict:
        """Read a camera picture: {'occupants', 'foxy_stage', 'visible'}."""
        deadline = time.perf_counter() + 0.4
        while time.perf_counter() < deadline:
            if self.vision.current_camera(self.ctl.window.grab()) == camera:
                break
        # Right after switching cameras the picture is covered by a burst of
        # static; wait for it to fade (only needed after a switch).
        settle_until = getattr(self, "_switched_at", 0.0) + layout.CAMERA_SWITCH_SECONDS
        if time.perf_counter() < settle_until:
            time.sleep(settle_until - time.perf_counter())
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
