# Progress Log — Stickman Comedy Studio

Chronological, newest last. Each entry records what was done, by which agent and tools, files changed, verification and blockers. **Agent:** Claude Code unless stated.

---

## 2026-11-10 · Repository assessment (read-only)
- **Work:** inspected the repository structure, the Skill's `SKILL.md`, references, scripts, tests and credits; assessed architecture, capabilities, automation, providers, costs and licensing risks; drafted the channel architecture, pilot workflow and phases.
- **Tools:** Bash, Read, Grep; Claude API skill (for model/pricing facts).
- **Files changed:** none.
- **Key findings:** the repo is an AI-agent Skill plus a local Node renderer (no app, no backend); only a Gemini connector is bundled; the renderer takes one audio file and has no image pivots, groups or tints outside style B3; bundled B5 examples include third-party IP and CC-BY music that must not be reused.
- **Blockers:** none.

## 2026-11-10 · Phase 0: environment setup and validation
- **Work:** installed FFmpeg/FFprobe 9.0.2; ran `npm ci` from the lockfile; ran `doctor`, the Node tests and the Python/shell checks; rendered the bundled B1 offline example (preview and full).
- **Tools:** PowerShell, Bash, Node, FFmpeg. No network calls to AI services.
- **Files and system changes:** FFmpeg at `C:\Users\PC\tools\ffmpeg` (user PATH updated); `skills/directing-stickman-videos/node_modules` (git-ignored); render workspace `C:\Users\PC\Desktop\Works\stickman-video-director\studio-work\phase0-b1-example`; a throwaway test copy in the scratchpad.
- **Verification:** `doctor` 6/6; Node tests 101 pass / 34 fail on the CRLF copy (cause found: line endings); on an LF-normalised scratch copy 134/135; the example MP4 is H.264 1280×720 30 fps 16.4 s with AAC audio, decodes cleanly.
- **Blockers found:** all text files were CRLF, which broke the B4/B5 hash locks.

## 2026-11-11 · Phase 0.1: line-ending fix
- **Work:** full hashed backup first; normalised 172 text files from CRLF to LF in place (byte-level, verified); re-ran diagnostics, tests and the render.
- **Tools:** PowerShell (robocopy), Node (normaliser in the scratchpad), Bash.
- **Files changed:** 172 text files (content identical except removal of carriage returns). Excluded by instruction: `package.json`, `package-lock.json`.
- **Backup:** `C:\Users\PC\Desktop\Works\_backups\stickman-pre-lf-20261111` (733 repo files + 21 workspace files, each hash-verified; plus `LF-NORMALIZATION-REPORT.json`).
- **Verification:** B4 style lock pass; B5 Spider-Man baseline pass; Jensen V13 lock pass (230 files + video); `doctor` 6/6; Node 134/135; Python 11/14; shell 0/2 (as-is). Re-render was byte-identical to the Phase 0 render. Manifests unchanged.
- **Remaining failures (not environmental):** an upstream Windows path-separator test bug; a macOS-only font path; a README/test inconsistency about a referral link; tests needing `.git` or `python3`. Upstream tests were not modified.

## 2026-11-11 · Phase 1: Channel Bible (draft)
- **Work:** wrote ten documents in `bible/`: `CHANNEL_BIBLE`, `VISUAL_IDENTITY`, `CHARACTER_BIBLE`, `WORLD_BIBLE`, `COMEDY_WRITING_GUIDE`, `ANIMATION_DIRECTION`, `AUDIO_DIRECTION`, `CONTENT_STRATEGY`, `EPISODE_FORMATS`, `PILOT_TREATMENT` (about 19,000 words). All content labelled APPROVED / PROPOSED / DECISION; 23 open decisions (D1–D23).
- **Tools:** Write, Edit, Bash. No generation of any media.
- **Files changed:** created `bible/*.md` only. Nothing else touched.
- **Verification:** 733 pre-existing files untouched; manifests unchanged; no CRLF in the new files.
- **Corrections made during the work:** a camera-zoom recommendation relied on group layers that exist only in style B3 — corrected; D22 was missing from the decision list — added.

## 2026-11-11 · Visual-direction comparison (Inkblock vs 2.5D Modern Pop)
- **Trigger:** owner's Project Operating Agreement reopened visual identity; the emerging preference is 2.5D Modern Pop; Inkblock is an alternative.
- **Reference inspection (actually accessed):** extracted six frames each from `assets/readme/style-2a-demo.mp4` and `style-2b-demo.mp4` with FFmpeg and viewed the contact sheets; read the Style 2 text in `style-catalog.md`. **Not inspected:** the GIF previews, `examples.md`, the outside X thread, any outside channel.
- **Work:** wrote a local SVG concept generator; produced the same Femi in the same three poses for both concepts, a perspective living room for B, a flat stage living room for A, a "Doom Tint" example, a flat-vs-lit-vs-cel test, and a side-by-side board. Wrote `bible/VISUAL_DIRECTION_COMPARISON.md`.
- **Tools:** Claude Code with Node and the already-installed `sharp` (no new dependency, no network, no AI service).
- **Files created:** `bible/concepts/*.png` (9), `bible/concepts/svg/*.svg`, `bible/concepts/src/generate-concepts.cjs`, `bible/VISUAL_DIRECTION_COMPARISON.md`, and the five root progress files.
- **Verification:** viewed every board. Fixed two defects found on inspection: Femi was ~4.7 heads tall (spec is 3.6) and the cast shadow floated away from the feet.
- **Known limits:** it is concept art, not final; the Level 3 cel shading is crude; the perspective room is simply furnished.
- **Result:** awaiting the owner's decision V1–V5.

## 2026-11-11 · Codex integration check and first delegated task
- **Check (read-only):** `codex-cli 0.167.0` installed; `codex login status` = logged in with ChatGPT; credentials file never read. No `genimg.sh` helper exists, so the stdin-heredoc method is used.
- **Delegated task:** **Agent:** Codex. **Tool:** its built-in image generation (model not exposed). **Task:** one empty 16:9 living-room background plate (no characters) from a character-free layout reference rendered by Claude Code. **Scope:** scratch folder `…\scratchpad\codex-work`, not the repository.
- **Outcome (completed):** exit code 0, about 78 seconds, exactly one image. Codex's reported original is `C:\Users\PC\.codex\generated_images\01a1c903-1f99-76a2-99a3-7f36660d55be\exec-56ddb1ce-504b-4224-881e-bb68bdcdaffe.png` (left untouched). Its scratch copy was byte-identical (SHA-256 checked). Claude Code inspected it before use: 1672×941, no people/text/logos, layout and palette matched. Copied (not moved) into `bible/concepts/codex-plate-test/` as a labelled **experimental, non-authoritative** record with a README of provenance.
- **Claude Code follow-up (local, no further Codex use):** composited the flat Femi onto the plate to judge integration. Finding: the plate is much richer than the procedural room, but the soft painted look clashes with the flat hard-outlined character; resolution is below the planned master; lighting is baked into a single layer. Consistency across angles is unproven.
- **Cost / quota:** no API call; ChatGPT image allowance used (remaining quota unknown). Codex reported 24,376 text tokens for the run.
- **Effect on decisions:** V2 (character flatness) and V3 (environment route) are linked; see `bible/VISUAL_DIRECTION_COMPARISON.md` §9.
- **Also changed:** `bible/concepts/src/generate-concepts.cjs` gained `--empty-reference DIR` and `--composite PLATE OUT` options. A first attempt to add `--composite` through a shell one-liner failed on quoting (nothing was applied; the generator re-ran and re-wrote the same boards), then it was applied with the Edit tool.

## 2026-11-11 · Investigation: simple 2D characters in rich illustrated environments (owner's new reference direction)
- **Trigger:** owner message describing a TikTok screenshot as the strongest reference. **The screenshot was not attached and was not found** in Downloads, Desktop, Pictures, the repo or the workspace; nothing about it was described or assumed beyond the owner's text.
- **Instruction constraints followed:** no images generated (including by Codex), no paid calls, renderer unchanged, no pilot production, no full cast, no commits.
- **Repository inspection (actually accessed):** six frames each from `style-4-cozy-cafe.mp4` and `b2-colorful-sleep.mp4` viewed (plus the earlier 2A/2B frames); `cozy-storytelling.md` read. Finding: A4 Cozy is the closest match (a simple stick figure in a richly illustrated café with depth and a foreground leaf pass) but was produced by AI video generators, not by the renderer; B2, made by the renderer, is flat and poster-like.
- **Technical spike (Claude Code, unmodified renderer, local art only):** exported three room layers, a tint overlay, and flat sprite + baked shadow PNGs for three poses (`--export-spike`); wrote a throwaway builder with per-frame camera keys; `validate` passed; `preview --seconds 6` rendered 180 frames at 1920×1080 in 77 s; FFprobe: H.264 1920×1080 30 fps 6.0 s + AAC; full decode OK; viewed an 8-frame sheet and a full-size deep-zoom frame. Verified: parallax, sprite compositing, shadows, pose swaps, snap zoom, shake, tint fade. No foot slip visible (not measured numerically).
- **Code-verified limits:** per-segment smoothstep (needs per-frame keys), no mirroring, no desaturation, rotation about the top-left only, one audio file, images only.
- **Also drawn locally:** a thin-limb test figure (`--thin-limb-test`) using the retired Femi template, only to show construction; crude, not a proposed character.
- **Files created:** `bible/VISUAL_DIRECTION_RICH_ENVIRONMENTS.md`; `bible/concepts/C-thinlimb-scene.png`, `C-thinlimb-femi-sheet.png`, `spike-layered-depth-frames.png`, `src/spike-build-layered-depth.cjs`; generator options `--export-spike` and `--thin-limb-test`; outside the repo: `…\studio-work\spike-layered-depth\` (assets, project.json, silent.wav, output).
- **Verification:** renderer scripts and package manifests unchanged (hash check; no Skill file modified); all outputs viewed.
- **Process note:** a shell one-liner that tried to patch the generator failed on quoting earlier today and was redone with the Edit tool; nothing was applied by the failed attempt.
- **Codex usage here:** none.

## 2026-11-11 · Owner direction change: world at large, Femi retired
- **Messages received:** (1) no Femi and no African stories, "it has to be world at large"; (2) "that is why I am giving you a character change"; (3) the owner will drop a reference picture in the folder.
- **Actions:** recorded AP-16 to AP-18 in `DECISIONS.md` (AP-3's African clause marked superseded; V4 withdrawn; V6–V9 added); added a "PARTLY SUPERSEDED" banner to ten Bible documents (`CHANNEL_BIBLE`, `CHARACTER_BIBLE`, `WORLD_BIBLE`, `COMEDY_WRITING_GUIDE`, `AUDIO_DIRECTION`, `CONTENT_STRATEGY`, `PILOT_TREATMENT`, `VISUAL_IDENTITY`, `ANIMATION_DIRECTION`, `VISUAL_DIRECTION_COMPARISON`), content otherwise untouched; adjusted the rich-environment report so the proof of concept needs a new character and no region-specific setting; created the empty reference folder `…\studio-work\references\`; rewrote `PROJECT_STATUS.md` and `NEXT_STEPS.md`.
- **Deliberately not done:** no replacement character was invented; the Bible was not rewritten (to avoid rewriting twice before the visual direction and character are chosen).
- **Reference check:** the folder was empty when checked; no picture seen yet.

## 2026-11-11 · Reference picture received and inspected
- **Received:** the owner pasted a phone screenshot (710×1536 JPG) into the chat; it was read directly. A private copy was saved outside the repo at `…\studio-work\references\tiktok-reference-1.jpg` (SHA-256 prefix 16d4d596…); not added to the repository because it is a third party's artwork.
- **Observed and recorded** in `bible/VISUAL_DIRECTION_RICH_ENVIRONMENTS.md` §0: vertical 9:16; thin black limbs; large expressive eyes and brows; a richly illustrated, layered living room; the character interacts with the sofa; limited palette echoing the room; the app labels it "Contains AI-generated media". Not judgeable from one frame: motion, layering, shadows, method.
- **Changes made:** report §0 rewritten from "not seen" to the observations; §7 originality safeguards made specific; V7 resolved; V10 (format priority) added; status and next steps updated.
- **No generation, no Codex use, no new dependencies.**
- **Owner question about "another stick man video copy":** answered in chat. The copies present are the Phase 0.1 safety backup (`_backups\stickman-pre-lf-20261111`, requested by the owner), my own temporary scratch copy of the repo in the session temp folder (to be offered for deletion), and the reference JPG copy above.

## 2026-11-11 · Multi-platform direction: architecture and platform research
- **Owner direction (approved):** YouTube, TikTok and Facebook; **9:16 primary, 16:9 secondary**; international original content, African/Nigerian storytelling must not define the identity; do not double production work; per-episode packages (complete episode, short edits, platform hooks/captions/titles/descriptions/thumbnails, safe framing); do not assume identical uploads; research specs and policies before automation; **no publishing automation or APIs yet**. Recorded as AP-19 to AP-24; V10 resolved; D14 superseded.
- **Research (Claude Code; WebSearch ×6 and WebFetch ×4; no cost, no accounts, no personal data sent):**
  - **Read on official pages:** YouTube Help *Shorts* (up to 3 minutes; vertical uploads; 1080p maximum; title ≤ 100 characters; "made for kids" selection) and YouTube Help *altered or synthetic content* (disclosure required for realistic AI-generated or altered content; **not** required for non-realistic content such as fully animated video; minor edits including captions and cloning your own voice are exempt).
  - **Secondary sources only (unverified):** TikTok specs (1080×1920; length reports conflict), TikTok AI labelling (scope conflicts), Facebook Reels specs (length unclear), Meta March 2026 originality guidance (reposts and lightly altered content demoted), YouTube "inauthentic content" (renamed from "repetitious" in July 2025).
  - **Could not retrieve:** TikTok's official AI-content help page (page did not render) and a Meta transparency page (404).
- **Repository inspection for the architecture:** re-read the renderer's portrait and caption handling: design plane is 1280 × (1280·height/width); captions are drawn at a fixed position 60 design units from the bottom with the bottom 110 units reserved, and captions are mandatory in the project file. Hence the proposal to burn captions in externally.
- **Work product:** wrote `bible/MULTI_PLATFORM_ARCHITECTURE.md` (principle "author once, render many"; content tiers; square superframe plates with 9:16 and 16:9 windows and a central action-safe square; scene graph; framing profiles; platform matrix with evidence labels; export presets and per-platform metadata as declarative proposals; per-episode folder layout; risks; research TODO; decisions M10–M16). Updated `CHANNEL_BIBLE.md`, `CONTENT_STRATEGY.md`, `EPISODE_FORMATS.md`, `PROJECT_STATUS.md`, `DECISIONS.md`, `NEXT_STEPS.md`, `HANDOFF.md` and the rich-environment report (proof of concept now vertical-first with a 16:9 reframe).
- **Not done (by instruction):** no publishing automation, no platform API connection, no accounts, no code for export or metadata, no renderer change, no image generation.
- **Estimate flagged:** extra effort for the second aspect ratio ≈ 10–25% per episode if staged in the safe square from the start. This is an assumption, not a measurement; it should be measured in the proof of concept.

## 2026-11-11 · Garage object-storage assessment (architecture planning only)
- **Request:** the owner is considering a shared, self-hosted Garage (S3-compatible) service instead of AWS S3, with a separate bucket and credentials per project; asked for an assessment, no implementation.
- **Repository evidence (read-only):** strict search found **no** S3, Garage, MinIO, bucket, presigned-URL or AWS SDK usage in code, tests, docs or scripts; the only network call is the optional Gemini adapter; dependencies are only `@napi-rs/canvas` and `sharp`. The renderer **rejects URLs** (`autopilot-core.mjs:31`), requires a real local `output/` with no symlinks (`:141,145`), keeps inputs out of `output/` (`:151`), uses temp-file-plus-rename writes and an exclusive lock file (`autopilot-render.mjs:169-175, 195-217`), and the B5 route writes a PNG per frame to disk. `.gitignore` already excludes `.env` and `.env.*`; `doctor` reports key presence only.
- **Measured sizes:** B1 film 43 KB/s (16.4 s at 1280×720, 704,145 B); layered spike 194 KB/s (6 s at 1920×1080, 1,162,725 B); shot cache ≈ final video size; spike sources 736 KB for 10 PNGs; Codex plate 1.56 MB; repository 337.8 MB; local backup 332 MB.
- **Garage documentation read (official, WebFetch ×6):** S3-compatibility, quick start, deployment, features, monitoring, reverse-proxy pages (examples show v2.5.0). Confirmed: multipart and presigned URLs supported; **no versioning, no object lock, no bucket policies**; lifecycle limited to expiration and aborting incomplete multipart uploads; **SSE-C only**; per-bucket read/write/owner key permissions; port 3900, region `garage`; 3 replicas / at least 3 nodes recommended; XFS, metadata on SSD, LMDB snapshots; TLS via reverse proxy; Prometheus metrics on 3903. **Not confirmed:** bucket quotas, a no-create-bucket key flag, a separate delete permission, checksums, scrub. The S3-compatibility page itself warns it may be outdated (history ends May 2022).
- **Work product:** wrote `docs/GARAGE_STORAGE_ARCHITECTURE.md` (confirmed implementation vs proposal vs open questions; layout; workflow options; reliability and security; tool compatibility; storage estimates; risks; decisions G1–G12). Updated `DECISIONS.md`, `PROJECT_STATUS.md`, `PROGRESS_LOG.md`, `NEXT_STEPS.md`, `HANDOFF.md`.
- **Conclusion:** recommend **local-first** (pull, render locally, push, retrieve). Streaming is infeasible without renderer changes; mounting is not recommended.
- **Not done (boundaries):** Garage not installed, deployed or configured; no bucket or key created; no secrets read, copied or written; no application code, workflow or dependency changed; nothing committed; existing assets, backups and scratch files preserved. The Kids project was not inspected.
- **Process note:** the multi-platform record updates earlier today first stopped halfway because one anchor string didn't match; I fixed the anchor, made the script skip the four files already updated, and re-ran it. All nine files were then verified to carry the update.

## 2026-11-11 · Garage storage: final architecture proposal
- **Owner decision:** approved the Garage design principles (12 items, recorded as AP-25 to AP-36): local-first rendering; Garage as the shared self-hosted S3-compatible service; dedicated bucket and credentials for this project; a completely separate bucket and credentials for the Kids project; active rendering, cache, lock and temporary files stay local; upload approved assets and completed outputs; private by default with no public links without explicit approval; independent backups outside the Garage server; TLS and secure credential handling; selective sync; no streaming or mounting; no publishing automation. **Deployment topology and other items deliberately left open until server specifications are confirmed.**
- **Review of the assessment:** re-read `docs/GARAGE_STORAGE_ARCHITECTURE.md` against the approvals. One error found and corrected (see below).
- **New verified finding (experiment):** copied the Phase 0 project (`project.json` and narration, byte-identical by SHA-256) into two scratch folders and ran `validate` in all three locations: **three different fingerprints** (`58fc908e…`, `f1b3ef22…`, `a4784f4c…`). Cause: absolute input paths are part of the fingerprint (`autopilot-core.mjs:135-137`) and of each shot's cache key (`autopilot-render.mjs:194`). Consequence: a project downloaded into a different folder would lose its preview approval and cache hits, so the design requires a **fixed absolute working root** (decision G17). The experiment used scratch copies only (`…\scratchpad\path-test`, left in place); nothing else was changed.
- **Correction to the assessment:** it said `approval.json` is "machine-bound, do not store". Accurate position: it is **path-bound provenance**; store it as a read-only record with each release, never as a live input. A banner on the assessment records this.
- **Work product:** wrote `docs/GARAGE_STORAGE_FINAL_ARCHITECTURE.md`: approved principles; unresolved decisions kept open (topology G2, secret method G4, client G5, backup specifics G6, retention G7, encryption G8, Terraform G10) plus new G13–G18; proposed bucket `stickman-studio` (placeholder) and four key roles; full object-prefix layout (masters, YouTube/TikTok/Facebook exports, captions, thumbnails, covers, publish metadata, rights ledger, releases, optional archive); write-once versioning and release manifests; the local-first download, render and upload workflow with failure handling; what stays local and what is uploaded (four tiers); backup and recovery design with scenarios and a restore drill; credential and TLS rules with project-prefixed variable names (placeholders only); independence table versus the Kids project; what would eventually need to change (renderer: none; new tooling outside the Skill; infrastructure; docs; tests); nine approval-gated next steps.
- **Records updated:** `PROJECT_STATUS.md`, `DECISIONS.md` (AP-25 to AP-36 added; G1 approved, G12 resolved, G3/G6/G9/G11 partly approved, G2 and others open, G13–G18 added), `PROGRESS_LOG.md`, `NEXT_STEPS.md`, `HANDOFF.md`.
- **Stated explicitly everywhere:** **Architecture approval is not deployment approval.**
- **Not done (boundaries):** Garage not installed, deployed or configured; no bucket, key or credential created; no secret read, copied or written; no application code, renderer, workflow, dependency or Terraform changed; no files deleted, committed or pushed; all existing artwork, test outputs, scratch files and backups preserved. The Kids project was not inspected.

## 2026-11-11 · Garage storage: second owner review recorded
- **Received:** the owner called the final proposal good, singled out the renderer fingerprint test, and said they would **approve the architecture direction but not deployment or production cutover yet**. Stated approvals: local-first rendering ("keep the existing renderer unchanged; download, render locally and upload approved outputs"); separate project buckets, credentials and storage configurations for Kids and Stickman; write-once production versions (new version prefixes and checksum manifests); a fixed working directory.
- **The message was cut off** after "Fixed working directory: Approved". It also said "there are a few important details to settle first", but those details did not arrive. **Nothing was inferred or invented to fill the gap.**
- **Recorded:** new AP-37 (write-once versions and manifests), AP-38 (fixed working directory; exact root path still to confirm), AP-39 (deployment and production cutover not approved); G7 partly approved, G17 approved in principle; the final proposal updated (approvals table, §5.3, §6.4 headings, G7 and G17 rows, status line); `PROJECT_STATUS.md`, `NEXT_STEPS.md` and `HANDOFF.md` updated.
- **No technical work done:** no installs, no buckets or keys, no code, no Terraform, no deletions; renderer unchanged.
- **Waiting on:** the rest of the owner's message, then server specifications (N1).

## 2026-11-11 · Femi removed from the concept images
- **Trigger:** the owner said they could still see Femi "all over the place" despite the character change. **Cause (my miss):** after the direction change I only added "partly superseded" banners to documents and paused the visuals, so every concept image still showed Femi.
- **Inventory (before changing anything):** 13 PNG boards and 10 SVG sources in `bible/concepts/`, plus one composite in `codex-plate-test/`, showed Femi; Femi was also mentioned in 19 repository text files.
- **Actions:** (1) **moved, not deleted,** all Femi images and SVGs to `bible/concepts/_archive-retired-femi/` with a README; (2) changed the concept generator to a **neutral placeholder figure** (light-grey mannequin colouring, slate garment, no glasses, no name) and renamed outputs (`*-character-sheet.png`, `placeholder-flat-on-codex-plate.png`, `figure-<pose>.png`); (3) regenerated every board, the thin-limb variant, the Codex-plate composite and the layered-depth spike (new run in `…\studio-work\spike-layered-depth-placeholder\`: validate passed; 180 frames, 1920×1080, 30 fps, 6.0 s, AAC; new frame sheet); (4) corrected `VISUAL_DIRECTION_COMPARISON.md`, `VISUAL_DIRECTION_RICH_ENVIRONMENTS.md` and the Codex test README, leaving only the deliberate "Femi is retired" notices; (5) verified every referenced image link resolves.
- **Viewed:** the regenerated comparison board and thin-limb sheet; the figure is a plainly neutral stand-in.
- **Still contains Femi (deliberately left, not hidden):** the retired Phase-1 cast documents (`CHARACTER_BIBLE`, `PILOT_TREATMENT`, `CONTENT_STRATEGY`, `COMEDY_WRITING_GUIDE`, `WORLD_BIBLE`, `AUDIO_DIRECTION`, `VISUAL_IDENTITY`, `ANIMATION_DIRECTION`), each with a "partly superseded" banner and awaiting the Bible rewrite; the progress records (as history); the **old spike** in `…\studio-work\spike-layered-depth\` (assets and rendered MP4, preserved as test evidence); and the pre-LF backups.
- **Not done:** the new character was not invented; the cast documents were not moved or rewritten (decision V9); nothing deleted.
- **Owner note received in the same message:** the Garage server is reachable over SSH from this workstation. **No connection was made.** Scope of any access to be agreed first (see `NEXT_STEPS.md`).

## 2026-11-11 · VPS production environment: read-only inspection and readiness design
- **Owner direction:** the Contabo VPS becomes the central production environment for both animation projects (shared Garage, monitoring, backup, security); the Windows machine is administration only; each project isolated; one coordinated infrastructure plan; neither Claude session deploys shared infrastructure independently. Recorded as AP-40 to AP-43. **Authorised:** read-only inspection and planning. **Not authorised:** installs, Garage deployment, firewall/DNS/Terraform/code changes, moving or deleting assets, changing fixed paths, heavy jobs, commits.
- **Server access (Claude Code):** two SSH sessions with key-based login, `BatchMode`, **strict host-key checking against an already-trusted key** (no new trust added), fixed read-only command lists run as one script each. No environment variables, configuration files or secrets were read; the other project's files were not inspected; nothing was written on the server. The earlier note "I have not connected" is superseded by this entry.
- **Server evidence:** Ubuntu 24.04.5, kernel 6.8, x86_64, glibc 2.39, KVM; 4 vCPU AMD EPYC; 7.8 GiB RAM, **no swap**; one 100 GB disk (96 GB `/`, 93 GB free, 4% used), no second disk; cgroup v2, systemd 255; load ≈ 0.08, CPU 99.75% idle, steal 0.00, memory ≈ 2.4% used; Docker 29.9.3 with **no containers**; **only SSH listening**; UFW active (deny incoming, 22 only); fail2ban `sshd` jail; unattended upgrades active; **sshd allows root login and password authentication**; one ordinary account; `/srv` empty; one git repository found under `/root` (the other project's). Installed: Python 3.12, git 2.43, Terraform 1.6.0, Docker, ufw, fail2ban. **Not installed:** Node, npm, FFmpeg, Codex CLI, Garage, any reverse proxy, rclone/AWS CLI, restic/borg, Prometheus/Grafana. Ubuntu repos offer Node 18.19.1 (too old) and FFmpeg 6.1.1. **No Stickman files exist on the server.**
- **Local checks supporting the design:** the lockfile includes the `linux-x64-gnu` builds of `sharp` and `@napi-rs/canvas` (matching glibc 2.39); engines `node >=20`; **no OS-specific code** in the Autopilot renderer, B3/B4 helpers, B5 route or adapters (strict search; only A6 has macOS font paths); the renderer reads `FFMPEG`/`FFPROBE` (a wrapper can limit FFmpeg without code changes) and passes **no `-threads`** option (x264 will use all cores); a per-project `render.lock` exists but nothing coordinates projects; Codex supports `login --device-auth`, `--with-api-key` (paid, not to be used) and `--with-access-token`.
- **Work product:** wrote `docs/VPS_PRODUCTION_READINESS.md` (evidence; renderer independence from Windows; generation/audio workflows; Codex on the VPS; proposed `/srv/stickman` layout with fixed working root `/srv/stickman/work/<episode-id>/`; environment names; isolation and limits; backup and recovery given one disk; resource assessment with a benchmark plan not run; security findings; integration changes; decisions P1–P15; next actions mapped to the owner's seven steps).
- **Coordination:** the Kids session (`youtube-automation`) messaged first (it will plan only and asked for this project's names); replied with Stickman's proposed names and the key server facts (no addresses or secrets); **nothing has been agreed by the Kids session yet**.
- **Records updated:** `PROJECT_STATUS.md`, `DECISIONS.md` (AP-40 to AP-43, P1–P15, G2 partly informed), `PROGRESS_LOG.md`, `NEXT_STEPS.md`, `HANDOFF.md`.
- **Not done (boundaries):** nothing installed; Garage not deployed; no firewall, DNS, Terraform or code change; no assets moved or deleted; no fixed path changed; no heavy job; nothing committed. The server's address, hostname and key details are not recorded in the repository.
- **Blockers:** off-box backup target (P4), repository transfer and version control (P1), Node ≥ 20 source (P2), DNS name (P3), swap/limits (P5), SSH hardening (P6), reconciliation with the Kids plan (P13).

## 2026-11-11 · Visual idea switched: look-development image with Codex
- **Trigger:** the owner said they still saw the "Femi sketch" and wanted the idea switched to something like the reference they shared ("just like the image I shared"), and pasted a link to a third party's social-media thumbnail. **Honest finding:** my grey placeholder was Femi's body shape and poses recoloured, so it was effectively the same sketch.
- **Boundary kept:** the look (rich, layered, warm illustrated room; simple thin-limbed character; large expressive eyes and brows) is pursued, but **not** the creator's character, composition or artwork, as the owner said earlier. The pasted link points to a third party's content; I did not download or reuse it. The reference was **not** attached to the generator.
- **Codex task (agent: Codex; tool: built-in image generation; model not exposed):** one 9:16 look-development image, scratch folder `…\scratchpad\codex-lookdev`, about 3 min 40 s, exit 0, one image; reported original preserved at `C:\Users\PC\.codex\generated_images\01a1c962-e4f0-7c01-9f1c-6c207965f6a2\exec-20dd7c60-3bf4-4988-bb87-d49e8b3d2773.png`; the scratch copy is **byte-identical** (SHA-256); 941×1672; codex reported 14,747 text tokens; **1 of the up to 4 images proposed in V6**, and the owner's message was treated as the go-ahead for this small test.
- **Inspected before use:** the image shows a mid-century living room with layered depth and a flat thin-limbed character (bald cream head, rust turtleneck, phone); no text, logos or watermarks.
- **Reorganised (moved, not deleted):** all vector boards, SVGs and the composite with the stand-in figure to `bible/concepts/technical-tests/`; doc links updated and verified; new `bible/concepts/README.md` explains the folders; new `bible/concepts/lookdev-richenv/` holds the image, the exact prompt, Codex's message and a README with provenance and limits.
- **Documents:** `VISUAL_DIRECTION_RICH_ENVIRONMENTS.md` gained §0b (look-development result and limits); `DECISIONS.md` (V6 partly exercised, V11 and P16 added, log row); `PROJECT_STATUS.md`.
- **Kids session reply (relayed):** proposes `yta`, `/srv/yta/…`, `YTA_*`, bucket `yta-media`, `yta.slice`: no collisions; agrees the shared pieces need one owner (raised as P16); suggests a shared render lock path; both sessions flagged the SSH root-login/password settings to their owner. Recorded in the VPS readiness document.
- **Not done:** no further images; character consistency and a separate empty plate are untested; the new look is a candidate, not an approved identity; the cast documents were not changed.

## 2026-11-11 · Kids session: shared-infrastructure coordination message
- **Received (not from the owner):** the Kids session reported it was assigned sole coordinator for shared infrastructure (coordination only, not deployment approval) and summarised its planning-only proposal (80/443 via Caddy, Garage on localhost, single-node replica 1, two buckets at bring-up, soft disk alerts, off-box rclone backup, a flock render lock, memory caps deferred, gated SSH-hardening procedure). It offered its documents.
- **Handling:** treated as **information, not authority**. Nothing was approved on Stickman's behalf and **its repository files were not read** (independence). Replied with Stickman-specific answers: the lock should cover `render`, `preview`, B5 `frames`/`encode` and future FFmpeg/Whisper steps but not Codex generation, `validate`, `probe`, `doctor` or transfers; 80/443-only fits (outbound-only needs); test large uploads through the proxy; the off-box backup is a prerequisite before any irreplaceable upload; `stickman-studio` is *planned, not created*; footprint estimates offered for its disk alerts.
- **Recorded:** the report and the reply in `docs/VPS_PRODUCTION_READINESS.md` §9; P16 now reads "reported by the Kids session, awaiting this owner's confirmation".
- **No server access, no installs, no changes.**
- **Follow-up from the Kids session (acknowledgement, no action requested):** it reports it incorporated Stickman's render-lock scope, the 80/443-only confirmation and the required Caddy large-upload test; recorded Stickman's non-confirmation of its coordinator assignment as an **open gap** and is telling its own owner that this owner must confirm it; and adopted, **on its side**, the rule that no irreplaceable asset goes into Garage until the off-box backup exists and a restore has been tested (this matches Stickman's approved AP-32 and my flag). `stickman-studio` remains *planned, not created*. Nothing is approved for Stickman by this message.

## 2026-11-11 · Owner confirmation: shared-infrastructure coordinator and safeguards
- **Received from the owner (in this session):** explicit confirmation that the **Kids Animation session is the sole shared-infrastructure coordinator for both projects**, authorised across both repositories; the coordinator owns Garage deployment and administration, reverse proxy and TLS, shared monitoring and alerting, independent backup and recovery, host-wide rendering coordination, and shared server security and runbooks. Stickman keeps its repository and renderer, production environment, bucket and credentials, storage integration, animation and export workflow, and testing and documentation. Stickman must coordinate and **not independently deploy or modify shared services**.
- **Five mandatory safeguards confirmed:** (1) real large multipart upload testing of Caddy before production use; (2) no irreplaceable assets in Garage until an independent off-server backup and a successful restore test are demonstrated; (3) only one heavy rendering job across both projects initially; (4) SSH hardening requires verified key-based access and a rollback procedure; (5) public web services on ports 80 and 443 with SSH separately restricted.
- **Important distinction recorded:** this establishes ownership and direction, **not blanket approval** of every infrastructure change; separate implementation gates still need the owner.
- **Recorded:** AP-44 to AP-50 in `DECISIONS.md` (P16 resolved; P4, P6, P12 and the DNS/monitoring items updated); `docs/VPS_PRODUCTION_READINESS.md` (rows added, relayed Kids update marked as owner-confirmed, P16 resolved); `PROJECT_STATUS.md`, `NEXT_STEPS.md` and `HANDOFF.md`.
- **Not done (as instructed):** no install, deployment, SSH change, firewall change or code change; no server access this turn.
- **Open for the owner:** the look-development image (V11, V8) and the next two images; the Stickman-side steps 5–7 remain behind their own gates.

## 2026-11-11 · VISUAL IDENTITY PERMANENTLY LOCKED and the two authorised technical tests
- **Owner decision:** the look-development image is **final and permanent**: simple, flat 2D characters (bold consistent black outlines, round expressive faces, large eyes and brows, thin limbs, readable body language, comedic expressions, controlled proportions, simple distinctive clothing) plus richly illustrated cinematic 2D environments (detail, strong three-quarter perspective, warm cinematic light, layered depth, believable interiors). **The pictured character is the master character** and must never change. **All future characters must share the universe but look distinct; all environments keep the same illustrated quality.** Do not redesign, replace, reinterpret, propose alternatives or silently alter. Recorded as AP-51 to AP-57.
- **Protection (done first):** SHA-256 of the canonical image computed (`36b7c97e8b9c31673d6b04dbc9c95b0a6b433dd14dee133fff9c87ad3ebff016`) and verified identical across the repo copy, Codex's untouched original and a new backup at `C:\Users\PC\Desktop\Works\_backups\canonical-visual-reference\` (with `SHA256.txt`); the repo copy and the backup were set **read-only**. `CANONICAL_REFERENCE.md` records the hash, the copies and the integrity rules.
- **Authorised test 1: character consistency (Codex call 1, one image):** the canonical image (a scratch copy) as reference; six poses and expressions on a plain grey background; about 1 min 15 s, exit 0; exactly one new output folder; original preserved (`…\01a1ca3b-5abc-7331-91ae-a4ddd41391a5\exec-099a529b-….png`), repo copy byte-identical. **Result [OBSERVED]:** strongly on-model; the worried-phone cell matches the canon very closely in a side-by-side; minor drift in outline weight (slightly thinner), skin tone (slightly lighter) and hand style (spread fingers in one cell).
- **Authorised test 2: same room without the character (Codex call 2, one image):** about 1 min 45 s, exit 0; exactly one new output folder; original preserved (`…\01a1ca3c-fc7a-7142-a67d-4c539e13c549\exec-3ea2b990-….png`), byte-identical copy; the call's log was larger (more tool activity; 28,547 tokens) but **only one image** was produced. **Result [OBSERVED + MEASURED]:** near-identical room, character and alert lines removed, bookshelf and rug continue naturally; mean absolute pixel difference per channel 2.8 to 7.1 outside the character area versus 41.0 inside it.
- **Images used so far:** 3 (look-development, character test, empty-room test). **No additional concepts, alternative designs or alternative environments were generated.**
- **Documents:** `bible/VISUAL_IDENTITY.md` rewritten as the locked specification (the Inkblock draft moved, not deleted, to `bible/_archive-superseded/`); lock blocks added to `CHARACTER_BIBLE`, `CHANNEL_BIBLE`, `ANIMATION_DIRECTION`, `CONTENT_STRATEGY`, `EPISODE_FORMATS`; `VISUAL_DIRECTION_COMPARISON` and `VISUAL_DIRECTION_RICH_ENVIRONMENTS` marked historical exploration; look-dev README rewritten with provenance and results; `DECISIONS.md` (AP-51 to AP-57; V1, V2, V3, V5, V6, V8, V11 updated; D2/D3 superseded; log row); `PROJECT_STATUS.md`, `NEXT_STEPS.md`, `HANDOFF.md`.
- **Not done:** no new designs of any kind; the cast documents were left as archive; no cut-outs or renderer tests yet (they need approval).
- **Open (technical, not visual):** depth-layer separation, resolution, new angles and other rooms, the exact asset pipeline, and the remaining unverified image-output terms.

## 2026-11-11 · Milestone close: visual-direction comparison ready for the owner## 2026-11-11 · Milestone close: visual-direction comparison ready for the owner## 2026-11-11 · Milestone close: visual-direction comparison ready for the owner## 2026-11-11 · Milestone close: visual-direction comparison ready for the owner## 2026-11-11 · Milestone close: visual-direction comparison ready for the owner## 2026-11-11 · Milestone close: visual-direction comparison ready for the owner## 2026-11-11 · Milestone close: visual-direction comparison ready for the owner
- **State:** all deliverables prepared; stopping at gate G1 (visual identity). Nothing approved on the owner's behalf.
- **Files created in this milestone:** `PROJECT_STATUS.md`, `DECISIONS.md`, `PROGRESS_LOG.md`, `NEXT_STEPS.md`, `HANDOFF.md` (repo root); `bible/VISUAL_DIRECTION_COMPARISON.md`; `bible/concepts/` (9 PNG boards, `svg/`, `src/generate-concepts.cjs`, `codex-plate-test/`).
- **Verification:** all boards and the Codex output were opened and viewed; two defects found and fixed in the concept art (proportions, shadow); the pre-existing 733 repository files were checked unchanged apart from the new files; package manifests unchanged.
- **Blockers:** owner decision V1–V5.

---

## 2026-11-11 · AP-58 to AP-60: extraction, compositing, vertical render
- **Work:** extracted six transparent poses (4 fix iterations; defect folders kept); composited pose 02 onto the empty-room plate (A, B, C) with a measured fit (scale 0.95) and comparison; built and rendered an 8 s 1080×1920 test with the unmodified renderer.
- **Tools:** Node + installed `sharp`, FFmpeg/ffprobe, renderer `autopilot.mjs` (validate, preview). Scripts: `bible/concepts/src/extract-poses.cjs`, `composite-test.cjs`, `poc-build-vertical.cjs`.
- **Files:** `bible/concepts/lookdev-richenv/extracted/`, `composite/`, `poc-vertical/` (READMEs inside); work folder `studio-work/poc-vertical-canonical/` (outside repo).
- **Verification:** all outputs viewed; source image hashes unchanged (`36b7c97e…`, `36e8cef3…`, `48ed1ca3…`); renderer validate passed, full decode pass, ffprobe 1080×1920 30 fps 240 frames; cold render 34.8 s.
- **Not done / limits:** peak memory not measured; no renderer change, installs, deletions, commits or image generations. Stopped for owner direction.

---

## 2026-11-11 · AP-61/62: production-candidate artwork (Images 4 and 5)
- **Work:** two Codex calls (one image each) with the canon, character sheet, extracted poses and approved empty room as references; candidates saved in a new folder; hashes, dimensions and measurements recorded; comparison sheets made.
- **Tools:** codex-cli (ChatGPT login), Node + sharp, ffprobe. Script: `bible/concepts/src/assess-candidates.cjs`.
- **Files:** `bible/concepts/lookdev-richenv/production-candidates/` (2 candidates, 2 prompts, 2 Codex messages, 2 comparison sheets, README).
- **Verification:** exactly one new generated-images folder per call; repo copies byte-identical to the originals; existing artwork untouched.
- **Result:** character 1024×1536 on-model (hands, skin tone flagged); environment 941×1672, near-identical to the earlier test; 2048 px target not met.
- **Blockers:** owner decision on the resolution route and candidate approval. No renderer change, installs, deletions or commits.

---

## 2026-11-11 · AP-63 to AP-66: resolution investigation and correction plan
- **Work:** inspected local upscaling tools (none AI-capable); ground-truth tests of 8 resampling methods on copies of both candidates; real ×2 copies; tiling seam test; close-up comparison sheets against the canon; web research (secondary sources) on higher-native-resolution generation; measured skin/sweater/shoe colours and wrote a non-destructive correction plan.
- **Tools:** Node + sharp, FFmpeg filter list, PowerShell hardware queries, vulkaninfo, pip list, WebSearch. Scripts: `bible/concepts/src/upscale-tests.cjs`, `upscale-compare.cjs`.
- **Files:** `bible/concepts/lookdev-richenv/production-candidates/upscale-tests/` (README, results JSON, 3 comparison sheets, 4 enlarged copies).
- **Findings:** classical resampling adds no detail (nohalo best); candidate 04 native already about 2.2× sharper than the sheet; the sheet pose 01 itself has the hook hands; no AI upscaler locally.
- **Not done:** corrections not executed (awaiting approval of the plan and the hand-target question); no AI upscaling tested. No generation, installs, paid calls, overwrites, deletions or commits.

---

## 2026-11-11 · AP-67: controlled corrections of Candidate 04
- **Work:** built a skin colour-ratio mask and applied a per-channel gain toward the canon; erased the two hook hands inside fixed zones and drew vector mitts at native resolution; iterated hands three times (patchy-skin/spiky draft, stubby v1, final v2; earlier drafts kept in labelled subfolders); wrote masks, pixel diff, report, four comparison sheets and the asset register.
- **Tools:** Node + sharp (SVG rasterisation, 4× supersample). Scripts: `bible/concepts/src/correct-candidate04.cjs`, `correct-candidate04-compare.cjs`.
- **Files:** `bible/concepts/lookdev-richenv/production-candidates/corrected/` and `bible/concepts/lookdev-richenv/ASSET_REGISTER.md`.
- **Verification:** Candidate 04 hash unchanged (`ca0148b0…`); canon, sheet and empty-room hashes unchanged; 0 changed pixels outside the masks; skin mean within 2 levels of the canon; all outputs viewed.
- **Limits:** hands are simpler than the canon (straight capsule fingers, slightly large palm); sweater and shoes deliberately unchanged. No generation, installs, downloads, paid calls, renderer changes, deletions or commits.
- **Blockers:** the owner's visual approval of the corrected candidate.

---

## 2026-11-11 · AP-68/69: hands refinement v3
- **Work:** archived v2 outputs and scripts as new labelled copies; changed only the hand geometry (palm 62×66 to 50×56; three curved rounded fingers sweeping inward/downward, mirrored for the right hand; one tuning pass to thicker, shorter fingers); regenerated masks, diff, report, comparison sheets and a combined review sheet.
- **Tools:** Node + sharp (SVG rasterisation). Script `bible/concepts/src/correct-candidate04.cjs` (v3); v2 kept as `correct-candidate04-v2-straight-fingers.cjs`.
- **Files:** `bible/concepts/lookdev-richenv/production-candidates/corrected/` (v3 outputs, `review-sheet-v3.png`, `_v2-straight-fingers/`), `ASSET_REGISTER.md` updated.
- **Verification:** skin-only file bit-identical to v2 (`438c904b…`); 0 changed pixels outside masks; Candidate 04 hash unchanged; canon, sheet, empty-room hashes unchanged; outputs viewed.
- **Limits:** fingers still simpler than the canon's; sweater and shoes untouched by instruction. No generation, downloads, installs, paid calls, renderer changes, deletions or commits.
- **Blockers:** the owner's visual approval; the owner must attach the sheets to their own review chat (cannot be uploaded from here).

---

## 2026-11-11 · AP-70: hands v3 accepted as the working candidate
- **Work:** recorded the owner's decision; asset register and the `corrected/` README updated (v3 = approved working candidate; v2 and earlier = historical evidence). No files created, changed or deleted beyond documentation.
- **Status:** Candidate 04 and v3 are not the final production master. Final visual sign-off awaits the owner viewing `review-sheet-v3.png` (they must attach it in their own chat).
- **Next (proposal only, not started):** production-ready asset workflow for the character and environment.

---

## 2026-11-11 · AP-71 / AP-72
- AP-71 DONE (documentation only): `bible/concepts/lookdev-richenv/ASSET_MANAGEMENT.md` (classification, naming for new files, provenance, approval workflow; no renames, no status changes). AP-72 DONE as a diagnostic: corrected v3 (via a new transparent cut-out) rendered 9:16 with the UNMODIFIED renderer (scripts hash identical before and after); output `C:\Users\PC\Desktop\Works\stickman-video-director\studio-work\poc-vertical-v3-ap72\output\preview.mp4` (SHA-256 758392a7a35f5c0c…), 1080x1920, 30 fps, 8.000 s, 240 frames, 4.88 MB, cold render 37.9 s, peak node 166 MB, full decode pass; AP-60 untouched. Much sharper outlines and canon skin; BUT v3 is a single neutral pose so all four shots show the same pose (pose swaps not reproduced). Evidence in `bible/concepts/lookdev-richenv/ap72-validation/`. Nothing promoted; no generation, installs, paid calls, deletions, overwrites, commits or pushes. Awaiting owner review.
- **Tools:** Node + sharp (cut-out, sheets), unmodified `autopilot.mjs` (validate, preview), ffmpeg/ffprobe. Scripts: `bible/concepts/src/ap72-cutout.cjs`, `ap72-build-vertical.cjs`, `ap72-compare.cjs`.
- **Defects fixed on the way:** cut-out first ate eye-white edges (anti-aliasing ramp counted as background); fixed with a tight pocket test and a 60 px minimum.
- **Limits:** single pose; faint flecks possible at shoulder gaps; peak memory approximate.

---

## 2026-11-11 · AP-73: pose library assessment
- AP-73 ASSESSMENT done (no extraction, correction, generation or render; no status changes): `bible/concepts/lookdev-richenv/POSE_LIBRARY_ASSESSMENT.md`. Sheet poses are about 550 px tall (v3 1270 px); skin uniform across the six (252,228,200 vs canon 252,222,180), so the v3 skin method fits all; hands differ per pose (01 hooks, 02/04 mitt-like, 03 splayed, 05/06 clasped or hidden) so hand correction must be per pose; at the 2.3x snap zoom sheet poses are enlarged 2.5x (v3 1.1x): adequate for wide shots and limited medium shots, higher-resolution poses eventually needed for close-ups. Recommended next test pose: 03 shocked (skin-only first; hand design is an owner decision). Awaiting owner approval; nothing approved or created.
- **Tools:** read-only Node + sharp sampling in the scratchpad; nothing written to the repo except the assessment document and record updates.

---

## 2026-11-11 · AP-74: pose 03 skin correction + Shot 2 render
- AP-74 DONE as TEST/EVIDENCE (awaiting owner visual review): skin-only correction of pose 03 (shocked): `bible/concepts/lookdev-richenv/ap74-pose03-test/character-01_pose-03-shocked_skin-only_test.png` (SHA-256 477f8e71…; source extract fabe6f7a… unchanged). Skin mean (252.8,226.7,196.5) to (251.8,221.7,180.0) vs canon (252,222,180); mask 17,369 px; changed inside 17,323, OUTSIDE 0; alpha and pink mouth unchanged; hands untouched. Comparison sheets and a 2 s single-shot render (AP-60 Shot 2) with the unmodified renderer: `C:\Users\PC\Desktop\Works\stickman-video-director\studio-work\poc-vertical-pose03-ap74\output\preview.mp4` (SHA-256 4610e8d7…), 1080x1920, 30 fps, 2.000 s, 802 KB, cold 10.8 s, peak node 158 MB, decode pass. Finding: colour closer to canon and expression/hands preserved, but NO sharpness gain (pose still enlarged about 2.5x at the snap zoom); v3 (AP-72) stays much sharper. Nothing promoted; no other pose touched.
- **Defects fixed on the way:** red-channel overflow (gain above 1 wrapped) and a chin seam from a too-low head cutoff.
- **Tools:** Node + sharp, unmodified `autopilot.mjs`, ffmpeg. Scripts: `ap74-pose03-skin.cjs`, `ap74-compare.cjs`, `ap74-build-shot2.cjs`, `ap74-render-compare.cjs`.

---

## 2026-11-11 · AP-75: pose 02 skin-only correction
- AP-75 DONE as TEST/EVIDENCE (awaiting owner visual review; NOT rendered): skin-only correction of pose 02 (worried, phone): `bible/concepts/lookdev-richenv/ap75-pose02-test/character-01_pose-02-worried-phone_skin-only_test.png` (SHA-256 ee921285d86a356d…; source extract 389d597b… unchanged). Skin mean (253.1,226.8,196.3) to (252.1,221.8,180.1) vs canon (252,222,180); mask 15,073 px; changed inside 15,014, OUTSIDE 0; phone, both hands, mouth, eye whites and alpha unchanged. Comparison sheets in the same folder. Owner approved pose 03 (AP-74) as a successful working test asset and said to keep its splayed hands exactly; sweater/shoe differences stay by decision. No render, no other pose, nothing promoted.
- **Tools:** Node + sharp; scripts `bible/concepts/src/ap75-pose02-skin.cjs`, `ap75-compare.cjs`.

---

## 2026-11-11 · AP-76: pose 05 skin-only correction
- AP-76 DONE as TEST/EVIDENCE (awaiting owner visual review; NOT rendered): skin-only correction of pose 05 (pleading): `bible/concepts/lookdev-richenv/ap76-pose05-test/character-01_pose-05-pleading_skin-only_test.png` (SHA-256 f2dae957eaf4b28d…; source extract 625e3fae… unchanged). Skin mean (253.1,226.9,196.7) to (252.1,221.9,179.9) vs canon (252,222,180), consistent with AP-74/AP-75; mask 17,795 px; changed inside 17,762, OUTSIDE 0; alpha, clasped hands, all near-black linework (22,451 px), eye whites, sweater and shoes unchanged. Comparison sheets in the same folder. No render, no other pose, nothing promoted. Pose 02 (AP-75) status unchanged: TEST awaiting review.
- **Tools:** Node + sharp; scripts `bible/concepts/src/ap76-pose05-skin.cjs`, `ap76-compare.cjs`.

---

## 2026-11-12 · AP-78: production toolkit
- AP-78 DONE (awaiting owner review): reusable conversation-short production toolkit in `production/` (conversation data and sequencing, message bubbles, typing indicator, hook and end card, character reaction composition, chat-stack layout with safety checks, renderer-exact storyboard preview, CLI). No renderer change (scripts byte-identical; renderer suite unchanged at 132/135 with the same 2 pre-existing environment failures and 1 skip); no new dependencies; no artwork created or edited; no image generation. 35 new tests pass. Short 001 v2 test fixture (`production/fixtures/short-001-v2.conversation.json`, hook "Four words. No warning."; SCRIPT_V2.md unchanged) compiles, validates in the renderer and renders a 54 s 1080x1920 30 fps preview (decode pass); evidence in `production/evidence/ap78/`. Technical compatibility only, not production approval.
- **Tools:** Node, the renderer's existing @napi-rs/canvas and fonts, the unmodified renderer (validate, preview, painter), ffmpeg.
- **Fixes made during the build:** the end card got a light caption band because the renderer draws B1 captions as dark text.

---

## 2026-11-12 · AP-80: pose approvals, pose 06 correction, script hook, records cleanup
- AP-80 (2026-11-12): owner APPROVED poses 02 (worried phone) and 05 (pleading) for working production use; pose 03 stays the approved working TEST asset with its splayed hands kept exactly; pose 06 (deadpan) skin-only correction AUTHORISED and DONE as a TEST awaiting visual review: `bible/concepts/lookdev-richenv/ap80-pose06-test/character-01_pose-06-deadpan_skin-only_test.png` (SHA-256 ee9dd2574411c86b…; source aeb639342c436fd7… unchanged; skin (253.1,227.4,197.4) to (252.1,222.4,180.1) vs canon (252,222,180); mask 21,398 px, changed inside 21,354, OUTSIDE 0; alpha, linework, crossed arms, eye whites, sweater and shoes unchanged). SCRIPT_V2 approved as the current working script with the hook "Four words. No warning." (19 beats and dialogue unchanged; not final production approval). Records corrected (repository facts, NEXT_STEPS archive, AP-76 script comment). AP-79 animation architecture is a proposal only: `docs/oddly-relatable/AP-79-PROPOSAL.md`. Multi-character and flexible-format requirements recorded as future architecture.
- **Tools:** Node + sharp; scripts `bible/concepts/src/ap80-pose06-skin.cjs`, `ap80-compare.cjs`. Renderer and AP-78 toolkit untouched.
- **Corrections:** AP-76 script header comment now says Pose 05 (pleading) (comment only; outputs unaffected); PROJECT_STATUS no longer claims there is no Git; NEXT_STEPS earlier-stage steps archived, not deleted.

---

## 2026-11-12 · AP-79: camera, pose transitions, multi-character foundations
- AP-79 DONE (2026-11-12; owner approved pose 06, the AP-79 architecture and scope, and the registry update): pose registry `production/characters/character-01.json` now points poses 02, 05 and 06 at their approved skin-corrected files (APPROVED_WORKING_ASSET, with file and source SHA-256 verified on load); pose 03 unchanged (approved working TEST asset). Toolkit 1.1: story layer (scenes, environments by ID), cast model (characters by ID, placement, height, z-order), scene-format strategies (text-chat implemented; phone-call, split-screen, face-to-face, solo declared, not implemented), camera (push-in, pull-back, cuts, shake, drift; zoom cap 1.5x; screen-space UI fixed), pose transitions (cut, pop, crossfade), script-to-timeline mapping of SCRIPT_V2 camera notes. Short 001 story `production/stories/short-001-v2.story.json` renders a 54 s 1080x1920 30 fps technical preview (decode pass; wide frames match AP-78 at 55.5 dB mean PSNR). Synthetic two-member cast test (Character 01 twice; no new character). 60/60 toolkit tests; renderer suite unchanged (132/135, same 2 pre-existing failures, 1 skip). Evidence `production/evidence/ap79/`. Technical evidence only; not final production approval.
- **Design notes:** the camera zooms about the focus character's head top so the face never rises into the chat zone (feet crop in medium shots, by design); keys are sampled on the frame grid so the renderer never interpolates between moving keys; crossfade is a dissolve-over (outgoing pose stays opaque underneath) after a first version let the room show through mid-fade.

---

## 2026-11-12 · AP-81: documentation reconciliation
- **Work:** records corrected to match AP-79 (commit `db1bfd3746322c6db46502935ce1add822035611`): PROJECT_STATUS (repository commit, pose row, toolkit row, final-production row, test count 60/60, operating restrictions now allow reviewed commits and pushes, owner decisions), HANDOFF (date, AP-80 marked historical, restrictions), DECISIONS (AP-80 entries annotated as superseded in part; AP-81 recorded), NEXT_STEPS (soft close-ups added before final production).
- **Numbering note:** AP-80 (pose approvals, pose 06 correction) was carried out before AP-79 (camera and transitions), so the log lists AP-80 above AP-79. Earlier entries are historical and describe the state at the time.
- **Open issue recorded:** soft character close-ups: at the approved 1.5× zoom the four Short 001 poses are enlarged about 2× on screen (02: 2.03×, 03: 1.94×, 05: 2.03×, 06: 1.96×), above the 1.7× softness threshold.
- **No changes** to code, artwork, the renderer or any approval status.

---

## 2026-11-12 · AP-82: end-to-end production engine
- AP-82 DONE (2026-11-12; owner brief titled "AP-80: End-to-End Production Engine", renumbered because AP-80 was already used): one-command production run `node production/cli.mjs produce <story> <out>` (validate and compile, then audio bed, storyboard, render with the unmodified renderer, audio export, QA, reports, hashed manifest). Short 001 produced end to end in 3 min 21 s: `render/short-001-v2.mp4` 1080x1920, 30 fps, 54.000 s, 1,620 frames, 9,038,361 bytes, byte-identical to the AP-79 preview (reproducible); audio 54.000 s, SFX only, peak -15.9 dBFS; QA 16/16 pass, 4 softness warnings. Audio pipeline accepts optional approved voice and music sources (hash and licence required; limiter; exact length); none exist yet, so Short 001 is SFX only. Episodes over 60 s need the owner's approval note before the renderer's full render (tool never writes approval). Toolkit tests 68/68; renderer suite unchanged. Technical acceptance only; publication needs the owner's review.
- **New modules:** `production/lib/produce.mjs` (orchestration), `audio.mjs` (audio plan, bed, measurement), `qa.mjs` (video, audio and input checks); CLI `produce`. Tests: `audio.test.mjs`, `produce.test.mjs`.
