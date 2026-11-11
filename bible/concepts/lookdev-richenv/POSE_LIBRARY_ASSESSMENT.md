# AP-73: existing six-pose library assessment (assessment only)

No extraction, correction, generation or rendering was done. Measurements are read-only (colour sampling and geometry on the existing extracted poses; nothing written to the repo except this document). No approval status changed. Sources: `lookdev-character-test-02.png` (1199×1312, SHA-256 `36e8cef3…`), `extracted/` (AP-58), canon `lookdev-scene-01.png`, v3 `production-candidates/corrected/candidate-04_corrected-v3.png`, AP-60 and AP-72 renders.

## 1. Six-pose assessment
Colours are mean RGB of flat interior fills, sampled the same way for all six (so comparable to each other; absolute values ±2).

| # | Pose / expression | AP-60 shot | File size; figure | Hands | Skin | Sweater | Notes |
|---|---|---|---|---|---|---|---|
| 01 | Neutral, arms down | not used | 272×572; 252×551 | **curled hooks** (not the v3 mitt) | 252,228,200 | 198,90,24 | Nearest to v3's stance; same expression family as v3 |
| 02 | Worried, looking at phone, mouth open | **Shot 1 worried phone** | 270×571; 249×549 | phone hand: round black mitt with finger bumps; other hand: mitt with 3 curved fingers on chest (already close to the v3 language) | 252,228,200 | 198,91,24 | Head tilted down; phone prop; overlapping arm and torso |
| 03 | Shocked, frozen, mouth open, arms out | **Shot 2 shocked** | 274×596; 253×575 | **splayed thin fingers** (4 thin strokes), a gesture different from the mitt | 252,228,200 | 199,91,24 | Frontal, no props, face and hands fully clear |
| 04 | Laughing, eyes closed, fists up, leaning | not used | 299×580; 278×559 | round black fists | 252,228,199 | 198,89,23 | Dynamic lean; widest figure |
| 05 | Pleading, eyes up, wavy mouth, hands clasped | **Shot 3 pleading** | 273×569; 252×549 | clasped black blob plus outline hand | 252,228,200 | 198,90,23 | Knees bent; hands overlap chest |
| 06 | Deadpan, half-lidded, one raised brow, arms crossed | **Shot 4 deadpan** | 271×591; 251×569 | hidden under crossed arms | 253,228,200 | 198,90,23 | Tallest crop; strongest personality read |

Common: all six are the same drawing family: bald round head, large ears, round eyes with black outline, rust ribbed turtleneck, thin black limbs, brown shoes. Heads, outline weight, ears and turtleneck read as consistent by eye (not measured). Skin and sweater are uniform across all six (±1 level), which means one correction recipe would fit all of them.

## 2. Comparison with the canon and v3
| Item | Canon | v3 | Sheet poses |
|---|---|---|---|
| Skin | 252,222,180 | 251,220,178 (corrected) | 252,228,200 (paler; gain about (1.0, 0.974, 0.90) would match) |
| Sweater | 188,76,21 | about 212,94,23 (not corrected, brighter) | about 198,90,24 (between the two) |
| Shoes | 132,86,59 | about 157,93,57 | about 149,92,57 |
| Hands | rounded black mitt, finger bumps | smaller palm, curved inward fingers | mixed: hooks (01), mitt-like (02, 04), splayed (03), hidden or clasped (05, 06) |
| Outline | clean heavy black | clean heavy black, 1024×1536 | clean at native size, soft when enlarged |
| Resolution (figure height) | scene 1672 px tall | 1270 px | 549 to 575 px (about 2.3× fewer pixels than v3) |

**Consequence:** mixing sheet poses with v3 in one sequence would show a sweater colour step (v3 is brighter than the sheet poses by about 14 in red), a shoe step and a resolution step. The owner has said not to correct sweater or shoes yet, so this is recorded only.

## 3. Resolution and production suitability (1080×1920)
Measured from the AP-60 camera: a sheet pose is drawn at about **1.09 screen px per sprite px at zoom 1.0**, 1.7× at zoom 1.55 and **2.5× at the 2.3× snap zoom**. v3 (AP-72) is 0.47 at zoom 1.0, 0.73 at 1.55 and **1.08 at 2.3×**, so it is never meaningfully enlarged.
| Shot type | Sheet poses | v3 |
|---|---|---|
| Wide full body (zoom ≈1.0, ≈1.1×) | adequate | very sharp |
| Medium (zoom ≈1.5, ≈1.7×) | acceptable but visibly soft outlines (as in AP-60) | sharp |
| Close-up (zoom 2.3, ≈2.5×) | **not adequate**: the AP-60 shock close-up is blurred | sharp (≈1.1×) |

**Recommendation:** with controlled corrections the existing poses are adequate for **wide shots** and **limited medium shots (about 1.5× or less)**; for close-ups and hero face moments **higher-resolution poses will eventually be necessary**. No classical upscaling is offered as added detail (AP-64 showed it adds none).

## 4. Correction feasibility (non-destructive)
- **Skin:** feasible with the v3 method (colour-ratio mask plus per-channel gain); skin is uniform across the six, so one gain fits all. Check that mouth interior pink, eye whites and the phone are excluded by the mask (the method excluded eye whites and outline in v3).
- **Hands:** per pose, not blanket. 01: replace the hooks with the v3 mitt (same procedure as v3). 02, 04: already mitt-like, do not replace (they hold the phone or are fists). 03: replacing the splayed fingers with the v3 mitt would remove the "frozen shock" gesture; owner decision required whether to keep as is, or draw a v3-style mitt with fingers splayed. 05, 06: do not touch (clasped or hidden hands are the body language).
- **Faces and expressions:** do not transplant v3's neutral face or hands onto expressive poses; only fill colour (skin) changes. Eyes, brows, mouths, outline stay bit-identical.
- **Outlines:** extraction already converts anti-aliasing to partial alpha; outlines preserved; a 4 px fringe rule exists. Corrections must report 0 changed pixels outside the declared masks.
- **Transparent extraction:** done for all six in AP-58 (clean on three backgrounds). The AP-72 cut-out method could be reused but is not needed.
- **Foot anchors:** recorded per pose (manifest); differ between poses (e.g. 102 vs 139), so each pose needs its own anchor and scale (v3 was matched by figure height 548 px).
- **Enlargement:** the sheet's softness cannot be fixed; vector redraw of black elements is possible only for hands (as in v3). Enlarged pixels add no detail.

## 5. Recommended test pose: **03, shocked / frozen**
1. It is the highest-impact moment (snap zoom 2.3×, where softness is worst).
2. Face and both hands are fully visible, frontal, no props, no overlapping arms, so extraction exists and is clean and a correction can be verified.
3. Its stance matches v3 and the canon (frontal, standing, arms away from the body), so comparison against the canon and v3 is direct.
4. The skin method transfers unchanged; the open mouth (pink) is a useful test of mask exclusion.
5. It exposes the real open question (hand design for a splayed gesture) before we invest in the other poses.
Runners-up: 06 (lowest risk: skin only, hands hidden, but less value); 02 (high value, higher risk due to phone and overlaps); 05 (clasped hands).

## 6. Proposed non-destructive workflow (not started)
1. Re-hash the canon, sheet, v3 and pose 03 file; confirm unchanged.
2. Test 1 (skin only): apply the v3 skin method to pose 03 as a new file in a new folder; report mask, mean colour before and after vs canon, and 0 changed pixels outside the mask.
3. Owner decision on hands (keep splayed fingers, or a v3-style splayed mitt) after seeing close-ups; only then, if wanted, a separate hands-only version.
4. Comparison sheet against canon, v3 and AP-60 pose 03; viewing size plus close-ups.
5. Render check in the AP-60 shot 2 only, using the unmodified renderer, in a new labelled folder.
6. Record in the register as TEST; owner approval needed before any higher status. Then repeat for 06, 02, 05, 01 one at a time.

## 7. Risks and limitations
- Sheet poses are about 550 px tall: close-ups stay soft; corrections do not add resolution.
- Colour steps between v3 and sheet poses (sweater, shoes) remain by instruction; mixed sequences would show them.
- Hand design inconsistency across poses (hooks, splayed, mitts) is part of the sheet; the owner has to decide which are acceptable.
- The consistency sheet was a generated image: pose-to-pose drift (head size, outline weight) is checked by eye only.
- Per-pose anchors and scales must be set individually; wrong anchors cause sliding feet.
- The sheet's neutral pose already had hooks, so the canon and the approved sheet disagree on hands; v3 resolved this in favour of the canon.
- Measurements are my sampling, not a human visual review; final judgement is the owner's.
