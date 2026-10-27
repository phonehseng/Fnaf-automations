"""Paths and user-tunable settings for the FNAF bot.

Everything a person might reasonably want to change without reading the rest
of the code lives here: where the game is installed, where cached data and
logs go, and the hotkey that stops the bot.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Project folders
# ---------------------------------------------------------------------------

# Run from source, the project folder is the one above this package. Run as
# the packaged FNAFBot.exe (PyInstaller sets sys.frozen), the code is
# unpacked to a temporary folder - so cache, logs and settings go next to
# the .exe instead, where they survive between runs.
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Settings chosen in the launcher window (for now just the game's location).
SETTINGS_FILE = PROJECT_ROOT / "fnafbot_settings.json"


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Game installation
# ---------------------------------------------------------------------------

# Default Steam install location. The FNAF_EXE environment variable wins,
# then the path saved by the launcher, then this default.
DEFAULT_GAME_EXE = r"C:\Program Files (x86)\Steam\steamapps\common\Five Nights at Freddy's\FiveNightsatFreddys.exe"
GAME_EXE = Path(os.environ.get("FNAF_EXE") or load_settings().get("game_exe") or DEFAULT_GAME_EXE)

# Title of the game window (used to find it on screen).
WINDOW_TITLE = "Five Nights at Freddy's"

# Note: the bot never reads or writes the game's save file (or any other game
# file) while playing. Nights are chosen through the game's own menus.

# Reference images are extracted from YOUR copy of the game on first run and
# cached here. They are never committed to git (they are the game's artwork).
ASSET_CACHE = PROJECT_ROOT / "cache" / "assets"

# Each run writes a log file here, plus screenshots of anything surprising.
LOG_DIR = PROJECT_ROOT / "logs"

# Small pictures of every doorway decision (for checking the bot's eyes).
EVIDENCE_DIR = LOG_DIR / "doorway"

# ---------------------------------------------------------------------------
# Safety / control
# ---------------------------------------------------------------------------

# Press this key at any time to stop the bot immediately.
STOP_HOTKEY = "f8"

# When True, every decision is printed to the console as well as the log file.
VERBOSE = True
