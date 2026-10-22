"""The bot's "hands and eyes": every in-game action, done as fast as possible.

The strategy (strategy.py) decides WHAT to do; this module knows HOW to do it
on the real game: where to move the mouse, how long the game takes to react,
and how to confirm that an action really happened.

Two rules shape every method here:

1. **Danger first.** When a light check reveals Bonnie or Chica, the door
   button directly above the light is clicked *before anything else* (even
   before switching the light off). The mouse is already on that side of the
   office, so closing takes about 30 ms.
2. **Power is precious.** Lights and the camera each add one usage bar while
   on, so they are switched off the moment the bot has seen what it needs.

The controller also remembers the state it has set (doors, camera, pan) so
the strategy can ask "is the left door closed?" without looking.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import cv2
import numpy as np

from fnafbot import layout
from fnafbot.mouse import Mouse
from fnafbot.screen import GameWindow
from fnafbot.vision import CameraReading, Hud, Vision

log = logging.getLogger(__name__)

LEFT, RIGHT = "left", "right"

# How bright (0-255 gray) the doorway area must be for a frame to count as
# "light on". The hall lights flicker off for single frames even while on,
# so dark frames are skipped rather than trusted.
LIT_THRESHOLD = 11.0

# Longest we wait for a lit frame before giving up on a light check.
LIGHT_TIMEOUT = 0.25

# Number of lit frames averaged for a doorway decision (reduces flicker noise).
LIT_FRAMES_WANTED = 2

# Frames averaged per camera reading (TV static changes every frame).
CAMERA_FRAMES = 2

# After ANY door or light click the game ignores all door/light clicks for
# 10 frames (event [95] in docs/GAME_LOGIC.md): 10 / 60 s = 0.167 s. We wait
# a little longer to be safe against frame-timing jitter.
BUTTON_COOLDOWN = 0.19


@dataclass
class DoorwayCheck:
    """Result of switching a hall light on and looking."""

    side: str
    occupied: bool          # Bonnie (left) / Chica (right) seen
    certain: bool           # False if the light never came on or the view was unclear
    closed_door: bool       # True if we closed the door because of what we saw


class Controller:
    """Performs actions on the live game and reports what it saw."""

    def __init__(self, window: GameWindow, vision: Vision) -> None:
        self.window = window
        self.mouse = Mouse(window)
        self.vision = vision

        # What we believe the game's state is (set by our own actions).
        self.door_closed = {LEFT: False, RIGHT: False}
        self.camera_is_up = False
        self.selected_camera = "1A"   # the game starts on the Show Stage camera
        self.side_in_view: str | None = None

        # Latest frame and HUD reading, refreshed by grab().
        self.frame: np.ndarray | None = None
        self.hud = Hud()

        # When the last door/light button was clicked (see BUTTON_COOLDOWN).
        self._last_button_click = 0.0

    def press(self, button: tuple[int, int]) -> float:
        """Click a door or light button, first waiting out the game's click
        cooldown so the click is never silently ignored. Returns the time
        (time.perf_counter) at which the click was sent."""
        wait = self._last_button_click + BUTTON_COOLDOWN - time.perf_counter()
        if wait > 0:
            time.sleep(wait)
        self.mouse.click(*button)
        self._last_button_click = time.perf_counter()
        return self._last_button_click

    # ------------------------------------------------------------------
    # Looking
    # ------------------------------------------------------------------

    def grab(self) -> np.ndarray:
        """Take a fresh screenshot and re-read the HUD from it."""
        self.frame = self.window.grab()
        hud = self.vision.read_hud(self.frame)
        if hud.visible:
            self.hud = hud
        return self.frame

    def night_in_progress(self) -> bool:
        """True while the office/camera HUD is on screen."""
        return self.vision.hud_visible(self.grab())

    # ------------------------------------------------------------------
    # Office: panning, lights, doors
    # ------------------------------------------------------------------

    def face(self, side: str) -> None:
        """Turn the office view fully to ``side`` so its buttons are clickable."""
        if self.camera_is_up or self.camera_showing():
            if not self.camera_is_up:
                log.warning("Monitor still showing when turning %s - lowering it first", side)
            self.camera_down()
        target_pan = 0 if side == LEFT else layout.MAX_PAN
        self.mouse.move(layout.PAN_LEFT_X if side == LEFT else layout.PAN_RIGHT_X, 400)
        if self.side_in_view == side:
            return
        deadline = time.perf_counter() + layout.FULL_PAN_SECONDS + 0.3
        while time.perf_counter() < deadline:
            if abs(self.vision.office_pan(self.window.grab()) - target_pan) <= 8:
                break
            time.sleep(0.01)
        self.side_in_view = side

    def set_door(self, side: str, closed: bool) -> None:
        """Close or open a door (no-op if it is already in that state)."""
        if self.door_closed[side] == closed:
            return
        self.face(side)
        self.press(layout.LEFT_DOOR_BUTTON if side == LEFT else layout.RIGHT_DOOR_BUTTON)
        self.door_closed[side] = closed
        log.info("%s door %s", side, "CLOSED" if closed else "opened")

    def verify_door(self, side: str) -> None:
        """Read the door button colour and fix our belief if it disagrees.
        Only possible while facing that side."""
        if self.side_in_view != side:
            return
        lamp = self.vision.door_lamp(self.window.grab(), side)
        if lamp is not None and (lamp == "closed") != self.door_closed[side]:
            log.warning("%s door is actually %s - correcting belief", side, lamp)
            self.door_closed[side] = lamp == "closed"

    def check_doorway(self, side: str) -> DoorwayCheck:
        """Flash the hall light on ``side``; if Bonnie/Chica is there, close the
        door immediately. The light is on for only ~0.1 s (one usage bar)."""
        self.face(side)
        light = layout.LEFT_LIGHT_BUTTON if side == LEFT else layout.RIGHT_LIGHT_BUTTON
        door = layout.LEFT_DOOR_BUTTON if side == LEFT else layout.RIGHT_DOOR_BUTTON
        look = self.vision.bonnie_at_left_door if side == LEFT else self.vision.chica_at_right_window

        self.press(light)
        lit_frames = self._collect_lit_frames(side)

        occupied, certain = False, False
        if lit_frames:
            frame = lit_frames[0] if len(lit_frames) == 1 else np.mean(lit_frames, axis=0).astype(np.uint8)
            occupied, margin = look(frame)
            certain = margin > 2.0

        closed_now = False
        if occupied and not self.door_closed[side]:
            # DANGER FIRST: the door button is right above the light button.
            # press() waits only for the game's 0.17 s click cooldown.
            self.press(door)
            self.door_closed[side] = True
            closed_now = True
            log.info("%s at the %s door -> door CLOSED", "Bonnie" if side == LEFT else "Chica", side)

        # Light off again (saves power). A different spot on the same button,
        # so Windows does not merge the two clicks into a double-click.
        self.press(layout.LEFT_LIGHT_BUTTON_OFF if side == LEFT else layout.RIGHT_LIGHT_BUTTON_OFF)
        self.mouse.move(layout.PAN_LEFT_X if side == LEFT else layout.PAN_RIGHT_X, 400)
        return DoorwayCheck(side, occupied, certain, closed_now)

    def _collect_lit_frames(self, side: str) -> list[np.ndarray]:
        """Grab frames until we have a couple where the light is actually on."""
        region = (slice(150, 600), slice(0, 300)) if side == LEFT else (slice(150, 600), slice(980, 1280))
        frames: list[np.ndarray] = []
        deadline = time.perf_counter() + LIGHT_TIMEOUT
        while time.perf_counter() < deadline and len(frames) < LIT_FRAMES_WANTED:
            frame = self.window.grab()
            if float(cv2.cvtColor(frame[region], cv2.COLOR_BGR2GRAY).mean()) > LIT_THRESHOLD:
                frames.append(frame)
        return frames

    # ------------------------------------------------------------------
    # Camera monitor
    # ------------------------------------------------------------------

    def _swipe_camera_bar(self) -> None:
        """Re-arm, then touch the bar (see the CAMERA_REARM note in layout.py)."""
        self.mouse.move(*layout.CAMERA_REARM)
        time.sleep(layout.CAMERA_HOVER_SECONDS)
        self.mouse.move(*layout.CAMERA_TRIGGER)
        time.sleep(layout.CAMERA_HOVER_SECONDS)

    def camera_showing(self) -> bool:
        """True if the screen currently shows a camera (its room label is visible)."""
        return self.vision.current_camera(self.window.grab()) is not None

    def camera_up(self) -> bool:
        """Raise the monitor; True once a camera picture is really showing.

        Every flip is checked on screen and retried, because a flip the game
        did not register would leave the bot clicking an office it cannot
        see (doors and lights do not work while the monitor is up)."""
        for attempt in range(3):
            if self.camera_showing():
                self.camera_is_up = True
                return True
            self._swipe_camera_bar()
            deadline = time.perf_counter() + 1.0
            while time.perf_counter() < deadline:
                camera = self.vision.current_camera(self.window.grab())
                if camera:
                    self.camera_is_up = True
                    self.side_in_view = None
                    self.selected_camera = camera
                    return True
            log.warning("Monitor did not come up (attempt %d)", attempt + 1)
        return False

    def camera_down(self) -> bool:
        """Lower the monitor; True once the office is showing again (verified)."""
        for attempt in range(3):
            if not self.camera_showing():
                break
            self._swipe_camera_bar()
            deadline = time.perf_counter() + 0.5
            while time.perf_counter() < deadline and self.camera_showing():
                pass
            if not self.camera_showing():
                break
            log.warning("Monitor did not go down (attempt %d)", attempt + 1)
        else:
            return False
        self.camera_is_up = False
        self.mouse.move(*layout.CAMERA_REARM)  # dead zone: the view stays still
        return True

    def view(self, camera: str) -> CameraReading:
        """Show ``camera`` on the monitor (raising it if needed) and read it."""
        self.camera_up()
        if self.selected_camera != camera:
            self.mouse.click(*layout.CAMERA_BUTTONS[camera])
            deadline = time.perf_counter() + 0.5
            while time.perf_counter() < deadline:
                if self.vision.current_camera(self.window.grab()) == camera:
                    break
            self.selected_camera = camera
            time.sleep(layout.CAMERA_SWITCH_SECONDS)  # let the switch static fade
        frames = [self.window.grab() for _ in range(CAMERA_FRAMES)]
        self.frame = frames[-1]
        return self.vision.read_camera(frames, camera)

    def select_camera_blind(self, camera: str) -> None:
        """Click a camera button without waiting to read it (monitor must be up)."""
        if self.camera_is_up and self.selected_camera != camera:
            self.mouse.click(*layout.CAMERA_BUTTONS[camera])
            self.selected_camera = camera

    # ------------------------------------------------------------------
    # Idle
    # ------------------------------------------------------------------

    def rest(self) -> None:
        """Park the mouse in the dead zone so the view stops panning."""
        if not self.camera_is_up:
            self.mouse.move(layout.PAN_STILL_X, 400)
