"""Find the first simulated loss and print what the brain was doing before it.

usage: python tools/debug_loss.py --custom 20 20 20 20 [--max-seeds 200]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fnafbot.brain import Brain           # noqa: E402
from fnafbot.sim import NightSim, SimBody  # noqa: E402


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--night", type=int, default=5)
    parser.add_argument("--custom", type=int, nargs=4)
    parser.add_argument("--max-seeds", type=int, default=300)
    parser.add_argument("--window", type=float, default=25.0, help="seconds of history to print")
    args = parser.parse_args()
    night = 7 if args.custom else args.night
    custom = dict(zip(("freddy", "bonnie", "chica", "foxy"), args.custom)) if args.custom else None

    handler = _Collect()
    logging.getLogger("fnafbot.brain").addHandler(handler)
    logging.getLogger("fnafbot.brain").setLevel(logging.INFO)
    for seed in range(1, args.max_seeds + 1):
        handler.lines.clear()
        sim = NightSim(night, custom, seed=seed)
        Brain(SimBody(sim), night, custom).play()
        if not sim.result.survived:
            end = sim.result.seconds
            print(f"seed {seed}: {sim.result.cause} at {end:.2f}s\n--- game events ---")
            for line in sim.events:
                if float(line.split("s", 1)[0]) > end - args.window:
                    print("  " + line)
            print("--- brain actions ---")
            for line in handler.lines:
                t = float(line.split("s", 1)[0])
                if t > end - args.window:
                    print("  " + line)
            return
    print("no loss found")


if __name__ == "__main__":
    main()
