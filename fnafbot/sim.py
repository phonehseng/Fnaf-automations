"""A frame-accurate simulation of one FNAF 1 night, for testing the brain.

Why a simulator?
    A real night takes 9 minutes. To trust that the bot never gets caught we
    need to play thousands of nights. The simulator re-implements the game's
    own event logic (docs/GAME_LOGIC.md, numbers in rules.py) frame by frame
    at 60 fps, so a night runs in well under a second.

Two classes:
    * NightSim  - the game itself (animatronics, doors, power, cameras ...).
    * SimBody   - lets the brain play the simulated game through exactly the
                  same methods it uses on the real game (see body.py), with
                  realistic delays (panning, camera flip, reaction time).

Simplifications (all on the safe side for testing):
    * An animatronic entering the office counts as an immediate loss (in the
      real game Bonnie/Chica only attack once the camera is lowered).
    * Running out of power counts as a loss.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from fnafbot import rules
from fnafbot.rules import FRAME, FPS

LEFT, RIGHT = "left", "right"

# Door states (mirroring the game's door AltA values 0/1/2/4).
OPEN, CLOSING, CLOSED, OPENING = "open", "closing", "closed", "opening"

DOOR_CLOSE_FRAMES = round(rules.DOOR_CLOSE_SECONDS * FPS)
DOOR_OPEN_FRAMES = round(rules.DOOR_OPEN_SECONDS * FPS)
CAMERA_UP_FRAMES = round(rules.CAMERA_UP_SECONDS * FPS)
CAMERA_DOWN_FRAMES = round(rules.CAMERA_DOWN_SECONDS * FPS)
CAMERA_DISRUPTION_FRAMES = 300


@dataclass
class _Timer:
    """An "every X seconds" timer, counted from the start of the night."""

    interval: float
    next_time: float = 0.0

    def __post_init__(self) -> None:
        self.next_time = self.interval

    def fires(self, now: float) -> bool:
        if now + 1e-9 >= self.next_time:
            self.next_time += self.interval
            return True
        return False


@dataclass
class NightResult:
    survived: bool
    power: int            # tenths of a percent left at the end
    cause: str = ""       # why the night was lost
    seconds: float = 0.0
    log: list[str] = field(default_factory=list)


class NightSim:
    """The game's night logic. Call step() once per frame."""

    def __init__(self, night: int, custom: dict[str, int] | None = None, seed: int | None = None) -> None:
        self.seed = seed                  # also seeds the simulated body's clock error
        self.rng = random.Random(seed)
        self.night = night
        self.custom = custom
        self.frame = 0
        self.power = rules.START_POWER
        self.over = False
        self.result: NightResult | None = None
        self.events: list[str] = []
        self.spent: dict[str, int] = {}   # power units charged per thing switched on

        # Inputs queued by SimBody for the next frame.
        self.pending_clicks: list[tuple[str, str]] = []   # ("door"/"light", side)
        self.pending_camera_hover = False
        self.pending_camera_select: str | None = None

        # Office.
        self.door = {LEFT: OPEN, RIGHT: OPEN}
        self.door_frames = {LEFT: 0, RIGHT: 0}
        self.light = {LEFT: False, RIGHT: False}
        self.cooldown = 0

        # Camera monitor.
        self.camera_state = "down"        # down / raising / up / lowering
        self.camera_frames = 0
        self.last_clicked = "1A"          # the game starts on the Show Stage camera
        self.viewing: str | None = None   # camera currently showing, None if down
        self.disrupted_frames = 0

        # Animatronics.
        self.bonnie = "1A"
        self.chica = "1A"
        self.coin = {"bonnie": 1, "chica": 1}
        self.move_who: str | None = None
        self.freddy = "1A"
        self.freddy_armed = 0             # game's AltM: 0 idle, 1 counting, 2 ready
        self.freddy_count = 0             # game's AltN
        self.foxy_stage = 0
        self.foxy_lock = 0
        self.foxy_stage3_frames = 0
        self.foxy_run_frames = 0
        self.foxy_bangs = 0

        self.timers = {
            "power": _Timer(rules.POWER_TICK),
            "coin": _Timer(1.0),
            "bonnie": _Timer(rules.BONNIE_TICK),
            "chica": _Timer(rules.CHICA_TICK),
            "freddy": _Timer(rules.FREDDY_TICK),
            "foxy": _Timer(rules.FOXY_TICK),
            "relock": _Timer(rules.FOXY_RELOCK_INTERVAL),
            "freddy_attack": _Timer(1.0),
        }
        drain = rules.PASSIVE_DRAIN_PERIOD.get(night)
        if drain:
            self.timers["passive"] = _Timer(float(drain))

    # ------------------------------------------------------------------ helpers

    @property
    def now(self) -> float:
        return self.frame * FRAME

    def ai(self) -> dict[str, int]:
        return rules.ai_levels(self.night, rules.hour_at(self.now), self.custom)

    def roll(self, name: str) -> bool:
        return self.rng.randint(1, 20) <= self.ai()[name]

    def usage(self) -> int:
        doors = sum(1 for side in (LEFT, RIGHT) if self.door[side] in (CLOSED, OPENING))
        lights = sum(1 for side in (LEFT, RIGHT) if self.light[side])
        return 1 + doors + lights + (1 if self.viewing else 0)

    def lose(self, cause: str) -> None:
        if not self.over:
            self.over = True
            self.result = NightResult(False, max(self.power, 0), cause, self.now, self.events)

    def log(self, text: str) -> None:
        self.events.append(f"{self.now:7.2f}s {text}")

    # ------------------------------------------------------------------ one frame

    def step(self) -> None:
        if self.over:
            return
        self.frame += 1
        now = self.now
        fired = {name: timer.fires(now) for name, timer in self.timers.items()}

        self._handle_clicks()
        self._animate_doors()
        self._animate_camera()

        if fired["power"]:
            self.power -= self.usage()
            # Book-keeping for analysis: what was switched on at this charge.
            for side in (LEFT, RIGHT):
                if self.door[side] in (CLOSED, OPENING):
                    self.spent[f"door {side}"] = self.spent.get(f"door {side}", 0) + 1
                if self.light[side]:
                    self.spent[f"light {side}"] = self.spent.get(f"light {side}", 0) + 1
            if self.viewing:
                self.spent["camera"] = self.spent.get("camera", 0) + 1
        if fired.get("passive"):
            self.power -= 1
        if self.power <= 0:
            self.lose("power ran out")
            return

        if fired["coin"]:
            self.coin = {"bonnie": self.rng.randint(1, 2), "chica": self.rng.randint(1, 2)}

        # Movement rolls (Chica's roll overwrites Bonnie's if both happen now).
        if fired["bonnie"] and self.roll("bonnie"):
            self.move_who = "bonnie"
            self._maybe_disrupt(self.bonnie)
        if fired["chica"] and self.roll("chica"):
            self.move_who = "chica"
            self._maybe_disrupt(self.chica)
        if fired["freddy"] and self.viewing is None and self.roll("freddy"):
            if self.freddy_armed == 0:
                self.freddy_armed = 1
        if (fired["foxy"] and self.viewing != "1C" and self.foxy_stage < 3
                and self.foxy_lock == 0 and self.roll("foxy")):
            self.foxy_stage += 1
            self.log(f"Foxy -> stage {self.foxy_stage}")

        self._resolve_moves()
        self._update_freddy(fired["freddy_attack"])
        self._update_foxy(fired["relock"])
        if self.disrupted_frames > 0:
            self.disrupted_frames -= 1

        if now >= rules.NIGHT_SECONDS and not self.over:
            self.over = True
            self.result = NightResult(True, self.power, "", now, self.events)

    # ------------------------------------------------------------------ office

    def _handle_clicks(self) -> None:
        if self.cooldown > 0:
            self.cooldown -= 1
        for kind, side in self.pending_clicks:
            if self.cooldown > 0 or self.viewing is not None:
                why = "cooldown" if self.cooldown > 0 else "camera up"
                self.log(f"click {kind} {side} IGNORED ({why})")
                continue  # ignored, exactly like the game
            if kind == "door":
                if self.door[side] == OPEN:
                    self.door[side], self.door_frames[side] = CLOSING, DOOR_CLOSE_FRAMES
                elif self.door[side] == CLOSED:
                    self.door[side], self.door_frames[side] = OPENING, DOOR_OPEN_FRAMES
                else:
                    self.log(f"click door {side} IGNORED (door still moving)")
                    continue  # mid-animation: the game ignores the click
                self.log(f"door {side} {self.door[side]}")
                self.cooldown = rules.CLICK_COOLDOWN_FRAMES
            else:
                turning_on = not self.light[side]
                self.light = {LEFT: False, RIGHT: False}
                self.light[side] = turning_on
                self.log(f"light {side} {'on' if turning_on else 'off'}")
                self.cooldown = rules.CLICK_COOLDOWN_FRAMES
        self.pending_clicks.clear()

    def _animate_doors(self) -> None:
        for side in (LEFT, RIGHT):
            if self.door[side] in (CLOSING, OPENING):
                self.door_frames[side] -= 1
                if self.door_frames[side] <= 0:
                    self.door[side] = CLOSED if self.door[side] == CLOSING else OPEN

    # ------------------------------------------------------------------ camera

    def _animate_camera(self) -> None:
        if self.pending_camera_select and self.viewing:
            self.last_clicked = self.pending_camera_select
            self.viewing = self.last_clicked
        self.pending_camera_select = None

        if self.pending_camera_hover:
            self.pending_camera_hover = False
            if self.camera_state == "down":
                self.camera_state, self.camera_frames = "raising", CAMERA_UP_FRAMES
            elif self.camera_state == "up":
                self._put_down()
        if self.camera_state == "raising":
            self.camera_frames -= 1
            if self.camera_frames <= 0:
                self.camera_state = "up"
                self.viewing = self.last_clicked
                self.light = {LEFT: False, RIGHT: False}   # lights go off on camera
        elif self.camera_state == "lowering":
            self.camera_frames -= 1
            if self.camera_frames <= 0:
                self.camera_state = "down"

    def _put_down(self) -> None:
        self.viewing = None
        self.camera_state, self.camera_frames = "lowering", CAMERA_DOWN_FRAMES

    def _maybe_disrupt(self, room: str) -> None:
        """Moving inside the watched camera blanks it for 5 s."""
        if self.viewing and self.viewing == room:
            self.disrupted_frames = CAMERA_DISRUPTION_FRAMES

    # ------------------------------------------------------------------ Bonnie / Chica

    def _resolve_moves(self) -> None:
        who = self.move_who
        if who is None:
            return
        side = LEFT if who == "bonnie" else RIGHT
        route = rules.BONNIE_ROUTE if who == "bonnie" else rules.CHICA_ROUTE
        room = self.bonnie if who == "bonnie" else self.chica
        if room == "DOOR":
            if self.door[side] == OPEN:
                new_room = "OFFICE"
            elif self.door[side] == CLOSED:
                new_room = rules.BONNIE_REPELLED_TO if who == "bonnie" else rules.CHICA_REPELLED_TO
            else:
                return  # door mid-animation: the move waits
        else:
            new_room = route[room][self.coin[who] - 1]
        self.move_who = None
        if who == "bonnie":
            self.bonnie = new_room
        else:
            self.chica = new_room
        self.log(f"{who} {room} -> {new_room}")
        if new_room == "OFFICE":
            self.lose(f"{who} got into the office")
            return
        if (room == "DOOR" or new_room == "DOOR") and self.viewing is None:
            self.light = {LEFT: False, RIGHT: False}   # the game switches lights off
        if self.viewing and self.viewing == new_room:
            self.disrupted_frames = CAMERA_DISRUPTION_FRAMES

    # ------------------------------------------------------------------ Freddy

    def _update_freddy(self, attack_tick: bool) -> None:
        if self.freddy == "OFFICE":
            if attack_tick and self.viewing is None and self.rng.randint(0, 3) == 1:
                self.lose("Freddy attacked")
            return
        ai = self.ai()["freddy"]
        if self.freddy_armed == 1:
            self.freddy_count += 1
            if self.viewing and self.viewing == self.freddy:
                self.freddy_count = 0  # watching his room resets the countdown
            if self.freddy_count >= rules.freddy_countdown_frames(ai) and self.viewing is None:
                self.freddy_armed, self.freddy_count = 2, 0
        if self.freddy_armed != 2:
            return
        room = self.freddy
        target = None
        if room == "1A":
            if self.bonnie != "1A" and self.chica != "1A":
                target = "1B"
        elif room in ("1B", "7", "6"):
            target = {"1B": "7", "7": "6", "6": "4A"}[room]
        elif room == "4A":
            if not self.light[RIGHT]:
                target = "4B"
        elif room == "4B" and self.viewing and self.viewing != "4B":
            if self.door[RIGHT] == OPEN:
                target = "OFFICE"
            elif self.door[RIGHT] == CLOSED and self.viewing != "4A":
                target = "4A"
        if target:
            self.freddy, self.freddy_armed = target, 0
            self.log(f"Freddy {room} -> {target}")
            if target == "OFFICE":
                self.log("Freddy is IN THE OFFICE")

    # ------------------------------------------------------------------ Foxy

    def _update_foxy(self, relock_tick: bool) -> None:
        if self.foxy_lock > 0:
            self.foxy_lock -= 1
        if relock_tick and self.viewing:
            self.foxy_lock = rules.FOXY_LOCK_MIN_FRAMES + self.rng.randint(0, rules.FOXY_LOCK_RANDOM_FRAMES - 1)
        if self.foxy_stage == 3:
            if self.viewing == "2A":
                self.foxy_stage, self.foxy_run_frames = 4, 0
                self.log("Foxy starts running (2A viewed)")
            else:
                self.foxy_stage3_frames += 1
                if self.foxy_stage3_frames > rules.FOXY_STAGE3_FRAMES:
                    self.foxy_stage = 5
        elif self.foxy_stage == 4:
            self.foxy_run_frames += 1
            if self.foxy_run_frames > rules.FOXY_RUN_FRAMES:
                self.foxy_stage = 5
        if self.foxy_stage == 5:
            if self.viewing:
                self._put_down()      # the game forces the camera down
            elif self.door[LEFT] == OPEN:
                self.lose("Foxy got in")
            elif self.door[LEFT] == CLOSED:
                cost = rules.FOXY_BANG_COST[min(self.foxy_bangs, len(rules.FOXY_BANG_COST) - 1)]
                self.power -= cost
                self.foxy_bangs += 1
                self.foxy_stage = self.rng.randint(0, 1)
                self.foxy_stage3_frames = 0
                self.log(f"Foxy banged on the door (-{cost / 10:.0f}%)")


# ---------------------------------------------------------------------------
# The brain's view of the simulated game
# ---------------------------------------------------------------------------

# Realistic bot delays, measured on the real game + controller, so that the
# simulated power use matches what the real bot spends.
PAN_SECONDS = 0.55          # full pan from one side to the other
READ_SECONDS = 0.035        # grab a frame and analyse it
DOORWAY_READ_SECONDS = 0.07     # wait for a lit frame and classify it
LAMP_READ_SECONDS = 0.015       # one screenshot, one small patch (door button lamp)
# The real bot's clock is never exact: the fitted night start wobbles by a
# few hundredths of a second. The simulated body's clock wanders the same
# way, so timing that only works with a perfect clock fails here too.
CLOCK_ERROR_SECONDS = 0.07
CAMERA_SETTLE_SECONDS = 0.12  # static burst after raising/switching (body.CAMERA_SETTLE default)
COVE_SETTLE_SECONDS = 0.3     # Pirate Cove waits longer (body.CAMERA_SETTLE["1C"])
CAMERA_READ_SECONDS = 0.08    # 2-3 frames grabbed and classified
CLICK_SECONDS = 0.03        # move + click
BUTTON_COOLDOWN = 0.19      # same safety spacing as controller.BUTTON_COOLDOWN


class SimBody:
    """Plays a NightSim through the same methods as the real game body."""

    def __init__(self, sim: NightSim, clock_error: float = CLOCK_ERROR_SECONDS) -> None:
        self.sim = sim
        self.facing: str | None = None
        self._last_button_click = -1.0
        # Slow, bounded wander of the clock (two sine waves with random
        # phases): the brain only ever sees now(), never the true time.
        rng = random.Random(f"clock-{getattr(sim, 'seed', 0)}")
        self._phase = (rng.uniform(0, 2 * math.pi), rng.uniform(0, 2 * math.pi))
        self._error = clock_error
        # In the simulator every timer runs on the same frame clock.
        self.scale = 1.0
        self.tick_phases: dict[str, float] = {}

    # -- time
    def _clock_error(self) -> float:
        t = self.sim.now
        return self._error * (0.7 * math.sin(t / 41.0 + self._phase[0]) + 0.3 * math.sin(t / 7.0 + self._phase[1]))

    def now(self) -> float:
        return self.sim.now + self._clock_error()

    def advance(self, seconds: float) -> None:
        target = self.sim.frame + max(1, round(seconds * FPS))
        while self.sim.frame < target and not self.sim.over:
            self.sim.step()

    def wait_until(self, t: float) -> None:
        while self.now() + 1e-9 < t and not self.sim.over:
            self.sim.step()

    def night_over(self) -> bool:
        return self.sim.over

    # -- office
    def face(self, side: str) -> None:
        if self.sim.camera_state != "down":
            self.camera_down()
        if self.facing != side:
            self.advance(PAN_SECONDS)
            self.facing = side

    def press(self, kind: str, side: str) -> None:
        """Click a door/light button. Like the real controller, first wait out
        the game's 10-frame click cooldown so the click is never ignored.
        (The real controller times this with the computer's own clock, so it
        is exact: use the true simulated time here, not the wandering one.)"""
        while self.sim.now + 1e-9 < self._last_button_click + BUTTON_COOLDOWN and not self.sim.over:
            self.sim.step()
        self.sim.pending_clicks.append((kind, side))
        self._last_button_click = self.sim.now
        self.advance(CLICK_SECONDS)

    def look_doorway(self, side: str) -> tuple[bool, bool]:
        """(someone there, light was really on). The light flickers dark on
        ~1 frame in 10; the real bot grabs frames until it gets a lit one."""
        self.advance(DOORWAY_READ_SECONDS)
        if not self.sim.light[side]:
            return False, False
        # With the door fully closed the doorway is hidden (verified live for
        # the left side; assumed for the right side so the brain never relies
        # on seeing through a closed door).
        if self.sim.door[side] == CLOSED:
            return False, True
        who = self.sim.bonnie if side == LEFT else self.sim.chica
        return who == "DOOR", True

    def light_is_on(self, side: str) -> bool:
        self.advance(READ_SECONDS)
        return self.sim.light[side]

    def door_state(self, side: str) -> str | None:
        """The door button's lamp: 'closed' from the moment a closing click
        is accepted (the simulator never loses clicks, but the brain checks).
        Reading one small patch of one screenshot is quick."""
        self.advance(LAMP_READ_SECONDS)
        if self.facing != side:
            return None
        return "closed" if self.sim.door[side] in (CLOSING, CLOSED) else "open"

    # -- camera
    def camera_up(self) -> bool:
        if self.sim.camera_state == "up":
            return True
        if self.sim.camera_state == "lowering":
            self.wait_until(self.sim.now + self.sim.camera_frames * FRAME)
        self.sim.pending_camera_hover = True
        while self.sim.camera_state != "up" and not self.sim.over:
            self.sim.step()
        return True

    def camera_down(self) -> bool:
        if self.sim.camera_state == "up":
            self.sim.pending_camera_hover = True
            self.sim.step()
        while self.sim.camera_state == "lowering" and not self.sim.over:
            self.sim.step()
        return True

    def select_camera(self, camera: str) -> None:
        self.sim.pending_camera_select = camera
        self.sim.step()

    def read_camera(self, camera: str) -> dict:
        """What the camera shows: {'occupants': set, 'foxy_stage': int|None,
        'visible': bool}. Freddy is only reported where the real vision can
        see him (Show Stage and E. Hall Corner)."""
        self.advance((COVE_SETTLE_SECONDS if camera == "1C" else CAMERA_SETTLE_SECONDS) + CAMERA_READ_SECONDS)
        sim = self.sim
        if sim.viewing != camera or sim.disrupted_frames > 0:
            return {"occupants": set(), "foxy_stage": None, "visible": False}
        occupants = set()
        if sim.bonnie == camera:
            occupants.add("B")
        if sim.chica == camera:
            occupants.add("C")
        if sim.freddy == camera and camera in ("1A", "4B"):
            occupants.add("F")
        if camera == "4B" and "C" in occupants:
            occupants.discard("F")   # Chica's picture hides Freddy behind her
        stage = sim.foxy_stage if camera == "1C" else None
        return {"occupants": occupants, "foxy_stage": stage, "visible": True}

    def power(self) -> int:
        return max(self.sim.power, 0) // 10
