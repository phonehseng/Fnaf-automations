"""Which timer model matches the real game? Checks old logs.

Bonnie and Chica can only move on their timer ticks. So whenever two doorway
checks in a row disagree (empty -> occupied or occupied -> empty), at least
one of that animatronic's ticks must lie between the two checks. A timer
model that leaves such a gap with no tick in it is wrong.

Models compared (period of an "every T seconds" timer):
  nominal   T exactly (what the decompiled numbers say)
  frames    the timer can only fire on a frame (60 fps) and loses the
            leftover part of a frame each time: ceil(T * 60) / 60
  slow      the whole game runs slow by the factor measured from the night
            length (6 AM after ~538.5 s instead of 535 s)

usage: python tools/tick_model_check.py logs/*.log
"""

from __future__ import annotations

import math
import re
import sys
from datetime import datetime
from pathlib import Path

# Night length seen in the logs: 6 AM arrived ~538.5 s after the first frame
# although the game counts 535 "1 second" ticks.
SLOW_FACTOR = 538.5 / 535

PERIOD = {"left": 4.97, "right": 4.98}          # Bonnie (left), Chica (right)
MODELS = {
    "nominal": lambda t: t,
    "frames": lambda t: math.ceil(t * 60 - 1e-9) / 60,
    "slow": lambda t: t * SLOW_FACTOR,
}

STAMP = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}) ")
BRAIN_TIME = re.compile(r"fnafbot\.brain: +(\d+\.\d+)s ")
DOORWAY = re.compile(r"doorway (left|right): (EMPTY|OCCUPIED)")
NIGHT_START = re.compile(r"=== (Night \d|Custom)")


def parse_time(line: str) -> float | None:
    match = STAMP.match(line)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S,%f").timestamp()


def nights(path: Path):
    """Yield one list of (night_time, side, occupied) per night in a log."""
    reads: list[tuple[float, str, bool]] = []
    offsets: list[float] = []          # wall clock - night clock, from brain lines
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        wall = parse_time(line)
        if wall is None:
            continue
        if NIGHT_START.search(line) and reads:
            yield _to_night_time(reads, offsets)
            reads, offsets = [], []
        brain = BRAIN_TIME.search(line)
        if brain:
            offsets.append(wall - float(brain.group(1)))
        door = DOORWAY.search(line)
        if door:
            reads.append((wall, door.group(1), door.group(2) == "OCCUPIED"))
    if reads:
        yield _to_night_time(reads, offsets)


def _to_night_time(reads, offsets):
    offsets.sort()
    offset = offsets[len(offsets) // 2]
    return [(wall - offset, side, occupied) for wall, side, occupied in reads]


def violations(reads, period: float, phase: float) -> int:
    """Count state changes with no tick between the two reads."""
    bad = 0
    last: dict[str, tuple[float, bool]] = {}
    for t, side, occupied in reads:
        if side in last and last[side][1] != occupied:
            t_prev = last[side][0]
            # Is there a k with t_prev < phase + k*period <= t ?
            k = math.floor((t - phase) / period)
            if not (phase + k * period > t_prev):
                bad += 1
        last[side] = (t, occupied)
    return bad


def main() -> None:
    all_nights = [n for p in sys.argv[1:] for n in nights(Path(p)) if len(n) > 20]
    print(f"{len(all_nights)} nights, {sum(len(n) for n in all_nights)} doorway reads")
    for name, model in MODELS.items():
        total = 0
        changes = 0
        for reads in all_nights:
            for side in ("left", "right"):
                side_reads = [r for r in reads if r[1] == side]
                changes += sum(1 for a, b in zip(side_reads, side_reads[1:]) if a[2] != b[2])
                # The first tick happens one period after the night starts.
                total += violations(side_reads, model(PERIOD[side]), 0.0)
        print(f"  {name:8s}: {total:3d} impossible changes out of {changes}")


if __name__ == "__main__":
    main()
