"""Human-labelled list of the game's reference images.

Each number is an image "handle" inside FiveNightsatFreddys.exe (v1.132, the
current Steam build). ``assets.py`` extracts them to ``cache/assets/NNNN.png``
so you can open any of them and see exactly what the label below describes.

The labels were made by extracting every image, grouping them by which camera
they belong to (automatically, by comparing with live screenshots) and then
checking each one by eye.

Letters used for who is visible:
    B = Bonnie, C = Chica, F = Freddy, G = Golden Freddy poster/hallucination
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CameraImage:
    """One possible picture for a camera, and who is in it."""

    handle: int
    occupants: frozenset[str] = field(default_factory=frozenset)
    note: str = ""
    # False for pictures that differ from the empty room by only a few dark
    # pixels (Freddy hiding in 1B, 4A and 7). Through the TV static these are
    # indistinguishable from an empty room, so the vision code skips them and
    # the strategy never relies on spotting Freddy in those rooms.
    visible: bool = True


def _img(handle: int, who: str = "", note: str = "", visible: bool = True) -> CameraImage:
    return CameraImage(handle, frozenset(who), note, visible)


# ---------------------------------------------------------------------------
# Camera pictures, grouped by camera id
# ---------------------------------------------------------------------------

CAMERA_IMAGES: dict[str, list[CameraImage]] = {
    "1A": [  # Show Stage - tells us who has left the stage
        _img(20, "BCF", "all three on stage"),
        _img(3, "BCF", "all three, staring at the camera (rare)"),
        _img(69, "CF", "Bonnie gone"),
        _img(224, "BF", "Chica gone"),
        _img(225, "F", "only Freddy left"),
        _img(356, "F", "only Freddy, staring (rare)"),
        _img(485, "", "stage empty - Freddy is roaming"),
    ],
    "1B": [  # Dining Area
        _img(49, "", "empty"),
        _img(493, "F", "Freddy - only his eyes glint in the dark at the back", visible=False),
        _img(91, "B", "Bonnie standing far back"),
        _img(121, "B", "Bonnie close to the camera"),
        _img(216, "C", "Chica far back"),
        _img(223, "C", "Chica close to the camera"),
    ],
    "2A": [  # West Hall (Foxy runs down this hall)
        _img(44, "", "empty, hall light off"),
        _img(45, "", "empty, hall light on"),
        _img(207, "B", "Bonnie"),
        _img(242, "B", "Bonnie"),
        _img(341, "B", "Bonnie (light flicker)"),
    ],
    "2B": [  # W. Hall Corner (just outside the left door)
        _img(1, "", "empty"),
        _img(572, "", "empty, alternate poster (rare)"),
        _img(541, "G", "Golden Freddy poster - see vision.py for how this is handled"),
        _img(479, "B", "Bonnie"),
        _img(189, "B", "Bonnie"),
        _img(480, "B", "Bonnie staring at the camera"),
    ],
    "3": [  # Supply Closet
        _img(63, "", "empty"),
        _img(191, "B", "Bonnie"),
    ],
    "4A": [  # East Hall
        _img(68, "", "empty"),
        _img(547, "", "empty, crying-children posters (rare)"),
        _img(555, "", "empty, 'IT'S ME' on the wall (rare)"),
        _img(488, "F", "Freddy - very dark, hard to see", visible=False),
        _img(222, "C", "Chica far"),
        _img(227, "C", "Chica close"),
    ],
    "4B": [  # E. Hall Corner (just outside the right door)
        _img(50, "", "empty"),
        _img(550, "", "empty, newspaper variant (rare)"),
        _img(551, "", "empty, newspaper variant (rare)"),
        _img(552, "", "empty, newspaper variant (rare)"),
        _img(553, "", "empty, newspaper variant (rare)"),
        _img(452, "C", "Chica"),
        _img(477, "C", "Chica"),
        _img(221, "C", "Chica"),
        _img(487, "F", "Freddy - dark shape with glinting eyes"),
    ],
    "5": [  # Backstage
        _img(84, "", "empty"),
        _img(355, "", "empty, endoskeleton staring (rare)"),
        _img(206, "B", "Bonnie"),
        _img(556, "B", "Bonnie staring at the camera"),
    ],
    "7": [  # Restrooms
        _img(42, "", "empty"),
        _img(495, "F", "Freddy - hidden in the doorway shadow", visible=False),
        _img(218, "C", "Chica far"),
        _img(220, "C", "Chica close"),
    ],
    # Camera 6 (Kitchen) shows no picture at all ("CAMERA DISABLED - AUDIO ONLY").
}

# ---------------------------------------------------------------------------
# Pirate Cove (camera 1C): Foxy's progress
# ---------------------------------------------------------------------------

# Foxy has four stages. Stage 3 means he has left and is about to run (or is
# running) down the West Hall toward the LEFT door.
FOXY_STAGE_IMAGES: dict[int, int] = {
    67: 0,   # curtain closed
    212: 1,  # peeking out between the curtains
    339: 2,  # stepping out of the cove
    241: 3,  # cove empty - he is gone
    554: 3,  # cove empty, sign says "IT'S ME" (rare)
}

# Frames of Foxy sprinting down the West Hall (camera 2A). Seeing ANY of these
# means: close the left door right now.
FOXY_RUNNING_IMAGES: list[int] = [
    245, 246, 247, 248, 249, 251,
    281, 282, 283, 284, 285, 286, 287, 288, 289, 290, 291, 293,
    303, 307,
    328, 330, 331, 332, 333, 334, 335, 336, 337, 338,
]

# ---------------------------------------------------------------------------
# Office pictures (1600 px wide, see layout.OFFICE_WIDTH)
# ---------------------------------------------------------------------------

OFFICE_NORMAL = 40              # lights off, nothing happening
OFFICE_LEFT_LIGHT_EMPTY = 59    # left hall light on, doorway empty
OFFICE_LEFT_LIGHT_BONNIE = 226  # left hall light on, Bonnie in the doorway
OFFICE_RIGHT_LIGHT_EMPTY = 128  # right hall light on, window empty
OFFICE_RIGHT_LIGHT_CHICA = 228  # right hall light on, Chica in the window
OFFICE_POWER_OUT = 305          # power ran out: dark office
OFFICE_POWER_OUT_FREDDY = 306   # power out: Freddy's face glowing in the left door

# ---------------------------------------------------------------------------
# HUD digit sprites: digit value -> image handle
# ---------------------------------------------------------------------------

# Each font matched the live HUD with a score of 1.0 (pixel perfect).
# "Power left: 97%" uses this 18x22 font, drawn at y = 624.
POWER_FONT = {0: 53, 1: 82, 2: 83, 3: 85, 4: 86, 5: 87, 6: 88, 7: 124, 8: 129, 9: 147}
# "Night 1" uses this 14x17 font.
NIGHT_FONT = {0: 188, 1: 192, 2: 193, 3: 194, 4: 195, 5: 196, 6: 197, 7: 198, 8: 199, 9: 200}
# "12 AM" uses this 24x30 font.
CLOCK_FONT = {0: 250, 1: 253, 2: 254, 3: 255, 4: 256, 5: 257, 6: 258, 7: 259, 8: 260, 9: 261}

# The word "Usage:" under the power readout. If it is on screen, a night is
# in progress and the HUD is visible (office or cameras).
USAGE_LABEL = 190

# Menu text sprites, used to know which screen is showing (score 0.98 - 1.0).
TITLE_CONTINUE = 450      # "Continue" on the title screen
TITLE_SIXTH_NIGHT = 444   # "6th Night" (only once the game is beaten)
TITLE_CUSTOM_NIGHT = 527  # "Custom Night" (only once night 6 is beaten)
CUSTOM_READY_BUTTON = 531 # "READY" on the Custom Night screen

# Room-name labels shown above the camera map, used to confirm which camera
# is on screen. Handle -> camera id. All are drawn with their top-left corner
# at about (832, 292); the match score on live screenshots is 0.94 - 0.999.
CAMERA_NAME_LABELS = {
    55: "1A", 73: "1B", 74: "1C", 75: "2A", 77: "2B", 51: "3",
    80: "4A", 76: "4B", 72: "5", 79: "6", 78: "7",
}
