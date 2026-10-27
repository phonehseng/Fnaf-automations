"""Build dist/FNAFBot.exe: one file, no Python needed on the computer it runs on.

usage (from the project folder):
    pip install pyinstaller
    python tools/build_exe.py

Double-clicking the .exe opens the launcher window (fnafbot/launcher.py);
run from a command prompt it takes the same options as `python -m fnafbot`
(for example `FNAFBot.exe --custom 20 20 20 20`). Its cache, logs and
settings are kept next to the .exe.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    # PyInstaller needs a script, not "-m fnafbot": a two-line one is written
    # to build/ (which git ignores) and pointed at the package's main().
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    entry = build / "fnafbot_exe.py"
    entry.write_text("from fnafbot.__main__ import main\n\nmain()\n", encoding="utf-8")
    subprocess.run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile",
        "--console",                     # the bot's live log shows in this window
        "--name", "FNAFBot",
        "--paths", str(ROOT),
        "--hidden-import", "fnafbot.launcher",   # imported only when double-clicked
        "--add-data", f"{ROOT / 'fnafbot' / 'fonts'};fnafbot/fonts",   # Google Sans for the launcher
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(build / "pyinstaller"),
        "--specpath", str(build),
        str(entry),
    ], check=True, cwd=ROOT)
    print(f"Built {ROOT / 'dist' / 'FNAFBot.exe'}")


if __name__ == "__main__":
    main()
