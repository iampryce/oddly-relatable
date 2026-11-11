# AP-60: short vertical render (technical proof of concept)

Unmodified renderer (`skills/directing-stickman-videos/scripts/autopilot.mjs`), project built by `bible/concepts/src/poc-build-vertical.cjs`. Work folder (outside the repo): `C:\Users\PC\Desktop\Works\stickman-video-director\studio-work\poc-vertical-canonical\` (`output/preview.mp4`). Sources copied, not moved. Style B1, grid off, silent audio, no new generation.

**Result:** 1080×1920, 30 fps, 8.0 s, 240 frames, H.264 4.65 Mbps, 4.66 MB, AAC silent track; `validate` passed; `preview --seconds 8` full decode pass. Four shots with pose swaps 02 worried, 03 shocked (snap zoom 1.55→2.3 and shake), 05 pleading, 06 deadpan; shared camera transform for plate, shadow and sprite; single-line captions.

**Timing:** cold cache 34.8 s wall for 8 s of video (about 0.145 s/frame, 4.4× slower than real time). Re-render with warm cache 5 s (4 of 4 shots cached). Peak memory not measured.

## Assessment
- **Works:** the composited character reads well in the rendered scene at every zoom; pose swaps stay planted (feet anchors); camera push-in, snap zoom and shake are smooth; the plate holds up at 1080×1920; expressions are clear.
- **Artefacts and limits:** (1) softness: the sprite (about 270 px wide) is upscaled up to roughly 2.5× at max zoom and the plate by 1.1 to 2.6×, outlines slightly soft and fur texture mushy, acceptable for a test but not for hero close-ups; (2) the head is cropped at the 2.3× zoom (camera framing choice, easy to change); (3) no depth: single plate, no parallax, no foreground overlay layer in this render (possible with the unmodified renderer using overlay cut-outs and identical transforms, shown only in the still composite C); (4) pose changes are hard cuts at shot boundaries, no in-betweens; (5) pose-to-pose colour drift (shocked sweater more saturated), no per-pose colour correction applied; (6) captions are small and single-line, fixed at the bottom; the renderer draws a small glyph before the first caption; (7) a flat character against a painterly plate has no ambient light on it, which matches the canon but looks sticker-like in motion.
- **Verdict:** technically viable. Quality blockers for production: higher-resolution character and plate assets (needs owner approval to regenerate), depth-layer overlays, and per-pose colour/outline normalisation.
