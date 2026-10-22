"""Low-level mouse control using the Windows API directly.

We avoid libraries like pyautogui here because they add built-in pauses
(pyautogui waits 0.1 s after every call by default). In FNAF a tenth of a
second can be the difference between closing a door in time or not, so every
action here is as fast as Windows allows.
"""

from __future__ import annotations

import ctypes
import time

from fnafbot.screen import GameWindow

_user32 = ctypes.windll.user32

# Flags for the legacy mouse_event API (simple and reliable for left clicks).
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004

# How long the button is held for a click. The game polls input once per
# frame - usually 16 ms apart, but gaps of up to 35 ms were measured live
# (tools/measure_fps.py), and a 20 ms press could fall entirely inside such
# a gap: the game then never saw it. A door click lost that way cost a
# night (docs/DEVLOG.md), so the press now lasts three frames.
CLICK_HOLD_SECONDS = 0.05

# Small pause after moving before clicking, so the game sees the cursor at the
# new position before it sees the button press.
MOVE_SETTLE_SECONDS = 0.01


class Mouse:
    """Moves and clicks the mouse in game coordinates."""

    def __init__(self, window: GameWindow) -> None:
        self.window = window
        self.x = 0.0  # last position we moved to, in game coordinates
        self.y = 0.0

    def move(self, x: float, y: float) -> None:
        """Teleport the cursor to (x, y) in game coordinates."""
        sx, sy = self.window.to_screen(x, y)
        _user32.SetCursorPos(sx, sy)
        self.x, self.y = x, y

    def click(self, x: float, y: float) -> None:
        """Move to (x, y) and left-click."""
        self.move(x, y)
        time.sleep(MOVE_SETTLE_SECONDS)
        _user32.mouse_event(_MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(CLICK_HOLD_SECONDS)
        _user32.mouse_event(_MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def glide(self, x0: float, y0: float, x1: float, y1: float, seconds: float, steps: int = 6) -> None:
        """Move in a short straight line. Used to "swipe" over the camera bar,
        because the game only flips the monitor when the cursor *enters* the bar."""
        for i in range(steps + 1):
            t = i / steps
            self.move(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
            time.sleep(seconds / steps)
