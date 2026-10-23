"""Cut the OBS clips the lecture film shows into JPEG frame folders.

The animation (night_shift_lecture.html) shows these in its footage
windows; in film mode it loads footage/<clip>/NNNNN.jpg. Each clip is cut
from the one long OBS recording of 2026-10-22/23 and resampled so that it
has exactly the number of frames its scene needs at 30 fps.

Times: the recording started at 19:09:20.6 on the bot's log clock (lined up
on live 4/20 #27's camera views against the usage meter), so a log time
maps to recording time = log time - 19:09:20.6.

usage: python export_footage.py timing.json
       (timing.json: {"scene_id": seconds, ...} from the narration recording)
"""

import json
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
VIDEO = Path.home() / "Videos" / "FNAF-bot" / "2026-10-22 19-09-19.mkv"
OUT = Path(__file__).parent / "footage"
FPS = 30
REC_START = 19 * 3600 + 9 * 60 + 20.6          # log clock (s) at recording time 0


def rec(hms: str) -> float:
    """Log clock 'HH:MM:SS.s' -> seconds into the recording (after midnight: +24 h)."""
    h, m, s = hms.split(":")
    t = int(h) * 3600 + int(m) * 60 + float(s)
    if t < REC_START:
        t += 24 * 3600
    return t - REC_START


# clip id: (log-clock start, source seconds, scene it plays in, share of that scene)
CLIPS = {
    # live 4/20 #28: the last seconds before 6 AM (6 AM screen at 00:55:22.2)
    "win28_end": ("00:55:12.5", 14.0, "title", None),
    # live 4/20 #26: Foxy forced to run (00:19:22) and the bang on the door
    "foxy_bang": ("00:19:21.0", 7.0, "foxy", 6.0),
    # live 4/20 #28: an ordinary stretch of the office, lights and flips
    "office28": ("00:50:00.0", None, "senses", None),
    # live 4/20 #27: the last seconds before Bonnie (night over 00:33:08)
    "bonnie27": ("00:32:55.0", 13.0, "hurdles", None),
    # campaign49: two bots in one window, Freddy walks in
    "twobots": ("00:59:42.0", 14.0, "hurdles", None),
    # live 4/20 #28: the whole night, 12 AM to 6 AM
    "win28_fast": ("00:46:26.4", 536.0, "results", None),
}
FRAMES_FIXED = {"win28_end": 360, "foxy_bang": 180, "bonnie27": 360, "twobots": 360}


def main() -> None:
    scenes = json.loads(Path(sys.argv[1]).read_text())
    manifest = {}
    for clip, (start, length, scene, _) in CLIPS.items():
        frames = FRAMES_FIXED.get(clip) or int(scenes[scene] * FPS)
        if length is None:
            length = frames / FPS                     # real time
        folder = OUT / clip
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob("*.jpg"):
            old.unlink()
        fps = frames / length
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", f"{rec(start):.2f}", "-i", str(VIDEO),
               "-t", f"{length:.2f}", "-vf", f"fps={fps:.5f},scale=960:540", "-frames:v", str(frames),
               "-q:v", "4", str(folder / "%05d.jpg")]
        subprocess.run(cmd, check=True)
        got = len(list(folder.glob("*.jpg")))
        manifest[clip] = {"frames": got}
        print(f"{clip}: {got} frames ({length:.1f} s of the recording at {fps:.2f} fps)")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
