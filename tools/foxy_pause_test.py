"""Does looking at Pirate Cove pause Foxy's timer?

Foxy's tick event ([191]) checks, in this order: viewing != 99 (99 is
camera 1C, Pirate Cove), fox progress < 3, then "every 5.01 seconds". In
Clickteam Fusion the conditions after a false one are not evaluated, and
the runtime's "every" timer only counts down when it IS evaluated (it
subtracts the frame's elapsed time). If so, his timer PAUSES while the cove
is on screen (and while he is at stage 3) - and every cove look moves his
ticks later by its length, which the bot's fixed-phase model never knew.

The test (Custom Night 0/0/0/20, left door shut all night, camera down
otherwise): his phase is measured from each bang - at stage 3 he leaves
exactly 1501 frames later and bangs on the shut door, the power dropping on
that frame - so (bang - 1501 frames) is the tick that took him to stage 3.
Right after each bang the cove is held on screen for a set time; the next
bang shows how far his phase moved. Expected if the timer pauses: +2.5 s,
then ~0 (a control), then +1.5 s (mod 5.01).

usage: python tools/foxy_pause_test.py
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fnafbot import layout, menu, rules  # noqa: E402
from fnafbot.body import RealBody  # noqa: E402
from fnafbot.controller import LEFT, Controller  # noqa: E402
from fnafbot.vision import Vision  # noqa: E402

FOXY = rules.TICK_PERIOD["foxy"]
FUSE = 1501 / 60
COVE_HOLDS = [2.5, 0.0, 1.5]       # seconds of Pirate Cove after bang 1, 2, 3


def main() -> None:
    window = menu.open_game()
    vision = Vision()
    ctl = Controller(window, vision)
    menu.choose(window, "custom", {"freddy": 0, "bonnie": 0, "chica": 0, "foxy": 20})
    body = RealBody(ctl, vision)
    body.start_clock()
    ctl.face(LEFT)
    time.sleep(0.4)
    ctl.press(layout.LEFT_DOOR_BUTTON)
    time.sleep(0.6)
    ctl.rest()

    def real_now() -> float:
        return time.perf_counter() - body.real_origin

    bangs: list[float] = []
    holds: list[tuple[float, float]] = []      # (start, end) of each cove view, real s
    last = None
    while not body.night_over() and len(bangs) < len(COVE_HOLDS) + 1:
        body.wait_until(body.now() + 0.01)
        power = body.last_power
        if power is None:
            continue
        if last is not None and power < last:
            t = body.now()
            off = t - math.floor(t)
            drop = last - power
            # A bang drops 1, 6, 11, 16 ... % (10 + 50 x earlier bangs units);
            # anything else (a lost leading digit: "94 % -> 9 %") is a misread.
            expected = 1 + 5 * len(bangs)
            if abs(drop - expected) <= 1 and (0.2 < off < 0.8 or drop >= 2):
                bang = real_now()
                bangs.append(bang)
                print(f"bang {len(bangs)} at {bang:8.3f} s real ({last}% -> {power}%)", flush=True)
                if len(bangs) <= len(COVE_HOLDS) and COVE_HOLDS[len(bangs) - 1] > 0:
                    hold = COVE_HOLDS[len(bangs) - 1]
                    time.sleep(1.0)        # he is back in the cove after the bang
                    ctl.camera_up()
                    ctl.select_camera_blind("1C")
                    start = real_now()
                    time.sleep(hold)
                    ctl.select_camera_blind("4B")
                    end = real_now()
                    ctl.camera_down()
                    ctl.face(LEFT)
                    holds.append((start, end))
                    print(f"   cove on screen {start:8.3f} - {end:8.3f} s ({end - start:.2f} s)", flush=True)
                body.wait_until(body.now() + 0.5)
                last = body.last_power
                continue
        last = power

    print("\nphase of the tick that took him to stage 3 (bang - 1501 frames), mod 5.01 s:")
    phases = []
    for i, bang in enumerate(bangs):
        tick = bang - FUSE
        phase = tick - math.floor(tick / FOXY) * FOXY
        phases.append(phase)
        print(f"  bang {i + 1}: tick at {tick:8.3f} s real, phase {phase:.3f}")
    for i in range(1, len(phases)):
        shift = (phases[i] - phases[i - 1] + FOXY / 2) % FOXY - FOXY / 2
        hold = COVE_HOLDS[i - 1]
        print(f"  shift between bang {i} and {i + 1}: {shift:+.3f} s  (cove held {hold:.1f} s)")


if __name__ == "__main__":
    main()
