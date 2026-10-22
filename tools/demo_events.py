"""Make things happen on purpose, for the camera.

The bot's whole job is to stop the animatronics. This script does the
opposite for a few minutes so that a recording can SHOW what the bot is
guarding against - with captions in the status panel explaining each moment.
Everything is normal play through the game's own menus and buttons (the
night is played with "Continue"; losing it does not change the save).

Scenes:
  bonnie-tell   Leave the LEFT door open. Bonnie walks in; the hall light
                then refuses to come on (the game's tell) and he attacks.
                This is the clue the bot missed in docs/DEVLOG.md.
  chica-window  Watch the right window with the light until Chica shows up,
                shut the door, then show her leaving.
  foxy-run      Both doors shut; watch Pirate Cove until Foxy leaves, make him
                run by viewing West Hall, hear him bang on the door.
  freddy-walk   Both doors shut; keep the monitor down so Freddy moves, and
                scan his cameras every few seconds to show his route.

usage: python tools/demo_events.py bonnie-tell [--seconds 300]
Press F8 to stop early.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fnafbot import config, layout, menu  # noqa: E402
from fnafbot.controller import LEFT, RIGHT, Controller  # noqa: E402
from fnafbot.overlay import StatusOverlay  # noqa: E402
from fnafbot.screen import GameWindow  # noqa: E402
from fnafbot.vision import Vision  # noqa: E402

log = logging.getLogger("demo")

FREDDY_ROUTE = ["1A", "1B", "7", "6", "4A", "4B"]
BONNIE_CAMS = ["1A", "1B", "5", "2A", "2B"]
CHICA_CAMS = ["1A", "1B", "7", "6", "4A", "4B"]


class Demo:
    """Shared helpers: captions, light checks that do NOT shut the door, timing."""

    def __init__(self, seconds: float) -> None:
        self.window = menu.open_game()
        self.vision = Vision()
        self.ctl = Controller(self.window, self.vision)
        self.overlay = StatusOverlay()
        self.stop = threading.Event()
        try:
            import keyboard
            keyboard.add_hotkey(config.STOP_HOTKEY, self.stop.set)
        except Exception:
            pass
        self.end_at = time.monotonic() + seconds
        self.started = 0.0

    # -- flow ----------------------------------------------------------------

    def start_night(self) -> None:
        menu.choose(self.window, "continue")
        self.caption("Starting the saved night (Continue)")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self.vision.hud_visible(self.window.grab()):
                self.started = time.monotonic()
                return
            time.sleep(0.05)
        raise RuntimeError("The night did not start")

    def running(self) -> bool:
        """False once the night ended (HUD gone for a second), time is up, or F8."""
        if self.stop.is_set() or time.monotonic() > self.end_at:
            return False
        gone_since = None
        while True:
            if self.vision.hud_visible(self.window.grab()):
                return True
            gone_since = gone_since or time.monotonic()
            if time.monotonic() - gone_since > 1.0:
                return False
            time.sleep(0.05)

    def caption(self, text: str, alert: bool = False) -> None:
        log.info(text)
        self.ctl.grab()
        hud = self.ctl.hud
        self.overlay.show(action=text, alert=alert,
                          status=f"DEMO | Power {hud.power if hud.power is not None else '?'}% | "
                                 f"{time.monotonic() - self.started:5.1f} s into the night",
                          threats="This is a staged demonstration, not the bot playing")

    def pause(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end and not self.stop.is_set():
            time.sleep(0.05)

    # -- looking without protecting ------------------------------------------

    def light_check(self, side: str) -> str:
        """Flash a hall light and say what the doorway shows: 'dark' (the
        light did not come on), 'empty' or 'occupied'. Unlike the bot, this
        never shuts the door."""
        ctl = self.ctl
        ctl.face(side)
        ctl.press(layout.LEFT_LIGHT_BUTTON if side == LEFT else layout.RIGHT_LIGHT_BUTTON)
        state = "dark"
        deadline = time.monotonic() + 0.35
        while time.monotonic() < deadline:
            seen, margin = self.vision.doorway_state(self.window.grab(), side)
            if seen != "dark" and margin > 1.5:
                state = seen
                break
        ctl.press(layout.LEFT_LIGHT_BUTTON_OFF if side == LEFT else layout.RIGHT_LIGHT_BUTTON_OFF)
        return state

    def look(self, camera: str, hold: float = 0.6):
        """Show a camera for a moment (so the viewer sees it too) and read it."""
        reading = self.ctl.view(camera)
        self.pause(hold)
        return reading

    def monitor_down(self) -> None:
        self.ctl.camera_down()

    def finish(self, text: str) -> None:
        self.caption(text)
        self.pause(4.0)
        self.overlay.close()


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------


def bonnie_tell(demo: Demo) -> None:
    demo.ctl.set_door(RIGHT, True)
    demo.caption("Demo: the LEFT door stays OPEN on purpose. Right door shut so only Bonnie can come.")
    demo.pause(3)
    seen_at_door = False
    dark_in_a_row = 0
    last_cam_look = 0.0
    while demo.running():
        if not seen_at_door and time.monotonic() - last_cam_look > 9:
            last_cam_look = time.monotonic()
            for cam in BONNIE_CAMS:
                reading = demo.look(cam, 0.5)
                if "B" in reading.occupants:
                    demo.caption(f"Bonnie seen on CAM {cam} - heading for the left door")
                    demo.pause(1.5)
                    break
            demo.monitor_down()
        state = demo.light_check(LEFT)
        if state == "occupied":
            seen_at_door = True
            dark_in_a_row = 0
            demo.caption("BONNIE AT THE LEFT DOOR. A player closes it now - we don't.", alert=True)
        elif state == "dark" and seen_at_door:
            dark_in_a_row += 1
            if dark_in_a_row >= 2:
                demo.caption("The light will NOT come on: Bonnie is inside, the game disables the switch.", alert=True)
        elif state == "empty":
            demo.caption("Left light: doorway empty")
        demo.pause(2.0)
    demo.finish("Night lost. The old bot would have logged this as SURVIVED (docs/DEVLOG.md).")


def chica_window(demo: Demo) -> None:
    demo.ctl.set_door(LEFT, True)
    demo.caption("Demo: watching the RIGHT window for Chica (left door shut).")
    closed = False
    last_cam_look = 0.0
    while demo.running():
        if not closed and time.monotonic() - last_cam_look > 9:
            last_cam_look = time.monotonic()
            for cam in CHICA_CAMS:
                reading = demo.look(cam, 0.5)
                if "C" in reading.occupants:
                    demo.caption(f"Chica seen on CAM {cam}")
                    demo.pause(1.5)
                    break
            demo.monitor_down()
        state = demo.light_check(RIGHT)
        if state == "occupied" and not closed:
            demo.caption("CHICA AT THE WINDOW - door closed", alert=True)
            demo.ctl.set_door(RIGHT, True)
            closed = True
        elif closed and state == "empty":
            demo.caption("She has gone back - the door can open again (this is what a peek is for)")
            demo.ctl.set_door(RIGHT, False)
            demo.pause(3)
            break
        elif closed:
            demo.caption("Door shut; peeking to see whether Chica has left")
        else:
            demo.caption("Right light: window empty")
        demo.pause(2.5)
    demo.finish("Chica demo done")


def foxy_run(demo: Demo) -> None:
    demo.ctl.set_door(LEFT, True)
    demo.ctl.set_door(RIGHT, True)
    demo.caption("Demo: both doors shut. Waiting for Foxy to leave Pirate Cove (CAM 1C).")
    while demo.running():
        reading = demo.look("1C", 0.8)
        stage = reading.foxy_stage
        if stage is None:
            demo.caption("Pirate Cove: unreadable picture, looking again")
        elif stage >= 3:
            demo.caption("FOXY HAS LEFT THE COVE. Viewing West Hall (CAM 2A) makes him run NOW.", alert=True)
            demo.pause(1.5)
            demo.ctl.view("2A")
            demo.caption("Foxy running down the west hall (100 frames to the door)", alert=True)
            demo.pause(2.0)
            demo.monitor_down()
            demo.pause(2.5)
            demo.caption("He banged on the CLOSED left door: a power penalty instead of a jumpscare")
            demo.pause(3)
            break
        else:
            demo.caption(f"Pirate Cove: Foxy at stage {stage} of 3 (he only moves while the monitor is down)")
        demo.monitor_down()
        demo.pause(8.0)
    demo.finish("Foxy demo done")


def freddy_walk(demo: Demo) -> None:
    demo.ctl.set_door(LEFT, True)
    demo.ctl.set_door(RIGHT, True)
    demo.caption("Demo: both doors shut, monitor down. Freddy only moves while nobody is watching.")
    last_seen = None
    while demo.running():
        demo.pause(10.0)
        found = None
        for cam in FREDDY_ROUTE:
            reading = demo.look(cam, 0.5)
            if "F" in reading.occupants:
                found = cam
                break
        demo.monitor_down()
        if found and found != last_seen:
            last_seen = found
            demo.caption(f"Freddy is on CAM {found}" + (" - next to the office!" if found == "4B" else ""))
        elif found:
            demo.caption(f"Freddy still on CAM {found}")
        else:
            demo.caption("Freddy not found on his route this scan")
        if found == "4B":
            demo.pause(4)
            demo.caption("From 4B he can only enter through an OPEN right door while a camera shows - never here.")
            demo.pause(4)
            break
    demo.finish("Freddy demo done")


SCENES = {
    "bonnie-tell": bonnie_tell,
    "chica-window": chica_window,
    "foxy-run": foxy_run,
    "freddy-walk": freddy_walk,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scene", choices=sorted(SCENES))
    parser.add_argument("--seconds", type=float, default=300.0, help="give up after this long")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", stream=sys.stdout)

    demo = Demo(args.seconds)
    demo.start_night()
    try:
        SCENES[args.scene](demo)
    finally:
        demo.overlay.close()


if __name__ == "__main__":
    main()
