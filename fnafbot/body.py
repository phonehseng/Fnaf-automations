"""The brain's interface to the REAL game (the simulator has the same methods).

RealBody turns the brain's requests ("face left", "press the right light",
"what does camera 4B show?") into mouse actions and screen readings, and
keeps the night clock.

The night clock
    Every game timer counts from the first frame of the night, which is the
    first frame where the office HUD is visible. The brain thinks in GAME
    seconds (tick k of the power timer is at exactly k game seconds), but a
    game second is a little longer than a real one (rules.TICK_SECONDS).
    now() converts. Power changes are seen 0.01 - 0.03 s after each tick, and
    the clock keeps refining both the night start and the length of a game
    second from them (see _calibrate()), so the brain can time actions to a
    couple of frames even late in the night.
"""

from __future__ import annotations

import ctypes
import logging
import time

import cv2
import numpy as np

from fnafbot import config, layout, rules
from fnafbot.controller import Controller, LEFT, RIGHT
from fnafbot.screen import looks_shifted
from fnafbot.vision import Vision

log = logging.getLogger(__name__)

# How long the HUD must be missing before we decide the night has ended
# (6 AM screen, a jumpscare, or the power-out sequence). Animations and the
# display switch after a tab-out can hide it briefly, so be patient.
HUD_GONE_SECONDS = 3.0
HUD_GONE_LOOKS = 10

# Typical delay between a game frame and our screenshot of it.
CAPTURE_LATENCY = 0.015

# Measuring the game second: fit a line through (tick number, time seen) for
# the power changes, once there are enough of them spread over enough ticks.
# The slope is the real length of a game second. Clamped to a sane range.
SCALE_MIN_SIGHTINGS = 20
SCALE_MIN_SPAN_TICKS = 30
SCALE_RANGE = (0.995, 1.02)
FIT_WINDOW_TICKS = 120           # fit the clock to the last two minutes of sightings
# A power change only counts for the fit if the HUD was looked at this
# shortly before (so the moment of the change is known to +- half of it).
SIGHTING_MAX_GAP = 0.12

# Write the power left to the log this often (night seconds).
POWER_LOG_EVERY = 30.0
# Warn when a timed wait ends this much later than asked.
WAIT_OVERSHOOT_WARN = 0.15
# Flip request -> camera picture readable, measured on the live game
# (0.63 - 0.75 s in logs/2026-10-22 campaign runs).
CAMERA_UP_LIVE = 0.75

# Doorway brightness (0-255 gray) above which the hall light counts as on
# (only used to tell whether a light is still on before switching it off).
LIT_THRESHOLD = 11.0

# Camera readings: how many frames to average (TV static changes every frame)
# and how clear a reading must be to be trusted. Pirate Cove decides whether
# Foxy has left, so it gets more frames and a higher bar (correct synthetic
# readings had margins >= 2.06).
CAMERA_FRAMES = {"1C": 3}
CAMERA_MIN_MARGIN = {"1C": 2.0, "4B": 0.5}
# Seconds to wait after switching to a camera before reading it. The static
# burst after a switch can outlast 0.12 s; Pirate Cove is not urgent, so it
# waits longer (live readings were wrong when taken too early).
CAMERA_SETTLE = {"1C": 0.3}

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
        self.scale = rules.TICK_SECONDS     # real seconds per game (power) second
        self.tick_phases = dict(rules.TICK_PHASE)   # movement timers: real-second offsets after the night start
        # From the flip request to a readable camera picture, measured live
        # (hover, flip-up animation, label visible): longer than the bare
        # animation the rules quote. The brain plans Foxy flips with it.
        self.camera_up_seconds = CAMERA_UP_LIVE
        self._power_sightings: list[tuple[int, float]] = []   # (tick number, perf_counter seen)
        self._fitted = False                # has the line fit taken over the clock?
        self.six_am_seen = False            # the "6 AM" screen was on display: night won
        self.power_logged_at = -1e9         # night time of the last power trace line
        self.last_hud_seen = 0.0
        self.hud_missing_since: float | None = None   # first look that found no HUD
        self.hud_missing_count = 0                     # looks in a row without the HUD
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
        """Night time in GAME seconds (what every rule in rules.py counts in)."""
        return (time.perf_counter() - self.t0) / self.scale

    def _calibrate(self, seen_at: float, gap: float = 2 * CAPTURE_LATENCY) -> None:
        """Refine the clock from a power change seen at ``seen_at``; the
        previous look at the HUD (which still showed the old value) was
        ``gap`` seconds earlier, so the change happened inside that gap.

        Power only changes on the power timer's ticks: tick k happens at
        night_start + k * scale (real seconds). Two things are learned:

        1. The night start. The change was seen AFTER it happened, so each
           sighting proves night_start <= seen_at - k * scale. The tightest
           such bound is the best early estimate.
        2. The scale (length of a game second). A straight line fitted
           through (k, time of change) has slope = scale. Without this the
           clock drifts about 3.5 s over a night - enough to let Bonnie in
           (docs/DEVLOG.md). Only changes pinned down to a short gap are
           used for the fit: while the bot is busy it may not look at the
           HUD for a second, and such a late sighting would bend the line.
        """
        if gap > SIGHTING_MAX_GAP:
            return   # noticed late: cannot even tell which tick it was
        elapsed = seen_at - self.t0
        k = round(elapsed / self.scale)
        if k < 1 or abs(elapsed - k * self.scale) > 0.25:
            return   # nowhere near a tick: not a whole-second charge
        if not self._fitted:
            bound = seen_at - k * self.scale
            if abs(elapsed - k * self.scale) < 0.08 + gap and bound < self.t0_upper_bound:
                self.t0_upper_bound = bound
                self.t0 = bound - gap / 2
        self._power_sightings.append((k, seen_at - gap / 2))   # best guess: mid-gap
        self._refit_clock()

    def _refit_clock(self) -> None:
        """Fit seen_at = t0 + k * scale through all power sightings so far.

        The slope is the length of a game second; the intercept (minus the
        typical capture delay) is the night start. Sightings far off the
        line - the extra charge for Foxy's bang - are dropped and the line
        fitted again."""
        # Only the recent sightings: the game's pace changes with what is
        # on screen, so an all-night line would lag behind the current speed.
        sightings = [s for s in self._power_sightings if s[0] >= self._power_sightings[-1][0] - FIT_WINDOW_TICKS]
        if len(sightings) < SCALE_MIN_SIGHTINGS or sightings[-1][0] - sightings[0][0] < SCALE_MIN_SPAN_TICKS:
            return
        ticks = np.array([k for k, _ in sightings], dtype=float)
        seen = np.array([t for _, t in sightings])
        slope, intercept = np.polyfit(ticks, seen, 1)
        on_line = np.abs(seen - (slope * ticks + intercept)) < 0.1
        if on_line.sum() >= SCALE_MIN_SIGHTINGS:
            slope, intercept = np.polyfit(ticks[on_line], seen[on_line], 1)
        new_scale = min(max(float(slope), SCALE_RANGE[0]), SCALE_RANGE[1])
        new_t0 = float(intercept)      # sightings are already mid-gap, so no delay to subtract
        if abs(new_scale - self.scale) > 0.0002 or abs(new_t0 - self.t0) > 0.02:
            log.info("Clock fitted from %d power changes: game second = %.4f real s (was %.4f), "
                     "night start moved %+.3f s", len(sightings), new_scale, self.scale, new_t0 - self.t0)
        self.scale, self.t0, self._fitted = new_scale, new_t0, True

    def _ensure_game(self, frame: np.ndarray | None = None) -> bool:
        """If someone switched away from the game, bring it back first.

        The game keeps running while minimised, so this must happen fast.
        After coming back, what the controller believed about the screen
        (camera up or down, which side is in view) may be stale, so it is
        re-read from the screen."""
        window = self.ctl.window
        if self.over or self.six_am_seen:
            return False
        # The picture check (is the HUD drawn?) only makes sense while the
        # HUD was there a moment ago. Between screens (6 AM, a jumpscare)
        # it is legitimately missing, and "repairing" the game then would
        # minimise and restore it in a loop and reset the night-over
        # detection - which once kept the bot clicking on the title screen
        # after a night it had won (docs/DEVLOG.md).
        hud_recent = self.hud_missing_since is None
        brought_back = window.ensure_visible(picture_ok=self.vision.hud_visible if hud_recent else None)
        if not brought_back and frame is not None and looks_shifted(frame):
            # In front, but drawn in the shifted "quarter" state.
            window.repair(picture_ok=self.vision.hud_visible)
            brought_back = True
        if brought_back:
            # The screen stays black for a moment while the game switches the
            # display back to 1280x720; wait until the HUD is really back.
            deadline = time.perf_counter() + 5.0
            back = False
            while time.perf_counter() < deadline:
                frame = self.ctl.window.grab()
                if self.vision.hud_visible(frame):
                    back = True
                    break
                time.sleep(0.05)
            if not back:
                log.warning("HUD not visible 5 s after bringing the game back")
                self._save_evidence(frame, "after_restore")
            self.ctl.camera_is_up = self.ctl.camera_showing()
            self.ctl.side_in_view = None
            self.facing = None
            self.hud_missing_since, self.hud_missing_count = None, 0
            log.warning("Resumed after the game was out of focus (%.2f s into the night)", self.now())
            return True
        return False

    def _note_hud(self, hud, stamp: float) -> None:
        """Book a HUD reading taken at ``stamp``: the clock learns from power
        changes, and the power is traced to the log now and then. Called for
        office frames AND camera frames (the HUD shows on both), so the clock
        keeps following the game's speed while the monitor is up - the game
        runs at a slightly different pace then (measured with
        tools/measure_ticks.py)."""
        if hud.power is not None:
            if self.last_power is not None and hud.power != self.last_power:
                # The change happened somewhere between the previous look at
                # the HUD and this one.
                self._calibrate(stamp, gap=stamp - self.last_hud_seen)
            self.last_power = hud.power
            if self.now() - self.power_logged_at >= POWER_LOG_EVERY:
                self.power_logged_at = self.now()
                log.info("power %d%% at %.0f s (usage %s)", hud.power, self.now(), hud.usage)
        self.last_hud_seen = stamp
        self.ctl.hud = hud

    def _observe(self) -> np.ndarray:
        """Grab a frame, update HUD-based state (power, night over, clock)."""
        self._check_stop()
        frame = self.ctl.window.grab()
        if self._ensure_game(frame):
            frame = self.ctl.window.grab()
        hud = self.vision.read_hud(frame)
        stamp = time.perf_counter()
        if hud.visible:
            self.hud_missing_since = None
            self.hud_missing_count = 0
            self._note_hud(hud, stamp)
        else:
            # The HUD can be hidden for a few frames (e.g. by the monitor
            # animation). Only a HUD that stays missing across several looks
            # for HUD_GONE_SECONDS means the night is really over.
            if self.hud_missing_since is None:
                self.hud_missing_since = stamp
            self.hud_missing_count += 1
            # Winning is decided by what replaces the HUD, never by the
            # clock: only the "6 AM" screen counts (a jumpscare, the
            # power-out blackout and the static afterwards look nothing
            # like it).
            if not self.six_am_seen and self.vision.six_am_visible(frame):
                self.six_am_seen = True
                self.over = True
                log.info("6 AM screen seen at %.2f s - night won", self.now())
                self._save_evidence(frame, "six_am")
                return frame
            if self.hud_missing_count >= HUD_GONE_LOOKS and stamp - self.hud_missing_since > HUD_GONE_SECONDS:
                self.over = True
                log.info("Night over: no HUD for %.1f s (%d looks); 6 AM seen: %s; game in front: %s",
                         stamp - self.hud_missing_since, self.hud_missing_count, self.six_am_seen,
                         self.ctl.window.in_front())
                self._save_evidence(frame, "night_over")
        return frame

    def wait_until(self, t: float) -> None:
        """Idle until night-time ``t``, watching the HUD meanwhile."""
        slowest_look = 0.0
        while not self.over:
            remaining = t - self.now()
            if remaining <= 0:
                break
            if remaining > 0.04:
                started = time.perf_counter()
                self._observe()
                slowest_look = max(slowest_look, time.perf_counter() - started)
                time.sleep(min(0.01, max(0.0, t - self.now() - 0.03)))
            else:
                # Last few milliseconds: spin for precision.
                while self.now() < t:
                    pass
                break
        overshoot = self.now() - t
        if overshoot > WAIT_OVERSHOOT_WARN:
            # Something in the loop took far longer than a look at the HUD
            # should. Worth knowing: a late door click once cost a night.
            log.warning("wait_until(%.2f) ended %.2f s late (slowest HUD look %.2f s)", t, overshoot, slowest_look)

    def night_over(self) -> bool:
        if not self.over:
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
        self._ensure_game()
        self.ctl.face(side)
        self.facing = side

    def press(self, kind: str, side: str) -> None:
        """Click a door or light button (the controller waits out the game's
        click cooldown). Alternates between two spots on the button."""
        self._check_stop()
        if self._ensure_game():
            self.ctl.face(side)   # the view may have moved while the game was away
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

    def door_state(self, side: str) -> str | None:
        """'closed' or 'open', read from the door button's lamp (it changes
        colour the instant the game accepts a click). None if that side is
        not in view."""
        if self.facing != side:
            return None
        return self.vision.door_lamp(self.ctl.window.grab(), side)

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

    def snapshot(self, label: str) -> None:
        """Save the current screen as evidence (e.g. when a click was lost)."""
        self._save_evidence(self.ctl.window.grab(), label)

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
        self._ensure_game()
        ok = self.ctl.camera_up()
        # A freshly raised camera also starts with a burst of static.
        self._switched_at = time.perf_counter()
        return ok

    def camera_down(self) -> bool:
        return self.ctl.camera_down()

    def select_camera(self, camera: str) -> None:
        self._check_stop()
        self._ensure_game()
        if self.ctl.selected_camera != camera:
            self.ctl.mouse.click(*layout.CAMERA_BUTTONS[camera])
            self.ctl.selected_camera = camera
            self._switched_at = time.perf_counter()

    def read_camera(self, camera: str) -> dict:
        """Read a camera picture: {'occupants', 'foxy_stage', 'visible'}."""
        deadline = time.perf_counter() + 0.4
        while time.perf_counter() < deadline:
            frame = self.ctl.window.grab()
            self._note_hud_on(frame)
            if self.vision.current_camera(frame) == camera:
                break
        # Right after switching cameras the picture is covered by a burst of
        # static; wait for it to fade (only needed after a switch).
        settle = CAMERA_SETTLE.get(camera, layout.CAMERA_SWITCH_SECONDS)
        settle_until = getattr(self, "_switched_at", 0.0) + settle
        if time.perf_counter() < settle_until:
            time.sleep(settle_until - time.perf_counter())
        # Classify several frames separately and keep the clearest reading
        # (averaging would mix in any frame still covered by static).
        frames, readings = [], []
        for i in range(CAMERA_FRAMES.get(camera, 2)):
            if i:
                time.sleep(0.03)
            frame = self.ctl.window.grab()
            self._note_hud_on(frame)
            frames.append(frame)
            readings.append(self.vision.read_camera(frame, camera))
        best = max(range(len(readings)), key=lambda i: readings[i].margin)
        reading, frames = readings[best], [frames[best]]
        confident = reading.margin >= CAMERA_MIN_MARGIN.get(camera, 0.5)
        who = "".join(sorted(reading.occupants)) or "-"
        log.info("camera %s: %s foxy=%s margin=%.2f%s", camera, who, reading.foxy_stage, reading.margin,
                 "" if confident else " (not sure)")
        label = f"stage{reading.foxy_stage}" if camera == "1C" else who
        self._save_evidence(frames[-1], f"cam{camera}_{label}_{reading.margin:.1f}")
        return {
            "occupants": set(reading.occupants),
            "foxy_stage": reading.foxy_stage,
            "visible": confident,
        }

    def _note_hud_on(self, frame: np.ndarray) -> None:
        """Read the HUD off a camera frame (if it shows) for the clock."""
        hud = self.vision.read_hud(frame)
        if hud.visible:
            self._note_hud(hud, time.perf_counter())

    def power(self) -> int:
        return self.last_power if self.last_power is not None else 0
