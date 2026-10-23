# The Night Shift Lecture - video tooling

Everything that makes the explainer videos, from narration to final MP4.
The footage, audio and renders themselves are not in the repository (they
are large); these scripts rebuild them from the OBS recordings.

| step | tool | makes |
|---|---|---|
| 1 | `productions.json` -> `sync_productions.py` | the narration of every production, copied into the page |
| 2 | `narrate.py [production ...]` | Piper TTS narration per production, exact cue timings written into the page |
| 3 | `export_footage.py` | the OBS clips the footage windows show, as JPEG frames |
| 4 | `render_all.sh` (`render_frames.py PRODUCTION`) | the animation, frame by frame, in headless Chromium |
| 5 | `sound.py [production ...]` | synthesized music and sound effects; narrated mixes, and a no-narrator mix of the long form |
| 6 | `mux.py [production ...]` | the final MP4s |
| 7 | `build_page.py` | the interactive page with stills and soundtracks |

`night_shift_lecture.html` is both the interactive page and the renderer:
`?p=<production>` picks a production, `?film` switches to frame-by-frame
rendering (`window.renderAt(t)`). Scenes draw in a 1080 x 1330 art space;
the layout puts the art above the text (9:16 shorts) or beside it (16:9 long
form). The full scripts are in `docs/video/SCRIPTS.md`.
