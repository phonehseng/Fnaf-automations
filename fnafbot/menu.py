"""Starting the game and getting from the title screen into a night.

How nights are chosen (from the game's own title-screen logic, see
docs/GAME_LOGIC.md):

* "Continue" starts the night stored as ``level`` in the save file (1-5).
* "6th Night" needs ``beatgame=1``; "Custom Night" also needs ``beat6=1``.

So to play any night the bot edits the save file (after making a backup),
then clicks the right menu entry. The game reads the save file when the
title screen appears, which is why the save is written *before* the game is
(re)started.
"""

from __future__ import annotations

import configparser
import logging
import shutil
import subprocess
import time
from pathlib import Path

import cv2

from fnafbot import assets, catalog, config, layout
from fnafbot.mouse import Mouse
from fnafbot.screen import GameWindow

log = logging.getLogger(__name__)

PROCESS_NAME = "FiveNightsatFreddys.exe"
BACKUP_FILE = config.PROJECT_ROOT / "cache" / "save_backup.ini"

# Custom Night screen: the left/right arrow buttons for each animatronic and
# the Ready button (game coordinates, measured on the live screen).
CUSTOM_ARROWS = {
    # name: (left arrow, right arrow)
    "freddy": ((134, 495), (300, 495)),
    "bonnie": ((418, 495), (582, 495)),
    "chica": ((702, 495), (865, 495)),
    "foxy": ((980, 495), (1143, 495)),
}
CUSTOM_READY = (1141, 656)

# Repeated clicks on one spot within ~0.5 s become a Windows double-click,
# which the game ignores. Alternating between two spots this far apart
# (still inside the arrow button) keeps every click a single click.
ARROW_CLICK_JITTER = 12

# The easter-egg combination that skips the night (see GAME_LOGIC.md).
FORBIDDEN_CUSTOM_LEVELS = {"freddy": 1, "bonnie": 9, "chica": 8, "foxy": 7}


# ---------------------------------------------------------------------------
# Save file
# ---------------------------------------------------------------------------


def read_save() -> dict[str, str]:
    """Return the save file's values, e.g. {'level': '3', 'lives': '5'}."""
    parser = configparser.ConfigParser()
    if config.SAVE_FILE.exists():
        parser.read(config.SAVE_FILE)
    return dict(parser["freddy"]) if parser.has_section("freddy") else {}


def backup_save() -> None:
    """Copy the save file to cache/save_backup.ini once (never overwritten),
    so the player's real progress can always be restored."""
    if config.SAVE_FILE.exists() and not BACKUP_FILE.exists():
        BACKUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(config.SAVE_FILE, BACKUP_FILE)
        log.info("Backed up the save file to %s", BACKUP_FILE)


def restore_save() -> None:
    """Put the player's original save file back."""
    if BACKUP_FILE.exists():
        shutil.copy2(BACKUP_FILE, config.SAVE_FILE)
        log.info("Restored the original save file")


def write_save(**values: int) -> None:
    """Set keys in the save file (keeping the others), e.g. write_save(level=3)."""
    backup_save()
    current = read_save()
    current.update({key: str(value) for key, value in values.items()})
    config.SAVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = ["[freddy]"] + [f"{key}={value}" for key, value in current.items()]
    config.SAVE_FILE.write_text("\n".join(lines) + "\n", encoding="ascii")


# ---------------------------------------------------------------------------
# Game process
# ---------------------------------------------------------------------------


def is_running() -> bool:
    output = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {PROCESS_NAME}"],
                            capture_output=True, text=True).stdout
    return PROCESS_NAME.lower() in output.lower()


def close_game() -> None:
    if is_running():
        subprocess.run(["taskkill", "/IM", PROCESS_NAME, "/F"], capture_output=True)
        time.sleep(1.5)


def launch_game() -> None:
    """Start the game exe directly (not through Steam: launching via Steam can
    be blocked when the Steam account is in use on another computer)."""
    subprocess.Popen([str(config.GAME_EXE)], cwd=str(config.GAME_EXE.parent))
    log.info("Launched %s", config.GAME_EXE.name)


def wait_for_sprite(window: GameWindow, handle: int, timeout: float = 30.0) -> bool:
    """Wait until one of the game's own text sprites (catalog.py) is on screen."""
    sprite = assets.load(handle)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        score = cv2.matchTemplate(window.grab(), sprite, cv2.TM_CCOEFF_NORMED).max()
        if score > 0.9:
            return True
        time.sleep(0.2)
    return False


def restart_game() -> GameWindow:
    """(Re)start the game so it re-reads the save file; returns its window
    once the title screen is showing (after the start-up warning screen)."""
    close_game()
    launch_game()
    window = GameWindow()
    window.find(timeout=30)
    window.focus()
    if not wait_for_sprite(window, catalog.TITLE_CONTINUE, timeout=30):
        raise RuntimeError("The title screen did not appear")
    time.sleep(0.5)  # let the menu finish fading in
    return window


# ---------------------------------------------------------------------------
# Starting nights
# ---------------------------------------------------------------------------


def start_night(night: int, custom_levels: dict[str, int] | None = None) -> GameWindow:
    """Prepare the save file, restart the game and click into ``night``.

    night 1-5 -> "Continue" with level=night
    night 6   -> "6th Night"
    night 7   -> "Custom Night" with ``custom_levels`` (e.g. all 20)
    """
    if night == 7:
        levels = custom_levels or {"freddy": 20, "bonnie": 20, "chica": 20, "foxy": 20}
        if levels == FORBIDDEN_CUSTOM_LEVELS:
            raise ValueError("1/9/8/7 is the easter-egg code and does not start a night")
        write_save(beatgame=1, beat6=1)
    elif night == 6:
        write_save(beatgame=1)
    else:
        write_save(level=night)

    window = restart_game()
    mouse = Mouse(window)
    if night <= 5:
        mouse.click(*layout.MENU_CONTINUE)
    elif night == 6:
        mouse.click(*layout.MENU_SIXTH_NIGHT)
    else:
        mouse.click(*layout.MENU_CUSTOM_NIGHT)
        if not wait_for_sprite(window, catalog.CUSTOM_READY_BUTTON, timeout=10):
            raise RuntimeError("The Custom Night screen did not appear")
        set_custom_levels(mouse, levels)
        time.sleep(0.3)
        mouse.click(*CUSTOM_READY)
    return window


def set_custom_levels(mouse: Mouse, levels: dict[str, int]) -> None:
    """On the Custom Night screen, click arrows until each AI level matches.

    The game remembers the levels between visits, so we first click the left
    arrow 20 times (reaching 0 from anywhere) and then the right arrow
    ``level`` times. Arrow buttons have no click cooldown.
    """
    for name, level in levels.items():
        left, right = CUSTOM_ARROWS[name]
        for button, count in ((left, 20), (right, level)):
            for i in range(count):
                offset = ARROW_CLICK_JITTER if i % 2 else -ARROW_CLICK_JITTER
                mouse.click(button[0], button[1] + offset)
                time.sleep(0.04)
