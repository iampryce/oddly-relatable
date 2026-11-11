# AP-59: Canonical Character 01 composited onto the empty-room plate

Inputs (untouched): `../lookdev-room-empty-03.png` (941×1672), `../extracted/canonical-character-01_02-worried-phone.png`, canon `../lookdev-scene-01.png` for comparison only. Script: `bible/concepts/src/composite-test.cjs`. No generation or redrawing.

| File | What |
|---|---|
| `composite-A-canonical-placement.png` | Pose 02 scaled **0.95** and placed at (450,785) (best fit to the canon by pixel search); feet at about (547,1317). No other processing |
| `composite-B-matched-shadow.png` | A + measured colour gain (R0.92 G0.88 B0.81) + soft contact shadow |
| `composite-C-foreground-overlap.png` | Scale 1.0, feet at (300,1488) behind the foreground table, mug, books and plant; occluded by a hand-traced polygon of plate pixels (`debug-foreground-polygon.png`) |
| `comparison-canon-vs-A-vs-diff.png` | Canon, A, and a difference image (crop) |
| `contact-sheet-composites.png` | A, B, C side by side |

## Evaluation
- **Scale/position:** the fit lands where the canon figure stands (head, torso, feet align to a few px); the sprite is a re-drawn pose, so the mean difference inside the crop is 13.6 per channel (limbs and phone differ by a few px; plate-only noise is 3 to 7). Scale 0.95 is a good match for feet at y≈1317; a nearer position needs a larger scale (perspective: roughly +10% per 100 px lower, estimated, not measured).
- **Perspective:** the figure is drawn front-on while the room is three-quarter. This is the same in the canon, so it reads as intended, but the feet cast no cue of the rug's perspective.
- **Outlines:** sprite outlines are slightly thinner and cleaner than the canon's (known drift); they hold well against the busy plate.
- **Integration:** flat character on a painterly plate matches the locked look. The sprite is lighter and peachier than the canon; the colour gain in B fixes it (worth correcting at the pose-sheet level). The soft shadow helps grounding without adding shading to the character.
- **Foreground overlap:** works once an occlusion mask exists (C: mug and table hide the legs, character reads as standing behind them). The polygon is hand-traced and approximate; clean edges on organic plants need a better mask. Depth placement is ambiguous without a depth map: feet behind a table need judgement per shot.
- **Limit:** the plate is one flat picture, so any parallax needs overlay cut-outs from the same plate.
