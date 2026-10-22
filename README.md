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

## Running

```bash
python -m fnafbot --night 1 2 3 4 5
```

```bash
python -m fnafbot --custom 20 20 20 20
```

* The bot starts (or restarts) the game itself and picks the night from the
  menu. To do that it edits the save file; your original save is backed up
  once to `cache/save_backup.ini`.
* A small status panel at the top of the screen shows what the bot is doing
  ("Looking for Bonnie", "Camera flip to hold Foxy", ...).
* **Press F8 to stop the bot at any time.**
* Every run writes a log to `logs/`. If a night is ever lost, a screenshot is
  saved next to the log.

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
| `fnafbot/overlay.py` | The on-screen status panel |
| `fnafbot/__main__.py` | Command-line entry point |
| `tools/` | Simulator runner, loss debugger, calibration helpers |
| `tests/` | Automated tests |
| `docs/GAME_LOGIC.md` | The game's real rules, read from its code |
| `docs/STRATEGY.md` | How the bot uses those rules |

## Notes

* The game's artwork is never stored in this repository. Reference pictures
  are extracted from your own installed copy into `cache/` on first run.
* The bot launches `FiveNightsatFreddys.exe` directly instead of through
  Steam, because Steam refuses to launch while the account is playing
  something on another computer.
