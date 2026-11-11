# AP-74: pose 03 (shocked) skin-only correction and single-shot render (TEST / EVIDENCE only)

Not promoted. No other pose touched. Sources unchanged (SHA-256 verified before and after; before-list in `source-checksums-before.txt`): canon `36b7c97e…`, sheet `36e8cef3…`, v3 `d4dcb808…`, pose 03 extract `fabe6f7a…`.

## Correction
- Input: `../extracted/canonical-character-01_03-shocked-frozen.png` (274×596 RGBA). Output (new): `character-01_pose-03-shocked_skin-only_test.png`, SHA-256 `477f8e713d6358fd…` (full in `correction-report.json`). Script `bible/concepts/src/ap74-pose03-skin.cjs`.
- Method = v3 method: colour-ratio plateau mask (ratios measured from the source's own skin), per-channel gain from sampled means, head region only, alpha copied unchanged, output clamped 0..255.
- **Skin mean RGB:** original (252.8, 226.7, 196.5) → corrected **(251.8, 221.7, 180.0)**. Canon recorded (252, 222, 180); approved v3 sampled (252.7, 221.4, 179.9). Gain (0.9969, 0.9793, 0.9161).
- Note: my direct sample of the canon head gave (249.6, 217.9, 171.3) from only 2067 pixels (shaded and edge pixels), which is outside the plausibility check, so the recorded canon value (252, 222, 180, measured earlier on the canon's flat skin) was used as the target, and v3's sampled mean agrees with it. This is stated, not hidden.
- **Mask:** 17,369 pixels. **Changed pixels inside the mask 17,323; outside the mask 0 (max delta 0); alpha pixels changed 0.** Pink mouth pixels checked 768, changed 0. Face shape, eyes, brows, mouth, ears' outline, hands, arms, sweater, shoes and linework are bit-identical to the source.
- A first run was wrong and was fixed before the final output: (1) red-channel overflow when a gain above 1 wrapped; (2) a head-region cutoff left a horizontal seam on the chin. Both fixed (clamp; cutoff raised to 40% of height); the final report is from the corrected run.

## Comparison sheets
`compare-sheet-1-full-figures.png` (original, corrected, canon, v3), `compare-sheet-2-closeups.png` (face and skin, pink mouth, both splayed hands, arm-to-hand transitions at 3× to 7×, nearest-neighbour, no invented detail). Hands: unchanged, splayed fingers intact.

## Single-shot render (AP-60 Shot 2 only)
- Work folder (outside repo): `C:\Users\PC\Desktop\Works\stickman-video-director\studio-work\poc-vertical-pose03-ap74\`; **render `output\preview.mp4`**, SHA-256 `4610e8d75f02b9db…`. Builder `bible/concepts/src/ap74-build-shot2.cjs` (derived from the AP-60 builder, untouched): Shot 2 timing is local 0 to 2 s (AP-60 2.5 to 4.5 s), same camera snap zoom and shake, plate, shadow, scale and feet anchor; caption at 0.2 to 1.8 s (AP-60: 2.7 to 4.3 s). A 2 s silent wav was created (ffmpeg, same format as the original) to match the 2 s clip.
- **Renderer:** unmodified (13 script hashes identical before and after); `validate` and `preview --seconds 2` only. AP-60 (`21a2bf50…`) and AP-72 (`758392a7…`) untouched.
- **Technical:** 1080×1920, 30 fps, 2.000 s, 60 frames, H.264 3.19 Mbps + AAC silent, 802,182 B; ffmpeg full decode pass; renderer `full_decode` pass; cold render 10.8 s; peak node 158 MB, node + ffmpeg sampled about 484 MB (approximate).
- Evidence: `compare-shot2-ap60-ap72-ap74.png` (4 times, three renders), `closeups-shot2-ap60-ap72-ap74.png`, `frames/`.

## Findings (AP-60 vs AP-72 vs AP-74)
- **Skin:** AP-74 is warmer and closer to the canon than AP-60's paler face; matches v3's tone. Expression, open pink mouth and splayed hands are preserved exactly; sweater, shoes, outline unchanged (sweater still brighter than the canon, shoes paler, by instruction).
- **Composition:** same scale, feet and framing as AP-60; no stretching. The splayed hands reach the frame edge at the 2.3× zoom (as in AP-60).
- **Sharpness: no improvement.** The pose is still about 2.5× enlarged at the snap zoom, so outlines, eye edges and hands are as soft as AP-60 and clearly softer than the v3 render (AP-72). The skin correction fixes colour only, as intended.
- **Remaining issues:** softness at close-ups (needs higher-resolution poses); faint pale mottling in the skin from the source (the sheet's noise is scaled with the colour); sweater/shoe steps vs v3; the loss of hand detail in the soft splayed fingers at zoom.

## Decision needed
Review the sheets; approve or reject the corrected pose 03 and say whether to continue with other poses. Nothing else will be corrected without approval.
