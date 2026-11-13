# Next Steps — Oddly Relatable (Stickman Comedy Studio)

**Last updated:** 2026-11-13 (AP-84B3 research report filed; stopped at the gate). Work stops at each gate; nothing starts without the owner's approval.

## 1. Current (active)

0f. **AP-84B3-D1 decision (owner):** approve or decline the research-only experiment specification and cost validation (pinned model manifest, workflow spec, cost ceiling proposal, test protocol). See `docs/oddly-relatable/AP-84B3-TECHNICAL-DECISION-REPORT.md` §6 for the local facts D1 must cover. GPU budget stays $0.
0e. **REGISTRY PROMOTION BUILT — review:** `studio/lib/promotion.mjs`, job page "Check promotion". Nothing has been promoted; real promotions need real (non-synthetic) candidates, so they wait for generation (AP-84B3, needs its brief and a GPU budget). Still to build when wanted: "make current" (preview render + separate owner approval) and story version pinning.
0d. **AP-84B2 accepted; OWNER DECISIONS 2026-11-13 (post AP-84B2) recorded** (see DECISIONS.md). Next scope needs explicit owner approval: registry promotion implementation (local, $0) or AP-84B3 (needs its brief and a GPU budget).
0c. **AP-84B2 review:** Generation > Story requirements / Reference packs tabs and the validation report on each job page. Answer the open questions in `docs/oddly-relatable/REGISTRY-PROMOTION-DESIGN.md` §7 before any promotion work. AP-84B3 is not authorised; GPU budget stays $0.
0b. **AP-84B1 review:** generation foundation (`#/generation` in the studio; `STUDIO_GEN_ADAPTER=fake` shows labelled synthetic fixtures). AP-84B2 (asset requests from stories, reference pack, validators, registry promotion design) needs your approval; GPU work stays at $0 until you approve a budget.
0a. **Studio available (AP-83):** `node studio/server.mjs` (with FFMPEG/FFPROBE set), open http://127.0.0.1:4317/. Review Short 001 there: play the video, read QA, record a decision (approve for next step / request changes / reject). Please confirm the MP4 plays in your browser.
0. **Produce command available (AP-82):** `node production/cli.mjs produce production/stories/short-001-v2.story.json studio-work/short-001-production` (needs FFMPEG/FFPROBE). Short 001 technical run: QA pass with 4 softness warnings; evidence `production/evidence/ap82/`.
1. **Owner: review the AP-79 technical evidence** in `production/evidence/ap79/`: `short-001-ap79-technical-preview.mp4`, `short-001-ap79-storyboard.png`, `short-001-ap78-vs-ap79.png`, and the synthetic cast test `synthetic-two-member-technical-preview.mp4` / `synthetic-two-member-transitions-camera.png`.
2. **Resolve soft character close-ups before final production:** soft character close-ups: at the approved 1.5× zoom the four Short 001 poses are enlarged about 2× on screen (02: 2.03×, 03: 1.94×, 05: 2.03×, 06: 1.96×), above the 1.7× softness threshold. First assess whether Short 001's camera framing can be adjusted (for example, lower medium zooms) without changing the story; only then decide whether higher-resolution character assets are needed (any new artwork or generation needs separate approval).
3. **Owner decisions before production:** audio (silent, or licensed notification/typing sounds and music); whether any Short 001 pose change should use pop or crossfade (the script specifies none, so all are hard cuts); naming of Character 01.
4. **Final Short 001 production** (needs explicit approval, after item 2): final render, QA, platform-safe captions. No publishing.
5. **Future formats** (phone call, split screen, face to face, solo) and **Character 02**: designed for in AP-79, each needs its own approval and artwork decision.

**Approved now:** poses 02, 05 and 06 (working use); pose 03 (working TEST, splayed hands kept); character v3 (working candidate); SCRIPT_V2 (working script, hook "Four words. No warning."); AP-79 architecture and scope. **Not approved:** any final production master, final production, publishing.

**Future architecture (recorded):** multiple characters with their own registries and interactions; phone-call, split-screen, face-to-face, text-message, multi-scene and solo formats; separate layers for story, scene, character, dialogue/audio, camera, animation and render (DECISIONS.md AP-80R). AP-79 built the foundations; only text-chat is implemented.

## 2. Still-open infrastructure and platform items (unchanged; each needs its own approval)

### 2b. Multi-platform: next steps (no automation, no APIs)
1. **Owner:** review and approve or change the proposals **M10–M16** in `DECISIONS.md` (author once / render many; master rule; external caption burn-in; extra ratios; Facebook scope; account names; research step).
2. **Research (read-only, no cost):** complete the TODO in `bible/MULTI_PLATFORM_ARCHITECTURE.md` §13: official TikTok and Meta specs and policies, monetization eligibility, music licensing, 9:16 safe-zone templates, thumbnail and cover specs. Only after this can export presets and metadata templates be finalised.
3. **Later, after approval:** safe-framing overlay guides; export-preset and per-platform metadata templates (declarative files); an external caption burn-in step. **Publishing automation and platform APIs stay off** until separately approved.
4. Fold the multi-platform rules into the Bible rewrite (V9).

### 2d. VPS production environment: next actions (planning done; nothing deployed)

> **Architecture approval is not deployment approval.** Everything below that changes the server needs its own approval and is a **shared, coordinated** change with the Kids project. Details: `docs/VPS_PRODUCTION_READINESS.md`.

**Owner confirmed (2026-11-11):** the Kids session is the **sole shared-infrastructure coordinator** (AP-44), so steps 1–4 below (server security, backup and monitoring, Garage, buckets) are **coordinated by it**, each still behind the owner's approval; Stickman owns steps 5–7 for its own project. **Mandatory safeguards (AP-45 to AP-49):** real large multipart upload test of Caddy; no irreplaceable assets in Garage before an off-server backup and a successful restore test; one heavy render across both projects initially; SSH hardening only with verified key access and a rollback; public services on 80/443 with SSH restricted separately. **This is not blanket approval (AP-50).**

0. **Owner: reconcile the Kids and Stickman reports** and answer **P1–P15** in `DECISIONS.md` (the blockers are P4 off-box backup target, P1 repository transfer/version control, P2 Node ≥ 20 source, P3 DNS name, P5 swap and limits, P6 SSH hardening, P13 naming).
1. **Step 1 (shared): server security, directories, storage:** admin and per-project users; `/srv/stickman` tree; systemd slices and limits; SSH hardening; swap decision.
2. **Step 2 (shared): independent backup and monitoring.**
3. **Step 3 (shared): one coordinated Garage deployment with TLS.** Not by this session alone.
4. **Step 4: create `stickman-studio` and the four key roles;** test isolation and the unconfirmed Garage features.
5. **Step 5: prepare the Stickman environment:** Node ≥ 20 and FFmpeg, repository transfer, `npm ci`, environment file, FFmpeg limiting wrapper, shared render lock.
6. **Step 6: integrate:** `tools/storage/` and a dry run on the Phase 0 example.
7. **Step 7: test rendering and recovery:** the benchmark plan (not run yet), restore drill, concurrency test with the other project.

### 2c. Storage (Garage): principles approved; deployment NOT approved

> **Architecture approval is not deployment approval.** Nothing is installed, created or configured. Each step below needs its own approval. Design: `docs/GARAGE_STORAGE_FINAL_ARCHITECTURE.md`.

0. **Owner: please resend the rest of your last message.** It was cut off after "Fixed working directory: Approved"; the "few important details to settle first" did not arrive. Recorded so far: architecture direction approved; local-first, separate buckets, write-once versions and fixed working directory approved (AP-25, AP-27, AP-28, AP-37, AP-38); **deployment and production cutover not approved (AP-39)**.
1. **N1: Owner supplies the Garage server specifications** (existing server or new; hosts, operating system, disks, network, node count, replication, administrator). *Server specifications were observed read-only on 2026-11-11 (see `docs/VPS_PRODUCTION_READINESS.md`): one Contabo VPS, 4 vCPU, 7.8 GiB RAM, no swap, one 100 GB disk. Topology is still open (single node, no off-box backup yet). Server addresses, key names and secrets are deliberately not recorded in these documents.* This resolves **G2** (topology), which is deliberately open until then; I will update the final proposal when it arrives.
2. **N2: Owner decides the remaining open items:** G4 (secret storage method), G5 (transfer client), G6 (backup target, schedule, retention), G8 (encryption at rest), G13 (extra archive bucket?), G14 (names and key set), G15 (sync list), G16 (export naming), G17 (**fixed absolute working root**), G18 (repository backup), G10 (Terraform scope).
3. **N3 (separate approval):** provision a **test** Garage instance behind TLS.
4. **N4 (separate approval):** create the bucket and keys on the test instance; verify quotas, the no-create-bucket flag, delete behaviour and large uploads.
5. **N5 (separate approval):** choose and install the transfer client, or approve small scripts.
6. **N6 (separate approval):** build `tools/storage/` (config check, manifest, pull, push, verify), with **no renderer change**.
7. **N7 (separate approval):** dry run on the Phase 0 example as a non-production episode (push, remove local copy, pull, re-render at the same path, compare).
8. **N8 (separate approval):** backup target, backup job and a restore drill on test data.
9. **N9 (separate approval):** production cut-over with the real bucket and keys.

## 3. Standing rules (current)
Renderer unchanged · no image generation, paid services or new dependencies without approval · never overwrite, delete or rename assets (new files only) · commit and push only reviewed files with normal pushes (never force) · no publishing · no VPS or shared-infrastructure changes without approval · do not touch the Kids Animation Studio project · Codex never bypasses an approval gate.

## 4. Archive: earlier-stage steps (superseded; kept for history, NOT current instructions)

> These come from earlier stages (before the visual identity lock, Canonical Character 01, the pose corrections, the toolkit and version control). Several contradict the current direction, for example "new lead character needed", "commit or push" forbidden, and "generate images before the proof of concept". Kept verbatim for history only.

### 1. Immediate (gate G1: inputs and approvals from the owner)

| # | Item | Who | Notes |
|---|---|---|---|
| 1 | ~~Drop the reference picture~~ **Done:** received and inspected (report §0) | Owner | Private copy kept outside the repo |
| 1b | ~~Format priority (V10)~~ **Resolved:** 9:16 primary, 16:9 secondary (AP-20) | Owner | See the multi-platform steps below |
| 2 | **The new lead character** (V8): a description or a reference, or tell me to propose options | Owner | Femi is retired. I will not invent a character unprompted |
| 3 | **Approve the proof of concept** (V6): one new character, one living room, 12–15 s, unmodified renderer, up to 4 Codex images | Owner | See `bible/VISUAL_DIRECTION_RICH_ENVIRONMENTS.md` §8 |
| 4 | Visual direction (V1) and flatness (V2) | Owner | Can be settled by the proof of concept |

### 1b. Visual identity: LOCKED (nothing to decide)
**The visual identity is permanently locked** to `bible/concepts/lookdev-richenv/lookdev-scene-01.png` (AP-51 to AP-57). Both authorised technical tests are done and passed (strongly on-model character; near-identical empty room). **No alternatives will be proposed.**

**AP-78 done: your review needed.** Watch `production/evidence/ap78/short-001-v2-compat-preview.mp4` and look at `short-001-v2-storyboard.png`. Decide: approve the toolkit; approve SCRIPT_V2 (with the hook change); pose 06 skin correction; poses 02 and 05 review; then AP-79 (integration) / AP-80 (production).

**(Earlier) AP-76 done: your visual review needed.** View `bible/concepts/lookdev-richenv/ap76-pose05-test/compare-sheet-1-full-figures.png` and `compare-sheet-2-closeups.png`; approve or reject corrected pose 05 (and pose 02 from AP-75). Draft script for the first short: `bible/episodes/short-001-we-need-to-talk/SCRIPT_DRAFT.md` (awaiting your approval).

**(Earlier) AP-75 done: your visual review needed.** View `bible/concepts/lookdev-richenv/ap75-pose02-test/compare-sheet-1-full-figures.png` and `compare-sheet-2-closeups.png`. Approve or reject corrected pose 02; then choose the next pose (01, 04, 05 or 06) or move to producing the first real short. Pose 03 is approved as a working test asset.

**(Done) AP-74: your visual review needed.** View `bible/concepts/lookdev-richenv/ap74-pose03-test/compare-sheet-1-full-figures.png`, `compare-sheet-2-closeups.png`, `compare-shot2-ap60-ap72-ap74.png`, `closeups-shot2-ap60-ap72-ap74.png` (attach them in your review chat). Decide: approve or reject corrected pose 03; whether to continue with other poses; and how to get sharper close-ups (higher-resolution poses need approval). No other pose will be corrected without your approval.

**AP-73 assessment done: your decision needed.** Read `bible/concepts/lookdev-richenv/POSE_LIBRARY_ASSESSMENT.md`. Approve (or change) the recommended controlled test on pose 03 shocked (skin-only first, new files only), and decide hand design for the splayed gesture. Nothing has been extracted or corrected.

**AP-71/72 done: review needed.** Read `bible/concepts/lookdev-richenv/ap72-validation/README.md` and view `compare-ap60-vs-ap72-sidebyside.png` and the close-ups (attach them in your review chat; I cannot upload). Decide: how to obtain more poses at v3 quality (new generation needs your approval; or reuse the sheet poses with a matched skin/hand correction), and whether to proceed to cut-out/overlay workflow. Nothing promoted.

**AP-70: hands v3 ACCEPTED as the working candidate; hand revisions stopped. Pending:** your final visual sign-off (attach `review-sheet-v3.png` in your review chat); approval of a proposed **production-ready asset workflow** (character: pose set from the corrected master with consistent hands/skin, cut-outs, depth layers; environment: plate handling, foreground overlays; naming, hashing, review gates). Not started; needs your go-ahead. Sweater/shoes unchanged; nothing promoted to final master; no more character images.

**(Superseded by AP-70) AP-69: hands v3 produced; your visual approval needed.** Attach `production-candidates/corrected/review-sheet-v3.png` (or `compare-full-body.png` and `compare-hands-closeup.png`) to your review chat; I cannot upload them from here. Then accept v3 or ask for another hand tweak. Sweater and shoes remain unchanged until you say. Nothing is promoted to final master.

**AP-67 done as a candidate; your visual approval needed:** review `production-candidates/corrected/compare-*.png`. Decide: accept v2, or ask for hands closer to the canon (curved fingers), and whether the sweater (about 12% brighter) and shoes (paler) should also be matched. Nothing is promoted to final production master until you say so. Still open from AP-63 to AP-66: any resolution route beyond classical resampling (a Real-ESRGAN test needs a download approval).

**AP-63 to AP-66 assessed: awaiting your approval of:** (1) executing the correction plan as new files (skin gain on a mask; hand-traced vector rounded mitts); (2) answer: is the target hand the canon mitt with finger bumps or a plain rounded mitt; (3) one controlled test of a portable Real-ESRGAN-ncnn-vulkan binary on copies (download = install, needs approval); (4) whether to verify and consider any paid higher-resolution route later. Details: `bible/concepts/lookdev-richenv/production-candidates/upscale-tests/README.md` §5.

**AP-61/62 done: two production candidates generated (not approved). Owner decisions needed:** accept or reject each candidate; how to reach true production resolution (the Codex tool caps near 1024×1536 / 941×1672; options: an upscaling step, an approved image API, or tiled/regional work); how to fix the hands (rounded mitts) and skin tone. No further images without approval.

**Steps 1 to 3 are DONE (AP-58 to AP-60):** six poses cut out, composite tested, 8 s vertical render completed with the unmodified renderer. Awaiting creative direction. Candidate next steps (each needs approval): higher-resolution character/plate assets; depth-layer overlays for foreground occlusion and parallax; per-pose colour and outline normalisation; in-between frames or mouth/eye swaps.
4. Decide **naming and personality** for Canonical Character 01 (a creative decision for you).
5. **Any additional character, location or generation** (including a depth-layered plate, another angle, or a new character) needs your explicit approval first. Images used so far: **3**.

### 2. Reference picture: done
Inspected and compared; the originality safeguards in the report §7 now name what we will not reuse. Add any further reference frames to the same folder if you want them considered.

### 3. After G1: the proof of concept (see the report §8)
P1 design the new character for approval → P2 three plate candidates for the same shot (improved procedural room; Codex plate set, at most 4 images; the Codex plate flattened locally) → P3 compose a 12–15 s **vertical (9:16)** test with the unmodified renderer, then a 16:9 reframe of the same scene graph (tests the reuse approach) → P4 side-by-side review. Acceptance criteria are in the report.

### 4. After the proof of concept: decide, then rewrite (gate G2)
- Lock the visual identity (V1–V3).
- **Rewrite the Bible for the world at large** (V9): cast, world, comedy guide, audio, content strategy, pilot treatment, language notes, cultural rules. Remove the West African setting and names; keep reusable structure (six-beat comedy framework, formats, hybrid-animation rules, content pillars).
- The pilot title "When Your Wife Says We Need to Talk" may stay, but the story and characters need re-writing around the new character.
- Owner approves the finished Bible.

### 5. After G2: tooling foundations and pilot (each needs its own approval)
Asset exporter, project/camera builder, plate post-processor, overlay baker, audio mixer (all outside the renderer); voice and music sourcing decisions; final script, storyboard, preview, full render, QA, Shorts. Any dependency install (e.g. Blender, Whisper) needs explicit approval first. A `git init` is the owner's call.

### 6. Housekeeping
Keep the five root progress files current. Mirror docs to Confluence only after the Bible is approved (the Atlassian connector must be authorised first).

### 7. Standing "do not"
Change the renderer · start pilot production · generate images before the proof of concept is approved · add paid image/voice/video services · install dependencies · commit or push · touch Kids Animation Studio · let Codex bypass an approval gate.
