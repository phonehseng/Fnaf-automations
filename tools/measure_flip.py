"""Does lowering the monitor too soon after raising it leave the game thinking
a camera is still up?

Suspicion (docs/DEVLOG.md): the game sets its "viewing" counter when the
flip-up ANIMATION finishes (event [133]), and clears it on put-down. If the
bot puts the monitor down before that animation has finished, the counter
is set AFTER the put-down and stays set - and then every door and light
click is ignored (they all require viewing == 0) until the next flip.

Test: raise the monitor, wait ``d`` seconds after the camera label appears,
lower it, then click the left door and read the door button's lamp. A
click that changes the lamp proves the game accepted it. Repeated for a
range of ``d``. Both doors start shut so the office is safe meanwhile; the
left door is opened/closed by the test clicks themselves.

usage: python tools/measure_flip.py   (needs a night; losing it is harmless)
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fnafbot import layout, menu  # noqa: E402
from fnafbot.body import RealBody  # noqa: E402
from fnafbot.controller import LEFT, RIGHT, Controller  # noqa: E402
from fnafbot.vision import Vision  # noqa: E402

DELAYS = [0.3, 0.45, 0.6, 0.8, 1.0, 1.3]
TRIALS = 3


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stdout)
    window = menu.open_game()
    vision = Vision()
    ctl = Controller(window, vision)
    menu.choose(window, "continue")
    body = RealBody(ctl, vision)
    body.start_clock()
    ctl.set_door(LEFT, True)
    ctl.set_door(RIGHT, True)
    time.sleep(0.5)

    results: dict[float, list[bool]] = {d: [] for d in DELAYS}
    for trial in range(TRIALS):
        for d in DELAYS:
            if body.night_over():
                break
            ctl.face(LEFT)
            if not ctl.camera_up():
                print("monitor did not come up; skipping")
                continue
            time.sleep(d)
            ctl.camera_down()
            time.sleep(0.25)
            ctl.face(LEFT)
            before = vision.door_lamp(window.grab(), LEFT)
            ctl.press(layout.LEFT_DOOR_BUTTON)
            time.sleep(0.12)
            after = vision.door_lamp(window.grab(), LEFT)
            accepted = before is not None and after is not None and after != before
            results[d].append(accepted)
            print(f"trial {trial + 1}  delay {d:.2f} s  lamp {before} -> {after}  {'OK' if accepted else 'IGNORED'}")
            if not accepted:
                # Recover: a flip up and down resets the game's viewing state.
                time.sleep(0.4)
                ctl.camera_up()
                time.sleep(1.5)
                ctl.camera_down()
                time.sleep(0.3)
                ctl.press(layout.LEFT_DOOR_BUTTON)   # back to the state before the test
            time.sleep(0.8)
            # Restore: the door should be shut between trials.
            lamp = vision.door_lamp(window.grab(), LEFT)
            if lamp == "open":
                ctl.press(layout.LEFT_DOOR_BUTTON)
                time.sleep(0.8)
    print("\ndelay after the camera label appeared -> clicks accepted")
    for d, outcomes in results.items():
        print(f"  {d:.2f} s: {sum(outcomes)}/{len(outcomes)}")


if __name__ == "__main__":
    main()
