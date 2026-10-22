"""Paths and user-tunable settings for the FNAF bot.

Everything a person might reasonably want to change without reading the rest
of the code lives here: where the game is installed, where cached data and
logs go, and the hotkey that stops the bot.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Game installation
# ---------------------------------------------------------------------------

# Default Steam install location. Override with the FNAF_EXE environment
# variable if the game lives somewhere else.
GAME_EXE = Path(
    os.environ.get(
        "FNAF_EXE",
        r"C:\Program Files (x86)\Steam\steamapps\common\Five Nights at Freddy's\FiveNightsatFreddys.exe",
    )
)

# Title of the game window (used to find it on screen).
WINDOW_TITLE = "Five Nights at Freddy's"

# Note: the bot never reads or writes the game's save file (or any other game
# file) while playing. Nights are chosen through the game's own menus.

# ---------------------------------------------------------------------------
# Project folders
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

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
