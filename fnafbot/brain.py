"""The bot's decision making: what to check, when, and how to react.

The brain works the same on the real game and in the simulator: it only
talks to a "body" (body.RealBody or sim.SimBody) through a few methods
(face a side, press a button, look at a doorway, raise the camera ...).

The whole strategy rests on one fact from the game's code: everything happens
on fixed timers counted from the start of the night (rules.py). Bonnie can
only move at 4.97 s, 9.94 s, 14.91 s ..., power is only charged at whole
seconds, and so on. So instead of checking "as often as possible", the bot
checks exactly when it matters and never pays power it does not need to.

Strategy in short (details in docs/STRATEGY.md):

* Bonnie / Chica: each move happens on a tick, so the bot keeps a
  lower bound on how many moves each one is from their door. Between two
  ticks where an arrival is possible, the hall light is flashed once
  (between two power charges, so it is free). Seen -> close the door. After
  their next tick: reopen, look again, close again only if still there.
* Foxy: a short camera flip just before each of his ticks re-arms his lock,
  so he never leaves Pirate Cove. Free too, if timed between power charges.
* Freddy: the camera always rests on E. Hall Corner (4B), the one view from
  which he cannot enter. Other cameras are only shown after confirming 4B
  is clear.
* Safety beats power: a door check always wins over a Foxy flip.
"""

from __future__ import annotations

import itertools
import logging
import math
from dataclasses import dataclass, field
from typing import Callable, Protocol

from fnafbot import rules

log = logging.getLogger(__name__)

LEFT, RIGHT = "left", "right"

# ---------------------------------------------------------------------------
# Timing constants (seconds). All chosen with safety margins on top of the
# measured game behaviour.
# ---------------------------------------------------------------------------

# Our idea of "now" can be off by several hundredths of a second (the night
# start and the length of a game second are both measured, not known);
# every precise plan keeps at least this much distance from a deadline.
CLOCK_MARGIN = 0.1
# Only count an animatronic's tick as passed this long after it: the clock
# can be off by CLOCK_MARGIN and the game fires the tick on a whole frame.
# A door reopened on the very frame of their tick lets them in (the move
# simply waits for the door animation to finish), so this must be generous.
TICK_SETTLE = 0.4

# Clicks are ignored for 10 frames after a door/light click.
BUTTON_COOLDOWN = 0.26     # same as controller.BUTTON_COOLDOWN (see the note there)

# Keep extra power use this far away from each whole-second power charge.
POWER_TICK_GUARD = 0.08

# A doorway check (light on -> look -> light off) keeps the light on this
# long on the real game (the off-click must wait out the 0.17 s click
# cooldown, plus looking and mouse time).
LIGHT_CHECK_SECONDS = 0.3

# Start checking this long after the animatronic's tick (the move happens on
# that frame; we wait a couple of frames to be sure it has been applied).
AFTER_TICK = 0.2

# Keep a hall light off this close to Bonnie's or Chica's ticks (an arrival
# or departure switches the lights off - see quiet_light_start()).
MOVE_TICK_GUARD = 0.15

# The light must be switched on at least this long before the animatronic's
# next tick, so that if they are there the door click (which has to wait for
# the click cooldown) still lands before that tick.
CHECK_DEADLINE_LEAD = BUTTON_COOLDOWN + 0.12 + CLOCK_MARGIN

PAN_SECONDS = 0.55

# Camera session for Foxy: the camera picture shows for about this long (just
# long enough to contain one of the game's 0.1 s re-lock instants), or much
# longer when the flip also reads 4B and looks at Pirate Cove.
# A hold view must contain one of the game's 0.1 s re-lock instants with
# FOXY_CLOCK_MARGIN to spare on both sides: 0.1 + 2 x 0.12 = 0.34 s, plus
# slack. (At 0.3 s most live ticks counted as "not covered" and the alert
# procedure shut the left door several times a minute.)
FREEZE_VIEW_SECONDS = 0.45
COVE_CHECK_VIEW_SECONDS = 1.0
# Foxy's lock is re-rolled only at the game's 0.1 s instants while a picture
# shows, so everything about covering his ticks gets a wider clock margin
# than the rest (the fitted clock wobbles by a few hundredths).
FOXY_CLOCK_MARGIN = 0.12
# The camera must go down no earlier than this before Foxy's tick: the lock
# set at the last re-lock lasts at least 50 frames (0.833 s).
FREEZE_LATEST_GAP = 0.833 - 0.1 - FOXY_CLOCK_MARGIN

# Re-check Pirate Cove (only when it is safe) at least this often. Foxy
# attacks 25 s after reaching stage 3, so a missed stage must be noticed
# well inside that.
FOXY_VERIFY_EVERY = 15.0
# Foxy at stage 3 attacks after 1500 frames (event [320]); assume a little
# less than 25 s. The full alert (shut the left door, look) starts this long
# before the earliest possible end of that fuse.
FOXY_FUSE_SECONDS = 24.5
# A planned door click that has to come before a Foxy flip starts this much
# earlier than the bare pan + click cooldown. 0.4 s covered more of Foxy's
# ticks in the simulator, but live (campaign59) the earlier shut kept the
# left door closed through Bonnie's whole cycle far more often: 50 s of
# "before camera flip" in one night against 4 - 16 s before. Back to 0.15.
FLIP_DOOR_SLACK = 0.15
FOXY_ALERT_LEAD = 11.0
# Foxy's real tick may come up to this long after the one the brain
# computes from rules.TICK_PHASE (measured to within ~0.1 s from his bangs;
# before the measurement this had to be 0.6 s, which cost ~4 % of camera
# power on 4/20 nights), so every flip covers the whole range...
FOXY_PHASE_SPREAD = 0.15
# ...and it may also come this much BEFORE it (the simulator tells the brain
# phases that are off by up to 0.15 s).
FOXY_PHASE_EARLY = 0.15
# The movement timers (Bonnie's, Chica's, Foxy's, Freddy's) fall behind
# real time on a camera-heavy night, by a different amount every night
# (tools/measure_timer_clock.py): one night +0.8 s by 90 s and then flat,
# another a steady +0.002 s per second (+0.35 s by 200 s); live 4/20 #8 was
# at ~0.6 s by 300 s. On a quiet night there is no lag. So every tick comes LATER than the measured
# phases say, by an amount the brain measures live (see _watch_leave) and
# brackets: the lag is at least the latest measurement minus LAG_NOISE (it
# never shrinks), and at most the latest plus LAG_NOISE plus LAG_GROWTH for
# every second since. Before the first measurement it is anything from 0 to
# LAG_PRIOR, plus LAG_PRIOR_GROWTH per second after LAG_PRIOR_QUIET (on
# three cold-started nights it jumped to 0.55 - 0.8 s within the first
# minute and a half, then stayed there). (Not knowing about it lost live
# 4/20 #8: a reopen "after" Bonnie's tick landed before it - docs/DEVLOG.md.)
LAG_NOISE = 0.07
# Since the power clock is fitted properly (live 4/20 #28 on, campaign47 -
# 62), every live lag sample has been 0.00 - 0.09 s, and it does not grow:
# the 0.5 - 1 s "lag" of the earlier nights was the brain's clock running
# 0.65 % slow (docs/DEVLOG.md, "The power clock never fitted"). The wide
# allowances below were for that and made every margin of a night with no
# sample a second wide: on campaign55 and 57 (no sample all night) the
# Foxy flips counted ~30 ticks as uncovered and the bot ran out of power.
# So the allowances are now small; should a sample ever show the timers
# more than LAG_WIDE_TRIGGER late, the night switches back to the wide ones
# (LAG_*_WIDE) - in the simulator with the old lag the narrow ones alone
# lost 240 of 400 nights.
LAG_GROWTH = 0.0003
LAG_GROWTH_EARLY = 0.001
LAG_EARLY_UNTIL = 90.0
LAG_PRIOR = 0.15
LAG_PRIOR_GROWTH = 0.0005
LAG_PRIOR_QUIET = 20.0
LAG_SPREAD_MAX = 0.95
# After the first minute and a half with no sample taken since, assume the
# lag is at most LAG_SETTLED_HI, growing by LAG_SETTLED_GROWTH a second.
# (An assumed FLOOR of 0.45 s here lost live 4/20 #13 and #14: on nights
# whose lag stayed small, every tick sat ~0.4 s late on the model and a
# door click landed on the real tick. Only a measurement raises the floor.)
LAG_SETTLED_AFTER = 90.0
LAG_SETTLED_HI = 0.25
LAG_SETTLED_GROWTH = 0.0003
# The wide allowances (from before the clock fix): the lag jumped to
# 0.55 - 0.85 s in the first minute and a half on cold starts, and live
# 4/20 #12 crept up to ~1 s by 416 s.
LAG_WIDE_TRIGGER = 0.3
# ... or once this many watches saw no departure (see _watch_leave). One:
# with two, the old lag in the simulator still lost 103 nights of 400; with
# one, 28 (a night that switches needlessly only loses a little power).
LAG_MISSES_FOR_WIDE = 1
LAG_GROWTH_WIDE = 0.002
LAG_GROWTH_EARLY_WIDE = 0.012
LAG_PRIOR_GROWTH_WIDE = 0.012
LAG_SETTLED_HI_WIDE = 0.8
LAG_SETTLED_GROWTH_WIDE = 0.0015
# The lamp is read this long after it really goes dark (one screen grab).
LAMP_SEEN_DELAY = 0.02
# A departure watch (see _watch_leave) has the light on and confirmed lit
# this long before the earliest possible tick, and keeps watching this long
# after the latest one.
WATCH_LEAD = 0.15
WATCH_TAIL = 0.12
LIGHT_ON_SECONDS = 0.1     # click -> lamp lit
# A watch cut short (by a Foxy flip) is only worth it if it still covers
# this much time after their earliest possible tick.
MIN_WATCH_AFTER_TICK = 0.3
# Until the lag has been measured once, every margin carries the wide prior
# (camera flips longer, doors shut longer). But early in the night Bonnie's
# and Chica's ticks fall within a second of Foxy's (4.97 / 4.98 / 5.01 s),
# so a watch always collides with a Foxy flip - for the first ~150 s. So the
# first watch may take the place of one flip, as long as Foxy cannot be
# past this stage afterwards (one uncovered tick moves him one stage at
# most, and the bot keeps track of that).
LAG_HUNGRY_FOXY_STAGE = 1
LAG_HUNGRY_AFTER = 15.0    # (not before this: nobody has reached a door yet)
# ... and so may a later one, once the lag is this uncertain again.
LAG_HUNGRY_SPREAD = 0.45
# ... and so may one when the last sample is this old (the narrow lag
# allowances are only right while samples keep confirming them: one sample
# at 30 s says nothing about a lag that builds up later), as long as Foxy
# cannot be past LAG_RESAMPLE_FOXY_STAGE afterwards.
LAG_RESAMPLE_EVERY = 90.0
LAG_RESAMPLE_FOXY_STAGE = 2

# Warm-up. The game loads a door's animation, a light, a camera's picture
# the first time it is used, and those stalls are what makes the
# animatronics' timers fall behind real time early in a night: +0.5 s by
# 55 s on two nights that started cold, +0.03 s at 40 s and under 0.12 s
# until 140 s on a night that began by using everything once
# (tools/measure_timer_clock.py --warmup; docs/DEVLOG.md). So the bot does
# that in the first seconds, while nobody can reach a door (Bonnie needs
# four moves, ~20 s): the camera tour rides along on the first Foxy flip,
# the door and light cycles fill the gaps until WARMUP_UNTIL.
# OFF: on the one night measured after a warm-up the lag stayed small for
# two minutes but then kept growing (to 1.1 s by 300 s), while three cold
# starts all levelled off at 0.55 - 0.8 s within 90 s - easier to plan for.
WARMUP = False
WARMUP_CAMERAS = ("1A", "1B", "5", "2A", "2B", "3", "7", "4A", "1C", "4B")
WARMUP_UNTIL = 18.0
# One side's warm-up: door shut and open again, light on and off.
WARMUP_CYCLE_SECONDS = (2 * 0.03 + 0.45 + 0.15 + 0.45 + 0.15 + 2 * 0.26 + 0.3)

# A flip that is late still goes ahead for a tick whose earliest moment
# passed up to this long ago (his real tick usually comes 0.3 - 1.0 s after
# it, measured): on live 4/20 #21 the bot shut Bonnie's door "before camera
# flip" a few tenths after Foxy's earliest tick, cycle after cycle, and
# every one of those flips was dropped - 18 s without a flip.
LATE_FLIP_GRACE = 1.2
BLIND_REOPEN_FLIP_GUARD = False     # (tried: far too costly in the simulator, 19/60 6th Nights)

# See Brain._foxy_lag_allowance.
FOXY_LAG_CAP = 0.3

# Foxy is only a threat if his fuse can end this long after 6 AM at the
# latest (see Brain._foxy_can_attack) - a margin for the clocks.
FOXY_END_MARGIN = 2.0

# Look at Pirate Cove at least this often, whenever the right door is shut
# anyway (for Chica) - then no door has to be shut for Freddy and the look
# costs only the camera. Foxy's tick bookkeeping is not enough on its own:
# on live 4/20 #9 and #16 he reached stage 3 and ran while every flip had
# been logged as covering his ticks, and with Freddy on 4B no cove check
# had happened for minutes.
COVE_LOOK_EVERY = 30.0
# ... and on any flip while the right door is shut anyway, if Foxy may
# have moved since he was last seen (see Brain._cove_check_due).
COVE_LOOK_WHEN_MOVED = True
COVE_LOOK_SECONDS = 2.2       # raise, switch to the cove, read, back to 4B, lower

# Log the power ledger (door and camera time, see Brain._power_ledger) this often.
LEDGER_EVERY = 30.0

# After someone was seen on 4B, assume it stays blocked this long before
# planning another routine cove check.
FOUR_B_BUSY_SECONDS = 20.0
# Roughly how long a Foxy alert (shut the left door, look at the cove, maybe
# shut the right door first) keeps the bot busy; used to let an urgent
# doorway check go first.
FOXY_ALERT_SECONDS = 3.0
# A Foxy alert looks at the cove with the left door still OPEN when his fuse
# (the earliest moment a stage-3 Foxy can attack) is at least this far away:
# the look takes ~2 - 4 s and, if he really is out, shutting the door and
# making him run takes ~1.5 s more. Shutting it first "just in case" cost
# 18 - 50 s of left door a night live (campaign55 - 60), and on most alerts
# he was still in the cove.
ALERT_OPEN_LOOK_SECONDS = 9.0
# ... and just before switching to the cove, at least this much must be left.
ALERT_OPEN_SWITCH_SECONDS = 5.0
# The left door may also only stay open if Bonnie cannot walk in before a
# doorway check can follow the alert. The alert keeps the bot busy for up
# to this long (raise, read 4B, lower, shut the right door, raise again,
# look at the cove, lower), and just the cove look itself this long.
# (Without this test Bonnie walked in on 25 of 400 simulated 4/20 nights.)
ALERT_FULL_SECONDS = 5.2
ALERT_LOOK_SECONDS = 2.4
# If a hall light fails to come on this close to their tick, shut the door
# instead of trying the light again.
LIGHT_FAIL_SHUT_LEAD = 1.3
# How long after a door click to wait before reading the button's lamp.
DOOR_LAMP_SETTLE = 0.03

# Just-in-time doors (see Brain._plan_close): shut the door shortly before
# Bonnie's/Chica's next tick instead of the moment they are seen.
JIT_DOORS = True
# The door click must land at least this long before their tick. A closing
# door already blocks them, so this only has to cover clock error (~0.03 s),
# click delay (one frame), and - should the game miss the click - reading
# the button's lamp (0.05 s) plus one click cooldown (0.19 s) for a second
# click that still lands before the tick (see _confirm_door_click).
JIT_MIN_LEAD = 0.5
# Only plan a later close if at least this much time is left to choose from.
JIT_MIN_SLACK = 0.6
# Head for a planned click this long before it is needed (on top of the pan
# and the click cooldown): slack for a slow screen read or a monitor that
# takes a moment longer to come down. A click 0.4 s late once let Bonnie
# in (docs/DEVLOG.md); the click itself still waits for the planned moment.
JIT_HEADROOM = 0.1
# The "certainly sent back at AI 20" shortcut (see _certainly_repelled): ON
# again. It was switched off after Chica "stayed at the door through a tick
# with the door fully shut" and walked in once it was opened (live 4/20 #7).
# Both explanations found since are now dealt with: a lost arrow click could
# leave her at AI 19 (the setup now gives spare clicks), and - the likelier
# one - the timers run late: her real tick came after the bot had already
# started opening the door, and a move during a door animation waits for it
# to finish. Ticks now count as passed only once the measured lag range is
# behind them. And a departure taken on trust is still verified with a
# light check before their next tick (verify_departure). Without it the
# left door stayed shut 14 - 82 s per Bonnie visit waiting for a peek that
# did not fit (live 4/20 #17, #18): the biggest single power cost.
TRUST_AI20_PROOF = True

# Can the doorway be checked with the door SHUT? Verified live on
# 2026-10-22 (tools/check_shut_window.py): Chica's window is beside the right
# door, not behind it, and reads normally; the left door covers Bonnie's
# doorway completely.
SEEN_THROUGH_SHUT_DOOR = {"left": False, "right": True}
# A peek that has waited this long for a gap may push the other side's
# routine check out of the way (see the scheduler).
STUCK_PEEK_SECONDS = 4.0
# A quick reopen may start this much past the planned start of a Foxy flip
# (flips are planned 0.4 s before the latest safe moment, and _hold_until
# keeps the picture up until the tick is covered anyway).
REOPEN_FLIP_SLACK = 0.0
# Blind reopens (open the door after their tick, shut it again before the
# next) only when the door can stay open at least BLIND_MIN_OPEN seconds -
# enough for the light to be flashed through it before the closing click
# (_look_while_open), so the bot learns whether he has gone. On live 4/20
# #10 they opened ~1 s before the closing click: open-shut-open-shut with
# no light ever switched on and nothing learned. (Turning them off
# altogether cost far more power in the simulator: 6/30 4/20 nights.)
BLIND_REOPENS = True
BLIND_MIN_OPEN = 2.0


class Body(Protocol):
    """What the brain needs from the game (real or simulated)."""

    def now(self) -> float: ...
    def wait_until(self, t: float) -> None: ...
    def night_over(self) -> bool: ...
    def face(self, side: str) -> None: ...
    def press(self, kind: str, side: str) -> None: ...
    def look_doorway(self, side: str) -> tuple[bool, bool]: ...
    def light_is_on(self, side: str) -> bool: ...
    def watch_lamp(self, side: str, until: float) -> float | None: ...
    def camera_up(self) -> bool: ...
    def camera_down(self) -> bool: ...
    def select_camera(self, camera: str) -> None: ...
    def read_camera(self, camera: str) -> dict: ...
    def power(self) -> int: ...


@dataclass
class DoorWatch:
    """What the brain knows about one doorway (Bonnie = left, Chica = right)."""

    who: str                       # "bonnie" or "chica"
    side: str
    tick: float                    # seconds between their movement chances
    distance: dict[str, int]       # moves from each room to the door
    repelled_to: str               # where they go when the door blocks them
    min_moves: int                 # lower bound on moves needed to reach the door
    at_door: bool = False          # seen in the doorway and not seen leaving
    door_closed: bool = False      # our door (as we set it)
    closed_at: float = -1.0        # when we clicked the door shut
    checked_since_tick: bool = True
    last_tick_seen: float = 0.0    # last of their ticks already accounted for
    failed_checks: int = 0         # light checks in a row where the light never came on
    seen_at_door_at: float = 0.0   # last time we actually SAW them in the doorway
    seen_for_sure: bool = True     # False if the door was shut "just in case"
    close_at: float | None = None  # planned just-in-time door click (night seconds)
    moving_until: float = 0.0      # the door's open/close animation ends at this time
    reopen_after: float = 0.0      # a reopen that found no closing slot waits until here
    looked_while_open: bool = True # after a blind reopen: has the light been flashed yet?
    verify_departure: bool = False # a "certainly sent back" still to be checked with a look
    watched_tick: float = -1e9     # a tick of theirs we watched with the light on (see _watch_leave)
    planned_watch_tick: float = -1e9   # the tick a departure watch was waiting for
    watch_skips: int = 0           # planned watches in a row that did not happen


@dataclass
class Status:
    """Human-readable summary for the overlay and the log."""

    action: str = "Starting"
    alert: bool = False
    notes: dict[str, str] = field(default_factory=dict)


class Brain:
    def __init__(self, body: Body, night: int, custom: dict[str, int] | None = None,
                 report: Callable[[Status], None] | None = None) -> None:
        self.body = body
        self.night = night
        self.custom = custom
        self.report = report or (lambda status: None)
        self.status = Status()

        self.left = DoorWatch("bonnie", LEFT, rules.BONNIE_TICK, rules.BONNIE_DISTANCE,
                              rules.BONNIE_REPELLED_TO, rules.BONNIE_DISTANCE["1A"])
        self.right = DoorWatch("chica", RIGHT, rules.CHICA_TICK, rules.CHICA_DISTANCE,
                               rules.CHICA_REPELLED_TO, rules.CHICA_DISTANCE["1A"])

        self.camera_selected = "1A"        # the game starts on Show Stage
        self.freddy_at_4b: bool | None = None
        self.last_press_at = -1.0          # last door/light click (for the click cooldown)

        # Foxy. foxy_stage is what we last SAW; foxy_max_stage is the highest
        # stage he could possibly have reached since then (each of his ticks
        # not covered by a camera flip may have moved him one stage).
        self.foxy_stage = 0
        self.foxy_max_stage = 0
        self.foxy_verified_at = 0.0            # he starts the night in the cove, stage 0
        self.foxy_last_tick_seen = 0.0
        self.foxy_frozen_tick = 0.0        # last Foxy tick we have planned a flip for
        self.foxy_emergency = False        # Foxy left the cove: left door must stay shut
        self.foxy_door_hold = False        # left door shut until we have looked at the cove
        self.foxy_alert_retry_at = 0.0     # earliest time for another Foxy alert attempt
        self.four_b_busy_at = -1e9         # when 4B was last seen occupied (blocks cove checks)
        self.foxy_fuse_from = math.inf     # earliest moment Foxy may have reached stage 3
        self.foxy_below3_seen_at = 0.0     # last time he was SEEN below stage 3 (his fuse started after it)
        # How far Foxy's ticks have been pushed back (real seconds) - see
        # _foxy_timer_paused.
        self.foxy_phase_shift = 0.0
        # After a run his ticks are anchored on the bang (real seconds, mod
        # his period) - see _foxy_timer_restarted. None until his first run.
        self.foxy_anchor: float | None = None
        self.bangs_seen = 0                # Foxy's bangs already booked (see _book_bangs)
        self.last_look_at = 0.0            # when a doorway was last looked at (light on)
        self.lag_wide = False              # wide lag allowances (see LAG_WIDE_TRIGGER)
        self.lag_misses = 0                # watches that saw no departure
        self.view_intervals: list[tuple[float, float]] = []   # when a camera picture showed
        # Measured lag of the movement timers: (night time, lag) samples, and
        # the floor the tick model uses (see LAG_NOISE).
        self.lag_samples: list[tuple[float, float, float]] = []   # (night time, lag at least, lag at most)
        # Power ledger (see _book_door): seconds each door has been shut, when
        # the current shut span started and why, and every camera view.
        self.door_seconds = {LEFT: 0.0, RIGHT: 0.0}
        self.door_shut_since = {LEFT: 0.0, RIGHT: 0.0}
        self.door_shut_reason = {LEFT: "", RIGHT: ""}
        self.view_intervals_all: list[tuple[float, float]] = []
        self.ledger_logged_at = 0.0
        self.lag_lo = 0.0
        # Warm-up still to do (see WARMUP_CAMERAS): the camera tour, and a
        # door-and-light cycle on each side.
        self.warmup_tour_done = not WARMUP
        self.warmup_sides = [LEFT, RIGHT] if WARMUP else []
        self._view_started = 0.0           # when the current camera picture appeared

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def ai(self, at: float) -> dict[str, int]:
        return rules.ai_levels(self.night, rules.hour_at(at), self.custom)

    def say(self, action: str, alert: bool = False) -> None:
        self.status.action = action
        self.status.alert = alert
        self.status.notes = {
            "Bonnie": "AT DOOR" if self.left.at_door else f">= {self.left.min_moves} moves",
            "Chica": "AT DOOR" if self.right.at_door else f">= {self.right.min_moves} moves",
            "Foxy": "LEFT COVE" if self.foxy_emergency else
                    f"stage {self.foxy_stage}" + (f" (<= {self.foxy_max_stage})" if self.foxy_max_stage > self.foxy_stage else ""),
            "Freddy": {None: "?", True: "at 4B", False: "not at 4B"}[self.freddy_at_4b],
            "Doors": " / ".join(self._door_note(w) for w in (self.left, self.right)),
        }
        log.info("%.2fs  %s", self.body.now(), action)
        self.report(self.status)

    @staticmethod
    def power_safe(start: float, duration: float) -> bool:
        """True if [start, start+duration] keeps clear of every power charge
        (power is only charged at whole seconds, see rules.POWER_TICK)."""
        lo = start - POWER_TICK_GUARD
        hi = start + duration + POWER_TICK_GUARD
        return math.ceil(lo) > hi   # no whole second inside [lo, hi]

    @staticmethod
    def next_power_safe_start(earliest: float, duration: float) -> float:
        """Earliest time >= earliest at which a ``duration`` action avoids power charges."""
        if Brain.power_safe(earliest, duration):
            return earliest
        return math.floor(earliest + duration + POWER_TICK_GUARD) + POWER_TICK_GUARD + 1e-3

    def quiet_light_start(self, earliest: float, latest: float) -> float:
        """Best moment in [earliest, latest] to switch a hall light on.

        Two kinds of moments are avoided while the light is on:
          * Bonnie's and Chica's ticks: when either of them arrives at or
            leaves a doorway the game switches BOTH lights off, which would
            spoil the check (correctness - avoided whenever possible);
          * whole seconds, when power is charged (cost - avoided if possible).
        """
        spread = self._lag_spread(earliest)

        def hits_move_tick(start: float) -> bool:
            for who in ("bonnie", "chica"):
                tick = self._next_tick(who, start - MOVE_TICK_GUARD - spread)
                if tick <= start + LIGHT_CHECK_SECONDS + MOVE_TICK_GUARD:
                    return True
            return False

        best_without_move_tick = None
        t = earliest
        while t <= latest:
            if not hits_move_tick(t):
                if self.power_safe(t, LIGHT_CHECK_SECONDS):
                    return t
                if best_without_move_tick is None:
                    best_without_move_tick = t
            t += 0.02
        return best_without_move_tick if best_without_move_tick is not None else earliest

    # -- movement ticks in the brain's clock --------------------------------
    #
    # The brain's clock (body.now()) counts the game's power seconds, which
    # are a little longer than real seconds (body.scale). The animatronics'
    # timers were measured to run in REAL seconds with a small phase offset
    # (rules.ANIM_TICK_PHASE), so every "when is their next tick" question
    # goes through these two helpers, which convert. (In the simulator both
    # clocks agree: scale 1, phase 0.) Getting this wrong cost several
    # nights - docs/DEVLOG.md.

    def _timer(self, who: str) -> tuple[float, float]:
        """(period, phase) of ``who``'s movement timer, in REAL seconds: the
        measured phase plus the smallest lag the timers can have now. Every
        tick this gives is the EARLIEST the real tick can be; it may come up
        to _lag_spread() later."""
        if who == "foxy" and self.foxy_anchor is not None:
            # Anchored on his last bang: the timers' lag measured since does
            # not move him (it was already in the bang's time).
            return rules.TICK_PERIOD[who], self.foxy_anchor + self.foxy_phase_shift
        shift = self.foxy_phase_shift if who == "foxy" else 0.0
        return rules.TICK_PERIOD[who], self.body.tick_phases.get(who, 0.0) + self.lag_lo + shift

    def _lag_spread(self, at: float) -> float:
        """How much later than the tick model a tick at night time ``at``
        may come (see LAG_NOISE)."""
        wide = self.lag_wide
        if at >= LAG_SETTLED_AFTER and not self._settled_samples():
            # No sample since the lag settled: the top of the range is the
            # settled assumption, growing - or the latest sample's growth
            # allowance, whichever is higher. The FLOOR is never raised
            # above what a sample measured: an assumed floor of 0.45 s on
            # live 4/20 #13, whose lag was ~0.05 s at 64 s, put every tick
            # 0.4 s late on the model - door clicks barely before the real
            # tick.
            high = ((LAG_SETTLED_HI_WIDE if wide else LAG_SETTLED_HI)
                    + (LAG_SETTLED_GROWTH_WIDE if wide else LAG_SETTLED_GROWTH) * (at - LAG_SETTLED_AFTER))
            if self.lag_samples:
                high = max(high, self.lag_samples[-1][2] + LAG_NOISE)
            return max(0.0, high - self.lag_lo)
        if not self.lag_samples:
            growth = LAG_PRIOR_GROWTH_WIDE if wide else LAG_PRIOR_GROWTH
            return min(LAG_SPREAD_MAX, LAG_PRIOR + growth * max(0.0, at - LAG_PRIOR_QUIET))
        recent = [self.lag_samples[-1][2]]       # the latest sample's upper end
        last = self.lag_samples[-1][0]
        early = max(0.0, min(at, LAG_EARLY_UNTIL) - last)        # seconds of fast build-up since
        late = max(0.0, at - max(last, LAG_EARLY_UNTIL))
        growth = ((LAG_GROWTH_EARLY_WIDE if wide else LAG_GROWTH_EARLY) * early
                  + (LAG_GROWTH_WIDE if wide else LAG_GROWTH) * late)
        return min(LAG_SPREAD_MAX, max(recent) + LAG_NOISE - self.lag_lo + growth)

    def _foxy_lag_allowance(self, tick: float) -> float:
        """How much of the lag range a Foxy flip covers. Not all of it: the
        lock a camera picture sets lasts 50 + Random(1000) frames (event
        [329]) - 9 s on average - and the bot plans for the 50-frame worst
        case, so a tick that comes a few tenths after the planned cover is
        only missed if the lock happened to be that short. Covering the
        whole range made every flip a second longer (the simulator ran out
        of power); a missed tick moves Foxy one stage at most, which the
        bot's stage-3 alert is there for."""
        return min(self._lag_spread(tick), FOXY_LAG_CAP)

    def _settled_samples(self) -> list[tuple[float, float, float]]:
        """Lag samples taken after the lag has settled (LAG_SETTLED_AFTER).
        An earlier one says little about the rest of the night: the lag is
        still building then (live 4/20 #12: 0.16 s at 35 s, its only sample,
        held the floor ~0.35 s below the ~0.5 s it settles at - and every
        Foxy flip then looked late on the model, five false Foxy alerts)."""
        return [sample for sample in self.lag_samples if sample[0] >= LAG_SETTLED_AFTER]

    def _raise_lag_floor(self, new_lo: float, allow_lower: bool = False) -> None:
        """The timers are at least ``new_lo`` late (it never shrinks).
        Every tick moves later by the difference; ticks already counted as
        passed must not be counted again when they "move" past the
        bookkeeping marks."""
        if new_lo == self.lag_lo or (new_lo < self.lag_lo and not allow_lower):
            return
        shift = self.body.real_to_game(new_lo) - self.body.real_to_game(self.lag_lo)
        for watch in (self.left, self.right):
            watch.last_tick_seen += shift
        if self.foxy_anchor is None:          # (anchored on a bang, his ticks do not move)
            self.foxy_last_tick_seen += shift
        self.lag_lo = new_lo

    def _note_lag(self, whos: tuple[str, ...], seen_at: float) -> float | None:
        """A tick of one of ``whos`` was seen at night time ``seen_at`` (the
        hall-light lamp went dark). Work out the timers' lag from it - one
        candidate per name; when it is not known whose tick it was, the
        sample is the range they span. Returns the (smallest) lag, or None
        if the sighting cannot be one of their ticks."""
        real = self.body.game_to_real(seen_at) - LAMP_SEEN_DELAY

        def candidates() -> list[float]:
            lags = []
            for who in whos:
                period = rules.TICK_PERIOD[who]
                base = self.body.tick_phases.get(who, 0.0)
                k = round((real - base - self.lag_lo) / period)
                lag = real - base - k * period
                if self.lag_lo - 0.2 <= lag <= self.lag_lo + self._lag_spread(seen_at) + 0.25:
                    lags.append(lag)
            return lags

        lags = candidates()
        if not self.lag_wide and (not lags or max(lags) > LAG_WIDE_TRIGGER):
            # Later than the small allowances expect (or off them): the
            # timers may be lagging like they did before the clock fix. Wide
            # margins for the rest of the night, and judge the sample again.
            self.lag_wide = True
            log.warning("%.2fs  the timers may be running late - wide timing margins from now on", seen_at)
            lags = candidates()
        if not lags:
            log.warning("%.2fs  lamp went dark off every tick model (%s) - not used as a lag sample",
                        seen_at, "/".join(whos))
            return None
        lag, high = min(lags), max(lags)
        self.lag_samples.append((seen_at, lag, high))
        if len(self.lag_samples) == 1 or (seen_at >= LAG_SETTLED_AFTER and len(self._settled_samples()) == 1):
            # The first sample - and the first one after the lag has settled
            # - sets the floor, even downwards (the first one after 90 s, too). (Moving the bookkeeping marks back can only
            # count a tick twice - one extra check, never a missed one.)
            self._raise_lag_floor(lag - LAG_NOISE, allow_lower=True)
        else:
            self._raise_lag_floor(lag - LAG_NOISE)
        log.info("%.2fs  timers run %.2f..%.2f s late (%s) - model now +%.2f .. +%.2f s",
                 seen_at, lag, high, "/".join(whos), self.lag_lo, self.lag_lo + self._lag_spread(seen_at))
        return lag

    def _next_tick(self, who: str, after: float) -> float:
        """The first tick of ``who``'s timer strictly after night time ``after``.

        Their timers run in real seconds from the night's first frame
        (measured: tools/measure_door_ticks.py --camera), so the question is
        answered in real time and converted to and from the brain's clock -
        whose pace changes with camera use - by the body."""
        period, phase = self._timer(who)
        after_real = self.body.game_to_real(after)
        return self.body.real_to_game(rules.next_tick(period, after_real - phase) + phase)

    def _tick_times(self, who: str, start: float, end: float) -> list[float]:
        """All ticks of ``who``'s timer inside [start, end)."""
        period, phase = self._timer(who)
        lo, hi = self.body.game_to_real(start), self.body.game_to_real(end)
        return [self.body.real_to_game(t + phase) for t in rules.tick_times(period, lo - phase, hi - phase)]

    def _tick_after(self, watch: DoorWatch, now: float) -> float:
        """Their next tick as far as the bot can be sure: a tick less than
        TICK_SETTLE ago may not have happened yet on the game's clock, so it
        still counts as upcoming. (Opening a door on the frame of their
        tick lets them in - found with the simulator's wandering clock.)"""
        return self._next_tick(watch.who, now - TICK_SETTLE - self._lag_spread(now))

    def _moves_since(self, watch: DoorWatch, after: float, until: float) -> int:
        """How many of their ticks (with AI > 0) fall in (after, until]."""
        ticks = self._tick_times(watch.who,after + 1e-6, until + 1e-6)
        return sum(1 for tick in ticks if self.ai(tick)[watch.who] > 0)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def play(self) -> None:
        self.say("Night started - watching the clock")
        while not self.body.night_over():
            now = self.body.now()
            if now - self.ledger_logged_at >= LEDGER_EVERY:
                self.ledger_logged_at = now
                log.info("%.0fs  power %s%%: %s", now, self.body.power(), self._power_ledger())
            self._account_for_ticks(now)
            job = self._choose_job(now)
            if job is None:
                self._idle(now)
                continue
            # Which jobs push the next Foxy flip past its planned start? (Live
            # nights leave 2 - 3 times more of his ticks uncovered than the
            # simulator does: this line says where the time goes.)
            flip_at = self._next_freeze_start(now) if job != self._freeze_foxy else None
            job()
            if flip_at is not None and now < flip_at and self.body.now() > flip_at + 0.05:
                log.info("%.2fs  late flip: '%s' (from %.2f s) ran %.2f s past the flip start",
                         self.body.now(), self.status.action, now, self.body.now() - flip_at)

    # ------------------------------------------------------------------
    # Bookkeeping: what can have changed since we last looked
    # ------------------------------------------------------------------

    def _book_bangs(self) -> None:
        """Foxy banged on the shut door (the body saw the power drop): he is
        back in the cove at stage 0 or 1, and his timer starts again from
        that moment - wherever the bot thought it was (_foxy_timer_restarted).
        On live 4/20 #23 a run the bot had set off was followed 73 s later by
        another: the restart had been placed by assumption, not by the bang."""
        bangs = getattr(self.body, "bangs", [])
        while self.bangs_seen < len(bangs):
            at = bangs[self.bangs_seen]
            self.bangs_seen += 1
            self._foxy_timer_restarted(at)
            self.foxy_stage, self.foxy_max_stage = 0, 1
            self.foxy_fuse_from = math.inf
            self.foxy_verified_at = max(self.foxy_verified_at, at)
            log.info("%.2fs  Foxy banged on the door: his timer restarts from here", at)

    def _account_for_ticks(self, now: float) -> None:
        self._book_bangs()
        # A tick only counts as passed once the clock is certainly past it;
        # otherwise a doorway check could run just BEFORE the real tick and
        # report "empty" about a doorway they are about to step into.
        now -= TICK_SETTLE + self._lag_spread(now)
        for watch in (self.left, self.right):
            for tick in self._tick_times(watch.who,watch.last_tick_seen + 1e-6, now + 1e-6):
                watch.last_tick_seen = tick
                if self.ai(tick)[watch.who] == 0:
                    continue
                if abs(tick - watch.watched_tick) < 1.0:
                    continue    # watched with the light on: already accounted for
                if abs(tick - watch.planned_watch_tick) < 1.0:
                    watch.watch_skips += 1     # a watch was planned for it but did not happen
                watch.checked_since_tick = False
                if not watch.at_door:
                    watch.min_moves = max(0, watch.min_moves - 1)
                    if watch.min_moves == 0 and watch.door_closed:
                        # They may have stepped into the doorway at this tick,
                        # behind a door that was shut (for Foxy, for the cove
                        # look...) - the routine light check only looks
                        # through OPEN doors. Treat them as possibly there, so
                        # the door is not opened before a look. (Simulated
                        # 4/20 seed 536: Chica arrived behind the shut door,
                        # it was opened as "needlessly shut", and she walked
                        # in at her next tick.)
                        watch.at_door = True
                        watch.seen_for_sure = False
                        watch.seen_at_door_at = tick
                elif self._certainly_repelled(watch, tick):
                    # At AI 20 the movement roll (Random(20) + 1 <= AI) never
                    # fails, so someone SEEN at a door that was shut through
                    # this tick has certainly been sent back. No need to
                    # keep shutting the door "in case they are still there"
                    # - on 4/20 nights that saves a door cycle (and two pans)
                    # every visit.
                    # They may have been sent back at ANY tick since they were
                    # last SEEN at the door (an earlier tick only lacked proof:
                    # a door still closing at it, or reopened and shut again
                    # since), and moved on one room per tick: count from the
                    # earliest. (Counting from the latest door closing let
                    # Bonnie in on simulated 4/20 nights.)
                    # A tick the model puts just before the sighting may
                    # really have come after it (the timers lag by up to
                    # _lag_spread): count it too. (Simulated 4/20 seed 103:
                    # a tick 0.01 s "before" the sighting came 0.49 s after
                    # it, Bonnie was one room nearer than counted, and he
                    # walked in.)
                    seen = watch.seen_at_door_at
                    since = self._tick_times(watch.who, seen - self._lag_spread(seen) - TICK_SETTLE, tick + 1e-6)
                    watch.at_door = False
                    watch.min_moves = max(0, watch.distance[watch.repelled_to] - max(0, len(since) - 1))
                    # Trust, but verify: look once before their next tick
                    # (checked_since_tick False + min_moves 0 = a doorway
                    # check is due). The proof assumes AI exactly 20; the
                    # Custom Night levels are set by clicking arrows, and a
                    # lost click (AI 19) makes 1 move in 20 fail - twice a
                    # "certainly sent back" Bonnie walked in at his next tick.
                    watch.verify_departure = True
                    watch.checked_since_tick = False
                    log.info("%.2fs  %s certainly sent back at %.2f s (AI 20, door shut)",
                             now, watch.who.capitalize(), tick)
        self._book_foxy_ticks(now)

    def _book_foxy_ticks(self, until: float) -> None:
        """Foxy: every tick of his up to ``until`` that no camera flip covered
        may have moved him."""
        now = until
        for tick in self._tick_times("foxy",self.foxy_last_tick_seen + 1e-6, now + 1e-6):
            self.foxy_last_tick_seen = tick
            if self.ai(tick)["foxy"] > 0 and not self._foxy_tick_covered(tick) and self.foxy_max_stage < 3:
                self.foxy_max_stage += 1
                if self.foxy_max_stage >= 3:
                    # His 25 s fuse (1500 frames at stage 3) can only have
                    # started at this tick: no hurry until near its end.
                    self.foxy_fuse_from = min(self.foxy_fuse_from, tick)
                log.info("%.2fs  Foxy tick at %.2f s was not covered by a flip (could be stage %d)",
                         now, tick, self.foxy_max_stage)

    def _certainly_repelled(self, watch: DoorWatch, tick: float) -> bool:
        """Was someone who was SEEN at the door certainly sent back at
        ``tick``? Only when their move cannot fail (AI 20) and the door was
        FULLY closed at the tick. A door still closing makes the move wait -
        but the game has a single "who is moving" slot, and the other
        animatronic's tick can overwrite the waiting move: then they simply
        stay at the door. (Assuming otherwise let Bonnie in on 5 of 200
        simulated 4/20 nights.)"""
        if not TRUST_AI20_PROOF:
            return False
        return (self.ai(tick)[watch.who] >= 20 and watch.seen_for_sure and watch.door_closed
                and watch.closed_at <= tick - rules.DOOR_CLOSE_SECONDS - CLOCK_MARGIN)

    def _foxy_tick_covered(self, tick: float) -> bool:
        """Was Foxy's lock certainly running at this tick?

        While a camera picture shows, the game re-rolls the lock at every
        whole 0.1 s of night time to at least 50 frames (0.833 s). So a tick
        is covered only if such a 0.1 s instant certainly fell inside a
        picture-showing interval BEFORE the tick, no more than 0.833 s
        earlier. (A picture that appears a moment before the tick, but after
        the last 0.1 s instant, does NOT protect it.)"""
        # Foxy's timer phase is unmeasured: his real tick may come up to
        # FOXY_PHASE_SPREAD after ``tick``. The whole range must be covered,
        # either by the picture still showing or by the lock from the last
        # re-lock instant. (Assuming phase 0 let Foxy advance unseen on a
        # live 4/20 night - docs/DEVLOG.md.)
        latest = tick + FOXY_PHASE_SPREAD + self._foxy_lag_allowance(tick)
        min_lock = rules.FOXY_LOCK_MIN_FRAMES * rules.FRAME
        for start, end in self.view_intervals[-4:]:
            first = start + FOXY_CLOCK_MARGIN          # picture certainly showing from here ...
            last = end - FOXY_CLOCK_MARGIN             # ... until here
            if last < first or first > tick - FOXY_PHASE_EARLY:
                continue
            last_relock = math.floor(last * 10 + 1e-9) / 10   # latest 0.1 s instant <= last
            if last_relock < first:
                continue
            protected_until = max(last, last_relock + min_lock - FOXY_CLOCK_MARGIN)
            if protected_until >= latest:
                return True
        return False

    def _door_check_needed(self, watch: DoorWatch) -> bool:
        """A light check is needed if they could have arrived at the last tick
        (or a "certainly sent back" is to be verified, see _account_for_ticks)."""
        return (not watch.at_door and not watch.checked_since_tick and not watch.door_closed
                and (watch.min_moves == 0 or watch.verify_departure))

    def _peek_needed(self, watch: DoorWatch, now: float) -> bool:
        """They were (or may be) at the closed door and one of their ticks has
        passed, so they may have gone. Never during a Foxy door hold."""
        if watch is self.left and (self.foxy_door_hold or self.foxy_emergency):
            return False
        return (watch.at_door and watch.door_closed and not watch.checked_since_tick
                and now >= watch.moving_until and now >= watch.reopen_after)

    # ------------------------------------------------------------------
    # Choosing what to do next
    # ------------------------------------------------------------------

    def _pan_time(self, side: str) -> float:
        return 0.0 if getattr(self.body, "facing", None) == side else PAN_SECONDS

    def _press(self, kind: str, side: str) -> None:
        """Click a door/light button (the body waits out the click cooldown)."""
        self.body.press(kind, side)
        self.last_press_at = self.body.now()

    def _press_door(self, watch: DoorWatch, reason: str = "") -> None:
        """Toggle a door. The game ignores door clicks while the door is still
        moving, so first wait for its previous animation to finish; then
        remember when this one will finish."""
        self.body.face(watch.side)
        self.body.wait_until(max(self.body.now(), watch.moving_until))
        self._press("door", watch.side)
        self._book_door(watch, reason)
        watch.door_closed = not watch.door_closed
        self._confirm_door_click(watch)
        duration = rules.DOOR_CLOSE_SECONDS if watch.door_closed else rules.DOOR_OPEN_SECONDS
        # The game ignores a door click while the door is still moving, so
        # the next click waits for the animation plus a frame or two.
        watch.moving_until = self.body.now() + duration + CLOCK_MARGIN + 0.05
        if watch.door_closed:
            watch.closed_at = self.body.now()
            watch.close_at = None

    # -- what is using power -----------------------------------------------

    def _book_door(self, watch: DoorWatch, reason: str) -> None:
        """Keep the door ledger: every second a door is shut costs power, and
        on a 4/20 night everything the bot does must fit in ~28 % of the
        battery (the rest is the game's own drain). Called just before a
        door is toggled."""
        now = self.body.now()
        if watch.door_closed:
            self.door_seconds[watch.side] += now - self.door_shut_since[watch.side]
        else:
            self.door_shut_since[watch.side] = now
            self.door_shut_reason[watch.side] = reason or "?"
        # One line per door click, whatever caused it (tools/door_report.py).
        log.info("%.2fs  DOOR %s %s (%s)", now, watch.side, "opens" if watch.door_closed else "shuts", reason or "?")

    def _door_note(self, watch: DoorWatch) -> str:
        """Short door state for the status panel: open, or shut for how long
        and why."""
        if not watch.door_closed:
            return f"{watch.side[0].upper()} open"
        shut_for = self.body.now() - self.door_shut_since[watch.side]
        return f"{watch.side[0].upper()} SHUT {shut_for:.0f}s ({self.door_shut_reason[watch.side][:18]})"

    def _power_ledger(self) -> str:
        """One line: how long each door has been shut (and why it is shut
        now, and since when nobody was SEEN there), and the camera time."""
        now = self.body.now()
        parts = []
        for watch in (self.left, self.right):
            total = self.door_seconds[watch.side]
            if watch.door_closed:
                shut_for = now - self.door_shut_since[watch.side]
                total += shut_for
                state = (f"SHUT {shut_for:.0f} s ({self.door_shut_reason[watch.side]}; "
                         f"{watch.who} last seen there {now - watch.seen_at_door_at:.0f} s ago)")
            else:
                state = "open"
            parts.append(f"{watch.side} door {state}, {total:.0f} s shut in all")
        camera = sum(end - start for start, end in self.view_intervals_all)
        return "; ".join(parts) + f"; camera up {camera:.0f} s"

    def _confirm_door_click(self, watch: DoorWatch) -> None:
        """Make sure the game saw the door click.

        The game occasionally misses a click (a live replay was lost when a
        just-in-time click never closed the door - docs/DEVLOG.md). The
        door button's lamp changes colour the moment a click is accepted,
        so read it and click again if nothing happened."""
        wanted = "closed" if watch.door_closed else "open"
        for attempt in range(3):
            # Two looks: the game applies a click on its next frame and the
            # screenshot lags another, so one early look can show the old
            # colour. A click repeated on that evidence would TOGGLE the
            # door the wrong way.
            self.body.wait_until(self.body.now() + DOOR_LAMP_SETTLE)
            seen = self.body.door_state(watch.side)
            if seen is None or seen == wanted:
                return
            self.body.wait_until(self.body.now() + DOOR_LAMP_SETTLE)
            seen = self.body.door_state(watch.side)
            if seen is None or seen == wanted:
                return
            if attempt == 2:
                log.warning("%s door click lost three times - giving up (button %s)", watch.side, seen)
                return
            log.warning("%s door click was lost (button still %s) - clicking again", watch.side, seen)
            self.body.snapshot(f"lost_click_{watch.side}")
            self.body.wait_until(max(self.body.now(), self.last_press_at + BUTTON_COOLDOWN))
            self._press("door", watch.side)

    def _next_commitment(self, now: float) -> float:
        """The next moment the bot must be free for something precise: a
        Foxy camera flip or a planned door click."""
        times = [self._jit_due(w) for w in (self.left, self.right) if w.close_at is not None]
        freeze = self._next_freeze_start(now)
        if freeze is not None:
            times.append(freeze)
        return min(times) if times else math.inf

    def _latest_light_start(self, watch: DoorWatch, now: float) -> float:
        """Latest moment a light check may start: before their next tick, and
        early enough not to delay the next flip / door click."""
        deadline = self._tick_after(watch, now) - CHECK_DEADLINE_LEAD
        free_until = self._next_commitment(now) - LIGHT_CHECK_SECONDS - BUTTON_COOLDOWN - 0.1
        return max(now, min(deadline, free_until)) if free_until > now else deadline

    def _jit_due(self, watch: DoorWatch) -> float:
        """When we must START heading for a planned door click: time to pan,
        plus a possible click cooldown, plus a safety margin."""
        return watch.close_at - self._pan_time(watch.side) - BUTTON_COOLDOWN - JIT_HEADROOM

    def _choose_job(self, now: float):
        """Return the most urgent action to do right now, or None to wait.

        Priority order (a job only starts if it cannot make anything above
        it late):
          1. planned just-in-time door clicks       - safety, hard deadline
          2. Foxy alert (he may have left the cove) - safety
          3. light checks through an OPEN door      - safety, deadline = their next tick
          4. the Foxy camera flip                   - keeps Foxy frozen
          5. peeks through a door shut on someone   - only saves power (the
             door is already protecting us), so it waits for a free moment
        """
        # 1) Just-in-time door clicks.
        hard = sorted((self._jit_due(w), w) for w in (self.left, self.right) if w.close_at is not None)
        if len(hard) == 2:
            # Both doors are due. If the second click could not follow the
            # first (cooldown + pan over) in time, shut that door right now -
            # but only while there is still time to pan back and make the
            # first click on schedule. (Shutting the second door 0.2 s before
            # the first click once made that click 0.4 s late: Bonnie in.)
            (first_due, first), (_, second) = hard
            room_to_pan_back = (now + self._pan_time(second.side) + BUTTON_COOLDOWN + PAN_SECONDS + 0.15
                                <= first.close_at)
            if (second.close_at < first.close_at + BUTTON_COOLDOWN + PAN_SECONDS + 0.3
                    and now >= first_due - 1.5 and room_to_pan_back):
                return lambda w=second: self._close_door(w, reason="two doors due together", after=now)
        for due, watch in hard:
            if now >= due:
                return lambda w=watch: self._jit_close(w)
        next_hard = hard[0][0] if hard else math.inf

        def shut_planned_door_now(reason: str):
            _, urgent = hard[0]
            return lambda w=urgent: self._close_door(w, reason=reason, after=self.body.now())

        # 2) Foxy may have left the cove: shut the left door and go and look.
        # A light check whose deadline falls inside the alert (it takes a
        # few seconds) goes first: Foxy needs 25 s from leaving the cove to
        # attack, Bonnie/Chica need one tick to step in through an open door.
        # Foxy at stage 3 attacks exactly 1500 frames (25 s) later, whatever
        # the cameras do (events [318]-[320]) - and silently: the running
        # sound only plays when he is MADE to run by viewing West Hall. So a
        # possible stage 3 leaves time for a cheap look on a normal flip;
        # the full alert (doors shut, look) only runs near the fuse's end.
        if (self.foxy_max_stage >= 3 and not self.foxy_emergency and now >= self.foxy_alert_retry_at
                and self._foxy_can_attack(now)
                and now >= self.foxy_fuse_from + FOXY_FUSE_SECONDS - FOXY_ALERT_LEAD):
            for watch in (self.left, self.right):
                if (self._door_check_needed(watch)
                        and self._tick_after(watch, now) - CHECK_DEADLINE_LEAD < now + FOXY_ALERT_SECONDS):
                    # ...unless a planned door click would be made late by
                    # it: then that door is shut first (once, a check run
                    # here pushed Bonnie's click onto his tick).
                    if hard:
                        check = self._pan_time(watch.side) + LIGHT_CHECK_SECONDS + BUTTON_COOLDOWN + 0.4
                        pan_back = 0.0 if hard[0][1].side == watch.side else PAN_SECONDS
                        if now + check + pan_back + 0.1 > hard[0][1].close_at:
                            return shut_planned_door_now("before a doorway check")
                    return lambda w=watch: self._check_doorway(w)
            return self._foxy_alert

        freeze_start = self._next_freeze_start(now)
        freeze_end = self._freeze_window(now)[1] if freeze_start is not None else None

        # 2b) A door shut through someone's tick: reopen it (with a look if
        # there is time, blind otherwise) as soon as nothing with a deadline
        # would be made late. Every second a door stays shut after their
        # tick costs a power charge, so this comes before the routine
        # checks and flips - but never delays them.
        checks_needed = [w for w in (self.left, self.right) if self._door_check_needed(w)]

        def nothing_late(duration: float, skip_flip: bool = False) -> bool:
            commitment = next_hard if skip_flip else min(self._next_commitment(now), next_hard)
            if now + duration > commitment:
                return False
            for w in checks_needed:
                check = self._pan_time(w.side) + LIGHT_CHECK_SECONDS + BUTTON_COOLDOWN + 0.4
                if now + duration + check > self._tick_after(w, now) - CHECK_DEADLINE_LEAD:
                    return False
            return True

        # Someone SEEN at a shut door: watch them leave. The light goes on
        # just before their next tick and its lamp is watched - the game
        # switches it off on the very frame they leave. That proves they
        # have gone without opening the door, and times their tick, which
        # measures the timers' lag (see _watch_leave).
        for watch in (self.left, self.right):
            plan = self._watch_plan(watch, now)
            if plan is None:
                continue
            start, light_by, _, end = plan
            # (Started up to half a second early: the job waits for its moment.)
            if (now >= start - 0.5
                    and now + self._pan_time(watch.side) <= light_by - LIGHT_ON_SECONDS + 0.02
                    and nothing_late(end - now + BUTTON_COOLDOWN + 0.1, skip_flip=self._lag_hungry())):
                return lambda w=watch, p=plan: self._watch_leave(w, p)

        # A door shut on someone who has certainly gone (see
        # _certainly_repelled) and is not held shut for Foxy: just open it.
        for watch in (self.left, self.right):
            if self._needlessly_shut(watch, now) and nothing_late(self._pan_time(watch.side) + 0.3):
                return lambda w=watch: self._open_needless(w)

        # The door that has been shut longest goes first (a door shut early
        # for "two doors due together" otherwise waited behind the other
        # door's reopen and the flip every cycle).
        for watch in sorted((self.left, self.right), key=lambda w: w.closed_at):
            if self._peek_needed(watch, now) and not self._watch_coming(watch, now):
                if nothing_late(self._peek_estimate(watch)) and self._peek_fits(watch, now):
                    return lambda w=watch: self._peek(w)
                # A left peek that keeps losing to Chica's routine check: the
                # left door can only be checked by opening it, but Chica can
                # be checked through her window with the right door SHUT. So
                # shut the right door (one cheap cycle) to make room - a left
                # door waiting for a gap once stayed shut for 194 s.
                other = self.right if watch is self.left else self.left
                if (not SEEN_THROUGH_SHUT_DOOR[watch.side] and SEEN_THROUGH_SHUT_DOOR[other.side]
                        and other in checks_needed and now - watch.closed_at > STUCK_PEEK_SECONDS
                        and self._peek_fits(watch, now)
                        and now + self._peek_estimate(watch) + PAN_SECONDS + BUTTON_COOLDOWN + 0.3
                        <= min(self._next_commitment(now), next_hard)):
                    return lambda o=other: self._shut_unchecked(o, reason="to make room for a peek")
                # A quick blind reopen may push the next flip back a little:
                # flips are planned with that much slack (see the gap list
                # in _next_freeze_start) and _hold_until still covers the tick.
                # Blind reopens keep cycling as long as nobody LOOKS: if it
                # is not even known that they are at the door (it was shut
                # for Foxy or on a failed light), wait for a peek instead.
                # (Chica's window can be checked with the door shut, so her
                # door is never reopened blind.) An unseen Bonnie's door is
                # reopened blind and then LOOKED through before the planned
                # closing click - see _look_while_open.
                if SEEN_THROUGH_SHUT_DOOR[watch.side] or not BLIND_REOPENS:
                    continue
                # (it first waits for the door to finish closing, if it is)
                quick = max(self._pan_time(watch.side), watch.moving_until - now) + 0.3
                if nothing_late(quick) or (now + quick <= min(self._next_commitment(now) + REOPEN_FLIP_SLACK, next_hard)
                                           and all(now + quick + 1.5 < self._tick_after(w, now) for w in checks_needed)):
                    return lambda w=watch: self._reopen_blind(w)

        # 2c) A door reopened blind: flash the light before its planned
        # closing click. If they have gone, the click is cancelled and the
        # door stays open; if they are there, the click goes ahead.
        for watch in (self.left, self.right):
            if not watch.door_closed and watch.at_door and watch.close_at is not None and not watch.looked_while_open:
                look = self._pan_time(watch.side) + LIGHT_CHECK_SECONDS + BUTTON_COOLDOWN + 0.4
                if now + look <= self._jit_due(watch) - 0.1 and nothing_late(look):
                    return lambda w=watch: self._look_while_open(w)

        # 3) Safety checks through open doors, most urgent first.
        checks = []
        for watch in (self.left, self.right):
            if self._door_check_needed(watch):
                deadline = self._tick_after(watch, now) - CHECK_DEADLINE_LEAD
                # Pan, wait for a quiet moment, light on, look, light off
                # (after the click cooldown). An optimistic estimate here
                # makes the next Foxy flip late, and a late flip does not
                # cover his tick.
                estimate = self._pan_time(watch.side) + LIGHT_CHECK_SECONDS + BUTTON_COOLDOWN + 0.4
                checks.append((deadline, estimate, watch))
        first = self._best_first(now, checks, freeze_start, freeze_end) if checks and not hard else None
        for deadline, estimate, watch in sorted(checks, key=lambda c: c[0]):
            job = lambda w=watch: self._check_doorway(w)
            if first == "flip":
                break                 # the flip goes first; the checks fit after it
            if first is not None and first is not watch:
                continue              # the other check goes first
            if hard:
                planned = hard[0][1]
                # Does the check fit BEFORE the planned click (including the
                # pan over to that door afterwards)? Bonnie's and Chica's
                # ticks keep almost the same spacing all night, so this
                # question comes up every cycle; answering it too
                # cautiously shut a door early every 5 s.
                pan_back = 0.0 if planned.side == watch.side else PAN_SECONDS
                if now + estimate + pan_back + 0.1 > planned.close_at:
                    # Can it wait until after the click instead? Only if it
                    # still fits between that click and its own deadline.
                    # (Deferring it without that test once let Chica in -
                    # docs/DEVLOG.md.)
                    after_click = planned.close_at + BUTTON_COOLDOWN + estimate + 0.15
                    if deadline > after_click:
                        continue
                    # Otherwise move the click EARLIER, just enough for the
                    # check to follow it before its deadline: a door shut a
                    # second early costs one power charge, a door shut now
                    # costs several.
                    earlier = deadline - estimate - BUTTON_COOLDOWN - 0.15
                    if earlier >= now + self._pan_time(planned.side) + BUTTON_COOLDOWN + 0.1:
                        planned.close_at = earlier
                        continue
                    return shut_planned_door_now("schedule conflict")
            if freeze_start is None or now + estimate <= freeze_start:
                return job
            if freeze_end + estimate > deadline:   # (estimate already includes the pan)
                return job        # cannot wait for the flip: safety first
            # ... nor if, after the flip, ALL the waiting checks would not fit
            # one after the other (judging this one alone let the flip go
            # first, and the second of two checks due together came too
            # late - simulated 4/20 seed 28: Chica walked in).
            if not self._checks_fit_after(freeze_end, sorted(checks, key=lambda c: c[0])):
                return job
            # Otherwise do the flip first; the check fits afterwards.

        # 3b) A cheap look at Pirate Cove while the right door happens to be
        # fully shut anyway (for Chica): Freddy cannot get in, so no door
        # has to be shut for it (see COVE_LOOK_EVERY).
        if (now - self.foxy_verified_at > COVE_LOOK_EVERY and not self.foxy_emergency
                and self.right.door_closed and now >= self.right.moving_until
                and self.right.close_at is None and nothing_late(COVE_LOOK_SECONDS)):
            return self._cove_look_while_right_shut

        # 4) The Foxy flip.
        if freeze_start is not None and hard and freeze_end + 0.05 > next_hard:
            # The flip would run into a planned door click: shut that door
            # first (costs a little power) and keep Foxy frozen. Started
            # early enough for the pan and the click cooldown to fit BEFORE
            # the flip - started at the flip time, it made flips 0.8 s late
            # on the live game, and late flips do not cover Foxy's tick.
            lead = self._pan_time(hard[0][1].side) + BUTTON_COOLDOWN + FLIP_DOOR_SLACK
            if now >= freeze_start - lead:
                return shut_planned_door_now("before camera flip")
        if freeze_start is not None and now >= freeze_start - 0.005:
            return self._freeze_foxy

        # 5) Nothing else to do (peeks and reopens were considered in 2b):
        # warm-up door cycles, if one fits before the next commitment.
        if self.warmup_sides and now < WARMUP_UNTIL:
            side = self.warmup_sides[0]
            if nothing_late(self._pan_time(side) + WARMUP_CYCLE_SECONDS):
                return lambda sd=side: self._warmup_cycle(sd)
        return None

    def _best_first(self, now: float, checks: list, freeze_start: float | None,
                    freeze_end: float | None):
        """Which of the waiting light checks and the next Foxy flip to do
        first: the watch of a check, "flip", or None (no order works - fall
        back to the safety-first rule: checks by deadline).

        Bonnie's, Chica's and Foxy's timers have almost the same period
        (4.97, 4.98, 5.01 s), so their deadlines bunch up in the same
        couple of seconds for minutes on end. Taking the checks simply by
        deadline often did both before the flip, and the second one made
        the flip late - a late flip leaves Foxy's tick uncovered, and on the
        live 4/20 nights 15 - 22 ticks a night went uncovered (8 - 17 Foxy
        alerts, each a left-door shut and a cove look). Here every order of
        (at most two) checks and the flip is tried, with the pans between the
        two sides: of the orders in which every check meets its deadline,
        the one that makes the flip least late wins."""
        if freeze_start is None:
            return None
        flip_length = freeze_end - max(freeze_start, now)
        items = [("check", deadline, estimate, watch) for deadline, estimate, watch in checks] + [("flip",)]
        facing = getattr(self.body, "facing", None)
        best = None
        for order in itertools.permutations(items):
            t, side, late, ok = now, facing, 0.0, True
            for item in order:
                if item[0] == "flip":
                    start = max(t, freeze_start)
                    late = start - freeze_start
                    t = start + flip_length
                else:
                    _, deadline, estimate, watch = item
                    pan_now = 0.0 if side == watch.side else PAN_SECONDS
                    # (the estimate already includes a pan from where the bot faces now)
                    t += estimate - self._pan_time(watch.side) + pan_now
                    side = watch.side
                    if t > deadline:
                        ok = False
                        break
            if ok and (best is None or (late, t) < best[0]):
                best = ((late, t), order[0])
        if best is None:
            return None
        return "flip" if best[1][0] == "flip" else best[1][3]

    def _checks_fit_after(self, start: float, ordered: list) -> bool:
        """Starting at ``start``, can these doorway checks be done one after
        the other in this order (panning between the sides), each switching
        its light on by its deadline (the deadline is for the light, not
        for the end of the check)?"""
        t, side = start, getattr(self.body, "facing", None)
        for deadline, estimate, watch in ordered:
            pan = 0.0 if side == watch.side else PAN_SECONDS
            if t + pan + 0.05 > deadline:
                return False
            t += estimate - self._pan_time(watch.side) + pan
            side = watch.side
        return True

    def _peek_estimate(self, watch: DoorWatch) -> float:
        """How long a peek keeps the bot busy, generously: pan over, wait for
        the door to finish moving, open it, pick a quiet moment, flash the
        light, and possibly shut the door again. (An optimistic estimate
        once let a peek run into the other door's just-in-time click.)"""
        if SEEN_THROUGH_SHUT_DOOR[watch.side]:
            return self._pan_time(watch.side) + LIGHT_CHECK_SECONDS + BUTTON_COOLDOWN + 0.4
        return (self._pan_time(watch.side) + rules.DOOR_OPEN_SECONDS + LIGHT_CHECK_SECONDS
                + 2 * BUTTON_COOLDOWN + 0.5)

    def _peek_fits(self, watch: DoorWatch, now: float) -> bool:
        """A peek opens the door, so it must finish (including shutting it
        again if they are still there) well before their next tick: a door
        that is still OPENING at their tick lets them in once it is open."""
        if SEEN_THROUGH_SHUT_DOOR[watch.side]:
            # The door stays shut: only keep the light clear of their tick
            # (an arrival or departure switches the lights off).
            needed = self._pan_time(watch.side) + LIGHT_CHECK_SECONDS + MOVE_TICK_GUARD + 0.1
            return now + needed < self._tick_after(watch, now)
        needed = (self._pan_time(watch.side) + rules.DOOR_OPEN_SECONDS + CLOCK_MARGIN
                  + LIGHT_CHECK_SECONDS + BUTTON_COOLDOWN + JIT_MIN_LEAD + 0.3)
        return now + needed < self._tick_after(watch, now)

    def _idle(self, now: float) -> None:
        """Nothing urgent: get into position for the next job, then wait."""
        wake = now + 0.25
        freeze_start = self._next_freeze_start(now)
        planned = [w for w in (self.left, self.right) if w.close_at is not None]
        if freeze_start is not None:
            wake = min(wake, freeze_start)
            if planned:
                # A planned click may have to be done before the flip (see
                # _choose_job, step 4): wake in time for that decision.
                early = freeze_start - (PAN_SECONDS + BUTTON_COOLDOWN + FLIP_DOOR_SLACK)
                if early > now:
                    wake = min(wake, early)
        watches = [(plan[0], w) for w in (self.left, self.right)
                   if (plan := self._watch_plan(w, now)) is not None and self._watch_coming(w, now)]
        for start, _ in watches:
            if start > now:
                wake = min(wake, start)
        if planned:
            target = min(planned, key=lambda w: w.close_at).side
        elif watches and min(watches, key=lambda x: x[0])[0] - now < 1.5:
            target = min(watches, key=lambda x: x[0])[1].side
        else:
            # Face the side whose check comes next, so the check itself is quick.
            upcoming = min((self.left, self.right), key=lambda w: self._tick_after(w, now))
            target = upcoming.side if (upcoming.min_moves <= 1 or upcoming.at_door) else None
        if target and (freeze_start is None or freeze_start - now > PAN_SECONDS + 0.1):
            self.body.face(target)
        self.body.wait_until(max(self.body.now(), min(wake, self.body.now() + 0.25)))

    def _freeze_window(self, now: float) -> tuple[float, float] | None:
        """(camera raise starts, camera fully down) for the next Foxy flip."""
        start = self._next_freeze_start(now)
        if start is None:
            return None
        # A flip that also looks at Pirate Cove is up much longer than a
        # plain hold (4B read, switch, settle, cove read, switch back). The
        # plain figure once let such a flip overrun a planned door click.
        view = COVE_CHECK_VIEW_SECONDS + 0.3 if self._cove_check_due() else FREEZE_VIEW_SECONDS
        # An overdue flip starts NOW, not at its planned time: costing it
        # from the planned time once let a late cove-check flip run 0.8 s
        # into a planned door click.
        actual_start = max(start, now)
        return start, actual_start + self.body.camera_up_seconds + view + rules.CAMERA_DOWN_SECONDS

    # ------------------------------------------------------------------
    # Doorways
    # ------------------------------------------------------------------

    def _check_doorway(self, watch: DoorWatch) -> None:
        """Flash the light; close the door at once if Bonnie/Chica is there."""
        name = watch.who.capitalize()
        self.say(f"Looking for {name} ({watch.side} light)")
        self.body.face(watch.side)
        now = self.body.now()
        self.body.wait_until(self.quiet_light_start(now, self._latest_light_start(watch, now)))
        present, lit = self._flash_light(watch)
        if not lit:
            # The light did not come on: a click lost to timing - or they are
            # already inside (the game disables the switch then). Try again,
            # but never loop forever, and never gamble when their tick is
            # about to happen: shutting the door is always safe.
            watch.failed_checks += 1
            self.say(f"{name}: light did not come on - retrying", alert=True)
            tick_imminent = self._tick_after(watch, self.body.now()) - self.body.now() < LIGHT_FAIL_SHUT_LEAD
            if (watch.failed_checks >= 3 or tick_imminent) and not watch.door_closed:
                self._close_door(watch, reason="cannot see the doorway", after=self.body.now())
                watch.at_door = True
                watch.seen_for_sure = False
                watch.failed_checks = 0
            return
        watch.failed_checks = 0
        watch.checked_since_tick = True
        watch.verify_departure = False
        if present:
            watch.at_door = True
            watch.seen_for_sure = True
            watch.seen_at_door_at = self.last_look_at
            watch.min_moves = 0
        else:
            watch.min_moves = max(watch.min_moves, 1)

    def _flash_light(self, watch: DoorWatch) -> tuple[bool, bool]:
        """Light on, look, react, light off. Returns (present, lit)."""
        light_on_at = self.body.now()
        self._press("light", watch.side)
        present, lit = self.body.look_doorway(watch.side)
        # The moment they were SEEN (not after the door click that may
        # follow): their moves are counted from here (_account_for_ticks).
        self.last_look_at = self.body.now()
        if present and not watch.door_closed:
            self._react_to_sighting(watch, light_on_at)
        # Switch the light off once the click cooldown allows it.
        self.body.wait_until(max(self.body.now(), light_on_at + BUTTON_COOLDOWN))
        if self.body.light_is_on(watch.side):
            self._press("light", watch.side)
        return present, lit

    def _react_to_sighting(self, watch: DoorWatch, light_on_at: float) -> None:
        """Bonnie/Chica is in the doorway with the door open.

        They can only come in at their NEXT tick, so the door only has to be
        shut by then. With just-in-time doors the bot schedules the click for
        shortly before that tick (see _plan_close), which keeps the door from
        costing power for ~4 s. If there is not enough slack to do that
        safely, the door is shut right now.
        """
        close_at = self._plan_close(watch) if JIT_DOORS else None
        if close_at is None:
            self._close_door(watch, reason="seen in doorway", after=light_on_at)
            return
        watch.close_at = close_at
        self.say(f"{watch.who.upper()} AT {watch.side.upper()} DOOR - closing at "
                 f"{close_at:.2f}s, before their move at "
                 f"{self._tick_after(watch, self.body.now()):.2f}s", alert=True)

    def _close_door(self, watch: DoorWatch, reason: str, after: float) -> None:
        watch.close_at = None
        if watch.door_closed:
            return
        self.body.wait_until(max(self.body.now(), after + BUTTON_COOLDOWN))
        self._press_door(watch, reason=f"{watch.who} at the door: {reason}")
        self.say(f"{watch.who.upper()} AT {watch.side.upper()} DOOR - door closed ({reason})", alert=True)

    # -- just-in-time doors ------------------------------------------------

    def _plan_close(self, watch: DoorWatch, earliest_extra: float = 0.0,
                    after_light: bool = True) -> float | None:
        """Pick when to shut the door before their next tick, or None to shut now.

        Constraints (safety first):
          * the click lands at least JIT_MIN_LEAD before their tick;
          * it does not overlap another planned door click;
        then, among the allowed moments, prefer one where the fully-closed
        door is not caught by a whole-second power charge. ``earliest_extra``
        delays the earliest candidate (e.g. for a door that first has to
        open). ``after_light`` is True when the light is still on and its
        off-click (plus a cooldown) has to come first.
        """
        now = self.body.now()
        tick = self._tick_after(watch, now)
        latest = tick - JIT_MIN_LEAD
        if after_light:
            earliest = now + 2 * BUTTON_COOLDOWN + 0.1 + earliest_extra   # light-off click comes first
            if latest - earliest < JIT_MIN_SLACK:
                return None
        else:
            earliest = now + earliest_extra
            if latest < earliest:
                return None

        # Only the other door's click is avoided here. A collision with the
        # next Foxy flip is handled by the scheduler, which shuts the door
        # early ("before camera flip") - cheaper than finding no slot at all
        # and leaving the door shut for a whole tick cycle.
        busy: list[tuple[float, float]] = []
        for other in (self.left, self.right):
            if other is not watch and other.close_at is not None:
                # The other click may land a little late, needs its cooldown,
                # and the pan over here takes time: keep well clear of it.
                # (Two clicks planned 0.9 s apart once made the second one
                # late, and Chica walked in - docs/DEVLOG.md.)
                busy.append((other.close_at - PAN_SECONDS - BUTTON_COOLDOWN - 0.2,
                             other.close_at + BUTTON_COOLDOWN + PAN_SECONDS + 0.4))

        best, best_cost = None, None
        c = latest
        while c >= earliest:
            if not any(lo <= c <= hi for lo, hi in busy):
                cost = self._closed_door_charges(c, tick)
                if best_cost is None or cost < best_cost:
                    best, best_cost = c, cost
                    if cost == 0:
                        break
            c -= 0.02
        if best is None and busy:
            # Every candidate collides with the other door's planned click.
            # Bonnie's and Chica's ticks can sit half a second apart all
            # night, so this is not rare: move the OTHER click earlier by
            # the pan-and-cooldown spacing (one extra power charge there)
            # so that this door gets its slot - otherwise it would stay
            # shut for whole tick cycles (five charges each).
            other = self.right if watch is self.left else self.left
            spacing = PAN_SECONDS + BUTTON_COOLDOWN + 0.15
            shifted = latest - spacing
            if other.close_at is not None and shifted > now + self._pan_time(other.side) + BUTTON_COOLDOWN + 0.1:
                other.close_at = min(other.close_at, shifted)
                best = latest
        return best

    @staticmethod
    def _open_charges_saved(open_done: float, close_click: float) -> int:
        """Whole seconds (power charges) at which a door would be fully open
        between finishing opening at ``open_done`` and counting as closed
        again after a click at ``close_click``."""
        start = open_done + POWER_TICK_GUARD
        end = close_click + rules.DOOR_CLOSE_SECONDS - POWER_TICK_GUARD
        return max(0, math.floor(end) - math.ceil(start) + 1)

    @staticmethod
    def _closed_door_charges(close_click: float, tick: float) -> int:
        """Whole seconds (power charges) while the door would count as closed:
        from the end of its closing animation until the end of the reopening
        animation (reopened right after the tick, see _peek)."""
        closed_from = close_click + rules.DOOR_CLOSE_SECONDS - POWER_TICK_GUARD
        reopen_click = max(tick + AFTER_TICK, close_click + rules.DOOR_CLOSE_SECONDS + CLOCK_MARGIN)
        closed_until = reopen_click + rules.DOOR_OPEN_SECONDS + 0.1 + POWER_TICK_GUARD
        return max(0, math.floor(closed_until) - math.ceil(closed_from) + 1)

    def _jit_close(self, watch: DoorWatch) -> None:
        """Shut the door at the planned moment (see _plan_close)."""
        if watch.door_closed or watch.close_at is None:
            watch.close_at = None
            return
        self.body.face(watch.side)
        self.body.wait_until(watch.close_at)
        tick = self._next_tick(watch.who,watch.close_at - 0.01)
        if self.body.now() > tick - 0.1:
            log.warning("Late door click for %s (%.3f s before the tick)", watch.who, tick - self.body.now())
        self._close_door(watch, reason="just in time", after=self.body.now() - BUTTON_COOLDOWN)

    def _shut_unchecked(self, watch: DoorWatch, reason: str) -> None:
        """Shut a door instead of doing its due light check. They may be
        there (or arrive at the tick), so they are treated as possibly at the
        door until a look - for Chica a cheap window look - says otherwise."""
        self._press_door(watch, reason=reason)
        watch.at_door = True
        watch.seen_for_sure = False
        watch.seen_at_door_at = self.body.now()
        watch.checked_since_tick = True          # look again after their next tick
        self.say(f"{watch.who.upper()} AT {watch.side.upper()} DOOR - door closed ({reason})")

    def _look_while_open(self, watch: DoorWatch) -> None:
        """Flash the light through a door that was reopened blind, before its
        planned closing click. Their tick has passed since the reopen, so an
        empty doorway means they cannot be back before their NEXT tick."""
        name = watch.who.capitalize()
        self.say(f"Is {name} still there? (light, door open until {watch.close_at:.2f}s)")
        self.body.face(watch.side)
        now = self.body.now()
        self.body.wait_until(self.quiet_light_start(now, max(now, self._jit_due(watch) - LIGHT_CHECK_SECONDS - 0.2)))
        if watch.door_closed or watch.close_at is None:
            return
        light_on_at = self.body.now()
        self._press("light", watch.side)
        present, lit = self.body.look_doorway(watch.side)
        # The moment they were SEEN (not after the door click that may
        # follow): their moves are counted from here (_account_for_ticks).
        self.last_look_at = self.body.now()
        self.body.wait_until(max(self.body.now(), light_on_at + BUTTON_COOLDOWN))
        if self.body.light_is_on(watch.side):
            self._press("light", watch.side)
        watch.looked_while_open = True
        if not lit:
            return                      # no news: the planned click stays
        if present:
            watch.seen_for_sure = True
            watch.seen_at_door_at = self.last_look_at
            return
        watch.at_door = False
        watch.close_at = None
        watch.min_moves = max(watch.min_moves, 1)
        self.say(f"{name} has gone - {watch.side} door stays open")

    def _needlessly_shut(self, watch: DoorWatch, now: float) -> bool:
        """Shut although nobody is believed to be at it, with no planned click
        and no Foxy hold on it. Opening such a door is always safe: someone
        who arrives at an OPEN door only gets in on their NEXT move, and the
        normal doorway check after every tick catches the arrival."""
        if watch is self.left and (self.foxy_door_hold or self.foxy_emergency):
            return False
        return (watch.door_closed and not watch.at_door
                and watch.close_at is None and now >= watch.moving_until)

    # -- warm-up -----------------------------------------------------------

    def _warmup_tour(self, tick: float) -> None:
        """First Foxy flip of the night: show every camera once (see
        WARMUP_CAMERAS) before settling on 4B. Kept short enough that the
        picture still covers Foxy's tick the normal way."""
        self.say("Warm-up: every camera once")
        for camera in WARMUP_CAMERAS:
            # Stop early if the tour would push the hold past the tick.
            if self.body.now() > tick - FOXY_PHASE_EARLY - 0.6:
                break
            self.body.select_camera(camera)
            self.camera_selected = camera
        if self.camera_selected != "4B":
            self.body.select_camera("4B")
            self.camera_selected = "4B"
        self.warmup_tour_done = True

    def _warmup_cycle(self, side: str) -> None:
        """Shut and open one door and flash its light, once, early in the
        night (see WARMUP_CAMERAS)."""
        watch = self.left if side == LEFT else self.right
        self.warmup_sides.remove(side)
        if watch.door_closed or watch.at_door or watch.min_moves <= 1:
            return      # (never needed so early - but never risk it)
        self.say(f"Warm-up: {side} door and light once")
        self._press_door(watch)        # shut
        self._press_door(watch)        # open again (waits for the animation)
        self._press("light", side)
        self.body.wait_until(self.body.now() + BUTTON_COOLDOWN)
        if self.body.light_is_on(side):
            self._press("light", side)

    # -- watching them leave -------------------------------------------------

    def _watch_plan(self, watch: DoorWatch, now: float) -> tuple[float, float, float, float] | None:
        """(start, light on by, tick, watch until) for watching them leave at
        their next tick - or None if there is nobody to watch. Only someone
        SEEN at a shut door: the game sends them back (if they move at all)
        and the lights go off on that frame. (A door still closing at their
        tick only delays that until it is shut - see _watch_leave.)"""
        if not (watch.at_door and watch.door_closed and watch.seen_for_sure and watch.close_at is None):
            return None
        if watch is self.left and self.foxy_emergency:
            return None
        lead = self._pan_time(watch.side) + LIGHT_ON_SECONDS + WATCH_LEAD
        tick = self._next_tick(watch.who, now + lead - 0.03)
        if self.ai(tick)[watch.who] == 0:
            return None
        # Only their FIRST tick since they were last seen there proves
        # anything: after a tick nobody watched they may already have gone,
        # and then a lamp that stays lit (or goes dark because they ARRIVED
        # back) says nothing about the door. (Watching a later tick once
        # read Bonnie's arrival as his departure - simulator.)
        # (With the timers' lag, a tick whose earliest time is before the
        # sighting may still have come after it: the first tick that counts
        # is the first one that could have come after the sighting. Using
        # the first one after it on the model once read a Chica who had
        # already been sent back as "still at the door" - simulator.)
        seen = watch.seen_at_door_at
        if abs(tick - self._next_tick(watch.who, seen - self._lag_spread(seen) - 0.05)) > 0.5:
            return None
        light_by = tick - WATCH_LEAD
        start = light_by - LIGHT_ON_SECONDS - self._pan_time(watch.side)
        end = tick + self._lag_spread(tick) + WATCH_TAIL
        # A Foxy flip comes first: watch only until it has to start. Their
        # tick may still fall inside the shorter window (then it is measured
        # all the same); if not, the watch proves nothing either way.
        if not self._lag_hungry():
            window = self._freeze_window(now)
            if window is not None and window[1] > start:
                end = min(end, window[0] - BUTTON_COOLDOWN - 0.1)
                if end < tick + MIN_WATCH_AFTER_TICK:
                    return None
        return start, light_by, tick, end

    def _watch_coming(self, watch: DoorWatch, now: float) -> bool:
        """Is a departure watch planned for their next tick, with nothing
        else (a Foxy flip, a planned door click) in its way? Then peeks and
        blind reopens wait for it - it settles the same question without
        opening the door. After two planned watches in a row that did not
        happen, peeks go ahead again."""
        if watch.watch_skips >= 2:
            return False
        plan = self._watch_plan(watch, now)
        if plan is None:
            return False
        start, _, tick, end = plan
        busy_until = end + BUTTON_COOLDOWN + 0.1
        for w in (self.left, self.right):
            if w.close_at is not None and start - 0.3 < w.close_at < busy_until + PAN_SECONDS:
                return False
        watch.planned_watch_tick = tick
        return True

    def _lag_hungry(self) -> bool:
        """No lag measurement yet, and one uncovered Foxy tick is affordable:
        the first watch may then take a Foxy flip's place (see
        LAG_HUNGRY_FOXY_STAGE)."""
        now = self.body.now()
        if self.foxy_emergency or now < LAG_HUNGRY_AFTER:
            return False
        uncertain = not self.lag_samples or self._lag_spread(now) > LAG_HUNGRY_SPREAD
        if uncertain and self.foxy_max_stage < LAG_HUNGRY_FOXY_STAGE:
            return True
        stale = not self.lag_samples or now - self.lag_samples[-1][0] > LAG_RESAMPLE_EVERY
        return stale and self.foxy_max_stage < LAG_RESAMPLE_FOXY_STAGE

    def _other_unchanged(self, other: DoorWatch) -> bool:
        """After an ambiguous lights-out: look at the OTHER doorway (Chica's
        window shows even with her door shut). If they are still where we
        last knew them - at the door, or not - the lights went out for the
        one we were watching. Live 4/20 #15: all three watches ended
        "the other one may have moved", and each time the left door then
        stayed shut 14 - 20 s waiting for a peek."""
        if not (SEEN_THROUGH_SHUT_DOOR[other.side] or not other.door_closed):
            return False        # (Bonnie's doorway is hidden behind his shut door)
        if self._next_commitment(self.body.now()) - self.body.now() < PAN_SECONDS + 0.9:
            return False        # no time for the look before a flip / door click
        was_there = other.at_door
        self.body.face(other.side)
        self.body.wait_until(max(self.body.now(), self.last_press_at + BUTTON_COOLDOWN))
        present, lit = self._flash_light(other)
        if not lit:
            return False
        if present:
            other.at_door = True
            other.seen_for_sure = True
            other.seen_at_door_at = self.last_look_at
            other.min_moves = 0
        elif was_there:
            other.at_door = False
            other.min_moves = other.distance[other.repelled_to]
        return present == was_there

    def _other_may_have_moved(self, watch: DoorWatch, seen_at: float) -> float | None:
        """The lights go off when EITHER of them arrives at or leaves a
        doorway. Could the other one have done so at ``seen_at``? Returns
        the other's tick (model time) if so, else None."""
        other = self.right if watch is self.left else self.left
        if not (other.at_door or other.min_moves <= 2):
            return None
        tick = self._next_tick(other.who, seen_at - self._lag_spread(seen_at) - 0.15)
        if tick <= seen_at + 0.15 and self.ai(tick)[other.who] > 0:
            return tick
        return None

    def _watch_leave(self, watch: DoorWatch, plan: tuple[float, float, float, float]) -> None:
        """Light on across their tick; did the lamp go dark by itself?

        The game switches both hall lights off on the frame Bonnie or Chica
        arrives at or leaves a doorway (events [226]/[227], [259]/[260]).
        Someone at a fully shut door is sent back on their tick, so the lamp
        going dark then means they have GONE - no need to open the door to
        look - and it timestamps their tick to a screen grab, which tells
        the brain how far the game's timers have fallen behind (see
        LAG_NOISE). If the lamp stays lit they did not move: still there.
        """
        _, light_by, tick, end = plan
        name = watch.who.capitalize()
        self.body.face(watch.side)
        self.body.wait_until(max(self.body.now(), light_by - LIGHT_ON_SECONDS))
        self.say(f"Watching {name} leave (light on across their tick at {tick:.2f}s)")
        self._press("light", watch.side)
        self.body.wait_until(self.body.now() + LIGHT_ON_SECONDS)
        if not self.body.light_is_on(watch.side):
            log.info("%.2fs  the light did not come on - no watch this time", self.body.now())
            return
        dark_at = self.body.watch_lamp(watch.side, end)
        if dark_at is None and end < tick + self._lag_spread(tick):
            # Cut short (a Foxy flip was due) before their latest possible
            # tick: no conclusion. The door question goes to a peek.
            self.body.wait_until(max(self.body.now(), self.last_press_at + BUTTON_COOLDOWN))
            if self.body.light_is_on(watch.side):
                self._press("light", watch.side)
            log.info("%.2fs  no change before the Foxy flip - %s's tick not seen", self.body.now(), watch.who)
            return
        if dark_at is None:
            # Lit all through the window: no change seen. That is NOT a
            # sighting - if their tick came after the window (a lag larger
            # than allowed for), they may have gone unseen. So nothing is
            # concluded and a peek settles it. (Counting it as "still at
            # the door" let the simulator chain five such watches on a
            # Bonnie who had long gone, then read his ARRIVAL back as him
            # leaving and open the door.)
            self.body.wait_until(max(self.body.now(), self.last_press_at + BUTTON_COOLDOWN))
            if self.body.light_is_on(watch.side):
                self._press("light", watch.side)
            self.say(f"{name}: no change across their tick - a peek will tell")
            # Someone seen at a door shut well before their tick leaves at
            # that tick for certain at AI 20, so a watch that saw nothing
            # usually means the tick came after the window: the timers lag
            # more than the allowances say: the night switches to
            # the wide ones (live this happened on 2 of 35 watches since the
            # clock fix; with the old lag in the simulator, on nearly every
            # watch - and without this the narrow allowances lost 6 nights in 10).
            if (not self.lag_wide and watch.seen_for_sure and self.ai(tick)[watch.who] >= 20
                    and watch.closed_at <= tick - rules.DOOR_CLOSE_SECONDS - CLOCK_MARGIN):
                self.lag_misses += 1
                if self.lag_misses >= LAG_MISSES_FOR_WIDE:
                    self.lag_wide = True
                    log.warning("%.2fs  %d watches saw no departure - the timers may be running late: "
                                "wide timing margins from now on", self.body.now(), self.lag_misses)
            return
        other_tick = self._other_may_have_moved(watch, dark_at)
        if other_tick is not None:
            # Cannot tell who it was: leave the door to a normal peek after
            # the tick. Early in the night their two ticks are almost
            # together (4.97 / 4.98 s), and then the moment still measures
            # the lag - against the LATER of the two ticks, which can only
            # make the estimate too small (the safe side for door clicks).
            other = self.right if watch is self.left else self.left
            if SEEN_THROUGH_SHUT_DOOR[watch.side]:
                # Watching Chica: her window shows with the door shut, so
                # just look. Gone - the lights went out for her. Still
                # there - they went out for Bonnie, who has left his door.
                # (Live 4/20 #17: three such watches stayed "ambiguous", the
                # lag range stayed 0.1 - 1.0 s wide, and no peek through
                # Bonnie's door fitted for 82 s.)
                self.body.wait_until(max(self.body.now(), self.last_press_at + BUTTON_COOLDOWN))
                present, lit = self._flash_light(watch)
                if lit and present:
                    # The lights went out for the other one. That says
                    # nothing about HER tick: with the lag it may still be to
                    # come (counting it as "she stayed" once let a simulated
                    # Chica leave unseen, come back and walk in).
                    self._note_lag((other.who,), dark_at)
                    # It was his DEPARTURE only if this was his first tick
                    # since he was last seen at his door; after an unseen one
                    # it may be him ARRIVING back (simulator: that read
                    # opened Bonnie's door for him).
                    seen = other.seen_at_door_at
                    first = self._next_tick(other.who, seen - self._lag_spread(seen) - 0.05)
                    his_first_tick = dark_at < first + self._lag_spread(first) + 0.3
                    # (Only for someone actually SEEN there: a door released
                    # after a Foxy check marks him "possibly there", and a
                    # lights-out was then once his ARRIVAL - simulator.)
                    if other.at_door and other.seen_for_sure and other.door_closed and his_first_tick:
                        other.at_door = False
                        other.min_moves = other.distance[other.repelled_to]
                        other.checked_since_tick = True
                        self.say(f"Lights went out for {other.who.capitalize()} - he has left the "
                                 f"{other.side} door; {watch.who.capitalize()} is still at hers")
                    return
                if not lit:
                    self.say(f"Lights went out at {dark_at:.2f}s - but the other one may have moved too")
                    self._note_lag((watch.who, other.who), dark_at)
                    return
                # Gone: it was her tick (fall through to "she left").
            elif not self._other_unchanged(other):
                self.say(f"Lights went out at {dark_at:.2f}s - but the other one may have moved too")
                self._note_lag((watch.who, other.who), dark_at)
                return
            # The other one is where they were: the lights went out for us.
        # A door still closing at their tick holds the move until it is shut:
        # then the lights went off when the door finished, not at the tick -
        # a departure all the same, but no measure of the timers' lag.
        door_shut_at = watch.moving_until - CLOCK_MARGIN - 0.05
        if dark_at - LAMP_SEEN_DELAY > door_shut_at + 0.05 and self._note_lag((watch.who,), dark_at) is None:
            return
        watch.watched_tick = tick
        watch.watch_skips = 0
        watch.at_door = False
        watch.checked_since_tick = True
        watch.verify_departure = False
        watch.min_moves = watch.distance[watch.repelled_to]
        self.say(f"{name} left at {dark_at:.2f}s (seen by the light going out) - {watch.side} door can open")

    def _open_needless(self, watch: DoorWatch) -> None:
        self.body.face(watch.side)
        self.body.wait_until(max(self.body.now(), watch.moving_until))
        if self._needlessly_shut(watch, self.body.now()):
            self._press_door(watch, reason="open needless")
            self.say(f"{watch.who.capitalize()} has gone - {watch.side} door open")

    def _reopen_blind(self, watch: DoorWatch) -> None:
        """After their tick, when a peek does not fit: open the door now and
        plan the just-in-time click that shuts it again before their next
        tick. They are treated as possibly still there until a peek can
        look. A door that is open between two ticks costs nothing; one that
        stays shut for a whole tick costs ~0.5 % - so this saves power
        whenever the schedule is crowded (4/20 nights especially)."""
        name = watch.who.capitalize()
        self.body.face(watch.side)
        self.body.wait_until(max(self.body.now(), watch.moving_until))
        now = self.body.now()
        # The door takes 0.45 s to open and must start closing again
        # JIT_MIN_LEAD before the tick; _plan_close finds a closing click
        # that respects both (a reopen with a 1 s window once ended with the
        # closing click ignored because the door was still opening - and
        # Bonnie in). If there is no such moment, the door stays shut
        # through this tick and the question comes up again after it.
        # Earliest closing click: once the door has finished opening (the
        # game ignores clicks on a moving door) - no light is involved.
        open_done = now + rules.DOOR_OPEN_SECONDS + CLOCK_MARGIN + 0.05
        close_at = self._plan_close(watch, earliest_extra=open_done - now + 0.05, after_light=False)
        # Worth it only if the door is fully open across at least one
        # whole-second power charge before it counts as closed again: that
        # is exactly what the reopen saves. (A fixed minimum window used to
        # decide this; it refused reopens that would have saved a charge,
        # and the door stayed shut for the whole next cycle - five charges.)
        # ... and not if its closing click would run into the next Foxy flip:
        # the door is then shut "before camera flip", late, and the flip is
        # lost (live 4/20 #21).
        window = self._freeze_window(now)
        flip_clash = (BLIND_REOPEN_FLIP_GUARD and close_at is not None and window is not None
                      and window[0] < close_at + PAN_SECONDS + BUTTON_COOLDOWN)
        if (close_at is None or self._open_charges_saved(open_done, close_at) < 1
                or close_at - open_done < BLIND_MIN_OPEN or flip_clash):
            watch.reopen_after = self._tick_after(watch, now) + TICK_SETTLE + self._lag_spread(now)
            return
        self._press_door(watch, reason="reopen blind")
        watch.close_at = close_at
        watch.looked_while_open = False
        watch.checked_since_tick = True     # nothing to learn until their next tick
        self.say(f"{name} may still be there - door open until {close_at:.2f}s, then shut again")

    def _peek(self, watch: DoorWatch) -> None:
        """After their tick: reopen, look, close again if they are still there."""
        name = watch.who.capitalize()
        self.body.face(watch.side)
        self.body.wait_until(max(self.body.now(), watch.moving_until))
        now = self.body.now()
        if not self._peek_fits(watch, now):
            return  # too close to their next tick now; peek after it instead
        other = self.right if watch is self.left else self.left
        if other.close_at is not None and now + self._peek_estimate(watch) > self._jit_due(other):
            return  # the other door's planned click comes first
        through_shut_door = SEEN_THROUGH_SHUT_DOOR[watch.side]
        if through_shut_door:
            # Chica's window: look with the door still shut. Free of the
            # door's open/close cycle and of any risk.
            self.say(f"Checking whether {name} left (window, door stays shut)")
            start = self.body.now()
        else:
            self.say(f"Checking whether {name} left (peek)")
            self._press_door(watch, reason="peek")
            start = watch.moving_until
        self.body.wait_until(self.quiet_light_start(start, max(start, self._latest_light_start(watch, start))))
        present, lit = self._flash_light(watch)
        watch.checked_since_tick = True
        if not lit:
            # Could not see: be safe and shut the door again (if it was opened).
            if not watch.door_closed:
                self._close_door(watch, reason="could not see", after=self.body.now())
                watch.seen_for_sure = False
            return
        if present:
            # Still there (_flash_light has shut an opened door again).
            watch.seen_for_sure = True
            watch.seen_at_door_at = self.last_look_at
            return
        watch.at_door = False
        # (A door that stayed shut for the look is opened by the scheduler's
        # "needlessly shut" rule once nothing more urgent is waiting.)
        if not watch.seen_for_sure:
            # The door was shut only because we could not see; they may never
            # have been there. Assume the worst: they could arrive any tick.
            watch.min_moves = 0
        else:
            # They left on one of their ticks since we last SAW them at the
            # door, possibly the earliest one, and may have moved on since.
            # Count every tick after that first possible departure as a
            # possible step back towards us.
            later_moves = max(0, self._moves_since(watch, watch.seen_at_door_at, self.body.now()) - 1)
            watch.min_moves = max(0, watch.distance[watch.repelled_to] - later_moves)
        self.say(f"{name} went back towards {watch.repelled_to} - door open")
        # A door that stayed shut for the look (Chica's window): open it now,
        # while the bot faces it, if that makes nothing late. Left for "later"
        # it often waited until their next tick, which then counted as a
        # possible arrival behind the shut door and wanted another look -
        # 8 - 20 s of right door per Foxy alert on live campaign67.
        now = self.body.now()
        if self._needlessly_shut(watch, now) and now + 0.3 <= self._next_commitment(now):
            self._press_door(watch, reason="open needless")

    # ------------------------------------------------------------------
    # Foxy and the camera
    # ------------------------------------------------------------------

    def _foxy_flip_search_from(self, now: float) -> float:
        """The earliest of Foxy's ticks a flip started now can still cover:
        one whose LATEST possible moment (the lag range after the model's
        earliest one) is still after the picture can be up. Looking only at
        ticks after now silently dropped every flip that ran late - on live
        4/20 #20 a blind reopen and Chica's checks pushed the flip past his
        earliest tick each cycle, and he went 25 s without a single flip."""
        reach = self.body.camera_up_seconds + FOXY_CLOCK_MARGIN
        late = max(self._foxy_lag_allowance(now), LATE_FLIP_GRACE)
        return now + reach - FOXY_PHASE_SPREAD - late

    def _next_freeze_start(self, now: float) -> float | None:
        """When to start raising the camera for the next Foxy tick (or None)."""
        tick = self._next_tick("foxy", max(self._foxy_flip_search_from(now), self.foxy_frozen_tick + 0.01))
        if self.ai(tick)["foxy"] == 0 or self.foxy_emergency or not self._foxy_can_attack(now):
            return None
        # Camera picture showing during [view_start, view_end], ending close
        # to the tick but before the lock from the last re-lock runs out.
        # A flip that also looks at Pirate Cove stays up much longer.
        view = COVE_CHECK_VIEW_SECONDS if self._cove_check_due() else FREEZE_VIEW_SECONDS
        # The picture must start showing before the earliest possible tick
        # and hold a re-lock late enough for the latest one (Foxy's phase is
        # unknown within FOXY_PHASE_SPREAD), so the view straddles the tick.
        # The timers' lag may put the real tick up to _lag_spread() later:
        # the view ends that much later too, and starts no later than for
        # the earliest tick (so it gets longer while the lag is uncertain).
        shift = self._foxy_lag_allowance(tick)
        for gap in (-0.1, -0.05, 0.0, -0.15, 0.05):
            view_end = tick + shift - gap
            view_start = min(view_end - view, tick - FOXY_PHASE_EARLY - FOXY_CLOCK_MARGIN - 0.08)
            if self.power_safe(view_start, view_end - view_start):
                self._freeze_view_end = view_end
                return view_start - self.body.camera_up_seconds
        self._freeze_view_end = tick + shift + 0.15
        return (min(tick + shift + 0.15 - view, tick - FOXY_PHASE_EARLY - FOXY_CLOCK_MARGIN - 0.08)
                - self.body.camera_up_seconds)


    # -- camera sessions ---------------------------------------------------

    def _raise_camera(self) -> bool:
        """Raise the monitor (it always comes up on the last camera viewed,
        which the bot keeps on 4B). Returns False if it did not come up."""
        if not self.body.camera_up():
            self.say("Camera did not come up", alert=True)
            self.body.camera_down()
            return False
        self._view_started = self.body.now()
        shown = self.body.shown_camera()
        if self.camera_selected != "4B" or shown not in ("4B", None):
            # Normally only on the very first flip of the night (the game
            # starts on Show Stage). Otherwise a camera click was lost: the
            # monitor came up on another camera, and with Freddy on 4B and
            # the right door open that lets him in - switch to 4B at once.
            if self.camera_selected == "4B":
                log.warning("monitor came up on %s, not 4B - switching", shown)
            self.body.select_camera("4B")
            self.camera_selected = "4B"
        return True

    def _lower_camera_covering_foxy(self) -> None:
        """Lower the monitor - but if one of Foxy's ticks is due within the
        next second, keep the picture up long enough to cover it first.
        Used by the longer procedures (Foxy alerts), whose short camera
        views otherwise left the tick in the middle of them uncovered."""
        tick = self._next_tick("foxy", self.body.now() - FOXY_PHASE_EARLY)
        if self.ai(tick)["foxy"] > 0 and tick - self.body.now() < 1.0:
            self.foxy_frozen_tick = max(self.foxy_frozen_tick, tick)
            self.body.wait_until(self._hold_until(tick))
        self._lower_camera()

    def _lower_camera(self) -> None:
        """Lower the monitor, always leaving it set to 4B for next time."""
        if self.camera_selected != "4B":
            self.body.select_camera("4B")
            self.camera_selected = "4B"
        # Record when a picture was showing; Foxy's lock is judged from this.
        self.view_intervals.append((self._view_started, self.body.now()))
        self.view_intervals_all.append((self._view_started, self.body.now()))
        self.view_intervals = self.view_intervals[-8:]
        tick = self._next_tick("foxy",self._view_started)
        log.info("camera view %.2f-%.2f s; Foxy tick at %.2f %s", self._view_started, self.body.now(), tick,
                 "covered" if self._foxy_tick_covered(tick) else "NOT covered")
        self.body.camera_down()

    def _read_4b(self) -> bool:
        """Read E. Hall Corner. True if it is certainly empty (Freddy cannot be
        waiting there, so other cameras may be viewed this session)."""
        view = self.body.read_camera("4B")
        if not view["visible"]:
            return False
        self.freddy_at_4b = "F" in view["occupants"]
        if view["occupants"]:
            self.four_b_busy_at = self.body.now()
        return not view["occupants"]

    def _cove_look_while_right_shut(self) -> None:
        """Look at Pirate Cove now - the right door is shut, so a camera
        other than 4B is safe (Freddy only gets in through an open right
        door). Covers Foxy's next tick on the way down, like any flip."""
        if not self._raise_camera():
            return
        stage = self._look_at_cove()
        self._lower_camera_covering_foxy()
        if stage is None:
            self.foxy_verified_at = self.body.now() - COVE_LOOK_EVERY + 5.0   # try again soon
            return
        if stage >= 3 and self._foxy_can_attack(self.body.now()):
            self._foxy_emergency()

    def _look_at_cove(self) -> int | None:
        """View Pirate Cove (caller guarantees it is safe) and update Foxy.
        Returns the stage seen, or None if the picture was unreadable."""
        self.say("Checking Foxy (Pirate Cove)")
        self.body.select_camera("1C")
        # From the click itself: the game switches on that click, and the
        # wait for the new picture to show is not part of the pause.
        cove_from = self.body.game_to_real(getattr(self.body, "camera_clicked_at", self.body.now()))
        self.camera_selected = "1C"
        view = self.body.read_camera("1C")
        if not view["visible"] or view["foxy_stage"] is None:
            # One unreadable picture (a burst of static) is not "no news" yet:
            # read once more. Taken as "he may be out" straight away, two
            # such pictures held the left door shut 15 s on live campaign67
            # while Foxy sat at stage 0.
            view = self.body.read_camera("1C")
        if view["visible"] and view["foxy_stage"] == 3:
            # "Foxy has gone" triggers the emergency procedure, so make sure:
            # look again (the TV static is different in every frame).
            second = self.body.read_camera("1C")
            if not (second["visible"] and second["foxy_stage"] == 3):
                view = second
        self.body.select_camera("4B")
        self.camera_selected = "4B"
        # His timer stood still while the cove showed - unless he was at
        # stage 3, when it was standing still anyway (_foxy_timer_paused).
        if not (view["visible"] and view["foxy_stage"] is not None and view["foxy_stage"] >= 3):
            cove_to = self.body.game_to_real(getattr(self.body, "camera_clicked_at", self.body.now()))
            self._foxy_timer_paused(cove_to - cove_from, started_at=self.body.real_to_game(cove_from))
        if not view["visible"] or view["foxy_stage"] is None:
            return None
        self.foxy_stage = self.foxy_max_stage = view["foxy_stage"]
        if self.foxy_stage < 3:
            self.foxy_fuse_from = math.inf
            self.foxy_below3_seen_at = self.body.now()
        self.foxy_verified_at = self.body.now()
        return self.foxy_stage

    # -- Foxy ----------------------------------------------------------------

    def _freeze_foxy(self) -> None:
        """Short camera flip just before Foxy's tick, so his lock is running."""
        now = self.body.now()
        planned = self._next_freeze_start(now)
        tick = self._next_tick("foxy", max(self._foxy_flip_search_from(now), self.foxy_frozen_tick + 0.01))
        if planned is not None and now - planned > 0.1:
            log.info("%.2fs  flip for Foxy's tick at %.2f s starts %.2f s late", now, tick, now - planned)
        self.foxy_frozen_tick = tick
        cove_check = self._cove_check_due()
        self.say("Camera flip: checking Foxy" if cove_check else "Camera flip to hold Foxy (resting on 4B)")
        if not self._raise_camera():
            return
        if not self.warmup_tour_done and self.body.now() < WARMUP_UNTIL:
            self._warmup_tour(tick)
        stage = None
        if cove_check and (self._right_door_safe() or self._read_4b()):
            stage = self._look_at_cove()
            if stage is None:
                # An unreadable cove is not "no news": the game blanks a
                # camera when someone moves in or out of that room, and a
                # blank Pirate Cove was the only sign that Foxy had just left
                # on a lost live 4/20 night. Treat it as "may be out".
                self.foxy_max_stage = 3
                self.foxy_fuse_from = -math.inf      # no time to lose
                self.say("Pirate Cove unreadable - Foxy may be out", alert=True)
        # Whatever was done up there, the picture must stay up long enough
        # to freeze Foxy for this tick (a cove check that finished early
        # once left half of all ticks uncovered in the simulator). A look at
        # the cove also paused his timer and moved this very tick later
        # (_foxy_timer_paused): if it now comes within a second, hold for
        # it too - lowering first left ~1 tick in 6 of the misses uncovered.
        # (foxy_frozen_tick has been moved by that pause; ``tick`` has not.)
        self.body.wait_until(self._hold_until(max(tick, self.foxy_frozen_tick)))
        self._lower_camera_covering_foxy()
        if stage is not None:
            self._after_cove_check(stage)

    def _hold_until(self, tick: float) -> float:
        """How long the camera picture must stay up to protect Foxy's ``tick``.

        The game re-rolls Foxy's lock only at its 0.1 s instants while a
        picture is "viewing" - which starts when the flip-up animation has
        finished - and the lock then lasts at least 0.833 s. So the picture
        must cover a re-lock instant close enough to the tick, through the
        NEXT instant as well (one instant exactly on the margin is not
        enough), never shorter than FREEZE_VIEW_SECONDS (the clock may be
        off by a few hundredths; a ~0.1 s hold once let Foxy reach stage 3
        unseen - docs/DEVLOG.md), and never shorter than the power-safe
        view that was planned."""
        first_relock = math.floor((self._view_started + FOXY_CLOCK_MARGIN) * 10 + 1) / 10
        min_lock = rules.FOXY_LOCK_MIN_FRAMES * rules.FRAME
        latest = tick + FOXY_PHASE_SPREAD + self._foxy_lag_allowance(tick)
        covering_relock = math.ceil((latest - (min_lock - FOXY_CLOCK_MARGIN)) * 10 - 1e-9) / 10
        planned_end = getattr(self, "_freeze_view_end", 0.0)
        if not (self._view_started < planned_end < latest):
            planned_end = 0.0
        return max(self.body.now(), self._view_started + FREEZE_VIEW_SECONDS, planned_end,
                   max(first_relock, covering_relock) + 0.1 + FOXY_CLOCK_MARGIN)

    def _foxy_timer_paused(self, seconds: float, started_at: float | None = None) -> None:
        """Foxy's timer stood still for ``seconds`` (real): all his ticks
        from now on come that much later.

        His tick event ([191]) checks "viewing != 99" (99 is Pirate Cove,
        event [141]) and "fox progress < 3" BEFORE its "every 5.01 seconds"
        timer, and Clickteam only counts an "every" timer down while it is
        evaluated - so it stands still while the cove is on screen. Measured
        live (tools/foxy_pause_test.py): holding the cove 2.56 s moved his
        ticks +2.54 s; without a hold, -0.13 s. Not knowing this, every cove
        look of the bot (alerts, checks) pushed his real ticks away from its
        flips, and on busy 4/20 nights he climbed a stage every few ticks."""
        if seconds <= 0:
            return
        if started_at is not None:
            # His ticks before the pause came on the old schedule: book them
            # first (shifting them too counted ticks a flip HAD covered as
            # uncovered - false Foxy alerts on live 4/20 #23).
            self._book_foxy_ticks(started_at)
        self.foxy_phase_shift += seconds
        shift = self.body.real_to_game(seconds) - self.body.real_to_game(0.0)
        self.foxy_last_tick_seen += shift
        self.foxy_frozen_tick += shift

    def _foxy_timer_restarted(self, at: float) -> None:
        """Foxy has just run (bang on the door) at night time ``at``. His
        timer fired at the tick that took him to stage 3 and then stood still
        (fox progress >= 3) until now - so his next tick is one full period
        from now (see _foxy_timer_paused)."""
        period = rules.TICK_PERIOD["foxy"]
        self.foxy_anchor = self.body.game_to_real(at) % period
        self.foxy_phase_shift = 0.0          # cove pauses from now on add to it
        self.foxy_last_tick_seen = at
        self.foxy_frozen_tick = at

    def _foxy_can_attack(self, now: float) -> bool:
        """Could Foxy still reach the office before 6 AM? He attacks only
        1500 frames (~25 s) after reaching stage 3 - so near the end of the
        night a Foxy who cannot climb to stage 3 AND sit out that fuse in
        time is harmless, and every flip, alert and forced run for him is
        wasted power. (Live 4/20 #19 ran out of power 40 s before 6 AM after
        four Foxy alerts and two runs in its last three minutes - the last
        run, at 490 s, could not have reached the door before 6 AM anyway.)"""
        end = rules.NIGHT_SECONDS + FOXY_END_MARGIN
        if self.foxy_max_stage >= 3:
            start = self.foxy_below3_seen_at
            if self.foxy_fuse_from != -math.inf:
                start = max(start, min(self.foxy_fuse_from, now))
            return start + FOXY_FUSE_SECONDS < end
        t = now
        for _ in range(3 - self.foxy_max_stage):     # one stage per tick of his, at best
            t = self._next_tick("foxy", t)
        return t + FOXY_FUSE_SECONDS < end

    def _cove_check_due(self) -> bool:
        """Look at Pirate Cove on this flip? Only when it is worth the time:
        Foxy may have moved since we last saw him (an uncovered tick), or it
        has been a while. A Foxy who was SEEN at stage 2 and whose every tick
        since was covered is still at stage 2 - no need to keep looking."""
        wanted = (self.foxy_max_stage > self.foxy_stage
                  or self.body.now() - self.foxy_verified_at > FOXY_VERIFY_EVERY)
        # A cove check needs 4B clear first (Freddy's rule). While somebody
        # was just seen on 4B, planning one would only make every flip long
        # - and a long flip usually spans a power charge - for nothing: the
        # plain flip keeps Foxy frozen just as well, and if his possible
        # stage reaches 3 the alert procedure shuts the right door and looks.
        four_b_blocked = self.body.now() - self.four_b_busy_at < FOUR_B_BUSY_SECONDS
        # A possible stage 3 is worth trying on every flip (4B is read
        # first; if it is occupied the flip just holds Foxy).
        # With the right door fully shut Freddy cannot get in whatever 4B
        # shows, so the flip can look at the cove anyway - at least every
        # COVE_LOOK_EVERY (on live 4/20 #17 the separate look never found a
        # free moment: 250 s without seeing the cove).
        right_shut = self._right_door_safe() and (self.body.now() - self.foxy_verified_at > COVE_LOOK_EVERY
                                                  or (COVE_LOOK_WHEN_MOVED and self.foxy_max_stage > self.foxy_stage))
        return wanted and (not four_b_blocked or self.foxy_max_stage >= 3 or right_shut)

    def _right_door_safe(self) -> bool:
        """Right door fully shut: any camera may show (Freddy's rule)."""
        return self.right.door_closed and self.body.now() >= self.right.moving_until

    def _foxy_alert(self) -> None:
        """Foxy may have left the cove (some of his ticks were not covered).

        Look at the cove - with the left door still open when there is
        plenty of time (see ALERT_OPEN_LOOK_SECONDS), otherwise shut it
        first (he can only come through it). If 4B is not clear, the right
        door is shut too before looking, because Freddy can only get in
        through an OPEN right door while a camera other than 4B is showing."""
        self._close_planned_doors_now()
        fuse_end = self.foxy_fuse_from + FOXY_FUSE_SECONDS
        now = self.body.now()
        if (fuse_end - now >= ALERT_OPEN_LOOK_SECONDS
                and self._left_safe_unwatched(now, now + ALERT_FULL_SECONDS)):
            # Plenty of time: look first, shut the left door only if he is out.
            self.say("Foxy might be out - looking (left door stays open)", alert=True)
        else:
            self._hold_left_for_foxy()
        shut_right = False
        if not self._raise_camera():
            return
        if not self._read_4b():
            self._lower_camera_covering_foxy()
            shut_right = not self.right.door_closed
            self._shut(self.right, "safe to look at Pirate Cove")
            # Shutting the right door took a while: still time to look with
            # the left door open? (Decided now, with the camera down - a
            # second raise just for this made the look ~1.5 s later.)
            now = self.body.now()
            if not self.foxy_door_hold and (fuse_end - now < ALERT_OPEN_SWITCH_SECONDS
                                            or not self._left_safe_unwatched(now, now + ALERT_LOOK_SECONDS)):
                self._hold_left_for_foxy()
            # The right door must be FULLY shut before another camera shows.
            self.body.wait_until(max(self.body.now(), self.right.moving_until))
            if not self._raise_camera():
                return
        stage = self._look_at_cove()
        self._lower_camera_covering_foxy()
        if shut_right:
            self._release(self.right)
        if stage is None:
            # Unreadable: keep the left door shut and try again in a moment
            # (not immediately, so the doorway checks still get their turn).
            self._hold_left_for_foxy()
            self.foxy_max_stage = 3
            self.foxy_fuse_from = -math.inf
            self.foxy_alert_retry_at = self.body.now() + 2.0
            return
        self._after_cove_check(stage)

    def _left_safe_unwatched(self, now: float, until: float) -> bool:
        """Can the left door stay open, with nobody looking, until ``until``
        and still leave time for a doorway check before Bonnie could step
        in? He steps in only at a tick of his that finds him already in the
        doorway: if he may be there now, the check must fit before his next
        tick; otherwise he can arrive at his next tick at the earliest, and
        the check must fit before the one after."""
        watch = self.left
        if watch.door_closed:
            return True
        if watch.at_door or watch.close_at is not None:
            return False
        check = PAN_SECONDS + LIGHT_CHECK_SECONDS + BUTTON_COOLDOWN + 0.4
        first = self._tick_after(watch, now)
        if self._door_check_needed(watch):
            return until + check <= first - CHECK_DEADLINE_LEAD
        if watch.min_moves >= 2:
            return True
        second = self._next_tick(watch.who, first + 0.01)
        return until + check <= second - CHECK_DEADLINE_LEAD

    def _hold_left_for_foxy(self) -> None:
        """Shut the left door and keep it shut until Foxy has been seen."""
        if self.foxy_door_hold:
            return
        self.say("Foxy might be out - left door shut until checked", alert=True)
        self.foxy_door_hold = True
        self._shut(self.left, "Foxy might be out")

    def _after_cove_check(self, stage: int) -> None:
        if stage >= 3 and self._foxy_can_attack(self.body.now()):
            self._foxy_emergency()
        elif self.foxy_door_hold:
            self.foxy_door_hold = False
            self._release(self.left)
            self.say(f"Foxy is still in the cove (stage {stage})")

    def _foxy_emergency(self) -> None:
        """Foxy has left the cove: shut the left door and make him run now.

        Viewing West Hall (2A) makes him run at once (he arrives 100 frames
        later), so the left door only stays shut for ~2 s instead of up to
        25 s. 2A is not 4B, so the right door is shut first for Freddy.
        """
        self.foxy_emergency = True
        self.say("FOXY LEFT THE COVE - closing doors", alert=True)
        self._close_planned_doors_now()
        self._shut(self.left, "Foxy is coming")
        shut_right = not self.right.door_closed
        self._shut(self.right, "safe to view West Hall")
        # Both doors must be FULLY shut before a camera other than 4B shows.
        self.body.wait_until(max(self.body.now(), self.left.moving_until, self.right.moving_until))
        self.say("Making Foxy run now (viewing West Hall)", alert=True)
        run_from = self.body.now()
        if self._raise_camera():
            self.body.select_camera("2A")
            self.camera_selected = "2A"
            # He starts running on the frame West Hall is chosen.
            run_from = getattr(self.body, "camera_clicked_at", self.body.now())
            self.body.wait_until(self.body.now() + 0.15)
            self._lower_camera()
        # He bangs on the closed door 100 frames after starting to run - and
        # his timer starts again from there. (Counted from lowering the
        # camera, this was 0.3 - 0.5 s late; a measured bang corrects it,
        # but his first bang of the night, 1 %, cannot be told from a charge.)
        bang_at = run_from + rules.FOXY_RUN_FRAMES * rules.FRAME
        # His bang costs power off the whole-second charges: keep it out of
        # the clock's power sightings.
        self.body.clock_deaf_from, self.body.clock_deaf_until = bang_at - 1.0, bang_at + 1.5
        self.body.wait_until(max(self.body.now(), bang_at + 0.6))
        self._foxy_timer_restarted(bang_at)
        self.foxy_emergency = False
        self.foxy_door_hold = False
        self.foxy_stage, self.foxy_max_stage = 0, 1      # he restarts at stage 0 or 1
        self.foxy_fuse_from = math.inf
        self.foxy_verified_at = self.body.now()   # he restarts in the cove (stage 0 or 1)
        if shut_right:
            self._release(self.right)
        self._release(self.left)
        self.say("Foxy hit the door - back to normal")

    # -- door helpers used by the Foxy procedures ---------------------------------

    def _close_planned_doors_now(self) -> None:
        """Before a long procedure: do every planned just-in-time door click
        right away, so the procedure can never make one of them late."""
        for watch in (self.left, self.right):
            if watch.close_at is not None and not watch.door_closed:
                self._shut(watch, "before a long action")
                watch.closed_at = self.body.now()

    def _shut(self, watch: DoorWatch, reason: str) -> None:
        """Shut a door for a Foxy/Freddy reason (if it is not shut already)."""
        if watch.door_closed:
            return
        self._press_door(watch, reason=reason)
        self.say(f"{watch.side} door closed ({reason})")

    def _release(self, watch: DoorWatch) -> None:
        """A door shut for Foxy/Freddy reasons is no longer needed for them.

        Nobody looked through it meanwhile. If Bonnie/Chica provably cannot
        be standing there (their distance bound is still >= 1), open it now.
        Otherwise treat them as possibly there: the door stays shut and the
        normal peek reopens it right after their next tick, which always
        leaves a full ~4.5 s to look and react."""
        if not watch.door_closed:
            return
        # Ticks that passed during the procedure have not been booked yet;
        # without this a door was once reopened right after Chica's arrival
        # tick, and she walked in at the next one (docs/DEVLOG.md).
        self._account_for_ticks(self.body.now())
        if not watch.at_door and watch.min_moves >= 1:
            self._press_door(watch, reason="release")
            return
        if not watch.at_door:
            watch.at_door = True
            watch.seen_for_sure = False
            watch.seen_at_door_at = self.body.now()
            # Look now if there is time before their next tick: the
            # procedure that held the door has just ended, so this is
            # usually the best moment of the cycle. (Waiting for a later
            # gap left the left door shut for 30-60 s on busy nights.)
            if self._peek_fits(watch, self.body.now()):
                watch.checked_since_tick = False
                self._peek(watch)
                return
            watch.checked_since_tick = True       # wait for their next tick
