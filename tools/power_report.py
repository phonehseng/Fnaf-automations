"""Where does the power go? Plays simulated nights and sums what was switched
on at each once-per-second power charge (10 units = 1 %).

usage: python tools/power_report.py --custom 20 20 20 20 --runs 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fnafbot.brain import Brain           # noqa: E402
from fnafbot.sim import NightSim, SimBody  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--night", type=int, default=5)
    parser.add_argument("--custom", type=int, nargs=4)
    parser.add_argument("--runs", type=int, default=20)
    args = parser.parse_args()
    night = 7 if args.custom else args.night
    custom = dict(zip(("freddy", "bonnie", "chica", "foxy"), args.custom)) if args.custom else None

    totals: dict[str, int] = {}
    foxy_bangs = 0
    for seed in range(args.runs):
        sim = NightSim(night, custom, seed=seed)
        Brain(SimBody(sim), night, custom).play()
        for key, units in sim.spent.items():
            totals[key] = totals.get(key, 0) + units
        foxy_bangs += sim.foxy_bangs
    print(f"average extra power per night ({args.runs} nights), in % of the battery:")
    for key, units in sorted(totals.items(), key=lambda kv: -kv[1]):
        print(f"  {key:12s} {units / args.runs / 10:5.1f} %")
    print(f"  Foxy bangs per night: {foxy_bangs / args.runs:.2f}")


if __name__ == "__main__":
    main()
