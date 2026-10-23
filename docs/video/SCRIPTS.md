# Video scripts

Generated from `video/lecture/productions.json` - the narration as recorded (Piper TTS, `en_GB-alan-medium`) and shown on screen as subtitles. Each numbered line is one animated scene (`DRAW.<name>` in `video/lecture/night_shift_lecture.html`).

## Long form (16:9)  (`long`, landscape)

**1. title**

> 5:49 AM, in-game. Freddy, Bonnie, Chica and Foxy are all set to 20, the hardest the game allows.
> The battery reads 11%. And nobody is touching the mouse.
> This is a Python program playing Five Nights at Freddy's by itself. It watches the screen with OpenCV and moves the mouse.
> Tonight's lecture: how it works, why the first attempt failed, and the twenty-eight nights it took to win.

**2. budget**

> Custom Night at 20/20/20/20 is the game's hardest setting. Every animatronic moves at every chance it gets.
> The battery holds 999 units, and the night lasts 535 seconds.
> The game itself takes one unit a second, plus one every three seconds: 71% of the battery, gone before you touch anything.
> Everything you do, every door, every light, every look at the cameras, has to fit in the remaining 29%.
> And power is charged once a second, for whatever is on at that instant. Remember that.

**3. first**

> November 2023. The first commit of this repository: 230 lines of PyAutoGUI.
> Look closely: three fatal design decisions.
> First: pyautogui.PAUSE = 1. Every mouse call sleeps one full second afterwards.
> In this game an animatronic gets a movement opportunity every 4.97 seconds.
> A bot that spends a second per gesture has lost the race before it starts.
> Second: it is open-loop. Light, door, cameras, light, door, and the script ends.
> It never asks what the light showed.
> Third: its only sense was one template match, at a confidence of 0.6: am I looking at the cameras?
> No power, no clock, no animatronics. A blindfolded night guard with a metronome.
> The README later said it plainly: sadly not complete.

**4. map**

> Before we can fight the animatronics, we must understand them. Here is the pizzeria from above.
> Bonnie takes the west side: the backstage, the west hall and the supply closet, to the left door.
> Chica takes the east side: the restrooms, the kitchen and the east hall, to the right door.
> Freddy follows Chica's side, slowly. And Foxy waits in Pirate Cove, behind a curtain.

**5. ai**

> The game was built in Clickteam Fusion: its logic is a list of event rows.
> Reverse-engineering an offline copy of the game gives us the rules exactly.
> Bonnie's row reads: every 4.97 seconds, if a random number from 1 to 20 is at most Bonnie's AI level, set the counter "move who?" to 1.
> Chica's row is the same, at 4.98 seconds, and sets it to 2.
> At level 20 the die always succeeds: Bonnie and Chica move at every opportunity. Perfectly predictable, if you know exactly when it comes.
> And there is only one move-who slot. While a door slides, the move waits.

**6. doorway**

> Nights are lost at the doors. Bonnie and Chica walk up to a doorway on one of their ticks, and stand there.
> On their next tick, if the door is open, they step into the office. Game over.
> So after every tick at which they could have arrived, the bot flashes the hall light and looks.
> If someone is there, the door shuts just before their next tick, they are sent back, and it opens again at once: a shut door costs power every second.
> And a trick: the game switches the hall lights off on the exact frame an animatronic moves. A light left on across a tick is a stopwatch.

**7. freddy**

> Freddy is slow, and patient. He waits on camera 4B, the corner right outside the right door.
> He comes in only through an open right door, and only while the camera shows something other than 4B.
> So every camera flip the bot makes rests on 4B, staring him down. And if 4B is not clear, the right door is shut before it looks anywhere else.

**8. foxy**

> Foxy is different. His opportunity comes every 5.01 seconds, but only once a lock counter has run out.
> While any camera is up, the game re-rolls that lock ten times a second. A well-timed camera flip freezes him.
> But his row checks that the camera is not on Pirate Cove before its timer, and Clickteam only advances a timer it evaluates.
> Looking at Foxy pauses his clock. Measured live: hold the cove for 2.56 s, and his ticks move 2.54 s later.
> At stage 3 he runs. Shut the left door in time and he bangs on it: 1% of the battery, then 6%, then 11%.

**9. senses**

> Now the machine. Sixty times a second it grabs the window, and to OpenCV the game is an array of numbers.
> Power and clock are read with cv2.matchTemplate against the game's own digit sprites. No OCR.
> A white mask keeps the left door's hazard stripes out of the digits; they once made 50% look like 5.
> Doorways are compared with the game's own lit-and-empty pictures. On the monitor, the room label names the camera, and the cove is graded stage by stage.
> And it never reads the game's memory or files while it plays. Everything it knows, it sees, like a player would.

**10. match**

> Here is how it reads the power, slowed right down.
> The game's own ten digit pictures slide across the readout, and OpenCV scores each one at every position.
> Where a digit really is, the score jumps to 1: a perfect match, every time.
> And only white pixels count, so the yellow hazard stripes behind the left door can never pass for a digit again.

**11. plan**

> The brain is a scheduler. Power is charged once a second, so a light flashed between two charges is free.
> A door is shut just in time, half a second before an animatronic's tick, and opened the moment it is sent back.
> Each Foxy flip is placed so the picture covers one of the game's tenth-of-a-second re-lock instants, just before his tick.
> When jobs collide, the bot tries every order of them and keeps the one that makes nothing late.
> Every rule was proven first in a frame-accurate simulator of the event rows.

**12. sim**

> None of this was tried on the real game first.
> The simulator replays the event rows sixty times a second: the same timers, dice and power rules.
> Sixty nights run in a few minutes, and every change is measured: ticks left uncovered, Foxy alerts, power left at 6 AM.
> But a simulator is a model. When the live game disagreed, the live game won, and the change was reverted.

**13. hurdles**

> Theory is cheap. Custom Night took 28 live attempts to win, and every loss was investigated on the recording.
> The timers fall behind: under load they lag real time by up to a second, so ticks were timed from the hall lights.
> The clock drifted. The bot assumed a game second lasts 1.0065 real seconds. The recording, read frame by frame, said exactly 1.000.
> Its calibration window was too narrow to notice. By 6 AM, its idea of between two charges was 3.5 seconds off.
> The start was late. Spotting the first frame of the night took up to 0.4 seconds: enough for Bonnie to walk in at 30 seconds.
> Now the first minute of power changes pins the true start, with a Theil-Sen fit that one bad sample cannot drag.
> And once, two copies of the bot ran at the same time, fighting over one mouse. Those nights were struck off, and the bot now refuses to start twice.

**14. attempts**

> Every live night was logged, and every loss was investigated.
> Bonnie, Chica, Foxy, Freddy, or an empty battery: each loss had a cause, and each cause got a fix.
> Attempt 25 was the first win, with 0% left.
> Attempt 28, after the clock fix, won with 11%.

**15. results**

> Since then, of ten clean live nights, seven reached 6 AM.
> The margins are still thin. The next job is already in the log: Foxy, who still costs too much power.

**16. closing**

> The first bot pressed buttons in the dark. The second watches, measures and plans, and when it is wrong, it records why.
> That is the real difference between the two: not the code, but the method.
> Class dismissed. Mind the left door.

## Lecture (9:16)  (`lecture_v`, vertical)

**1. title**

> 5:49 AM, in-game. Every animatronic is set to 20, the maximum.
> The battery reads 11%. And nobody is touching the mouse.
> Good evening. Tonight's lecture is about a machine that learned to work the night shift at Freddy Fazbear's Pizza.
> And about the first machine that didn't.

**2. first**

> November 2023. The first commit of this repository: 230 lines of PyAutoGUI.
> Look closely and you will see three fatal design decisions.
> First: pyautogui.PAUSE = 1. Every mouse call sleeps one full second afterwards.
> In this game an animatronic gets a movement opportunity every 4.97 seconds.
> A bot that spends a second per gesture has lost the race before it starts.
> Second: it is open-loop. Light, door, cameras, light, door, and then the script simply ends.
> It never asks what the light showed.
> Third: its only sense was one template match at a confidence of 0.6, answering one question: am I looking at the cameras?
> No power, no clock, no animatronics. A blindfolded night guard with a metronome.
> The README later said it plainly: sadly not complete.

**3. map**

> Before we can fight the animatronics, we must understand them. Here is the pizzeria from above.
> Bonnie takes the west side: the backstage, the west hall and the supply closet, to the left door.
> Chica takes the east side: the restrooms, the kitchen and the east hall, to the right door.
> Freddy follows Chica's side, slowly. And Foxy waits in Pirate Cove, behind a curtain.

**4. ai**

> The game was built in Clickteam Fusion, and its logic is a list of event rows.
> Reverse-engineering an offline copy of the game gives us the rules exactly.
> Bonnie's row reads: every 4.97 seconds, if a random number from 1 to 20 is at most Bonnie's AI level, set the counter "move who?" to 1.
> Chica's row is the same, at 4.98 seconds, and sets it to 2.
> At level 20 the die always succeeds. On Custom Night, Bonnie and Chica move at every opportunity: perfectly predictable, if you know exactly when it comes.
> And there is only one move-who slot. A door must be fully open or fully shut for the doorway rule to fire; while it slides, the move waits.

**5. foxy**

> Foxy is different. His opportunity comes every 5.01 seconds, but only once a lock counter has run out.
> While any camera is up, the game re-rolls that lock to 50 + Random(1000) frames, ten times a second. A well-timed camera flip freezes him.
> But his row checks that the camera is not on Pirate Cove before its timer, and Clickteam only advances a timer it evaluates.
> Looking at Foxy pauses his clock. Measured live: hold the cove for 2.56 s, and his ticks move 2.54 s later.
> At stage 3 he runs. Shut the left door in time and he bangs on it: 1% of the battery, then 6%, then 11%.

**6. senses**

> Now the machine. Sixty times a second it grabs the window with mss, and to OpenCV the game is an array of numbers.
> Power and clock are read with cv2.matchTemplate against the game's own digit sprites. No OCR.
> A white mask keeps the left door's hazard stripes out of the digits; they once made 50% look like 5.
> Doorways are compared with the game's own lit-and-empty pictures, only where an animatronic would stand. On the monitor, the room label names the camera, and the cove is graded stage by stage.
> And it never reads the game's memory or files while it plays. Everything it knows, it sees, like a player would.

**7. plan**

> The brain is a scheduler. Power is charged once per second, for whatever is switched on at that instant, so a light flashed between two charges is free.
> A door is shut just in time, half a second before the tick at which an animatronic would step in, and opened again the moment it is sent back.
> Each Foxy flip is placed so the picture covers one of the game's tenth-of-a-second re-lock instants, just before his tick.
> When jobs collide, the bot tries every order of them and keeps the one that makes nothing late.
> Every rule was proven first in a frame-accurate simulator of the event rows, thousands of nights at a time.

**8. hurdles**

> Theory is cheap. Custom Night took 28 live attempts before it was won, and every loss was investigated on the recording.
> The timers fall behind. Under load, the game's timers lag real time by up to a second, so ticks were measured from the hall lights, which switch off on the exact frame an animatronic moves.
> The clock drifted. The bot assumed a game second lasts 1.0065 real seconds. The recording, read frame by frame, said exactly 1.000.
> Its calibration window was too narrow to ever notice. By 6 AM, its idea of between two charges was 3.5 seconds wrong.
> The start was late. Spotting the first frame of the night took up to 0.4 seconds: enough for Bonnie to walk in at 30 seconds.
> Now the first minute of power changes pins the true start, with a Theil-Sen fit that one bad sample cannot drag.
> And once, two copies of the bot ran at the same time, fighting over one mouse. Those nights were struck from the record, and the bot now refuses to start twice.

**9. results**

> With the clock fixed, the same night ends with 11% instead of 0%.
> Of the ten clean live nights since, seven reached 6 AM. The margins are still thin, and every loss is written down in the development log, with its cause.

**10. closing**

> The first bot pressed buttons in the dark. The second one watches, measures and plans, and when it is wrong, it records why.
> That is the real difference between the two: not the code, but the method.
> Class dismissed. Mind the left door.

## Short: What if  (`short_whatif`, vertical)

**1. clip** - A BOT PLAYED FNAF ON MAX?

> What if a bot played Five Nights at Freddy's on the hardest setting, with nobody touching the mouse? This is it, reaching 6 AM.

**2. cams** - FOUR AT MAX

> Four animatronics, all at level 20. Bonnie and Chica move at every chance, Freddy waits for you to look away, and Foxy runs.

**3. budget (split)** - THE POWER

> Worse, the game itself drains 71% of the battery. Every door, light and camera has to fit in the last 29%.

**4. night** - IT WATCHES

> The bot reads the screen with OpenCV sixty times a second, shutting each door just in time and opening it again the moment it's safe.

**5. attempts (count)** - 28 ATTEMPTS

> It lost its first twenty-four nights. Every loss was recorded, explained, and fixed, until attempt twenty-five reached 6 AM.

**6. results** - SIX AM

> Now it wins seven nights out of ten, often with power to spare.

**7. recap** - YES. IT CAN.

> So yes. A bot can survive the hardest night in Five Nights at Freddy's, by watching the screen and spending power smarter than the animatronics can drain it.

## Short: Foxy  (`short_foxy`, vertical)

**1. clip** - THE FOX THAT RUNS

> This is Foxy, sprinting down the West Hall toward your left door. Yet he's the one animatronic that freezes when you watch him.

**2. cams** - FOUR STAGES

> He hides in Pirate Cove. Every 5.01 seconds he can move one stage further out, and at stage three he's gone.

**3. lock** - A LOCK ON HIM

> But he can only move once a lock counter runs out. While any camera is up, the game re-rolls that lock ten times a second, so a well-timed camera flip keeps him frozen.

**4. pause** - WATCHING PAUSES HIM

> And looking straight at Pirate Cove pauses his clock completely. Measured live: hold the cove for 2.56 seconds, and his next move comes 2.54 seconds later.

**5. foxyoffice** - BANG. BANG. BANG.

> When he does run, a shut left door stops him. But every bang costs power: 1% of your battery, then 6%, then 11%.

**6. flips** - ALWAYS ON TIME

> So the bot flips the camera just before every one of his ticks, keeping him locked behind the curtain all night.

**7. recap** - FREEZE THE FOX

> That's Foxy. Keep him locked with the camera, and he never gets the chance to run.

## Short: First bot  (`short_first`, vertical)

**1. code** - MY FIRST FNAF BOT

> In 2023 I wrote a bot to beat Five Nights at Freddy's. It never survived a single night. Here's exactly why.

**2. code** - A SECOND PER CLICK

> Flaw one: every mouse action had a one-second pause built in, and the animatronics get a move every 4.97 seconds.

**3. blind** - IT NEVER LOOKED

> Flaw two: it ran a fixed list, light, door, camera, light, door, and then stopped. It never checked what the light showed, so Bonnie just walked in.

**4. code** - ONE FUZZY MATCH

> Flaw three: its only sense was one fuzzy image match, asking: am I looking at the cameras? No power, no clock, no animatronics.

**5. clip** - LOOK, THEN ACT

> The new bot looks at the screen sixty times a second, times every move to the frame, and reaches 6 AM on the hardest setting.

**6. recap** - LOOK BEFORE YOU ACT

> Same game, same mouse. The difference wasn't speed. It was looking before acting.

## Short: How it sees  (`short_sees`, vertical)

**1. clip** - THE BOT'S VIEW

> This is what a bot sees when it plays Five Nights at Freddy's: sixty screenshots a second, read with OpenCV.

**2. match (slide)** - TEMPLATE MATCHING

> To read the power, the game's own digit pictures slide across the screen. Where one fits exactly, the match score jumps to one.

**3. match (mask)** - THE HAZARD STRIPES

> Only pure white pixels count. Without that, the yellow hazard stripes on the left door once made 50% read as 5.

**4. clip** - BONNIE DETECTED

> Each doorway is compared with the game's own picture of an empty, lit hallway. Anything different is an animatronic, and the door shuts.

**5. cams** - WHO IS WHERE

> On the monitor, the room name tells it which camera it's on, and each picture is graded: how far out Foxy is, and whether Freddy is at the door.

**6. recap** - IT SEES WHAT YOU SEE

> No memory reading, no game files. It sees exactly what you see, and that's enough to survive the night.

## Short: Freddy  (`short_freddy`, vertical)

**1. clip** - THOSE TWO DOTS ARE FREDDY

> Those two dots are Freddy, staring into the corner camera. Look away now, and he walks right in.

**2. cams** - THE SHOW STAGE

> He starts on the show stage, and he won't leave it until Bonnie and Chica have both gone.

**3. route** - THE EAST SIDE

> Then he takes the east side: the dining area, the restrooms, the kitchen, the east hall, and the corner outside your right door.

**4. cams** - ON THE CAMERAS

> On camera he's barely there, just two eyes glinting in the dark. The kitchen camera has no picture at all, only sound.

**5. roll** - A DICE ROLL

> Every 3.02 seconds he rolls a twenty-sided die. A success starts a countdown of 1000 minus 100 times his AI level, in frames. At level 20, that's zero.

**6. slowpath** - WATCHING SLOWS HIM DOWN

> And he only moves while your monitor is down. Every tick that lands while you're watching is a tick he can't use, so keeping your eyes on him slows him down the whole way to 4B.

**7. sneak** - LOOK AWAY, AND HE'S IN

> At the corner, he walks in only if your right door is open while your camera shows anything but him. Check Pirate Cove a second too long, and he's in the office.

**8. guardwatch** - STARE HIM DOWN

> So the bot ends every camera flip on 4B. While it's watching him, he can't come in, and the right door stays open, costing no power.

**9. recap** - KEEP YOUR EYES ON 4B

> That's all of Freddy. He moves only when you're not looking, and gets in only when you look away from him. Keep your eyes on 4B, and he never will.

## Short: Human vs robot  (`short_versus`, vertical)

**1. versus (intro)** - HUMAN VS ROBOT

> Same night, every animatronic at maximum. On the left, a human guard who doesn't know the rules. On the right, a robot that knows every one of them.

**2. versus (power)** - THE BATTERY

> The human shuts a door the moment anything moves and leaves the lights on to feel safe, and every second of that costs power. The robot shuts each door just before an animatronic's move, and flashes the lights between the game's once-a-second power charges, for free.

**3. versus (freddy)** - FREDDY

> The human checks Pirate Cove with the right door open, and Freddy walks right in. The robot knows Freddy's rule, and ends every camera flip on 4B.

**4. versus (timing)** - REACTION TIME

> A person reacts. The robot's clicks land on the exact frame they were planned for, sixty frames a second, timed to the game's own clock.

**5. versus (foxy)** - FOXY

> The human forgets about Foxy until he's already running. The robot flips the camera just before each of his moves, so he never leaves the curtain.

**6. versus (result)** - LIGHTS OUT VS 6 AM

> The human's battery dies at 4 AM, and Freddy comes for them in the dark. The robot reaches 6 AM, with power left.

**7. recap** - KNOWLEDGE, NOT LUCK

> It isn't flawless: the robot still loses about three nights in ten. But it wastes no power, knows every rule, and never misses a frame. That's the whole difference.
