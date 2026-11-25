"""Shot frames: one storyboard frame per shot of the reference video (the notes), then one per recorded line after
the notes end; each shot on the side of the room its people belong to, with only those people."""
import unittest

from oddstudio.shot_frames import plan_shots, side_of

DESK, FAM = "desk-442", "family-444"
SIDES = {DESK: ["uncle-mortimer", "solicitor"],
         FAM: ["ralph", "sidney", "winifred", "ronald", "young-wife", "mr-crabtree", "mrs-crabtree"]}


def r(t0, t1, shot, *who, emo="neutral"):
    return {"start": t0, "end": t1, "shot": shot, "roles": [{"who": w, "emotion": emo} for w in who]}


class PlanTest(unittest.TestCase):
    def test_side_follows_who_is_on_screen(self):
        self.assertEqual(side_of(["uncle-mortimer"], SIDES, FAM), DESK)
        self.assertEqual(side_of(["ralph"], SIDES, FAM), FAM)
        self.assertEqual(side_of(["uncle-mortimer", "ralph", "sidney"], SIDES, FAM), FAM)
        self.assertEqual(side_of([], SIDES, FAM), FAM)

    def test_notes_then_script_lines(self):
        ranges = [r(0, 2, "wide", "uncle-mortimer", "ralph", "sidney"), r(2, 4, "close", "uncle-mortimer", emo="serious"),
                  r(4, 6, "medium", "ralph")]
        lines = [{"id": "l1", "start": 0.5, "end": 3.5}, {"id": "l2", "start": 7.0, "end": 9.0}]
        scenes = [{"line_ids": ["l1"], "set": DESK, "staging": {}, "shots": {"l1": "wide"}},
                  {"line_ids": ["l2"], "set": FAM, "staging": {"uncle-mortimer": "off", "mr-crabtree": "off", "mrs-crabtree": "off"},
                   "shots": {"l2": "close"}}]
        shots = plan_shots(ranges, lines, scenes, SIDES, FAM)
        self.assertEqual([s["index"] for s in shots], [1, 2, 3, 4])
        self.assertEqual((shots[0]["side"], shots[0]["people"]), (FAM, ["ralph", "sidney"]))   # Mortimer is not drawn on their side
        self.assertEqual((shots[1]["side"], shots[1]["people"], shots[1]["shot"]), (DESK, ["uncle-mortimer"], "close"))
        self.assertEqual(shots[1]["emotions"], {"uncle-mortimer": "serious"})
        self.assertEqual(shots[3]["source"], "script (l2)")
        self.assertEqual(shots[3]["people"], ["ralph", "sidney", "winifred", "ronald", "young-wife"])
        self.assertEqual(shots[3]["shot"], "medium")                  # several people: a close shot becomes medium


if __name__ == "__main__":
    unittest.main()
