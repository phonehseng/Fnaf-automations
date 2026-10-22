"""Why do the doors stay shut so long? Plays simulated nights and lists every
door closure: why it was shut (the brain's own words), how long it stayed
shut, and how many power charges it cost.

usage: python tools/door_spans.py --custom 20 20 20 20 --runs 10 [--show 5]
"""

from __future__ import annotations

import argparse
import collections
import logging
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fnafbot.brain import Brain           # noqa: E402
from fnafbot.sim import NightSim, SimBody  # noqa: E402

EVENT = re.compile(r"\s*(\d+\.\d+)s door (left|right) (closing|opening)")
REASON = re.compile(r"door closed \(([^)]*)\)")


class Collect(logging.Handler):
    """Keep (true sim time, message) for every brain log line."""

    def __init__(self, sim_ref: list) -> None:
        super().__init__()
        self.sim_ref = sim_ref
        self.lines: list[tuple[float, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append((self.sim_ref[0].now, record.getMessage()))


def spans(sim: NightSim, lines: list[tuple[float, str]]):
    """Yield (side, closed_from, closed_until, reason) for each closure."""
    shut: dict[str, float] = {}
    for event in sim.events:
        m = EVENT.match(event)
        if not m:
            continue
        t, side, what = float(m.group(1)), m.group(2), m.group(3)
        if what == "closing":
            shut[side] = t
        elif side in shut:
            start = shut.pop(side)
            reason = "?"
            for lt, msg in lines:
                if abs(lt - start) < 0.4 and "door closed" in msg and (side.upper() in msg or side in msg):
                    rm = REASON.search(msg)
                    reason = rm.group(1) if rm else msg
                    break
            yield side, start, t, reason


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--night", type=int, default=6)
    parser.add_argument("--custom", type=int, nargs=4)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--show", type=int, default=0, help="print the brain's log around the N longest closures")
    args = parser.parse_args()
    night = 7 if args.custom else args.night
    custom = dict(zip(("freddy", "bonnie", "chica", "foxy"), args.custom)) if args.custom else None

    sim_ref: list = [None]
    handler = Collect(sim_ref)
    logging.getLogger("fnafbot.brain").addHandler(handler)
    logging.getLogger("fnafbot.brain").setLevel(logging.INFO)

    by_reason: dict[str, list[float]] = collections.defaultdict(list)
    charges: dict[str, int] = collections.Counter()
    longest = []
    for seed in range(args.runs):
        handler.lines = []
        sim = NightSim(night, custom, seed=seed)
        sim_ref[0] = sim
        Brain(SimBody(sim), night, custom).play()
        for side, start, end, reason in spans(sim, handler.lines):
            # Counted as closed from the end of the closing animation to the
            # end of the opening one: 0.55 s after "closing", 0.45 s after "opening".
            c_from, c_to = start + 0.55, end + 0.45
            n = max(0, math.floor(c_to) - math.ceil(c_from) + 1)
            by_reason[reason].append(c_to - c_from)
            charges[reason] += n
            longest.append((c_to - c_from, seed, side, start, end, reason, list(handler.lines)))

    print(f"door closures over {args.runs} nights (per night):")
    print(f"  {'reason':32s} {'count':>6} {'mean s':>7} {'charges':>8}")
    for reason, durs in sorted(by_reason.items(), key=lambda kv: -charges[kv[0]]):
        print(f"  {reason:32s} {len(durs) / args.runs:6.1f} {sum(durs) / len(durs):7.2f} "
              f"{charges[reason] / args.runs:8.1f}")
    print(f"  total power on doors: {sum(charges.values()) / args.runs / 10:.1f} %")

    longest.sort(reverse=True)
    for dur, seed, side, start, end, reason, lines in longest[:args.show]:
        print(f"\n--- seed {seed}: {side} door shut {start:.2f} -> {end:.2f} ({dur:.1f} s), reason: {reason}")
        for t, msg in lines:
            if start - 1.0 <= t <= end + 0.3:
                print(f"    [{t:7.2f}] {msg}")


if __name__ == "__main__":
    main()
