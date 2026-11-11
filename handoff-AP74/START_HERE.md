# Stickman Comedy Studio: handoff (state after AP-74, 2026-11-11)

Open the new session in: `C:\Users\PC\Desktop\Works\stickman-video-director` (the live project and renderer). This folder is a **copy** of the key files for reference; the originals were not moved or changed. Ask the new session to read this file first, then `records\HANDOFF.md`.

## What the project is
Original, world-at-large animated comedy brand (YouTube/TikTok/Facebook), 9:16 primary. Look is PERMANENTLY LOCKED to `assets\canon\lookdev-scene-01.png`: flat 2D character with bold black outlines on rich illustrated cinematic rooms. Master character = "Canonical Character 01" (unnamed): cream bald round head, rust turtleneck, thin black limbs, small black mitt hands, brown shoes.

## Where things stand
- Pipeline proven: the unmodified renderer (`skills\directing-stickman-videos\scripts\autopilot.mjs`) makes 1080×1920, 30 fps vertical video with camera moves and captions. Needs env vars `FFMPEG` and `FFPROBE` (FFmpeg at `C:\Users\PC\tools\ffmpeg\bin`).
- Assets: `candidate-04_corrected-v3.png` = APPROVED WORKING CANDIDATE (sharp, one neutral pose; not a final master). Six-pose sheet = 6 expressive poses, about 550 px tall (fine for wide and medium shots up to about 1.5x zoom, soft in close-ups). Pose 03 skin-corrected as a TEST (AP-74), awaiting your review. Room plate = `lookdev-room-empty-03.png`; Candidate 05 = alternative plate.
- NOT done yet: no script, joke, voice or finished episode. Everything so far was asset checking.

## Proposed next step (waiting for the owner's go-ahead)
Stop testing; make a first real 20 to 30 s short with existing assets: new original script and shot list, owner approves, apply the approved skin correction to the other poses, render with the existing pipeline (wide and medium shots, zoom up to about 1.5x), owner reviews. The owner's decision needed: a joke/topic of their own, or pick from three original ideas. Also pending: review of AP-74 pose 03.

## Standing rules (from the owner)
No renderer changes; no installs or downloads; no paid APIs; no new image generation without approval; no overwriting, deleting or renaming existing assets; no Git init/commits/pushes; stop at gates and wait for approval; update the five records and `ASSET_REGISTER.md` at each milestone. Do not touch the Kids Animation Studio files. Never record VPS addresses or keys in the repo. The owner is the final approver and dislikes endless micro-adjustments. Sweater and shoe colour differences are NOT approved for correction.

## Folder map
- `records\` the five tracking files (status, decisions, progress, next steps, handoff)
- `docs\` ASSET_REGISTER, ASSET_MANAGEMENT (naming, provenance, approval rules), POSE_LIBRARY_ASSESSMENT
- `assets\canon\` the locked canon image
- `assets\character\` v3, review sheet, v3 cut-out, six-pose sheet, `extracted-poses\` (transparent poses + manifest), pose 03 skin-corrected test
- `assets\environment\` empty room, Candidate 05
- `evidence\` AP-72 and AP-74 comparison sheets, reports, frames
- `videos\` AP-60 (original 8 s), AP-72 (v3 8 s), AP-74 (pose 03 shot, 2 s)
- `scripts\` the build, correction and comparison scripts used (they expect to live in `bible\concepts\src\` of the project)

## Live locations (originals)
- Project: `C:\Users\PC\Desktop\Works\stickman-video-director` (`bible\concepts\lookdev-richenv\` for assets and evidence)
- Test videos and project folders: `C:\Users\PC\Desktop\Works\stickman-video-director\studio-work\`
- Auto-memory notes: `C:\Users\PC\.claude\projects\c--Users-PC-Desktop-Works-stickman-video-director\memory\`
