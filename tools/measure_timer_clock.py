"""Which clock do the movement timers follow: real time, or the game's clock?

The game's own clock (the one the power readout and 6 AM follow) runs
slower than real time while the camera is up - up to 0.65 % slower. So on
a camera-heavy night the two clocks drift apart by a second or more, and a
bot that computes Bonnie's ticks on the wrong one is late or early by that
much (live 4/20 #8 was lost to it - docs/DEVLOG.md).

This plays a Custom Night with only Bonnie active (AI 20, so every tick is
a move) and keeps the camera up for most of each 4.97 s cycle, to make the
clocks drift apart as fast as possible. Ticks are timestamped from the hall
light: the game switches the lights off on the frame Bonnie arrives at or
leaves the left doorway (events [226]/[227]). Only those ticks can be seen,
so each prediction is anchored on the last tick actually seen, and the
light is kept on across a window that covers BOTH clocks' prediction.

With --warmup, the first ~12 s of the night are spent doing once
everything the bot does in a night (both doors shut and opened, both
lights, every camera viewed): if the lag comes from the game loading things
the first time they are used, it all happens then, and stays flat after.

usage: python tools/measure_timer_clock.py [--seconds 540] [--warmup]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fnafbot import layout, menu, rules  # noqa: E402
from fnafbot.body import RealBody  # noqa: E402
from fnafbot.controller import LEFT, RIGHT, Controller  # noqa: E402
from fnafbot.vision import Vision  # noqa: E402

PERIOD = rules.TICK_PERIOD["bonnie"]
WATCH_BEFORE = 0.7      # light on this long before the earliest prediction ...
WATCH_AFTER = 0.7       # ... until this long after the latest one


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=540.0)
    parser.add_argument("--warmup", action="store_true")
    args = parser.parse_args()

    window = menu.open_game()
    vision = Vision()
    ctl = Controller(window, vision)
    menu.choose(window, "custom", {"freddy": 0, "bonnie": 20, "chica": 0, "foxy": 0})
    body = RealBody(ctl, vision)
    body.start_clock()
    if args.warmup:
        for side, door, light in ((LEFT, layout.LEFT_DOOR_BUTTON, layout.LEFT_LIGHT_BUTTON),
                                  (RIGHT, layout.RIGHT_DOOR_BUTTON, layout.RIGHT_LIGHT_BUTTON)):
            ctl.face(side)
            time.sleep(0.6)
            for button, pause in ((door, 0.7), (door, 0.7), (light, 0.35), (light, 0.35)):
                ctl.press(button)
                time.sleep(pause)
        ctl.camera_up()
        for camera in layout.CAMERA_BUTTONS:
            ctl.select_camera_blind(camera)
            time.sleep(0.4)
        ctl.select_camera_blind("4B")
        time.sleep(0.3)
        ctl.camera_down()
        print(f"warm-up done at {body.now():.2f} s (real {time.perf_counter() - body.real_origin:.2f})", flush=True)
    ctl.face(LEFT)
    time.sleep(0.6)

    def real_now() -> float:
        return time.perf_counter() - body.real_origin

    def lamp_on() -> bool:
        return vision.light_lamp_on(window.grab(), LEFT)

    def light_on() -> None:
        """Switch the left light on and make sure it stays on (lowering the
        monitor switches the lights off by itself a frame or two later)."""
        for _ in range(5):
            body.wait_until(body.now() + 0.12)
            if lamp_on():
                body.wait_until(body.now() + 0.12)
                if lamp_on():
                    return
            ctl.press(layout.LEFT_LIGHT_BUTTON)

    def light_off() -> None:
        if lamp_on():
            ctl.press(layout.LEFT_LIGHT_BUTTON)

    # (game s, real s, what) for every tick seen
    events: list[tuple[float, float, str]] = []
    door_shut = False
    # Anchor: the last tick seen, on both clocks. Before any is seen, the
    # night start (tick 0) on both.
    anchor_game, anchor_real = 0.0, 0.0
    end = time.monotonic() + args.seconds
    while time.monotonic() < end and not body.night_over():
        # Next tick after now, predicted on each clock from the anchor.
        n_game = int((body.now() - anchor_game) / PERIOD) + 1
        n_real = int((real_now() - anchor_real) / PERIOD) + 1
        n = max(1, min(n_game, n_real))
        pred_game = anchor_game + n * PERIOD                                   # game seconds
        pred_real_as_game = body.real_to_game(anchor_real + n * PERIOD)        # real model, in game seconds
        start = min(pred_game, pred_real_as_game) - WATCH_BEFORE
        stop = max(pred_game, pred_real_as_game) + WATCH_AFTER

        # Camera up until shortly before the watch window (the slow-down).
        if start - body.now() > 1.6:
            ctl.camera_up()
            body.wait_until(start - 0.9)
            ctl.camera_down()
            ctl.face(LEFT)
        body.wait_until(max(body.now(), start - 0.35))
        light_on()

        # Watch the lamp across the window.
        seen = None
        while body.now() < stop and not body.night_over():
            if not lamp_on():
                seen = (body.now(), real_now())
                break
        if seen is None:
            light_off()       # a tick that did not involve the doorway
            # Skip past this prediction before planning the next one.
            body.wait_until(stop + 0.05)
            continue

        game_t, real_t = seen
        what = "left the door" if door_shut else "arrived"
        events.append((game_t, real_t, what))
        k = round(real_t / PERIOD)
        print(f"{game_t:8.3f} s  (real {real_t:8.3f})  bonnie {what}   offset {real_t - k * PERIOD:+.3f}", flush=True)
        anchor_game, anchor_real = game_t, real_t
        body.wait_until(body.now() + 0.3)
        ctl.press(layout.LEFT_DOOR_BUTTON)      # arrived: shut it / left: open it
        door_shut = not door_shut
        body.wait_until(body.now() + 0.6)

    print(f"\nclock: game second = {body.scale:.4f} real s at the end; {len(events)} ticks seen")
    print(f"{'game s':>9} {'real s':>9}  {'event':14s} {'k':>4} {'real model':>11} {'game model':>11}")
    real_res, game_res = [], []
    for game_t, real_t, what in events:
        k_real, k_game = round(real_t / PERIOD), round(game_t / PERIOD)
        real_res.append(real_t - k_real * PERIOD)
        game_res.append(game_t - k_game * PERIOD)
        print(f"{game_t:9.3f} {real_t:9.3f}  {what:14s} {k_game:4d} {real_res[-1]:+10.3f}s {game_res[-1]:+10.3f}s")
    for name, res in (("real-time", real_res), ("game-time", game_res)):
        if res:
            print(f"{name} model: offsets {min(res):+.3f} .. {max(res):+.3f} s (spread {max(res) - min(res):.3f})")
    print("The model whose offsets stay put is the clock the timers follow"
          " (each tick is seen up to one look, ~0.02 s, late).")


if __name__ == "__main__":
    main()
