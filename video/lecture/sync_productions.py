"""Copy productions.json into the page (its <script id="productions">).

usage: python sync_productions.py
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
page = HERE / "night_shift_lecture.html"
prods = json.loads((HERE / "productions.json").read_text(encoding="utf-8"))
html = page.read_text(encoding="utf-8")
html = re.sub(r'(<script id="productions" type="application/json">).*?(</script>)',
              lambda m: m.group(1) + json.dumps(prods, ensure_ascii=False) + m.group(2), html, flags=re.S)
page.write_text(html, encoding="utf-8")
print("synced", list(prods))
