"""Snapshot frames of the lecture animation at given times (for checking)."""
import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image
import io
HERE = Path(__file__).parent
pid = sys.argv[2]
times = [float(x) for x in sys.argv[3:]] if len(sys.argv) > 3 else None
with sync_playwright() as pw:
    b = pw.chromium.launch(); p = b.new_page(viewport={"width": 1080, "height": 1920})
    errors = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    p.add_init_script("window.FOOTAGE = " + (HERE / "footage" / "manifest.json").read_text() + ";")
    p.goto((HERE / "night_shift_lecture.html").as_uri() + "?film&p=" + pid)
    p.wait_for_function("window.renderAt && window.LECTURE")
    info = p.evaluate("window.LECTURE")
    p.set_viewport_size({"width": info["width"], "height": info["height"]})
    if times is None:
        times = [s["start"] + s["dur"] * f for s in info["scenes"] for f in (0.45, 0.85)]
    shots = []
    for t in times:
        p.evaluate("t => window.renderAt(t)", t)
        im = Image.open(io.BytesIO(p.locator("#c").screenshot())); shots.append(im.resize((im.width // 4, im.height // 4)))
    b.close()
cols = 4 if shots[0].width > shots[0].height else 5; rows = (len(shots) + cols - 1) // cols
sw, sh = shots[0].width + 4, shots[0].height + 4
sheet = Image.new("RGB", (cols * sw, rows * sh), "white")
for i, im in enumerate(shots): sheet.paste(im, ((i % cols) * sw, (i // cols) * sh))
sheet.save(sys.argv[1])
print("total", round(info["total"], 1), "errors:", errors[:5])
