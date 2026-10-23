"""Put the soundtracks under the rendered animations. Every video carries
the narration on screen as subtitles.

  ../long_form/night_shift_lecture_narrated.mp4   - 16:9, with the narrator
  ../long_form/night_shift_lecture_no_narrator.mp4 - 16:9, music and effects only
  ../shorts/<name>.mp4                              - 9:16, narrated

usage: python mux.py [production ...]   (after render_all.sh and sound.py)
"""

import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

HERE = Path(__file__).parent
OUTPUTS = [
    ("long", "narrated", "long_form/night_shift_lecture_narrated.mp4"),
    ("long", "ambient", "long_form/night_shift_lecture_no_narrator.mp4"),
    ("lecture_v", "narrated", "shorts/night_shift_lecture_vertical.mp4"),
    ("short_whatif", "narrated", "shorts/what_if_a_bot_played_fnaf.mp4"),
    ("short_foxy", "narrated", "shorts/why_watching_foxy_freezes_him.mp4"),
    ("short_first", "narrated", "shorts/my_first_fnaf_bot_never_looked.mp4"),
    ("short_sees", "narrated", "shorts/how_a_bot_sees_fnaf.mp4"),
    ("short_freddy", "narrated", "shorts/freddys_ai_explained.mp4"),
    ("short_versus", "narrated", "shorts/human_vs_robot_night_guard.mp4"),
]
for pid, mix, rel in OUTPUTS:
    if sys.argv[1:] and pid not in sys.argv[1:]:
        continue
    video, audio, out = HERE / f"animation_{pid}.mp4", HERE / f"mix_{pid}_{mix}.wav", HERE.parent / rel
    if not (video.exists() and audio.exists()):
        print("skipped", rel, "(missing", video.name if not video.exists() else audio.name, ")")
        continue
    out.parent.mkdir(exist_ok=True)
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(video), "-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)], check=True)
    print("wrote", rel, out.stat().st_size // (1024 * 1024), "MB")
