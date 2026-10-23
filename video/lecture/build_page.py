"""Build the publishable page: the animation plus a still per footage
window (small JPEG data URIs) and the narrated soundtrack as an MP3.

Writes publish/night_shift_lecture.html and one narrated MP3 per production.

usage: python build_page.py   (after export_footage.py and sound.py)
"""

import base64
import io
import json
import subprocess
from pathlib import Path

import imageio_ffmpeg
from PIL import Image

HERE = Path(__file__).parent
OUT = HERE / "publish"
# Which frame of each clip makes the best still (share of the clip).
STILL_AT = {"win28_end": 0.2, "foxy_bang": 0.4, "office28": 0.5, "bonnie27": 0.4, "twobots": 0.39, "win28_fast": 0.98}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    manifest = json.loads((HERE / "footage" / "manifest.json").read_text())
    footage = {}
    for clip, info in manifest.items():
        idx = max(1, int(info["frames"] * STILL_AT.get(clip, 0.5)))
        img = Image.open(HERE / "footage" / clip / f"{idx:05d}.jpg").convert("RGB")
        img.thumbnail((640, 360))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        footage[clip] = {"frames": info["frames"], "still": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}
    html = (HERE / "night_shift_lecture.html").read_text(encoding="utf-8")
    prods = json.loads((HERE / "productions.json").read_text(encoding="utf-8"))
    audio = {pid: f"audio_{pid}.mp3" for pid in prods}
    inject = ("<script>window.FOOTAGE = " + json.dumps(footage) + ";\nwindow.LECTURE_AUDIO = " + json.dumps(audio) + ";</script>\n")
    marker = '<script>\n(() => {'
    assert html.count(marker) == 1
    (OUT / "night_shift_lecture.html").write_text(html.replace(marker, inject + marker), encoding="utf-8")
    for pid, name in audio.items():
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(HERE / f"mix_{pid}_narrated.wav"), "-ac", "1", "-b:a", "80k", str(OUT / name)], check=True)
    for f in OUT.iterdir():
        print(f.name, f.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
