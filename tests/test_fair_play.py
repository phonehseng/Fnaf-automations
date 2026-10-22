"""Guard rails: the bot must play like a player.

While playing, the bot may only look at the screen and use the mouse. It must
never read or modify the game's files (save file, executable, memory) to get
information or progress. These tests scan the source code so a future change
cannot quietly break that rule.
"""

from __future__ import annotations

from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "fnafbot"

# Only the one-time setup step (assets.py) may open the game executable, and
# only to copy out pictures; config.py defines its path, menu.py launches it.
ALLOWED_TO_MENTION_GAME_EXE = {"assets.py", "config.py", "menu.py"}


def _sources():
    for path in sorted(PACKAGE.glob("*.py")):
        yield path.name, path.read_text(encoding="utf-8")


def test_no_code_touches_the_save_file():
    for name, text in _sources():
        assert "MMFApplications" not in text, f"{name} refers to the game's save folder"
        assert "SAVE_FILE" not in text, f"{name} refers to the save file"


def test_only_setup_reads_the_game_exe():
    for name, text in _sources():
        if "GAME_EXE" in text:
            assert name in ALLOWED_TO_MENTION_GAME_EXE, f"{name} uses the game exe"


def test_menu_only_launches_the_exe():
    import re

    text = (PACKAGE / "menu.py").read_text(encoding="utf-8")
    assert "read_bytes" not in text and "write_text" not in text
    # The built-in open() (but not e.g. subprocess.Popen or open_game).
    assert not re.search(r"(?<![\w.])open\(", text), "menu.py opens a file"


def test_no_memory_reading():
    for name, text in _sources():
        for forbidden in ("ReadProcessMemory", "OpenProcess", "pymem"):
            assert forbidden not in text, f"{name} uses {forbidden}"
