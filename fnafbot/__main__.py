"""Run the FNAF bot.

One-time setup (before the first run; never during play):
    python -m fnafbot --setup                 # copy reference pictures out of your installed game

Playing (the bot only uses the game's own menus, like a player):
    python -m fnafbot --new-game              # New Game: play night 1 onwards until night 5 is won
    python -m fnafbot --continue              # Continue from the night the game has saved
    python -m fnafbot --continue --nights 2   # ... but stop after two nights
    python -m fnafbot --sixth                 # 6th Night (once the game has unlocked it)
    python -m fnafbot --custom 20 20 20 20    # Custom Night (once unlocked): Freddy Bonnie Chica Foxy
    python -m fnafbot --campaign              # New Game -> nights 1-5 -> 6th Night -> Custom 20/20/20/20

Press F8 at any time to stop the bot. Logs go to logs/ (doorway pictures to logs/doorway/).
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from datetime import datetime

import cv2

from fnafbot import assets, config, menu, narrator, rules
from fnafbot.body import CAPTURE_LATENCY, RealBody, StopRequested
from fnafbot.brain import Brain, Status
from fnafbot.controller import Controller
from fnafbot.overlay import StatusOverlay
from fnafbot.screen import GameWindow, looks_shifted
from fnafbot.vision import Vision

log = logging.getLogger("fnafbot")

# How long to wait for the next screen (a night or the title) before giving up.
SCREEN_TIMEOUT = 120.0
# A completely black game window for this long means the game is stuck.
BLACK_SCREEN_RESTART = 20.0


def setup_logging() -> str:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = config.LOG_DIR / f"{datetime.now():%Y-%m-%d_%H-%M-%S}.log"
    handlers: list[logging.Handler] = [logging.FileHandler(path, encoding="utf-8")]
    if config.VERBOSE:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", handlers=handlers)
    return str(path)


def watch_stop_key() -> threading.Event:
    """Return an Event that becomes set when the stop hotkey is pressed."""
    stop = threading.Event()
    try:
        import keyboard
        keyboard.add_hotkey(config.STOP_HOTKEY, stop.set)
    except Exception:  # the keyboard hook can fail without admin rights; Ctrl+C still works
        log.warning("Could not register the %s stop hotkey; use Ctrl+C instead", config.STOP_HOTKEY)
    return stop


class Session:
    """Plays nights back to back, following the game's own screens."""

    def __init__(self, menu_plan: list[tuple[str, dict | None]], max_nights: int | None) -> None:
        self.menu_plan = list(menu_plan)       # e.g. [("new", None), ("sixth", None)]
        self.max_nights = max_nights
        self.vision = Vision()
        self.overlay = StatusOverlay()
        self.stop = watch_stop_key()
        self.window: GameWindow | None = None
        self.custom_levels: dict | None = None
        self.results: list[tuple[str, bool, int]] = []

    # -- main loop -----------------------------------------------------------

    def run(self) -> None:
        self.window = menu.open_game()
        while self.max_nights is None or len(self.results) < self.max_nights:
            screen, started_at = self._wait_for_night_or_title()
            if screen == "title":
                if not self.menu_plan:
                    log.info("Back on the title screen and nothing left to do")
                    break
                entry, levels = self.menu_plan.pop(0)
                self.custom_levels = levels if entry == "custom" else None
                self.overlay.show(action=f"Menu: {entry}", status="", threats="")
                menu.choose(self.window, entry, levels)
                continue
            survived = self._play_night(started_at)
            if not survived:
                log.error("A night was lost - stopping so it can be investigated")
                break

    def _wait_for_night_or_title(self) -> tuple[str, float]:
        """Watch the screen until a night starts (HUD appears) or the title
        screen shows. Returns ('night', time of the first HUD frame) or
        ('title', 0)."""
        self.overlay.show(action="Waiting for the next screen...", status="", threats="")
        deadline = time.monotonic() + SCREEN_TIMEOUT
        last_title_check = 0.0
        black_since: float | None = None
        while time.monotonic() < deadline:
            if self.stop.is_set():
                raise StopRequested()
            self.window.ensure_visible()   # someone may have switched away
            frame = self.window.grab()
            if looks_shifted(frame):
                self.window.repair()       # the shifted "quarter" picture
            if self.vision.hud_visible(frame):
                return "night", time.perf_counter() - CAPTURE_LATENCY
            # After a minimise/restore the game sometimes draws nothing at
            # all and never recovers (seen live: a black window for over a
            # minute). Restarting it is the only way out.
            if frame.max() < 8:
                black_since = black_since or time.monotonic()
                if time.monotonic() - black_since > BLACK_SCREEN_RESTART:
                    log.warning("The game has shown a black screen for %.0f s - restarting it", BLACK_SCREEN_RESTART)
                    menu.close_game()
                    self.window = menu.open_game()
                    black_since = None
            else:
                black_since = None
            if time.monotonic() - last_title_check > 0.5:
                last_title_check = time.monotonic()
                if menu.on_title_screen(self.window):
                    return "title", 0.0
        raise menu.MenuError("Neither a night nor the title screen appeared")

    # -- one night -------------------------------------------------------------

    def _play_night(self, started_at: float) -> bool:
        controller = Controller(self.window, self.vision)
        body = RealBody(controller, self.vision, stop_flag=self.stop.is_set)
        body.start_clock_at(started_at)
        night = self.vision.read_hud(self.window.grab()).night or 1
        custom = self.custom_levels if night == 7 else None
        label = (f"Custom {'/'.join(str(custom[n]) for n in rules.ANIMATRONICS)}"
                 if custom else f"Night {night}")
        log.info("=== %s ===", label)

        def report(status: Status) -> None:
            t = body.now()
            # The panel speaks to people (narrator.py); the log keeps the
            # brain's exact words for the tools.
            comment, low = narrator.power_comment(body.power(), t, night)
            self.overlay.show(
                action=narrator.narrate(status.action, status.notes),
                alert=status.alert,
                # One short line each, so all three fit the panel's height.
                status=f"Power {body.power()}% - {comment} | usage {controller.hud.usage or '?'}",
                warn=low,
                threats="  ".join(f"{name} {note}" for name, note in status.notes.items()),
                night_time=t,
                rate=1.0 / body.scale,   # keeps the clock hands moving between updates
            )

        Brain(body, night, custom, report=report).play()
        # Only the game's own "6 AM" screen counts as a win. (An earlier
        # version trusted the clock - "535 s passed, so we won" - and once
        # called a jumpscare at 533 s a victory; see docs/DEVLOG.md.)
        survived = body.six_am_seen
        power = body.power()
        self.overlay.show(action=narrator.night_over_message(survived, power), alert=not survived)
        self.results.append((label, survived, power))
        log.info("%s finished: %s with %d%% power", label, "SURVIVED" if survived else "LOST", power)
        if not survived:
            cv2.imwrite(str(config.LOG_DIR / f"loss_{datetime.now():%H-%M-%S}.png"), self.window.grab())
        return survived


def _only_copy_running() -> bool:
    """Claim a system-wide name, so a second copy of the bot cannot start.

    Two copies once ran at the same time (a test series started twice):
    both clicked in the same game window and one closed the game under the
    other between nights - three "lost" nights that said nothing about the
    bot (docs/DEVLOG.md). The name is held until this process ends."""
    import win32api
    import win32event
    import winerror

    global _MUTEX
    _MUTEX = win32event.CreateMutex(None, False, "fnafbot-single-copy")
    return win32api.GetLastError() != winerror.ERROR_ALREADY_EXISTS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--setup", action="store_true", help="extract reference pictures from the game (one time)")
    parser.add_argument("--new-game", action="store_true", help="start a New Game (night 1)")
    parser.add_argument("--continue", dest="cont", action="store_true", help="continue the saved night")
    parser.add_argument("--sixth", action="store_true", help="play the 6th Night")
    parser.add_argument("--custom", type=int, nargs=4, metavar=("FREDDY", "BONNIE", "CHICA", "FOXY"),
                        help="play Custom Night with these AI levels")
    parser.add_argument("--campaign", action="store_true", help="new game, nights 1-5, 6th night, custom 20/20/20/20")
    parser.add_argument("--nights", type=int, help="stop after this many nights")
    args = parser.parse_args()

    if not _only_copy_running():
        sys.exit("Another copy of the bot is already running - not starting a second one.")
    log_path = setup_logging()
    if args.setup:
        count = assets.extract_all()
        print(f"Extracted {count} reference pictures to {config.ASSET_CACHE}")
        return

    plan: list[tuple[str, dict | None]] = []
    if args.campaign:
        plan = [("new", None), ("sixth", None), ("custom", dict.fromkeys(rules.ANIMATRONICS, 20))]
    else:
        if args.new_game:
            plan.append(("new", None))
        if args.cont:
            plan.append(("continue", None))
        if args.sixth:
            plan.append(("sixth", None))
        if args.custom:
            plan.append(("custom", dict(zip(rules.ANIMATRONICS, args.custom))))
    if not plan:
        parser.error("choose what to play: --new-game, --continue, --sixth, --custom or --campaign")

    print(f"Logging to {log_path}. Press {config.STOP_HOTKEY.upper()} to stop.")
    session = Session(plan, args.nights)
    try:
        session.run()
    except (StopRequested, KeyboardInterrupt):
        log.info("Stopped by the user")
    finally:
        if session.results:
            time.sleep(3.0)      # leave the last words ("6 AM! We made it...") up for a moment
        session.overlay.close()
        for label, survived, power in session.results:
            print(f"{label}: {'survived' if survived else 'LOST'} with {power}% power")


if __name__ == "__main__":
    main()
