"""When do Bonnie's / Chica's ticks really happen? Measured from the hall light.

The game switches the hall lights off on the very frame Bonnie or Chica
arrives at or leaves a doorway (decompiled events [226], [227], [259],
[260]). So with the light kept on, the light button's lamp going dark - when
the bot did not click it - timestamps one of their ticks to within one HUD
look (~0.02 s), far better than watching a camera (tools/measure_ticks.py).

This plays a Custom Night with only the chosen animatronic active (AI 20, so
every tick is a move): light on with the door open until they arrive, then
the door shut (they are sent back on their next tick - the light goes off
again), then the door open and the light on again, and so on.

usage: python tools/measure_door_ticks.py --who bonnie [--seconds 240]
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fnafbot import layout, menu, rules  # noqa: E402
from fnafbot.body import RealBody  # noqa: E402
from fnafbot.controller import LEFT, RIGHT, Controller  # noqa: E402
from fnafbot.vision import Vision  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--who", choices=("bonnie", "chica"), required=True)
    parser.add_argument("--seconds", type=float, default=240.0)
    parser.add_argument("--camera", action="store_true",
                        help="raise the camera between their ticks (slows the game clock) to test "
                             "whether their timers slow down with it")
    args = parser.parse_args()
    side = LEFT if args.who == "bonnie" else RIGHT
    light = layout.LEFT_LIGHT_BUTTON if side == LEFT else layout.RIGHT_LIGHT_BUTTON
    door = layout.LEFT_DOOR_BUTTON if side == LEFT else layout.RIGHT_DOOR_BUTTON
    period = rules.TICK_PERIOD[args.who]

    window = menu.open_game()
    vision = Vision()
    ctl = Controller(window, vision)
    levels = {"freddy": 0, "bonnie": 0, "chica": 0, "foxy": 0, args.who: 20}
    menu.choose(window, "custom", levels)
    body = RealBody(ctl, vision)
    body.start_clock()
    ctl.face(side)
    time.sleep(0.6)

    def lamp_on() -> bool:
        return vision.light_lamp_on(window.grab(), side)

    events: list[tuple[float, float, str]] = []    # (game seconds, real seconds, what)
    door_shut = False
    ctl.press(light)
    end = time.monotonic() + args.seconds
    while time.monotonic() < end and not body.night_over():
        body.wait_until(body.now() + 0.005)
        if args.camera:
            # Raise the camera while their next tick (either model) is far
            # away: the camera's static makes the game drop frames.
            to_next = period - ((time.perf_counter() - body.real_origin) % period)
            if 1.4 < to_next < period - 0.6:
                ctl.camera_up()
                time.sleep(max(0.0, to_next - 1.2))
                ctl.camera_down()
                ctl.face(side)
                # Lowering the monitor switches the hall lights off by
                # itself (events [226]/[227] fire again once "viewing" is
                # 0), possibly a frame after our click. So switch the light
                # on, and keep at it until the lamp stays lit - otherwise
                # that switch-off is mistaken for their tick.
                for _ in range(4):
                    time.sleep(0.15)
                    if lamp_on():
                        break
                    ctl.press(light)
                continue
        if lamp_on():
            continue
        # The light went off by itself: a tick of theirs just happened.
        t = body.now()
        real_t = time.perf_counter() - body.real_origin   # the fixed origin the brain uses
        what = "left the door" if door_shut else "arrived"
        events.append((t, real_t, what))
        print(f"{t:8.3f} s  {args.who} {what}", flush=True)
        time.sleep(0.3)
        if not door_shut:
            ctl.press(door)            # shut it: they are sent back on their next tick
            door_shut = True
        else:
            ctl.press(door)            # gone: open again and wait for the next visit
            door_shut = False
            time.sleep(0.6)
        time.sleep(0.3)
        ctl.press(light)
        time.sleep(0.3)

    print(f"\nclock: game second = {body.scale:.4f} real s at the end; {len(events)} ticks seen")
    print(f"{'game s':>9} {'real s':>9}  {'event':14s} {'real-time model':>18} {'game-time model':>18}")
    real_res, game_res = [], []
    for t, real_t, what in events:
        kr = round(real_t / period)
        kg = round(t / period)
        real_res.append(real_t - kr * period)
        game_res.append(t - kg * period)
        print(f"{t:9.3f} {real_t:9.3f}  {what:14s} {kr:4d} {real_res[-1]:+8.3f} s   {kg:4d} {game_res[-1]:+8.3f} s")
    for name, res in (("real-time", real_res), ("game-time", game_res)):
        if res:
            print(f"{name} model: offsets {min(res):+.3f} .. {max(res):+.3f} s (spread {max(res) - min(res):.3f})")
    print("The model whose offsets stay put (no drift with time) is how their timer runs;"
          " each tick is seen up to one look (~0.02 s) late.")


if __name__ == "__main__":
    main()
