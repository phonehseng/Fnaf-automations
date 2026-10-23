"""The night clock: the overlay's hands, the 6 AM screen detector and the
game-second scale that RealBody learns from power changes."""

import numpy as np

from fnafbot import overlay, rules, vision


def test_hour_hand_sweeps_half_a_turn():
    assert overlay.clock_angles(0.0) == (0.0, 0.0)
    hour, minute = overlay.clock_angles(rules.NIGHT_SECONDS / 2)
    assert abs(hour - 90.0) < 1e-9
    assert overlay.clock_angles(rules.NIGHT_SECONDS) == (180.0, 0.0)


def test_minute_hand_turns_once_per_game_hour():
    # 12 AM lasts 90 s: half way through, the minute hand points at 6.
    assert abs(overlay.clock_angles(45.0)[1] - 180.0) < 1e-9
    # 1 AM starts at 90 s and lasts 89 s.
    assert abs(overlay.clock_angles(90.0)[1]) < 1e-9
    assert abs(overlay.clock_angles(90.0 + 89.0 / 4)[1] - 90.0) < 1e-9


def test_hour_names_and_countdown():
    assert overlay.hour_name(0.0) == "12 AM"
    assert overlay.hour_name(89.9) == "12 AM"
    assert overlay.hour_name(90.0) == "1 AM"
    assert overlay.hour_name(535.0) == "6 AM"
    assert overlay.countdown_text(53.0) == "1 AM in 37 s"
    assert overlay.countdown_text(600.0) == "6 AM"


def _six_am_frame() -> np.ndarray:
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    frame[300:380, 560:740] = 255          # the big white "6 AM"
    return frame


def test_six_am_screen_is_recognised():
    v = vision.Vision.__new__(vision.Vision)     # no reference pictures needed
    assert v.six_am_visible(_six_am_frame())


def test_other_screens_are_not_six_am():
    v = vision.Vision.__new__(vision.Vision)
    static = np.random.default_rng(1).integers(0, 120, (720, 1280, 3), dtype=np.uint8)
    assert not v.six_am_visible(static)                     # the static after a loss
    assert not v.six_am_visible(np.zeros((720, 1280, 3), dtype=np.uint8))   # blackout
    office = _six_am_frame()
    office[400:700, 100:400] = 90                           # something lit elsewhere
    assert not v.six_am_visible(office)


def test_game_second_scale_is_learned_from_power_changes():
    from fnafbot import body as body_module

    body = body_module.RealBody.__new__(body_module.RealBody)
    body.t0 = 1000.0
    body.real_origin = 1000.0
    body.scale = 1.0                    # start with a wrong belief: 1 game s = 1 real s
    body._power_sightings = []
    body._fitted = False
    true_scale = 1.0065
    rng = np.random.default_rng(0)
    for k in range(1, 200):
        delay = rng.uniform(0.005, 0.03)                     # we see a change a little after it
        body._calibrate(1000.0 + k * true_scale + delay, gap=0.03)
        if k == 100:
            body._calibrate(1000.0 + 100.6 * true_scale, gap=0.03)   # Foxy's bang: a charge between ticks
        if k % 7 == 0:
            # A change noticed late, after a busy second: must not bend the line.
            body._calibrate(1000.0 + k * true_scale + 0.9, gap=1.0)
    assert abs(body.scale - true_scale) < 0.0003
    assert abs(body.t0 - 1000.0) < 0.02
    # The brain's clock (game seconds) now agrees with the real tick times.
    assert abs((1000.0 + 500 * true_scale - body.t0) / body.scale - 500) < 0.05


def _sparse_power_night(true_scale: float, guess: float, seed: int, late_start: float = 0.0):
    """A night as the bot sees it: the power display only changes when the
    battery crosses a whole percent (every 5 - 8 s at 4/20 drain), the HUD
    is looked at every 0.03 - 0.1 s while the bot is idle, now and then it
    is busy for a second (a late sighting, which must not count), and one
    sighting in ten is simply wrong by up to 0.18 s."""
    from fnafbot import body as body_module

    body = body_module.RealBody.__new__(body_module.RealBody)
    body.t0 = 1000.0 + late_start          # the first frame noticed late
    body.real_origin = body.t0
    body.scale = guess
    body._power_sightings = []
    body._fitted = False
    rng = np.random.default_rng(seed)
    errors = []                      # (charge, how far the clock's whole second is from it)
    units = 999
    for k in range(1, 536):
        units -= int(rng.choice([1, 2, 2, 3])) + (1 if k % 3 == 0 else 0)
        if units // 10 != (units + 1) // 10 or rng.random() < 0.15:
            charge = 1000.0 + k * true_scale
            gap = rng.uniform(0.03, 0.1) if rng.random() > 0.1 else 1.0
            stale = rng.uniform(-0.18, 0.18) if rng.random() < 0.1 else 0.0   # a bad sighting
            body._calibrate(charge + rng.uniform(0.0, gap) + 0.015 + stale, gap=gap)
        errors.append((k, body.t0 + k * body.scale - (1000.0 + k * true_scale)))
    return body, errors


def test_power_clock_follows_sparse_changes():
    """On live 4/20 nights the fit never started (DEVLOG: "the power clock
    never fitted"): the clock must lock on with a power change only every
    few seconds, whether the starting guess is too long or too short."""
    for true_scale, guess in ((1.0, 1.0065), (1.0065, 1.0), (1.003, 1.0)):
        for seed in range(6):
            body, errors = _sparse_power_night(true_scale, guess, seed)
            # Locked on within a minute; well inside POWER_TICK_GUARD after that.
            assert max(abs(e) for k, e in errors if k >= 40) < 0.12, (true_scale, guess, seed)
            assert max(abs(e) for k, e in errors if k >= 100) < 0.05, (true_scale, guess, seed)
            assert abs(body.scale - true_scale) < 0.001


def test_late_noticed_night_start_is_corrected():
    """Live 4/20 #27 started its clock 0.4 s after the first frame (OBS
    recording) and lost to Bonnie. The first minute of power changes must
    move both the clock and the movement timers' origin to the real start."""
    for late in (0.1, 0.4, 0.6):
        for seed in range(4):
            body, errors = _sparse_power_night(1.0, 1.0, seed, late_start=late)
            assert max(abs(e) for k, e in errors if k >= 30) < 0.08, (late, seed)
            assert abs(body.real_origin - 1000.0) < 0.06, (late, seed, body.real_origin - 1000.0)


def test_power_misreads_are_ignored():
    """The digit reader sometimes misses the leading digit (76 % -> 6 %).
    Such a reading must not reach the clock fit; a value that keeps coming
    back is real all the same (a big bang drop)."""
    from fnafbot import body as body_module

    body = body_module.RealBody.__new__(body_module.RealBody)
    body.last_power, body._odd_power, body._odd_count = 76, None, 0
    assert not body._power_reading_ok(6)        # lost leading digit
    assert not body._power_reading_ok(77)       # power never goes up
    assert body._power_reading_ok(75)           # a normal charge
    body.last_power = 10
    assert body._power_reading_ok(9)            # 10 -> 9 is real
    # A value that keeps coming back for POWER_MISREAD_PATIENCE seconds is real.
    body.last_power = 12
    clock = [100.0]
    body_module.time.perf_counter, real = (lambda: clock[0]), body_module.time.perf_counter
    try:
        results = []
        for _ in range(12):
            results.append(body._power_reading_ok(1))
            clock[0] += body_module.POWER_MISREAD_PATIENCE / 8
        assert not any(results[:8]) and any(results[8:])
    finally:
        body_module.time.perf_counter = real
