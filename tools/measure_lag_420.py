"""The timers' lag on a night loaded like 4/20: all four animatronics at 20.

The measurement nights so far had one or two animatronics active and found
the "every N seconds" timers 0.5 - 0.8 s behind real time a minute into a
cold start - but live 4/20 #11 needed ~1.3 s by 75 s to explain Bonnie
being inside already (docs/DEVLOG.md). A 4/20 night loads the game far
more (four animatronics moving, more pictures). This measures the lag on
exactly such a night:

  * Custom Night 20/20/20/20, BOTH doors shut all night: Bonnie and Chica
    cannot get in, Freddy cannot either (he needs the right door open), and
    Foxy bangs on the left door if he runs (his bangs time his ticks too).
  * Bonnie and Chica still walk up to the doors and are sent back, and the
    game switches the hall lights off on the frame either of them arrives
    at or leaves a doorway (events [226]/[227], [259]/[260]). So the left
    light is kept on in a window around each of their predicted ticks, and
    the moment its lamp goes dark is a tick of one of them.
  * Between the windows the camera comes up like the bot's flips (4B, and
    Pirate Cove every third cycle): the same kind of load. Foxy's lock
    from a view lasts 50 + Random(1000) frames, so he mostly stays put.

The battery runs out after a few minutes (two doors shut) - expected.

usage: python tools/measure_lag_420.py [--seconds 420]
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

BONNIE = rules.TICK_PERIOD["bonnie"]
CHICA = rules.TICK_PERIOD["chica"]
FOXY = rules.TICK_PERIOD["foxy"]
PHASE = {"bonnie": rules.TICK_PHASE["bonnie"], "chica": rules.TICK_PHASE["chica"]}
WATCH_BEFORE = 0.4     # light on this long before the predicted tick ...
WATCH_AFTER = 1.2      # ... until this long after (the lag may jump between samples)
FUSE_SECONDS = 1501 / 60
OFF_CHARGE = 0.2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=420.0)
    args = parser.parse_args()

    window = menu.open_game()
    vision = Vision()
    ctl = Controller(window, vision)
    menu.choose(window, "custom", {"freddy": 20, "bonnie": 20, "chica": 20, "foxy": 20})
    body = RealBody(ctl, vision)
    body.start_clock()

    def real_now() -> float:
        return time.perf_counter() - body.real_origin

    power_events: list[tuple[float, float, int, int]] = []
    last = {"power": None}

    def look():
        frame = body._observe()
        power = body.last_power
        if power is not None and last["power"] is not None and power < last["power"]:
            power_events.append((body.now(), real_now(), last["power"], power))
        if power is not None:
            last["power"] = power
        return frame

    def wait(t: float) -> None:
        while body.now() < t and not body.night_over():
            look()

    def lamp_on() -> bool:
        return vision.light_lamp_on(look(), LEFT)

    def light_on() -> bool:
        for _ in range(5):
            wait(body.now() + 0.1)
            if lamp_on():
                wait(body.now() + 0.1)
                if lamp_on():
                    return True
            ctl.press(layout.LEFT_LIGHT_BUTTON)
        return False

    def light_off() -> None:
        if lamp_on():
            ctl.press(layout.LEFT_LIGHT_BUTTON)

    # Both doors shut, facing left (the left light is the one watched).
    ctl.face(RIGHT)
    time.sleep(0.5)
    ctl.press(layout.RIGHT_DOOR_BUTTON)
    time.sleep(0.6)
    ctl.face(LEFT)
    time.sleep(0.5)
    ctl.press(layout.LEFT_DOOR_BUTTON)
    time.sleep(0.6)
    print(f"doors shut at {body.now():.2f} s", flush=True)

    # (real s, lag if Bonnie's tick, lag if Chica's tick)
    events: list[tuple[float, float, float]] = []
    lag_est = 0.0                 # latest sample (the earlier of the two readings)
    cycle = 0
    end = time.monotonic() + args.seconds
    while time.monotonic() < end and not body.night_over():
        # Next Bonnie/Chica tick (their ticks are within 0.01 x k s of each
        # other: watch from the earlier to the later), with the lag so far.
        now_real = real_now()
        kb = math.floor((now_real - lag_est - PHASE["bonnie"]) / BONNIE) + 1
        kc = math.floor((now_real - lag_est - PHASE["chica"]) / CHICA) + 1
        tb = kb * BONNIE + PHASE["bonnie"] + lag_est
        tc = kc * CHICA + PHASE["chica"] + lag_est
        first, last_tick = min(tb, tc), max(tb, tc)
        if last_tick - first > 2.5:          # far apart late in the night: one at a time
            last_tick = first
        start_real = first - WATCH_BEFORE
        stop_real = last_tick + WATCH_AFTER

        # Camera flip in the gap before the window, like the bot's (4B; the
        # cove every third cycle).
        to_start = start_real - real_now()
        if to_start > 2.4:
            cycle += 1
            ctl.camera_up()
            if cycle % 3 == 0:
                ctl.select_camera_blind("1C")
                wait(body.now() + 0.9)
                ctl.select_camera_blind("4B")
            up_until = body.real_to_game(start_real - 1.0)
            wait(max(body.now() + 0.5, up_until))
            ctl.camera_down()
            ctl.face(LEFT)
        wait(body.real_to_game(start_real) - 0.25)
        if not light_on():
            print(f"{body.now():8.2f} s  light would not come on", flush=True)
            wait(body.real_to_game(stop_real))
            continue

        seen = None
        while real_now() < stop_real and not body.night_over():
            if not lamp_on():
                seen = real_now()
                break
        if seen is None:
            light_off()
            continue
        lb = seen - (round((seen - PHASE["bonnie"] - lag_est) / BONNIE) * BONNIE + PHASE["bonnie"])
        lc = seen - (round((seen - PHASE["chica"] - lag_est) / CHICA) * CHICA + PHASE["chica"])
        events.append((seen, lb, lc))
        lag_est = max(0.0, min(lb, lc))
        print(f"{body.now():8.2f} s (real {seen:8.3f})  lights out: lag {lb:+.3f} if Bonnie, "
              f"{lc:+.3f} if Chica", flush=True)
        wait(body.now() + 0.4)

    print(f"\nclock: game second = {body.scale:.4f} real s at the end")
    print("\nLights-out events (real s): lag if it was Bonnie's tick / Chica's tick")
    for seen, lb, lc in events:
        print(f"  {seen:8.3f}   {lb:+.3f} / {lc:+.3f}")
    print("\nPower drops (a bang = off a whole-second charge, or 2 % or more):")
    for game_t, real_t, before, after in power_events:
        off = game_t - math.floor(game_t)
        if OFF_CHARGE < off < 1 - OFF_CHARGE or before - after >= 2:
            tick = real_t - FUSE_SECONDS
            k = round(tick / FOXY)
            print(f"  {real_t:8.3f} s  {before}% -> {after}%   Foxy's stage-3 tick then at "
                  f"k {k} {tick - k * FOXY:+.3f} (quiet phase ~ -0.1)")


if __name__ == "__main__":
    main()
