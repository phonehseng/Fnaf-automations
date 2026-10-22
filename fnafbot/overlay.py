"""A small always-on-top status panel drawn over the game.

It shows, in plain words, what the bot is doing right now ("Checking Foxy",
"Bonnie at left door - door CLOSED") plus the power, time and what it
believes about each animatronic - and a little analog clock of the night:

* the HOUR hand sweeps from 12 (night start) to 6 (6 AM) over the night;
* the MINUTE hand makes one full turn per in-game hour (90 s for 12 AM,
  89 s for every later hour), so the moment an hour ends is easy to see;
* under it, a countdown to the next hour ("2 AM in 37 s").

The clock keeps running between updates: the bot tells the panel the night
time and how fast game time passes, and the panel extrapolates.

Design rules (each one prevents a real problem):

* **Never takes keyboard focus.** A fullscreen game minimises itself when
  another window becomes active, so the panel is created with
  ``WS_EX_NOACTIVATE``.
* **Click-through.** ``WS_EX_TRANSPARENT`` lets mouse clicks fall through to
  the game, in case the cursor ever passes over the panel.
* **Lives in a strip the vision code ignores** (``layout.OVERLAY``), because
  the bot's own screenshots include the panel.
* **Runs in its own thread.** Tkinter needs its own event loop; the bot only
  ever calls :meth:`StatusOverlay.show`, which is thread-safe.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
import tkinter as tk

import win32con
import win32gui

from fnafbot import layout, rules

log = logging.getLogger(__name__)

# Colours: dark translucent panel, readable text, alert colours.
BACKGROUND = "#101010"
TEXT = "#e8e8e8"
DIM = "#8a8a8a"
ACCENT = "#7fd1ff"
ALERT = "#ff5050"
OPACITY = 0.85

CLOCK_SIZE = 56          # pixels; the clock face is drawn inside this square
REDRAW_MS = 30           # how often the panel applies updates and moves the hands


def hour_boundaries() -> list[float]:
    """Night times (game seconds) at which the clock hour changes: 1 AM .. 6 AM."""
    times = [rules.FIRST_HOUR_SECONDS]
    for _ in range(5):
        times.append(times[-1] + rules.HOUR_SECONDS)
    return times


HOUR_STARTS = [0.0] + hour_boundaries()          # 12 AM, 1 AM, ... 6 AM
HOUR_NAMES = ["12 AM", "1 AM", "2 AM", "3 AM", "4 AM", "5 AM", "6 AM"]


def clock_angles(night_time: float) -> tuple[float, float]:
    """(hour hand angle, minute hand angle) in degrees clockwise from 12.

    Hour hand: 0 deg at the night's start, 180 deg (pointing at 6) at 6 AM,
    moving smoothly in between. Minute hand: one full turn per in-game hour.
    """
    t = max(0.0, min(night_time, rules.NIGHT_SECONDS))
    hour_angle = 180.0 * t / rules.NIGHT_SECONDS
    index = max(i for i, start in enumerate(HOUR_STARTS) if start <= t)
    if index >= 6:                                   # 6 AM reached: hands rest
        return 180.0, 0.0
    length = HOUR_STARTS[index + 1] - HOUR_STARTS[index]
    minute_angle = 360.0 * (t - HOUR_STARTS[index]) / length
    return hour_angle, minute_angle


def countdown_text(night_time: float) -> str:
    """'2 AM in 37 s' - the next hour and how long until it."""
    t = max(0.0, night_time)
    for name, start in zip(HOUR_NAMES[1:], HOUR_STARTS[1:]):
        if t < start:
            return f"{name} in {start - t:.0f} s"
    return "6 AM"


class StatusOverlay:
    """Thread-safe status panel. Call ``show(...)`` from anywhere."""

    def __init__(self) -> None:
        self._updates: queue.Queue[dict] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="overlay", daemon=True)
        self._ready = threading.Event()
        # Night clock as last told by the bot, for extrapolating between updates.
        self._night_time: float | None = None
        self._rate = 1.0                 # game seconds per real second
        self._told_at = 0.0              # perf_counter() when _night_time was set
        self._thread.start()
        self._ready.wait(timeout=5)

    # -- public API -------------------------------------------------------------

    def show(self, action: str | None = None, status: str | None = None,
             threats: str | None = None, alert: bool = False,
             night_time: float | None = None, rate: float = 1.0) -> None:
        """Update the panel. Any text argument left as None keeps its old text.

        action     - what the bot is doing this instant (top line)
        status     - night / time / power summary (middle line)
        threats    - what the bot believes about each animatronic (bottom line)
        alert      - draw the action line in red (an animatronic is at a door)
        night_time - seconds into the night (game seconds); None hides the clock
        rate       - how many game seconds pass per real second (to keep the
                     hands moving between updates)
        """
        self._updates.put({"action": action, "status": status, "threats": threats, "alert": alert,
                           "night_time": night_time, "rate": rate, "told_at": time.perf_counter()})

    def close(self) -> None:
        self._updates.put({"quit": True})

    # -- Tk thread ----------------------------------------------------------------

    def _run(self) -> None:
        try:
            self._root = root = tk.Tk()
        except tk.TclError:
            log.exception("Could not create the status overlay; continuing without it")
            self._ready.set()
            return
        box = layout.OVERLAY
        root.overrideredirect(True)            # no title bar or border
        root.attributes("-topmost", True)
        root.attributes("-alpha", OPACITY)
        root.configure(bg=BACKGROUND)
        root.geometry(f"{box.x1 - box.x0}x{box.y1 - box.y0}+{box.x0}+{box.y0}")

        # Left: the clock face. Middle: hour name + countdown. Right: the text.
        self._clock = tk.Canvas(root, width=CLOCK_SIZE, height=CLOCK_SIZE, bg=BACKGROUND,
                                highlightthickness=0)
        self._clock.pack(side="left", padx=(6, 2), pady=4)
        middle = tk.Frame(root, bg=BACKGROUND)
        middle.pack(side="left", padx=(0, 8))
        small = ("Consolas", 9)
        self._hour = tk.Label(middle, text="--", fg=TEXT, bg=BACKGROUND, font=("Consolas", 12, "bold"), anchor="w")
        self._countdown = tk.Label(middle, text="", fg=DIM, bg=BACKGROUND, font=small, anchor="w")
        self._hour.pack(fill="x")
        self._countdown.pack(fill="x")

        text_column = tk.Frame(root, bg=BACKGROUND)
        text_column.pack(side="left", fill="both", expand=True)
        font = ("Consolas", 10)
        self._action = tk.Label(text_column, text="Starting...", fg=ACCENT, bg=BACKGROUND,
                                font=(font[0], 11, "bold"), anchor="w")
        self._status = tk.Label(text_column, text="", fg=TEXT, bg=BACKGROUND, font=font, anchor="w")
        self._threats = tk.Label(text_column, text="", fg=TEXT, bg=BACKGROUND, font=font, anchor="w")
        for label in (self._action, self._status, self._threats):
            label.pack(fill="x", padx=2)

        self._draw_face()
        root.update_idletasks()
        self._make_unfocusable(root)
        self._ready.set()
        root.after(REDRAW_MS, self._poll)
        root.mainloop()

    @staticmethod
    def _make_unfocusable(root: tk.Tk) -> None:
        """Add the Windows styles that stop the panel stealing focus or clicks."""
        hwnd = win32gui.GetParent(root.winfo_id()) or root.winfo_id()
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        style |= (win32con.WS_EX_NOACTIVATE | win32con.WS_EX_TRANSPARENT
                  | win32con.WS_EX_LAYERED | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_TOPMOST)
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style)
        # Re-assert "always on top" without activating the window.
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)

    # -- the clock ----------------------------------------------------------------

    def _draw_face(self) -> None:
        """The static part: rim, twelve tick marks and a '6' where the night ends."""
        c = self._clock
        r = CLOCK_SIZE / 2
        c.create_oval(2, 2, CLOCK_SIZE - 2, CLOCK_SIZE - 2, outline=DIM, width=1)
        for i in range(12):
            angle = math.radians(i * 30)
            inner = r - (6 if i % 3 == 0 else 3)
            c.create_line(r + inner * math.sin(angle), r - inner * math.cos(angle),
                          r + (r - 3) * math.sin(angle), r - (r - 3) * math.cos(angle),
                          fill=DIM if i % 3 else TEXT, width=1)
        c.create_text(r, r + r * 0.55, text="6", fill=DIM, font=("Consolas", 7))
        # The hands are redrawn every poll; create them once and move them.
        self._hour_hand = c.create_line(r, r, r, r, fill=TEXT, width=3, capstyle="round")
        self._minute_hand = c.create_line(r, r, r, r, fill=ACCENT, width=1)
        c.create_oval(r - 2, r - 2, r + 2, r + 2, fill=TEXT, outline=TEXT)

    def _move_hands(self, night_time: float | None) -> None:
        c = self._clock
        r = CLOCK_SIZE / 2
        if night_time is None:
            c.coords(self._hour_hand, r, r, r, r - r * 0.5)
            c.coords(self._minute_hand, r, r, r, r - r * 0.8)
            self._hour.configure(text="--")
            self._countdown.configure(text="")
            return
        hour_angle, minute_angle = clock_angles(night_time)
        for item, angle, length in ((self._hour_hand, hour_angle, r * 0.5),
                                    (self._minute_hand, minute_angle, r * 0.8)):
            a = math.radians(angle)
            c.coords(item, r, r, r + length * math.sin(a), r - length * math.cos(a))
        self._hour.configure(text=hour_name(night_time))
        self._countdown.configure(text=countdown_text(night_time))

    # -- updates --------------------------------------------------------------------

    def _poll(self) -> None:
        """Apply queued updates and move the hands (every REDRAW_MS, in the Tk thread)."""
        try:
            while True:
                update = self._updates.get_nowait()
                if update.get("quit"):
                    self._root.destroy()
                    return
                if update["action"] is not None:
                    self._action.configure(text=update["action"], fg=ALERT if update["alert"] else ACCENT)
                if update["status"] is not None:
                    self._status.configure(text=update["status"])
                if update["threats"] is not None:
                    self._threats.configure(text=update["threats"])
                self._night_time = update["night_time"]
                self._rate = update["rate"]
                self._told_at = update["told_at"]
        except queue.Empty:
            pass
        if self._night_time is None:
            self._move_hands(None)
        else:
            elapsed = time.perf_counter() - self._told_at
            self._move_hands(self._night_time + elapsed * self._rate)
        # Fullscreen games sometimes push themselves above "topmost" windows;
        # lifting the panel regularly keeps it visible.
        self._root.lift()
        self._root.after(REDRAW_MS, self._poll)


def hour_name(night_time: float) -> str:
    """'12 AM' .. '6 AM' for a night time in game seconds."""
    index = max(i for i, start in enumerate(HOUR_STARTS) if start <= max(0.0, night_time))
    return HOUR_NAMES[index]
