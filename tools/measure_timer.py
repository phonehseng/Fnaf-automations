"""Time one of the game's "every N seconds" timers from the screen.

On the title screen the game runs "every 0.09 s: give the static a new random
transparency". That makes the average brightness of the picture jump every
time the timer fires. We sample the brightness at the display's refresh rate
and look at the gaps between jumps:

  - if the timer carries the left-over part of a frame into the next round,
    the gaps alternate between 5 and 6 frames (90 ms on average);
  - if it throws the left-over away, every gap is 6 frames (100 ms).

usage: python tools/measure_timer.py [--seconds 20]   (title screen showing)
"""

from __future__ import annotations

import argparse
import collections
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fnafbot.screen import GameWindow  # noqa: E402

JUMP = 2.0   # brightness change (0-255 scale) that counts as a new alpha value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=20.0)
    args = parser.parse_args()

    window = GameWindow()
    window.find()
    window.ensure_visible()
    time.sleep(1.0)
    window.refresh_position()

    import mss
    # A strip on the right of the title screen: static only, no menu text.
    left, top = window.to_screen(900, 600)
    patch = {"left": left, "top": top, "width": 360, "height": 100}
    samples: list[tuple[float, float]] = []
    with mss.MSS() as sct:
        end = time.perf_counter() + args.seconds
        while time.perf_counter() < end:
            frame = np.asarray(sct.grab(patch))[:, :, :3]
            samples.append((time.perf_counter(), float(frame.mean())))

    times = np.array([s[0] for s in samples])
    level = np.array([s[1] for s in samples])
    jumps = times[1:][np.abs(np.diff(level)) > JUMP]
    gaps_ms = np.diff(jumps) * 1000
    print(f"{len(samples) / args.seconds:.1f} samples/s, {len(jumps) / args.seconds:.2f} jumps/s")
    print(f"mean gap {gaps_ms.mean():.1f} ms, median {np.median(gaps_ms):.1f} ms")
    # Histogram in whole frames (16.7 ms).
    frames = collections.Counter(int(round(g / (1000 / 60))) for g in gaps_ms)
    for n in sorted(frames):
        if frames[n] >= 2:
            print(f"  {n:2d} frames: {frames[n]}")


if __name__ == "__main__":
    main()
