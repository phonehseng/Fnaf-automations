"""Where did the power go? Door timeline from a live log.

Reads a bot log (logs/campaignNN_stdout.txt) and lists, for each door, every
span it was shut: when, for how long, why it was shut and what opened it.
Also totals the camera time. On a 4/20 night everything the bot does has
to fit in ~28 % of the battery (the rest is the game's own drain), so a
door shut for no reason is the first thing to look for.

usage: python tools/door_report.py logs/campaign36_stdout.txt
"""

from __future__ import annotations

import re
import sys

# A door click is logged by these brain messages (the door toggles).
SHUT = [
    (r"(BONNIE|CHICA) AT (LEFT|RIGHT) DOOR - door closed \((.*)\)", None),
    (r"(left|right) door closed \((.*)\)", None),
]
OPEN = [
    r"(Bonnie|Chica) has gone - (left|right) door open",
    r"(Bonnie|Chica) went back towards \S+ - door open",
    r"(Bonnie|Chica) may still be there - door open until",
]


def side_of(name: str) -> str:
    return "left" if name.lower() in ("bonnie", "left") else "right"


def main() -> None:
    path = sys.argv[1]
    spans = {"left": [], "right": []}
    shut_at: dict[str, tuple[float, str] | None] = {"left": None, "right": None}
    camera = 0.0
    flips = 0
    end = 0.0
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.search(r"camera view ([\d.]+)-([\d.]+) s", line)
        if m:
            camera += float(m.group(2)) - float(m.group(1))
            flips += 1
            continue
        m = re.search(r"brain: ([\d.]+)s\s+(.*)", line)
        if not m:
            continue
        t, msg = float(m.group(1)), m.group(2).strip()
        end = max(end, t)
        m1 = re.search(r"(BONNIE|CHICA) AT (LEFT|RIGHT) DOOR - door closed \((.*)\)", msg)
        m2 = re.search(r"(left|right) door closed \((.*)\)", msg)
        if m1 or m2:
            side = (m1.group(2) if m1 else m2.group(1)).lower()
            why = m1.group(3) if m1 else m2.group(2)
            if shut_at[side] is None:
                shut_at[side] = (t, why)
            continue
        if "FOXY LEFT THE COVE" in msg:
            for side in ("left", "right"):
                if shut_at[side] is None:
                    shut_at[side] = (t, "Foxy left the cove")
            continue
        for pattern in OPEN:
            m = re.search(pattern, msg)
            if m:
                side = side_of(m.group(2) if m.lastindex and m.lastindex >= 2 and m.group(2) in ("left", "right") else m.group(1))
                if shut_at[side] is not None:
                    t0, why = shut_at[side]
                    spans[side].append((t0, t, why, msg[:60]))
                    shut_at[side] = None
                break
        if "Foxy hit the door - back to normal" in msg:
            for side in ("left", "right"):
                if shut_at[side] is not None:
                    t0, why = shut_at[side]
                    spans[side].append((t0, t, why, "Foxy run over"))
                    shut_at[side] = None
    for side in ("left", "right"):
        if shut_at[side] is not None:
            t0, why = shut_at[side]
            spans[side].append((t0, end, why, "(still shut at the end)"))

    print(f"night length in the log: {end:.0f} s")
    print(f"camera: {flips} views, {camera:.0f} s of picture")
    for side in ("left", "right"):
        total = sum(b - a for a, b, _, _ in spans[side])
        print(f"\n{side.upper()} door: shut {total:.0f} s in {len(spans[side])} spans "
              f"({total / max(end, 1) * 100:.0f} % of the night)")
        by_reason: dict[str, float] = {}
        for a, b, why, _ in spans[side]:
            by_reason[why] = by_reason.get(why, 0.0) + (b - a)
        for why, secs in sorted(by_reason.items(), key=lambda kv: -kv[1]):
            print(f"   {secs:6.1f} s  shut because: {why}")
        print("   longest spans:")
        for a, b, why, opened in sorted(spans[side], key=lambda s: s[0] - s[1])[:8]:
            print(f"   {a:7.1f} - {b:7.1f}  ({b - a:5.1f} s)  {why:28s} -> {opened}")


if __name__ == "__main__":
    main()
