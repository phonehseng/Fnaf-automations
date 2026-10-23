# FNAF Automations

A bot that plays **Five Nights at Freddy's 1** (Steam, PC) by itself: it watches
the screen with OpenCV, clicks doors, lights and cameras with the mouse, and
aims to finish every night **without a single jumpscare and with as much
power left as possible**. It plays nights 1-6 and Custom Night (including
20/20/20/20).

The general approach (screen capture, resolution-independent coordinates,
reading the game's text, a kill hotkey) is loosely modelled on
[BTD6bot](https://github.com/j-miet/BTD6bot).

## How it works, in one paragraph

FNAF 1 is completely driven by timers that start the moment a night begins:
Bonnie may move every 4.97 s, Chica every 4.98 s, Freddy every 3.02 s, Foxy
every 5.01 s, and power is charged once per second. These rules were read
directly out of the game's code (see [docs/GAME_LOGIC.md](docs/GAME_LOGIC.md)).
The bot keeps a precise clock of the night, so it knows exactly when each
animatronic *can* have moved. It looks only when something could have
changed, closes a door the instant Bonnie or Chica is seen, keeps Foxy frozen
in Pirate Cove with well-timed camera flips, and keeps the camera resting on
the one view from which Freddy cannot get in. Lights and camera flips are
timed between the once-per-second power charges, so most checks cost no
power at all. Details: [docs/STRATEGY.md](docs/STRATEGY.md).

## Requirements

* Windows 10/11
* Five Nights at Freddy's (Steam version 1.132) installed. If it is not in the
  default Steam folder, set the `FNAF_EXE` environment variable to the full
  path of `FiveNightsatFreddys.exe`.
* Python 3.12+

```bash
pip install -r requirements.txt
```

## Fair play

The bot plays the way a person does: **during a night it only looks at the
screen and moves the mouse.** It never reads or changes the game's save file,
memory or any other game file, and it reaches nights only through the game's
own menus (so 6th Night and Custom Night must be unlocked by actually winning
the earlier nights). `tests/test_fair_play.py` checks the code for this.

Two things were learned from the game beforehand, the way a player would
study a strategy guide: the rules (timers, routes, AI levels - see
[docs/GAME_LOGIC.md](docs/GAME_LOGIC.md)) and the reference pictures the
vision compares the screen against (copied once from your installed game by
the setup step below, never during play).

## Running

One-time setup (copies the reference pictures out of your installed game):

```bash
python -m fnafbot --setup
```

Then, for example:

```bash
python -m fnafbot --campaign
```

| Option | What it plays |
|---|---|
| `--new-game` | New Game: Night 1, then each next night until Night 5 is won |
| `--continue` | Continue from the night the game has saved |
| `--sixth` | 6th Night (once the game has unlocked it) |
| `--custom 20 20 20 20` | Custom Night with these AI levels (Freddy, Bonnie, Chica, Foxy), once unlocked |
| `--campaign` | New Game, nights 1-5, then 6th Night, then Custom Night 20/20/20/20 |
| `--nights N` | Stop after N nights |

* The bot starts the game if it is not running and follows the game's own
  screens: after a won night the game goes on to the next night by itself.
* A small status panel at the top of the screen shows what the bot is doing
  ("Looking for Bonnie", "Camera flip to hold Foxy", ...).
* **Press F8 to stop the bot at any time.**
* Every run writes a log to `logs/`, and a small picture of every doorway
  decision to `logs/doorway/`. If a night is ever lost, the bot stops and
  saves a screenshot next to the log.

Do not use the mouse while the bot is playing - it needs the cursor.

## Testing without the game (simulator)

The brain can play thousands of simulated nights in minutes. The simulator
re-implements the game's own logic frame by frame:

```bash
python tools/simulate.py --night 5 --runs 500
```

```bash
python tools/simulate.py --custom 20 20 20 20 --runs 500
```

If a simulated night is ever lost, `tools/debug_loss.py` prints the game's
events and the brain's actions leading up to it.

Unit tests (vision on the game's own pictures, plus sanity checks):

```bash
python -m pytest tests
```

## Project layout

| Path | What it is |
|---|---|
| `fnafbot/config.py` | Paths and settings (game location, stop key) |
| `fnafbot/rules.py` | The game's rules as numbers (timers, AI levels, routes) |
| `fnafbot/layout.py` | Every screen position and measured animation timing |
| `fnafbot/assets.py` | Extracts reference pictures from your copy of the game |
| `fnafbot/catalog.py` | Labels for those pictures (who is on which camera) |
| `fnafbot/screen.py` | Finds the game window and takes screenshots |
| `fnafbot/mouse.py` | Fast, direct mouse input |
| `fnafbot/vision.py` | Reads the HUD, cameras and doorways from screenshots |
| `fnafbot/controller.py` | Low-level actions: pan, lights, doors, cameras |
| `fnafbot/body.py` | Connects the brain to the real game, keeps the night clock |
| `fnafbot/brain.py` | The strategy: what to check and when |
| `fnafbot/sim.py` | Frame-accurate simulator of a night (for testing the brain) |
| `fnafbot/menu.py` | Starting the game and choosing a night |
| `fnafbot/overlay.py` | The on-screen status panel with the analog night clock |
| `fnafbot/__main__.py` | Command-line entry point |
| `tools/` | Simulator runner, loss debugger, calibration helpers, `demo_events.py` (stages events for recordings) |
| `tests/` | Automated tests |
| `docs/GAME_LOGIC.md` | The game's real rules, read from its code |
| `docs/STRATEGY.md` | How the bot uses those rules |
| `docs/DEVLOG.md` | Bugs found on the live game and how they were fixed |

## Live results (2026-10-22)

| Night | Result on the real game | Power left |
|---|---|---|
| 1 | won | 41 % |
| 2 | won | 16 % |
| 3 | won (after three lost replays, see the devlog) | 34 % |
| 4 | won | 8 % |
| 5 | won | 2 % |
| 6th Night | won (with the last percent of power) | 0 % |
| 20/20/20/20 | won (live #25 with 0 %, #28 with 11 % after the clock fixes) | 11 % |

Every lost night on the way is written up in [docs/DEVLOG.md](docs/DEVLOG.md):
what the log showed, what the game's own code says, the measurement that
settled it, and the fix. The 6th Night was a scheduling-efficiency problem
(every door cycle costs power charges); 4/20 is both that and the game's
timing being only knowable to about a tenth of a second.

## The status panel

While playing, a small panel at the top of the screen shows what the bot is
doing, what it believes about each animatronic, and a clock of the night:
the hour hand sweeps from 12 to 6 over the night, the minute hand makes one
turn per in-game hour (90 s for 12 AM, 89 s for the others), and a countdown
says when the next hour lands. The panel never takes focus and clicks pass
through it. "tick 1.0056s" is the measured length of one game second (see
`docs/DEVLOG.md` for why that matters).

## Notes

* The game's artwork is never stored in this repository. Reference pictures
  are extracted from your own installed copy into `cache/` by `--setup`.
* The bot launches `FiveNightsatFreddys.exe` directly instead of through
  Steam, because Steam refuses to launch while the account is playing
  something on another computer.
