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
