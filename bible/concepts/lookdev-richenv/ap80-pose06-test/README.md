# AP-80: pose 06 (deadpan, arms crossed) skin-only correction (TEST / EVIDENCE; awaiting owner visual review)

Authorised by the owner (2026-11-12). Same method as v3, AP-74, AP-75 and AP-76 (`bible/concepts/src/ap80-pose06-skin.cjs`, a copy of the AP-76 script with new paths and whole-image protected-feature checks built in). Not rendered, not promoted.

**Sources, verified unchanged before and after** (`source-checksums-before.txt`): canon `36b7c97e…`, sheet `36e8cef3…`, v3 `d4dcb808…`, pose 06 extract `aeb639342c436fd7c92d997595dd9941dad4ec5497bc15b4fe38e725f6b7b699` (matches `extracted/manifest.json`). Poses 02 (`ee921285…`), 03 (`477f8e71…`) and 05 (`f2dae957…`) untouched.

- **Input:** `../extracted/canonical-character-01_06-deadpan-arms-crossed.png` (271×591 RGBA).
- **Output (new):** `character-01_pose-06-deadpan_skin-only_test.png`, 271×591 RGBA, SHA-256 `ee9dd2574411c86bb2e325d48937d8b6106d646a079375060f82bd0076b93fd9`. Report: `correction-report.json`; mask: `mask-skin-weight.png`.
- **Skin mean RGB:** original (253.1, 227.4, 197.4) → corrected **(252.1, 222.4, 180.1)**. Canon recorded (252, 222, 180); v3 sampled (252.7, 221.4, 179.9). Gain (0.9956, 0.9764, 0.9117). As in AP-74 to AP-76, the recorded canon value was the target because the direct canon sample (249.6, 217.9, 171.3; 2,067 shaded/edge pixels) fails the plausibility check.
- **Mask:** **21,398 px in the mask; changed inside 21,354; changed OUTSIDE the mask: 0 (max delta 0). Alpha pixels changed: 0.**
- **Protected features (whole image, read back from the written PNG):** near-black pixels (outline, crossed arms and hands, pupils, brows, mouth line) 21,104 checked, 0 changed; eye whites 2,251 checked, 0 changed; sweater 12,781 checked, 0 changed; shoes 3,421 checked, 0 changed; black pixels below the head 10,871, 0 changed. All changes lie in rows 17 to 203 of 591 (the head and ears). The 96 grey-class pixels changed inside the mask are all warm (r > b) skin-to-outline anti-aliasing blends, as in earlier poses; 0 cool-grey pixels changed. No pink mouth in this pose (the mouth is a line), so the pink check finds 0, as expected.
- **No sharpening, upscaling, redrawing or generation;** dimensions and alpha preserved.
- **Comparison:** `compare-sheet-1-full-figures.png` (original, corrected, canon, v3) and `compare-sheet-2-closeups.png` (face and skin; half-lidded eyes and raised brow; mouth and chin; crossed arms and hidden hands; shoes; nearest-neighbour enlargement only).
- **Limitations:** sheet softness remains (about 570 px tall); sweater and shoe colour steps vs v3 remain by decision; the skin keeps the sheet's faint mottling.
