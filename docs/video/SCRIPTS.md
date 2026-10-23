# Video scripts

Generated from `video/lecture/productions.json` - the narration as recorded (Piper TTS, `en_GB-alan-medium`) and shown on screen as subtitles. Each heading is one animated scene (`DRAW.<name>` in `video/lecture/night_shift_lecture.html`).

## Long form (16:9)  (`long`)

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

## Lecture (9:16)  (`lecture_v`)

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

## Short: What if  (`short_whatif`)

**1. title**

> What if a bot played Five Nights at Freddy's on the hardest setting?
> Every animatronic at 20. Nobody touching the mouse.
> It watches the screen with OpenCV and plans every second of the night.

**2. map**

> Bonnie and Chica walk to the doors on a timer.
> Bonnie comes down the west side.
> Chica comes down the east side.
> Freddy waits, and Foxy hides in Pirate Cove.

**3. results**

> It took 28 attempts to win a single night.
> Now it wins seven nights in ten. Follow for how it works.

## Short: Foxy  (`short_foxy`)

**1. foxy**

> Why does watching Foxy keep him still?
> While any camera is up, the game re-rolls his lock, ten times a second. A camera flip at the right moment freezes him.
> But his code checks that you're not looking at Pirate Cove before his timer runs.
> So looking at him pauses his clock. Hold the cove 2.56 seconds, and he moves 2.54 seconds later.
> At stage 3 he runs. Shut the left door, and he bangs on it: 1%, then 6%, then 11% of your battery.

## Short: First bot  (`short_first`)

**1. first**

> My first FNAF bot, in 2023.
> It had three fatal flaws.
> pyautogui.PAUSE = 1: a full second after every click.
> The animatronics move every 4.97 seconds.
> It was always too slow.
> It was open-loop: light, door, cameras, and the script just ends.
> It never checked what the light showed.
> It could see one thing: am I on the cameras?
> A blindfolded night guard with a metronome.
> The new one watches, measures and plans. Part two next.

## Short: How it sees  (`short_sees`)

**1. senses**

> How does a bot see Five Nights at Freddy's?
> Sixty screenshots a second, read with OpenCV's matchTemplate. No OCR.
> A white mask stops the door's hazard stripes from turning 50% into 5%.
> Doorways are checked against the game's own empty-hallway pictures.
> And it never reads the game's files. Only the screen, like you.

**2. match**

> Here's the trick, slowed down.
> Each of the game's ten digit pictures slides across the power readout.
> Where a digit really is, the score hits 1.
> Only white pixels count. Follow for the rest.
