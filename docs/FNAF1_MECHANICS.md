# Five Nights at Freddy's 1: Mechanics Reference for the Bot

This document collects the low-level game mechanics of *Five Nights at Freddy's* (PC/Steam, Clickteam Fusion build, v1.132) that matter for a computer-vision bot. The bot's goals are Nights 1-5 plus Custom Night 20/20/20/20, with no jumpscares and as much power left as possible at 6 AM.

The best source available is **FNAF1-Recomp-proj** (Sergey004). It is a clean-room C++ reimplementation whose author treats a CTFAK dump of the original Clickteam event program as "the only source of truth". Its docs and code cite the original event-group numbers. Everything else (wikis, Steam guides, forum posts) was cross-checked against it, and disagreements are flagged.

> **Research caveats.**
> - The Fandom wikis (`freddy-fazbears-pizza.fandom.com`, `technicalfnaf.fandom.com`) and the BreezeWiki mirror blocked direct fetching (HTTP 402 or a bot check). Wiki claims below come from search-engine extracts of those pages, not full reads.
> - Reddit and speedrun.com were not reached within the research budget.
> - The port's `EXE_VERSION.md` was not read, so it is not confirmed that the dump came from exactly v1.132.
> - Calibrate every timing below against the real game before relying on it, especially the hour length and the power-drain rate.

**Tags used in this document**

| Tag | Meaning |
|---|---|
| **[DUMP]** | From FNAF1-Recomp-proj docs/code, which cite the original event groups. |
| **[TW]** | Technical FNAF wiki (search extracts). |
| **[FW]** | Main FNAF Fandom wiki (search extracts). |
| **[STEAM]** | Steam community guide or discussion. |
| **[MEM]** | General community knowledge, **not verified in this research session**. |
| **[DERIVED]** | My own arithmetic from the numbers above. |

Primary sources:
- https://github.com/Sergey004/FNAF1-Recomp-proj
  - `FNAF1-Recomp-proj/docs/AI_MECHANICS.md`
  - `FNAF1-Recomp-proj/src/AnimatronicAI.cpp`
  - `FNAF1-Recomp-proj/src/PowerSystem.cpp`

---

## 1. Global timing and AI

### Tick rate and clock
- The game logic runs at **60 ticks/s** ("Timer 1000 = 1 s"). [DUMP]
- **Hour length: 90 s.** The dump's rule is "minute counter >= 90 → hour++" (groups 264-265). That gives 12 AM→6 AM = **540 s** (6 × 90; my arithmetic). [DUMP]
  - **DISAGREEMENT:** the community/Fandom figure is usually "~89 s per hour, ~8:55 per night" [MEM].
  - **Recommendation:** read the on-screen clock and calibrate. Don't hard-code the night end.
- Hour boundaries, assuming 90 s hours [DERIVED]:

  | Hour | Seconds from night start |
  |---|---|
  | 12 AM | 0-90 |
  | 1 AM | 90-180 |
  | 2 AM | 180-270 |
  | 3 AM | 270-360 |
  | 4 AM | 360-450 |
  | 5 AM | 450-540 |

### Movement opportunities
All four sources agree on these intervals. [DUMP][TW][STEAM]

| Animatronic | Interval |
|---|---|
| Freddy | 3.02 s |
| Bonnie | 4.97 s |
| Chica | 4.98 s |
| Foxy | 5.01 s |

### Roll rule
- On each opportunity the game draws `RandomRange(1,20)`. The move succeeds if **roll <= AI level**. [DUMP][TW]
  - So the chance per opportunity is AI/20.
  - AI 0 never moves. AI >= 20 always moves.
- Expected time per successful move = interval × 20/AI. [DERIVED]
- Evaluation order is Bonnie, Chica, Freddy, Foxy. [DUMP]
- **Bonnie and Chica share one "move-who" channel.** If both succeed on the same tick, Chica overwrites Bonnie and Bonnie loses that move. [DUMP] This rarely matters, but it means that at AI 20 Bonnie can occasionally skip a tick.

### Starting AI (Freddy / Bonnie / Chica / Foxy) and hourly increases
Hourly rule: **2 AM: Bonnie +1. 3 AM and 4 AM: Bonnie, Chica and Foxy each +1. Freddy never increases.** [DUMP][TW][STEAM]

| Night | 12 AM | 2 AM | 3 AM | 4 AM-6 AM |
|---|---|---|---|---|
| 1 | 0/0/0/0 | 0/1/0/0 | 0/2/1/1 | 0/3/2/2 |
| 2 | 0/3/1/1 | 0/4/1/1 | 0/5/2/2 | 0/6/3/3 |
| 3 | 1/0/5/2 | 1/1/5/2 | 1/2/6/3 | 1/3/7/4 |
| 4 | **1 or 2** (50/50, `1+Random(2)`)/2/4/6 | F/3/4/6 | F/4/5/7 | F/5/6/8 |
| 5 | 3/5/7/5 | 3/6/7/5 | 3/7/8/6 | 3/8/9/7 |
| 6 | 4/10/12/**16?** | 4/11/12/16 | 4/12/13/17 | 4/13/14/18 |
| 7 (Custom) | slider values (0-20) | ? | ? | ? |

- **DISAGREEMENT (Night 2):** the Steam "Ultimate AI Breakdown" lists Night 2 as 3 AM 0/4/2/2 and 4 AM 0/5/3/3. That skips the 2 AM Bonnie bump, which contradicts the guide's own rule. The table above applies the rule.
- **DISAGREEMENT (Night 6 Foxy):** the port's AI_MECHANICS.md table says **6**, while the Steam guide (and common wiki tables [MEM]) say **16**. This doesn't affect this bot's targets.
- **Custom Night = internal night 7.** The slider values are copied into the AI counters and clamped to 0-20. [DUMP]
  - **Unconfirmed:** whether the hourly bumps apply on night 7. The port doc lists the bumps with no night exclusion but never says so explicitly.
  - At 20/20/20/20 it is irrelevant, because AI >= 20 always succeeds. The Steam guide says 4/20 stays 20/20/20/20 all night.

Sources:
- https://github.com/Sergey004/FNAF1-Recomp-proj
- https://technicalfnaf.fandom.com/wiki/Movement_Opportunities_(Fnaf_1)
- https://technicalfnaf.fandom.com/wiki/AI_Levels_(Fnaf_1)
- https://steamcommunity.com/sharedfiles/filedetails/?id=2995834654

---

## 2. Power

### Start value
- The game starts at **999 tenths (99.9%)** (group 176), so the display reads 99% at 12 AM. [DUMP]

### Usage
- **usage = 1 + cameraUp + leftDoorClosed + rightDoorClosed + leftLightOn + rightLightOn** (group 175). Each door, each light and the monitor adds **1 bar**. [DUMP]
  - The dump's sum is uncapped.
  - In practice the maximum is 4: only one light can be on at a time, and raising the monitor turns the lights off [MEM].
- **DISAGREEMENT:** one Steam guide says a closed door costs 2 blocks. The dump says 1.

### Drain
- **Every 1 s, power −= usage tenths** (group 177). That is **0.1% per bar per second**: [DUMP]

  | Usage | Time per 1% |
  |---|---|
  | 1 | 10 s |
  | 2 | 5 s |
  | 3 | 3.33 s |
  | 4 | 2.5 s |

- **DISAGREEMENT:** the common wiki figure for usage 1 is "1% every 9.6 s" [MEM]. Calibrate on the real game by timing the percentage display.

### Extra passive drain per night
Each night after Night 1 also removes **1 tenth** on a fixed interval: [DUMP]

| Night | Extra drain |
|---|---|
| 1 | none |
| 2 | every 6 s (1% per 60 s) |
| 3 | every 5 s |
| 4 | every 4 s |
| 5, 6 and Custom (night 7) | every 3 s (1% per 30 s) |

### Idle end-of-night power
With nothing used for the whole 540 s night: [DERIVED, using the dump formula]

| Night | Calculation | End power |
|---|---|---|
| 1 | 99.9 − 54.0 | **45.9%** |
| 2 | − 9.0 more | **36.9%** |
| 3 | − 10.8 more | **35.1%** |
| 4 | − 13.5 more | **32.4%** |
| 5 / 6 / Custom | − 18.0 more | **27.9%** |

**Every bar-second of extra usage costs 0.1%.** So on 4/20 the entire usage budget is **279 bar-seconds**: about 4.65 minutes of one extra bar across the night.

### Foxy door-bang penalty
- Drain per bang = **(10 + 50 × bangsSoFar) tenths** (group 324). [DUMP]
  - Per bang: **1%, 6%, 11%, 16%, 21%, …**
  - Cumulative: 1, 7, 18, 34, 55%.
- The counter only ever increments within a night. It does **not** reset after a bang. [DUMP]
- Agrees with the Steam "Ultimate fnaf 1 guide" ((5n−4)%). **DISAGREEMENT:** one guide lists 7% for the second bang.

### At 0%
Power clamps at 0, the power-out flag is set, and **all animatronic AI freezes** (`if (power.IsPowerOut()) return`) (groups 285/286). The doors open and Freddy appears at the **left** doorway [MEM]. The sequence (groups 342-345): [DUMP]

| Phase | What happens | Duration |
|---|---|---|
| 0 | Darkness | Each 5 s, 20% chance to advance; forced at 20 s. |
| 1 | Toreador March music box; Freddy's face flickers in the left door every 0.5 s | Each 5 s, 20% chance to advance; forced at 20 s. |
| 2 | Buzz | 20 ticks. |
| 3 | Pitch black | Each 2 s, 20% chance of the Freddy kill; forced at 20 s. |

- Survival after hitting 0% therefore ranges from **~12 s to ~60 s**. [DERIVED]
- **6 AM still saves you in any phase**, because the clock keeps running. [DUMP]
- The 4/20 world-record community tracks a "negative power" category, meaning wins after a blackout. [STEAM/YouTube]

Sources:
- https://raw.githubusercontent.com/Sergey004/FNAF1-Recomp-proj/HEAD/FNAF1-Recomp-proj/src/PowerSystem.cpp
- https://steamcommunity.com/sharedfiles/filedetails/?id=2215604361
- https://steamcommunity.com/sharedfiles/filedetails/?id=1777334418
- https://www.youtube.com/watch?v=YGAPCYGSyg8

---

## 3. Bonnie (left side)

### Room graph
Each step is a 50/50 coin flip at move time. [DUMP]

| From | Possible destinations |
|---|---|
| 1A Show Stage | 5 Backstage, 1B Dining Area |
| 5 Backstage | 1B, 2A West Hall |
| 1B Dining Area | 5, 2A |
| 2A West Hall | 3 Supply Closet, 2B W. Hall Corner |
| 2B W. Hall Corner | 3, **Left Door** |
| 3 Supply Closet | **Left Door**, 2A |

Minimum distances [DERIVED]:
- From 1A: **4 moves to reach the door** and a 5th move to enter. That is at least 19.9 s to the door and 24.9 s to entry.
- From 1B after a retreat: **3 moves to the door**, at least 14.9 s.

### Successful move while at the left door
- **Door open:** he enters the office.
- **Door closed:** he retreats to **1B Dining Area**.
- **Door mid-slide:** he waits, and the move resolves once the door settles.

### Entry rules
- Entry is **not gated on the monitor**: he can enter while the cameras are down. [DUMP]
- Arriving at the door and entering are separate successful moves, so there is always at least one full 4.97 s interval between them. **A left-light check at least every ~4.9 s therefore always catches him before he can enter.** [DERIVED]

### In the office
- The door and light buttons stop working and play an "error" buzz (groups 97/107). [DUMP][FW]
- **The kill renders only when the monitor is down after it has been up.** [DUMP]
  - If the monitor is up when he enters (or is raised later), it is **force-dropped ≤ 30 s later**, and the jumpscare follows.
  - The jumpscare lasts ≈ 0.65 s before the "died" screen.
- The wikis agree:
  - [TW]: "jumpscare the player the next time the camera is raised."
  - [FW]: he attacks when you stop viewing the camera, and forces the camera down if you stay on it too long.
- **Unconfirmed:** what happens if you never raise the monitor again. One forum anecdote reports surviving by sitting still for about 2 minutes.
  - Even so, Foxy can still arrive while you are pinned.
  - **Treat a Bonnie entry as a lost night unless 6 AM is very close.** The bot should then **not raise the monitor**.
- **Detecting an entry:** a door or light click that does not toggle, plus the error sound, means someone is inside.

Sources:
- https://raw.githubusercontent.com/Sergey004/FNAF1-Recomp-proj/HEAD/FNAF1-Recomp-proj/src/AnimatronicAI.cpp
- https://technicalfnaf.fandom.com/wiki/Bonnie_(Fnaf_1)
- https://freddy-fazbears-pizza.fandom.com/wiki/Jumpscares_(FNaF1)

---

## 4. Chica (right side)

### Room graph
[DUMP]

| From | Possible destinations |
|---|---|
| 1A | **1B only** |
| 1B | 7 Restrooms, 6 Kitchen |
| 6 Kitchen | 7, 4A East Hall |
| 7 Restrooms | 6, 4A |
| 4A | **1B**, 4B E. Hall Corner |
| 4B | 4A, **Right Door (window)** |

- CAM 6 is audio-only: she can be heard but not seen there (pots and pans). [MEM]
- Minimum distances [DERIVED]:
  - From 1A: **5 moves to the door** (24.9 s at AI 20).
  - From 4A after a retreat: **2 moves to the door** (≥ 9.96 s), and entry no sooner than 14.94 s.

### Successful move while at the right door
- **Door open:** she enters the office.
- **Door closed:** she retreats to **4A**.
- **Door mid-slide:** she waits.

### In the office
Office behavior, monitor rules and the force-drop are the same as Bonnie's (≤ 30 s). Entry is not gated on the monitor. [DUMP]

### Vision notes
- She is visible in the right window when the right light is on, including while the right door is closed. [MEM]
- Bonnie and Chica have alternate camera poses (`Random(2)+1`). [DUMP]

Source: https://raw.githubusercontent.com/Sergey004/FNAF1-Recomp-proj/HEAD/FNAF1-Recomp-proj/src/AnimatronicAI.cpp

---

## 5. Foxy (Pirate Cove, CAM 1C)

### Internal stages
[DUMP]

| Stage | Meaning |
|---|---|
| 0 | Curtains closed |
| 1 | Peeking |
| 2 | Leaning out |
| 3 | Cove empty ("IT'S ME" sign) |
| 4 | Running down 2A |
| 5 | At the left door |

The visual mapping of stages 0-2 is [MEM]. The port renders stage 3 as the empty cove.

### Advancing (stages 0→3)
- On each 5.01 s opportunity he advances one stage on a successful roll, but only if:
  - he is not running and not at the door,
  - his **tablet cooldown == 0**,
  - and you are not viewing 1C with the monitor up. [DUMP]

### How the cameras stall him
- While the monitor is up on **any** camera, the cooldown is re-armed every 0.1 s (group 329). [DUMP][TW]
- While the monitor is down, the cooldown decrements by 1 per tick (group 313).
- **Cooldown = 50 + Random(1000) ticks = 0.83 s to ~17.48 s** (mean ≈ 9.2 s). [DUMP][TW]
  - **DISAGREEMENT:** the folklore range "0.83-16.67 s" is wrong. Both [TW] and the dump give a 17.48 s maximum.
- After the cooldown expires, his next 5.01 s tick rolls. So the earliest advance after lowering the monitor is ~0.83 s; typically it takes 9-15 s. [DERIVED]

### Stage 3 (cove empty)
Two ways out:
- **Viewing CAM 2A** with the monitor up triggers the sprint immediately: stage 4, run animation (anim 51, 33 frames at 39 fps).
  - **Run time to the door: 100 ticks ≈ 1.67 s**, then stage 5. [DUMP]
  - The port fixed this trigger to 2A in v2.46. An older port note said the Cove.
- **Lurk timeout:** if unseen for **1500 ticks = 25 s**, he goes straight to stage 5 at the door. [DUMP] It is not known whether this timer pauses while the monitor is up.

### At the door (stage 5)
- He **waits while the monitor is up**, and resolves as soon as it is down: [DUMP]
  - **Left door open:** jumpscare.
  - **Left door closed:** bang plus the power drain from §2, then he returns to **stage 0 or 1 (50/50)**.
  - Door/bang audio: he bangs four times [FW].
- **Consequence for the bot:** you cannot click the doors with the monitor up. Close the left door **before** raising the monitor whenever Foxy might be at stage 3 or later. [DERIVED]

### Cheapest safe way to handle stage 3
[DERIVED]
1. Lower the monitor.
2. Close the left door.
3. Raise the monitor on **2A** to trigger the sprint.
4. Wait ~2 s.
5. Lower the monitor and let the bang resolve.
6. Open the door.

This costs about 0.5% of door and camera time plus the bang (1%, then 6%, …), versus about 2.5% for holding the door through the 25 s timeout. Prevention by regular camera flips is cheaper still, because bang costs escalate.

### Check cadence that guarantees catching stage 3 before the timeout
[DERIVED]
- If the last 1C check showed stage ≤ 2, the earliest stage 5 is about 25-26 s later.
- So **check 1C at least every ~20 s** whenever Foxy's AI > 0. Each check also re-arms the cooldown.

### Camera static
If an animatronic moves while its room is being watched, the feed static-outs for **300 ticks (~5 s)** (§9). The bot cannot read 1C during that time. [DUMP]

Sources:
- https://technicalfnaf.fandom.com/wiki/Foxy_(Fnaf_1)
- https://github.com/Sergey004/FNAF1-Recomp-proj
- https://steamcommunity.com/sharedfiles/filedetails/?id=2215604361

---

## 6. Freddy

### Rolling
- He rolls on a 3.02 s opportunity, **only when the monitor is down** and he is not in the office. [DUMP][TW] [TW]: "if you are using cameras, he will fail every movement."

### Post-roll countdown
- After a successful roll, a delay counter must reach **1000 − 100 × AI ticks** before he steps. [DUMP]

  | AI | Delay |
  |---|---|
  | 1 | 900 ticks = 15 s |
  | 2 | 800 ticks = 13.3 s |
  | 3 | 700 ticks = 11.7 s |
  | 4 | 600 ticks = 10 s |
  | ≥ 10 | instant |

- The counter only fires while the monitor is down.
- **Watching Freddy's current camera with the monitor up resets the counter to 0.** [DUMP] Per [TW], at AI 9 this stall amounts to 100 frames.

### Path and stage rule
- **Fixed path, no branching:** 1A → 1B → 7 → 6 → 4A → 4B → office. That is 6 steps to 4B. [DUMP]
- **He cannot leave 1A while Bonnie or Chica is still on stage.** [DUMP]
- CAM 6 Kitchen is audio-only. His music box is heard there [MEM].
- He laughs and plays footsteps when he moves [MEM].

### Office entry (4B → office)
- Requires all of the following: [DUMP]
  - he has a pending "go" (a roll plus the countdown completed while the monitor was down),
  - the **monitor is up**,
  - the viewed camera is **not 4B**,
  - and the **right door is open**.
- If the **right door is closed** in that situation, he retreats to **4A**, but only if the viewed camera is not 4A.
- **Watching 4B blocks his entry entirely**, and with the monitor down he cannot enter at all.
  - So **resting the camera on 4B** (the monitor reopens on the last viewed camera) makes raising the monitor safe.
  - Switching away from 4B while he is there and the right door is open lets him in.
- **Unverified port-only rule:** a code comment (v2.53) says the 4A → 4B step is blocked while the **right light is on**. AI_MECHANICS.md does not contain this rule.

### Freddy in the office
- On entry he **kills both lights** (groups 406, 408-412) and loops a whisper sound (group 405). He is not visible. [DUMP]
- **Kill roll:** while the monitor is down, once per second, `Random(4)==1` gives a **25%/s** chance of the jumpscare. [DUMP][FW]
  - Expected survival with the monitor down is about 4 s.
- **Port-only claims (flag):**
  - The roll accumulates only while the right door is **open**, and resets if the door closes or the monitor goes up.
  - The roll is blocked while Foxy is at stage ≥ 5.
  - The common wiki wording is just "25% per second while the cameras are down" [MEM]. The emergency fallback is to keep the monitor up until 6 AM.

Sources:
- https://raw.githubusercontent.com/Sergey004/FNAF1-Recomp-proj/HEAD/FNAF1-Recomp-proj/src/AnimatronicAI.cpp
- https://technicalfnaf.fandom.com/wiki/Movement_Opportunities_(Fnaf_1)

---

## 7. Golden Freddy and other random events that can confuse a vision bot

### Golden Freddy
- **Trigger:** a 1/100000 roll per second **while CAM 2B is viewed** swaps the 2B poster for Golden Freddy's (group 425). [DUMP]
- Lowering the monitor afterwards shows **Golden Freddy slumped in the office** (group 420).
- **Escape:** raise the monitor (group 423). If he stays visible for **300 ticks (~5 s)**, it is the "creepy end" (jumpscare, then the game closes).
- **Bot rule:** avoid 2B entirely; lights are enough for Bonnie. If the office shows Golden Freddy, raise the camera immediately.

### Custom Night code
- Entering **1/9/8/7** on Custom Night gives the Golden Freddy screen and closes the game. [DUMP][MEM] Never set those values.

### Camera static on movement
- A move while the room is being watched gives a **300-tick (~5 s) static-out** on that feed. [DUMP]

### Hallucinations
- Flashes of faces / "IT'S ME" and the poster changes. The port lists "33% per 5 s when the tablet is up at office entry". [DUMP] The exact semantics are unclear.

### Other noise
- Alternate animatronic poses on cameras (`Random(2)+1`). [DUMP]
- Kitchen sound re-rolls every 1 s while Chica or Freddy is in CAM 6. [DUMP]
- Cove "Golden Freddy photo" (random ≤ 10). [DUMP]
- The 1/10000-per-second "creepy end" roll only applies on the game-over screen. [DUMP]

Source: https://github.com/Sergey004/FNAF1-Recomp-proj (docs/AI_MECHANICS.md)

---

## 8. Strategies

### 8a. Community 4/20 (20/20/20/20) routines
[STEAM / forum]

- **The Mr.Buu-style rotation:** "light, camera, light, camera".
  - Flash one door light, flip the monitor briefly, flash the other light, flip again.
  - Close a door only when its animatronic is seen; reopen as soon as it leaves.
  - Reported as more power-efficient than checking the right door every time.
- **Start on CAM 4B.** Check both lights and close whichever door has an animatronic, then repeat (Steam 3087295888). Another loop is "check Pirate Cove, check both lights, close the right door, repeat" (IndieDB).
- **Foxy:** check Pirate Cove periodically, "around every 10-15% of power" (Steam 451401086). His speed varies run to run because of the cooldown RNG.
- **Freddy:** opinions differ:
  - close the right door before each camera check, or
  - close it after the 4th laugh, or
  - keep the 4B camera up to keep him from entering (Fandom blog).
  - The mechanics in §6 support "rest the camera on 4B".
- **Typical end power:** **~0-5%.** Wins at **2%** and "about 3%" are reported, and there is a "negative power" WR category. No verified "most power left" record was found.

### 8b. Derived bot routine for 4/20
[DERIVED from the mechanics above]

Budget: 279 bar-seconds (27.9%).

- **Always rest the monitor on 4B.** It shows Chica or Freddy in the corner, and any camera stalls Foxy. Never leave 4B while Freddy is in 4B and the right door is open.
- **Phase-lock to the timers.**
  - At AI 20, every Bonnie/Chica opportunity succeeds, so their positions change at fixed 4.97/4.98 s ticks.
  - Estimate the phase from observed transitions; re-estimate continuously, because Clickteam timers can drift with frame drops.
  - A door only needs to be **fully closed at the tick** when the animatronic at it would move.
  - A door closed just before the tick and opened right after the retreat costs about 1-2 s per visit (~0.15%).
- **One light flash per side per tick (~5 s).** At ~0.25 s per flash this costs about 0.025% each, roughly 2.7% per side per night.
- **Freddy:**
  - At AI 20 he steps on every monitor-down 3.02 s opportunity once Bonnie and Chica are off stage, reaching 4B after about 18 s of monitor-down time.
  - With the camera resting on 4B he can sit there harmlessly.
  - **Before a 1C check while Freddy is in 4B**, close the right door. Viewing 1C then sends him back to 4A.
- **Foxy:**
  - Brief monitor flips (the "camera" step of the rotation) keep re-arming the 0.83-17.48 s cooldown.
  - Peek at 1C at least every ~20 s.
  - On stage 3, use the close-door-then-view-2A trick (§5).

### 8c. Power-efficient zero-jumpscare play for Nights 1-5
[DERIVED unless tagged]

- **Night 1:**
  - **Do nothing from 12-2 AM**: all AI are 0 and Freddy is 0 all night.
  - Left-light checks are only needed from **2 AM + ~15 s**: Bonnie needs ≥ 4 moves from 1A.
  - Right-light checks and Foxy checks from **3 AM**.
  - Expect about 8 successful Bonnie moves all night (≈ 0.9 + 1.8 + 5.4 across the hours).
  - Foxy expects ~4.5 advance chances over 3-6 AM with no camera use, so he *can* reach stage 3. Do not skip 1C checks after 3 AM.
- **Night 2:** Bonnie 3→6 and Chica/Foxy 1→3 from the start. Freddy is 0.
- **Night 3:** Bonnie 0 until 2 AM, Chica 5→7, Foxy 2→4, Freddy 1.
  - Freddy averages ~75 s per step, so ~7.5 min to reach 4B. He rarely gets there, but keep the 4B rule.
- **Night 4:** Freddy 1-2, Bonnie 2→5, Chica 4→6, Foxy 6→8.
- **Night 5:** Freddy 3 (~32 s/step, so he will likely reach 4B), Bonnie 5→8, Chica 7→9, Foxy 5→7.
- **Light-check scheduling (guaranteed safe):**
  - Per side, flash the light at least once per ~4.9 s whenever that animatronic could be within one move of the door.
  - After a confirmed retreat you may skip:
    - the left side for ~14 s (Bonnie needs 3 moves from 1B),
    - the right side for ~9.9 s (Chica needs 2 moves from 4A).
- **Cameras:** use them only for Foxy (1C every ≤ 20 s once his AI > 0) and the 4B safety rule. One flip of ~1 s costs ~0.1%.
- **Theoretical ceilings:** roughly the idle values in §2 (45.9 / 36.9 / 35.1 / 32.4 / 27.9%) minus about 3-8% for checks and door time.
  - No sourced "top player end power" figures for Nights 1-5 were found. These are calculated targets only.

Sources:
- https://steamcommunity.com/app/319510/discussions/0/616189106663990524/
- https://steamcommunity.com/sharedfiles/filedetails/?id=451401086
- https://steamcommunity.com/sharedfiles/filedetails/?id=692188066
- https://steamcommunity.com/sharedfiles/filedetails/?id=3087295888
- https://www.indiedb.com/games/five-nights-at-freddys/tutorials/fnaf-420-mode
- https://freddy-fazbears-pizza.fandom.com/wiki/User_blog:Daoo21/New_4/20_strategy_found!_MUCH_EASIER!
- https://www.youtube.com/watch?v=YGAPCYGSyg8

Related: https://github.com/ArtyMend07/Fly-NAF is another AI agent that plays FNAF 1.

---

## 9. Controls, save file, Custom Night

### Controls
Gameplay is **mouse-only**. [MEM]
- Click the door and light buttons on each side wall. Lights toggle, only one light is on at a time, and raising the monitor turns lights off.
- Hover the **flip bar at the bottom of the screen** to raise or lower the monitor. The cursor must leave the bar and re-enter it to toggle again.
- Click the camera buttons on the map.
- The office view pans with the mouse x-position near the screen edges.
- Door and light buttons cannot be clicked while the monitor is up. [MEM]
- The monitor reopens on the last viewed camera, which defaults to 1A. [MEM]

### Keyboard cheat
- Holding **C + D + numpad "+"** during a night completes it instantly. [STEAM][GameFAQs] The main-row "+" reportedly does not work. Don't use it in bot runs.

### Save file
`%APPDATA%\MMFApplications\freddy` (INI, no extension), section `[freddy]`: [STEAM]

| Key | Meaning |
|---|---|
| `level=N` | Night 1-5 loaded by "Continue". Editing it skips ahead, but this doesn't work for nights 6/7. |
| `beatgame=1` | Star 1, **unlocks 6th Night**. |
| `beat6=1` | Star 2, **unlocks Custom Night**. |
| `beat7=1` | Star 3 (completed 20/20/20/20). One post says to leave it out to keep Custom Night playable; another says it works fine. |

Example unlock-all: `level=5`, `beatgame=1`, `beat6=1`. Back up the file first.

### Custom Night screen
- Four portraits with left and right arrow buttons per animatronic. Each click changes AI by 1, clamped 0-20. [DUMP][MEM]
- The default values on entry are commonly 1/3/3/1 [MEM, verify].
- Click "Ready" to start.
- Avoid 1/9/8/7.

Sources:
- https://steamcommunity.com/app/319510/discussions/0/35222218590999189?ctp=3
- https://steamcommunity.com/sharedfiles/filedetails?id=390206948
- https://gamefaqs.gamespot.com/pc/827431-five-nights-at-freddys/cheats
- https://steamcommunity.com/sharedfiles/filedetails/?id=1770625681

---

## 10. Open questions to verify empirically

1. **Hour length:** 90 s (dump) vs ~89 s (wiki). Time several nights from the first frame to 6 AM.
2. **Power drain at usage 1:** 10 s/% (dump) vs 9.6 s/% (wiki).
3. **Bonnie/Chica in the office with the monitor never raised:** is it safe until 6 AM? Is the ≤ 30 s force-drop only armed when the monitor is up?
4. **Foxy's 25 s lurk timer:** does it pause while the monitor is up? Is there any audio warning on the timeout path?
5. **Freddy:**
   - Does the right light block the 4A → 4B step?
   - Does closing the right door stop the in-office kill roll?
6. **Custom Night:** do the hourly bumps apply to sliders below 20?
7. **Animation timings:** monitor raise/lower and door slide durations. These are not in the sources found, and they matter for the "door must be settled at the tick" timing.
