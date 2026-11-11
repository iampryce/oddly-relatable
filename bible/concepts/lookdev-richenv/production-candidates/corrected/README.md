# AP-67: controlled corrections of Candidate 04 (awaiting the owner's visual approval)

Script: `bible/concepts/src/correct-candidate04.cjs` (+ `correct-candidate04-compare.cjs`). Input: `../production-candidate-04-character-master.png` (**unchanged**, SHA-256 `ca0148b03a7aa59d08cabef6e4c8451407b0723829f039a112e66c478dcbf99b` before and after). Everything here is a new file. No generation, no downloads or installs, no paid calls, no renderer change, no deletions (superseded drafts moved into labelled subfolders and kept).

## What was changed (and only this)
1. **Skin tone, skin-only mask.** Mask = pixels whose colour ratios (g/r and (r−b)/r) match the skin and that are not dark, within the head (`mask-skin-weight.png`); soft fall-off at outlines, eye whites and background so those are not touched. Per-channel gain (0.996, 0.957, 0.878). Mean skin **(252,230,203) → (251,220,178)**; canon (252,222,180): within 2 levels.
2. **Hands.** The two curled-hook hands were erased (only inside the hook zones, `mask-old-hand-windows.png`) and replaced by **native-resolution vector mitts** (`hands-vector.svg`): a solid black round palm with three rounded finger bumps, drawn at 4× and downsampled, mirrored for the right hand, hanging from the existing wrists. Geometry is taken from the canon's mitt proportions (palm about 0.3 head width; stubby rounded fingers fanned to one side).

## Verification
- **Pixel diff outside the masks: 0 changed pixels (maximum delta 0)** across the 1024×1536 image: sweater, shoes, face drawing, eyes, brows, mouth, proportions, outline, legs, arms and background are bit-identical to the candidate (`diff-original-vs-v2-x4.png` shows changes only in the head fill and the two hands).
- Changed pixels: 73,333 in the skin mask, 13,108 in the hand zones.

## Files
`candidate-04_corrected-v2.png` (both corrections), `-skin-only.png`, `-hands-only.png`, `hands-vector.svg`, `mask-*.png`, `diff-original-vs-v2-x4.png`, `correction-report.json` (hashes, gain, means), and sheets `compare-full-body.png`, `compare-face-closeup.png`, `compare-hands-closeup.png`, `compare-viewing-size.png`.

## Honest assessment (for your visual approval)
- **Skin:** now matches the canon's colour on the face and ears; uniform, no patches, eyes whites and outline untouched. A faint pale 1 px fringe where skin meets outline exists in the original too and is unchanged.
- **Hands:** now rounded mitts with three rounded finger bumps, closer to the canon than the hooks. They are **simpler than the canon's hand**: the canon's fingers are curved and sweep to one side, mine are straight capsules hanging down, a little "paw-like"; the palm is slightly larger relative to the arm than in the canon. This is v2 after two earlier drafts (`_draft1…` patchy skin and spiky fingers; `_v1-stubby-fingers`, shorter fingers). A curved-finger, canon-matching version is possible if you want it closer.
- **Not changed, as instructed:** sweater (still about 12% brighter than the canon's painted value) and shoes (still paler).
- **Status: CANDIDATE. Not promoted. Not the final production master.**

---

## AP-68: hands refinement v3 (owner revision, 2026-11-11)
Owner decision on v2: **skin approved in principle (kept unchanged); hands not final; sweater and shoes stay unchanged.** Requested: a rounded palm slightly smaller and better proportioned to the arm; two or three rounded fingers that curve and sweep to one side instead of hanging straight down; simple black silhouette; no points, spikes or complicated anatomy; a refinement of the vector work, not a redraw.

**v3** (`candidate-04_corrected-v3.png`, SHA-256 `d4dcb8082317ec2ab76c91e1bbcaf6ea20d9667ab721596f0e02718bbf07da51`; hands-only `b8ee84ad…`):
- Palm 62×66 px (v2) → **50×56 px**.
- Fingers are now **curved strokes** (quadratic curves with rounded ends, 19 px thick, lengths 40/50/39) that sweep inward and downward from the palm, mirrored for the right hand; no sharp points.
- **Skin unchanged:** the skin-only file is bit-identical to the one from v2 (SHA-256 `438c904b…`); mean (251,220,178) vs canon (252,222,180).
- **Pixel diff outside the masks: 0 changed pixels**; the sweater, shoes, face, proportions and outline are bit-identical to Candidate 04.
- **Preserved:** v2 and earlier attempts in `_v2-straight-fingers/`, `_v1-stubby-fingers/`, `_draft1-superseded-…/`; scripts `correct-candidate04-v2-straight-fingers.cjs` and `correct-candidate04-compare-v2.cjs` (v3 is `correct-candidate04.cjs`).
- Review sheet: `review-sheet-v3.png` (original, v3, and the hands of original / v2 / v3), `compare-hands-closeup.png`, `compare-full-body.png`, `compare-face-closeup.png`, `compare-viewing-size.png`.
- **Honest assessment:** closer to the canon (smaller palm, sweeping curved fingers). Still a little simpler than the canon's hand: the fingers are slim capsules, the palm is slightly egg-shaped, and at full-body size the hands read as small mitts with finger bumps. **Status: CANDIDATE, awaiting the owner's visual approval; Candidate 04 remains a working candidate, not the final production master.**

## AP-70: owner decision
v3 **accepted as the current approved working candidate** (2026-11-11), on the strength of the measurements and assessment; the owner will give final visual sign-off after seeing `review-sheet-v3.png`. No further hand revisions for now. v2 and earlier attempts kept as historical evidence. Sweater and shoes unchanged. **Candidate 04 and v3 are not the final production master.** No further character images to be generated.
