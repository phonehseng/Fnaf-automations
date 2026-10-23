"""Render the lecture animation to a silent 30 fps video.

Opens night_shift_lecture.html?film in headless Chromium, draws every frame
with the page's own renderAt(t) (which waits for its footage frames), and
pipes the screenshots into ffmpeg.

usage: python render_frames.py PRODUCTION [--from S] [--to S]   (writes animation_PRODUCTION.mp4)
"""

import argparse
import json
import subprocess
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
FPS = 30


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("production")
    ap.add_argument("--from", dest="t0", type=float, default=0.0)
    ap.add_argument("--to", dest="t1", type=float, default=None)
    args = ap.parse_args()
    args.out = str(HERE / f"animation_{args.production}.mp4")
    manifest = json.loads((HERE / "footage" / "manifest.json").read_text())
    ffmpeg = subprocess.Popen(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-f", "image2pipe",
         "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-preset", "medium",
         "-crf", "18", "-pix_fmt", "yuv420p", args.out], stdin=subprocess.PIPE)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1920})
        page.add_init_script(f"window.FOOTAGE = {json.dumps(manifest)};")
        page.goto((HERE / "night_shift_lecture.html").as_uri() + "?film&p=" + args.production)
        page.wait_for_function("window.renderAt && window.LECTURE")
        info = page.evaluate("window.LECTURE")
        page.set_viewport_size({"width": info["width"], "height": info["height"]})
        total = page.evaluate("window.LECTURE.total")
        t1 = args.t1 if args.t1 is not None else total
        n = int((t1 - args.t0) * FPS)
        canvas = page.locator("#c")
        for i in range(n):
            t = args.t0 + i / FPS
            page.evaluate("t => window.renderAt(t)", t)
            ffmpeg.stdin.write(canvas.screenshot(type="jpeg", quality=92))
            if i % 300 == 0:
                print(f"{t:7.1f} / {t1:.1f} s", flush=True)
        browser.close()
    ffmpeg.stdin.close()
    ffmpeg.wait()
    print("wrote", args.out)


if __name__ == "__main__":
    main()
