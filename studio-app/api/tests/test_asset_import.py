"""Import of local generations with provenance (asset_import.py): the file must match its manifest, the original bytes are
stored unchanged, an import is always a candidate (never approved), the owner's existing approval flows decide it, a
mask links to its pose, a reverse plate links to its wide plate, and the pose dimension round-trips. Rows from before
the pose dimension (NULL) behave exactly as before. No network, nothing generated."""
import base64
import hashlib
import io
import unittest

from helpers import Env

from PIL import Image, ImageDraw


def png(size=(200, 300), transparent=False, colour=(209, 209, 209), mode=None) -> bytes:
    """A small figure: on a transparent background (a cut-out) or on flat grey (as the image route returns it)."""
    if transparent:
        im = Image.new("RGBA", size, (0, 0, 0, 0))
    else:
        im = Image.new(mode or "RGB", size, colour)
    d = ImageDraw.Draw(im)
    w, h = size
    d.ellipse([w * 0.3, h * 0.05, w * 0.7, h * 0.35], fill=(240, 220, 190, 255) if transparent else (240, 220, 190), outline="black")
    d.rectangle([w * 0.4, h * 0.35, w * 0.6, h * 0.7], fill=(60, 90, 160, 255) if transparent else (60, 90, 160), outline="black")
    d.line([w * 0.45, h * 0.7, w * 0.4, h * 0.95], fill="black", width=4)
    d.line([w * 0.55, h * 0.7, w * 0.6, h * 0.95], fill="black", width=4)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def manifest(raw: bytes, **kw) -> dict:
    im = Image.open(io.BytesIO(raw))
    m = {"kind": "pose", "file_name": "test-candidate-01.png", "sha256": sha(raw), "width": im.width,
         "height": im.height, "expression": "neutral",
         "generated": {"at": "2026-11-24", "by": "codex-cli 0.165.0, ChatGPT sign-in", "how": "one call, one image",
                       "prompt": "[Attached reference images: ./reference-identity.png]\nDraw ONE image.",
                       "prompt_file": "prompts/prompt-test.txt",
                       "references": [{"role": "identity", "file": "references/identity.png", "sha256": "a" * 64}],
                       "session_id": "01a20cb4-b4ce-7592-a9aa-fe6327c66e9a",
                       "original_path": "~/.codex/generated_images/01a20cb4/exec-1.png"}}
    m.update(kw)
    return m


def body(raw: bytes, **kw) -> dict:
    return {"file_base64": base64.b64encode(raw).decode(), "manifest": manifest(raw, **kw)}


class AssetImportTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        r = self.c.post("/api/characters", json={"key": "ralph", "name": "Ralph", "scope": "recurring"})
        self.assertEqual(r.status_code, 201, r.text)
        self.cid = r.json()["id"]

    def tearDown(self):
        self.env.close()

    def char(self):
        return next(x for x in self.c.get("/api/characters").json() if x["id"] == self.cid)

    def asset(self, aid):
        return next(a for a in self.char()["assets"] if a["id"] == aid)

    def imp(self, raw, status=201, **kw):
        r = self.c.post(f"/api/characters/{self.cid}/import", json=body(raw, **kw))
        self.assertEqual(r.status_code, status, r.text)
        return r.json()

    def decide(self, aid, decision="approve", status=200):
        r = self.c.post(f"/api/character-assets/{aid}/decision", json={"decision": decision})
        self.assertEqual(r.status_code, status, r.text)
        return r.json()

    @staticmethod
    def mask_block(source: bytes) -> dict:
        return {"method": "hand-drawn polygons over the source; grey background removed inside them",
                "script": "masks.py figure_mask", "script_sha256": "b" * 64, "source_sha256": sha(source),
                "spec": {"ellipses": [[10, 10, 50, 50]], "polygons": [[[1, 1], [5, 1], [5, 5]]]}}

    def seated(self, n=1, **kw):
        raw = png((200 + n, 300))
        return raw, self.imp(raw, **{"posture": "seated", "body_turn": "left", **kw})["asset_id"]

    # ------------------------------------------------------------------ import
    def test_import_creates_a_candidate_with_provenance_and_the_original_bytes(self):
        from oddstudio.db import new_session
        from oddstudio.models import CharacterAsset
        from oddstudio.storage import storage
        raw, aid = self.seated()
        a = self.asset(aid)
        self.assertEqual((a["kind"], a["status"], a["imported"]), ("pose", "review", True))
        self.assertEqual((a["posture"], a["body_turn"], a["view"], a["framing"]), ("seated", "left", None, None))
        self.assertEqual(a["sha256"], sha(raw))
        self.assertEqual(a["provenance"]["generated"]["by"], "codex-cli 0.165.0, ChatGPT sign-in")
        self.assertEqual(a["provenance"]["generated"]["original_path"], "~/.codex/generated_images/01a20cb4/exec-1.png")
        full = self.c.get(f"/api/character-assets/{aid}/provenance").json()["provenance"]
        self.assertIn("Draw ONE image.", full["generated"]["prompt"])
        self.assertEqual(full["generated"]["references"][0]["sha256"], "a" * 64)
        self.assertEqual(full["generated"]["session_id"], "01a20cb4-b4ce-7592-a9aa-fe6327c66e9a")
        self.assertTrue(full["sha256_verified"])
        self.assertEqual(full["imported_by"], "owner@example.com")
        with new_session() as s:
            key = s.get(CharacterAsset, aid).storage_key
        self.assertEqual(storage().local_path(key).read_bytes(), raw, "the original bytes, unchanged")
        self.assertEqual(self.char()["art_status"], "none", "an import changes nothing until the owner decides")

    def test_a_sha256_or_size_mismatch_is_refused_and_nothing_is_stored(self):
        raw = png()
        b = body(raw)
        b["manifest"]["sha256"] = sha(raw + b"x")
        r = self.c.post(f"/api/characters/{self.cid}/import", json=b)
        self.assertEqual(r.status_code, 422)
        self.assertIn("sha256", r.text)
        self.imp(raw, status=422, width=999, posture="seated")
        self.assertEqual(self.char()["assets"], [], "nothing stored")
        self.imp(png(), status=422, kind="pose", expression="neutral")   # a standing front pose must be a cut-out
        self.imp(png((210, 300)), status=422, kind="portrait", posture="seated")
        self.assertEqual(self.char()["assets"], [])

    def test_an_import_is_never_approved(self):
        raw = png((201, 300))
        b = body(raw, posture="seated")
        b["manifest"]["status"] = "approved"
        self.assertEqual(self.c.post(f"/api/characters/{self.cid}/import", json=b).status_code, 422, "no status field")
        for kind, extra in (("pose", {"posture": "seated"}), ("expression-sheet", {"expressions": ["alert", "sad"]}),
                            ("back-view", {"posture": "seated"})):
            aid = self.imp(png((220 + len(kind), 300)), kind=kind, **extra)["asset_id"]
            self.assertEqual(self.asset(aid)["status"], "review")
        self.assertEqual(self.asset(aid)["view"], "back", "a back view is seen from the back")
        c = self.char()
        self.assertEqual((c["expressions"], c["art_status"]), ({}, "none"))
        # the sheet decision approves the studio's own sheet only: imported candidates are decided one by one
        self.assertEqual(self.c.post(f"/api/characters/{self.cid}/sheet/decision", json={"decision": "approve"}).status_code, 409)
        self.assertTrue(all(a["status"] == "review" for a in self.char()["assets"]))

    def test_the_existing_approve_flow_approves_an_imported_pose_which_then_works_as_a_normal_pose(self):
        from oddstudio.db import new_session
        from oddstudio.head_angles import neutral_pose
        from oddstudio.models import Character, Job
        aid = self.imp(png(transparent=True))["asset_id"]          # standing, front: the default dimension
        a = self.asset(aid)
        self.assertEqual((a["status"], a["posture"]), ("review", None))
        c = self.decide(aid)
        self.assertEqual(c["art_status"], "approved")
        self.assertEqual(c["expressions"], {"neutral": f"p{aid}"})
        with new_session() as s:
            self.assertEqual(neutral_pose(s, s.get(Character, self.cid)).id, aid, "the 3D rig's front reference")
            self.assertEqual(s.query(Job).filter_by(kind="rig_check", character_id=self.cid).count(), 1, "rig check queued")
        # a seated pose of the same expression is kept apart: approving it retires nothing standing
        _, sid = self.seated()
        c = self.decide(sid)
        self.assertEqual(c["expressions"], {"neutral": f"p{aid}"}, "a seated pose never stands in for an expression")
        self.assertEqual(self.asset(aid)["status"], "approved")
        self.assertEqual(self.asset(sid)["status"], "approved")
        _, sid2 = self.seated(2)
        self.decide(sid2)
        self.assertEqual(self.asset(sid)["status"], "rejected", "one approved pose per expression AND dimension")
        self.assertEqual(self.asset(aid)["status"], "approved")
        # a rejected import is just rejected
        _, sid3 = self.seated(3, body_turn="right")
        self.assertEqual(self.decide(sid3, "reject")["art_status"], "approved")
        self.assertEqual(self.asset(sid3)["status"], "rejected")

    def test_a_mask_links_to_its_parent(self):
        raw, parent = self.seated()
        mask = png((201, 300), transparent=True)
        spec = self.mask_block(raw)
        self.imp(png((201, 300)), status=422, kind="mask", parent_asset_id=parent, mask=spec)    # no alpha
        self.imp(mask, status=422, kind="mask", mask=spec)                                       # no parent
        self.imp(mask, status=422, kind="mask", parent_asset_id=parent + 99, mask=spec)          # not this character's
        mid = self.imp(mask, kind="mask", parent_asset_id=parent, mask=spec, posture="seated", body_turn="left")["asset_id"]
        m = self.asset(mid)
        self.assertEqual((m["kind"], m["parent_asset_id"], m["status"]), ("mask", parent, "review"))
        self.assertEqual(self.c.get(f"/api/character-assets/{mid}/provenance").json()["provenance"]["mask"], spec)
        self.assertEqual(self.c.get(f"/api/character-assets/{mid}/provenance").json()["provenance"]["sha256"], sha(mask),
                         "the mask has its own provenance (its own file, its own manifest)")
        self.imp(png((205, 300), transparent=True), status=422, kind="mask", parent_asset_id=parent,
                 mask=self.mask_block(b"another image"))                                  # not made from this parent
        self.decide(mid)
        self.assertEqual(self.asset(mid)["status"], "approved", "the existing decision flow decides a mask")
        self.assertEqual(self.char()["expressions"], {}, "a mask is never an expression")
        # a mask imported before its pose (named by the pose's file sha256) is linked when the pose arrives
        later = png((230, 300))
        mask2 = png((230, 300), transparent=True)
        m2 = self.imp(mask2, kind="mask", parent_sha256=sha(later), mask=self.mask_block(later))["asset_id"]
        self.assertIsNone(self.asset(m2)["parent_asset_id"])
        p2 = self.imp(later, posture="seated", body_turn="left")["asset_id"]
        self.assertEqual(self.asset(m2)["parent_asset_id"], p2)
        self.imp(later, status=409, posture="seated")                                            # already imported

    def test_set_import_with_reverse_of(self):
        wide, rev = png((1672, 941)), png((1672, 941), colour=(180, 170, 160))
        r = self.c.post("/api/sets/import", json=body(wide, kind="set-plate", label="Library study (wide)",
                                                      plate_view="wide", expression=""))
        self.assertEqual(r.status_code, 201, r.text)
        w = r.json()
        self.assertEqual((w["id"], w["status"], w["imported"], w["kept"]), ("library-study-wide", "candidate", True, True))
        self.assertEqual(w["provenance"]["sha256"], sha(wide))
        self.assertTrue(w["blocking"]["floor_y"] > 0, "the same proposed staging as a generated candidate")
        bad = self.c.post("/api/sets/import", json=body(rev, kind="set-plate", label="Study reverse", reverse_of="nope"))
        self.assertEqual(bad.status_code, 422)
        r = self.c.post("/api/sets/import", json=body(rev, kind="set-plate", label="Library study (reverse)",
                                                      reverse_of=sha(wide)))
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["reverse_of"], "library-study-wide", "named by the wide plate's sha256, linked by id")
        dup = self.c.post("/api/sets/import", json=body(wide, kind="set-plate", label="Again"))
        self.assertEqual(dup.status_code, 409)
        mism = body(png((1600, 900)), kind="set-plate", label="Mismatch")
        mism["manifest"]["sha256"] = "0" * 64
        self.assertEqual(self.c.post("/api/sets/import", json=mism).status_code, 422)
        listed = {x["id"]: x for x in self.c.get("/api/sets").json()["sets"]}
        self.assertEqual(listed["library-study-reverse"]["reverse_of"], "library-study-wide")
        self.assertEqual(listed["library-study-wide"]["status"], "candidate")
        # the existing approval flow, unchanged
        d = self.c.post("/api/sets/library-study-wide/decide", json={"decision": "approve"})
        self.assertEqual(d.status_code, 200, d.text)
        from oddstudio import sets
        from oddstudio.db import new_session
        with new_session() as s:
            self.assertIn("library-study-wide", sets.approved(s))
            self.assertNotIn("library-study-reverse", sets.approved(s))

    def test_an_imported_original_is_immutable(self):
        from oddstudio.db import new_session
        from oddstudio.models import CharacterAsset
        from oddstudio.storage import storage
        raw, aid = self.seated()
        with new_session() as s:
            key = s.get(CharacterAsset, aid).storage_key
        self.assertIn(sha(raw), key, "the key is the file's own sha256")
        self.imp(raw, status=409, posture="seated")                       # no re-upload over it
        self.c.put(f"/api/character-assets/{aid}/dimension", json={"posture": "seated", "body_turn": "right"})
        self.decide(aid)
        self.decide(aid, "reject")
        with new_session() as s:                                          # even after it is binned
            s.get(CharacterAsset, aid).status = "binned"
            s.commit()
        r = self.c.post(f"/api/characters/{self.cid}/import", json=body(raw, posture="seated"))
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("never replaced", r.text)
        self.assertEqual(storage().local_path(key).read_bytes(), raw, "decisions and dimension edits never touch the file")
        wide = png((640, 360))
        self.assertEqual(self.c.post("/api/sets/import", json=body(wide, kind="set-plate", label="Room one")).status_code, 201)
        from oddstudio import sets
        with new_session() as s:
            recs = sets.records(s)
            recs["room-one"]["status"] = "binned"
            sets.save(s, recs)
        r = self.c.post("/api/sets/import", json=body(wide, kind="set-plate", label="Room one"))
        self.assertEqual(r.status_code, 409, "a binned plate's original is not written again")

    def test_a_malformed_manifest_is_refused_with_a_precise_message(self):
        raw = png((240, 300))
        b = body(raw, posture="seated")
        del b["manifest"]["generated"]
        r = self.c.post(f"/api/characters/{self.cid}/import", json=b)
        self.assertEqual(r.status_code, 422)
        self.assertIn("generated", r.text)
        b = body(raw, posture="seated")
        b["manifest"]["generated"]["by"] = ""
        r = self.c.post(f"/api/characters/{self.cid}/import", json=b)
        self.assertEqual(r.status_code, 422)
        self.assertIn('"by"', r.text)
        r = self.c.post(f"/api/characters/{self.cid}/import", json=body(
            raw, posture="seated", approved={"by": "owner", "at": "2026-11-24"}, rejected={"by": "owner", "at": "2026-11-24"}))
        self.assertEqual(r.status_code, 422)
        self.assertIn("approved and rejected are both recorded", r.text)
        b = body(raw, posture="seated")
        b["manifest"]["review_status"] = "APPROVED"
        r = self.c.post(f"/api/characters/{self.cid}/import", json=b)
        self.assertEqual(r.status_code, 422)
        self.assertIn("review_status", r.text, "one status string is not a field: the states are distinct")
        r = self.c.post(f"/api/characters/{self.cid}/import", json=body(raw, kind="mask", parent_sha256="c" * 64))
        self.assertEqual(r.status_code, 422)
        self.assertIn("mask block", r.text)
        self.assertEqual(self.char()["assets"], [])

    def test_a_recorded_approval_is_information_only(self):
        rec = {"approved": {"by": "owner", "at": "2026-11-24", "note": "approved as the seated master (manifest only)"},
               "reviewed": {"by": "owner", "at": "2026-11-24", "notes": ["chair a little light"]}}
        _, aid = self.seated(**rec)
        a = self.asset(aid)
        self.assertEqual(a["status"], "review", "still a candidate: the owner's decision in the studio counts")
        self.assertEqual(a["provenance"]["approved"]["note"], "approved as the seated master (manifest only)")
        self.assertEqual(a["provenance"]["reviewed"]["notes"], ["chair a little light"])
        self.assertIsNone(a["provenance"]["rejected"])
        r = self.c.post("/api/sets/import", json=body(png((640, 360)), kind="set-plate", label="Room two", **rec))
        self.assertEqual(r.json()["status"], "candidate")
        self.assertEqual(r.json()["provenance"]["approved"]["by"], "owner")

    def test_the_pose_dimension_round_trips(self):
        _, aid = self.seated(framing="chest_up", view="front")
        a = self.asset(aid)
        self.assertEqual((a["posture"], a["body_turn"], a["view"], a["framing"]), ("seated", "left", "front", "chest_up"))
        r = self.c.put(f"/api/character-assets/{aid}/dimension", json={"posture": "seated", "body_turn": "right", "framing": "bust"})
        self.assertEqual(r.status_code, 200, r.text)
        a = self.asset(aid)
        self.assertEqual((a["posture"], a["body_turn"], a["view"], a["framing"]), ("seated", "right", None, "bust"))
        self.assertEqual(self.c.put(f"/api/character-assets/{aid}/dimension", json={"posture": "lying"}).status_code, 422)
        # an opaque picture cannot become a standing front pose (no feet anchor): refused, unchanged
        self.assertEqual(self.c.put(f"/api/character-assets/{aid}/dimension", json={}).status_code, 422)
        self.assertEqual(self.asset(aid)["body_turn"], "right")
        self.decide(aid)
        self.assertEqual(self.c.put(f"/api/character-assets/{aid}/dimension", json={"posture": "standing"}).status_code, 409,
                         "an approved asset keeps its dimension")
        self.imp(png((260, 300)), status=422, posture="crouching")

    def test_old_rows_with_no_dimension_behave_as_before(self):
        """A studio pose (NULL dimension, no provenance) is decided exactly as before, alone or with the sheet."""
        from oddstudio.db import new_session
        from oddstudio.models import CharacterAsset
        from oddstudio.storage import storage
        import tempfile
        from pathlib import Path
        ids = []
        with new_session() as s, tempfile.TemporaryDirectory() as tmp:
            for exp in ("neutral", "neutral", "happy"):
                f = Path(tmp) / f"{exp}-{len(ids)}.png"
                f.write_bytes(png(transparent=True))
                key = f"characters/ralph/poses/{f.name}"
                storage().put_file(key, f, "image/png")
                a = CharacterAsset(character_id=self.cid, kind="pose", expression=exp, storage_key=key, width=200, height=300,
                                   feet={"x": 100, "y": 285}, figure_height=270, status="review")
                s.add(a)
                s.flush()
                ids.append(a.id)
            s.commit()
        a = self.asset(ids[0])
        self.assertEqual((a["posture"], a["imported"], a["provenance"], a["parent_asset_id"]), (None, False, None, None))
        self.decide(ids[0])
        c = self.decide(ids[1])
        self.assertEqual(self.asset(ids[0])["status"], "rejected", "one approved pose per expression, as before")
        self.assertEqual(c["expressions"], {"neutral": f"p{ids[1]}"})
        _, imported = self.seated()
        r = self.c.post(f"/api/characters/{self.cid}/sheet/decision", json={"decision": "approve"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["expressions"], {"neutral": f"p{ids[1]}", "happy": f"p{ids[2]}"})
        self.assertEqual(self.asset(imported)["status"], "review", "the sheet decision leaves imported candidates alone")
        # a studio pose of another kind than pose is still not decided here
        self.assertEqual(self.c.post("/api/character-assets/999999/decision", json={"decision": "approve"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
