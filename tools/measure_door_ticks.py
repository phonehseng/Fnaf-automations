"""When do Bonnie's / Chica's ticks really happen? Measured from the hall light.

The game switches the hall lights off on the very frame Bonnie or Chica
arrives at or leaves a doorway (decompiled events [226], [227], [259],
[260]). So with the light kept on, the light button's lamp going dark - when
the bot did not click it - timestamps one of their ticks to within one HUD
look (~0.02 s), far better than watching a camera (tools/measure_ticks.py).

This plays a Custom Night with only the chosen animatronic active (AI 20, so
every tick is a move): light on with the door open until they arrive, then
the door shut (they are sent back on their next tick - the light goes off
again), then the door open and the light on again, and so on.

usage: python tools/measure_door_ticks.py --who bonnie [--seconds 240]
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fnafbot import layout, menu, rules  # noqa: E402
from fnafbot.body import RealBody  # noqa: E402
from fnafbot.controller import LEFT, RIGHT, Controller  # noqa: E402
from fnafbot.vision import Vision  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--who", choices=("bonnie", "chica"), required=True)
    parser.add_argument("--seconds", type=float, default=240.0)
    args = parser.parse_args()
    side = LEFT if args.who == "bonnie" else RIGHT
    light = layout.LEFT_LIGHT_BUTTON if side == LEFT else layout.RIGHT_LIGHT_BUTTON
    door = layout.LEFT_DOOR_BUTTON if side == LEFT else layout.RIGHT_DOOR_BUTTON
    period = rules.TICK_PERIOD[args.who]

    window = menu.open_game()
    vision = Vision()
    ctl = Controller(window, vision)
    levels = {"freddy": 0, "bonnie": 0, "chica": 0, "foxy": 0, args.who: 20}
    menu.choose(window, "custom", levels)
    body = RealBody(ctl, vision)
    body.start_clock()
    ctl.face(side)
    time.sleep(0.6)

    def lamp_on() -> bool:
        return vision.light_lamp_on(window.grab(), side)

    events: list[tuple[float, str]] = []
    door_shut = False
    ctl.press(light)
    end = time.monotonic() + args.seconds
    while time.monotonic() < end and not body.night_over():
        body.wait_until(body.now() + 0.005)
        if lamp_on():
            continue
        # The light went off by itself: a tick of theirs just happened.
        t = body.now()
        what = "left the door" if door_shut else "arrived"
        events.append((t, what))
        print(f"{t:8.3f} s  {args.who} {what}", flush=True)
        time.sleep(0.3)
        if not door_shut:
            ctl.press(door)            # shut it: they are sent back on their next tick
            door_shut = True
        else:
            ctl.press(door)            # gone: open again and wait for the next visit
            door_shut = False
            time.sleep(0.6)
        time.sleep(0.3)
        ctl.press(light)
        time.sleep(0.3)

    print(f"\nclock: game second = {body.scale:.4f} real s; {len(events)} ticks seen")
    phases = []
    for t, what in events:
        real = t * body.scale
        k = round(real / period)
        phases.append(real - k * period)
        print(f"  {real:8.3f} real s  {what:14s} tick {k:3d} {real - k * period:+.3f} s")
    if phases:
        print(f"\nphase: min {min(phases):+.3f}  mean {sum(phases) / len(phases):+.3f}  "
              f"max {max(phases):+.3f} s  (seen up to one look, ~0.02 s, after the tick)")


if __name__ == "__main__":
    main()
