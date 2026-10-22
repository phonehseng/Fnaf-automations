"""Turn screenshots into facts about the game ("power is 87%", "Foxy is peeking").

How the recognition works (in plain words):

* **HUD numbers** (power %, clock, night) are drawn with small bitmap fonts.
  We cut the exact digit pictures out of the game (see catalog.py) and look
  for them with OpenCV template matching. This is pixel-perfect, so there is
  no guessing as with general text recognition (OCR).

* **Which camera is on screen** is read from the room-name label above the
  map (e.g. "Pirate Cove"), again by matching the game's own label pictures.

* **Who is in a camera picture**: for every camera the game has a handful of
  fixed pictures (empty room, Bonnie in the room, ...). The live picture is
  those pictures plus moving TV static, and it may be slid sideways (the
  cameras slowly pan). We compare the live picture against each known picture
  at every possible slide position and pick the best match.

* **Doorways**: when a hall light is on, the office picture switches to a
  "lit" version. We compare the doorway area against the lit-empty picture
  and the lit-with-animatronic picture.

Everything is compared in grayscale at 1/4 size: it is ~16x faster and the
static noise mostly averages out.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import cv2
import numpy as np

from fnafbot import assets, catalog, layout

log = logging.getLogger(__name__)

# Work at 1/4 resolution (320 x 180) to find how far a camera is panned, and
# at 1/2 resolution (640 x 360, colour) to decide who is in the picture.
SCALE = 4
FINE_SCALE = 2

# A camera answer counts as certain when the runner-up answer fits worse by
# at least this much (average colour error, see CameraReading.confident).
MIN_CONFIDENT_MARGIN = 0.5

# Typical "live = contrast * reference + brightness" relationship caused by
# the static overlay; only used if it cannot be measured on the frame itself.
TYPICAL_CONTRAST = 0.55
TYPICAL_BRIGHTNESS = 10.0

# Pixels compared per camera read (see _rank_candidates).
MAX_COMPARE_PIXELS = 4000

# Region (quarter-size rows y0:y1, cols x0:x1) used to find a camera's pan.
# It is the left 800 x 530 px of the screen, below the recording dot and
# above the power text: the map and HUD never cover it.
PAN_STRIP = (18, 150, 0, 200)

# Template-match score needed to accept a HUD digit / label (1.0 = perfect).
DIGIT_MIN_SCORE = 0.90
LABEL_MIN_SCORE = 0.85


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class Hud:
    """Numbers read from the on-screen HUD. ``None`` means "could not read"."""

    visible: bool = False
    power: int | None = None   # 0-100
    usage: int | None = None   # 1-5 bars
    hour: int | None = None    # 12, 1, 2, 3, 4, 5
    night: int | None = None   # 1-7


@dataclass
class CameraReading:
    """What a single look at a camera told us."""

    camera: str
    handle: int = -1                       # best-matching reference picture
    occupants: frozenset[str] = field(default_factory=frozenset)
    foxy_stage: int | None = None          # only for camera 1C
    foxy_running: bool = False             # only for camera 2A
    golden_poster: bool = False            # only for camera 2B
    margin: float = 0.0                    # certainty: how much worse the next-best answer fits
    offset: int = 0                        # how far the camera picture was panned

    @property
    def confident(self) -> bool:
        """True when the answer clearly beats every alternative answer.

        Margins are average colour errors (0-255 scale). In synthetic tests
        with real static, correct answers on cameras 1A, 1C and 4B had margins
        of 0.7 - 7, while wrong answers on the hard camera 2A had < 0.15.
        """
        return self.margin >= MIN_CONFIDENT_MARGIN


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _small_gray(image: np.ndarray) -> np.ndarray:
    """Grayscale, 1/4 size, float32 - the format used for picture comparisons."""
    if image.ndim == 3:
        image = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2GRAY)
    h, w = image.shape[:2]
    return cv2.resize(image, (w // SCALE, h // SCALE), interpolation=cv2.INTER_AREA).astype(np.float32)


def _spread_sample(mask: np.ndarray, limit: int) -> tuple[np.ndarray, np.ndarray]:
    """Row/column indices of True pixels in ``mask``, thinned out evenly to at
    most ``limit`` pixels (deterministic, so results are repeatable)."""
    ys, xs = np.nonzero(mask)
    if ys.size > limit:
        step = ys.size // limit + 1
        ys, xs = ys[::step], xs[::step]
    return ys, xs


def _line_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Least-squares straight line y = a*x + b (faster than np.polyfit)."""
    x_mean, y_mean = float(x.mean()), float(y.mean())
    variance = float(((x - x_mean) ** 2).mean())
    if variance < 1e-6:
        return TYPICAL_CONTRAST, TYPICAL_BRIGHTNESS
    slope = float(((x - x_mean) * (y - y_mean)).mean()) / variance
    return slope, y_mean - slope * x_mean


def _is_animation_frame(handle: int) -> bool:
    """Foxy's sprint frames are not useful for finding the camera pan."""
    return handle in catalog.FOXY_RUNNING_IMAGES


@dataclass
class _CameraCandidates:
    """Pre-computed reference data for one camera (built once at start-up)."""

    keys: list[str]               # the answer each picture stands for, e.g. "B" or "stage2"
    handles: list[int]            # image handles, same order as keys
    fine: list[np.ndarray]        # half-size colour pictures (1600 px wide / 2)
    coarse: list[np.ndarray]      # quarter-size gray pictures, used to find the pan
    differs: np.ndarray           # True where the pictures disagree (half size)


def _camera_mask() -> np.ndarray:
    """1 where a camera picture is visible, 0 where the HUD/map covers it."""
    mask = np.ones((720 // SCALE, 1280 // SCALE), np.float32)
    for box in layout.CAMERA_IGNORE:
        mask[box.y0 // SCALE:box.y1 // SCALE, box.x0 // SCALE:box.x1 // SCALE] = 0
    return mask


def _read_digits(region: np.ndarray, font: dict[int, np.ndarray]) -> int | None:
    """Find the digits of ``font`` inside ``region`` and return them as a number."""
    hits: list[tuple[int, int, float]] = []  # (x position, digit, score)
    for digit, template in font.items():
        if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
            continue
        scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.nonzero(scores >= DIGIT_MIN_SCORE)
        hits.extend((int(x), digit, float(scores[y, x])) for y, x in zip(ys, xs))
    if not hits:
        return None
    # Several neighbouring positions can match the same digit; keep only the
    # best-scoring hit in every ~half-digit-wide slot.
    hits.sort(key=lambda h: -h[2])
    width = next(iter(font.values())).shape[1]
    chosen: list[tuple[int, int, float]] = []
    for hit in hits:
        if all(abs(hit[0] - c[0]) > width // 2 for c in chosen):
            chosen.append(hit)
    chosen.sort()
    return int("".join(str(c[1]) for c in chosen))


# ---------------------------------------------------------------------------
# The main class
# ---------------------------------------------------------------------------


class Vision:
    """Loads all reference pictures once, then answers questions about frames."""

    def __init__(self) -> None:
        assets.ensure_extracted()

        # HUD fonts and labels (full colour, full size: they are pixel perfect).
        self.power_font = {d: assets.load(h) for d, h in catalog.POWER_FONT.items()}
        self.clock_font = {d: assets.load(h) for d, h in catalog.CLOCK_FONT.items()}
        self.night_font = {d: assets.load(h) for d, h in catalog.NIGHT_FONT.items()}
        self.usage_label = assets.load(catalog.USAGE_LABEL)
        self.camera_labels = {cam: assets.load(h) for h, cam in catalog.CAMERA_NAME_LABELS.items()}

        # Camera reference pictures. Two cached sizes are built on demand:
        # quarter-size gray (to find the pan) and half-size colour (to decide).
        self._coarse_cache: dict[int, np.ndarray] = {}
        self._fine_cache: dict[int, np.ndarray] = {}
        self.camera_mask = _camera_mask()
        self.fine_mask = cv2.resize(
            self.camera_mask, (1280 // FINE_SCALE, 720 // FINE_SCALE), interpolation=cv2.INTER_NEAREST
        ).astype(bool)
        self.camera_refs: dict[str, list[tuple[int, np.ndarray]]] = {
            cam: [(img.handle, self._coarse(img.handle)) for img in images if img.visible]
            for cam, images in catalog.CAMERA_IMAGES.items()
        }
        self.camera_info = {img.handle: img for images in catalog.CAMERA_IMAGES.values() for img in images}
        self.foxy_run_refs = self._distinct_running_frames()
        self.camera_candidates = self._build_camera_candidates()

        # Office pictures, small + gray.
        self.office_normal = _small_gray(assets.load(catalog.OFFICE_NORMAL))
        self.left_lit_empty = _small_gray(assets.load(catalog.OFFICE_LEFT_LIGHT_EMPTY))
        self.left_lit_bonnie = _small_gray(assets.load(catalog.OFFICE_LEFT_LIGHT_BONNIE))
        self.right_lit_empty = _small_gray(assets.load(catalog.OFFICE_RIGHT_LIGHT_EMPTY))
        self.right_lit_chica = _small_gray(assets.load(catalog.OFFICE_RIGHT_LIGHT_CHICA))
        # Where (in office coordinates) Bonnie / Chica appear when lit.
        self.left_door_mask = self._difference_mask(self.left_lit_empty, self.left_lit_bonnie)
        self.right_door_mask = self._difference_mask(self.right_lit_empty, self.right_lit_chica)

    # -- setup helpers --------------------------------------------------------

    def _distinct_running_frames(self) -> list[tuple[int, np.ndarray]]:
        """Foxy's run animation ends on frames where the hall is already empty
        again. Those would be confused with "nobody here", so drop any running
        frame that is nearly identical to an empty West Hall picture."""
        empties = [ref for handle, ref in self.camera_refs["2A"] if not self.camera_info[handle].occupants]
        kept = []
        for handle in catalog.FOXY_RUNNING_IMAGES:
            ref = self._coarse(handle)
            if min(float(np.abs(ref - e).mean()) for e in empties) > 4.0:
                kept.append((handle, ref))
        return kept

    @staticmethod
    def _difference_mask(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """Pixels where two pictures clearly differ, cleaned of speckles."""
        mask = (np.abs(a - b) > 25).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        return cv2.dilate(mask, np.ones((3, 3), np.uint8)).astype(bool)

    # -- HUD ------------------------------------------------------------------

    def hud_visible(self, frame: np.ndarray) -> bool:
        """True while a night is being played (the "Usage:" text is on screen)."""
        region = frame[660:690, 30:120]
        score = cv2.matchTemplate(region, self.usage_label, cv2.TM_CCOEFF_NORMED).max()
        return bool(score > LABEL_MIN_SCORE)

    def read_hud(self, frame: np.ndarray) -> Hud:
        """Read power, usage, hour and night from the HUD."""
        if not self.hud_visible(frame):
            return Hud(visible=False)
        return Hud(
            visible=True,
            power=_read_digits(frame[615:655, 150:245], self.power_font),
            usage=self._count_usage_bars(frame),
            hour=_read_digits(frame[22:66, 1110:1200], self.clock_font),
            night=_read_digits(frame[66:94, 1210:1250], self.night_font),
        )

    @staticmethod
    def _count_usage_bars(frame: np.ndarray) -> int | None:
        """Count the coloured usage bars (green / yellow / red rectangles).

        Bars are 19 px wide and start every 21 px from x = 120. We only look
        at the centre of each bar slot, because a closed left door paints
        orange hazard stripes right next to the HUD that would otherwise be
        mistaken for extra bars.
        """
        count = 0
        for i in range(5):
            x = layout.USAGE_FIRST_BAR_X + layout.USAGE_BAR_PITCH * i + layout.USAGE_BAR_PITCH // 2
            pixel = frame[674:676, x - 2:x + 2].reshape(-1, 3)
            hsv = cv2.cvtColor(pixel[None, :, :], cv2.COLOR_BGR2HSV)[0]
            if not ((hsv[:, 1] > 120) & (hsv[:, 2] > 120)).all():
                break  # bars are always filled from the left, so stop at the first gap
            count += 1
        return count or None

    # -- camera monitor -------------------------------------------------------

    def current_camera(self, frame: np.ndarray) -> str | None:
        """Which camera is on screen, or None if the monitor is down."""
        region = frame[282:330, 820:1150]
        best_cam, best_score = None, LABEL_MIN_SCORE
        for cam, label in self.camera_labels.items():
            score = float(cv2.matchTemplate(region, label, cv2.TM_CCOEFF_NORMED).max())
            if score > best_score:
                best_cam, best_score = cam, score
        return best_cam

    def _build_camera_candidates(self) -> dict[str, _CameraCandidates]:
        """Prepare, once, everything needed to read each camera quickly."""
        result: dict[str, _CameraCandidates] = {}
        for camera, images in catalog.CAMERA_IMAGES.items():
            keys_and_handles = [("".join(sorted(img.occupants)) or "-", img.handle) for img in images if img.visible]
            if camera == "2A":
                keys_and_handles += [("foxy", h) for h, _ in self.foxy_run_refs]
            result[camera] = self._prepare(keys_and_handles)
        result["1C"] = self._prepare([(f"stage{s}", h) for h, s in catalog.FOXY_STAGE_IMAGES.items()])
        return result

    def _prepare(self, keys_and_handles: list[tuple[str, int]]) -> _CameraCandidates:
        fine = [self._fine(h) for _, h in keys_and_handles]
        stack = np.stack(fine)
        # Where (over the full 1600 px picture) the candidates disagree.
        spread = (stack.max(axis=0) - stack.min(axis=0)).max(axis=2)
        return _CameraCandidates(
            keys=[k for k, _ in keys_and_handles],
            handles=[h for _, h in keys_and_handles],
            fine=fine,
            coarse=[self._coarse(h) for _, h in keys_and_handles if not _is_animation_frame(h)],
            differs=spread > 20,
        )

    def _pan_offset(self, live_small: np.ndarray, refs: list[np.ndarray]) -> int:
        """Find how far the camera picture is slid sideways (0-320 px).

        Only the left part of the screen, which the map never covers, is
        matched (``PAN_STRIP``), so no mask is needed and the match takes about
        a millisecond per reference picture.
        """
        y0, y1, x0, x1 = PAN_STRIP
        strip = live_small[y0:y1, x0:x1]
        best_score, best_offset = -2.0, 0
        for ref in refs:
            scores = cv2.matchTemplate(ref[y0:y1], strip, cv2.TM_CCOEFF_NORMED)
            if scores.max() > best_score:
                best_score, best_offset = float(scores.max()), int(np.argmax(scores)) * SCALE
        return best_offset

    def _rank_candidates(self, live: np.ndarray, prepared: _CameraCandidates,
                         offset: int) -> tuple[str, int, float]:
        """Pick the reference picture that best explains the live picture.

        Only the pixels where the candidates DIFFER from each other are
        compared (the shared background tells us nothing), in colour, at half
        size. The live picture is darker and lower-contrast than the clean
        reference (TV static is blended over it), so we first fit
        ``live = contrast * reference + brightness`` on the shared background.

        Returns (answer key, image handle, margin). The margin is how much
        worse (in average 0-255 colour error) the best *different* answer is;
        a bigger margin means a more certain answer.
        """
        x = offset // FINE_SCALE
        width = 1280 // FINE_SCALE
        differs = prepared.differs[:, x:x + width] & self.fine_mask
        background = self.fine_mask & ~differs
        if differs.sum() < 20:
            differs = self.fine_mask

        # A few thousand evenly spread pixels give the same averages as all of
        # them, at a fraction of the cost (this keeps a camera read ~20 ms).
        diff_y, diff_x = _spread_sample(differs, MAX_COMPARE_PIXELS)
        live_px = live[diff_y, diff_x]
        back_y, back_x = _spread_sample(background, MAX_COMPARE_PIXELS)
        if back_y.size > 100:
            base_px = prepared.fine[0][back_y, back_x + x].ravel()
            contrast, brightness = _line_fit(base_px, live[back_y, back_x].ravel())
        else:
            contrast, brightness = TYPICAL_CONTRAST, TYPICAL_BRIGHTNESS

        errors = sorted(
            (float(np.abs(live_px - (contrast * ref[diff_y, diff_x + x] + brightness)).mean()), key, handle)
            for key, handle, ref in zip(prepared.keys, prepared.handles, prepared.fine)
        )
        best_error, best_key, best_handle = errors[0]
        runner_up = min((e for e, k, _ in errors if k != best_key), default=best_error + 99.0)
        return best_key, best_handle, runner_up - best_error

    def _fine(self, handle: int) -> np.ndarray:
        """Half-size colour version of a reference picture (cached)."""
        if handle not in self._fine_cache:
            image = assets.load(handle)
            self._fine_cache[handle] = cv2.resize(
                image, (image.shape[1] // FINE_SCALE, image.shape[0] // FINE_SCALE), interpolation=cv2.INTER_AREA
            ).astype(np.float32)
        return self._fine_cache[handle]

    def _coarse(self, handle: int) -> np.ndarray:
        """Quarter-size gray version of a reference picture (cached)."""
        if handle not in self._coarse_cache:
            self._coarse_cache[handle] = _small_gray(assets.load(handle))
        return self._coarse_cache[handle]

    def read_camera(self, frames: np.ndarray | list[np.ndarray], camera: str) -> CameraReading:
        """Work out who/what is visible on ``camera``.

        ``frames`` may be one screenshot or a few taken in quick succession.
        The picture itself does not change between them but the TV static
        does, so averaging 2-3 frames cancels much of the static.
        """
        if isinstance(frames, np.ndarray):
            frames = [frames]
        average = frames[0] if len(frames) == 1 else np.mean(frames, axis=0).astype(np.uint8)
        reading = CameraReading(camera)

        prepared = self.camera_candidates.get(camera)
        if prepared is None:  # camera 6 is audio-only: nothing to see
            reading.margin = 99.0
            return reading

        offset = self._pan_offset(_small_gray(average), prepared.coarse)
        live = cv2.resize(average, (1280 // FINE_SCALE, 720 // FINE_SCALE), interpolation=cv2.INTER_AREA)
        key, handle, margin = self._rank_candidates(live.astype(np.float32), prepared, offset)

        reading.handle, reading.margin, reading.offset = handle, margin, offset
        if key.startswith("stage"):
            reading.foxy_stage = int(key[-1])
        elif key == "foxy":
            reading.foxy_running = True
        else:
            reading.occupants = frozenset(key.strip("-"))
            reading.golden_poster = "G" in key
        return reading

    # -- office ---------------------------------------------------------------

    def office_pan(self, frame: np.ndarray) -> int:
        """How far the office view is panned (0 = fully left, 320 = fully right)."""
        live = _small_gray(frame)[35:150]           # rows between the HUD texts
        ref = self.office_normal[35:150]
        scores = cv2.matchTemplate(ref, live, cv2.TM_CCOEFF_NORMED)
        return int(np.argmax(scores)) * SCALE

    def _doorway(self, frame: np.ndarray, empty: np.ndarray, occupied: np.ndarray,
                 mask: np.ndarray) -> tuple[bool, float]:
        """Compare the doorway area with the lit-empty and lit-occupied pictures.

        Returns (someone_is_there, confidence_margin).
        """
        pan = self.office_pan(frame) // SCALE
        live = _small_gray(frame)
        view = np.zeros_like(mask)
        view[:, pan:pan + live.shape[1]] = mask[:, pan:pan + live.shape[1]]
        ys, xs = np.nonzero(view)
        if xs.size < 50:
            return False, 0.0  # the doorway is not in view at this pan position
        live_px = live[ys, xs - pan]
        err_empty = float(np.abs(live_px - empty[ys, xs]).mean())
        err_occupied = float(np.abs(live_px - occupied[ys, xs]).mean())
        return err_occupied < err_empty, abs(err_empty - err_occupied)

    def bonnie_at_left_door(self, frame: np.ndarray) -> tuple[bool, float]:
        """With the LEFT light on and the view panned left: is Bonnie there?"""
        return self._doorway(frame, self.left_lit_empty, self.left_lit_bonnie, self.left_door_mask)

    def chica_at_right_window(self, frame: np.ndarray) -> tuple[bool, float]:
        """With the RIGHT light on and the view panned right: is Chica there?"""
        return self._doorway(frame, self.right_lit_empty, self.right_lit_chica, self.right_door_mask)

    @staticmethod
    def door_lamp(frame: np.ndarray, side: str) -> str | None:
        """Read a door button's colour: 'closed' (green), 'open' (red) or None
        if the button is not on screen (view panned the other way)."""
        box = layout.LEFT_DOOR_LAMP if side == "left" else layout.RIGHT_DOOR_LAMP
        b, g, r = box.crop(frame).reshape(-1, 3).mean(axis=0)
        if g > 120 and g > r * 1.5:
            return "closed"
        if r > 120 and r > g * 1.5:
            return "open"
        return None
