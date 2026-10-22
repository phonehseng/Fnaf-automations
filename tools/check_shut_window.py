"""Can the right window be read with the right door SHUT?

Chica appears in the window beside the right door, not in the doorway the
door covers. If the window is still visible with the door shut, the bot can
check whether she has left without opening the door (and without paying for
the door's open/close cycle). This starts a night, shuts both doors, turns
the right light on and classifies the window area exactly like a normal
doorway check; it does the same on the left for comparison.

usage: python tools/check_shut_window.py   (needs a night; nothing is at risk:
both doors stay shut for the 20 s this takes)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fnafbot import config, layout, menu  # noqa: E402
from fnafbot.body import RealBody  # noqa: E402
from fnafbot.controller import LEFT, RIGHT, Controller  # noqa: E402
from fnafbot.vision import Vision  # noqa: E402


def main() -> None:
    window = menu.open_game()
    vision = Vision()
    ctl = Controller(window, vision)
    menu.choose(window, "continue")
    body = RealBody(ctl, vision)
    body.start_clock()
    ctl.set_door(LEFT, True)
    ctl.set_door(RIGHT, True)
    time.sleep(0.8)
    config.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    for side in (RIGHT, LEFT):
        ctl.face(side)
        time.sleep(0.3)
        lamp = vision.door_lamp(window.grab(), side)
        for trial in range(3):
            ctl.press(layout.RIGHT_LIGHT_BUTTON if side == RIGHT else layout.LEFT_LIGHT_BUTTON)
            readings = []
            end = time.perf_counter() + 0.3
            frame = None
            while time.perf_counter() < end:
                frame = window.grab()
                readings.append(vision.doorway_state(frame, side))
            ctl.press(layout.RIGHT_LIGHT_BUTTON_OFF if side == RIGHT else layout.LEFT_LIGHT_BUTTON_OFF)
            lit = [r for r in readings if r[0] != "dark"]
            best = max(lit, key=lambda r: r[1]) if lit else ("dark", 0.0)
            print(f"{side:5s} door={lamp}  trial {trial + 1}: {len(lit)}/{len(readings)} lit frames, "
                  f"best reading {best[0]} (margin {best[1]:.1f})")
            if frame is not None:
                cv2.imwrite(str(config.EVIDENCE_DIR / f"shut_{side}_light_{trial}.jpg"), frame)
            time.sleep(0.6)


if __name__ == "__main__":
    main()
