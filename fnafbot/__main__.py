"""Run the FNAF bot.

Examples (from the project folder):
    python -m fnafbot --night 1                  # play night 1
    python -m fnafbot --night 1 2 3 4 5          # play nights 1-5 in a row
    python -m fnafbot --custom 20 20 20 20       # 4/20 mode (Freddy Bonnie Chica Foxy)
    python -m fnafbot --night 5 --repeat 3       # play night 5 three times

Press F8 at any time to stop the bot. Logs are written to logs/.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from datetime import datetime

from fnafbot import config, menu, rules
from fnafbot.body import RealBody, StopRequested
from fnafbot.brain import Brain, Status
from fnafbot.controller import Controller
from fnafbot.overlay import StatusOverlay
from fnafbot.vision import Vision

log = logging.getLogger("fnafbot")


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


def play_night(night: int, custom: dict[str, int] | None, vision: Vision, overlay: StatusOverlay,
               stop: threading.Event) -> tuple[bool, int]:
    """Start and play one night. Returns (survived, power % left)."""
    label = "Custom " + "/".join(str(custom[n]) for n in rules.ANIMATRONICS) if custom else f"Night {night}"
    overlay.show(action=f"Starting {label}...", status="", threats="")
    window = menu.start_night(night, custom)
    controller = Controller(window, vision)
    body = RealBody(controller, vision, stop_flag=stop.is_set)
    body.start_clock()

    def report(status: Status) -> None:
        t = body.now()
        hour = rules.hour_at(t)
        hud = controller.hud
        overlay.show(
            action=status.action,
            alert=status.alert,
            status=f"{label} | {hour} AM | Power {body.power()}% | Usage {hud.usage or '?'} | t={t:5.1f}s",
            threats=" | ".join(f"{name}: {note}" for name, note in status.notes.items()),
        )

    brain = Brain(body, night, custom, report=report)
    brain.play()
    survived = body.now() >= rules.NIGHT_SECONDS - 2
    power = body.power()
    log.info("%s finished: %s with %d%% power", label, "SURVIVED" if survived else "LOST", power)
    if not survived:
        # Keep evidence of what went wrong.
        import cv2
        cv2.imwrite(str(config.LOG_DIR / f"loss_{datetime.now():%H-%M-%S}.png"), window.grab())
    time.sleep(12)   # let the 6 AM / game-over screens finish
    return survived, power


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--night", type=int, nargs="*", default=[], help="night(s) 1-6 to play")
    parser.add_argument("--custom", type=int, nargs=4, metavar=("FREDDY", "BONNIE", "CHICA", "FOXY"),
                        help="play a custom night with these AI levels")
    parser.add_argument("--repeat", type=int, default=1, help="play the whole list this many times")
    args = parser.parse_args()

    log_path = setup_logging()
    plan: list[tuple[int, dict | None]] = [(n, None) for n in args.night]
    if args.custom:
        plan.append((7, dict(zip(rules.ANIMATRONICS, args.custom))))
    if not plan:
        parser.error("choose --night and/or --custom")
    plan = plan * args.repeat

    print(f"Logging to {log_path}. Press {config.STOP_HOTKEY.upper()} to stop.")
    vision = Vision()
    overlay = StatusOverlay()
    stop = watch_stop_key()
    results = []
    try:
        for night, custom in plan:
            results.append((night, custom, *play_night(night, custom, vision, overlay, stop)))
    except (StopRequested, KeyboardInterrupt):
        log.info("Stopped by the user")
    finally:
        overlay.close()
        for night, custom, survived, power in results:
            name = f"custom {custom}" if custom else f"night {night}"
            print(f"{name}: {'survived' if survived else 'LOST'} with {power}% power")


if __name__ == "__main__":
    main()
