"""The status panel's words (fnafbot/narrator.py)."""

from fnafbot import narrator


def test_camera_flip_says_freddy_when_he_is_on_4b():
    # The panel used to say "Camera flip to hold Foxy" while the camera was
    # really staring at Freddy on 4B.
    text = narrator.narrate("Camera flip to hold Foxy (resting on 4B)", {"Freddy": "at 4B"})
    assert "Freddy" in text
    text = narrator.narrate("Camera flip to hold Foxy (resting on 4B)", {"Freddy": "not at 4B"})
    assert "Freddy" not in text and "4B" in text


def test_animatronics_at_the_doors():
    assert narrator.narrate("BONNIE AT LEFT DOOR - door closed (seen in doorway)") == "Oh no! Bonnie's here! Left door SHUT"
    assert "Chica" in narrator.narrate("CHICA AT RIGHT DOOR - door closed (just in time)")
    assert narrator.narrate("FOXY LEFT THE COVE - closing doors").startswith("FOXY IS COMING")


def test_unknown_messages_pass_through():
    assert narrator.narrate("Warm-up: every camera once") == "Warm-up: every camera once"


def test_power_comment_follows_the_winning_pace():
    # Live 4/20 #28 (won with 11 %): 65 % at 213 s, 35 % at 394 s - on track.
    assert narrator.power_comment(65, 213, 7)[1] is False
    assert narrator.power_comment(35, 394, 7)[1] is False
    # Behind a winning pace but not yet doomed.
    text, warn = narrator.power_comment(33, 306, 7)
    assert warn and "lower than expected" in text
    # Only the game's own drain left to pay for.
    text, warn = narrator.power_comment(7, 480, 7)
    assert warn and "critical" in text


def test_night_over_words():
    assert narrator.night_over_message(True, 11).startswith("6 AM!")
    assert "jumpscared" in narrator.night_over_message(False, 40)
    assert "Out of power" in narrator.night_over_message(False, 0)
