"""Stills and extra clips for the shorts.

* stills/<name>.jpg - real game pictures (the camera images the bot's vision
  compares against, extracted from the game once: cache/assets) and frames
  from the bot's own live recordings (OBS, and the frames it judged from).
* footage/freddy4b - live: Freddy's eyes in the dark on CAM 4B (capture
  session, tools/capture_freddy.py), slowed down.
* footage/foxyrun - the game's own animation of Foxy sprinting down the
  West Hall (its 31 frames, in order).

usage: python prepare_stills.py
"""

import json
import subprocess
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageEnhance

HERE = Path(__file__).parent
REPO = HERE.parent.parent / "Fnaf-automations"
ASSETS = REPO / "cache" / "assets"
CAPTURE = Path.home() / "Videos" / "FNAF-bot" / "2026-10-23 04-26-03.mkv"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# name: (game picture id, what it shows)
GAME = {
    "1A_all": 20, "1A_freddy": 225, "1A_empty": 485,
    "1B_freddy": 493, "7_freddy": 495, "4A_freddy": 488, "4B_freddy": 487, "4B_empty": 50,
    "1C_s0": 67, "1C_s1": 212, "1C_s2": 339, "1C_s3": 241,
    "2B_bonnie": 480, "1B_bonnie": 121,
}
# name: (recording, seconds) - frames of the live recordings
LIVE = {"6_kitchen": (CAPTURE, 77.2), "4B_live": (CAPTURE, 156.5)}
EVIDENCE = {"door_bonnie": REPO / "logs" / "doorway" / "0020.51s_left_occupied_2.8.jpg"}
FOXY_RUN = [245, 246, 247, 248, 249, 251, 281, 282, 283, 284, 285, 286, 287, 288, 289, 290, 291, 293,
            303, 307, 328, 330, 331, 332, 333, 334, 335, 336, 337, 338]


def camera_crop(img: Image.Image) -> Image.Image:
    """Camera pictures are 1600 px wide (the game pans them): keep the middle 1280 x 720."""
    if img.width > 1280:
        x = (img.width - 1280) // 2
        img = img.crop((x, 0, x + 1280, 720))
    return img


def main() -> None:
    stills = HERE / "stills"
    stills.mkdir(exist_ok=True)
    for name, pid in GAME.items():
        img = camera_crop(Image.open(ASSETS / f"{pid:04d}.png").convert("RGB"))
        if name in ("1B_freddy", "4A_freddy", "7_freddy", "4B_freddy"):
            img = ImageEnhance.Brightness(img).enhance(1.7)        # he hides in the dark
        img.save(stills / f"{name}.jpg", quality=88)
    for name, (video, t) in LIVE.items():
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", f"{t}", "-i", str(video), "-frames:v", "1",
                        "-y", str(stills / f"{name}.jpg")], check=True)
    for name, path in EVIDENCE.items():
        Image.open(path).convert("RGB").save(stills / f"{name}.jpg", quality=90)
    # Freddy staring into CAM 4B, live, 4.5 s played over 8 s, lightly brightened
    out = HERE / "footage" / "freddy4b"
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*.jpg"):
        f.unlink()
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", "155.2", "-i", str(CAPTURE), "-t", "4.5",
                    "-vf", "eq=gamma=1.45:contrast=1.2,fps=53.33,scale=960:540", "-frames:v", "240", "-q:v", "3",
                    str(out / "%05d.jpg")], check=True)
    # Foxy's run: the game's own frames, each held for 3 video frames
    run = HERE / "footage" / "foxyrun"
    run.mkdir(parents=True, exist_ok=True)
    n = 0
    for pid in FOXY_RUN:
        img = camera_crop(Image.open(ASSETS / f"{pid:04d}.png").convert("RGB")).resize((960, 540))
        for _ in range(3):
            n += 1
            img.save(run / f"{n:05d}.jpg", quality=88)
    manifest = json.loads((HERE / "footage" / "manifest.json").read_text())
    manifest["freddy4b"] = {"frames": len(list(out.glob("*.jpg")))}
    manifest["foxyrun"] = {"frames": n}
    (HERE / "footage" / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(sorted(p.name for p in stills.iterdir()), manifest["freddy4b"], manifest["foxyrun"])


if __name__ == "__main__":
    main()
