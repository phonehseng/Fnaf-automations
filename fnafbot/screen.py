"""Find the game window and grab frames from it.

All other modules work in *game coordinates*: a 1280 x 720 grid matching
FNAF 1's native resolution, with (0, 0) at the top-left of the game picture.
This module is the only place that knows where that picture is on the real
monitor, so the rest of the bot never has to care about window position or
Windows display scaling.
"""

from __future__ import annotations

import ctypes
import logging
import time

import cv2
import mss
import numpy as np
import win32api
import win32con
import win32gui

from fnafbot import config

log = logging.getLogger(__name__)

# FNAF 1 always renders at 1280 x 720.
GAME_WIDTH = 1280
GAME_HEIGHT = 720

# Virtual-key code for ALT and the flag for "key released" (see focus()).
_VK_MENU = 0x12
_KEYEVENTF_KEYUP = 0x0002

# Without this call, Windows "display scaling" (e.g. 150%) would make every
# coordinate we read or send be off by that factor.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor DPI aware
except (AttributeError, OSError):
    ctypes.windll.user32.SetProcessDPIAware()


class GameWindow:
    """Locates the FNAF window and converts between game and screen pixels."""

    def __init__(self) -> None:
        self.hwnd = 0
        self.left = 0
        self.top = 0
        self.width = GAME_WIDTH
        self.height = GAME_HEIGHT
        self._grabber = mss.MSS()

    # -- locating ---------------------------------------------------------

    def find(self, timeout: float = 30.0) -> None:
        """Wait (up to ``timeout`` seconds) for the game window to appear."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.hwnd = win32gui.FindWindow(None, config.WINDOW_TITLE)
            if self.hwnd:
                self.refresh_position()
                log.info("Found game window at (%d, %d) size %dx%d", self.left, self.top, self.width, self.height)
                return
            time.sleep(0.5)
        raise RuntimeError(f"Game window '{config.WINDOW_TITLE}' not found. Is the game running?")

    def refresh_position(self) -> None:
        """Re-read where the window's drawing area (client area) is on screen."""
        _, _, width, height = win32gui.GetClientRect(self.hwnd)
        self.left, self.top = win32gui.ClientToScreen(self.hwnd, (0, 0))
        self.width, self.height = width, height

    def focus(self) -> None:
        """Bring the game to the front so it receives our mouse input.

        A fullscreen game minimises itself whenever another window steals
        focus (an installer, a notification...). If that happened we restore
        it first, then wait for it to switch back to fullscreen.
        """
        if win32gui.GetForegroundWindow() == self.hwnd and not win32gui.IsIconic(self.hwnd):
            self.refresh_position()
            return  # already in front: do nothing (see the ALT note below)

        # Windows only lets the program that the user last interacted with
        # change the foreground window. Tapping ALT counts as "interacting",
        # which lifts that restriction for our process.
        # Side effect: ALT puts the game in "menu mode", which swallows the
        # next mouse click. That is why this only runs when really needed,
        # and why we send one harmless click afterwards (see below).
        user32 = ctypes.windll.user32
        user32.keybd_event(_VK_MENU, 0, 0, 0)
        user32.keybd_event(_VK_MENU, 0, _KEYEVENTF_KEYUP, 0)

        if win32gui.IsIconic(self.hwnd):
            log.warning("Game window was minimised - restoring it")
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
        try:
            win32gui.SetForegroundWindow(self.hwnd)
        except Exception:  # Windows sometimes refuses; the game usually still works.
            log.debug("SetForegroundWindow was refused", exc_info=True)

        # Wait for the fullscreen mode switch to finish before measuring.
        deadline = time.monotonic() + 5.0
        while win32gui.IsIconic(self.hwnd) and time.monotonic() < deadline:
            time.sleep(0.2)
        time.sleep(0.5)
        self.refresh_position()

        # Cancel the ALT "menu mode" with a click on a spot that does nothing
        # in any game screen: the empty middle of the top edge.
        x, y = self.to_screen(640, 5)
        user32.SetCursorPos(x, y)
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # left button down
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # left button up
        time.sleep(0.05)

    def is_alive(self) -> bool:
        return bool(self.hwnd) and bool(win32gui.IsWindow(self.hwnd))

    def in_front(self) -> bool:
        """True if the game is the active window and not minimised."""
        return win32gui.GetForegroundWindow() == self.hwnd and not win32gui.IsIconic(self.hwnd)

    def display_ok(self) -> bool:
        """True if the game is showing full screen at its native size.

        After switching away and back, the game sometimes comes back in a
        broken "zoomed / quarter" state (on high-DPI laptops the display mode
        and the game disagree about the screen size). In the good state the
        display mode is exactly 1280 x 720 and the game fills it."""
        try:
            mode = win32api.EnumDisplaySettings(None, win32con.ENUM_CURRENT_SETTINGS)
        except Exception:
            return True  # cannot tell; assume fine
        self.refresh_position()
        return (mode.PelsWidth, mode.PelsHeight) == (GAME_WIDTH, GAME_HEIGHT) and \
            (self.left, self.top, self.width, self.height) == (0, 0, GAME_WIDTH, GAME_HEIGHT)

    def ensure_visible(self, picture_ok=None) -> bool:
        """Bring the game back if the user (or another program) switched away.

        ``picture_ok(frame) -> bool`` (optional) checks that the game's
        picture is really right, e.g. that the HUD sits exactly where it
        should. That matters because after a switch-back the game sometimes
        draws its picture shifted by (320, 180) - the "quarter" state - even
        though the window and display mode look correct. Measured fix:
        minimise, wait ~2 s, restore; repeated until the picture is right.

        Returns True if the game had to be brought back (time has passed and
        the screen state may have changed)."""
        if self.in_front() and self.display_ok():
            return False
        log.warning("The game is not in front - bringing it back")
        self.focus()
        time.sleep(1.0)
        self.repair(picture_ok)
        return True

    def repair(self, picture_ok=None) -> bool:
        """Minimise/restore until the game is in front and drawn correctly."""
        def picture_good() -> bool:
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                frame = self.grab()
                if not looks_shifted(frame) and (picture_ok is None or picture_ok(frame)):
                    return True
                time.sleep(0.1)
            return False

        for attempt in range(1, 8):
            if self.in_front() and self.display_ok() and picture_good():
                if attempt > 1:
                    log.info("Game picture fixed after %d minimise/restore cycles", attempt - 1)
                return True
            log.warning("Game picture is wrong (shifted 'quarter' state?) - minimise/restore #%d", attempt)
            win32gui.ShowWindow(self.hwnd, win32con.SW_MINIMIZE)
            time.sleep(2.0)
            self.focus()
            time.sleep(1.0)
        log.error("Could not bring the game back properly")
        return False


    # -- coordinates --------------------------------------------------------

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        """Convert a point in game coordinates (1280x720) to monitor pixels."""
        sx = self.left + x * self.width / GAME_WIDTH
        sy = self.top + y * self.height / GAME_HEIGHT
        return int(round(sx)), int(round(sy))

    # -- capturing -----------------------------------------------------------

    def grab(self) -> np.ndarray:
        """Capture the current game picture as a 1280x720 BGR image.
        (While the game is minimised there is nothing to capture: a black
        picture is returned, which every check treats as "not ready".)"""
        if self.width <= 0 or self.height <= 0 or self.left <= -32000:
            self.refresh_position()
            if self.width <= 0 or self.height <= 0 or self.left <= -32000:
                return np.zeros((GAME_HEIGHT, GAME_WIDTH, 3), np.uint8)
        shot = self._grabber.grab({"left": self.left, "top": self.top, "width": self.width, "height": self.height})
        frame = np.asarray(shot)[:, :, :3]  # mss gives BGRA; drop alpha
        if frame.shape[1] != GAME_WIDTH or frame.shape[0] != GAME_HEIGHT:
            # The game is stretched to another size (e.g. windowed); normalise it.
            frame = cv2.resize(frame, (GAME_WIDTH, GAME_HEIGHT), interpolation=cv2.INTER_AREA)
        return np.ascontiguousarray(frame)


def looks_shifted(frame: np.ndarray) -> bool:
    """The broken "quarter" state: the game draws its picture shifted by
    (320, 180), so the top-left 310 x 170 pixels are pure black while the
    rest of the screen has content. A real office or camera view never has a
    pure-black top-left corner like that (and fully black screens such as
    6 AM are not reported, because they have no content elsewhere either)."""
    corner_black = int(frame[:170, :310].max()) <= 6
    has_content = float(frame[180:, 320:].mean()) > 12
    return corner_black and has_content
