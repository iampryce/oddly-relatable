# AP-61/62: production candidates (Image 4 character master, Image 5 environment master)

Authorised by the owner (2026-11-11): exactly two Codex calls, existing ChatGPT login, no API. **Candidates only: not approved, not production assets.** Nothing existing was overwritten. Prompts: `prompt-04-…txt`, `prompt-05-…txt`; Codex messages: `codex-final-message-04/05.md`. Measurement script: `bible/concepts/src/assess-candidates.cjs`. Images used in total: **5**; **no further images authorised**.

| | Image 4: character master | Image 5: environment master |
|---|---|---|
| File | `production-candidate-04-character-master.png` | `production-candidate-05-environment-master.png` |
| **Actual size** | **1024×1536** | **941×1672** |
| SHA-256 | `ca0148b03a7aa59d08cabef6e4c8451407b0723829f039a112e66c478dcbf99b` | `ac83bf7f4b70efde726f410c32e5fdf42f4efe0932def37ed8b5bc702437803e` |
| References attached (`-i`) | canon, character sheet, extracted neutral + worried poses | canon, approved empty-room test |
| Calls / images | 1 / 1 (one new output folder `01a1ca61…`, verified) | 1 / 1 (`01a1ca62…`, verified) |
| Original (preserved) | `~\.codex\generated_images\01a1ca61-…\exec-5e1e0d64-….png` (byte-identical copy here) | `…\01a1ca62-…\exec-d48b5a0e-….png` (byte-identical copy here) |

**Resolution target NOT met:** the Codex built-in image tool returned 1024×1536 and 941×1672, not 2048 on the long edge, despite the request. It appears capped by the tool (the earlier tests were 1199×1312 and 941×1672). Genuinely higher resolution needs another route (upscaling, or an approved image API), which is a separate decision.

## Assessment (viewed + measured; `comparison-candidates-vs-canon.png`, `zoom-head-sheet-vs-candidate.png`)

**Character master**
- *Consistency:* strongly on-model: cream bald round head, small ears, large white oval eyes with small pupils, thick brows, small flat mouth, rust ribbed turtleneck with ribbed hem, thin black limbs, brown shoes. Full body with 126 px top and 137 px bottom margin; uniform grey background (203,203,203), no floor or shadow: easy to segment.
- *Resolution:* the figure is 1272 px tall versus about 570 px in the sheet poses (about 2.2× the linear detail): far better for close-ups than the sheet, but not 2048.
- *Outlines:* clean, smooth and heavier than the sheet's, closer to the canon's bold weight; crisp edges.
- *Colour:* sweater matches the canon (213,95,24 vs 212,84,18). **Skin is lighter and peachier** (255,232,205 vs canon 252,225,177), the same known drift. Shoes slightly paler/pinker than the canon's brown.
- *Deviations to flag:* hands are curled hook shapes with a notch, **not the small rounded mitts** of the lock; eyes slightly smaller relative to the head than in the canon. Pose is symmetrical and stiff (as requested).
- *Suitability:* a good base for segmentation and close-ups after a skin colour correction; the hands need fixing before approval.

**Environment master**
- *Consistency:* the same room, near-identical to the earlier empty-room test (zone differences 2 to 8 per channel); no character, no marks. Versus the canon, zones the character did not occupy differ 4 to 12 per channel (armchair 7.4, credenza 8.6, rug 9.9, ceiling 3.9, foreground 4.7); the bookshelf zone reads 27.6 only because the character stood there in the canon. Mean colours are within about 5 to 10 levels.
- *Resolution:* **941×1672, identical to the earlier test: no resolution gain and no obvious extra detail.** It is a different file (different hash) but not a meaningful upgrade.
- *Suitability:* acceptable as an alternative empty plate; **it does not solve the production-resolution problem.**

**Deviations from the locked design:** none in the room; in the character only the hand shape, skin-tone drift and slightly smaller eyes.
