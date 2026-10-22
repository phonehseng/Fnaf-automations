"""Starting the game and getting from the title screen into a night.

The bot only uses the game the way a player does. It never reads or edits
the save file or any other game file; it looks at the screen and clicks:

* "New Game"     -> Night 1 (the game resets its own progress)
* "Continue"     -> whatever night the game has saved (1-5)
* "6th Night"    -> only shown once the game has been beaten
* "Custom Night" -> only shown once night 6 has been beaten; AI levels are
                    set with the arrow buttons on the Custom Night screen

Which entries exist is read from the title screen itself (the game's own
"6th Night" / "Custom Night" text sprites, see catalog.py).

After a won night (1-4) the game goes straight on to the next night by
itself; after night 5 it shows the ending and returns to the title screen.
"""

from __future__ import annotations

import logging
import subprocess
import time

import cv2

from fnafbot import assets, catalog, config, layout
from fnafbot.mouse import Mouse
from fnafbot.screen import GameWindow, looks_shifted

log = logging.getLogger(__name__)

PROCESS_NAME = "FiveNightsatFreddys.exe"

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

# The easter-egg combination that skips the night (see docs/GAME_LOGIC.md).
FORBIDDEN_CUSTOM_LEVELS = {"freddy": 1, "bonnie": 9, "chica": 8, "foxy": 7}


class MenuError(RuntimeError):
    """The expected screen did not appear, or a menu entry is not unlocked."""


# ---------------------------------------------------------------------------
# Game process
# ---------------------------------------------------------------------------


def is_running() -> bool:
    output = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {PROCESS_NAME}"],
                            capture_output=True, text=True).stdout
    return PROCESS_NAME.lower() in output.lower()


def launch_game() -> None:
    """Start the game exe directly (not through Steam: launching via Steam can
    be blocked when the Steam account is in use on another computer)."""
    subprocess.Popen([str(config.GAME_EXE)], cwd=str(config.GAME_EXE.parent))
    log.info("Launched %s", config.GAME_EXE.name)


def close_game() -> None:
    """Close the game process (used only to get back to a clean title screen)."""
    if is_running():
        subprocess.run(["taskkill", "/IM", PROCESS_NAME, "/F"], capture_output=True)
        time.sleep(2.0)


def open_game() -> GameWindow:
    """Get the game to its title screen and bring it to the front.

    If the game is already in the middle of something (e.g. a night that
    started before the bot did), the bot cannot know when that night began,
    and its whole timing depends on that. So it restarts the game instead."""
    if is_running():
        window = GameWindow()
        window.find(timeout=10)
        window.focus()
        if wait_for_sprite(window, catalog.TITLE_CONTINUE, timeout=4):
            return window
        log.info("The game is not on its title screen - restarting it")
        close_game()
    launch_game()
    window = GameWindow()
    window.find(timeout=30)
    window.focus()
    return window


# ---------------------------------------------------------------------------
# Reading the screen
# ---------------------------------------------------------------------------


def sprite_visible(window: GameWindow, handle: int, threshold: float = 0.9) -> bool:
    """Is one of the game's own text sprites (catalog.py) on screen?"""
    score = cv2.matchTemplate(window.grab(), assets.load(handle), cv2.TM_CCOEFF_NORMED).max()
    return bool(score > threshold)


def wait_for_sprite(window: GameWindow, handle: int, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sprite_visible(window, handle):
            return True
        time.sleep(0.2)
    return False


def on_title_screen(window: GameWindow) -> bool:
    return sprite_visible(window, catalog.TITLE_CONTINUE)


def unlocked(window: GameWindow) -> dict[str, bool]:
    """Which extra menu entries the title screen shows right now.

    Several frames are checked: the title's rolling static band hides a
    line of text for a few frames at a time, and one unlucky frame once
    made the bot believe the 6th Night was not unlocked."""
    found = {"sixth": False, "custom": False}
    for _ in range(6):
        found["sixth"] = found["sixth"] or sprite_visible(window, catalog.TITLE_SIXTH_NIGHT)
        found["custom"] = found["custom"] or sprite_visible(window, catalog.TITLE_CUSTOM_NIGHT)
        time.sleep(0.12)
    return found


# ---------------------------------------------------------------------------
# Menu actions (call these while the title screen is showing)
# ---------------------------------------------------------------------------


def choose(window: GameWindow, entry: str, custom_levels: dict[str, int] | None = None) -> None:
    """Click a title-screen entry: 'new', 'continue', 'sixth' or 'custom'."""
    title_ok = lambda frame: cv2.matchTemplate(  # noqa: E731 - small inline check
        frame, assets.load(catalog.TITLE_CONTINUE), cv2.TM_CCOEFF_NORMED).max() > 0.9
    window.ensure_visible(picture_ok=title_ok)
    if looks_shifted(window.grab()):
        window.repair(picture_ok=title_ok)
    if not wait_for_sprite(window, catalog.TITLE_CONTINUE, timeout=40):
        raise MenuError("The title screen is not showing")
    time.sleep(0.5)  # let the menu finish fading in
    available = unlocked(window)
    if entry in ("sixth", "custom") and not available[entry]:
        raise MenuError(f"'{entry}' is not unlocked in the game yet - win the earlier nights first")
    mouse = Mouse(window)
    target = {
        "new": layout.MENU_NEW_GAME,
        "continue": layout.MENU_CONTINUE,
        "sixth": layout.MENU_SIXTH_NIGHT,
        "custom": layout.MENU_CUSTOM_NIGHT,
    }[entry]
    log.info("Menu: %s", entry)
    mouse.click(*target)
    if entry != "custom":
        # The title text stays visible while the screen fades out; wait for
        # it to go so the caller does not mistake it for a new title screen.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and sprite_visible(window, catalog.TITLE_CONTINUE):
            time.sleep(0.2)
    if entry == "custom":
        levels = custom_levels or {"freddy": 20, "bonnie": 20, "chica": 20, "foxy": 20}
        if levels == FORBIDDEN_CUSTOM_LEVELS:
            raise MenuError("1/9/8/7 is the easter-egg code and does not start a night")
        if not wait_for_sprite(window, catalog.CUSTOM_READY_BUTTON, timeout=10):
            raise MenuError("The Custom Night screen did not appear")
        set_custom_levels(mouse, levels)
        time.sleep(0.3)
        mouse.click(*CUSTOM_READY)


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
