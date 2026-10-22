"""Where everything is on screen, and how long the game takes to react.

Like BTD6bot's ``locations.py``, every clickable spot and every region the
vision code reads is defined here, in one place, in *game coordinates*
(1280 x 720, see screen.py). If a game update ever moves a button, this is
the only file that needs editing.

All timings below were measured on the real game (v1.132) with
``tools/measure_timings.py``; re-run that tool if something feels off.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Box:
    """A rectangle in game coordinates: left, top, right, bottom (exclusive)."""

    x0: int
    y0: int
    x1: int
    y1: int

    def crop(self, frame):
        """Return the part of ``frame`` inside this box."""
        return frame[self.y0:self.y1, self.x0:self.x1]

    @property
    def center(self) -> tuple[int, int]:
        return (self.x0 + self.x1) // 2, (self.y0 + self.y1) // 2


# ---------------------------------------------------------------------------
# The office
# ---------------------------------------------------------------------------

# The office picture is 1600 px wide but the screen is only 1280 px, so the
# view slides ("pans") left and right depending on where the mouse is.
OFFICE_WIDTH = 1600
MAX_PAN = OFFICE_WIDTH - 1280  # 320: pan offset when fully looking right

# Mouse x positions that make the office pan. Measured:
#   x <= 150         -> fastest pan left (~680 px/s, full sweep in ~0.5 s)
#   x ~ 300          -> medium (~380 px/s)
#   x ~ 450          -> slow (~130 px/s)
#   560 <= x <= 720  -> dead zone, the view stays still
# (the right side mirrors this).
PAN_LEFT_X = 5
PAN_RIGHT_X = 1275
PAN_STILL_X = 640
FULL_PAN_SECONDS = 0.55  # time to sweep from one side to the other (+ margin)

# Door/light buttons. These are only on screen when the view is panned all
# the way to that side, so the bot always pans first, then clicks.
LEFT_DOOR_BUTTON = (55, 335)
LEFT_LIGHT_BUTTON = (55, 460)
RIGHT_DOOR_BUTTON = (1220, 350)
RIGHT_LIGHT_BUTTON = (1220, 475)

# Second click spot on each light button, used to switch the light OFF.
# Windows turns two clicks on the same spot within ~0.5 s into a
# "double-click", and the game ignores the second click of a double-click.
# Clicking ~20 px away (still on the button) avoids that, so the light can be
# switched off right after it is checked instead of wasting half a second.
LEFT_LIGHT_BUTTON_OFF = (55, 482)
RIGHT_LIGHT_BUTTON_OFF = (1220, 497)

# The door button glows red when the door is open and green when closed.
# Sampled from the middle of each button (screen coords, view fully panned).
LEFT_DOOR_LAMP = Box(42, 300, 70, 370)
RIGHT_DOOR_LAMP = Box(1207, 315, 1235, 385)
LEFT_LIGHT_LAMP = Box(42, 425, 70, 495)
RIGHT_LIGHT_LAMP = Box(1207, 440, 1235, 510)

# ---------------------------------------------------------------------------
# The camera monitor
# ---------------------------------------------------------------------------

# Hovering the bar flips the monitor up (or back down). The game has two
# invisible hover zones (positions read from the game's level data):
#   * "flip down", centred at (589, 599): touching it RE-ARMS the flip;
#   * "flip up", the bar itself: touching it (when armed) flips the monitor.
# So every flip is: rest on the re-arm spot, then on the bar, each for at
# least a couple of frames. Measured live: 32/32 flips worked this way, and
# 0/32 when re-arming from (640, 560), which is outside the re-arm zone.
CAMERA_BAR = Box(258, 648, 852, 690)
CAMERA_REARM = (589, 599)       # inside "flip down"; also in the pan dead zone
CAMERA_TRIGGER = (554, 668)     # centre of the visible bar
CAMERA_HOVER_SECONDS = 0.04     # how long to rest on each spot (2-3 frames)

# Measured: the camera picture appears 0.50-0.61 s after touching the bar;
# it disappears ~0.05 s after touching it again, then the monitor animation
# needs a little longer before the next flip is accepted.
CAMERA_UP_SECONDS = 0.55
CAMERA_DOWN_SECONDS = 0.35

# Measured: a camera switch shows the new feed within ~0.05 s, followed by a
# short burst of static. We wait a little longer before trusting the picture.
CAMERA_SWITCH_SECONDS = 0.12

# Camera buttons on the map (centre of each "CAM xx" box).
CAMERA_BUTTONS: dict[str, tuple[int, int]] = {
    "1A": (983, 353),  # Show Stage
    "1B": (964, 409),  # Dining Area
    "1C": (932, 487),  # Pirate Cove
    "2A": (983, 603),  # West Hall
    "2B": (983, 643),  # W. Hall Corner
    "3": (900, 585),   # Supply Closet
    "4A": (1089, 603), # East Hall
    "4B": (1089, 643), # E. Hall Corner
    "5": (858, 436),   # Backstage
    "6": (1187, 568),  # Kitchen (audio only)
    "7": (1196, 436),  # Restrooms
}

# The name of the room being viewed is printed here (e.g. "Pirate Cove").
CAMERA_NAME = Box(820, 285, 1110, 325)

# The camera map (white boxes and lines). If this area looks like the map,
# the monitor is up.
CAMERA_MAP = Box(830, 330, 1240, 670)

# The bot's own status panel (overlay.py) is drawn here, top centre. Nothing
# the vision code relies on is in this strip, and it is listed in
# CAMERA_IGNORE below so the panel never confuses the camera checks.
OVERLAY = Box(430, 0, 850, 58)

# Parts of a camera picture that are covered by the HUD/map and must be
# ignored when comparing the picture to the reference images.
CAMERA_IGNORE = (
    Box(800, 280, 1280, 720),  # map + room name
    Box(1100, 0, 1280, 110),   # clock and night number
    Box(0, 600, 800, 720),     # power/usage text and the flip bar
    Box(0, 0, 160, 70),        # recording dot
    OVERLAY,                   # the bot's status panel
)

# ---------------------------------------------------------------------------
# HUD text (visible both in the office and on the cameras)
# ---------------------------------------------------------------------------

POWER_DIGITS = Box(180, 620, 240, 652)   # "97" in "Power left: 97%"
USAGE_BARS = Box(118, 658, 225, 690)     # 1-5 coloured bars
USAGE_FIRST_BAR_X = 120                  # left edge of the first bar
USAGE_BAR_PITCH = 21                     # distance from one bar to the next
CLOCK_DIGITS = Box(1130, 25, 1195, 65)   # "12" in "12 AM"
NIGHT_DIGIT = Box(1215, 68, 1240, 92)    # "1" in "Night 1"

# ---------------------------------------------------------------------------
# Menus
# ---------------------------------------------------------------------------

MENU_NEW_GAME = (270, 420)
MENU_CONTINUE = (270, 490)
MENU_SIXTH_NIGHT = (285, 566)    # only shown once the game is beaten
MENU_CUSTOM_NIGHT = (320, 634)   # only shown once night 6 is beaten
