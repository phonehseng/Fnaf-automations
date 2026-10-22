"""A small always-on-top status panel drawn over the game.

It shows, in plain words, what the bot is doing right now ("Checking Foxy",
"Bonnie at left door - door CLOSED") plus the power, time and what it
believes about each animatronic.

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
import queue
import threading
import tkinter as tk

import win32con
import win32gui

from fnafbot import layout

log = logging.getLogger(__name__)

# Colours: dark translucent panel, readable text, alert colours.
BACKGROUND = "#101010"
TEXT = "#e8e8e8"
ACCENT = "#7fd1ff"
ALERT = "#ff5050"
OPACITY = 0.85


class StatusOverlay:
    """Thread-safe status panel. Call ``show(...)`` from anywhere."""

    def __init__(self) -> None:
        self._updates: queue.Queue[dict] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="overlay", daemon=True)
        self._ready = threading.Event()
        self._thread.start()
        self._ready.wait(timeout=5)

    # -- public API -------------------------------------------------------------

    def show(self, action: str | None = None, status: str | None = None,
             threats: str | None = None, alert: bool = False) -> None:
        """Update the panel. Any argument left as None keeps its old text.

        action  - what the bot is doing this instant (top line)
        status  - night / time / power summary (middle line)
        threats - what the bot believes about each animatronic (bottom line)
        alert   - draw the action line in red (an animatronic is at a door)
        """
        self._updates.put({"action": action, "status": status, "threats": threats, "alert": alert})

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

        font = ("Consolas", 10)
        self._action = tk.Label(root, text="Starting...", fg=ACCENT, bg=BACKGROUND, font=(font[0], 11, "bold"), anchor="w")
        self._status = tk.Label(root, text="", fg=TEXT, bg=BACKGROUND, font=font, anchor="w")
        self._threats = tk.Label(root, text="", fg=TEXT, bg=BACKGROUND, font=font, anchor="w")
        for label in (self._action, self._status, self._threats):
            label.pack(fill="x", padx=6)

        root.update_idletasks()
        self._make_unfocusable(root)
        self._ready.set()
        root.after(30, self._poll)
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

    def _poll(self) -> None:
        """Apply queued updates (runs every 30 ms inside the Tk thread)."""
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
        except queue.Empty:
            pass
        # Fullscreen games sometimes push themselves above "topmost" windows;
        # lifting the panel regularly keeps it visible.
        self._root.lift()
        self._root.after(30, self._poll)
