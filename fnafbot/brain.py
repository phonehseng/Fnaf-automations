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

# A doorway check (light on -> look -> light off) keeps the light on this long.
LIGHT_CHECK_SECONDS = 0.24

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

# Camera session for Foxy: the camera picture must show for this long
# (long enough to contain one of the game's 0.1 s re-lock instants and to
# read E. Hall Corner).
FREEZE_VIEW_SECONDS = 0.22
# The camera must go down no earlier than this before Foxy's tick: the lock
# set at the last re-lock lasts at least 50 frames (0.833 s).
FREEZE_LATEST_GAP = 0.833 - 0.1 - CLOCK_MARGIN

# Re-check Pirate Cove (only when it is safe) at least this often.
FOXY_VERIFY_EVERY = 30.0


class Body(Protocol):
    """What the brain needs from the game (real or simulated)."""

    def now(self) -> float: ...
    def wait_until(self, t: float) -> None: ...
    def night_over(self) -> bool: ...
    def face(self, side: str) -> None: ...
    def press(self, kind: str, side: str) -> None: ...
    def look_doorway(self, side: str) -> tuple[bool, bool]: ...
    def light_is_on(self, side: str) -> bool: ...
    def camera_up(self) -> None: ...
    def camera_down(self) -> None: ...
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
        self.foxy_stage = 0
        self.foxy_verified_at = -1e9
        self.foxy_frozen_tick = 0.0        # last Foxy tick we have planned a freeze for
        self.foxy_emergency = False        # Foxy left the cove: left door must stay shut

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
            "Foxy": "LEFT COVE" if self.foxy_emergency else f"stage {self.foxy_stage}",
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

    def _door_check_needed(self, watch: DoorWatch) -> bool:
        """A light check is needed if they could have arrived at the last tick."""
        return (not watch.at_door and not watch.checked_since_tick and watch.min_moves == 0
                and not watch.door_closed)

    def _peek_needed(self, watch: DoorWatch, now: float) -> bool:
        """They were at the closed door and one of their ticks has passed."""
        return (watch.at_door and watch.door_closed and not watch.checked_since_tick
                and now >= watch.closed_at + rules.DOOR_CLOSE_SECONDS + CLOCK_MARGIN)

    # ------------------------------------------------------------------
    # Choosing what to do next
    # ------------------------------------------------------------------

    def _choose_job(self, now: float):
        """Return the most urgent action to do right now, or None to wait."""
        # 1) Doorway work, most urgent deadline first.
        door_jobs = []
        for watch in (self.left, self.right):
            next_tick = rules.next_tick(watch.tick, now)
            if self._door_check_needed(watch):
                door_jobs.append((next_tick - CHECK_DEADLINE_LEAD, lambda w=watch: self._check_doorway(w)))
            elif self._peek_needed(watch, now):
                door_jobs.append((next_tick - 1.4, lambda w=watch: self._peek(w)))
        door_jobs.sort(key=lambda job: job[0])

        # 2) The Foxy freeze session (a precise-time job).
        freeze_start = self._next_freeze_start(now)

        if door_jobs:
            deadline, job = door_jobs[0]
            if freeze_start is None:
                return job
            # Do the door work now unless it would make us miss the freeze and
            # can safely wait until after the freeze session.
            door_job_end = now + PAN_SECONDS + LIGHT_CHECK_SECONDS + 0.3
            freeze_end = freeze_start + rules.CAMERA_UP_SECONDS + FREEZE_VIEW_SECONDS + rules.CAMERA_DOWN_SECONDS
            if door_job_end <= freeze_start or freeze_end + PAN_SECONDS + 0.3 > deadline:
                return job
        if freeze_start is not None and now >= freeze_start - 0.005:
            return self._freeze_foxy
        return None

    def _idle(self, now: float) -> None:
        """Nothing urgent: get into position for the next job, then wait."""
        wake = now + 0.25
        freeze_start = self._next_freeze_start(now)
        if freeze_start is not None:
            wake = min(wake, freeze_start)
        # Face the side whose check comes next, so the check itself is quick.
        upcoming = min((self.left, self.right), key=lambda w: rules.next_tick(w.tick, now))
        if (upcoming.min_moves <= 1 or upcoming.at_door) and (freeze_start is None or freeze_start - now > PAN_SECONDS + 0.1):
            self.body.face(upcoming.side)
        self.body.wait_until(max(self.body.now(), min(wake, self.body.now() + 0.25)))

    # ------------------------------------------------------------------
    # Doorways
    # ------------------------------------------------------------------

    def _check_doorway(self, watch: DoorWatch) -> None:
        """Flash the light; close the door at once if Bonnie/Chica is there."""
        name = watch.who.capitalize()
        self.say(f"Looking for {name} ({watch.side} light)")
        self.body.face(watch.side)
        now = self.body.now()
        deadline = rules.next_tick(watch.tick, now) - CHECK_DEADLINE_LEAD
        self.body.wait_until(self.quiet_light_start(now, deadline))
        present, lit = self._flash_light(watch)
        if not lit:
            # The light did not come on (a click lost to timing). Try again,
            # but never loop forever: after a few failures shut the door,
            # which is always safe.
            watch.failed_checks += 1
            self.say(f"{name}: light did not come on - retrying", alert=True)
            if watch.failed_checks >= 3 and not watch.door_closed:
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
        """Light on, look, (close door if needed), light off. Returns (present, lit)."""
        light_on_at = self.body.now()
        self.body.press("light", watch.side)
        present, lit = self.body.look_doorway(watch.side)
        if present and not watch.door_closed:
            self._close_door(watch, reason="seen in doorway", after=light_on_at)
        # Switch the light off once the click cooldown allows it.
        self.body.wait_until(max(self.body.now(), light_on_at + BUTTON_COOLDOWN))
        if self.body.light_is_on(watch.side):
            self.body.press("light", watch.side)
        return present, lit

    def _close_door(self, watch: DoorWatch, reason: str, after: float) -> None:
        self.body.wait_until(max(self.body.now(), after + BUTTON_COOLDOWN))
        self.body.press("door", watch.side)
        watch.door_closed = True
        watch.closed_at = self.body.now()
        self.say(f"{watch.who.upper()} AT {watch.side.upper()} DOOR - door closed ({reason})", alert=True)

    def _peek(self, watch: DoorWatch) -> None:
        """After their tick: reopen, look, close again if they are still there."""
        name = watch.who.capitalize()
        self.say(f"Checking whether {name} left (peek)")
        self.body.face(watch.side)
        opened_at = self.body.now()
        self.body.press("door", watch.side)
        watch.door_closed = False
        door_open = opened_at + rules.DOOR_OPEN_SECONDS + CLOCK_MARGIN
        deadline = rules.next_tick(watch.tick, door_open) - CHECK_DEADLINE_LEAD
        self.body.wait_until(self.quiet_light_start(door_open, deadline))
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
        for gap in (0.25, 0.4, 0.15, 0.55, 0.05, -0.15):
            view_end = tick - gap
            view_start = view_end - FREEZE_VIEW_SECONDS
            if self.power_safe(view_start, FREEZE_VIEW_SECONDS) and gap <= FREEZE_LATEST_GAP:
                return view_start - rules.CAMERA_UP_SECONDS
        return tick - 0.25 - FREEZE_VIEW_SECONDS - rules.CAMERA_UP_SECONDS

    def _freeze_foxy(self) -> None:
        now = self.body.now()
        tick = rules.next_tick(rules.FOXY_TICK, max(now, self.foxy_frozen_tick + 0.01))
        self.foxy_frozen_tick = tick
        self.say("Camera flip to hold Foxy (resting on 4B)")
        self.body.camera_up()
        view_start = self.body.now()
        if self.camera_selected != "4B":
            # Only happens on the very first flip of the night (the game starts
            # on Show Stage). Freddy is still on stage then, so it is safe.
            self.body.select_camera("4B")
            self.camera_selected = "4B"
        view = self.body.read_camera("4B")
        if view["visible"]:
            self.freddy_at_4b = "F" in view["occupants"]
            clear = not view["occupants"]
        else:
            clear = False
        if clear and self.body.now() - self.foxy_verified_at > FOXY_VERIFY_EVERY:
            self._verify_foxy()
        # Keep the picture up for the planned time, then lower it.
        self.body.wait_until(max(self.body.now(), view_start + FREEZE_VIEW_SECONDS))
        self.body.camera_down()

    def _verify_foxy(self) -> None:
        """Look at Pirate Cove (only called when 4B is confirmed empty)."""
        self.say("Checking Foxy (Pirate Cove)")
        self.body.select_camera("1C")
        view = self.body.read_camera("1C")
        self.body.select_camera("4B")   # always leave the camera resting on 4B
        self.camera_selected = "4B"
        if view["visible"] and view["foxy_stage"] is not None:
            self.foxy_stage = view["foxy_stage"]
            self.foxy_verified_at = self.body.now()
            if self.foxy_stage >= 3:
                self._foxy_emergency()

    def _foxy_emergency(self) -> None:
        """Foxy has left the cove: shut the left door and make him run now.

        Viewing West Hall (2A) makes him run at once, so the left door only
        has to stay shut for ~2 s instead of up to 25 s. 2A is not 4B, so
        Freddy must be made safe first: the right door is shut too (with it
        shut, viewing 2A sends a waiting Freddy back to East Hall).
        """
        self.foxy_emergency = True
        self.say("FOXY LEFT THE COVE - closing doors", alert=True)
        self.body.camera_down()
        shut_right = not self.right.door_closed
        for watch in (self.left, self.right) if shut_right else (self.left,):
            if not watch.door_closed:
                self.body.face(watch.side)
                self.body.wait_until(self.body.now() + BUTTON_COOLDOWN)
                self.body.press("door", watch.side)
                watch.door_closed = True
                watch.closed_at = self.body.now()
        self.body.wait_until(self.body.now() + rules.DOOR_CLOSE_SECONDS + CLOCK_MARGIN)
        self.say("Making Foxy run now (viewing West Hall)", alert=True)
        self.body.camera_up()
        self.body.select_camera("2A")
        self.body.wait_until(self.body.now() + 0.15)
        self.body.select_camera("4B")
        self.camera_selected = "4B"
        self.body.camera_down()
        # He arrives 100 frames after the run starts and bangs on the door.
        self.body.wait_until(self.body.now() + rules.FOXY_RUN_FRAMES * rules.FRAME + 0.6)
        self.foxy_emergency = False
        self.foxy_stage = 0
        self.foxy_verified_at = -1e9    # look at Pirate Cove again at the next safe moment
        # Reopen the doors that were shut only because of Foxy, and look
        # through them again before the next tick (someone may have arrived).
        for watch in (self.right, self.left):
            reopen = watch is self.left or shut_right
            if reopen and watch.door_closed and not watch.at_door:
                self.body.face(watch.side)
                self.body.wait_until(self.body.now() + BUTTON_COOLDOWN)
                self.body.press("door", watch.side)
                watch.door_closed = False
                watch.checked_since_tick = False
                watch.min_moves = 0
        self.say("Foxy hit the door - back to normal")
