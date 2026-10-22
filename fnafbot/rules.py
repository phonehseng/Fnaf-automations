"""The game's rules as numbers, taken from the game's own event code.

Every value here is explained (with the event numbers it comes from) in
docs/GAME_LOGIC.md. Both the simulator (sim.py) and the bot's brain
(brain.py) read from this file, so the two can never disagree.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

FPS = 60                       # the game runs at 60 frames per second
FRAME = 1.0 / FPS

# How many REAL seconds one of the game's "every 1 second" ticks takes.
# Measured on the live game: 6 AM (after 535 game seconds) arrived about
# 538.5 real seconds after the night's first frame, in every logged night.
# Every animatronic timer is the same kind of Clickteam timer, so all tick
# times in this file are in GAME seconds; the body converts (see
# docs/DEVLOG.md, "the game's clock runs slow").
TICK_SECONDS = 1.0065

# The animatronics' movement timers do NOT stretch like the power timer:
# measured live (tools/measure_ticks.py), Bonnie's room changes land at
# 0.5 + k * 4.97 REAL seconds after the night start, with no drift, while
# the power readout drops every 1.0065 real seconds. Chica walked in on a
# click made 0.05 s after k * 4.98 real seconds, so her timer has no such
# offset. The brain converts movement ticks with the measured scale (see
# Brain._next_tick); each timer's phase is listed here, a little on the
# early side so that errors fall on the safe side. Foxy's is unmeasured.
# Measured against the bot's HUD-based night start: Bonnie +0.44..+0.62 s,
# Chica +0.59..+0.79 s (tools/measure_ticks.py, 2026-10-22). Foxy unmeasured.
TICK_PHASE = {"bonnie": 0.5, "chica": 0.6, "foxy": 0.0}

FIRST_HOUR_SECONDS = 90        # 12 AM lasts 90 s ...
HOUR_SECONDS = 89              # ... every later hour 89 s
NIGHT_SECONDS = FIRST_HOUR_SECONDS + 5 * HOUR_SECONDS   # 6 AM at 535 s

# Movement opportunity ("tick") intervals in seconds.
BONNIE_TICK = 4.97
CHICA_TICK = 4.98
FREDDY_TICK = 3.02
FOXY_TICK = 5.01
POWER_TICK = 1.0               # power is charged only at these instants
TICK_PERIOD = {"bonnie": BONNIE_TICK, "chica": CHICA_TICK, "foxy": FOXY_TICK}

# ---------------------------------------------------------------------------
# Power (in tenths of a percent: 999 = 99.9 %)
# ---------------------------------------------------------------------------

START_POWER = 999
# Extra passive drain: 1 unit every N seconds on these nights.
PASSIVE_DRAIN_PERIOD = {2: 6, 3: 5, 4: 4, 5: 3, 6: 3, 7: 3}

# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------

CLICK_COOLDOWN_FRAMES = 10     # door/light clicks are ignored for 10 frames after one

# Animation lengths measured on the live game (see tools/measure_timings.py).
DOOR_CLOSE_SECONDS = 0.55      # click -> door counts as "fully closed"
DOOR_OPEN_SECONDS = 0.45       # click -> door counts as "fully open"
CAMERA_UP_SECONDS = 0.55       # touch the bar -> camera picture showing (measured 0.50-0.61 s)
CAMERA_DOWN_SECONDS = 0.30     # touch it again -> camera stops at once; monitor gone ~0.3 s later

# ---------------------------------------------------------------------------
# AI levels
# ---------------------------------------------------------------------------

ANIMATRONICS = ("freddy", "bonnie", "chica", "foxy")

NIGHT_AI = {
    1: {"freddy": 0, "bonnie": 0, "chica": 0, "foxy": 0},
    2: {"freddy": 0, "bonnie": 3, "chica": 1, "foxy": 1},
    3: {"freddy": 1, "bonnie": 0, "chica": 5, "foxy": 2},
    4: {"freddy": 2, "bonnie": 2, "chica": 4, "foxy": 6},  # Freddy is 1 or 2 at random; plan for 2
    5: {"freddy": 3, "bonnie": 5, "chica": 7, "foxy": 5},
    6: {"freddy": 4, "bonnie": 10, "chica": 12, "foxy": 6},
}

# Added at the start of these hours, on every night including custom night.
HOURLY_AI_INCREASE = {
    2: {"bonnie": 1},
    3: {"bonnie": 1, "chica": 1, "foxy": 1},
    4: {"bonnie": 1, "chica": 1, "foxy": 1},
}


def ai_levels(night: int, hour: int, custom: dict[str, int] | None = None) -> dict[str, int]:
    """AI level of each animatronic on ``night`` during ``hour`` (12, 1, ... 5).

    A level above 20 behaves exactly like 20 (the roll is 1-20)."""
    levels = dict(custom if night == 7 and custom else NIGHT_AI.get(night, NIGHT_AI[6]))
    for at_hour, increases in HOURLY_AI_INCREASE.items():
        if hour != 12 and hour >= at_hour:
            for name, extra in increases.items():
                levels[name] += extra
    return {name: min(level, 20) for name, level in levels.items()}


def move_chance(ai: int) -> float:
    """Probability that one tick results in a move (roll 1-20 <= AI)."""
    return max(0, min(ai, 20)) / 20.0


def hour_at(seconds: float) -> int:
    """Clock hour shown at ``seconds`` into the night: 12, 1, 2, ... 6."""
    if seconds < FIRST_HOUR_SECONDS:
        return 12
    return min(6, 1 + int((seconds - FIRST_HOUR_SECONDS) // HOUR_SECONDS))


def tick_times(interval: float, start: float, end: float) -> list[float]:
    """All tick instants of a timer with ``interval`` inside [start, end)."""
    first = max(1, math.ceil(start / interval - 1e-9))
    times = []
    k = first
    while k * interval < end:
        times.append(k * interval)
        k += 1
    return times


def next_tick(interval: float, after: float) -> float:
    """The first tick strictly after ``after``."""
    return (math.floor(after / interval + 1e-9) + 1) * interval


def previous_tick(interval: float, at_or_before: float) -> float:
    """The last tick at or before ``at_or_before`` (0 if none yet)."""
    return math.floor(at_or_before / interval + 1e-9) * interval


# ---------------------------------------------------------------------------
# Routes (who can go where), and how many moves each room is from the door
# ---------------------------------------------------------------------------

# Each room maps to its two possible next rooms (the game flips a coin).
BONNIE_ROUTE = {
    "1A": ("5", "1B"),
    "5": ("1B", "2A"),
    "1B": ("5", "2A"),
    "2A": ("3", "2B"),
    "2B": ("3", "DOOR"),
    "3": ("DOOR", "2A"),
}
CHICA_ROUTE = {
    "1A": ("1B", "1B"),
    "1B": ("7", "6"),
    "6": ("7", "4A"),
    "7": ("6", "4A"),
    "4A": ("1B", "4B"),
    "4B": ("4A", "DOOR"),
}
# Where they go when their move fails against a closed door.
BONNIE_REPELLED_TO = "1B"
CHICA_REPELLED_TO = "4A"

BONNIE_DISTANCE = {"1A": 4, "1B": 3, "5": 3, "2A": 2, "2B": 1, "3": 1, "DOOR": 0}
CHICA_DISTANCE = {"1A": 5, "1B": 4, "6": 3, "7": 3, "4A": 2, "4B": 1, "DOOR": 0}

FREDDY_ROUTE = ["1A", "1B", "7", "6", "4A", "4B", "OFFICE"]

# ---------------------------------------------------------------------------
# Foxy and Freddy timers (frames)
# ---------------------------------------------------------------------------

FOXY_LOCK_MIN_FRAMES = 50          # lock after the camera = 50 + random(0..999) frames
FOXY_LOCK_RANDOM_FRAMES = 1000
FOXY_RELOCK_INTERVAL = 0.1         # while a camera is showing, the lock is re-rolled every 0.1 s
FOXY_STAGE3_FRAMES = 1500          # stage 3 -> attack after 25 s
FOXY_RUN_FRAMES = 100              # after viewing West Hall at stage 3
FOXY_BANG_COST = (10, 60, 110, 160, 210, 260, 310)   # power lost per bang, in order


def freddy_countdown_frames(ai: int) -> int:
    """Frames between Freddy's successful roll and his actual move."""
    return max(0, 1000 - 100 * ai)
