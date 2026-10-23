"""Music and sound effects for the lecture film - all synthesized here.

Nothing is sampled from anywhere, so the whole soundtrack is ours to use:
a suspense drone with a slow minor pad, an original music-box motif, a
heartbeat under the hurdles, and effects placed on the animation's own
beats (static bursts and whooshes on every cut, footsteps on the map, a
metronome for the 2023 bot, Foxy's run and bangs, a jumpscare screech, a
6 AM chime, the left door slamming at the end).

Writes, for each production:
  mix_<production>_narrated.wav - the narration on top, music ducked under it
  mix_long_ambient.wav          - the long form only: no narrator, music and
                                  effects carry the film

usage: python sound.py [production ...]   (after narrate.py)
"""

import json
import re
import sys
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
RATE = 48000
RNG = np.random.default_rng(7)


# ---------------------------------------------------------------- building blocks
def t_axis(dur):
    return np.arange(int(dur * RATE)) / RATE


def env(n, attack, release):
    """Linear attack, exponential release envelope of n samples."""
    a = max(1, int(attack * RATE))
    e = np.exp(-np.arange(n) / max(1, release * RATE))
    e[:a] *= np.linspace(0, 1, a)
    return e


def lowpass(x, cutoff):
    """One-pole low-pass; cutoff may be a number or an array per sample."""
    cutoff = np.broadcast_to(np.asarray(cutoff, dtype=float), x.shape)
    a = np.exp(-2 * np.pi * cutoff / RATE)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):          # short sounds only, so a loop is fine
        acc = a[i] * acc + (1 - a[i]) * x[i]
        y[i] = acc
    return y


def noise(dur):
    return RNG.standard_normal(int(dur * RATE)).astype(np.float32)


def whoosh(dur=0.7):
    n = noise(dur)
    sweep = np.linspace(300, 4000, len(n)) ** 1.0
    sweep = np.concatenate([sweep[: len(n) // 2], sweep[len(n) // 2:][::-1]])
    x = lowpass(n, sweep) - lowpass(n, sweep * 0.25)
    return x * np.sin(np.linspace(0, np.pi, len(x))) ** 2 * 0.9


def static(dur=0.3):
    n = noise(dur)
    crackle = (RNG.random(len(n)) > 0.985) * RNG.standard_normal(len(n)) * 3
    x = n - lowpass(n, 2500) + crackle
    return x * env(len(x), 0.005, dur * 0.6) * 0.35


def thud(freq=55, dur=0.35, click=0.3):
    t = t_axis(dur)
    pitch = freq * (1 + 1.5 * np.exp(-t * 30))
    x = np.sin(2 * np.pi * np.cumsum(pitch) / RATE) * env(len(t), 0.002, 0.09)
    x += lowpass(noise(dur), 900) * env(len(t), 0.001, 0.02) * click
    return x


def footstep():
    return thud(70, 0.25, 0.6) * 0.8


def metal_bang():
    t = t_axis(1.4)
    x = sum(np.sin(2 * np.pi * f * t) * a for f, a in ((187, 1.0), (311, 0.7), (523, 0.5), (871, 0.35), (1340, 0.2)))
    x = x * env(len(t), 0.001, 0.35) * 0.5 + np.pad(thud(48, 0.5, 1.0), (0, len(t) - int(0.5 * RATE)))
    return x


def door_slam():
    t = t_axis(1.8)
    x = np.pad(thud(40, 0.8, 1.4), (0, len(t) - int(0.8 * RATE))) * 1.3
    rattle = lowpass(noise(1.8), 3000) * env(len(t), 0.001, 0.25) * 0.5
    ring = sum(np.sin(2 * np.pi * f * t) for f in (233, 377, 610)) * env(len(t), 0.001, 0.5) * 0.15
    return x + rattle + ring


def tick():
    t = t_axis(0.05)
    return np.sin(2 * np.pi * 1500 * t) * env(len(t), 0.0005, 0.01) * 0.5


def blip(freq=880, dur=0.12):
    t = t_axis(dur)
    return np.sin(2 * np.pi * freq * t) * env(len(t), 0.003, 0.04) * 0.35


def bell(freq, dur=2.5, amp=0.4):
    t = t_axis(dur)
    x = sum(np.sin(2 * np.pi * freq * m * t) * a * np.exp(-t * d) for m, a, d in ((1, 1, 1.6), (2.76, 0.4, 3), (5.4, 0.2, 5), (0.5, 0.3, 1.2)))
    return x * env(len(t), 0.002, dur) * amp


def chime():
    """An original three-note 6 AM chime (not the game's)."""
    out = np.zeros(int(4 * RATE), dtype=np.float32)
    for i, f in enumerate((659.3, 830.6, 987.8)):
        b = bell(f, 3.0, 0.35)
        s = int(i * 0.42 * RATE)
        out[s:s + len(b)] += b[: len(out) - s]
    return out


def screech(dur=0.9):
    t = t_axis(dur)
    f = 420 + 260 * np.sin(2 * np.pi * 23 * t) + 600 * t
    saw = 2 * ((np.cumsum(f) / RATE) % 1) - 1
    x = saw * 0.5 + (noise(dur) - lowpass(noise(dur), 1500)) * 0.4
    return x * env(len(t), 0.01, 0.35) * 0.45


def dice():
    out = np.zeros(int(0.8 * RATE), dtype=np.float32)
    for k in range(9):
        c = thud(900 + 300 * RNG.random(), 0.04, 1.2) * (0.5 - k * 0.04)
        s = int((k * 0.07 + 0.02 * RNG.random()) * RATE)
        out[s:s + len(c)] += c[: len(out) - s]
    return out


def curtain():
    n = noise(0.8)
    return (lowpass(n, 1800) - lowpass(n, 300)) * np.sin(np.linspace(0, np.pi, len(n))) * 0.6


def time_stop():
    t = t_axis(1.6)
    f = 600 * np.exp(-t * 2.2) + 60
    return np.sin(2 * np.pi * np.cumsum(f) / RATE) * env(len(t), 0.02, 1.0) * 0.35


def boom():
    t = t_axis(3.0)
    return (np.sin(2 * np.pi * 36 * t) + 0.5 * np.sin(2 * np.pi * 54 * t)) * env(len(t), 0.01, 1.2) * 0.8


# ---------------------------------------------------------------- music bed
def music(total, intensity):
    """Suspense drone: A minor pad on a slow cycle, a low pulse, and a
    sparse music-box motif. intensity(t) in 0..1 shapes it per scene."""
    t = t_axis(total)
    lfo = 0.6 + 0.4 * np.sin(2 * np.pi * t / 11)
    drone = (np.sin(2 * np.pi * 55 * t) + 0.6 * np.sin(2 * np.pi * 82.41 * t + np.sin(t * 0.3))
             + 0.3 * np.sin(2 * np.pi * 110.3 * t)) * 0.18 * lfo
    chords = [(220, 261.6, 329.6), (174.6, 220, 261.6), (146.8, 174.6, 220), (164.8, 207.7, 246.9)]   # Am F Dm E
    pad = np.zeros_like(t)
    seg = 8.0
    for i in range(int(total / seg) + 1):
        a, b = int(i * seg * RATE), int(min(total, (i + 1) * seg + 2) * RATE)
        if a >= len(t):
            break
        tt = t[a:b] - i * seg
        shape = np.minimum(1, tt / 2.5) * np.minimum(1, np.maximum(0, (seg + 2 - tt) / 2.5))
        for f in chords[i % 4]:
            pad[a:b] += (np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(2 * np.pi * f * 2.003 * tt)) * shape * 0.035
    inten = np.interp(t, *zip(*intensity))
    pulse = np.zeros_like(t)
    for k in np.arange(0, total, 1.0):        # heartbeat: lub-dub, louder when tense
        for off, amp in ((0, 1.0), (0.22, 0.6)):
            s = int((k + off) * RATE)
            th = thud(50, 0.3, 0.2) * amp * 0.35
            pulse[s:s + len(th)] += th[: max(0, len(pulse) - s)]
    box = np.zeros_like(t)
    motif = [880, 1046.5, 1318.5, 1174.7, 1046.5, 987.8, 880]      # original, A minor
    for k in np.arange(4, total - 4, 16.0):
        for j, f in enumerate(motif):
            s = int((k + j * 0.55) * RATE)
            b = bell(f, 1.6, 0.06)
            box[s:s + len(b)] += b[: max(0, len(box) - s)]
    return (drone + pad) * (0.7 + 0.5 * inten) + pulse * inten + box * (1 - inten)


# ---------------------------------------------------------------- the cue sheet
# Effects for each kind of scene, wherever it appears: put(sound, t, gain)
# places a sound at scene time t; cue(i) is when narration cue i starts; d is
# the scene's length.
def fx_title(put, cue, d):
    cold = min(12, d * 0.45)
    fan = lowpass(noise(cold), 400) * 0.25 + np.sin(2 * np.pi * 120 * t_axis(cold)) * 0.03
    put(fan * np.minimum(1, t_axis(cold) / 1.0), 0)
    put(chime(), cold * 0.93, 0.9)                     # the 6 AM screen in the footage
    put(whoosh(1.2), cold - 0.2, 0.8)
    put(boom(), cold + 0.3, 0.9)


def fx_budget(put, cue, d):
    put(blip(440, 0.3), cue(1), 0.6)
    put(time_stop(), cue(2), 0.7)                      # the game's share drains in
    for k in np.arange(cue(4), d - 0.5, 1.0):          # the once-a-second charge
        put(tick(), k, 0.9)


def fx_first(put, cue, d):
    for k in np.arange(cue(2), cue(5), 1.0):           # PAUSE = 1: a metronome
        put(tick(), k, 0.8)
    for j in range(5):
        put(footstep(), cue(6) + j * 0.5, 0.5)         # Bonnie, walking in unseen
    put(screech(0.7), cue(8), 0.5)
    put(thud(45, 0.6, 1.5), cue(8), 1.0)


def fx_map(put, cue, d):
    speed = 32 / max(d - 2, 1)
    walks = {"bonnie": [3, 6, 9, 12, 15, 18, 21, 24, 27, 30], "chica": [4, 8, 12, 16, 20, 24, 27, 30], "freddy": [12, 24]}
    for who, ts in walks.items():
        for w in ts:
            when = w / speed + 1 - 0.8
            if when < d:
                for j in range(3):
                    put(footstep(), when + j * 0.22, 0.45 if who != "freddy" else 0.7)


def fx_ai(put, cue, d):
    put(dice(), cue(2), 0.8)
    for k in np.arange(cue(5), d, 1.2):
        put(blip(660, 0.08), k, 0.6)


def fx_doorway(put, cue, d):
    for j in range(4):
        put(footstep(), cue(1) - 2.0 + j * 0.22, 0.6)  # Bonnie arrives
    put(blip(1200, 0.06), cue(2) + 0.6, 0.8)           # the light switch
    put(blip(1200, 0.06), cue(2) + 1.5, 0.6)
    put(door_slam(), cue(3) + 0.9, 0.6)
    put(whoosh(0.6), cue(3) + 3.9, 0.4)                # the door goes back up
    put(blip(1200, 0.06), cue(4) + 0.8, 0.8)
    put(static(0.25), cue(4) + 3.4, 0.6)               # the light cuts out by itself


def fx_freddy(put, cue, d):
    put(boom(), 0.5, 0.35)
    put(blip(300, 0.3), cue(1), 0.6)
    put(blip(250, 0.3), cue(1) + 0.4, 0.6)
    put(whoosh(0.6), cue(2), 0.5)
    put(bell(196, 3.0, 0.25), cue(2) + 0.5, 1.0)



def fx_freddyai(put, cue, d):
    put(boom(), 0.5, 0.35)
    for k in np.arange(cue(1), cue(3), 3.02):          # his 3.02 s roll
        put(dice(), k, 0.35)
    put(time_stop(), cue(2), 0.6)                      # watched: the countdown resets
    walk_from, walk_to = cue(3) + 2.2, cue(4) - 0.4
    for j in range(5):                                 # five rooms to the corner
        for k in range(2):
            put(footstep(), walk_from + j * (walk_to - walk_from) / 5 + k * 0.25, 0.8)
    put(blip(300, 0.3), cue(4), 0.6)
    put(blip(250, 0.3), cue(4) + 0.4, 0.6)
    put(screech(0.6), cue(4) + 1.2, 0.35)
    put(bell(196, 3.0, 0.25), cue(5) + 0.5, 1.0)

def fx_foxy(put, cue, d):
    run = cue(4) + 1
    for k in range(1, 4):
        put(curtain(), k * run / 4, 0.7)               # the curtains part a stage at a time
    put(time_stop(), cue(3), 1.0)
    for j in range(8):
        put(footstep(), run + j * 0.2, 0.7)
    for j in range(3):
        put(metal_bang(), run + 1.6 + j * 0.8, 0.8)


def fx_senses(put, cue, d):
    for i in range(5):
        put(blip(520 + i * 120), 0.8 + i * 0.5, 0.7)
    put(blip(330, 0.25), cue(2), 0.8)


def fx_match(put, cue, d):
    for k in np.arange(cue(1), cue(2) + 1.5, 0.25):
        put(tick(), k, 0.3)
    put(chime(), cue(2), 0.4)
    put(static(0.3), cue(3), 0.5)


def fx_plan(put, cue, d):
    for k in np.arange(0.4, d, 1 / 0.5):
        put(tick(), k, 0.35)
    for i, f in enumerate((300, 990, 300)):
        put(blip(f, 0.2), cue(3) + 0.6 + i * 0.5, 0.8)


def fx_sim(put, cue, d):
    for k in np.arange(cue(1), cue(3), 0.12):
        put(tick(), k, 0.15)
    put(chime(), cue(3) - 0.4, 0.4)
    put(thud(50, 0.5, 1.0), cue(3), 0.8)


def fx_hurdles(put, cue, d):
    for i in (2, 4, 6):
        put(whoosh(0.6), cue(i) - 0.3, 0.5)
    put(screech(0.9), cue(6) - 0.7, 0.55)
    put(screech(0.9), cue(6) + 0.39 * (d - cue(6)), 0.55)


def fx_attempts(put, cue, d):
    for i in range(28):
        put(blip(400 + (i % 7) * 60, 0.05), 0.4 + i * (max(1, cue(2) - 0.4) / 28), 0.4)
    put(chime(), cue(2), 0.5)
    put(chime(), cue(3), 0.6)


def fx_results(put, cue, d):
    put(chime(), d * 0.55, 0.6)


def fx_closing(put, cue, d):
    put(door_slam(), d - 3.0 + 0.3, 1.0)               # the door lands 0.35 s after it starts
    put(boom(), d - 3.0 + 0.35, 0.6)


TENSE = {"title": 0.3, "budget": 0.3, "first": 0.4, "map": 0.3, "ai": 0.2, "doorway": 0.6, "freddy": 0.6, "freddyai": 0.6,
         "foxy": 0.7, "senses": 0.15, "match": 0.15, "plan": 0.25, "sim": 0.2, "hurdles": 0.9, "attempts": 0.5,
         "results": 0.1, "closing": 0.4}


# ---------------------------------------------------------------- the shorts' scenes and music
def fx_clip(put, cue, d):
    put(static(0.4), 0.0, 0.5)
    put(boom(), 0.1, 0.35)


def fx_cams(put, cue, d):
    pass                                               # the cuts inside get their static from cams_cuts


def fx_route(put, cue, d):
    for k in np.arange(0.6, d - 0.8, 0.9):
        put(footstep(), k, 0.6)


def fx_roll(put, cue, d):
    for k in np.arange(0.05, d, 3.02):
        put(dice(), k, 0.5)


def fx_watch(put, cue, d):
    for k in np.arange(0.0, d, 2.2):
        put(whoosh(0.4), k, 0.25)                      # the monitor goes up
        put(footstep(), k + 1.3, 0.7)                  # and he steps closer while it is down


def fx_corner(put, cue, d):
    put(blip(300, 0.3), 0.15 * d, 0.6)
    put(blip(250, 0.3), 0.35 * d, 0.6)
    for j in range(3):
        put(footstep(), 0.62 * d + j * 0.35, 0.9)
    put(screech(0.9), 0.62 * d + 1.0, 0.5)


def fx_answer(put, cue, d):
    put(bell(196, 3.0, 0.25), 0.5, 1.0)
    put(chime(), d * 0.6, 0.35)


def fx_recap(put, cue, d):
    for i in range(4):
        put(blip(660 + i * 110, 0.12), 0.5 + i * (d * 0.55 / 4), 0.6)


def fx_lock(put, cue, d):
    for k in np.arange(0.0, d, 2.4):
        put(whoosh(0.4), k, 0.25)
        for j in range(12):
            put(tick(), k + j * 0.1, 0.2)              # the re-rolls, ten a second


def fx_pause(put, cue, d):
    put(time_stop(), 0.25 * d, 1.0)


def fx_bangs(put, cue, d):
    for j in range(7):
        put(footstep(), j * 0.2, 0.7)
    for b in (1.6, 2.6, 3.6):
        put(metal_bang(), min(b, d - 1.2), 0.8)


def fx_flips(put, cue, d):
    for k in np.arange(0.5, d, 5.01 / 0.6):
        put(whoosh(0.4), k, 0.3)



def fx_versus(put, cue, d):
    put(whoosh(0.6), 0.1, 0.5)
    for k in np.arange(0.4, d, 1.0):                   # the power charges
        put(tick(), k, 0.25)
    put(screech(0.8), d * 0.7, 0.4)                    # the human's side goes wrong
    put(chime(), d * 0.85, 0.3)


def fx_sneak(put, cue, d):
    for j in range(5):
        put(footstep(), d * 0.3 + j * 0.6, 0.6)
    put(screech(1.0), d * 0.78, 0.7)
    put(boom(), d * 0.78, 0.6)


def fx_slowpath(put, cue, d):
    for k in np.arange(0.6, d, 1.36):
        put(footstep(), k, 0.5)


def fx_guardwatch(put, cue, d):
    put(bell(196, 3.0, 0.25), 0.5, 1.0)
    put(chime(), d * 0.6, 0.35)


def fx_foxyoffice(put, cue, d):
    for j in range(8):
        put(footstep(), j * 0.18, 0.7)
    put(door_slam(), d * 0.32, 0.9)
    for b in (0.45, 0.6, 0.75):
        put(metal_bang(), d * b, 0.8)


def fx_blind(put, cue, d):
    for k in np.arange(0.0, d * 0.82, 1.0):
        put(tick(), k, 0.8)
    for j in range(5):
        put(footstep(), d * 0.25 + j * 0.7, 0.5)
    put(screech(1.0), d * 0.82, 0.7)
    put(boom(), d * 0.82, 0.6)


def fx_night(put, cue, d):
    for at in (0.18, 0.34, 0.52, 0.66, 0.8):
        put(footstep(), at * d, 0.6)
        put(door_slam(), at * d + 0.45, 0.5)
    put(chime(), d * 0.93, 0.8)


def fx_code(put, cue, d):
    put(tick(), 0.3, 0.6)


TENSE.update({"clip": 0.6, "cams": 0.5, "route": 0.4, "roll": 0.3, "watch": 0.7, "corner": 0.9, "answer": 0.3,
              "recap": 0.2, "versus": 0.6, "sneak": 0.9, "slowpath": 0.5, "guardwatch": 0.3, "foxyoffice": 0.9, "blind": 0.8, "night": 0.6, "lock": 0.5, "pause": 0.4, "bangs": 0.9, "flips": 0.3, "code": 0.4})


def short_music(total, intensity):
    """A beat under the shorts: 96 BPM, kick and snare, eighth-note hats, a
    minor bassline, over the same drone and pad as the long form."""
    t = t_axis(total)
    bed = music(total, intensity) * 0.6
    beat = 60 / 96
    drums = np.zeros_like(t)
    bass_notes = [55.0, 55.0, 43.65, 49.0]             # A1 A1 F1 G1, one per bar
    for n, k in enumerate(np.arange(0, total - 0.5, beat)):
        s = int(k * RATE)
        if n % 2 == 0:
            kk = thud(52, 0.35, 0.4) * 0.9
            drums[s:s + len(kk)] += kk[: max(0, len(drums) - s)]
        else:
            sn = (noise(0.18) - lowpass(noise(0.18), 1800)) * env(int(0.18 * RATE), 0.002, 0.05) * 0.5
            drums[s:s + len(sn)] += sn[: max(0, len(drums) - s)]
        for h in (0, beat / 2):
            hs = int((k + h) * RATE)
            hh = (noise(0.05) - lowpass(noise(0.05), 6000)) * env(int(0.05 * RATE), 0.001, 0.012) * 0.25
            drums[hs:hs + len(hh)] += hh[: max(0, len(drums) - hs)]
    bass = np.zeros_like(t)
    for bar, k in enumerate(np.arange(0, total, beat * 4)):
        f = bass_notes[bar % 4]
        for j in range(4):
            s, n = int((k + j * beat) * RATE), int(beat * 0.9 * RATE)
            tt = np.arange(n) / RATE
            note = (np.sin(2 * np.pi * f * tt) + 0.35 * np.sin(2 * np.pi * f * 2 * tt)) * env(n, 0.005, beat * 0.6) * 0.5
            bass[s:s + n] += note[: max(0, len(bass) - s)]
    inten = np.interp(t, *zip(*intensity))
    fade_in = np.minimum(1, t / 1.5)
    return bed + (drums * (0.55 + 0.45 * inten) + bass * 0.7) * fade_in


def mix_production(pid, prod, timing):
    scenes = prod["scenes"]
    start, at = [], 0.0
    for i in range(len(scenes)):
        start.append(at)
        at += timing[str(i)]["dur"]
    total = at + 1.0
    sfx = np.zeros(int(total * RATE) + RATE * 4, dtype=np.float32)
    for i, scene in enumerate(scenes):
        s0, cues, d = start[i], timing[str(i)]["cues"], timing[str(i)]["dur"]

        def put(sound, when, gain=1.0, s0=s0):
            k = int((s0 + when) * RATE)
            if 0 <= k < len(sfx):
                sfx[k:k + len(sound)] += (sound * gain)[: len(sfx) - k]

        def cue(j, cues=cues):
            return cues[min(j, len(cues) - 1)][0]

        if i > 0:                                      # every cut: a static burst and a whoosh
            put(static(0.35), -0.2, 0.9)
            put(whoosh(0.8), -0.5, 0.6)
        globals()["fx_" + scene["draw"]](put, cue, d)
        if scene["draw"] == "cams":                    # a static burst at each camera cut
            for j in range(1, len(scene["cams"])):
                put(static(0.25), j * d / len(scene["cams"]), 0.7)
    points = [(0, 0.3)]
    for i, scene in enumerate(scenes):
        tension = TENSE[scene["draw"]]
        points += [(start[i] + 0.5, tension), (start[i] + timing[str(i)]["dur"] - 0.5, tension)]
    points.append((total, 0.2))
    short = pid.startswith("short_")
    bed = short_music(total, points) if short else music(total, points)
    n = min(len(bed), len(sfx))
    bed, fx = bed[:n], sfx[:n]
    bed *= np.minimum(1, np.minimum(np.arange(n) / RATE / 2.0, (n / RATE - np.arange(n) / RATE) / 3.0))
    with wave.open(str(HERE / f"narration_{pid}.wav"), "rb") as w:
        voice = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    voice = np.pad(voice, (0, max(0, n - len(voice))))[:n]
    # duck the music under the voice (smoothed envelope of the narration)
    level = np.convolve(np.abs(voice), np.ones(4800) / 4800, mode="same")
    duck = np.convolve(1 - 0.6 * np.clip(level * 12, 0, 1), np.ones(9600) / 9600, mode="same")

    def write(name, x):
        x = x / max(1e-6, np.abs(x).max()) * 0.9
        with wave.open(str(HERE / name), "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(RATE)
            w.writeframes((np.stack([x, x], 1) * 32767).astype(np.int16).tobytes())
        print("wrote", name, f"{len(x) / RATE:.1f} s")

    if short:   # the shorts' music stays up under the voice
        write(f"mix_{pid}_narrated.wav", voice + bed * 0.5 * (0.55 + 0.45 * duck) + fx * 0.55)
    else:
        write(f"mix_{pid}_narrated.wav", voice + bed * 0.55 * duck + fx * 0.5)
    if prod["layout"] == "landscape":                  # only the long form gets a cut without the narrator
        write(f"mix_{pid}_ambient.wav", bed * 0.8 + fx * 0.75)


def main() -> None:
    html = (HERE / "night_shift_lecture.html").read_text(encoding="utf-8")
    timing = json.loads(re.search(r'<script id="timing" type="application/json">(.*?)</script>', html, re.S).group(1))
    prods = json.loads(re.search(r'<script id="productions" type="application/json">(.*?)</script>', html, re.S).group(1))
    for pid in (sys.argv[1:] or list(prods)):
        mix_production(pid, prods[pid], timing[pid])


if __name__ == "__main__":
    main()
