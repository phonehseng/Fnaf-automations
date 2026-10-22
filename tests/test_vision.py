"""Vision tests that need no screenshots: frames are built from the game's
own pictures with the game's own TV-static pictures blended over them, the
same way the real camera feed looks.

These tests need the game installed (the pictures are extracted from it); they
are skipped otherwise. Run with:  python -m pytest tests
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from fnafbot import assets, catalog, config

pytestmark = pytest.mark.skipif(not config.GAME_EXE.exists(), reason="FNAF is not installed")

# Handles of full-screen TV static frames in the game (1280 x 720).
STATIC_FRAMES = [13, 14, 15, 16, 17, 18, 19]

# Measured on live screenshots: the camera picture keeps 42-81 % of its
# contrast under the static. Test at the harder (lower) end of that range.
PICTURE_STRENGTH = 0.45


@pytest.fixture(scope="module")
def vision():
    from fnafbot.vision import Vision

    return Vision()


def fake_camera_frame(handle: int, pan: int, static_index: int) -> np.ndarray:
    """A 1280x720 frame: camera picture ``handle`` panned by ``pan`` px, with
    static blended over it, plus a black HUD/map area like the real game."""
    picture = assets.load(handle).astype(np.float32)[:, pan:pan + 1280]
    static = assets.load(STATIC_FRAMES[static_index % len(STATIC_FRAMES)]).astype(np.float32)
    frame = PICTURE_STRENGTH * picture + (1 - PICTURE_STRENGTH) * static * 0.5
    frame[280:, 800:] = 0  # where the camera map is drawn
    return np.clip(frame, 0, 255).astype(np.uint8)


@pytest.mark.parametrize("handle,stage", sorted(catalog.FOXY_STAGE_IMAGES.items()))
@pytest.mark.parametrize("pan", [0, 160, 320])
def test_pirate_cove_stage(vision, handle, stage, pan):
    reading = vision.read_camera(fake_camera_frame(handle, pan, handle + pan), "1C")
    assert reading.foxy_stage == stage
    assert reading.confident


@pytest.mark.parametrize("camera", ["1A", "4B", "1B", "5", "3"])
@pytest.mark.parametrize("pan", [0, 100, 200, 320])
def test_reliable_cameras(vision, camera, pan):
    """The vision may say "not sure" (e.g. on Show Stage at pan 0 Freddy is
    hidden behind the camera map), but it must never be confidently wrong.
    And at the middle pan positions it must actually get every picture right."""
    for image in catalog.CAMERA_IMAGES[camera]:
        if not image.visible:
            continue
        reading = vision.read_camera(fake_camera_frame(image.handle, pan, image.handle), camera)
        correct = reading.occupants == image.occupants
        assert correct or not reading.confident, f"confidently wrong on picture {image.handle}: {image.note}"
        if pan in (100, 200):
            assert correct, f"picture {image.handle}: {image.note}"


def test_hud_digits_roundtrip(vision):
    """Draw the power font digits '57' on a black frame and read them back."""
    frame = np.zeros((720, 1280, 3), np.uint8)
    for i, digit in enumerate([5, 7]):
        sprite = assets.load(catalog.POWER_FONT[digit])
        frame[624:624 + sprite.shape[0], 185 + 18 * i:185 + 18 * i + sprite.shape[1]] = sprite
    usage = assets.load(catalog.USAGE_LABEL)
    frame[667:667 + usage.shape[0], 38:38 + usage.shape[1]] = usage
    hud = vision.read_hud(frame)
    assert hud.visible
    assert hud.power == 57


def test_camera_label(vision):
    """Every room-name label is recognised where the game draws it."""
    for handle, camera in catalog.CAMERA_NAME_LABELS.items():
        frame = np.zeros((720, 1280, 3), np.uint8)
        label = assets.load(handle)
        frame[292:292 + label.shape[0], 832:832 + label.shape[1]] = label
        assert vision.current_camera(frame) == camera


def test_doorway_lights(vision):
    """Lit doorway pictures are told apart (office panned to the matching side)."""
    left_empty = assets.load(catalog.OFFICE_LEFT_LIGHT_EMPTY)[:, :1280]
    left_bonnie = assets.load(catalog.OFFICE_LEFT_LIGHT_BONNIE)[:, :1280]
    right_empty = assets.load(catalog.OFFICE_RIGHT_LIGHT_EMPTY)[:, 320:]
    right_chica = assets.load(catalog.OFFICE_RIGHT_LIGHT_CHICA)[:, 320:]
    assert vision.bonnie_at_left_door(np.ascontiguousarray(left_bonnie))[0] is True
    assert vision.bonnie_at_left_door(np.ascontiguousarray(left_empty))[0] is False
    assert vision.chica_at_right_window(np.ascontiguousarray(right_chica))[0] is True
    assert vision.chica_at_right_window(np.ascontiguousarray(right_empty))[0] is False


def test_extracted_odd_width_label_is_not_sheared():
    """Regression test for the row-padding bug: the 'Show Stage' label (odd
    width) must have its text starting at the left edge, not wrapped around."""
    label = cv2.cvtColor(assets.load(55), cv2.COLOR_BGR2GRAY)
    bright_columns = np.nonzero((label > 200).any(axis=0))[0]
    assert bright_columns[0] < 10 and bright_columns[-1] > label.shape[1] - 15
