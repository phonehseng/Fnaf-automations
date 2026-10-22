"""Play many simulated nights with the real brain and report the results.

Examples (run from the project folder):
    python tools/simulate.py --night 5 --runs 500
    python tools/simulate.py --custom 20 20 20 20 --runs 300
    python tools/simulate.py --night 5 --runs 1 --verbose     # show one night's events
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fnafbot.brain import Brain           # noqa: E402
from fnafbot.sim import NightSim, SimBody  # noqa: E402


def play_one(night: int, custom: dict | None, seed: int, verbose: bool = False):
    sim = NightSim(night, custom, seed=seed)
    brain = Brain(SimBody(sim), night, custom)
    brain.play()
    if verbose:
        print("\n".join(sim.events))
    return sim.result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--night", type=int, default=1, help="night 1-6")
    parser.add_argument("--custom", type=int, nargs=4, metavar=("FREDDY", "BONNIE", "CHICA", "FOXY"),
                        help="custom night AI levels (implies night 7)")
    parser.add_argument("--runs", type=int, default=200)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    night = 7 if args.custom else args.night
    custom = dict(zip(("freddy", "bonnie", "chica", "foxy"), args.custom)) if args.custom else None

    start = time.perf_counter()
    results = [play_one(night, custom, args.seed + i, args.verbose) for i in range(args.runs)]
    elapsed = time.perf_counter() - start

    wins = [r for r in results if r.survived]
    losses = [r for r in results if not r.survived]
    label = f"custom {args.custom}" if custom else f"night {night}"
    print(f"{label}: {len(wins)}/{len(results)} survived ({elapsed:.1f}s)")
    if wins:
        powers = [r.power / 10 for r in wins]
        print(f"  power left: mean {statistics.mean(powers):.1f}%  min {min(powers):.1f}%  max {max(powers):.1f}%")
    causes: dict[str, int] = {}
    for r in losses:
        causes[r.cause] = causes.get(r.cause, 0) + 1
    for cause, count in sorted(causes.items(), key=lambda kv: -kv[1]):
        print(f"  lost {count}x: {cause}")
    if losses and not args.verbose:
        first = losses[0]
        print(f"  first loss at {first.seconds:.1f}s; last events:")
        for line in first.log[-12:]:
            print("    " + line)


if __name__ == "__main__":
    main()
