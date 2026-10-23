#!/bin/bash
# Render every production, three at a time.
cd "$(dirname "$0")"
PY="$LOCALAPPDATA/Programs/Python/Python312/python.exe"
"$PY" render_frames.py long > render_long.txt 2>&1 &
"$PY" render_frames.py lecture_v > render_lecture_v.txt 2>&1 &
( for p in short_whatif short_foxy short_first short_sees; do "$PY" render_frames.py $p > render_$p.txt 2>&1; done ) &
wait
ls -la animation_*.mp4
