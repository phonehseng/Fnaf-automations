"""Where are Foxy's ticks really? Find out by where a camera flip holds him.

On live 4/20 nights - and on a Custom Night with Foxy alone - Foxy kept
climbing stages while every camera flip placed on his computed tick was
logged as "covering" it. Under the game's rules (events [191], [313],
[329]) a camera picture locks him for at least 50 frames after the monitor
comes down, so a flip that really sits on his tick holds him every time;
one that sits seconds away from it only holds him while the random part of
the lock lasts. So the flip position that stops him climbing IS his tick.

Custom Night 0/0/0/20 (Foxy alone), left door shut all night (a run only
costs a bang). The night is played in segments; in each, every one of his
ticks gets a short flip (0.5 s of picture on 4B) ending OFFSET seconds after
the tick the model computes, and every third flip also looks at Pirate
Cove to read his stage. The number of stages he gains per tick, per offset,
shows where his real tick is.

With --chica, Chica is active too (AI 20) and both doors stay shut all
night: does her moving around break Foxy's lock? (The lock lives on the
Chica object - chica.AltM - and an object condition is true if ANY of its
instances passes it.)

usage: python tools/foxy_flip_offset.py [--ticks 12] [--offsets 0 2.5 1.25 3.75] [--chica]
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

FOXY = rules.TICK_PERIOD["foxy"]
PHASE = rules.TICK_PHASE["foxy"]
VIEW = 0.5            # seconds of picture per flip
UP = 0.75             # flip request -> picture showing (measured live)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticks", type=int, default=12, help="flips per offset segment")
    parser.add_argument("--offsets", type=float, nargs="+", default=[0.0, 2.5, 1.25, 3.75])
    parser.add_argument("--chica", action="store_true")
    args = parser.parse_args()

    window = menu.open_game()
    vision = Vision()
    ctl = Controller(window, vision)
    menu.choose(window, "custom", {"freddy": 0, "bonnie": 0, "chica": 20 if args.chica else 0, "foxy": 20})
    body = RealBody(ctl, vision)
    body.start_clock()
    if args.chica:
        ctl.face(RIGHT)
        time.sleep(0.4)
        ctl.press(layout.RIGHT_DOOR_BUTTON)      # Chica cannot get in
        time.sleep(0.6)
    ctl.face(LEFT)
    time.sleep(0.4)
    ctl.press(layout.LEFT_DOOR_BUTTON)          # shut all night: a run is only a bang
    time.sleep(0.6)

    def real_now() -> float:
        return time.perf_counter() - body.real_origin

    def wait_real(t: float) -> None:
        body.wait_until(body.real_to_game(t))

    last_stage = None
    results: dict[float, list[int]] = {}          # offset -> stage gained at each read
    log_lines = []
    for offset in args.offsets:
        gains: list[int] = []
        k = math.floor((real_now() - PHASE) / FOXY) + 2
        for n in range(args.ticks):
            if body.night_over():
                break
            tick = k * FOXY + PHASE
            view_end = tick + offset
            view_start = view_end - VIEW
            if view_start - UP < real_now() + 0.05:
                k += 1
                continue
            wait_real(view_start - UP)
            ctl.camera_up()
            read = (n % 3 == 2)
            if read:
                reading = ctl.view("1C")
                stage = reading.foxy_stage if reading.margin >= 1.0 else None
                ctl.select_camera_blind("4B")
            wait_real(max(view_end, real_now()))
            ctl.camera_down()
            if read:
                line = f"offset {offset:+.2f}: tick k={k} ({tick:7.2f} s real)  cove stage {stage}"
                print(line, flush=True)
                log_lines.append(line)
                if stage is not None and last_stage is not None:
                    gains.append(stage - last_stage if stage >= last_stage else 0)
                if stage is not None:
                    last_stage = stage
            k += 1
        results[offset] = gains
        print(f"segment offset {offset:+.2f}: stage gains between reads {gains}", flush=True)

    print("\nSUMMARY (stages gained per 3 ticks, per flip offset after the model's tick):")
    for offset, gains in results.items():
        mean = sum(gains) / len(gains) if gains else float("nan")
        print(f"  offset {offset:+.2f} s: {gains}  mean {mean:.2f}")
    print("The offset with ~0 gains is where the flips really sit on his tick.")


if __name__ == "__main__":
    main()
