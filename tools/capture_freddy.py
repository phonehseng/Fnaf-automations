"""Film Freddy walking his route, for the videos (not part of the bot).

Custom Night with Freddy, Bonnie and Chica at 20 and Foxy at 0, both doors
shut the whole time (nobody can get in; the night ends when the power runs
out). Freddy only leaves the stage once Bonnie and Chica have, and only
moves while the monitor is DOWN - so this lowers the monitor for a few
seconds, then flips to where he should be now and holds the picture after
the switching static has cleared. Once he reaches the East Hall Corner (4B)
it holds long views of him there.

Every hold is printed with OBS's recording timecode, so the clips can be cut
from the recording exactly. OBS must be recording.

usage: python tools/capture_freddy.py [seconds]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import obsws_python as obs  # noqa: E402

from fnafbot import layout, menu  # noqa: E402
from fnafbot.body import RealBody  # noqa: E402
from fnafbot.controller import LEFT, RIGHT, Controller  # noqa: E402
from fnafbot.vision import Vision  # noqa: E402

ROUTE = ["1A", "1B", "7", "6", "4A", "4B"]
DOWN_SECONDS = 3.4        # monitor down: one or two of his 3.02 s rolls
HOLD_SECONDS = 2.2        # each camera, after the static clears
CORNER_HOLD = 5.0         # long looks at 4B once he is there


def main() -> None:
    length = float(sys.argv[1]) if len(sys.argv) > 1 else 170.0
    rec = obs.ReqClient(host="localhost", port=4455, password="", timeout=5)

    def stamp(what: str) -> None:
        print(f"{rec.get_record_status().output_timecode}  {what}", flush=True)

    window = menu.open_game()
    vision = Vision()
    ctl = Controller(window, vision)
    menu.choose(window, "custom", {"freddy": 20, "bonnie": 20, "chica": 20, "foxy": 0})
    body = RealBody(ctl, vision)
    body.start_clock()
    stamp("night start")
    for side, button in ((LEFT, layout.LEFT_DOOR_BUTTON), (RIGHT, layout.RIGHT_DOOR_BUTTON)):
        ctl.face(side)
        time.sleep(0.3)
        ctl.press(button)
        time.sleep(0.5)
    ctl.rest()
    stamp("doors shut")
    step = 0
    end = time.perf_counter() + length
    while time.perf_counter() < end and not body.night_over():
        time.sleep(DOWN_SECONDS)
        if not ctl.camera_up():
            continue
        # where he was, then where he may be now
        for cam in dict.fromkeys([ROUTE[step], ROUTE[min(step + 1, 5)]]):
            ctl.select_camera_blind(cam)
            time.sleep(0.35)               # the switching static
            stamp(f"hold {cam}")
            time.sleep(CORNER_HOLD if cam == "4B" else HOLD_SECONDS)
        ctl.camera_down()
        step = min(step + 1, 5)
    stamp("done")


if __name__ == "__main__":
    main()
