# AP-85 Track A: owner contact-sheet review

**Status: AWAITING OWNER REVIEW. Nothing here records acceptance.** Track A acceptance requires both the automated checks A-1 to A-10 (all passing at commit `910e877`) **and** the owner's review of these sheets (AP-85 plan §5.2).

**Track A only.** These sheets show the composition engine: placement, layering, timing, speaker attribution and camera framing. They are **not** identity evidence for any character (that is Track B). The blue body/green head figure is a **SYNTHETIC PLACEHOLDER, NOT ARTWORK**. It is a test fixture, not Character 02 and not a design. No Character 02 artwork exists.

## Files

| File | What it shows |
|---|---|
| `A1-annotated.png`, `A1-clean.png` | **A1 two-shot.** Character 01 on the left, placeholder on the right, 8 alternating lines, a pose change on every line, wide shots. |
| `A2-annotated.png`, `A2-clean.png` | **A2 swapped.** The same lines with positions swapped and z order reversed: the placeholder is on the left, behind, facing right. |
| `A3a-annotated.png`, `A3a-clean.png` | **A3a overlap.** The placeholder (z 1) stands partly in front of Character 01 (z 0). Includes an overlap detail panel. |
| `A3b-annotated.png`, `A3b-clean.png` | **A3b overlap.** The same positions with the order reversed: Character 01 (z 1) is in front. Includes an overlap detail panel. |
| `A4-annotated.png`, `A4-clean.png` | **A4 shot sequence.** Wide; medium on the placeholder; medium on Character 01; close on Character 01 (reaction); close on the placeholder (reaction); wide. |
| `manifest.json` | Commit, source hashes, sample times, render-plan hashes, sheet hashes and each member's painted box per frame. |
| `generate-review-sheets.mjs` | Regenerates the sheets (local, $0, needs `FFMPEG`/`FFPROBE`). |

Each **annotated** sheet has:
- a header with the scene's purpose, the cast (character, feet position, height, z order, facing, speech style and side), the shot sequence and what to inspect;
- one panel per line, sampled 60% through the line once the bubble has settled.

In each panel:
- each member has a dashed outline and a tag in its own colour: orange for `c01 · CHARACTER 01`, magenta for `ph · SYNTHETIC PLACEHOLDER, NOT ARTWORK`;
- the speaker's tag is filled and reads `SPEAKING`;
- the caption gives the line, time, speaker, bubble style and side, the text, the shot (camera, focus, zoom), each member's pose (and the drawing used when a facing resolves to a variant), and the back-to-front order.

Each **clean** sheet has the same frames and captions with no overlays, so nothing hides the picture. The placeholder's own on-figure label ("SYNTHETIC / PLACEHOLDER / NOT ARTWORK") is part of the rendered image in both sheets.

## What to inspect

1. **A1 attribution:** every bubble belongs to the member tagged SPEAKING. Character 01's bubbles use style "him" (dark orange, left); the placeholder's use "neutral" (white, right). Each line changes only the speaker's pose.
2. **A2 independence from position:** Character 01 now stands on the right and in front, yet its bubbles keep style "him". They also stay on the **left of the screen**, because c01's speech configuration declares side "left" and the bubble side is configuration, not derived from where the member stands. The placeholder's bubbles stay "neutral" on the right for the same reason. The placeholder uses its right-facing drawings (`p1-r`, `p2-r`), which are separate drawings, not mirrors. Check that styles follow the member. Also judge whether a bubble on the opposite side from its speaker reads acceptably; with real scenes, the speech side would normally be configured to match staging.
3. **A3a and A3b layering:** in A3a the placeholder covers Character 01 where they overlap; in A3b Character 01 covers the placeholder. Use the overlap detail panels.
4. **A4 camera framing (owner judgement needed):** each shot's "focus" pins the zoom pivot to that member's head. The focus member stays still and grows, and the other member moves toward the frame edge. The camera does **not** re-centre or isolate the focus member. Consequences visible on the sheet:
   - shots 2 and 3 (medium on `ph`, medium on `c01`) look alike;
   - in shot 5 (close on `ph`), Character 01 is the larger figure and is cropped at the left edge.

   Check A-7 passes because it tests the pivot. Whether this framing reads as "a shot of that member" is for the owner to judge, and any change to the camera model would need its own approval.
5. **Every sheet:** both members stay recognisable, keep their declared position and height, and are never confused with each other. Bubbles stay inside the frame.

Facing: Character 01's registry declares no facings, so it always uses its drawings as drawn (`native`). How characters face each other with real artwork is still the open owner decision M7.

## How these were made

1. **Scene definitions:** `generate-review-sheets.mjs` evaluates the scene definitions straight from the committed test file `production/tests/ap85-track-a.test.mjs` (hash recorded in `manifest.json`). The sheets therefore show exactly the scenes the Track A checks ran on.
2. **Build:** it writes the placeholder to a temporary folder with the test fixture, then compiles each scene with the production pipeline (`compileProject`, `allowSynthetic: true`, which only tests and this script pass) into temporary folders.
3. **Frames:** they are painted by the **unmodified** renderer (`loadProject` and `painter`); no video is encoded.
4. **Outlines:** each member's outline comes from the pixels it actually painted. The frame is painted again without that member's drawings, and the box covers the pixels that change. The labels follow the render, not the scene declarations.

Nothing in production code, character assets, other evidence or AP-84B3 was changed. Two runs produce byte-identical sheets and manifest. The script refuses to overwrite existing sheets unless `REPLACE=1` is set.

```bash
FFMPEG=... FFPROBE=... REPLACE=1 node production/evidence/ap85/review/generate-review-sheets.mjs
```
