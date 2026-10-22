# How the bot plays

This explains the decisions in `fnafbot/brain.py`. The rules it relies on
are in [GAME_LOGIC.md](GAME_LOGIC.md) (read from the game's code).

## Goals, in order

1. **Never get caught.** Every rule below is built so that a mistake in
   power-saving can never turn into a jumpscare.
2. **Finish with as much power as possible.** Idling alone uses 1 power unit
   per second; everything else should cost as close to nothing as possible.

## The clock

Every game timer starts at the night's first frame. The bot starts its own
clock on the first screenshot that shows the office HUD and then sharpens it:
power can only change on whole seconds, so every observed power change proves
the night began no later than "time seen − whole seconds". On the live game
the clock is accurate to about ±0.02 s.

With the clock the bot knows, for every second of the night:

* when Bonnie (every 4.97 s), Chica (4.98 s), Freddy (3.02 s) and Foxy
  (5.01 s) get their movement chances;
* when power is charged (every whole second).

## Saving power: act between power charges

Power is charged only at whole seconds, using whatever is switched on at
that instant. So a light flash or a camera flip that starts and ends between
two whole seconds is free. The bot plans each light check (~0.24 s) and each
camera view (~0.22 s) inside such a gap (`quiet_light_start`,
`_next_freeze_start`). On top of that, it simply never turns anything on
unless it is needed.

## Bonnie and Chica (the doors)

* They can only move on their ticks, and only one room per successful tick.
  The bot keeps a **lower bound on how many moves each one is from their
  door**: 4 for Bonnie and 5 for Chica at the start, minus one per tick.
* The light is only flashed when an arrival is actually possible (the bound
  has reached 0), **once between two of their ticks**, and early enough that
  the door can still be shut before their next tick (the door click has to
  wait 0.17 s for the game's click cooldown).
* The light is never on during one of Bonnie's or Chica's ticks, because an
  arrival or departure makes the game switch both lights off and would spoil
  the check.
* **Seen → the door closes immediately** (the door button sits right above
  the light button, so the cursor only moves a few pixels).
* After their next tick the bot reopens the door and looks again. A blocked
  move sends Bonnie back to the Dining Area (3 moves away) and Chica back to
  the East Hall (2 moves away). If they are still there (their move roll
  failed), the door closes again.
* If they left, the distance bound is reset to where they were sent back
  to, minus every tick they may have used since they were last seen.

## Foxy

Foxy can only advance when his "lock" timer is 0, and every 0.1 s that a
camera picture is showing the lock is re-rolled to at least 50 frames
(0.83 s). So one short camera flip that ends less than ~0.67 s before each of
Foxy's ticks keeps him at stage 0 for the whole night. Any camera works,
so the bot uses E. Hall Corner (4B) (see Freddy).

Every ~30 s, when it is safe, the bot glances at Pirate Cove to confirm.
If Foxy has somehow left (stage 3), the bot closes the left door (and the
right door, for Freddy), views West Hall to make him run immediately instead
of waiting up to 25 s, lets him bang once, and reopens.

## Freddy (any aggression level)

Freddy can only enter the office at a moment when the camera is up, showing
any camera **other than 4B**, and the right door is fully open. So:

* the camera always rests on 4B: every flip starts and ends on 4B;
* another camera (only ever Pirate Cove, rarely) is shown only when 4B has
  just been seen empty. Freddy cannot reach 4B while the camera stays up,
  so the rest of that camera session is safe;
* the Foxy emergency closes the right door before viewing West Hall.

This works the same at Freddy AI 1 and at 20, so "Freddy at full aggression"
needs no special power-hungry mode.

## Never viewed

* W. Hall Corner (2B): Golden Freddy can only appear after viewing 2B.
* Anything not needed: every extra view costs time and, at the wrong moment,
  power.

## Testing

`tools/simulate.py` plays the brain against `fnafbot/sim.py`, a frame-by-frame
re-implementation of the game's own event logic, with the same delays the real
bot has (0.55 s pans, 0.43 s camera flips, 0.17 s click cooldown).
