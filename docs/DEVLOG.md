# Development log - bugs found and how they were fixed

A running diary of the interesting problems met while making the bot play
unsupervised. Newest entries at the bottom. Times are the laptop's local
time; "night time" is seconds since the night's first frame.

---

## 2026-10-22 - "Night 3: SURVIVED with 20% power" was a lie

**Where it showed up.** The campaign run (`logs/2026-10-22_01-54-46.log`)
reported Night 3 as survived, then crashed in the menu because the game
said *6th Night* was not unlocked. The game was right: the save still said
"Continue - Night 3". Night 3 had been lost.

**Why the bot thought it had won.** `Session._play_night` decided
"survived" with `body.now() >= 535 - 2`. The HUD vanished at night time
538.6 s, which is past 535 s, so the bot called it a win. It never looked
at *what* replaced the HUD (the 6 AM screen or a jumpscare).

**Who got in.** The log's last seconds (02:22:59 - 02:23:01):

```
532.94s  Checking whether Bonnie left (peek)
         doorway left: no lit frame (light did not come on?)
534.18s  BONNIE AT LEFT DOOR - door closed (could not see)
535.06s  Camera flip to hold Foxy ...
         Monitor did not come up (attempt 1..3)
```

The left light "not coming on" is the game's own tell: event 267 of the
night frame says *bonnie overlapping "got you left" -> light on left = 0*.
Bonnie was already inside the office. The door button and monitor then
stopped responding because the jumpscare sequence had started. Evidence
picture: `logs/doorway/0538.66s_night_over.jpg` (TV static, no 6 AM text).

**The real cause: the game's clock runs slow.** Comparing "Night started"
with the moment the HUD disappeared in every logged night:

| night | HUD gone at (night time) | result |
|-------|--------------------------|--------|
| N1 (01:43 run) | 538.78 s | survived |
| N1 | 538.30 s | survived |
| N2 | 538.46 s | survived |
| N3 | 533.10 s | **lost** (jumpscare) |

The game reaches 6 AM after 535 of its "every 1 second" ticks, but the
6 AM screen arrived about 538.5 s after the first frame. So one game
second is about **1.0065 real seconds** (0.65 % slow). Every animatronic
timer (Bonnie 4.97 s, Chica 4.98 s, Freddy 3.02 s, Foxy 5.01 s) is the
same "Every N seconds" Clickteam condition, so they all drift the same way.

The bot's clock only ever corrected itself *earlier* (`RealBody._calibrate`
tightens an upper bound on the night start), so after nine minutes its idea
of "Bonnie's next tick" was ~3.4 s *ahead* of the real tick. The
just-in-time door logic closed the door for a tick that had not happened
yet, reopened it, and the real tick came while the door was open.

**Why the simulator never caught it.** `fnafbot/sim.py` steps the game at
exactly 60 frames per second with the nominal periods. A perfect model of
the decompiled rules - but the real game is not perfect: Clickteam's timer
appears to lose the fraction of a frame left over each time it re-arms
(1 s -> 61 frames at 60 fps = 1.0167 s would be too slow; the measured
1.0065 s suggests the frame rate itself is a bit above 60 and the timer
rounds up, see `tools/measure_fps.py` and `tools/measure_timer.py`).
Screen capture is capped at the 60 Hz display refresh, so the exact
mechanism could not be resolved from pixels; the night length is the
reliable measurement.

**Fix.**
1. `rules.TICK_SECONDS` - the measured length of one game second; all tick
   times are scaled by it. `RealBody` refines the scale during the night
   from the power readout, which changes exactly once per game second.
2. Survival is now judged by what is on screen after the HUD disappears
   (the 6 AM screen is near-black with the "6 AM" text; a loss shows the
   jumpscare followed by static), not by elapsed time.
3. The campaign re-checks the title menu before assuming a night was won.

Tools written for this investigation: `tools/tick_model_check.py` (tests
timer models against logged doorway sightings), `tools/measure_fps.py`,
`tools/measure_timer.py`.

**Checked live.** The replayed Night 3 (`logs/2026-10-22_02-54-24.log`)
fitted the clock from the power readout within the first minute:
"game second = 1.0056 real s, night start moved +0.275 s", then
1.0053 s. So the drift is real, it varies a little per session, and the
fit catches it early.

---

## 2026-10-22 - Replayed Night 3: Chica got in at 453 s (two deadlines 0.9 s apart)

Same night, new clock, lost again - differently. The last seconds:

```
449.17s  BONNIE AT LEFT DOOR - closing at 451.77s, before their move at 452.27s
449.90s  Camera flip to hold Foxy (resting on 4B)
451.87s  BONNIE AT LEFT DOOR - door closed (just in time)
451.92s  Looking for Chica (right light)        <- Chica's tick is at 453.18 s
453.17s  Chica: light did not come on - retrying
453.57s  Chica: light did not come on - retrying
454.70s  CHICA AT RIGHT DOOR - door closed (cannot see the doorway)
         Night over (jumpscare)
```

Chica's last check (empty) was at 446.9 s; her tick at 448.2 s could have
brought her to the window, so a right-light check was due before her next
tick at 453.2 s. Bonnie's just-in-time door click was planned for 451.8 s.
The scheduler saw that the Chica check would collide with that click and
*deferred* it ("it can wait until after the planned door click") - the rule
only required the deadline to be more than 1 s after the click's start.
But after the click the bot still had to pan right (0.55 s), wait out the
click cooldown (0.19 s) and run the light check (0.3 s): it reached the
light at ~452.5 s and nothing happened. Then it retried twice *after*
Chica's tick instead of shutting the door.

Two fixes in `Brain`:
1. A deferred check must fit **between the planned click and its own
   deadline** (`close_at + cooldown + pan + light check`); otherwise the
   planned door is shut early ("schedule conflict") and the check runs
   first.
2. A light that does not come on within ~1.3 s of their tick shuts the door
   immediately (`LIGHT_FAIL_SHUT_LEAD`) instead of retrying.

Also seen: "light did not come on" happened 9 times in the campaign without
anyone inside. Those clicks are lost somewhere between the mouse and the
game; the retry handles it, but it is worth measuring (TODO).

---

## 2026-10-22 - Replay 2: the door click that never happened (lost at 141 s)

Third replay of Night 3, 03:07. Chica was seen at the window at 136.3 s;
the door click went out at 139.1 s, 0.34 s before her tick at 139.44 s -
which has worked dozens of times (a door that is still closing makes her
wait). This time she walked in. The peek 1.5 s later found the light dead
(the tell again) and the jumpscare followed.

Nothing in the log explains it, which is the explanation: the game never
saw the click. The mouse button was held for 20 ms, and
`tools/measure_fps.py` had measured frame gaps of up to 35 ms - a press
that starts just after one frame polls the mouse and ends before the next
one is invisible to the game. That also explains the nine "light did not
come on" retries in the campaign log: same lost clicks, on the light
button, where a retry is harmless.

**Fix.**
1. `mouse.py`: hold the button for 50 ms (three frames).
2. `Brain._confirm_door_click`: after every door click, read the door
   button's lamp (it changes colour the instant the game accepts a click);
   if it did not change, click again after the cooldown. Both bodies (real
   and simulated) expose `door_state(side)`.
3. `JIT_MIN_LEAD` 0.30 -> 0.45 s so that the second click still lands
   before their tick.

The simulator never loses clicks, so this could only have been found on
the real game - one more reason to keep replaying nights on camera.

---

## 2026-10-22 - Replay 4: WON (6 AM at 533 s) - and then the bot would not stop

Fourth replay, 03:16 - 03:25. All three fixes held: the clock fitted
itself to 1.0056 - 1.0070 s per game second as the night went on, Bonnie
and Chica were shut out every time, and "6 AM screen seen at 533.26 s -
night won" is in the log. Power left: 34 %.

Then the log kept going. After 6 AM the game shows the next-day screen and
the title; the HUD is gone. `RealBody._ensure_game` took the missing HUD
for the "quarter-state" picture glitch, minimised and restored the game
to repair it, reset the night-over counter every time, and the brain
carried on playing an office that was not there - its door clicks landed
on the title screen and pressed *Continue*. Night 4 started with nobody
at the desk (stopped by hand at 81 % power; losing does not touch the
save, which correctly says Night 4).

**Fix.** Seeing the 6 AM screen ends the night at once; and the picture
repair only runs while the HUD was on screen a moment ago. Between
screens a missing HUD is normal.

**Also learned:** the hall light does not come on for a moment right
after Bonnie's tick (two "light did not come on" retries in this night,
both 0.5 s after one of his ticks, both followed by a normal reading).
The retry costs half a second; the door shuts if his next tick is close.

---

## 2026-10-22 - Simulator: where the 4/20 power went (8 % -> 17 % left)

With the real action durations in the simulator, 20/20/20/20 nights ended
with ~8 % power and the occasional blackout. `tools/power_report.py` now
also counts the brain's own announcements per night, which made the cause
obvious: **101 "Camera flip: checking Foxy" per night, 6 plain flips.**

A cove check is only allowed when 4B is empty (Freddy's rule), and on
4/20 Freddy or Chica is on 4B most of the time. So every flip was
*planned* as a long cove check (1 s of camera, which almost always spans
a power charge), then found 4B occupied, skipped the cove, and the next
flip was planned long again because Foxy was still "unverified".

Fix: remember when 4B was last seen occupied and do not plan a routine
cove check for the next 10 s (`FOUR_B_BUSY_SECONDS`); only an uncovered
Foxy tick forces one. Result on 100 simulated 4/20 nights: 100 survived,
17.3 % power left on average (was 8.0 % and 99/100).

---

## 2026-10-22 - Live Night 4: blackout at 477 s (0 % power)

The campaign continued (03:31) with the code from *before* the cove-check
fix, and ran out of power at about 477 s. Counting the log:
22 Foxy ticks "not covered by a flip", 6 Foxy alerts (left door shut, cove
checked), one real Foxy run with a bang on the door, 9 "light did not come
on" retries, and one camera flip the game did not register (the other
nine "Monitor did not come up" lines are after the blackout, when the
monitor no longer works).

Lessons:
1. The uncovered-tick -> alert -> doors-shut spiral is the power sink on
   the real game too, exactly as in the simulator. 22 uncovered ticks on
   a night with Foxy at level 2-3 means the flips were landing in the
   wrong place or were skipped for door work, not that the game ignored
   them.
2. A reminder of what the cove check is for: ANY camera picture re-rolls
   Foxy's lock every 0.1 s and keeps him in the cove; looking at 1C only
   tells the bot which stage he is at. Fewer cove checks cost no safety.
3. Heavy simulations and video renders were running on the same laptop
   during this night. The game polls the mouse once per frame, so from
   now on nothing heavy runs on this machine during a live night.

The bot now writes the power left to the log every 30 s so the next loss
can be read as a curve instead of a guess.

---

## 2026-10-22 - Live Night 4 again: Foxy, through a door the bot thought was safe

Second try at Night 4 (03:42), with the cove-check fix. Lost at 199 s with
69 % power: the Game Over screen, no HUD, the monitor refusing to come up.
The log shows Foxy seen at stage 2 at 164 s, then a "hold" flip every
5 s, each one believed to cover his tick - and nothing else. Foxy attacks
25 s after reaching stage 3, so he must have reached it around 172-175 s
*through* one of those flips, and the left door was open when he ran.

Back to the decompiled events, which settle it:

* `[130]` hovering the flip bar only starts the flip-up *animation*;
  `[133]` sets `viewing` when that animation **finishes**; `[329]` re-rolls
  Foxy's lock every 0.1 s **while viewing > 0**; `[313]` the lock counts
  down one per frame; `[191]` Foxy may only move while the lock is 0 and
  the monitor is not on 1C (`viewing != 99`; 4B is 42).
* A hold flip lowered the monitor as little as 60 ms after the first
  0.1 s instant it assumed. The night-start fit wobbles by +-70 ms, so
  that instant could fall just outside the picture - no re-roll, lock 0,
  Foxy free to move.
* The routine cove re-check ran every 30 s; Foxy's fuse is 25 s.

**Fix.** Everything about Foxy's lock now uses a 0.12 s clock margin
(`FOXY_CLOCK_MARGIN`); a hold flip keeps the picture up for at least
0.3 s; the cove is re-checked every 15 s. And the simulator's body now has
a wandering clock error of up to 0.07 s, so timing that only works with a
perfect clock fails in the simulator first.

**What the wandering clock found at once** (all fixed the same hour):
* Bonnie/Chica walked in when a door was reopened on the very frame of
  their tick: the brain had booked the tick as "passed" 0.12 s after its
  own idea of the time. Now a tick counts as upcoming until 0.2 s after
  it (`TICK_SETTLE`, used by every "their next tick" calculation).
* A peek (open the door, look) was started with an optimistic time
  estimate and overran the other door's just-in-time click by a quarter
  of a second. The estimate now includes the cooldowns and a margin, and
  the peek re-checks the other door's deadline right before opening.
* With wider margins, peeks often no longer fit between a tick and the
  next Foxy flip and the door stayed shut for whole 5 s cycles (0.5 %
  each). New "blind reopen": open the door right after their tick, plan
  the just-in-time click for the next one, and look whenever there is
  time.

Simulated with the wandering clock: nights 1, 4, 5: 60/60 each; 4/20:
40/40 but only ~7 % power left on average (it was 17 % with a perfect
clock). The margins cost power; tuning continues on the live game.

---

## 2026-10-22 - Live Night 4, third try: both doors due together (lost at 443 s)

Bonnie and Chica were both at their doors from 436 s on, each on a
"blind reopen" cycle (door open between ticks, shut just in time). Their
ticks fell 0.9 s apart again: Bonnie's click was planned for 441.9 s,
Chica's for 442.8 s. After Bonnie's click the bot still had to wait out
the click cooldown and pan to the right; Chica's click landed at 443.2 s,
her tick was 443.22 s. In.

`_plan_close` did keep clear of the other door's planned click, but only
by the pan time; it now keeps clear by pan + cooldown + margins on both
sides, and `_choose_job` shuts the second door early whenever two clicks
are due too close together ("two doors due together"). The blind reopens
double the number of just-in-time clicks on a busy night, which is what
made this collision likely.

---

## 2026-10-22 - Live Night 4, fourth try: a click 0.4 s late (lost at 384 s)

Bonnie on a blind-reopen cycle; a Foxy hold flip at 374.7 s; Bonnie's
just-in-time click planned for 377.3 s landed at 377.7 s - his tick - and
the two follow-up clicks were ignored: **once he is inside, the door
button is dead** (`[96]`: `NOT bonnie overlapping "got you left"`). He
killed when the next flip lowered the monitor.

Where the 0.4 s went is not in the log yet (the flip's "monitor down"
verification is the suspect), so two things changed: the bot now heads
for a planned click 0.4 s earlier than strictly needed (`JIT_HEADROOM`;
the click itself still waits for the planned moment, so no power is
lost), and planned clicks keep an extra 0.3 s clear of a flip. And the
body now warns whenever a timed wait ends more than 0.15 s late, naming
the slowest screen read, so next time the culprit is in the log.
