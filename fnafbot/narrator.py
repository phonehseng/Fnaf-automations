"""Friendly words for the status panel.

The brain logs exactly what it does ("Camera flip to hold Foxy (resting on
4B)") - the tools in tools/ read those lines, so they stay as they are. The
panel is for people watching, so this module turns each of those messages
into something that says what is really going on, with a bit of personality:
"Oh no! Bonnie's here! Door shut", "Eyes on Freddy...".

It also comments on the power: is the battery lasting as well as on a
winning night, or is it running low?

Everything here is a plain function of the brain's message and a few
numbers, so it is easy to test (tests/test_narrator.py).
"""

from __future__ import annotations

import re

from fnafbot import rules

# Extra power use (doors, lights, camera) on the live 4/20 wins, in units
# (0.1 %) per second on top of the game's own drain: #28 used ~176 units in
# 535 s and won with 11 %. A night at this pace ends with a few percent left.
WINNING_USAGE_RATE = 0.33
# How far below that pace (in %) counts as "lower than expected".
BEHIND_PACE = 4


def _name(word: str) -> str:
    return word.capitalize()


def _freddy_at_4b(notes: dict[str, str]) -> bool:
    return notes.get("Freddy") == "at 4B"


def narrate(action: str, notes: dict[str, str] | None = None) -> str:
    """The panel's top line for one brain message."""
    notes = notes or {}
    a = action

    # -- Bonnie and Chica ------------------------------------------------------------
    m = re.match(r"(BONNIE|CHICA) AT (LEFT|RIGHT) DOOR - closing at", a)
    if m:
        who = _name(m.group(1))
        return f"Oh no! {who}'s here! Shutting the door just in time..."
    m = re.match(r"(BONNIE|CHICA) AT (LEFT|RIGHT) DOOR - door closed", a)
    if m:
        who = _name(m.group(1))
        if who == "Chica":
            return "Oh no! Chica's at the window! Right door SHUT"
        return "Oh no! Bonnie's here! Left door SHUT"
    m = re.match(r"Looking for (\w+) \((left|right) light\)", a)
    if m:
        return f"Peeking down the {m.group(2)} hall for {m.group(1)}..."
    m = re.match(r"(\w+): light did not come on", a)
    if m:
        return f"The {'left' if m.group(1) == 'Bonnie' else 'right'} light won't come on?! Trying again"
    m = re.match(r"Is (\w+) still there\?", a)
    if m:
        return f"Is {m.group(1)} still lurking out there?"
    m = re.match(r"(\w+) has gone - (left|right) door", a)
    if m:
        return f"Phew - {_name(m.group(1))} wandered off. {m.group(2).capitalize()} door open"
    m = re.match(r"(\w+) went back towards", a)
    if m:
        return f"Phew - {m.group(1)} went back down the hall. Door open"
    m = re.match(r"(\w+) left at [0-9.]+s \(seen by the light going out\)", a)
    if m:
        return f"Phew - {m.group(1)} left (the light flickered off). Door can open"
    m = re.match(r"Watching (\w+) leave", a)
    if m:
        return f"Light on... waiting for {m.group(1)} to walk away"
    m = re.match(r"(\w+): no change across their tick", a)
    if m:
        return f"{m.group(1)} didn't budge..."
    if a.startswith("Lights went out"):
        return "The lights flickered off - someone moved in the halls"
    m = re.match(r"(\w+) may still be there - door open until", a)
    if m:
        return f"{m.group(1)} might still be there... door open, just for a moment"
    m = re.match(r"Checking whether (\w+) left \(window", a)
    if m:
        return f"Is {m.group(1)} still at the window? (door stays shut)"
    m = re.match(r"Checking whether (\w+) left \(peek\)", a)
    if m:
        return f"Quick peek: is {m.group(1)} gone yet?"

    # -- Freddy and Foxy (the camera) ---------------------------------------------------
    # Every camera flip "holds" Foxy (his lock is re-rolled while any camera
    # shows) and rests on 4B, the East Hall Corner - where Freddy waits, and
    # where looking keeps him from walking in.
    if a.startswith("Camera flip to hold Foxy"):
        if _freddy_at_4b(notes):
            return "Eyes on Freddy - he's right there on 4B! (keeps Foxy frozen too)"
        return "Camera on 4B: East Hall clear - and Foxy stays frozen"
    if a.startswith("Camera flip: checking Foxy"):
        if _freddy_at_4b(notes):
            return "Freddy is right there on 4B... and how's Foxy doing?"
        return "Camera: East Hall (4B), then a look at Foxy"
    if a.startswith("Checking Foxy (Pirate Cove)"):
        return "Peeking at Pirate Cove - is Foxy behind the curtain?"
    m = re.match(r"Foxy is still in the cove \(stage (\d)\)", a)
    if m:
        stage = int(m.group(1))
        mood = ["fast asleep", "peeking out", "getting restless", "about to run!"][min(stage, 3)]
        return f"Foxy's still in Pirate Cove ({mood})"
    if a.startswith("Pirate Cove unreadable"):
        return "Can't see Pirate Cove! Is Foxy out?!"
    if a.startswith("Foxy might be out"):
        return "Uh oh - Foxy might be out! Left door shut while I check"
    if a.startswith("FOXY LEFT THE COVE"):
        return "FOXY IS COMING! Shutting the doors!"
    if a.startswith("Making Foxy run now"):
        return "Making Foxy run into the shut door (West Hall)..."
    if a.startswith("Foxy hit the door"):
        return "BANG! Foxy hit the door. Back to normal"
    if a.startswith("Camera did not come up"):
        return "The monitor won't come up!"

    # -- everything else ------------------------------------------------------------------
    m = re.match(r"(left|right) door closed \((.*)\)", a)
    if m:
        return f"{m.group(1).capitalize()} door shut ({m.group(2)})"
    if a.startswith("Night started"):
        return "Night started - here we go!"
    return a


def power_comment(power: int | None, night_time: float, night: int) -> tuple[str, bool]:
    """A few words on the power, and whether they are a warning.

    Compares the power left with what a winning 4/20 night had at the same
    time (the game's own drain plus WINNING_USAGE_RATE) and with what the
    game's own drain alone will still take."""
    if power is None:
        return "", False
    remaining = max(0.0, rules.NIGHT_SECONDS - night_time)
    passive = rules.PASSIVE_DRAIN_PERIOD.get(night)
    base_rate = 1.0 + (1.0 / passive if passive else 0.0)          # units per second
    must_keep = remaining * base_rate / 10                          # %, with nothing switched on
    on_pace = remaining * (base_rate + WINNING_USAGE_RATE) / 10     # %, like a winning 4/20 night
    if remaining <= 0:
        return "", False
    if power < must_keep + 2:
        return "Power critical - every second counts!", True
    if power < on_pace - BEHIND_PACE:
        return "Power running lower than expected!", True
    if power > on_pace + 3 * BEHIND_PACE:
        return "Power looking healthy", False
    return "Power on track", False


def night_over_message(survived: bool, power: int) -> str:
    """The last words on the panel when the night ends."""
    if survived:
        return f"6 AM! We made it with {power}% left!"
    if power <= 0:
        return "Out of power... the lights are gone. Oh no."
    return "Oh no! Getting jumpscared!"
