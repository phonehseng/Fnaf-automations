# FNAF 1 game logic, read from the game itself

This is how Five Nights at Freddy's 1 (Steam build, v1.132, Clickteam Fusion
2.5 build 284, **60 frames per second**) actually works, taken from the game's
own event code rather than from wikis or videos.

**How it was obtained.** The game data inside `FiveNightsatFreddys.exe` is a
Clickteam "PAMU" data pack. Its event chunks are compressed and encrypted
with Clickteam's standard RC4-style cipher (key derived from the editor file
name and app name). A small Python reader decrypted the night frame
(`Frame 1`, 435 event groups) and printed it as readable "IF ... THEN ..."
lines. Numbers like `[188]` below refer to those event groups. The bot never
reads the exe at runtime except to extract reference pictures (see
`fnafbot/assets.py`).

All times below are exact. "Every X s" timers count real time from the
moment the night starts, so tick *k* of an X-second timer happens at
`k * X` seconds (rounded up to the next frame).

---

## Time

* A second counter adds 1 every second; when it reaches 90 the hour advances
  and the counter restarts at 1 `[264]-[266]`. So 12 AM lasts 90 s and every
  other hour 89 s.
* At 6 AM the night is won `[303]`: about **535 s** (8 min 55 s) after the start.

## Power

* Power starts at **999** (tenths of a percent; the HUD shows `power / 10`,
  rounded down) `[176]`.
* **Once per second** (and only then) power drops by the current usage
  `[177]`.
* Usage = 1 + left door fully closed + right door fully closed + left light
  on + right light on + camera up `[175]`.
  * A door counts from the moment its closing animation *finishes* until its
    opening animation *finishes* `[167]-[170]`.
  * The camera counts while a camera picture is showing (not during the
    flip animation) `[143]-[144]`.
* **Consequence:** anything that is switched on and off again *between* two
  one-second ticks costs no power at all.
* Extra drain on later nights `[342]-[345]`: night 2 loses 1 (=0.1 %) every
  6 s, night 3 every 5 s, night 4 every 4 s, nights 5, 6 and 7 every 3 s.
* Best possible end-of-night power (idling the whole night):
  night 1 ≈ 46 %, 2 ≈ 37 %, 3 ≈ 35 %, 4 ≈ 33 %, 5-7 ≈ 28 %.

## Clicking doors and lights

* Every door or light click starts a **10-frame (0.167 s) cooldown** during
  which all door/light clicks are ignored `[95]-[109]`.
* Doors and lights only respond while the camera is down `[96]`, `[106]`.
* Doors have a closing and an opening animation; a door can only be
  re-clicked once its animation has finished `[89]-[105]`.
* Turning one light on turns the other off `[106]`, `[108]`.
* While a light is on, about 1 frame in 10 is drawn dark (flicker) `[119]`,
  `[122]`.
* Lights are switched off automatically when the camera is raised `[326]`
  and when Bonnie/Chica arrive at or leave a doorway `[226]`, `[227]`,
  `[259]`, `[260]`.

## How animatronics decide to move

A "movement opportunity" is a timer tick. At each tick the game draws a
number from 1 to 20; the move happens if that number is **≤ the AI level**
(AI 0 never moves, AI 20 always moves).

| Animatronic | Tick every | Extra condition |
|---|---|---|
| Bonnie | 4.97 s `[188]` | – |
| Chica | 4.98 s `[189]` | – |
| Freddy | 3.02 s `[190]` | only while the camera is **down** |
| Foxy | 5.01 s `[191]` | not while viewing Pirate Cove, and only when his lock timer is 0 |

Where to go is chosen with a coin flip that is re-drawn every second
`[201]`.

### Starting AI levels `[305]-[311]`

| Night | Freddy | Bonnie | Chica | Foxy |
|---|---|---|---|---|
| 1 | 0 | 0 | 0 | 0 |
| 2 | 0 | 3 | 1 | 1 |
| 3 | 1 | 0 | 5 | 2 |
| 4 | 1 or 2 (random) | 2 | 4 | 6 |
| 5 | 3 | 5 | 7 | 5 |
| 6 | 4 | 10 | 12 | 6 |
| 7 (custom) | as chosen | as chosen | as chosen | as chosen |

Hourly increases on **every** night, including custom night `[335]-[337]`:
2 AM Bonnie +1; 3 AM Bonnie, Chica, Foxy +1; 4 AM Bonnie, Chica, Foxy +1.

## Bonnie (left side) `[199]-[215]`

Route (each arrow is one successful move; "or" is the coin flip):

* Show Stage 1A → Backstage 5 **or** Dining 1B
* Backstage 5 → Dining 1B **or** West Hall 2A
* Dining 1B → Backstage 5 **or** West Hall 2A
* West Hall 2A → Supply Closet 3 **or** W. Hall Corner 2B
* W. Hall Corner 2B → Supply Closet 3 **or** LEFT DOOR
* Supply Closet 3 → LEFT DOOR **or** West Hall 2A
* LEFT DOOR, next successful move:
  * door **fully open** → he is in the office `[214]` (you die the next time
    you lower the camera, or after up to 30 s on camera);
  * door **fully closed** → he goes back to Dining 1B `[215]`;
  * door **mid-animation** → the move waits until the animation finishes,
    then applies one of the two rules above.

Minimum moves to the door: 1A 4, 1B 3, 5 3, 2A 2, 2B 1, 3 1.

## Chica (right side) `[232]-[244]`

* Show Stage 1A → Dining 1B
* Dining 1B → Restrooms 7 **or** Kitchen 6
* Kitchen 6 → Restrooms 7 **or** East Hall 4A
* Restrooms 7 → Kitchen 6 **or** East Hall 4A
* East Hall 4A → Dining 1B **or** E. Hall Corner 4B
* E. Hall Corner 4B → East Hall 4A **or** RIGHT DOOR
* RIGHT DOOR, next successful move: fully open → in the office `[243]`;
  fully closed → back to East Hall 4A `[244]`.

Minimum moves to the door: 1A 5, 1B 4, 6 3, 7 3, 4A 2, 4B 1.

## Foxy (Pirate Cove 1C) `[191]`, `[313]-[329]`

* Stages 0 (curtain closed) → 1 (peeking) → 2 (stepping out) → 3 (gone).
  Each successful tick adds one stage while below 3.
* **Lock:** while a camera picture is showing, every 0.1 s his lock is set
  to `50 + random(0..999)` frames (0.83 – 17.5 s) `[329]`. The lock counts
  down one per frame `[313]` and he cannot move until it reaches 0.
  So raising the camera (any camera) shortly before each of his ticks keeps
  him at stage 0 forever.
* Stage 3: after **1500 frames (25 s)** he attacks `[318]-[320]`. Viewing
  West Hall 2A while he is at stage 3 makes him run immediately; he arrives
  **100 frames (1.67 s)** later `[40]`, `[315]-[317]`.
* When he arrives the camera is forced down `[321]`. Then:
  * left door fully open → jumpscare `[323]`;
  * left door fully closed → he bangs on it and returns to stage 0 or 1.
    Each bang costs more power: 1 %, 6 %, 11 %, ... `[324]`.

## Freddy `[389]-[406]`

* Rolls only while the camera is down (every 3.02 s). A success arms a
  countdown of `1000 − 100 × AI` frames (instant at AI 10+) `[190]`,
  `[397]-[398]`. The countdown can only finish while the camera is down, and
  looking at his room on camera resets it `[401]`.
* Route: 1A (only once Bonnie **and** Chica have left the stage) → 1B →
  Restrooms 7 → Kitchen 6 → East Hall 4A → E. Hall Corner 4B. 4A → 4B only
  while the right light is off.
* From 4B he enters the office **only at a moment when the camera is up,
  showing any camera other than 4B, and the right door is fully open**
  `[394]`. If the right door is fully closed instead (and the camera is not
  on 4A/4B), he goes back to 4A `[395]`.
* Inside the office: every second the camera is down there is a 1 in 4
  chance he attacks `[406]`.
* **Consequence:** if the monitor always shows E. Hall Corner 4B when it
  comes up, and other cameras are only viewed when 4B is confirmed clear (or
  the right door is closed), Freddy can never get in, at any AI level.

## Camera disruption `[194]-[198]`

If Bonnie or Chica moves while you are watching the camera of the room they
are in, that camera's picture is blanked for 300 frames (5 s).

## Golden Freddy `[41]-[44]`, `[420]-[425]`

Once per second there is a 1 in 100,000 chance a poster appears on W. Hall
Corner 2B. Only *after viewing 2B with that poster* can Golden Freddy appear
in the office (raising the camera within 5 s makes him leave). The bot never
views camera 2B, so he cannot appear.

## Power outage `[286]-[302]`

At 0 % the doors open, lights and cameras stop working, and after a random
music-box sequence Freddy attacks unless 6 AM arrives first.

## Menu and save file (`%APPDATA%\MMFApplications\freddy`)

* `level=N` – the night "Continue" starts (1-5).
* `beatgame=1` unlocks 6th Night; `beat6=1` (with `beatgame=1`) unlocks
  Custom Night; `beat7=1` is the third star.
* Custom Night: click the right/left arrow next to each animatronic
  (0-20 each), then the Ready button. Setting exactly Freddy 1, Bonnie 9,
  Chica 8, Foxy 7 triggers an easter egg instead of the night.
