# FNAF Automations - voiceover script

Video: `fnaf-bot-explainer.mp4` (1280x720, 6:22, no audio track).
Read at a relaxed pace (~150 words per minute). Each block starts at the
timestamp shown and should end before the next one; *[on screen]* notes
describe what the viewer is seeing. All game footage is the bot playing
the real game (recorded with OBS), except the staged demonstration at
2:34, which was played by `tools/demo_events.py` on purpose.

---

### 0:00 - Title (5 s)

> This is FNAF Automations: a Python program that plays Five Nights at
> Freddy's by itself, by looking at the screen and moving the mouse.

### 0:05 - The bot in action (9 s)

*[on screen: Night 3 starting; the panel at the top with the little clock]*

> Everything you see is done by the bot. The panel at the top is what it's
> thinking, and the clock is the night: the hour hand goes from twelve to
> six.

### 0:14 - 1. Seeing the game (10 s)

*[on screen: the office with Python code; a zoom into pixels]*

> Step one is seeing. The mss library grabs the game window sixty times a
> second, and NumPy turns each grab into an array. To OpenCV, the whole
> game is just numbers.

### 0:24 - 2. Reading the HUD (14 s)

*[on screen: the game's digit sprites sliding across the power readout]*

> To read the power and the clock there's no OCR at all. The bot takes the
> game's own digit pictures and slides each one across the screen with
> matchTemplate. Where a digit really is, the score jumps to one - a
> perfect match, every time.

### 0:38 - 3. Where the pictures come from (10 s)

*[on screen: 605 thumbnails filling the screen]*

> Those reference pictures come from the game itself: FNAF was made in
> Clickteam Fusion, and its exe hides a compressed image bank. A small
> Python reader pulls out all six hundred and five of them.

### 0:48 - 4. Which camera, and who is on it? (18 s)

*[on screen: the Pirate Cove label; the pan score; the red difference mask]*

> On the monitor, the room label says which camera this is. The picture
> slowly pans, so the bot slides the reference to find the alignment. Then
> the trick: it only compares the pixels where the possible answers
> actually differ - shown in red - after correcting for the static's
> brightness. That's how it tells which stage Foxy is at, and how sure it is.

### 1:06 - 5. The doorways (14 s)

*[on screen: live doorway next to "light off", "empty", "Bonnie"]*

> At the doors: a quick flash of the light, and the doorway is compared
> with three pictures - light off, empty, and Bonnie. "Light off" is its own
> answer, so a flicker can never be mistaken for an empty doorway. Lowest
> error wins. Here: Bonnie. Door.

### 1:20 - 6. The hidden rules (22 s)

*[on screen: hex bytes, the decryption key, then decoded rules]*

> Here's the part nobody tells you. The game's logic is stored as encrypted
> Clickteam events, and the key is built from the developer's own project
> path. Decrypted, the night is four hundred and thirty-five if-then rules.
> Bonnie may move every four point nine seven seconds. Power is charged
> once per second. After any click, clicks are ignored for ten frames. Any
> camera picture freezes Foxy. Freddy can only get in while you're looking
> at a camera other than 4B.

### 1:42 - 7. Planning between the ticks (18 s)

*[on screen: timeline of power ticks, movement ticks and the bot's actions]*

> Because every timer starts on the night's first frame, the bot knows when
> each animatronic can move, and checks right after. And since power is
> charged only on whole seconds, light checks and camera flips are squeezed
> in between those ticks - they cost nothing. Doors close just before a
> move and open right after.

### 2:00 - 8. A simulator to prove it (14 s)

*[on screen: counters and the power chart]*

> To trust it, the rules were re-written as a frame-accurate simulator, and
> the same brain played it thousands of times. Zero jumpscares, and the
> power left at six AM close to the best possible. Then came the real game.

### 2:14 - 9. The night the bot lied about (20 s)

*[on screen: the campaign log typing out: "Night 3 finished: SURVIVED",
then the menu crash]*

> After Night 3 the bot logged: survived, twenty percent power. Then it
> crashed, because the game refused to show the sixth night. The game knew
> something the bot didn't: Night 3 had been lost. Look at the last lines:
> the bot flicks the left light, and the light doesn't come on.

### 2:34 - The tell, staged on purpose (28 s)

*[on screen: a staged night - Bonnie at the open left door; the light
switch doing nothing; the jumpscare]*

> So I made it happen on purpose. This is a demo script, not the bot:
> Bonnie at the left door, and we leave the door open. He steps in - and
> now the light switch is dead. In the game's own code, that is the tell:
> when Bonnie is inside the office, the light is disabled. And the old bot's
> "survived" check was just a stopwatch: five hundred thirty-five seconds
> passed, so it must have won. Nobody looked at the screen.

### 3:02 - The numbers (10 s)

*[on screen: table of four nights, "HUD vanished after 538.8 s, 538.3 s,
538.5 s... and 533.1 s"]*

> In every logged night, six AM arrived three and a half seconds late. The
> game's "every one second" timer takes one point zero zero six five seconds.

### 3:12 - Two clocks (18 s)

*[on screen: two analog clocks diverging, the drift counter growing]*

> The bot counted real seconds, the game counts its own, slightly longer
> ones. By five AM the bot's clock was three and a half seconds ahead of
> Bonnie's timer: it closed the door for a move that hadn't happened yet,
> opened it again, and then the real move came.

### 3:30 - The fix (16 s)

*[on screen: the code: TICK_SECONDS, the line fit, six_am_visible]*

> The fix: measure the game's second instead of trusting it, refine it all
> night from the power readout - which changes exactly once per game
> second - and decide "survived" by looking for the six AM screen, not the
> stopwatch.

### 3:46 - Live, one minute into the replay (6 s)

*[on screen: "Clock fitted from 20 power changes: game second = 1.0056"]*

> Replayed with the new clock, the bot measured the game's second for
> itself within a minute.

### 3:52 - ...and lost again (14 s)

*[on screen: 5 AM, "6 AM in 80 s", Chica, static]*

> And at five AM, eighty seconds from the end: Chica. Lost again - for a
> completely different reason, and that's the point of keeping a log.

### 4:06 - Two deadlines 0.9 s apart (20 s)

*[on screen: the timeline of Bonnie's and Chica's ticks and the bot's
actions, "Chica walks in"]*

> Bonnie's and Chica's timers had landed nine tenths of a second apart. The
> scheduler put Bonnie's door click first and deferred Chica's light check
> behind it - but after the click it still had to turn, wait out the click
> cooldown, and switch the light on. A quarter of a second too late. Now a
> deferred check must fit between the click and its own deadline, or the
> door shuts early.

### 4:26 - Replay three (13 s)

*[on screen: Night 3 at 1 AM, Chica at the window, the door click, static]*

> Replay three lasted two minutes. Chica, door click, jumpscare - and the
> log showed nothing wrong. The game never saw the click: a twenty
> millisecond press can fall between two frames. Now it's held for three.

### 4:39 - The process, sixteen times faster (20 s)

*[on screen: time-lapse of the terminal, the logs, the tools being written]*

> Every one of these took the same loop: read the log, find the moment, go
> back to the decompiled rules, write a small measuring tool, run it on the
> real game, fix, replay. Measuring tools for frame rate, timer periods,
> tick phases, power use - all of them live in the repository now.

### 4:59 - Replay four: Bonnie at the door (12 s)

*[on screen: Bonnie at the left door, the door closing just in time]*

> Replay four. Bonnie at the door - the door closes just in time, and opens
> again right after his move, because every second a door stays shut costs
> a power charge.

### 5:11 - Replay four: six AM (14 s)

*[on screen: the overlay clock reaching 6 AM; the game's 6 AM screen]*

> And there it is: the game's own six AM screen, thirty-four percent power
> left. Night 3, finally, for real.

### 5:25 - Night 4: Foxy (14 s)

*[on screen: Night 4 at 2 AM, the game-over screen]*

> Night 4 was lost to Foxy through a door the bot was sure was safe. The
> code again: the monitor only counts as "viewing" once its flip animation
> has finished, and Foxy's lock is re-rolled only at the game's tenths of a
> second. The bot's quick flips were a hair too short.

### 5:39 - Night 4: both doors (16 s)

*[on screen: 4 AM, both doors opening and shutting every five seconds]*

> With Bonnie and Chica both at their doors, two planned clicks landed
> too close together once more; and a door or light click, it turned out,
> has to be a full fifteen frames after the previous one, not eleven. After
> that fix: not a single lost click in a whole night.

### 5:55 - Night 4, won (14 s)

*[on screen: 5 AM, the countdown, the 6 AM screen at 8 %]*

> Night 4, twelfth attempt of the day: six AM with eight percent left.

### 6:09 - Night 5, won (13 s)

*[on screen: Night 5's last seconds, 8 %, the 6 AM screen at 2 %]*

> Night 5: two percent at six AM, which is about as close as it gets. Every
> night from one to five, played by Python, NumPy and OpenCV's template
> matching - plus a little knowledge from inside the game's own code. The
> sixth night and four-twenty are the next chapter of the devlog. The code
> is on GitHub.
