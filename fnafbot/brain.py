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

# Our idea of "now" can be off by up to ~0.03 s; every precise plan keeps
# at least this much distance from a deadline.
CLOCK_MARGIN = 0.06

# Clicks are ignored for 10 frames after a door/light click.
BUTTON_COOLDOWN = 0.19

# Keep extra power use this far away from each whole-second power charge.
POWER_TICK_GUARD = 0.06

# A doorway check (light on -> look -> light off) keeps the light on this
# long on the real game (the off-click must wait out the 0.17 s click
# cooldown, plus looking and mouse time).
LIGHT_CHECK_SECONDS = 0.3

# Start checking this long after the animatronic's tick (the move happens on
# that frame; we wait a couple of frames to be sure it has been applied).
AFTER_TICK = 0.06

# Keep a hall light off this close to Bonnie's or Chica's ticks (an arrival
# or departure switches the lights off - see quiet_light_start()).
MOVE_TICK_GUARD = 0.08

# The light must be switched on at least this long before the animatronic's
# next tick, so that if they are there the door click (which has to wait for
# the click cooldown) still lands before that tick.
CHECK_DEADLINE_LEAD = BUTTON_COOLDOWN + 0.12 + CLOCK_MARGIN

PAN_SECONDS = 0.55

# Camera session for Foxy: the camera picture shows for about this long (just
# long enough to contain one of the game's 0.1 s re-lock instants), or much
# longer when the flip also reads 4B and looks at Pirate Cove.
FREEZE_VIEW_SECONDS = 0.25
COVE_CHECK_VIEW_SECONDS = 1.0
# The camera must go down no earlier than this before Foxy's tick: the lock
# set at the last re-lock lasts at least 50 frames (0.833 s).
FREEZE_LATEST_GAP = 0.833 - 0.1 - CLOCK_MARGIN

# Re-check Pirate Cove (only when it is safe) at least this often.
FOXY_VERIFY_EVERY = 30.0
# Roughly how long a Foxy alert (shut the left door, look at the cove, maybe
# shut the right door first) keeps the bot busy; used to let an urgent
# doorway check go first.
FOXY_ALERT_SECONDS = 3.0
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
JIT_MIN_LEAD = 0.4
# Only plan a later close if at least this much time is left to choose from.
JIT_MIN_SLACK = 0.6


class Body(Protocol):
    """What the brain needs from the game (real or simulated)."""

    def now(self) -> float: ...
    def wait_until(self, t: float) -> None: ...
    def night_over(self) -> bool: ...
    def face(self, side: str) -> None: ...
    def press(self, kind: str, side: str) -> None: ...
    def look_doorway(self, side: str) -> tuple[bool, bool]: ...
    def light_is_on(self, side: str) -> bool: ...
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
        self.foxy_verified_at = -1e9
        self.foxy_last_tick_seen = 0.0
        self.foxy_frozen_tick = 0.0        # last Foxy tick we have planned a flip for
        self.foxy_emergency = False        # Foxy left the cove: left door must stay shut
        self.foxy_door_hold = False        # left door shut until we have looked at the cove
        self.foxy_alert_retry_at = 0.0     # earliest time for another Foxy alert attempt
        self.view_intervals: list[tuple[float, float]] = []   # when a camera picture showed
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
        def hits_move_tick(start: float) -> bool:
            for interval in (rules.BONNIE_TICK, rules.CHICA_TICK):
                tick = rules.next_tick(interval, start - MOVE_TICK_GUARD)
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

    def _moves_since(self, watch: DoorWatch, after: float, until: float) -> int:
        """How many of their ticks (with AI > 0) fall in (after, until]."""
        ticks = rules.tick_times(watch.tick, after + 1e-6, until + 1e-6)
        return sum(1 for tick in ticks if self.ai(tick)[watch.who] > 0)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def play(self) -> None:
        self.say("Night started - watching the clock")
        while not self.body.night_over():
            now = self.body.now()
            self._account_for_ticks(now)
            job = self._choose_job(now)
            if job is None:
                self._idle(now)
                continue
            job()

    # ------------------------------------------------------------------
    # Bookkeeping: what can have changed since we last looked
    # ------------------------------------------------------------------

    def _account_for_ticks(self, now: float) -> None:
        for watch in (self.left, self.right):
            for tick in rules.tick_times(watch.tick, watch.last_tick_seen + 1e-6, now + 1e-6):
                watch.last_tick_seen = tick
                if self.ai(tick)[watch.who] == 0:
                    continue
                watch.checked_since_tick = False
                if not watch.at_door:
                    watch.min_moves = max(0, watch.min_moves - 1)
        # Foxy: every tick of his that no camera flip covered may have moved him.
        for tick in rules.tick_times(rules.FOXY_TICK, self.foxy_last_tick_seen + 1e-6, now + 1e-6):
            self.foxy_last_tick_seen = tick
            if self.ai(tick)["foxy"] > 0 and not self._foxy_tick_covered(tick) and self.foxy_max_stage < 3:
                self.foxy_max_stage += 1
                log.info("%.2fs  Foxy tick at %.2f s was not covered by a flip (could be stage %d)",
                         now, tick, self.foxy_max_stage)

    def _foxy_tick_covered(self, tick: float) -> bool:
        """Was Foxy's lock certainly running at this tick?

        While a camera picture shows, the game re-rolls the lock at every
        whole 0.1 s of night time to at least 50 frames (0.833 s). So a tick
        is covered only if such a 0.1 s instant certainly fell inside a
        picture-showing interval BEFORE the tick, no more than 0.833 s
        earlier. (A picture that appears a moment before the tick, but after
        the last 0.1 s instant, does NOT protect it.)"""
        for start, end in self.view_intervals[-4:]:
            first = start + CLOCK_MARGIN          # picture certainly showing from here ...
            last = min(end, tick) - CLOCK_MARGIN  # ... until here
            if last - first < 0.0:
                continue
            last_relock = math.floor(last * 10 + 1e-9) / 10   # latest 0.1 s instant <= last
            if last_relock >= first and tick - last_relock <= 0.833 - CLOCK_MARGIN:
                return True
        return False

    def _door_check_needed(self, watch: DoorWatch) -> bool:
        """A light check is needed if they could have arrived at the last tick."""
        return (not watch.at_door and not watch.checked_since_tick and watch.min_moves == 0
                and not watch.door_closed)

    def _peek_needed(self, watch: DoorWatch, now: float) -> bool:
        """They were (or may be) at the closed door and one of their ticks has
        passed, so they may have gone. Never during a Foxy door hold."""
        if watch is self.left and (self.foxy_door_hold or self.foxy_emergency):
            return False
        return (watch.at_door and watch.door_closed and not watch.checked_since_tick
                and now >= watch.moving_until)

    # ------------------------------------------------------------------
    # Choosing what to do next
    # ------------------------------------------------------------------

    def _pan_time(self, side: str) -> float:
        return 0.0 if getattr(self.body, "facing", None) == side else PAN_SECONDS

    def _press(self, kind: str, side: str) -> None:
        """Click a door/light button (the body waits out the click cooldown)."""
        self.body.press(kind, side)
        self.last_press_at = self.body.now()

    def _press_door(self, watch: DoorWatch) -> None:
        """Toggle a door. The game ignores door clicks while the door is still
        moving, so first wait for its previous animation to finish; then
        remember when this one will finish."""
        self.body.face(watch.side)
        self.body.wait_until(max(self.body.now(), watch.moving_until))
        self._press("door", watch.side)
        watch.door_closed = not watch.door_closed
        self._confirm_door_click(watch)
        duration = rules.DOOR_CLOSE_SECONDS if watch.door_closed else rules.DOOR_OPEN_SECONDS
        watch.moving_until = self.body.now() + duration + CLOCK_MARGIN
        if watch.door_closed:
            watch.closed_at = self.body.now()
            watch.close_at = None

    def _confirm_door_click(self, watch: DoorWatch) -> None:
        """Make sure the game saw the door click.

        The game occasionally misses a click (a live replay was lost when a
        just-in-time click never closed the door - docs/DEVLOG.md). The
        door button's lamp changes colour the moment a click is accepted,
        so read it and click again if nothing happened."""
        wanted = "closed" if watch.door_closed else "open"
        for _ in range(2):
            self.body.wait_until(self.body.now() + DOOR_LAMP_SETTLE)
            seen = self.body.door_state(watch.side)
            if seen is None or seen == wanted:
                return
            log.warning("%s door click was lost (button still %s) - clicking again", watch.side, seen)
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
        deadline = rules.next_tick(watch.tick, now) - CHECK_DEADLINE_LEAD
        free_until = self._next_commitment(now) - LIGHT_CHECK_SECONDS - BUTTON_COOLDOWN - 0.1
        return max(now, min(deadline, free_until)) if free_until > now else deadline

    def _jit_due(self, watch: DoorWatch) -> float:
        """When we must START heading for a planned door click: time to pan,
        plus a possible click cooldown, plus a safety margin."""
        return watch.close_at - self._pan_time(watch.side) - BUTTON_COOLDOWN - 0.12

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
        if self.foxy_max_stage >= 3 and not self.foxy_emergency and now >= self.foxy_alert_retry_at:
            for watch in (self.left, self.right):
                if (self._door_check_needed(watch)
                        and rules.next_tick(watch.tick, now) - CHECK_DEADLINE_LEAD < now + FOXY_ALERT_SECONDS):
                    return lambda w=watch: self._check_doorway(w)
            return self._foxy_alert

        freeze_start = self._next_freeze_start(now)
        freeze_end = (freeze_start + rules.CAMERA_UP_SECONDS + FREEZE_VIEW_SECONDS + rules.CAMERA_DOWN_SECONDS
                      if freeze_start is not None else None)

        # 3) Safety checks through open doors, most urgent first.
        checks = []
        for watch in (self.left, self.right):
            if self._door_check_needed(watch):
                deadline = rules.next_tick(watch.tick, now) - CHECK_DEADLINE_LEAD
                estimate = self._pan_time(watch.side) + LIGHT_CHECK_SECONDS + 0.25
                checks.append((deadline, estimate, watch))
        for deadline, estimate, watch in sorted(checks, key=lambda c: c[0]):
            job = lambda w=watch: self._check_doorway(w)
            if now + estimate + BUTTON_COOLDOWN > next_hard:
                # Can the check wait until after the planned door click? Only
                # if it still fits between that click and its own deadline.
                # (Bonnie's and Chica's ticks once fell 0.9 s apart: the
                # check was deferred, started after the click, and Chica
                # walked in while the light was still being switched on -
                # docs/DEVLOG.md.)
                after_click = hard[0][1].close_at + BUTTON_COOLDOWN + estimate + 0.15
                if deadline > after_click:
                    continue
                return shut_planned_door_now("schedule conflict")
            if freeze_start is None or now + estimate <= freeze_start:
                return job
            if freeze_end + PAN_SECONDS + estimate > deadline:
                return job        # cannot wait for the flip: safety first
            # Otherwise do the flip first; the check fits afterwards.

        # 4) The Foxy flip.
        if freeze_start is not None and now >= freeze_start - 0.005:
            if freeze_end + 0.05 > next_hard:
                # The flip would run into a planned door click: shut that door
                # now (costs a little power) and keep Foxy frozen.
                return shut_planned_door_now("before camera flip")
            return self._freeze_foxy

        # 5) Peeks, only when they fit before everything precise.
        for watch in (self.left, self.right):
            if self._peek_needed(watch, now):
                estimate = self._pan_time(watch.side) + rules.DOOR_OPEN_SECONDS + LIGHT_CHECK_SECONDS + 0.6
                if now + estimate <= min(self._next_commitment(now), next_hard) and self._peek_fits(watch, now):
                    return lambda w=watch: self._peek(w)
        return None

    def _peek_fits(self, watch: DoorWatch, now: float) -> bool:
        """A peek opens the door, so it must finish (including shutting it
        again if they are still there) well before their next tick: a door
        that is still OPENING at their tick lets them in once it is open."""
        needed = (self._pan_time(watch.side) + rules.DOOR_OPEN_SECONDS + CLOCK_MARGIN
                  + LIGHT_CHECK_SECONDS + BUTTON_COOLDOWN + JIT_MIN_LEAD + 0.3)
        return now + needed < rules.next_tick(watch.tick, now)

    def _idle(self, now: float) -> None:
        """Nothing urgent: get into position for the next job, then wait."""
        wake = now + 0.25
        freeze_start = self._next_freeze_start(now)
        if freeze_start is not None:
            wake = min(wake, freeze_start)
        planned = [w for w in (self.left, self.right) if w.close_at is not None]
        if planned:
            target = min(planned, key=lambda w: w.close_at).side
        else:
            # Face the side whose check comes next, so the check itself is quick.
            upcoming = min((self.left, self.right), key=lambda w: rules.next_tick(w.tick, now))
            target = upcoming.side if (upcoming.min_moves <= 1 or upcoming.at_door) else None
        if target and (freeze_start is None or freeze_start - now > PAN_SECONDS + 0.1):
            self.body.face(target)
        self.body.wait_until(max(self.body.now(), min(wake, self.body.now() + 0.25)))

    def _freeze_window(self, now: float) -> tuple[float, float] | None:
        """(camera raise starts, camera fully down) for the next Foxy flip."""
        start = self._next_freeze_start(now)
        if start is None:
            return None
        return start, start + rules.CAMERA_UP_SECONDS + FREEZE_VIEW_SECONDS + rules.CAMERA_DOWN_SECONDS

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
            tick_imminent = rules.next_tick(watch.tick, self.body.now()) - self.body.now() < LIGHT_FAIL_SHUT_LEAD
            if (watch.failed_checks >= 3 or tick_imminent) and not watch.door_closed:
                self._close_door(watch, reason="cannot see the doorway", after=self.body.now())
                watch.at_door = True
                watch.seen_for_sure = False
                watch.failed_checks = 0
            return
        watch.failed_checks = 0
        watch.checked_since_tick = True
        if present:
            watch.at_door = True
            watch.seen_for_sure = True
            watch.seen_at_door_at = self.body.now()
            watch.min_moves = 0
        else:
            watch.min_moves = max(watch.min_moves, 1)

    def _flash_light(self, watch: DoorWatch) -> tuple[bool, bool]:
        """Light on, look, react, light off. Returns (present, lit)."""
        light_on_at = self.body.now()
        self._press("light", watch.side)
        present, lit = self.body.look_doorway(watch.side)
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
                 f"{rules.next_tick(watch.tick, self.body.now()):.2f}s", alert=True)

    def _close_door(self, watch: DoorWatch, reason: str, after: float) -> None:
        watch.close_at = None
        if watch.door_closed:
            return
        self.body.wait_until(max(self.body.now(), after + BUTTON_COOLDOWN))
        self._press_door(watch)
        self.say(f"{watch.who.upper()} AT {watch.side.upper()} DOOR - door closed ({reason})", alert=True)

    # -- just-in-time doors ------------------------------------------------

    def _plan_close(self, watch: DoorWatch) -> float | None:
        """Pick when to shut the door before their next tick, or None to shut now.

        Constraints (safety first):
          * the click lands at least JIT_MIN_LEAD before their tick;
          * it does not overlap the next Foxy camera session (with time to
            pan back to this side afterwards) or another planned door click;
        then, among the allowed moments, prefer one where the fully-closed
        door is not caught by a whole-second power charge.
        """
        now = self.body.now()
        tick = rules.next_tick(watch.tick, now)
        latest = tick - JIT_MIN_LEAD
        earliest = now + 2 * BUTTON_COOLDOWN + 0.1   # light-off click comes first
        if latest - earliest < JIT_MIN_SLACK:
            return None

        busy: list[tuple[float, float]] = []
        freeze = self._freeze_window(now)
        if freeze:
            busy.append((freeze[0] - 0.05, freeze[1] + PAN_SECONDS + 0.05))
        for other in (self.left, self.right):
            if other is not watch and other.close_at is not None:
                busy.append((other.close_at - PAN_SECONDS - 0.1, other.close_at + PAN_SECONDS + 0.1))

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
        return best

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
        tick = rules.next_tick(watch.tick, watch.close_at - 0.01)
        if self.body.now() > tick - 0.1:
            log.warning("Late door click for %s (%.3f s before the tick)", watch.who, tick - self.body.now())
        self._close_door(watch, reason="just in time", after=self.body.now() - BUTTON_COOLDOWN)

    def _peek(self, watch: DoorWatch) -> None:
        """After their tick: reopen, look, close again if they are still there."""
        name = watch.who.capitalize()
        self.body.face(watch.side)
        self.body.wait_until(max(self.body.now(), watch.moving_until))
        if not self._peek_fits(watch, self.body.now()):
            return  # too close to their next tick now; peek after it instead
        self.say(f"Checking whether {name} left (peek)")
        self._press_door(watch)
        door_open = watch.moving_until
        self.body.wait_until(self.quiet_light_start(door_open, max(door_open, self._latest_light_start(watch, door_open))))
        present, lit = self._flash_light(watch)
        watch.checked_since_tick = True
        if not lit:
            # Could not see: be safe and shut the door again.
            if not watch.door_closed:
                self._close_door(watch, reason="could not see", after=self.body.now())
                watch.seen_for_sure = False
            return
        if present:
            # _flash_light already shut the door again.
            watch.seen_for_sure = True
            watch.seen_at_door_at = self.body.now()
            return
        watch.at_door = False
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

    # ------------------------------------------------------------------
    # Foxy and the camera
    # ------------------------------------------------------------------

    def _next_freeze_start(self, now: float) -> float | None:
        """When to start raising the camera for the next Foxy tick (or None)."""
        tick = rules.next_tick(rules.FOXY_TICK, max(now, self.foxy_frozen_tick + 0.01))
        if self.ai(tick)["foxy"] == 0 or self.foxy_emergency:
            return None
        # Camera picture showing during [view_start, view_end], ending close
        # to the tick but before the lock from the last re-lock runs out.
        # A flip that also looks at Pirate Cove stays up much longer.
        view = COVE_CHECK_VIEW_SECONDS if self._cove_check_due() else FREEZE_VIEW_SECONDS
        for gap in (0.25, 0.4, 0.15, 0.55, 0.05, -0.15):
            view_end = tick - gap
            view_start = view_end - view
            if self.power_safe(view_start, view) and gap <= FREEZE_LATEST_GAP:
                return view_start - rules.CAMERA_UP_SECONDS
        return tick - 0.25 - view - rules.CAMERA_UP_SECONDS


    # -- camera sessions ---------------------------------------------------

    def _raise_camera(self) -> bool:
        """Raise the monitor (it always comes up on the last camera viewed,
        which the bot keeps on 4B). Returns False if it did not come up."""
        if not self.body.camera_up():
            self.say("Camera did not come up", alert=True)
            self.body.camera_down()
            return False
        self._view_started = self.body.now()
        if self.camera_selected != "4B":
            # Only on the very first flip of the night (the game starts on
            # Show Stage); Freddy is still on stage then, so this is safe.
            self.body.select_camera("4B")
            self.camera_selected = "4B"
        return True

    def _lower_camera(self) -> None:
        """Lower the monitor, always leaving it set to 4B for next time."""
        if self.camera_selected != "4B":
            self.body.select_camera("4B")
            self.camera_selected = "4B"
        # Record when a picture was showing; Foxy's lock is judged from this.
        self.view_intervals.append((self._view_started, self.body.now()))
        self.view_intervals = self.view_intervals[-8:]
        self.body.camera_down()

    def _read_4b(self) -> bool:
        """Read E. Hall Corner. True if it is certainly empty (Freddy cannot be
        waiting there, so other cameras may be viewed this session)."""
        view = self.body.read_camera("4B")
        if not view["visible"]:
            return False
        self.freddy_at_4b = "F" in view["occupants"]
        return not view["occupants"]

    def _look_at_cove(self) -> int | None:
        """View Pirate Cove (caller guarantees it is safe) and update Foxy.
        Returns the stage seen, or None if the picture was unreadable."""
        self.say("Checking Foxy (Pirate Cove)")
        self.body.select_camera("1C")
        self.camera_selected = "1C"
        view = self.body.read_camera("1C")
        if view["visible"] and view["foxy_stage"] == 3:
            # "Foxy has gone" triggers the emergency procedure, so make sure:
            # look again (the TV static is different in every frame).
            second = self.body.read_camera("1C")
            if not (second["visible"] and second["foxy_stage"] == 3):
                view = second
        self.body.select_camera("4B")
        self.camera_selected = "4B"
        if not view["visible"] or view["foxy_stage"] is None:
            return None
        self.foxy_stage = self.foxy_max_stage = view["foxy_stage"]
        self.foxy_verified_at = self.body.now()
        return self.foxy_stage

    # -- Foxy ----------------------------------------------------------------

    def _freeze_foxy(self) -> None:
        """Short camera flip just before Foxy's tick, so his lock is running."""
        now = self.body.now()
        tick = rules.next_tick(rules.FOXY_TICK, max(now, self.foxy_frozen_tick + 0.01))
        self.foxy_frozen_tick = tick
        cove_check = self._cove_check_due()
        self.say("Camera flip: checking Foxy" if cove_check else "Camera flip to hold Foxy (resting on 4B)")
        if not self._raise_camera():
            return
        stage = None
        if cove_check and self._read_4b():
            stage = self._look_at_cove()
        else:
            # A plain flip only has to be up while one of the game's 0.1 s
            # re-lock instants passes; every extra moment risks a power
            # charge. But the re-lock must also be close enough to the tick
            # (the lock lasts at least 0.833 s), so if the camera went up
            # early - for a cove check that 4B then forbade - stay up until
            # a re-lock instant that still protects the tick.
            first_relock = math.floor((self._view_started + CLOCK_MARGIN) * 10 + 1) / 10
            min_lock = rules.FOXY_LOCK_MIN_FRAMES * rules.FRAME
            covering_relock = math.ceil((tick - (min_lock - CLOCK_MARGIN)) * 10 - 1e-9) / 10
            self.body.wait_until(max(self.body.now(), first_relock, covering_relock) + CLOCK_MARGIN)
        self._lower_camera()
        if stage is not None:
            self._after_cove_check(stage)

    def _cove_check_due(self) -> bool:
        """Look at Pirate Cove on this flip? Only when it is worth the time:
        Foxy may have moved since we last saw him (an uncovered tick), or it
        has been a while. A Foxy who was SEEN at stage 2 and whose every tick
        since was covered is still at stage 2 - no need to keep looking."""
        return (self.foxy_max_stage > self.foxy_stage
                or self.body.now() - self.foxy_verified_at > FOXY_VERIFY_EVERY)

    def _foxy_alert(self) -> None:
        """Foxy may have left the cove (some of his ticks were not covered).

        Shut the left door first (he can only come through it), then look at
        the cove. If 4B is not clear, the right door is shut too before
        looking, because Freddy can only get in through an OPEN right door
        while a camera other than 4B is showing."""
        self.say("Foxy might be out - left door shut until checked", alert=True)
        self._close_planned_doors_now()
        self.foxy_door_hold = True
        self._shut(self.left, "Foxy might be out")
        shut_right = False
        if not self._raise_camera():
            return
        if not self._read_4b():
            self._lower_camera()
            shut_right = not self.right.door_closed
            self._shut(self.right, "safe to look at Pirate Cove")
            # The right door must be FULLY shut before another camera shows.
            self.body.wait_until(max(self.body.now(), self.right.moving_until))
            if not self._raise_camera():
                return
        stage = self._look_at_cove()
        self._lower_camera()
        if shut_right:
            self._release(self.right)
        if stage is None:
            # Unreadable: keep the left door shut and try again in a moment
            # (not immediately, so the doorway checks still get their turn).
            self.foxy_max_stage = 3
            self.foxy_alert_retry_at = self.body.now() + 2.0
            return
        self._after_cove_check(stage)

    def _after_cove_check(self, stage: int) -> None:
        if stage >= 3:
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
        if self._raise_camera():
            self.body.select_camera("2A")
            self.camera_selected = "2A"
            self.body.wait_until(self.body.now() + 0.15)
            self._lower_camera()
        # He bangs on the closed door 100 frames after starting to run.
        self.body.wait_until(self.body.now() + rules.FOXY_RUN_FRAMES * rules.FRAME + 0.6)
        self.foxy_emergency = False
        self.foxy_door_hold = False
        self.foxy_stage, self.foxy_max_stage = 0, 1      # he restarts at stage 0 or 1
        self.foxy_verified_at = -1e9
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
        self._press_door(watch)
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
            self._press_door(watch)
            return
        if not watch.at_door:
            watch.at_door = True
            watch.seen_for_sure = False
            watch.checked_since_tick = True       # wait for their next tick
            watch.seen_at_door_at = self.body.now()
