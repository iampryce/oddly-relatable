# Asset management specification (AP-71)

Documentation only. No tool or system is introduced; the central register remains `ASSET_REGISTER.md`. Nothing here renames or re-statuses an existing file. Applies to all Stickman Comedy Studio character and environment assets.

## 1. Classification
| Status | Meaning | Register term today |
|---|---|---|
| **Canonical** | Authoritative visual reference; never altered | PROTECTED |
| **Approved working candidate** | Approved for controlled production tests; not necessarily final | APPROVED WORKING CANDIDATE (also WORKING SOURCE, ALTERNATIVE for conditionally approved items) |
| **Approved production asset** | Explicitly approved by the owner for production use | none yet |
| **Test** | Experimental output awaiting review | CANDIDATE / APPROVED TEST (once accepted as a test) |
| **Draft** | Unfinished work | CANDIDATE (intermediate) |
| **Historical** | Superseded versions, rejected attempts, preserved evidence | SUPERSEDED / EVIDENCE |

Existing register terms stay; this table only maps them. A status changes only by an owner decision recorded in `DECISIONS.md`.

## 2. Naming conventions (for NEW files only; existing files are not renamed)
Pattern: `<subject>_<type>[-<variant>]_<version>[_<status-tag>].<ext>` lower-case, hyphens inside a field, underscores between fields. `status-tag` is one of `canon`, `wc` (working candidate), `prod`, `test`, `draft`, `hist`. A status tag in a filename is a label only; the register is authoritative, and a rename is never done to change status.

| Asset | Pattern | Example |
|---|---|---|
| Character master | `character-NN_master_vN[_tag]` | `character-01_master_v3_wc.png` |
| Pose | `character-NN_pose-NN-<name>_vN` | `character-01_pose-02-worried_v1` |
| Expression | `character-NN_expr-<name>_vN` | `character-01_expr-shock_v1` |
| Transparent cut-out | `<source-name>_cutout[_tag]` | `character-01_master-v3_cutout_test.png` |
| Environment plate | `env-<place>_plate_vN[_tag]` | `env-living-room_plate_v1_wc` |
| Foreground overlay | `env-<place>_fg-<object>_vN` | `env-living-room_fg-chair_v1` |
| Episode-specific | `epNNN_<asset-pattern>` | `ep001_character-01_pose-03-shock_v1` |
| Render output | `<project>_apNN_<WxH>-<fps>fps_vN.mp4` | `poc-vertical-v3_ap72_1080x1920-30fps_v1.mp4` |
| Contact sheet / comparison | `contact-sheet-<subject>`, `compare-<a>-vs-<b>` | `compare-ap60-vs-ap72-sidebyside.png` |

Renders live in a clearly labelled output folder per task (never overwrite an earlier render's folder).

## 3. Integrity and provenance
- Checksums are SHA-256, computed by script (`crypto` in Node, or `sha256sum`), full value stored in a JSON sidecar or README, first 16 hex characters in the register.
- Every derived asset has a provenance record (JSON sidecar or README section): source path and SHA-256 **before and after** the operation, output path and SHA-256, method (script path, key parameters), tools and versions, date, and the AP/decision id.
- Verify protected references at the start and end of every task by re-hashing (canon `36b7c97e…`, sheet `36e8cef3…`, empty room `48ed1ca3…`, Candidate 04 `ca0148b0…`, Candidate 05 `ac83bf7f…`, v3 `d4dcb808…`); any mismatch stops work.
- Pixel-level proof for corrections: report changed pixels outside the declared masks (target 0).
- Renderer integrity: hash the renderer scripts folder before and after a render and report the diff.

## 4. Approval workflow
1. Create a new candidate; never overwrite its source.
2. Record source, method and checksum.
3. Generate a comparison against the canonical reference.
4. Review identity, proportions, outlines, colours, hands and other relevant details (at viewing size and zoomed).
5. Obtain explicit human approval.
6. Update the asset register and `DECISIONS.md` (and the five project records).
7. Only then may an asset receive a higher status. Approval of a working candidate never implies production-master approval.

## 5. Current status (unchanged by this task)
Canon `lookdev-scene-01.png` PROTECTED · `candidate-04_corrected-v3.png` APPROVED WORKING CANDIDATE · Candidate 04 unpromoted (WORKING SOURCE) · v2 and earlier hand attempts historical · Candidate 05 alternative plate, not a resolution upgrade · consistency sheet and empty-room test preserved · sweater and shoe differences not approved for correction · no further character image generation authorised.
