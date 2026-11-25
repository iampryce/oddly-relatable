"""Staging "off": a character not in a scene's picture; a speaker who is off is heard, not seen (shot / reverse shot
with one narrator). The scene staging is editable on the storyboard."""
import unittest

from oddstudio.acting import seat_starts
from oddstudio.script_schema import STAGING_POSITIONS


class SeatStartsTest(unittest.TestCase):
    def test_off_is_not_on_stage_and_takes_no_seat(self):
        out, left = seat_starts({"uncle-mortimer": "off", "ralph": "seated", "sidney": "seated", "mr-crabtree": "standing"},
                                ["uncle-mortimer", "ralph", "sidney", "mr-crabtree"], 6)
        self.assertEqual(out, {"uncle-mortimer": "off", "ralph": "seat:0", "sidney": "seat:1", "mr-crabtree": "on"})
        self.assertEqual(left, [])

    def test_positions(self):
        self.assertEqual(STAGING_POSITIONS, ("seated", "standing", "off"))


if __name__ == "__main__":
    unittest.main()
