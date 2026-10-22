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
        # Windows only lets the program that the user last interacted with
        # change the foreground window. Tapping ALT counts as "interacting",
        # which lifts that restriction for our process.
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

    def is_alive(self) -> bool:
        return bool(self.hwnd) and bool(win32gui.IsWindow(self.hwnd))

    # -- coordinates --------------------------------------------------------

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        """Convert a point in game coordinates (1280x720) to monitor pixels."""
        sx = self.left + x * self.width / GAME_WIDTH
        sy = self.top + y * self.height / GAME_HEIGHT
        return int(round(sx)), int(round(sy))

    # -- capturing -----------------------------------------------------------

    def grab(self) -> np.ndarray:
        """Capture the current game picture as a 1280x720 BGR image."""
        shot = self._grabber.grab({"left": self.left, "top": self.top, "width": self.width, "height": self.height})
        frame = np.asarray(shot)[:, :, :3]  # mss gives BGRA; drop alpha
        if frame.shape[1] != GAME_WIDTH or frame.shape[0] != GAME_HEIGHT:
            # The game is stretched to another size (e.g. windowed); normalise it.
            frame = cv2.resize(frame, (GAME_WIDTH, GAME_HEIGHT), interpolation=cv2.INTER_AREA)
        return np.ascontiguousarray(frame)
