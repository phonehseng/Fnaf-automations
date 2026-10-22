"""Measure WHEN Bonnie really moves, to settle how the game's timers run.

Bonnie only changes room on one of his "every 4.97 s" ticks, and a room
change shows instantly on the camera. So: shut both doors (safe for a few
minutes), keep the monitor on the camera Bonnie is on, and note the game
time at which his picture changes. Each change is a tick. Comparing those
times with two candidate models tells them apart:

  nominal  tick k at k * 4.97 game seconds
  frames   the timer re-arms on whole frames: ceil(4.97 * 60) = 299 frames,
           so tick k at k * 299 / 60 = k * 4.9833 s (0.8 s later by 300 s)

The clock is the bot's own (RealBody), fitted to the power readout as
during a real night. usage: python tools/measure_ticks.py [--seconds 240]
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fnafbot import menu, rules  # noqa: E402
from fnafbot.body import RealBody  # noqa: E402
from fnafbot.controller import LEFT, RIGHT, Controller  # noqa: E402
from fnafbot.vision import Vision  # noqa: E402

CAMS = {"bonnie": ["1A", "1B", "5", "2A", "2B", "3"], "chica": ["1A", "1B", "7", "6", "4A", "4B"]}
LETTER = {"bonnie": "B", "chica": "C"}


def find(ctl: Controller, who: str) -> str | None:
    for cam in CAMS[who]:
        if LETTER[who] in ctl.view(cam).occupants:
            return cam
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=240.0)
    parser.add_argument("--who", choices=("bonnie", "chica"), default="bonnie")
    parser.add_argument("--fit-seconds", type=float, default=60.0, help="HUD-only time to fit the clock first")
    args = parser.parse_args()
    who, letter = args.who, LETTER[args.who]
    nominal = rules.TICK_PERIOD[who]
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)

    window = menu.open_game()
    vision = Vision()
    ctl = Controller(window, vision)
    menu.choose(window, "continue")
    body = RealBody(ctl, vision)
    body.start_clock()
    ctl.set_door(LEFT, True)
    ctl.set_door(RIGHT, True)
    # Let the clock fit itself first: ~35 s of tight HUD looks (each power
    # change pinned to a few hundredths) is what a real night gives it.
    print("fitting the clock from the power readout...")
    body.wait_until(args.fit_seconds)
    print(f"game second = {body.scale:.4f} real s after {len(body._power_sightings)} sightings; "
          f"fitted: {body._fitted}")

    events: list[tuple[float, str]] = []
    cam = find(ctl, who)
    print(f"{who} starts on {cam} at {body.now():.2f} s")
    last_seen = cam is not None
    end = time.monotonic() + args.seconds
    while time.monotonic() < end and not body.night_over():
        if cam is None:
            cam = find(ctl, who)
            if cam:
                events.append((body.now(), f"appears on {cam}"))
                print(f"{events[-1][0]:8.2f} s  {events[-1][1]}")
            continue
        reading = ctl.view(cam)
        t = body.now()            # time of the frame just read
        present = letter in reading.occupants
        if reading.confident and present != last_seen:
            events.append((t, f"{'appears on' if present else 'leaves'} {cam}"))
            print(f"{t:8.2f} s  {events[-1][1]}")
            last_seen = present
            if not present:
                cam = None
        body.wait_until(body.now() + 0.02)   # keeps the clock fitting from the power readout

    ctl.camera_down()
    scale = body.scale
    print(f"\nclock: game second (power timer) = {scale:.4f} real s; {len(events)} room changes")
    # Candidate rules for Bonnie's timer, all expressed in REAL seconds since
    # the night's first frame (the bot's clock times scale):
    models = {
        f"game {nominal}": nominal * scale,                   # same stretch as the power timer
        f"real {nominal}": nominal,                           # exact real time
        "frames": round(nominal / (scale / 60)) * scale / 60,     # whole frames, rounded
    }
    print(f"{'game s':>8} {'real s':>8}  {'event':14} " + "  ".join(f"{name:>16}" for name in models))
    for t, what in events:
        real = t * scale
        cells = []
        for name, period in models.items():
            k = round(real / period)
            cells.append(f"k={k:3d} {real - k * period:+6.2f}s")
        print(f"{t:8.2f} {real:8.2f}  {what:14} " + "  ".join(f"{c:>16}" for c in cells))
    print("\n'leaves' lines are the precise ones (an 'appears' is found by scanning, later).")
    print("The rule whose residuals stay constant (any offset, no growth with k) is the real one.")


if __name__ == "__main__":
    main()
