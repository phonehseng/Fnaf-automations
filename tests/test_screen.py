"""Tests for screen.py that need no running game."""

from __future__ import annotations

import numpy as np

from fnafbot.screen import GAME_HEIGHT, GAME_WIDTH, GameWindow, looks_shifted


def test_game_window_has_its_methods():
    """Guards against a method accidentally ending up outside the class."""
    for name in ("find", "focus", "in_front", "display_ok", "ensure_visible", "repair", "to_screen", "grab"):
        assert callable(getattr(GameWindow, name, None)), name


def test_to_screen_maps_game_coordinates():
    window = GameWindow()
    window.left, window.top, window.width, window.height = 100, 50, GAME_WIDTH * 2, GAME_HEIGHT * 2
    assert window.to_screen(0, 0) == (100, 50)
    assert window.to_screen(640, 360) == (100 + 1280, 50 + 720)


def test_looks_shifted():
    normal = np.full((720, 1280, 3), 40, np.uint8)
    assert not looks_shifted(normal)

    shifted = normal.copy()
    shifted[:180, :] = 0
    shifted[:, :320] = 0
    assert looks_shifted(shifted)

    black = np.zeros((720, 1280, 3), np.uint8)   # e.g. the 6 AM screen
    assert not looks_shifted(black)
