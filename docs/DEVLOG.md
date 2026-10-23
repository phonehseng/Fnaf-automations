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

**Found it, one night later.** The new warning "Monitor still showing
when turning left - lowering it first" appeared four times in the next
Night 4. `Controller.camera_down` took a single frame without a camera
label as proof that the monitor was down - but right after the brain
switches back to 4B before lowering, the switch static hides the label
for a few frames. So the swipe was skipped, the monitor stayed up (door
clicks are ignored while viewing, and Foxy's ticks were "covered" by a
flip that never ended), and the next action paid for lowering it. Now the
monitor only counts as down after 0.2 s without a label, and a believed-up
monitor is always swiped.

---

## 2026-10-22 - Measuring Bonnie's ticks: the game's pace depends on the screen

Night 4 was lost twice more to just-in-time clicks that should have been
fine, so the tick model itself went under the microscope.
`tools/measure_ticks.py` shuts both doors, keeps the monitor on Bonnie's
camera and timestamps the moment his picture changes (a room change only
happens on his tick). Two models were compared: nominal (tick k at
k x 4.97 game seconds) and "whole frames" (the timer re-arms on a whole
frame: 299 frames = 4.9833 s per tick, drifting 0.8 s later by 300 s).

Result (clock fitted in the office during the first 36 s):

```
leaves 1B   k=12  nominal +0.21 s   frames +0.05 s
leaves 5    k=16  nominal -0.02 s   frames -0.23 s
leaves 1B   k=18  nominal -0.20 s   frames -0.44 s
leaves 5    k=33  nominal -0.44 s   frames -0.88 s
leaves 1B   k=40  nominal -0.82 s   frames -1.36 s
```

The ticks come *earlier* and earlier than the nominal model, and the
frames model predicts the opposite, so that one is dead. The early
drift is the clock: it was fitted while the office was showing
(1.0065 real s per game second), but with the monitor up the game runs at
a different pace (about 1.002). The game's speed depends on what it is
drawing, and the fit stopped updating because the HUD was only read on
office frames.

**Fix.** The HUD is now read off every camera frame too, and the clock is
fitted to the last two minutes of power changes instead of the whole
night, so it follows the current pace.

**Second look at the same numbers, in REAL seconds.** Converting the
bot's scaled times back to real seconds since the night start:

```
leaves 1B   k=12   real  60.24 s   k x 4.97 = 59.64   +0.60
leaves 5    k=16   real  80.02 s             79.52   +0.50
leaves 1B   k=18   real  89.84 s             89.46   +0.38
leaves 5    k=33   real 164.63 s            164.01   +0.62
leaves 1B   k=40   real 199.27 s            198.80   +0.47
(next run)  k=22   real 109.78 s            109.34   +0.44
```

Flat. Bonnie's timer runs at **exactly 4.97 real seconds**, offset by
about half a second, while the power readout (and so 6 AM) drifts at
1.0065 real seconds per tick. The bot's single scaled clock was right
for power and wrong for Bonnie by `0.5 - 0.032 k` seconds: nothing at
75 s, -0.8 s at 200 s, -2 s at 400 s - which is where every Night 4
loss sat, and exactly where the last one happened (tick 88: the model
said 440.2 s, the real-time rule says 437.9 s, the "lost" door click was
at 438.0 s).

**Fix.** Movement ticks are now computed in real seconds
(`rules.ANIM_TICK_PHASE` + k x period) and converted into the brain's
power-second clock with the measured scale (`Brain._next_tick`,
`_tick_times`). The simulator keeps one clock for everything (scale 1,
phase 0). Why one Clickteam timer drifts and another does not is still
open; the measurement is what the bot follows.

**Chica's phase is different.** The next live Night 4 (06:10) was lost
to Chica on a click made 0.05 s after k x 4.98 real seconds - she was
already in - so her timer has no half-second offset. Phases are now per
timer (`rules.TICK_PHASE`: Bonnie 0.4, Chica 0, Foxy unmeasured 0).

---

## 2026-10-22 - Where the power went once the timing was right (two blackouts)

With the timers right, Night 4 was played twice to a blackout at 0 %
with nobody inside. Both logs show the same thing: usage 3-4 for minutes,
i.e. both doors shut nearly all the time. The simulator (now with a
per-night power report, `tools/power_report.py`) reproduced it and the
reasons, one by one:

* a Foxy hold flip lowered the monitor too early on cove-check flips
  (half of all ticks "not covered" -> alert -> both doors shut);
* the live flip takes 0.75 s to show a picture, not the 0.55 s animation
  the rules quote, so flips started late;
* a door reopened 0.7 s before it had to shut again, then shut early for
  a "schedule conflict" with the other side's light check - every cycle;
* the right door starved: Bonnie's and Chica's ticks keep almost the same
  spacing all night, so Chica's closing click could never be planned
  around Bonnie's, and the right door stayed shut for 50-60 s at a time
  (6 % each time).

Fixes, all in `Brain`: `_hold_until` for every flip; the body reports its
live flip latency; reopens need a 1.2 s open span; the door with the
earlier tick is reopened first and may push a flip back by 0.5 s (flips
are planned with that slack); a check that collides with a planned click
moves the click earlier instead of shutting the door at once; and a door
whose closing slot is blocked by the other door's click shifts that
click. Simulated night 4: 30/30 at ~12 %; night 5 is still tight
(22/30) - the margins that make the timing safe cost about ten points of
power, and night 5's baseline alone is ~71 %.

**Chica measured properly** (06:58, `--who chica`, residuals against
k x 4.98 real seconds): +0.59 s (k=19), +0.62 s (k=23), +0.79 s (k=42).
So both timers sit about half a second after the bot's night start
(`TICK_PHASE`: Bonnie 0.5, Chica 0.6) - the earlier "Chica has no offset"
reading came from a lost click, not from her timer. Lost door clicks are
therefore a problem of their own: the bot now saves a screenshot whenever
the door button's lamp says a click was ignored.

**Night 4 won** (07:14, twelfth attempt of the day): 6 AM screen at
533.4 s, 8 % power left, 2 of 40 Foxy flips uncovered, one door click
lost and retried. Night 5 started straight after with the same code.

**Night 5 won** (07:24): 6 AM at 533.9 s with 2 % left - usage sat at 1
for most of the night, so this was the baseline drain plus the extra
charges of the (deliberately wide) door margins. The bot went on to the
6th Night on its own.

**Lost clicks, a hypothesis.** The door-button lamp is read 0.03 s after
a click; the game applies the click on its next frame and the screenshot
lags one more, so an early look can still show the old colour and the
"retry" then toggles the door the wrong way. The confirmation now looks
twice before retrying and gives up after three lost clicks instead of
clicking blindly.

**6th Night lost (07:31, 26 % power) to exactly such a click.** Bonnie
seen in the doorway at 375.6 s, the "danger first" door click 0.1 s
before his tick ignored, the retry after it (he was in by then; the
button is dead once he is inside). Two theories tested:

* *The game still thinks a camera is up after an early put-down*
  (`viewing` is set when the flip-up animation finishes, event `[133]`).
  `tools/measure_flip.py`: 18 of 18 door clicks accepted after put-downs
  0.3 - 1.3 s after the label appeared. Dead.
* *The click cooldown.* A door or light click sets a 10-frame cooldown
  (`[95]`); the bot spaced its clicks 0.19 s apart, i.e. 11.3 frames at
  the real 16.8 ms frame time - half a frame of margin, and frames are
  sometimes 35 ms. The "danger first" door click always comes exactly one
  cooldown after the light click, so it is exactly the click that lands on
  the edge. Every "light did not come on" retry fits the same picture.
  Clicks are now spaced 0.26 s (15 frames) apart.

**Confirmed on the next 6th Night (07:40):** not a single lost click or
failed light in 500 s. That night was lost to the battery instead (0 % at
495 s): the 6th Night's baseline drain is ~71 %, the Foxy flips ~3 %, and
each door cycle (shut just in time, reopened after the tick) costs one to
three power charges - with Bonnie at 10 and Chica at 12 there are ~60
such cycles. The margins that made the timing safe (0.75 s click lead,
0.65 s tick settle) were tightened to 0.5 / 0.4 now that the timer
phases and the click cooldown are understood. The scheduler still leaves
the right door shut too long on busy nights (simulated 6th Night: a few
10-20 s closures per night); that is the next thing to fix for the 6th
Night and 4/20, and it is a power problem, not a safety one.

Where things stand at 08:00: Nights 1-5 won live with zero jumpscares in
the final runs (Night 3 at 34 %, Night 4 at 8 %, Night 5 at 2 %); the 6th
Night and 20/20/20/20 run out of power before 6 AM.

Three more 6th Night attempts (07:55 - 08:24) found and fixed three
scheduling edge cases on the way - the second due door shut too late to
pan back for the first click; a cove-check flip overrunning a planned
click because it was planned with the short-flip length; the title's
static band hiding the "6th Night" entry from a single-frame check - and
the last attempt reached 420 s with 22 % before a Foxy alert came too
late. The 6th Night remains open: on the power side (door cycles) and on
Foxy coverage when both doors are busy.

**Also noted (from the user):** the hall light works with the door shut,
and on the right side Chica's window is beside the door, so a peek on
the right may not need the door open at all. The simulator assumes a
shut door hides both sides; to verify on the right and exploit (TODO).

---

## 2026-10-22 (afternoon) - Power on busy nights: where the door seconds went

Goal: the 6th Night and 20/20/20/20, which kept running out of battery
with nobody getting in. New tool: `tools/door_spans.py` plays simulated
nights and lists every door closure with the brain's reason for it, how
long it stayed shut and how many power charges that cost. In order of
discovery:

1. **Blind reopens pushed Foxy flips late.** Letting a reopen run past a
   planned flip uncovered half of Foxy's ticks, and every uncovered tick
   ends in an alert that shuts both doors. Reopens may no longer delay a
   flip; whether a reopen is worth it is now decided by the power charges
   it saves, not by a fixed window.
2. **At AI 20 a move never fails** (`Random(20) + 1 <= AI`). Someone seen at
   a door that was shut through their tick has certainly been sent back,
   so the door simply opens. (The first version counted from the wrong
   tick and was one move optimistic - the simulator caught it at once:
   moves are now counted from the earliest tick at which they could have
   been sent back.)
3. **A Foxy alert let an urgent light check jump a planned door click.**
   Fixed: the planned door is shut first.
4. **Chica can be checked with the right door SHUT.** Pointed out by the
   user and verified live (`tools/check_shut_window.py`): the window is
   beside the door and reads "empty, margin 6.1" exactly as with the door
   open, while the left door hides Bonnie's doorway completely (margin
   0.2, untrusted). Chica's "has she left?" check is now a window look -
   no door cycle at all.
5. **Doors shut on nobody stayed shut.** After a window look found Chica
   gone, nothing reopened the door. Opening a door nobody is at is always
   safe (an arrival at an OPEN door only gets in on the NEXT move, and the
   normal check catches it), so the scheduler now does.
6. **An unseen Bonnie kept the left door shut for minutes** (one closure
   lasted 194 s). After a Foxy alert nobody knows where Bonnie is, and a
   full peek - open, look, maybe shut - needed a ~2 s gap that most
   cycles never have, because Bonnie's, Chica's and Foxy's ticks run
   nearly in step (4.97 / 4.98 / 5.01 s). The peek is now split: reopen
   blind right after his tick with a just-in-time closing click planned,
   then flash the light in any later gap; if he has gone, the click is
   cancelled.

Result, 100 fresh simulated nights each (wandering clock on):

| night | before (morning) | now |
|---|---|---|
| 4 | 30/30, ~12 % | 100/100, 18.6 % |
| 5 | 18-22/30, ~8 % | 98/100, 12.8 % |
| 6th | 1-11/20, ~2 % | 100/100, 12.7 % |
| 20/20/20/20 | 5-8/30, ~3 % | 99/100, 13.3 % |

No break-ins in 700 nights; the three losses are the battery.

### Live, 13:35 - 13:50: 6th Night WON, 20/20/20/20 lost at 307 s

**6th Night: won, 6 AM at 0 %.** First live win of the 6th Night, but the
simulator had promised ~13 %. The difference: 19 of 106 Foxy flips did not
cover his tick (11 alerts, each shutting doors). The flips started up to
0.8 s late, every time right after "door closed (before camera flip)":
when a planned door click would collide with a flip, the bot shut that
door first - but only started doing so at the flip's own start time, so
the pan and the click cooldown came out of the flip. It now starts early
enough to finish before the flip (and wakes up in time to decide), and an
overdue flip is costed from *now*, not from its planned start (a late
cove-check flip once ran 0.8 s into a planned door click that way).

**20/20/20/20: lost at 307 s with 48 % power.** Chica's just-in-time
click landed 0.31 s before her *assumed* tick, and the monitor would not
come up right after - she was in. The assumed tick came from the phases
measured this morning (Bonnie 0.5 s, Chica 0.6 s), and those were
measured wrong in one direction: `measure_ticks.py` timestamped the camera
READING that saw the room change, up to ~0.25 s after the move. So they
are upper bounds. The brain now assumes the earliest plausible phase
(Bonnie 0.15 s, Chica 0.35 s) and keeps the 0.4 s "tick settle" for the
other side, and the simulator now tells the brain slightly wrong phases
(up to +-0.15 s) on purpose - it found one more late-click path at once
(the late cove-check flip above).

**200-night 4/20 batch with the wrong phases: 5 break-ins.** Two more
holes in the AI-20 "certainly sent back" proof, both found by the
simulator:

* The game has a single "who is moving" slot (`move who?` in the
  decompiled events). A move waiting for a still-closing door can be
  overwritten by the other animatronic's tick - then Bonnie simply stays
  at the door. The proof now needs the door FULLY closed at his tick.
* Moves since a repel are now counted from when he was last SEEN at the
  door, not from the latest door closing (an earlier, unproven tick may
  already have sent him back).

After both: 4/20 195/200 (5 batteries, no break-ins), nights 2-6 500/500.

### Live 4/20 #2 (14:28): lost to Foxy at 212 s - and what his code says

Lost at 212 s with 61 % power. The monitor refused to come up, which the
decompiled flip-up event `[130]` only does while Foxy is attacking
(`fox progress == 5`) or Freddy is in. The last cove picture, at 208 s,
was black: the game blanks a camera when someone moves in that room -
Foxy leaving. The bot had treated the unreadable picture as "no news",
and on 4/20 nights 4B (which must be clear before looking at the cove) is
almost never clear: Foxy had not been seen for 200 s.

What Foxy's events say (`[40]`, `[315]`-`[324]`):

* At stage 3 he leaves exactly **1500 frames (25 s)** later, whatever the
  cameras do - silently. The running sound ("run") only plays when he is
  *made* to run by viewing West Hall at stage 3 (the bot's own emergency
  move); then he arrives 100 frames later. So listening for him (a good
  question from the user) cannot catch the dangerous case.
* At the door: left door open -> jumpscare; shut -> he knocks, and the
  power drops by **10 + 50 x (earlier knocks)** units: 1 %, 6 %, 11 %,
  16 %... Keeping him in the cove matters for power, not only safety.

Changes:

1. An unreadable cove counts as "Foxy may be out" (alert at once).
2. Because the fuse is 25 s, a *possible* stage 3 no longer shuts doors
   immediately: the bot tries to look on its normal flips and only runs
   the full alert (left door shut, right door too if 4B is busy, look)
   7 s before the earliest possible end of the fuse.
3. **Foxy's timer phase, measured** (`tools/measure_foxy_phase.py`): a
   Custom Night 0/0/0/20, left door shut, camera never raised; every
   knock lands 1500 frames after the tick that brought him to stage 3 and
   shows as a power drop between the once-per-second charges. Four knocks
   (6 %, 11 %, 16 %, 21 % - the formula exactly) put his ticks 0.05 -
   0.16 s *before* k x 5.01 s. The brain now uses -0.1 s and covers 0.15 s
   either side; covering an unknown phase (up to 0.6 s late) had cost
   ~4 % of camera power.
   Side finding: with the camera never raised, the power clock ran at
   exactly 1.0000 real s per second - the 0.65 % slowdown comes from
   camera use (the game drops frames while the monitor's static plays).
4. A Foxy alert keeps the camera up across a Foxy tick that falls in the
   middle of it.
5. A double-counted pan made the scheduler choose a light check over an
   overdue Foxy flip ("safety first") when the check could have waited.

Simulated 4/20 after all five: 60/60, 16.0 % left on average (worst 9.8 %),
0.12 knocks per night.

### Live 4/20 #3 (15:04): lost to Freddy at ~100 s - a static frame read as "4B empty"

Before looking at Pirate Cove the bot reads 4B: Freddy can only get in
while a camera other than 4B shows, and only from 4B. The 4B frame it
used was a camera-switch static burst - white bands over half the picture
- and the classifier called it "empty, margin 11.7" (a confident answer).
The bot switched to the cove with the right door open, and the next thing
it saw was a blank cove and a monitor that would not come up.

Checking the saved evidence: 24 of 1217 camera frames are such bursts, and
the classifier gave confident answers on them (one "Freddy, margin 34.6"
on a frame with no Freddy). Fix: frames with more than 15 % near-white
pixels in the picture area are thrown away before classification, and 4B
counts as empty only if two clean frames agree.

### Live 4/20 #4 (15:09): lost at ~55 s - Bonnie's timer was assumed 0.15 s late

The bot concluded "Bonnie certainly sent back (AI 20, door shut)" at 49.5 s,
reopened the left door, and he walked in at his next tick: the game-over
static was already on screen in the next doorway frame. The proof needs
the door fully closed at his tick; with a tick that really came ~0.15 s
earlier than assumed, the door was still closing - the move waited, and
the game's single move slot dropped it.

So the phases were measured again, properly. New tool:
`tools/measure_door_ticks.py`. The game switches the hall lights off on the
very frame Bonnie or Chica arrives at or leaves a doorway, so on a Custom
Night with only one of them active (AI 20) and the light kept on, the light
button's lamp going dark timestamps their ticks to ~0.02 s.

| timer | measured offset from k x period |
|---|---|
| Bonnie (12 ticks) | -0.02 .. +0.09 s (mean +0.04, incl. ~0.03 s capture delay) |
| Chica (8 ticks) | -0.06 .. +0.06 s |
| Foxy (4 knocks) | -0.05 .. -0.16 s |

All three are essentially on time. This morning's camera-based numbers
(+0.5 / +0.6 s) were wrong: that measurement kept the camera up all the
time, which slows the power clock it was measured against. The brain now
uses -0.05 / -0.05 / -0.1 s (erring early, the safe side for door clicks).
Both measurement nights ran the power clock at exactly 1.0000 real s.

### Live 4/20 #5 (15:23): lost at ~276 s with 50 % power - cause not certain

The best run so far (past the half-way mark at 58 %). At 268 s the 4B
picture was black (the game blanks a camera when someone moves in that
room), at 275.5 s the right light would not come on twice, then the monitor
would not come up - in the game's rules that is Freddy in the office.
Freddy can only get in while the monitor shows a camera other than 4B, and
the bot never checked which camera a flip-up actually showed: a lost click
after the 255 s cove check would have left the monitor on Pirate Cove for
every later "hold on 4B" flip. Not proven, so two cheap guards went in:
every camera switch is verified on screen (and retried), and after every
flip-up the room label is read and the monitor switched to 4B if needed,
with a warning in the log - the next run will show whether it happens.

### Live 4/20 #6 (15:31): lost at ~278 s - the reference point was moving

Same symptoms as #5 (the monitor refused to come up at 277 s - in the
game's rules only Freddy or an attacking Foxy do that), and Foxy had been
seen only once all night, at 20 s, with every tick counted as covered.

`tools/measure_door_ticks.py --camera` settled the timer question: same
hall-light timestamps, but with the camera raised between Bonnie's ticks
so the game clock slows down. Against real time his ticks stayed within
0.24 s; against the game (power) clock they drifted by over a second. So
the movement timers do run in real seconds. But the "real seconds" were
counted from `t0`, the night start re-fitted from the power readout all
night - and on camera-heavy nights the power clock's pace changes, so the
fit kept moving that origin by tenths of a second. Every Foxy flip and
every door click was placed relative to a moving reference.

Fix: the body keeps a fixed `real_origin` (the night's first frame,
refined only by the earliest power sightings, while both clocks still
agree); movement ticks are computed in real seconds from it and converted
to the brain's clock with `game_to_real` / `real_to_game`. Measured again
(Chica, camera-heavy): offsets +0.114, +0.131, +0.132, +0.134 s - flat.

Also from #6: a "certainly sent back" (AI 20) is now verified with one light
check before their next tick instead of trusted outright.

### Live 4/20 #7 (15:55): to 410 s, then Chica - read off the OBS footage

The best run yet: past the 277 s mark, two Foxy escapes spotted and handled
(he knocked on the shut left door both times, -1 % and -6 % on the HUD,
exactly the game's formula). At ~410 s the log alone could not say who
attacked, so the frames were pulled from the OBS recording at 5 fps: the
right door is visibly shut (green lamp) through Chica's computed move at
405.7 s, the bot logs "Chica certainly sent back (AI 20, door shut)", the
door opens at 406.8 s, a light check at 408.7 s still shows her at the
window, and at 409.4 s - the moment the monitor comes down - it is her
jumpscare.

So the AI-20 shortcut was wrong a second time, with the door fully shut:
she simply did not move at that tick. Whatever the reason (an AI level one
below 20 after a lost arrow click on the Custom Night screen, or the
game's single move slot), the shortcut is now off (`TRUST_AI20_PROOF`).
Departures are always confirmed by a look: Chica through her window with
the door shut, Bonnie by a blind reopen whose closing click stays planned
until a look says he has gone. Cost in the simulator: 4/20 59/60 at 12.3 %
(was ~15 %).

### Live 4/20 #8 (16:07): Bonnie at ~328 s, 41 % power - the timers fall behind

With the AI-20 shortcut off the run looked healthy (Foxy never moved, every
door visit handled) until ~328 s. The OBS frames: left door shut (green
lamp) from 324.6 s, the bot's blind reopen at 326.6 s ("Bonnie may still be
there"), door fully open by ~327 s, camera flip for Foxy, and Bonnie's
jumpscare the instant the monitor came down at ~328.5 s.

Two things from the decompiled events explain how:

* Bonnie's timer ([188]) only *sets* the shared "move who?" counter to 1.
  The doorway events consume it only when the left door is fully open
  (AltA 0: [214], he gets in) or fully shut (AltA 2: [215], sent back).
  While the door is moving (AltA 1 closing, 4 opening) the move simply
  waits, and fires on the first frame the door finishes. So a reopen whose
  click lands *before* his real tick lets him in, however fast the bot is.
* For that, his tick must have come at least 0.54 s after the one the bot
  computed (326.04 s). The same night's earlier blind reopens (296.96 s,
  301.86 s) survived, so the lag was below ~0.7 s then.

That lag is in old data too. The `measure_door_ticks.py --camera` run
(Bonnie, camera raised between ticks) was summarised as "within 0.24 s",
but in time order it reads +0.25 s until 160 s, then +0.32 s (195 s), +0.42
(229 s), +0.47 (234 s): with the camera in use the movement timers *fall
further behind* real time as the night goes on. On a quiet night they do
not (-0.02 .. +0.09 s flat). Every 4/20 loss came after 270 s, where the
bot's tick model was ~0.5 s early - looks "after" the tick were really
before it, and reopens landed on it.

Same reasoning for Foxy (event [191]): his ticks would move late out of the
camera views meant to cover them, which fits the two Foxy runs late in #7.
A full-night measurement with the camera in use is running to get the
curve.

### The timers' lag, measured over whole nights

New tool `tools/measure_timer_clock.py`: Bonnie alone at AI 20, the camera
up for most of every cycle (to load the game the way a 4/20 night does),
and each tick timestamped from the hall light. Each prediction is anchored
on the last tick actually seen, and the light covers both the real-time
and the game-clock prediction, so a drifting model cannot make it miss
ticks (the older tool timed its camera raises from the real-time model
only, lost track of Bonnie, and its door logic went out of step).

Bonnie's offset from k x 4.97 real seconds, two nights:

| night time | plain start | with a warm-up at night start |
|---|---|---|
| 35-45 s | +0.18 .. +0.45 | +0.03 |
| 60-90 s | +0.67 .. +0.79 | +0.08 .. +0.17 |
| 135-170 s | +0.78 .. +0.90 | +0.08 .. +0.25 |
| 200-260 s | +0.79 .. +0.85 | +0.32 .. +0.59 |
| 280-340 s | +0.77 .. +0.84 | +0.86 .. +1.15 |
| 340-445 s | +0.79 .. +0.84 | +1.10 |

(The warm-up: both doors shut and opened, both lights, every camera viewed
once, in the first 13 s.) So the movement timers fall behind real time by
up to a second over a camera-heavy night, in bursts, by a different amount
every night - and against the bot's fitted game clock they drift too (the
second night: -0.2 s early on, then flat at -1.0 s from 160 s). Neither
clock predicts the ticks; the lag has to be measured during the night.
Live 4/20 #8 fits: ~0.6 s by 300 s, more than the 0.4 s of slack the bot
allowed after a tick.

**How the bot measures it:** someone seen at a shut door is sent back at
their next tick (if they move at all), and the game switches the hall
lights off on that frame. So the bot keeps the light on across that tick
and watches the button's lamp (`Brain._watch_leave`). The lamp going dark
proves they have gone - no need to open the door to look - and timestamps
the tick. If the lamp stays lit they did not move. Every tick in the brain
is now the earliest the real one can be (measured phase + the smallest lag
the samples allow), and every "has the tick happened yet" decision and
every Foxy flip allows for the largest lag they allow.

**The catch:** early in the night Bonnie's, Chica's and Foxy's ticks fall
within a second of each other (4.97 / 4.98 / 5.01 s), and the Foxy flip
has to straddle Foxy's tick - so for the first ~200 s a departure watch
always collides with a flip. Before the first sample the bot has to assume
a wide range, which costs a lot of power (simulator: camera time and
left-door time both doubled). Still being worked out.

**Two more measurement nights, and what the bot does now.** A second cold
start (no warm-up) repeated the first: +0.18 s at 25 s, +0.51 s at 55 s,
then flat at +0.53 .. +0.62 s to the end (300 s). Three cold starts (two
measured, live #8) all level off at 0.55 - 0.8 s within 90 s; the one
night with a warm-up stayed small for two minutes and then kept climbing to
1.1 s. So the warm-up (in the code, `WARMUP`) is off, and the bot plans for
a cold start: until its first sample, the lag may be anything from 0 to
0.15 s + 0.012 s per second after 20 s (capped at 0.95 s).

Samples come from departure watches - when one fits. Fixes found in the
simulator on the way:

* A watch only proves anything for the FIRST tick that can have come after
  they were last seen at the door - with the lag, that can be a tick whose
  earliest time was before the sighting. Watching a later one read a
  Chica who had already been sent back as "still at the door", and read
  Bonnie *arriving* back as Bonnie leaving.
* Early in the night Bonnie's and Chica's ticks are hundredths of a second
  apart, so the lamp often cannot say whose tick it was; it still pins the
  lag to one of two values, and both are kept (the earlier for door clicks,
  the later for "has the tick happened").
* Before the first sample a watch may take one Foxy flip's place (Foxy at
  most one stage further); after that the flips win and a watch is cut
  short to fit before them.
* Foxy flips only cover 0.3 s of the lag range, not all of it: the lock a
  picture sets lasts 50 + Random(1000) frames (event [329]), so a tick a
  few tenths late is rarely missed - and covering the full range made
  every flip a second longer.

Simulator with timers lagging like the cold-start measurements (0.4 - 0.85 s
jump, small drift), 40 nights each: the previous brain survives 1/40 4/20
and 0/40 6th Nights (Bonnie, every time - as live); the new one 36/40
(6.0 % left) and 36/40 (8.4 %), every loss a power-out. Night 5 29/40
(6.9 %): the lag costs power everywhere, and Night 5 has the least spare.

### Live 4/20 #9 (17:25): Foxy at ~158 s, 69 % power

First live run with lag tracking. One lag sample (29.7 s: 0.04 - 0.10 s,
Bonnie and Chica ambiguous), none after - nobody stood at a shut door at a
moment that did not collide with a Foxy flip. Three early Foxy ticks went
uncovered (one given up for that sample), the alerts shut the left door
from 73 s, and the cove pictures at 77, 85 and 94 s were static (the game
blanks a camera when someone moves in it - Foxy changing stage); the one
at 100.9 s was a clean stage 0 (curtains shut, "out of order" sign) - most
likely he had knocked on the shut door and been reset (event [324]: back
to Random(2)). Then every flip until 154 s logged its tick as covered,
and at ~158 s Foxy ran in through the open left door (OBS frames).

From a real stage 0 at 100 s to a run at 158 s takes three free ticks in
~35 s. With a flip every cycle, the decompiled rules make that very
unlikely if the ticks come a little AFTER the flips (the lock lasts
50 + Random(1000) frames after the monitor comes down, 9 s on average) -
but likely if they come BEFORE them (four seconds after the previous view,
the lock has run out about one time in five). So Foxy's timer may have
been early relative to the model, which nothing measured so far explains
(his phase came from knocks on a quiet night, assuming the 1500-frame
fuse runs at 60 fps). Open.

Simulator experiments with the lag model's jump widened to 1.0 s (40
nights): the committed brain 35/40 6th Nights, 30/40 4/20 - covering more
of the lag range in Foxy flips, or holding the first sample back until the
lag settles, all came out worse (power).

### Does Foxy's timer fall behind too? Yes, like the others

New tool `tools/measure_foxy_lag.py`: Custom Night 0/0/20/20, left door
shut all night. For the first 100 s the camera is up for most of every
cycle (to build up the timers' lag); after that it stays down so Foxy can
advance and bang on the door. Chica's ticks come from the right hall light
as before; Foxy's from his bangs - the power drops on the very frame
(event [324]), 1501 frames after the tick that took him to stage 3.

| bang (real s) | power | Foxy's stage-3 tick | offset from k x 5.01 | Chica's lag then |
|---|---|---|---|---|
| 135.5 | 58 -> 57 % (1st: -1 %) | 110.47 s | +0.25 | +0.25 .. +0.30 |
| 170.5 | 48 -> 42 % (2nd: -6 %) | 145.50 s | +0.21 | +0.27 .. +0.30 |
| 205.5 | 32 -> 21 % (3rd: -11 %) | 180.52 s | +0.16 | +0.29 .. +0.31 |

(The other power "drops" in the raw output are HUD misreads - 97 % read
as 7 % - or noise while the camera was up.) Foxy's quiet-night phase was
about -0.1 s, so his lag here is +0.26 .. +0.35 s: the same as Chica's.
One shared lag for every "every N seconds" timer is what the brain already
assumes, so Foxy's ticks were not early on live #9 - that loss is still
not explained by the timing model; the likeliest reading is a lag much
larger than on the measurement nights (4/20 loads far more) that the bot
had no sample of.

### Live 4/20 #10 (19:16): out of power at ~388 s

Nobody got in; the battery ran out. The log explains it: not a single lag
sample all night (0 departure watches), so every margin stayed at the wide
"not measured yet" setting. From ~180 s Bonnie's door went into a loop of
blind reopens ("Bonnie may still be there - door open until ..., then shut
again", 14 times; one watch was tried all night): opened after his tick, shut again before the next,
never looked through - and a watch only counts on the first tick after he
was last SEEN at the door, so once he was not re-seen no watch could ever
be planned again. Foxy cost the rest: views that came up ~0.1 s later than
planned counted his ticks as uncovered (stage 3 possible by 119 s), and
four alerts shut the left door and looked at the cove (it showed him at
stage 1 at 141.7 s - he really was advancing). Also seen: the power-clock
fit jumped by +1.46 s at 372 s.

**After #10 (the user watching it: "the bot kept leaving the door closed
and closing it with no info or light switches").** Exactly what the log
shows: with no lag sample, the "has his tick certainly happened" wait was
~1.4 s, so a peek almost never fitted, and the blind reopens opened ~1 s
before their closing click - open, shut, open, shut, light never on. Fixes:

* A blind reopen now needs the door to stay open at least 2 s
  (`BLIND_MIN_OPEN`), long enough to flash the light through it before the
  closing click - so it learns whether he has gone. (Turning blind reopens
  off altogether cost far too much power: 6/30 simulated 4/20 nights.)
* With no sample after 90 s the lag is assumed to have settled between
  0.45 and 1.0 s (where the cold starts settled), instead of "anything
  from 0 to 0.95". The first real sample replaces that, even downwards.
* A departure watch where the lamp stays lit is no longer read as "still
  at the door": if his tick came after the window he may have gone unseen.
  In the simulator that conclusion chained over five watches on a Bonnie
  who had long gone, then his ARRIVAL back was read as him leaving and the
  door was opened for him. A lit lamp now concludes nothing; a peek does.

Simulator (40 nights each, nobody got in on any of them): 4/20 30/40
(5.9 % left), 6th Night 36/40 (6.7 %), Night 5 36/40 (10.1 %); every loss
a power-out.

### Live 4/20 #11 (19:35): Bonnie at ~79 s

Over in 80 seconds. Bonnie was seen in the doorway at 75.3 s; the bot
planned the door for 78.46 s, before his move at 78.96 s on its model -
and the game ignored the click three times (cursor on the red DOOR button
in the OBS frames, door fully open and idle). Event [96] refuses a door
click while Bonnie is already inside, and the jumpscare came as soon as
the next camera flip came down - so he was most likely in by 78.5 s. That
needs his tick to have come at least ~1.3 s later than the model already
at 75 s into the night: far more lag than any measurement night showed at
that point (~0.5 s). No lag sample had been taken yet.

Also: at 55-56 s Bonnie stayed at the shut door through a tick, which at
AI 20 cannot happen (and Chica did the same on #7). The Custom Night
levels are set by clicking arrows 20 + 20 times with no check; a lost
click leaves 19. The arrows stop at 0 and 20, so they now get 5 spare
clicks at each end - a lost click can no longer matter.

### The lag under a real 4/20 load, and the HUD misreads

New tool `tools/measure_lag_420.py`: Custom Night 20/20/20/20 with both
doors shut all night (nobody can get in; Bonnie and Chica still walk up and
are sent back), the left light on around every one of their ticks, and the
camera up between those windows the way the bot's flips are (4B, Pirate
Cove every third cycle). Lights-out moments, read as Chica's ticks (the
reading that gives a smooth curve):

| night time | lag |
|---|---|
| 45 - 100 s | +0.26 .. +0.43 s |
| 105 - 185 s | +0.48 .. +0.53 s |

So a 4/20 load settles at ~0.5 s too - inside the 0.45 - 1.0 s range the
bot now assumes after 90 s. Live #11's door clicks remain unexplained: the
OBS frames (this recording runs in step with the log) show the cursor on
the red DOOR button for all three clicks and the door never moving - open,
idle, camera down. The only remaining reason in event [96] is Bonnie
already inside, which would need a far larger lag than measured here.

The same night exposed a bigger, older problem: the power readout's digit
reader regularly loses the LEADING digit - 91 % read as 9 %, 75 % as 4 %,
70 % as 0 % - dozens of times a night, mostly on camera frames. Each such
misread looked like two power changes, and power changes are what the bot
fits its game clock to (the +1.46 s jump of the night start on live #10).
`RealBody._power_reading_ok` now rejects readings that go up, drop more
than 20 %, or fall from two digits to one (except 10 -> 9) - unless the
same value comes back five times in a row (a real bang drop).

### Live 4/20 #12 (20:22): out of power at ~422 s

Nobody got in; the battery ran out (79 % at 122 s, 50 % at 243 s, 22 % at
335 s). Its lag samples: 0.16 - 0.23 s at 35 s, then nothing until 356 s
(0.25 or 0.97, ambiguous) and 416 s (0.97, Chica) - so on a live 4/20
night the lag keeps creeping up, to ~1 s by 400 s. Where the power went:
nine Foxy alerts (left door shut, cove look) and 34 "checking Foxy" flips
(only 7 reached the cove - Freddy sits on 4B), all from eleven Foxy ticks
counted as uncovered. Three cove looks showed him really at stage 2 the
whole time - false alarms. The cause: the bot's only early sample (0.16 s
at 35 s, while the lag was still building) held its tick model ~0.35 s
early for the rest of the night, so flips that started in time for the
real ticks looked late on the model.

Changes: a sample taken before the lag has settled (90 s) no longer holds
the floor down after that - until a later sample, the floor is 0.45 s and
the top 0.8 s + 0.0015 s per second after 90 s (1.27 s by 400 s, matching
#12). The simulator's lag drift goes up to 0.0015 s/s to match. (Simulator:
no change either way within noise - it does not reproduce the false Foxy
alarms; the live night is the test.)

### Live 4/20 #13 (20:35): Chica at ~164 s - my own floor rule

This night's lag was small: -0.03 .. +0.10 s at 64 s. But the rule just
added (an early sample does not hold the floor after 90 s) raised the
floor to an assumed 0.45 s at 90 s - so every tick sat 0.4 s too LATE on
the model. Chica was seen at 160.5 s; her move was "at 163.68 s", the
click planned for 163.18 s; her real tick came at ~163.3 s, right on top
of it, and the game ignored the click three times (she was in).

Fix: the floor of the lag range only ever comes from a measurement (a
measured lag is a true lower bound - it never shrinks); an assumption only
ever widens the TOP of the range. With no sample since 90 s the top is
0.8 s + 0.0015 s/s, or the latest sample plus its growth allowance,
whichever is higher. The 0.45 s floor stays only for a night with no
sample at all.

### Live 4/20 #14 (20:40): Chica at ~95 s - the same floor, once more

No lag sample before 90 s, so the "no sample at all" case still raised the
floor to the assumed 0.45 s at 90 s; Chica's click at 93.91 s (0.5 s
before her move "at 94.41 s") was refused three times - she was in. The
assumed floor is now gone completely: only a measured lag raises it.
Simulator (40 nights each): 4/20 26/40, 6th Night 36/40, Night 5 34/40 -
nobody got in on any of them; every loss a power-out.

### Live 4/20 #15 (20:45): out of power at ~444 s

Nobody got in; power 77 % at 121 s, 57 % at 242 s (the best yet), 28 % at
362 s, 0 at ~444 s (two Foxy runs, both bangs on the shut door). The night
budget: 999 units, 1 a second always (53.5 %), plus Night 7's passive 1
every 3 s (17.8 %) - which leaves 28.6 % for every door, light and camera
second of the night. The log's spending in 444 s: ~47 s of camera
pictures (82 flips), the left door shut ~142 s in 21 spans, the right ~74 s,
122 light looks - the doors are the big item. All three departure watches
ended "the other one may have moved", so each left-door visit then waited
14 - 20 s for a peek.

Change: after an ambiguous lights-out, the bot looks at Chica's window (it
shows with her door shut): if she is where she was - at the door or not -
the lights went out for Bonnie, and he has gone. (Also tried: refusing a
blind reopen whenever a Foxy flip would pull its closing click forward -
far worse in the simulator, 7/40 4/20 nights; short reopens still save
power on balance.)

### Live 4/20 #16 (20:59): Foxy at ~246 s, 57 % power

The best power yet (80 % at 121 s, 58 % at 241 s) - and Foxy ran in at
~246 s (OBS frames). The bot believed him at stage 1 at most: one cove
look at 9.5 s (stage 0), two uncovered ticks since, every other flip
logged as covering his tick. Same story as #9. Under the decompiled rules
a tick a little after a flip cannot move him (the lock lasts at least 50
frames after the monitor comes down) - but a tick a little BEFORE one
can (four seconds after the previous view the lock has run out about one
time in five). Why his ticks would fall before the flips on live 4/20
nights is not understood; the Foxy-vs-Chica measurement says his timer
lags like the others.

Guard that does not depend on the answer: with Freddy on 4B the routine
cove checks never happen (they need 4B clear), so the bot had not looked
at the cove for 236 s. Now, whenever the right door is fully shut anyway
(for Chica - several times a minute on 4/20) and the cove has not been
seen for 30 s, the bot looks at it - Freddy cannot get in through a shut
door, so it costs only the camera. A stage 3 there goes straight to the
existing emergency (both doors shut, make him run at the shut door).
Simulator, 40 nights each: 4/20 30/40 (was 23), 6th Night 32/40, Night 5
34/40; nobody got in on any.

### Live 4/20 #17 (21:08), and "the bot keeps needlessly keeping the left door shut"

Out of power at ~436 s (79 % at 121 s, 54 % at 241 s). The user, watching:
"it needs to be aware of the status of every single door and what is
using power. 19 % at 3 AM is absurd." New tool `tools/door_report.py`
(door timeline from a live log) on #17: the LEFT door was shut 169 s of
417 - 41 % of the night - against 12 % for the right. One span alone was
82 s (290 - 372 s): Bonnie seen at 289 s, door shut, and then not a single
look at the left side - no peek ever fitted between the Foxy flips and
Chica's checks, because the lag range was 0.1 - 1.0 s wide. It was that
wide because Chica's watches all ended "ambiguous" (Bonnie, at his shut
door, could have switched the lights off too) - while each time the very
next look through her window showed her gone.

Changes:

* Watching Chica, an ambiguous lights-out is settled on the spot by her
  window: gone - it was her tick (an exact sample); still there - it was
  Bonnie's, and if it was his first tick since he was seen at his door,
  he has left it. (Two simulator losses found on the way: the look
  happens before HER tick may have come, so it must not count as "she
  stayed"; and after an unseen tick of his, the lights going out may be
  Bonnie ARRIVING - opening his door then let him in.)
* A power ledger: the brain books every second each door is shut, why,
  and how long since anyone was actually seen there, plus the camera
  time; it is logged every 30 s next to the power, and the status panel
  shows each door's state ("L SHUT 12s (bonnie at the door...)").
* The power-misread filter accepts an "impossible" value only after it has
  stayed for 2 s (five readings in a row let "48 % -> 4 % -> 31 %" through).

Simulator, 60 nights each, nobody got in on any: 4/20 56/60 (8.2 % left),
6th Night 55/60 (9.5 %), Night 5 52/60 (9.4 %); Nights 1-3 30/30, Night 4
26/30 (power).

### Live 4/20 #18 (21:27): out of power at ~445 s - and the AI-20 shortcut back on

The new power ledger made the cost plain. tools/door_report.py: the LEFT
door shut 177 s of 448 (39 %), mostly in 10 - 16 s spans that ended with a
late peek finding "Bonnie went back towards 1B": he had been sent back at
his first tick behind the shut door, and the bot did not know until a
peek fitted.

At AI 20 he always moves at his tick, and a fully shut door always sends
him back (event [215]). The shortcut that used this (TRUST_AI20_PROOF) was
switched off after live #7, where Chica "stayed at the shut door through
a tick" and walked in once it was opened. Both explanations found since
are dealt with: a lost arrow click could leave her at AI 19 (the Custom
Night setup now has spare clicks), and the timers' lag - her real tick
came after the bot had started opening the door, and a move during a door
animation waits for it to finish and then goes through. Ticks now only
count as passed once the measured lag range is behind them, and a
departure taken on trust is still checked with the light before their
next tick. Simulator, 60 nights: 4/20 60/60 with 11.9 % left (was 56/60,
8.2 %); the 6th Night and Night 5 unchanged (their AI is below 20).

### Live 4/20 #19 (21:37): out of power 40 s before 6 AM

The closest yet: with the AI-20 shortcut the left door was shut 46 s by
395 s (it was 138 s by 402 s on #18), and the power ledger read 61 % at
212 s, 50 % at 273 s, 40 % at 333 s - on course to finish with ~8 %. Then
Foxy: four alerts and two runs in the last 170 s (the second bang 6 %),
and the battery ran out at ~495 s. Nobody got in.

Most of that Foxy work could not have mattered: he attacks only 1500
frames (~25 s) after reaching stage 3. `Brain._foxy_can_attack` works out
the earliest moment he could reach the office - his fuse end at stage 3,
otherwise the ticks he still needs plus the fuse - and if that is after
6 AM the bot stops flipping for him, stops alerting, and does not make him
run (Freddy needs no flips with the monitor down). Simulator, 60 nights:
4/20 60/60 (12.1 %), 6th Night 56/60, Night 5 54/60.

### Live 4/20 #20 (21:50) and why Foxy kept climbing on 4/20 nights

#20 ran out of power at ~450 s (two Foxy runs 32 s apart, the second bang
6 %). Foxy again climbed from stage 0/1 to 3 in about 30 s while the bot
believed it was flipping for him.

Two experiments with Foxy alone (Custom 0/0/0/20):

* the bot itself, flipping on every tick: he gained one stage in ~45 s;
* `tools/foxy_flip_offset.py`: flips placed 0, 2.5 and 1.25 s after his
  computed tick, cove read every third flip - 1 stage in 15 ticks at 0,
  none in 18 at 2.5, none in 18 at 1.25 (the lock a picture sets lasts
  50 + Random(1000) frames, 9 s on average, so ANY regular flipping holds
  him well).

So on his own he barely moves. On 4/20 the log of #20 shows why he did:
between his run at 354 s and the next alert at 381 s there was not one
camera flip. Each cycle, Chica's checks and a blind reopen of Bonnie's
door ran first, Bonnie's planned click was then made "before camera flip"
- but already after Foxy's earliest tick (363.90 vs 363.41 s, 368.85 vs
368.40 s) - and the flip planner, which only ever aimed at ticks still in
the future, quietly moved on to the next one. 25 s with no flip.

Fix: a flip that is late still covers the current tick if his LATEST
possible moment (the lag range after the earliest) is still ahead of the
picture (`Brain._foxy_flip_search_from`). Simulator, 60 nights: 4/20 59/60
(12.6 %), 6th Night 57/60, Night 5 52/60; nobody got in.

### Live 4/20 #21 (22:09): out of power at ~470 s - flips still starved

The best start yet (74 % at 152 s, 63 % at 212 s, 52 % at 273 s, 40 % at
335 s, no Foxy alert until 376 s), then two Foxy runs 60 s apart and the
battery was gone. Between the runs there was again a stretch with no
flips at all (419 - 437 s): every cycle a blind reopen of Bonnie's door,
a Chica check, then Bonnie's door shut "before camera flip" a few tenths
after Foxy's earliest tick - and the late-flip allowance (0.4 s) was not
enough, so each flip was dropped. A late flip now goes ahead up to 1.2 s
after his earliest tick (his real tick usually comes 0.3 - 1.0 s after
it). (Also tried: no blind reopen whose closing click would run into the
next flip - 19/60 6th Nights in the simulator, far too costly.)

One more simulator find: a door released after a Foxy check marks the
animatronic "possibly there" (not seen); a Chica watch then read a
lights-out as that one leaving - it was Bonnie arriving. That conclusion
now needs a real sighting. Simulator, 60 nights: 4/20 60/60 (12.9 %), 6th
Night 55/60, Night 5 55/60; nobody got in.
