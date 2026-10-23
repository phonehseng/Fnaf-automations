"""Record the professor's narration and time the film to it.

Reads the subtitle cues from night_shift_lecture.html, speaks each one with
Piper (offline neural TTS, voice en_GB-alan-medium), measures it, and lays
the cues out scene by scene with short pauses. Writes:

* the exact timings back into the page (<script id="timing">), so the
  animation, its subtitles and the narration line up;
* timing.json - scene lengths, for export_footage.py and the sound design;
* narration.wav - the whole narration track (48 kHz, mono).

The subtitles keep real notation ("pyautogui.PAUSE = 1"); SPEAK turns the
few things a voice would trip over into words.

usage: python narrate.py [production ...]   (default: all of them)
"""

import json
import re
import sys
import wave
from pathlib import Path

import numpy as np
from piper import PiperVoice

HERE = Path(__file__).parent
PAGE = HERE / "night_shift_lecture.html"
VOICE = HERE / "voices" / "en_GB-alan-medium.onnx"
RATE = 48000

LEAD = 0.8          # silence before a scene's first cue
GAP = 0.45          # between cues
TAIL = 1.1          # after a scene's last cue
# Some cues must wait for the picture (the cold open's footage runs first).
CUE_NOT_BEFORE = {("title", 2): 13.2}
SCENE_MIN = {"title": 21.0, "first": 30.0, "foxy": 24.0, "closing": 14.0, "doorway": 30.0}

SPEAK = [
    ("pyautogui.PAUSE = 1", "pie auto G U I dot pause equals one"),
    ("PyAutoGUI", "pie auto G U I"),
    ("cv2.matchTemplate", "C V two dot match template"),
    ("mss", "M S S"),
    ("OpenCV", "Open C V"),
    ("README", "read me"),
    ("Theil-Sen", "Tile-Sen"),
    ("\"move who?\"", "move who"),
    ("move-who", "move who"),
    ("50 + Random(1000) frames", "fifty plus a random thousand frames"),
    ("5:49 AM", "Five forty-nine in the morning"),
    ("1.0065", "one point oh oh six five"),
    ("1.000", "exactly one"),
    ("exactly exactly", "exactly"),
    ("0.4 seconds", "four tenths of a second"),
    ("2.56 s", "two point five six seconds"),
    ("2.54 s", "two point five four seconds"),
    ("4.97", "four point nine seven"),
    ("4.98", "four point nine eight"),
    ("5.01", "five point oh one"),
    ("0.6", "zero point six"),
    ("3.5", "three and a half"),
    ("6 AM", "six A M"),
    ("20/20/20/20", "twenty, twenty, twenty, twenty"),
    ("2.56 seconds", "two point five six seconds"),
    ("2.54 seconds", "two point five four seconds"),
    ("999", "nine hundred and ninety-nine"),
    ("seven reached", "seven reached"),
    ("%", " percent"),
    (" AI ", " A I "),
]


def speakable(text: str) -> str:
    for a, b in SPEAK:
        text = text.replace(a, b)
    return text


def synth(voice: PiperVoice, text: str) -> np.ndarray:
    """One cue as float samples at RATE."""
    tmp = HERE / "_cue.wav"
    with wave.open(str(tmp), "wb") as w:
        voice.synthesize_wav(text, w)
    with wave.open(str(tmp), "rb") as w:
        sr = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    tmp.unlink()
    # resample to RATE (linear is fine for speech)
    n = int(len(pcm) * RATE / sr)
    return np.interp(np.linspace(0, len(pcm) - 1, n), np.arange(len(pcm)), pcm).astype(np.float32)


def main() -> None:
    html = PAGE.read_text(encoding="utf-8")
    prods = json.loads(re.search(r'<script id="productions" type="application/json">(.*?)</script>', html, re.S).group(1))
    wanted = sys.argv[1:] or list(prods)
    all_timing = json.loads(re.search(r'<script id="timing" type="application/json">(.*?)</script>', html, re.S).group(1) or "{}")
    voice = PiperVoice.load(str(VOICE))
    for pid in wanted:
        timing, track, start = {}, [], 0.0
        print(f"== {pid}")
        for si, scene in enumerate(prods[pid]["scenes"]):
            draw = scene["draw"]
            # shorts cut faster: less air around each scene
            lead, tail = (0.25, 0.45) if pid.startswith("short_") else (LEAD, TAIL)
            at, cues, pieces = lead, [], []
            for i, text in enumerate(scene["cues"]):
                at = max(at, CUE_NOT_BEFORE.get((draw, i), 0.0))
                audio = synth(voice, speakable(text))
                dur = len(audio) / RATE
                cues.append([round(at, 3), round(at + dur, 3)])
                pieces.append((at, audio))
                at += dur + GAP
            dur = max(at - GAP + tail, SCENE_MIN.get(draw, 0.0) if not pid.startswith("short_") else 0.0)
            timing[str(si)] = {"dur": round(dur, 3), "cues": cues}
            track.append((start, pieces))
            start += dur
            print(f"  {draw:9s} {dur:6.1f} s  ({len(cues)} cues)")
        mix = np.zeros(int(start * RATE) + RATE, dtype=np.float32)
        for scene_start, pieces in track:
            for at, audio in pieces:
                i = int((scene_start + at) * RATE)
                mix[i:i + len(audio)] += audio
        mix = mix / (float(np.abs(mix).max()) or 1.0) * 0.89
        with wave.open(str(HERE / f"narration_{pid}.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
            w.writeframes((mix * 32767).astype(np.int16).tobytes())
        all_timing[pid] = timing
        print(f"  total {start:.1f} s")
    html = re.sub(r'(<script id="timing" type="application/json">).*?(</script>)',
                  lambda m: m.group(1) + json.dumps(all_timing) + m.group(2), html, flags=re.S)
    PAGE.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
