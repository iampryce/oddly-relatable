# AP-85 shadow correction: corrected A4 evidence

**Status: CORRECTION IMPLEMENTED; THE CORRECTED A4 EVIDENCE AWAITS OWNER VISUAL REVIEW.** The owner approved this corrective task on 2026-11-16. Nothing here replaces or re-accepts the accepted A4 evidence on the owner's behalf. The original accepted sheets stay unchanged in `../review/` (`A4-annotated.png`, `A4-clean.png`).

**Track A only.** The blue body/green head figure is a **SYNTHETIC PLACEHOLDER, NOT ARTWORK**, not Character 02.

**Correction commit:** `59e6f3ef2b224ebefd64e5588cd47018b0f30633`.

## The defect
In face-to-face scenes with `single` shots, a member's shadow was split into one layer per interval in which the member is on camera. The function that builds those layers (`worldLayer` in `production/lib/timeline.mjs`) sets no visibility window (`from`/`to`), so the renderer showed every one of them for the whole shot. Outside its interval, each layer held its first or last position. As a result:
- **in another member's single**, the off-camera member's shadow still showed;
- **every shot showed duplicate shadows**, left at positions from other shots' framings.

On the accepted A4 scene, before the fix, Character 01 had up to 3 shadow layers painting at once, including while it was off camera.

## The correction
`production/lib/formats/face-to-face.mjs` now gives each split shadow layer the visibility window of its member's on-camera interval.
- **Whole-shot shadows:** a shadow that covers the whole shot keeps its exact previous form, with no window. Scenes without singles are therefore unchanged byte for byte.
- **Unchanged:** positions, sizes, appearance, camera transformations and the shadow layers' keys.
- **Not modified:** the renderer.

## Files here
| File | What it is |
|---|---|
| `A4-shadow-before-after.png` | Row 1: before (code of commit `81fc4c0`). Row 2: after. Row 3: the after frame dimmed, with every changed pixel in magenta. Six panels, at the A4 review-sheet times |
| `difference.json` | Per time: changed pixels and their bounding box; the checks that the projects differ only in shadow visibility windows and that frames without shadows are pixel-identical |
| `A4-annotated.png`, `A4-clean.png` | The corrected A4 review sheets, made with the same generator as the accepted ones (`../review/generate-review-sheets.mjs`, `REVIEW_OUT` set to this folder) |
| `manifest.json` | Provenance of the corrected sheets: base commit, engine source hashes, sample times, render-plan and sheet hashes |
| `compare-shadows.mjs` | Regenerates the comparison: `BEFORE=<checkout of 81fc4c0> node production/evidence/ap85/shadow-correction/compare-shadows.mjs` |

## What differs, exactly
- **Changed pixels per sample time:** 7,833 (wide), 10,859 (single on ph), 10,259 (single on c01), 9,604 (close on c01), 10,129 (close on ph) and 7,566 (wide). See `difference.json`.
- **What they are:** all floor-shadow ellipses that are no longer drawn:
  - in the singles, the off-camera member's shadow;
  - in every shot, the duplicate copies left at positions from other shots.
- **Nothing else moved:** with every shadow layer removed, before and after are pixel-identical at every sample time (and in all 100 frames of the scene checked at 0.1 s). The projects are identical apart from the shadow layers' windows. Characters, framing, zoom, shot order and duration, dialogue, speakers and bubbles are unchanged.
- **The close shots:** each focus member's own shadow is still present in its window, but at 1.5× zoom it lies below the bottom of the frame (y ≈ 2405 of 2275.6 design units), as before. So no shadow is visible there now; the shadows that showed there before were the stale copies.

## What to inspect (owner)
1. `A4-shadow-before-after.png`: row 3 should show changes only in floor-shadow ellipses.
2. `A4-annotated.png` and `A4-clean.png` here, against the accepted ones in `../review/`:
   - in shots 2 to 5 (singles), the off-camera member casts no shadow;
   - in the wide shots, each member casts exactly one shadow.

## Tests
`production/tests/ap85-shadow-visibility.test.mjs` (2 tests) checks two things:
- **In the render plan:** each member's shadow windows equal its on-camera intervals, there is exactly one shadow per member on camera at every frame and none off camera, and scenes without singles keep a single windowless shadow.
- **In rendered frames:** at the wide shot, in the other member's single, when the member returns, and at the final wide shot, an on-camera member casts exactly one shadow and an off-camera member's shadow is absent.

Both tests fail on the pre-fix code and pass on the corrected code.
