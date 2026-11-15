# AP-85 Track A: owner contact-sheet review

**Status: TRACK A FORMALLY ACCEPTED BY THE OWNER ON 2026-11-15.**
- **Passed owner review:** A1, A2, A3a, A3b and A4.
- **Accepted implementation and corrected evidence:** commit `305a50474ee3433af16104294e921631a346a8a4`.
- **Acceptance record:** commit `310a74762926d809826bc0000c4f4e90cc5e01c1` (AP-85 plan §5.4, `DECISIONS.md`).
- **Basis:** acceptance required both the automated checks A-1 to A-10 **and** the owner's review of these sheets (AP-85 plan §5.2).
- **Still open:** Track B has not started, and owner decisions M3 to M8 remain open.

**Track A only.** These sheets show the composition engine: placement, layering, timing, speaker attribution and camera framing. The acceptance covers this composition architecture only. These sheets are **not** identity evidence for any character (that is Track B). The blue body/green head figure is a **SYNTHETIC PLACEHOLDER, NOT ARTWORK**. It is a test fixture, not Character 02, not production artwork and not a design. No Character 02 artwork exists.

## Review history

1. **First review (sheets at `e624a91`).** The owner's findings:
   - A1 passes.
   - A3a and A3b pass the technical layer-order checks.
   - **A2 needs correcting:** after the positions are swapped, each bubble stayed on its original screen side, away from its speaker.
   - **A4 needs correcting:** shots 2 and 3 did not show distinct subjects, shot 5 cut Character 01 at the left edge, and the head-pivot camera did not protect the composition.
2. **Corrections (`305a504`).** The engine was corrected (see below). The **A2 and A4** sheets were regenerated. The A1, A3a and A3b sheets were not regenerated: their scenes render byte-identically (`unchanged-check.json`), so their files are unchanged from `e624a91`.
3. **Owner acceptance (2026-11-15).** After reviewing the original and the corrected sheets, the owner formally accepted Track A. A1, A2, A3a, A3b and A4 passed owner review. This was recorded in commit `310a747`.

## What changed

**A2: bubble side follows the speaker.**
- Each bubble goes on the side of the screen where its speaker stands in that line's shot: left of the frame centre gives a left bubble, otherwise right. The tail points to the same side.
- The bubble style still comes only from the speaker's speech configuration and never from position.
- A speaker who is off camera (in a single on someone else) still gets a bubble on the side where it stands.
- A `speech.side` that a scene declares is now a checked constraint. If the speaker stands on the other side, the build fails rather than ignoring either the declaration or the position.

**A4: medium and close shots are composed.**
- Zoom levels are unchanged: medium 1.3×, close 1.5×. Character positions and relative scale are unchanged.
- The camera pans to centre the focus member as far as the background allows. Previously it only zoomed about the focus member's head.
- Every other member is either fully in frame or fully out of it, never cut by the left or right frame edge.
- When another member is in frame, the focus member must be clearly the most central figure. If a framing can't meet these rules, the build fails with an explanation.
- A shot can now explicitly ask for a single (`"single": true`), which shows only the focus member for that shot. A4's shots 2 to 5, whose captions already called them singles and reactions, now declare it.
- Why singles are needed here: with A4's staging (members 480 units apart) and a background that only just covers the frame, no pan at 1.3× or 1.5× can show one member without the other.
- Without `single`, the engine refuses those framings rather than cutting a member. A4's shot 5 as a two-shot is refused this way, and a regression test checks it.

## Files

| File | What it shows |
|---|---|
| `A1-annotated.png`, `A1-clean.png` | **A1 two-shot** (unchanged since `e624a91`). Character 01 on the left, placeholder on the right, 8 alternating lines, wide shots. |
| `A2-annotated.png`, `A2-clean.png` | **A2 swapped (corrected).** Positions swapped and z order reversed; bubbles now follow their speakers: Character 01 on the right, placeholder on the left. |
| `A3a-annotated.png`, `A3a-clean.png` | **A3a overlap** (unchanged since `e624a91`). Placeholder in front. Includes an overlap detail panel. |
| `A3b-annotated.png`, `A3b-clean.png` | **A3b overlap** (unchanged since `e624a91`). Character 01 in front. Includes an overlap detail panel. |
| `A4-annotated.png`, `A4-clean.png` | **A4 shot sequence (corrected).** Wide; single on the placeholder; single on Character 01; close reaction single on Character 01; close reaction single on the placeholder; wide. |
| `manifest.json` | Per scene: where it was generated from (A1 and A3 keep their original provenance; A2 and A4 record the engine source hashes), sample times, render-plan hashes, sheet hashes and each member's painted box per frame. |
| `unchanged-check.json` | A1, A3a, A3b, A5 and A6 before (`e624a91`) and after the corrections: render plan, generated assets and every renderer frame at 0.1 s steps are identical. |
| `generate-review-sheets.mjs` | Regenerates the sheets (local, $0, needs `FFMPEG`/`FFPROBE`; `SCENES=A2,A4` for a subset). |
| `fingerprint-frames.mjs` | Produces the fingerprints compared in `unchanged-check.json`. |

**Annotated sheets.** Each has a header with the scene's purpose, the cast, the shot sequence (singles marked) and what to inspect. Each line has one panel, sampled 60% through the line. In each panel:
- every member on camera has a dashed outline and a tag in its own colour: orange for `c01 · CHARACTER 01`, magenta for `ph · SYNTHETIC PLACEHOLDER, NOT ARTWORK`;
- the speaker's tag is filled and reads `SPEAKING`;
- the caption gives the speaker (marked "off camera" when relevant), the bubble style and side, the shot (camera, single, focus, zoom), each member's pose, and who is off camera.

**Clean sheets.** The same frames and captions with no overlays. The placeholder's on-figure label ("SYNTHETIC / PLACEHOLDER / NOT ARTWORK") is part of the rendered image on both versions.

## What to inspect

1. **A2 (corrected):**
   - every bubble sits on the side where its speaker stands: Character 01 (right) has right-hand bubbles, the placeholder (left) has left-hand bubbles, and each tail points that way;
   - the styles are still "him" for Character 01 and "neutral" for the placeholder, as in A1;
   - the placeholder uses its right-facing drawings (`p1-r`, `p2-r`); nothing is mirrored.
2. **A4 (corrected):**
   - shot 2 shows only the placeholder and shot 3 only Character 01, each framed toward the centre;
   - shot 4 (close, reaction) shows only Character 01 and shot 5 (close, reaction) only the placeholder, with no figure cut at the frame edge;
   - wide shots 1 and 6 show both;
   - in shots 4 and 5 the speaker is off camera, and its bubble sits on the side where it stands.
3. **The single convention (owner judgement):** a single takes the other member off camera for that shot, even where the framed area includes the spot where that member stands. This is the usual 2D "cheat" for shot/reverse-shot; positions and scale are not changed. Please judge whether it reads correctly.
4. **A1, A3a, A3b:** unchanged. See `unchanged-check.json`.

Facing: Character 01's registry declares no facings, so it always uses its drawings as drawn. How characters face each other with real artwork is still the open owner decision M7.

## How these were made

1. **Scene definitions:** `generate-review-sheets.mjs` evaluates them directly from the Track A test file `production/tests/ap85-track-a.test.mjs`, whose hash is recorded in `manifest.json`. The sheets therefore show exactly the scenes the checks ran on.
2. **Build:** the placeholder is written to a temporary folder by the test fixture. Each scene is compiled by the production pipeline (`compileProject` with `allowSynthetic: true`, which only tests and these scripts pass).
3. **Frames:** painted by the **unmodified** renderer; no video is encoded.
4. **Outlines:** taken from the pixels each member actually painted (the frame is painted again without that member), so the labels follow the render.

The scripts refuse to overwrite existing sheets unless `REPLACE=1` is set, and two runs give byte-identical output.

```bash
FFMPEG=... FFPROBE=... SCENES=A2,A4 REPLACE=1 node production/evidence/ap85/review/generate-review-sheets.mjs
FFMPEG=... FFPROBE=... OUT=/tmp/fp.json node production/evidence/ap85/review/fingerprint-frames.mjs
```
