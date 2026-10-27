"""The launcher window: what FNAFBot.exe shows when it is double-clicked.

It does nothing clever itself. It lets a person point at their copy of the
game, choose what to play, and then starts the normal command-line bot
(the same `python -m fnafbot ...` options, see __main__.py) in this console
window, so its live log is visible while it plays.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from fnafbot import config

# Colours for the window (a dark office, a gold accent, like the status panel).
BG = "#16181b"
PANEL = "#202328"
TEXT = "#eceae4"
MUTED = "#9ea3a8"
GOLD = "#f2c33a"
GOOD = "#8fdc8a"
BAD = "#ff6b5e"

# Type: Google Sans, with Google Sans Code for paths and section labels. Both
# ship inside the package (fnafbot/fonts, SIL Open Font License) and are
# loaded for this program only - nothing is installed on the computer. If
# loading fails, Tk quietly falls back to its default font.
FONT_DIR = Path(__file__).resolve().parent / "fonts"
SANS = "Google Sans"
MONO = "Google Sans Code"


def load_fonts() -> None:
    import ctypes
    FR_PRIVATE = 0x10       # visible to this process only, gone when it exits
    for font in ("GoogleSans.ttf", "GoogleSansCode.ttf"):
        try:
            ctypes.windll.gdi32.AddFontResourceExW(str(FONT_DIR / font), FR_PRIVATE, 0)
        except (AttributeError, OSError):
            pass


# What can be played: label shown in the window -> command-line options.
MODES = [
    ("Full campaign: Night 1 - 5, 6th Night, then Custom 20/20/20/20", ["--campaign"]),
    ("New Game: Night 1 until Night 5 is won", ["--new-game"]),
    ("Continue the night the game has saved", ["--continue"]),
    ("6th Night (once unlocked)", ["--sixth"]),
    ("Custom Night with these AI levels (once unlocked):", None),
]


def bot_command(options: list[str]) -> list[str]:
    """The command that runs the bot with these options: the .exe itself
    when packaged, `python -m fnafbot` when run from source."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *options]
    return [sys.executable, "-m", "fnafbot", *options]


def pictures_ready() -> bool:
    """Have the reference pictures been copied out of the game yet?"""
    return config.ASSET_CACHE.is_dir() and any(config.ASSET_CACHE.iterdir())


class Launcher:
    def __init__(self) -> None:
        # Sharp text on scaled (high-DPI) screens instead of a blurry bitmap.
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
        load_fonts()
        self.root = tk.Tk()
        self.root.title("FNAF Bot")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TRadiobutton", background=PANEL, foreground=TEXT, font=(SANS, 10))
        style.configure("TRadiobutton", indicatorbackground="#2b2f35", indicatorforeground=GOLD)
        style.map("TRadiobutton", background=[("active", PANEL)],
                  indicatorbackground=[("selected", GOLD), ("!selected", "#2b2f35")])
        style.configure("TSpinbox", fieldbackground="#2b2f35", foreground=TEXT, arrowcolor=TEXT)

        self.game_path = tk.StringVar(value=str(config.GAME_EXE))
        self.mode = tk.IntVar(value=0)
        self.levels = [tk.IntVar(value=20) for _ in range(4)]
        self.status = tk.StringVar()
        self._build()
        self._refresh()

    # -- layout --------------------------------------------------------------

    def _build(self) -> None:
        pad = {"padx": 18}
        tk.Label(self.root, text="FNAF Bot", bg=BG, fg=TEXT, font=(SANS, 24, "bold")).pack(anchor="w", pady=(10, 0), **pad)
        tk.Label(self.root, text="Plays Five Nights at Freddy's by watching the screen (OpenCV) and using the mouse.",
                 bg=BG, fg=MUTED, font=(SANS, 9)).pack(anchor="w", **pad)

        # 1. Where the game is.
        game = self._section("1  YOUR GAME")
        row = tk.Frame(game, bg=PANEL)
        row.pack(fill="x")
        tk.Entry(row, textvariable=self.game_path, width=58, bg="#2b2f35", fg=TEXT, insertbackground=TEXT,
                 relief="flat", font=(MONO, 9)).pack(side="left", ipady=4)
        tk.Button(row, text="Browse...", command=self._browse, bg="#2b2f35", fg=TEXT, relief="flat",
                  activebackground="#3a3f46", activeforeground=TEXT).pack(side="left", padx=(8, 0), ipadx=6)
        self.game_note = tk.Label(game, bg=PANEL, font=(SANS, 9))
        self.game_note.pack(anchor="w", pady=(6, 0))
        self.game_path.trace_add("write", lambda *_: self._refresh())

        # 2. What to play.
        play = self._section("2  WHAT TO PLAY")
        for index, (label, _) in enumerate(MODES):
            ttk.Radiobutton(play, text=label, variable=self.mode, value=index).pack(anchor="w", pady=0)
        levels = tk.Frame(play, bg=PANEL)
        levels.pack(anchor="w", padx=(24, 0), pady=(4, 0))
        for column, name in enumerate(("Freddy", "Bonnie", "Chica", "Foxy")):
            tk.Label(levels, text=name, bg=PANEL, fg=MUTED, font=(SANS, 9)).grid(row=0, column=column, padx=4)
            ttk.Spinbox(levels, from_=0, to=20, width=4, textvariable=self.levels[column]).grid(row=1, column=column, padx=4)

        # 3. Go.
        go = tk.Frame(self.root, bg=BG)
        go.pack(fill="x", pady=(14, 16), **pad)
        self.start_button = tk.Button(go, text="START", command=self._start, bg=GOLD, fg="#111", relief="flat",
                                      font=(SANS, 12, "bold"), activebackground="#ffd75a", padx=26, pady=0)
        self.start_button.pack(side="left")
        tk.Label(go, text="F8 stops the bot. Keep the mouse still while it plays.",
                 bg=BG, fg=MUTED, font=(SANS, 9), justify="left").pack(side="left", padx=14)
        tk.Label(self.root, textvariable=self.status, bg=BG, fg=GOLD, font=(SANS, 9)).pack(anchor="w", pady=(0, 12), **pad)

    def _section(self, title: str) -> tk.Frame:
        tk.Label(self.root, text=title, bg=BG, fg=GOLD, font=(MONO, 9, "bold")).pack(anchor="w", padx=18, pady=(14, 4))
        frame = tk.Frame(self.root, bg=PANEL, padx=12, pady=10)
        frame.pack(fill="x", padx=18)
        return frame

    # -- actions -------------------------------------------------------------

    def _browse(self) -> None:
        chosen = filedialog.askopenfilename(title="Find FiveNightsatFreddys.exe",
                                            filetypes=[("Five Nights at Freddy's", "FiveNightsatFreddys.exe"),
                                                       ("Programs", "*.exe")])
        if chosen:
            self.game_path.set(str(Path(chosen)))

    def _refresh(self) -> None:
        """Say whether the game was found and whether setup has been done."""
        found = Path(self.game_path.get()).is_file()
        if not found:
            self.game_note.configure(text="Game not found here - use Browse to find FiveNightsatFreddys.exe", fg=BAD)
        elif pictures_ready():
            self.game_note.configure(text="Found, and the reference pictures are ready.", fg=GOOD)
        else:
            self.game_note.configure(text="Found. On the first START the bot copies its reference pictures "
                                          "out of the game (once).", fg=GOOD)
        self.start_button.configure(state="normal" if found else "disabled")

    def _options(self) -> list[str]:
        label, options = MODES[self.mode.get()]
        if options is not None:
            return options
        levels = [max(0, min(20, var.get())) for var in self.levels]
        return ["--custom", *map(str, levels)]

    def _start(self) -> None:
        game = str(Path(self.game_path.get()))
        settings = config.load_settings()
        settings["game_exe"] = game
        config.save_settings(settings)
        env = dict(os.environ, FNAF_EXE=game)
        options = self._options()
        self.start_button.configure(state="disabled")
        self.status.set("Playing - the live log is in the console window. Press F8 to stop.")
        self.root.iconify()
        threading.Thread(target=self._run, args=(options, env), daemon=True).start()

    def _run(self, options: list[str], env: dict) -> None:
        """Set up once if needed, then play; the bot prints to this console."""
        if not pictures_ready():
            print("First run: copying the reference pictures out of your game...")
            subprocess.run(bot_command(["--setup"]), env=env)
        code = subprocess.run(bot_command(options), env=env).returncode
        self.root.after(0, self._finished, code)

    def _finished(self, code: int) -> None:
        self.root.deiconify()
        self._refresh()
        self.status.set("Finished - see the console for each night's result." if code == 0
                        else "The bot stopped with an error - see the console and the logs folder.")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    Launcher().run()
