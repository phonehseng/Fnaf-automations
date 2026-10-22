"""When do Foxy's "every 5.01 s" ticks really happen? Measured from his bangs.

Foxy cannot be watched without freezing him (any camera picture locks him),
but the game's rules give another way (decompiled events [318]-[324]):

  * at stage 3 he leaves exactly 1500 frames (25 s) later, and
  * if the left door is shut at that moment he bangs on it, and the power
    drops by 10 + 50 x (earlier bangs) units on that very frame - in
    between the once-per-second power charges.

He can only reach stage 3 on one of his ticks. So every bang happens 25 s
after one of his ticks, and (bang time - 25 s) modulo 5.01 s is the phase of
his timer. This plays a Custom Night with only Foxy active (0/0/0/20), the
left door shut all night and the camera never raised, and timestamps every
power drop that does not fall on a power charge.

usage: python tools/measure_foxy_phase.py   (the night is lost to the
battery after a handful of bangs - that is expected and harmless)
"""

from __future__ import annotations

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

FUSE_SECONDS = 1500 / 60          # stage 3 -> leaves the cove
# A power change counts as a bang if it is this far (game seconds) from the
# nearest power charge; charges are seen 0.0 - 0.1 s after a whole second.
OFF_CHARGE = 0.2


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stdout)
    window = menu.open_game()
    vision = Vision()
    ctl = Controller(window, vision)
    menu.choose(window, "custom", {"freddy": 0, "bonnie": 0, "chica": 0, "foxy": 20})
    body = RealBody(ctl, vision)
    body.start_clock()
    ctl.set_door(LEFT, True)
    ctl.face(RIGHT)            # look away from the left door; nothing else to do
    ctl.rest()

    bangs: list[tuple[float, float, int]] = []    # (night time, real seconds, drop %)
    last = None
    while not body.night_over():
        body.wait_until(body.now() + 0.01)
        power = body.last_power
        if power is None:
            continue
        if last is not None and power < last:
            t = body.now()                       # game seconds (power clock)
            off = t - math.floor(t)
            if OFF_CHARGE < off < 1 - OFF_CHARGE or last - power >= 2:
                real = t * body.scale
                bangs.append((t, real, last - power))
                print(f"bang? at {t:7.2f} s (real {real:7.2f} s), power {last}% -> {power}%")
        last = power

    print(f"\nclock: game second = {body.scale:.4f} real s; {len(bangs)} bangs")
    for t, real, drop in bangs:
        tick_real = real - FUSE_SECONDS
        k = math.floor(tick_real / rules.FOXY_TICK)
        phase = tick_real - k * rules.FOXY_TICK
        print(f"  bang at real {real:7.2f} s (-{drop}%): stage 3 reached at real {tick_real:7.2f} s "
              f"= tick {k} + {phase:.2f} s")
    print("\nThe phase is the part after the '+'. The bang is seen up to a HUD look (~0.03 s)"
          " after it happens, so the true phase is at most that much smaller.")


if __name__ == "__main__":
    main()
