# Project Status — Stickman Comedy Studio

**Last updated:** 2026-11-11 (after AP-76) · **Updated by:** Claude Code
**Repository:** `C:\Users\PC\Desktop\Works\stickman-video-director` (the existing copy; kept, not recloned) · **Git:** none (`.git` is absent; nothing has ever been committed from here)
**Roles:** Claude Code = technical and creative production agent. ChatGPT = creative and architectural decision partner. Project owner = final approval.

## 1. Where we are

| Phase / item | State | Notes |
|---|---|---|
| Repository assessment (read-only) | ✅ Complete | 2026-11-10 |
| Phase 0: environment setup and validation | ✅ Complete, approved | FFmpeg, `npm ci`, offline render |
| Phase 0.1: line-ending fix | ✅ Complete, approved | 172 files CRLF→LF, backed up first |
| Phase 1: Channel Bible (10 docs in `bible/`) | 🟠 **Drafted; now partly superseded** | Written for a West African setting with Femi. **Paused pending rewrite** (AP-16/17). Banners added; content not rewritten |
| Visual-direction comparison (Inkblock vs 2.5D Modern Pop) | ✅ Prepared | `bible/VISUAL_DIRECTION_COMPARISON.md` · **historical; superseded by the locked identity (AP-51)** |
| **Rich-environment investigation** (owner's new reference direction) | ✅ Report written, **awaiting owner approval of the proof of concept** | `bible/VISUAL_DIRECTION_RICH_ENVIRONMENTS.md` · **historical; superseded by the locked identity (AP-51)** |
| Technical spike (layered depth, unmodified renderer) | ✅ Done and verified | 6 s, 1920×1080, 30 fps; see §5 |
| Codex background-plate test (1 image, earlier today) | ✅ Done | Rich, but clashes with a flat character |
| **Owner's reference picture** | ✅ **Received and inspected** | One vertical TikTok frame; private copy in `…\studio-work\references\` (outside the repo). Findings in the report §0 |
| **New lead character** | ⏳ **Needed from the owner** | Femi is retired |
| **Visual identity** | 🔒 **PERMANENTLY LOCKED (AP-51 to AP-57)** | Canonical reference `bible/concepts/lookdev-richenv/lookdev-scene-01.png` (SHA-256 `36b7c97e…ff016`, read-only, three identical copies). **Two approved technical tests passed:** the master character stays strongly on-model across six poses and expressions; the same room recreates near-identically without the character. **3 images used; no further generation without approval.** Earlier looks archived or historical |
| **Technical proof of concept (AP-58 to AP-60)** | ✅ **Done; awaiting creative direction** | Six poses extracted; composite tested; 8 s 1080×1920 render with the unmodified renderer (cold 34.8 s). Viable; limits: softness at zoom, no depth layers, per-pose drift. `bible/concepts/lookdev-richenv/{extracted,composite,poc-vertical}/` |
| **Production-candidate artwork (AP-61/62)** | 🟡 **Two candidates generated; awaiting owner approval** | Character master 1024×1536 (on-model; hands/skin drift), environment master 941×1672 (near-identical to the earlier test). **2048 px target not met** (tool cap). 5 images used; no more without approval. `…/production-candidates/` |
| **Resolution and corrections (AP-63 to AP-66)** | 🟡 **Assessed; awaiting approval** | Image 4 conditionally approved (working source), Image 5 approved as alternative plate. No local AI upscaler available; classical resampling adds no detail. Correction plan (skin gain, rounded-mitt hands) written, not executed. `…/production-candidates/upscale-tests/README.md` |
| **Candidate 04 corrections (AP-67)** | 🟡 **Produced as a candidate; awaiting the owner's visual approval** | `candidate-04_corrected-v2.png`: skin matched to the canon, vector rounded-mitt hands; everything else bit-identical to Candidate 04. Not a final production master. `…/production-candidates/corrected/`, asset register `…/lookdev-richenv/ASSET_REGISTER.md` |
| **Hands refinement v3 (AP-68 to AP-70)** | ✅ **v3 accepted as the approved working candidate (not final); final visual sign-off pending** | Skin approved in principle (unchanged); hands v3: smaller palm, curved sweeping rounded fingers; v2 and earlier preserved. Sweater and shoes unchanged by instruction. Candidate 04 remains a working candidate, not the final master. `…/production-candidates/corrected/review-sheet-v3.png` |
| **Asset rules + v3 render check (AP-71/72)** | ✅ **Done; awaiting owner review** | ASSET_MANAGEMENT.md written; v3 rendered 9:16 with the unmodified renderer (`…/poc-vertical-v3-ap72/output/preview.mp4`); sharper, canon skin; single pose only. Nothing promoted. Evidence `lookdev-richenv/ap72-validation/`. |
| **Pose library assessment (AP-73)** | ✅ **Assessment done; awaiting owner approval** | Sheet poses ~550 px tall: fine for wide shots, soft in close-ups. Recommended test pose: 03 shocked (skin-only first). Nothing extracted, corrected or promoted. `lookdev-richenv/POSE_LIBRARY_ASSESSMENT.md` |
| **Pose 03 skin test (AP-74)** | ✅ **Done as TEST; awaiting owner visual review** | Skin-only, 0 changed pixels outside the mask; hands/mouth untouched; Shot 2 rendered with the unmodified renderer; closer to canon colour, no sharpness gain. `lookdev-richenv/ap74-pose03-test/` |
| **Pose library correction (AP-74 to AP-76)** | 🟡 **Pose 03 approved as working TEST asset; poses 02 and 05 produced, awaiting review** | Same skin-only method, 0 changed pixels outside masks; hands, phone and expressions untouched; pose 02 not rendered. Poses 01, 04, 05, 06 await review. `lookdev-richenv/ap75-pose02-test/` |
| **Multi-platform direction** | ✅ Approved; architecture drafted (proposal) | YouTube + TikTok + Facebook; 9:16 primary, 16:9 secondary; `bible/MULTI_PLATFORM_ARCHITECTURE.md`. **No publishing automation or APIs built** |**No publishing automation or APIs built** |
| **Garage object storage** | 🟡 **Architecture direction approved (AP-25 to AP-38); deployment and production cutover NOT approved (AP-39)** | `docs/GARAGE_STORAGE_FINAL_ARCHITECTURE.md`. Second review approved write-once versions and a fixed working directory. Topology (G2) open until server specs. **Nothing installed, created or configured.** The owner's latest message was cut off; further "details to settle first" are awaited. **Architecture approval is not deployment approval.** |
| **VPS production environment** | 🟡 **Read-only inspection done; design written; NOT deployed** | `docs/VPS_PRODUCTION_READINESS.md`. AP-40 to AP-43: the Contabo VPS is the central production environment for both projects; Windows is administration only. Server is clean and idle (Ubuntu 24.04, 4 vCPU, 7.8 GiB, no swap, one 100 GB disk, only SSH open); **nothing for Stickman is installed there**. 15 open decisions (P1–P15). **Architecture approval is not deployment approval.**  **Owner-confirmed (AP-44): the Kids session is the sole shared-infrastructure coordinator;** five mandatory safeguards recorded (AP-45 to AP-49); not blanket approval (AP-50). |
| Character artwork, tooling, pilot production | ⛔ Not started (gated) | |

## 2. Direction changes from the owner today (override earlier approvals)
1. **World at large.** No Nigerian/African-specific stories, settings, names or language (reverses part of AP-3).
2. **Femi is retired; a different character is wanted.** The whole proposed cast was West African-coded and is paused.
3. **Exploration direction:** simple 2D stickman characters with thin limbs and expressive eyes/brows, in richly illustrated, layered environments. Recorded as the preferred direction **for exploration**, not a final approval.
4. **Reference picture:** received (a vertical TikTok frame) and inspected.
5. **Multi-platform brand:** YouTube, TikTok and Facebook; **9:16 primary, 16:9 secondary**; reusable assets across ratios; international, original content; **no publishing automation or API connections yet** (AP-19 to AP-24).
6. **Visual identity permanently locked** to the canonical image (simple expressive 2D characters + richly illustrated cinematic 2D environments); the pictured character is the master character; no alternatives or silent changes (AP-51 to AP-57).

## 3. Approved vs proposed (summary; full register in `DECISIONS.md`)
**Approved:** channel concept and pillars; original identity (no copying); hybrid animation; lightweight locally rendered production; balanced relationship humour; pilot title idea; renderer unchanged; phase-gated work; Codex policy (AP-15); the direction changes above (AP-16 to AP-18); the multi-platform direction (AP-19 to AP-24); the Garage storage principles (AP-25 to AP-36; architecture only, not deployment).
**Proposed / open:** the visual identity (V1), the new character (V8), the proof of concept (V6), Bible rewrite scope (V9), and most `D1–D23` items (several are now superseded).

## 4. Environment (verified)
| Item | State |
|---|---|
| OS / shell | Windows 10 Pro; PowerShell and Git Bash |
| Node / npm | 24.13.1 / 11.8.0 |
| FFmpeg / FFprobe | 9.0.2 at `C:\Users\PC\tools\ffmpeg\bin` (user PATH) |
| Skill dependencies | `npm ci`: `@napi-rs/canvas` 0.1.100, `sharp` 0.35.5. Manifests unchanged (still CRLF by owner instruction) |
| Python | 3.14.3; `PYTHONUTF8=1`; no `python3`; Whisper not installed |
| GPU / Docker | None needed / installed, unused |
| `doctor` | 6/6 |
| Tests | Node 134/135 (one upstream Windows path bug); Python 11/14; shell 0/2 (Windows, macOS-only, no-`.git` causes) |
| Backups | `C:\Users\PC\Desktop\Works\_backups\stickman-pre-lf-20261111` |

## 5. Technical findings so far
- **The unmodified renderer can do layered depth** (back/mid/front parallax, sprite + baked shadow, pose swaps, snap zoom, shake, tint overlay). Spike output: `C:\Users\PC\Desktop\Works\stickman-video-director\studio-work\spike-layered-depth\output\preview.mp4` (H.264 + AAC, 180 frames, 77 s to render ≈ 0.43 s/frame). Frames: `bible/concepts/spike-layered-depth-frames.png`.
- **Limits** (code-verified): smooth camera needs one keyframe per frame; no mirroring, no desaturation, rotation only about the layer's top-left, one audio file, no video inside shots.
- **Minimal external tooling is needed** (asset exporter, project/camera builder, plate post-processor, overlay baker, audio mixer), **all outside the renderer.** Prototypes of the first two exist as throwaway concept code.
- **Open risk:** a rich painted plate makes a flat character look pasted on; the proof of concept is designed to test this.

## 6. Codex integration
| Item | Status |
|---|---|
| Installed / authenticated | ✅ `codex-cli 0.167.0`; "Logged in using ChatGPT" (credentials never read) |
| Method | `codex exec` via Bash, prompt on stdin (quoted heredoc), `-i` for reference images placed before other options, `-o` for the final message, `--sandbox workspace-write`, `-C` a scratch directory |
| Output location | `~/.codex/generated_images` |
| Helper `genimg.sh` | Does not exist on this machine |
| Used so far | **One** task (agent: Codex; tool: built-in image generation): an empty living-room plate, scratch only, ~78 s; original preserved; inspected; copied to `bible/concepts/codex-plate-test/` as an experimental, non-authoritative record |
| **Not used** in the rich-environment investigation | Per the owner's instruction not to generate images during it |
| Rules | Scratch-only; inspect before copying; never overwrite authoritative assets; keep originals; log agent and tool; no silent switch to a paid API; Codex never bypasses an approval gate; model not exposed, quota unknown |

## 7. Operating restrictions in force
Renderer unchanged · **no installs, Garage deployment, firewall/DNS/Terraform changes or heavy jobs on the VPS; read-only inspection only** · no pilot production · **no Garage install, configuration, buckets or keys** (architecture approval is not deployment approval)** · no paid image/voice/video services · no dependency installs · no commits or pushes · existing files preserved · independent of Kids Animation Studio · **no image generation until the owner approves the proof of concept.**

## 8. Risks and blockers
- **Blocked on the owner:** the new character (V8), approval of the proof of concept (V6, now vertical-first), and the multi-platform proposals M10–M16.
- **Bible is inconsistent with current direction** until rewritten (V9); bannered, not fixed, to avoid rewriting twice.
- **No `.git`:** no change tracking.
- **Platform specs and policies are only partly verified:** YouTube Shorts and synthetic-content rules were read on official pages; **TikTok and Meta come from secondary sources only** (official pages could not be read). Research must be completed before any publishing automation.
- **Storage (if Garage is adopted):** Garage has no object versioning, no object lock and no bucket policies, so deletion/overwrite protection must come from write-once prefixes, restricted keys and a separate backup; a shared service still shares capacity and outages with the Kids project. No Garage host exists yet as far as the repository shows.
- **VPS findings (observed read-only):** no swap with 7.8 GiB RAM (OOM risk if heavy renders overlap); **one disk, so backups must be off-box and no target exists (blocker P4)**; SSH has root login and password authentication enabled; Ubuntu's Node is 18.19 (renderer needs ≥ 20); Node, FFmpeg, Garage, TLS proxy, monitoring and backup tools are all absent; the other project's repository sits under `/root`.
- **Absolute paths are baked into the renderer fingerprint and shot-cache keys [verified 2026-11-11]:** identical project content in three folders gave three fingerprints. An approved project must stay at a fixed absolute path; pulling it into a different folder would invalidate the preview approval and the cache (decision G17).
- **Renderer captions** sit at a fixed bottom position- **Renderer captions** sit at a fixed bottom position that platform interfaces cover in portrait; plan is to burn captions in externally (M12).
- **Unverified:** AI plate consistency across angles; ChatGPT image output commercial terms; YouTube policy on synthetic/repetitive content.
- **Originality:** compared against one frame only; the finished look still needs a by-eye check by the owner and ChatGPT.

## 9. Key paths
`docs/VPS_PRODUCTION_READINESS.md` (VPS production design) · `docs/GARAGE_STORAGE_FINAL_ARCHITECTURE.md` (final storage proposal) · `docs/GARAGE_STORAGE_ARCHITECTURE.md` (storage evidence) · `bible/MULTI_PLATFORM_ARCHITECTURE.md` (platforms, formats, reuse across ratios, research) · `bible/` · `bible/VISUAL_DIRECTION_RICH_ENVIRONMENTS.md` (current investigation) · `bible/concepts/` (boards, `src/` generator and spike builder, `codex-plate-test/`) · `C:\Users\PC\Desktop\Works\stickman-video-director\studio-work\references\` (drop the reference here) · `…\spike-layered-depth\` (spike) · `…\phase0-b1-example\` (Phase 0 render)
