"""Measure how many frames per second the game really draws.

The game's timers ("every 1 second", "every 4.97 seconds", ...) are tied to
its frames, so knowing the true frame rate tells us how long one of those
"seconds" really lasts. This grabs a small patch of the screen as fast as
possible and counts how often it changes (the title screen and the camera
static flicker on every frame).

usage: python tools/measure_fps.py [--seconds 10]
Run it while the title screen (or a night) is showing.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fnafbot.screen import GameWindow  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=10.0)
    args = parser.parse_args()

    window = GameWindow()
    window.find()
    window.ensure_visible()
    time.sleep(1.0)
    window.refresh_position()

    import mss
    left, top = window.to_screen(440, 200)
    patch = {"left": left, "top": top, "width": 400, "height": 300}
    changes: list[float] = []
    grabs = 0
    with mss.MSS() as sct:
        previous = np.asarray(sct.grab(patch))
        end = time.perf_counter() + args.seconds
        while time.perf_counter() < end:
            frame = np.asarray(sct.grab(patch))
            grabs += 1
            if not np.array_equal(frame, previous):
                changes.append(time.perf_counter())
                previous = frame
    gaps = np.diff(changes) * 1000
    print(f"{grabs / args.seconds:.0f} grabs/s, {len(changes) / args.seconds:.2f} picture changes/s")
    if len(gaps):
        print(f"gap between changes: median {statistics.median(gaps):.2f} ms, "
              f"mean {gaps.mean():.2f} ms, min {gaps.min():.2f}, max {gaps.max():.2f}")


if __name__ == "__main__":
    main()
