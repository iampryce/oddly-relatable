# AP-72: corrected v3 character in the 9:16 render (diagnostic only)

**Result:** renders successfully with the **unmodified renderer**. Not a production render; no asset promoted.

## What was done
- Derived a transparent cut-out of v3 (new file; v3 untouched, SHA-256 `d4dcb808…` before and after): `character-01_master-v3_cutout_test.png` (535×1293, SHA-256 `dd0f3939…`, sidecar `.json`; script `bible/concepts/src/ap72-cutout.cjs`; method: border flood fill and edge unmix, no redrawing).
- Built the project with `bible/concepts/src/ap72-build-vertical.cjs` (derived copy of the AP-60 builder; AP-60 builder untouched). Same plate, shadow, silent wav, camera paths, timing, captions, 4 shots, 1080×1920, 30 fps. Only change: the character. Scale chosen so the figure height equals AP-60's (548 px / 1270 px), feet anchored at the AP-60 feet point.
- Work folder (outside repo): `C:\Users\PC\Desktop\Works\stickman-video-director\studio-work\poc-vertical-v3-ap72\`; **render: `output\preview.mp4`** (SHA-256 `758392a7a35f5c0c…`). AP-60 file untouched (`21a2bf50…`, matches its report).

## Limitation that changes the test
v3 is **one neutral pose** (no phone, no shock mouth, no pleading, no crossed arms). All four shots therefore show the same pose and expression; AP-60's pose swaps are **not reproduced**. This was necessary, not a workaround of the renderer. The test isolates fidelity, not performance.

## Technical validation
| | AP-60 | AP-72 |
|---|---|---|
| Resolution / fps / duration | 1080×1920 / 30 / 8.000 s | same |
| Frames | 240 | 240 |
| Codec | H.264 video + AAC silent audio | same |
| Video bitrate | 4.65 Mbps | 4.87 Mbps |
| File size | 4,658,956 B | 4,884,725 B |
| Full decode (ffmpeg null) | pass | pass (and renderer `full_decode` pass) |
| Render time, cold cache | 34.8 s | 37.9 s |
| Peak memory | not measured | node 166 MB; node + ffmpeg sampled total about 580 MB (sampled every 0.3 s, so an approximation) |
| Renderer scripts hash diff before/after | n/a | none (13 files identical) |

## Visual findings (see sheets in this folder)
- **Sharper:** outlines are crisp and pure black at every zoom, including the 2.3× snap zoom (AP-60 outlines are soft and dark navy). Native sprite resolution is about 2× the old sheet. Eyes, brows, mouth, turtleneck ribs and hands are clean.
- **Identity:** face, proportions, rust turtleneck and brown shoes consistent with the canon; skin now matches the canon colour (the AP-60 sprite skin is paler); hands read as small black mitts with curved fingers; at wide shots they are tiny but legible as mitts.
- **Composition:** same scale and foot placement as AP-60; no stretching; shadow aligned. At the 2.3× snap zoom the whole face is in frame (AP-60 cropped it); the framing is unchanged, the v3 head simply sits slightly lower.
- **Sweater/shoes:** still unchanged by instruction (sweater about 12% brighter than the canon painting; shoes paler).

## Regressions and remaining limitations
1. Loss of all pose and expression variety (single pose). Biggest functional regression; not a rendering fault.
2. Faint light flecks may remain at the shoulder-arm gaps of the cut-out (enclosed gaps under 60 px are kept to protect eye-white edges); not noticed at normal size.
3. Still a sticker-like flat character on a painterly plate; no foreground overlap or depth layers (out of scope).
4. Plate softness at zoom is unchanged (same plate).
5. Peak memory is an approximate sample.
6. Human review is still required; technical checks are not acceptance.

## Files
`compare-ap60-vs-ap72-sidebyside.png` (7 times, both renders), `contact-sheet-ap72.png`, `closeup-face-t3.4.png`, `closeup-hands-torso-t1.2.png`, `closeup-hands-torso-t6.0.png`, `frames/` (14 extracted frames), cut-out PNG and JSON.
