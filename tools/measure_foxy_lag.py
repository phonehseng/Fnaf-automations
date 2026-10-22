"""Does Foxy's timer fall behind like Bonnie's and Chica's? Measured on one night.

Live 4/20 #9 was lost to a Foxy who went from a clean stage 0 to a run in
under a minute while every camera flip in between was logged as covering
his tick - which the game's rules only allow if his ticks came BEFORE the
flips (docs/DEVLOG.md). His phase was measured on a quiet night; the other
timers fall behind real time on camera-heavy nights. This measures both on
the same night:

  * Chica's ticks from the right hall light (the game switches the lights
    off on the frame she arrives at or leaves her doorway) - the lag of the
    "every N seconds" timers, as in tools/measure_timer_clock.py;
  * Foxy's ticks from his bangs: at stage 3 he leaves exactly 1500 frames
    later (events [318]-[320]) and, with the left door shut, bangs on it -
    the power drops on that very frame (event [324]). So bang - 1501 frames
    is the tick that took him to stage 3.

A raised camera freezes Foxy, so the night has two phases: for the first
--camera-until seconds the camera is up for most of every cycle (that is
what makes the timers fall behind - on cold starts the lag then stays
flat), after that it stays down and Foxy is free to advance and bang.

Custom Night 0/0/20/20 (Chica and Foxy). The left door stays shut all
night. The night is lost to the battery after a few bangs - that is
expected and harmless.

usage: python tools/measure_foxy_lag.py [--camera-until 100] [--seconds 420]
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

CHICA = rules.TICK_PERIOD["chica"]
FOXY = rules.TICK_PERIOD["foxy"]
FUSE_SECONDS = 1501 / 60       # stage 3 -> bang, at 60 frames per second
WATCH_BEFORE = 0.7             # light on this long before Chica's predicted tick ...
WATCH_AFTER = 0.7              # ... until this long after
OFF_CHARGE = 0.2               # a power drop this far from a whole game second is not a charge


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera-until", type=float, default=100.0)
    parser.add_argument("--seconds", type=float, default=420.0)
    args = parser.parse_args()

    window = menu.open_game()
    vision = Vision()
    ctl = Controller(window, vision)
    menu.choose(window, "custom", {"freddy": 0, "bonnie": 0, "chica": 20, "foxy": 20})
    body = RealBody(ctl, vision)
    body.start_clock()

    # The left door stays shut all night: Foxy bangs on it instead of coming in.
    ctl.face(LEFT)
    time.sleep(0.4)
    ctl.press(layout.LEFT_DOOR_BUTTON)
    time.sleep(0.6)
    ctl.face(RIGHT)
    time.sleep(0.6)

    def real_now() -> float:
        return time.perf_counter() - body.real_origin

    # Every look at the screen also reads the HUD, so power drops (Foxy's
    # bangs) are timed as closely as the lamp.
    power_events: list[tuple[float, float, int, int]] = []   # (game s, real s, before, after)
    last = {"power": None}

    def look():
        frame = body._observe()
        power = body.last_power
        if power is not None and last["power"] is not None and power < last["power"]:
            power_events.append((body.now(), real_now(), last["power"], power))
        if power is not None:
            last["power"] = power
        return frame

    def lamp_on() -> bool:
        return vision.light_lamp_on(look(), RIGHT)

    def wait(t: float) -> None:
        while body.now() < t and not body.night_over():
            look()

    def light_on() -> None:
        """Switch the right light on and make sure it stays on (lowering the
        monitor switches the lights off by itself a frame or two later)."""
        for _ in range(5):
            wait(body.now() + 0.12)
            if lamp_on():
                wait(body.now() + 0.12)
                if lamp_on():
                    return
            ctl.press(layout.RIGHT_LIGHT_BUTTON)

    def light_off() -> None:
        if lamp_on():
            ctl.press(layout.RIGHT_LIGHT_BUTTON)

    chica: list[tuple[float, float, str]] = []      # (game s, real s, what)
    door_shut = False
    anchor_game, anchor_real = 0.0, 0.0
    end = time.monotonic() + args.seconds
    while time.monotonic() < end and not body.night_over():
        n_game = int((body.now() - anchor_game) / CHICA) + 1
        n_real = int((real_now() - anchor_real) / CHICA) + 1
        n = max(1, min(n_game, n_real))
        pred_game = anchor_game + n * CHICA
        pred_real_as_game = body.real_to_game(anchor_real + n * CHICA)
        start = min(pred_game, pred_real_as_game) - WATCH_BEFORE
        stop = max(pred_game, pred_real_as_game) + WATCH_AFTER

        if body.now() < args.camera_until and start - body.now() > 1.6:
            ctl.camera_up()
            wait(start - 0.9)
            ctl.camera_down()
            ctl.face(RIGHT)
        wait(max(body.now(), start - 0.35))
        light_on()

        seen = None
        while body.now() < stop and not body.night_over():
            if not lamp_on():
                seen = (body.now(), real_now())
                break
        if seen is None:
            light_off()
            wait(stop + 0.05)
            continue
        game_t, real_t = seen
        what = "left the door" if door_shut else "arrived"
        chica.append((game_t, real_t, what))
        k = round(real_t / CHICA)
        print(f"{game_t:8.3f} s  (real {real_t:8.3f})  chica {what}   lag {real_t - k * CHICA:+.3f}", flush=True)
        anchor_game, anchor_real = game_t, real_t
        wait(body.now() + 0.3)
        ctl.press(layout.RIGHT_DOOR_BUTTON)       # arrived: shut it / left: open it
        door_shut = not door_shut
        wait(body.now() + 0.6)

    # ---- results ------------------------------------------------------------
    print(f"\nclock: game second = {body.scale:.4f} real s at the end")
    print("\nChica (lamp), lag = real time - k x 4.98 s:")
    for game_t, real_t, what in chica:
        k = round(real_t / CHICA)
        print(f"  {real_t:8.3f} s  {what:14s}  lag {real_t - k * CHICA:+.3f}")

    print("\nPower drops (a bang is one that does not fall on a whole-second charge, or is 2 % or more):")
    for game_t, real_t, before, after in power_events:
        off = game_t - math.floor(game_t)
        bang = OFF_CHARGE < off < 1 - OFF_CHARGE or before - after >= 2
        line = f"  {real_t:8.3f} s real  {before}% -> {after}%"
        if bang:
            tick_real = real_t - FUSE_SECONDS
            k = round(tick_real / FOXY)
            line += (f"   BANG: stage-3 tick at real {tick_real:8.3f} s = k {k} {tick_real - k * FOXY:+.3f}"
                     f"  (quiet-night phase was -0.05 .. -0.16)")
        print(line)
    print("\nCompare Foxy's offsets with Chica's lags at the same time: if Foxy's timer"
          " falls behind like hers, his offset = her lag - ~0.1 s. Each sighting is up to"
          " one look (~0.02 s) late.")


if __name__ == "__main__":
    main()
