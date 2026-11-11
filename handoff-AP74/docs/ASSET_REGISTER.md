# Asset register: Canonical Character 01 and canonical room

Status values: **PROTECTED** (read-only, never modify) · **APPROVED TEST** (evidence, keep) · **WORKING SOURCE** (conditionally approved, not final) · **ALTERNATIVE** (approved for a purpose, not canon) · **APPROVED WORKING CANDIDATE** (accepted by the owner as the current working version, not final) · **CANDIDATE** (awaiting owner's visual approval) · **EVIDENCE** (tests, drafts, defect history). **No asset is a final production master yet.** Hashes are SHA-256 (first 16 hex characters; full values in the READMEs and `correction-report.json`). Paths are relative to `bible/concepts/lookdev-richenv/`. Last updated 2026-11-11 (AP-74; no status changes). Pose assessment: `POSE_LIBRARY_ASSESSMENT.md`. Management rules: `ASSET_MANAGEMENT.md` (AP-71).

| Asset | Path | Size | SHA-256 | Status |
|---|---|---|---|---|
| Canonical scene (master character in the room) | `lookdev-scene-01.png` | 941×1672 | `36b7c97e8b9c3167` | **PROTECTED** (+2 identical backups) |
| Approved consistency sheet (6 poses) | `lookdev-character-test-02.png` | 1199×1312 | `36e8cef3f3149786` | **APPROVED TEST** (note: its neutral pose has curled-hook hands) |
| Approved empty-room test | `lookdev-room-empty-03.png` | 941×1672 | `48ed1ca37146447d` | **APPROVED TEST** |
| Extracted poses 01 to 06 (transparent) | `extracted/canonical-character-01_0N-*.png` | about 270×570 | 01 `9776ab45…`, 02 `389d597b…`, 03 `fabe6f7a…`, 04 `857fd242…`, 05 `625e3fae…`, 06 `aeb63934…` | APPROVED (AP-58), low resolution |
| Composite tests A, B, C | `composite/composite-*.png` | 941×1672 | A `7f24b147…`, B `fa494d5e…`, C `70e6e4b1…` | APPROVED TEST |
| Vertical render test (8 s, 9:16) | `…/studio-work/poc-vertical-canonical/output/preview.mp4` (outside repo) | 1080×1920 | see `poc-vertical/README.md` | APPROVED TEST |
| **Candidate 04: character master (original)** | `production-candidates/production-candidate-04-character-master.png` | 1024×1536 | `ca0148b03a7aa59d` | **WORKING SOURCE** (conditionally approved; unchanged; hooks hands, skin too light) |
| **Candidate 05: environment master** | `production-candidates/production-candidate-05-environment-master.png` | 941×1672 | `ac83bf7f4b70efde` | **ALTERNATIVE** empty plate (approved); not a resolution upgrade |
| **Candidate 04 corrected v3 (skin + refined hands)** | `production-candidates/corrected/candidate-04_corrected-v3.png` | 1024×1536 | `d4dcb80823…` | **APPROVED WORKING CANDIDATE (owner, 2026-11-11, AP-70); NOT the final production master** |
| Candidate 04 corrected v2 (straight fingers) | `production-candidates/corrected/_v2-straight-fingers/candidate-04_corrected-v2.png` | 1024×1536 | `d6af9544c0bab6a5` | SUPERSEDED (historical evidence) |
| Candidate 04 corrected, skin only | `production-candidates/corrected/candidate-04_corrected-skin-only.png` (approved in principle; bit-identical in v2 and v3) | 1024×1536 | `438c904b2d7b0b03` | CANDIDATE (intermediate) |
| Candidate 04 corrected, hands only | `production-candidates/corrected/candidate-04_corrected-hands-only.png` | 1024×1536 | `b8ee84ad57e93e3f` | CANDIDATE (intermediate) |
| Vector hands (native coordinates) | `production-candidates/corrected/hands-vector.svg` | 1024×1536 viewBox | n/a | CANDIDATE (editable source of the hands) |
| Masks, diff, report, comparison sheets | `production-candidates/corrected/mask-*.png`, `diff-original-vs-v3-x4.png`, `correction-report.json`, `compare-*.png` | | | EVIDENCE |
| Earlier correction drafts | `production-candidates/corrected/_draft1-superseded-spiky-hands-patchy-skin/`, `_v1-stubby-fingers/`, `_v2-straight-fingers/` | | | EVIDENCE (kept, superseded) |
| Upscaling tests | `production-candidates/upscale-tests/` (`char04_2x_*.png`, `room05_2x_*.png`, results, sheets) | 2048×3072 / 1882×3344 | cubic `2487e1af…`, nohalo `4cd97525…` (char); cubic `a497fe73…`, nohalo `cf0f9eca…` (room) | EVIDENCE (resampling adds no real detail) |
| Character v3 transparent cut-out (AP-72) | `ap72-validation/character-01_master-v3_cutout_test.png` (+ `.json` provenance) | 535×1293 | `dd0f393972ff7610` | TEST (derived from v3; not approved) |
| AP-72 diagnostic render (v3, 9:16) | `…/studio-work/poc-vertical-v3-ap72/output/preview.mp4` (outside repo) | 1080×1920 | `758392a7a35f5c0c` | TEST (diagnostic; awaiting review) |
| AP-72 comparison evidence | `ap72-validation/*.png`, `README.md` | | | EVIDENCE |
| Pose 03 skin-only corrected (AP-74) | `ap74-pose03-test/character-01_pose-03-shocked_skin-only_test.png` (+ `correction-report.json`, `mask-skin-weight.png`) | 274×596 | `477f8e713d6358fd` | TEST (derived from `extracted/…03-shocked-frozen.png` `fabe6f7a…`; 0 changed pixels outside the mask; not approved) |
| AP-74 single-shot render (Shot 2) | `…/studio-work/poc-vertical-pose03-ap74/output/preview.mp4` (outside repo) | 1080×1920, 2 s | `4610e8d75f02b9db` | TEST |
| AP-74 comparison evidence | `ap74-pose03-test/*.png`, `README.md` | | | EVIDENCE |
| Extraction defect history | `extracted/_v1…_v4-*-defect/` | | | EVIDENCE |

## Rules
- Nothing marked PROTECTED, APPROVED TEST, WORKING SOURCE or ALTERNATIVE is ever overwritten; corrections are new files.
- Promotion to **final production master** needs the owner's explicit approval (not given for any asset yet).
- Images generated so far: **5** (canon, character sheet, empty room, candidate 04, candidate 05). No further generation without approval.
