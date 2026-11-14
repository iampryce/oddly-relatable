# Oddly Relatable Studio (AP-83, local MVP)

A local web dashboard around the existing production engine (`production/`). It manages episodes, starts production runs in the background, shows live progress and logs, plays the rendered MP4, and shows the storyboard, QA report, layout report and manifest. It records human review decisions separately from QA.

## Start

```bash
# from the repository root; FFMPEG/FFPROBE are needed by the production engine
export FFMPEG=/path/to/ffmpeg FFPROBE=/path/to/ffprobe
node studio/server.mjs
# then open http://127.0.0.1:4317/
```

- `npm --prefix studio start` runs the same server without Node's "SQLite is experimental" notice.
- **Options:**
  - `STUDIO_PORT` (default `4317`).
  - `STUDIO_GEN_ADAPTER` (`none` by default, or `fake`), and `STUDIO_WORKSPACE` (default `studio-work/studio`, git-ignored). The workspace holds `studio.db`, `runs/<run-id>/` and `logs/<run-id>.log`.
- **Tests:** `node --disable-warning=ExperimentalWarning --test studio/tests/*.test.mjs`.

**No dependencies.** It uses Node's built-in `node:http` and `node:sqlite` (Node ≥ 22.5; tested on Node 24) and a no-build ES-module dashboard. No React, Express, Redis or Docker: one local user, one machine, no build step to maintain.

## Architecture

| Part | File | Role |
|---|---|---|
| Server | `server.mjs`, `lib/app.mjs` | HTTP API, media serving, static dashboard; loopback only |
| Database | `lib/db.mjs` | SQLite: `episodes`, `runs`, `reviews` (append-only audit), `events` (activity) |
| Job runner | `lib/jobs.mjs` | Runs `node production/cli.mjs produce <story> <out>` as a background child process (argument array, no shell); one run at a time; one active run per episode |
| Stories | `lib/stories.mjs` | Lists and validates `production/stories/*.story.json` with the engine's own story and format code |
| Storage | `lib/storage.mjs` | Local implementation of a storage interface; the API exposes run IDs and artifact keys only, never paths |
| Dashboard | `public/` | Overview, episode library, new episode, episode detail, production runs, run detail with review |

**Production output** is exactly what `produce` writes (AP-82), one folder per run: `runs/<run-id>/{project, render, audio, storyboard, reports}`, `production-manifest.json` and `production-run.json`. The studio never overwrites a run; every run gets a new ID and folder.

## Routes

**Dashboard:**
- `#/` overview
- `#/episodes` library
- `#/episodes/new` new episode
- `#/episodes/<id>` episode detail and history
- `#/runs` production runs
- `#/runs/<run-id>` run detail: stages, log, video, QA, storyboard and frames, outputs, manifest, layout report, review

**API (JSON):**

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | ok, storage kind, whether FFMPEG/FFPROBE are set (no values) |
| GET | `/api/overview` | counts, recent runs, activity |
| GET | `/api/stories` | approved stories with validity, duration, formats, cast |
| GET / POST | `/api/episodes` | list / create (`{storyFile, id?, title?, note?}`) |
| GET | `/api/episodes/:id` | detail, run history, reviews |
| POST | `/api/episodes/:id/runs` | start a production run: **202** with the queued run immediately; **409** if one is already active |
| GET | `/api/runs`, `/api/runs/:id` | runs; detail with stages, summary, artifacts, QA, review state |
| GET | `/api/runs/:id/log?offset=N` | log tail |
| POST | `/api/runs/:id/cancel` | cancel a queued or running run (stops the renderer and ffmpeg too) |
| POST | `/api/runs/:id/reviews` | `{decision: approved-next-step \| changes-requested \| rejected, note, reviewer?}` |
| GET | `/media/runs/:id/<key>` | whitelisted artifacts only (MP4 with HTTP Range, PNG, WAV, JSON) |

## Run states and recovery

- **States:** `queued` → `running` → `produced` | `qa-failed` | `failed` | `awaiting-approval` | `interrupted` | `cancelled`. Stage progress comes from the run's `production-run.json`, which `produce` now saves as each stage starts and ends.
- **Logs:** written by the child process straight into a log file, so production continues and logs survive if the studio stops.
- **On restart:**
  - A run whose process is still alive is watched until it ends.
  - A run whose process ended is decided by its own run file. A run that never finished is marked **`interrupted`**, never successful.
  - Queued runs resume.

## Review and approval

- **Separate from QA:** a QA pass never approves anything. A finished run shows "awaiting review" until a person records a decision with a note.
- **Audit history:** decisions are kept as an append-only history per run and per episode.
- **Nothing downstream:** recording a decision does **not** call the renderer's `approve`, does not render anything further, and does not publish. Episodes over 60 s still need the owner's own approval note through `produce --approval-note` (AP-82).

## Generation foundation (AP-84B1)

A local, zero-cost foundation for future GPU-generated assets. It has no GPU, no external service and no models. Nothing is generated except labelled test fixtures.

- **Jobs:** `gen_jobs` goes `queued` → `running` → `candidate_ready` | `failed` | `cancelled`. A person then moves a ready job to `approved` or `rejected`. Generation jobs are separate from production runs. Each job records the asset type and key, description, episode, adapter, who started it, the attempt number and parent job, progress, the error, and whether it can be retried.
- **Adapters** are set by server configuration only (`STUDIO_GEN_ADAPTER`, never by API clients):
  - `none` (the default) always fails a job with "No generation worker is configured" and never produces anything.
  - `fake` produces a deterministic, striped **SYNTHETIC TEST FIXTURE / NOT ARTWORK** card. Identical requests give byte-identical files.
  - `import` (AP-84B3) imports transfer-verified candidates from a local run folder set by `STUDIO_GEN_IMPORT_DIR`. It generates nothing. See "AP-84B3 experiment tooling" below.
  - Live RunPod and ComfyUI adapters are not implemented.
- **Quarantine:** `<workspace>/quarantine/<job-id>/` only, never inside `production/`, `bible/` or `skills/`.
  - File names are whitelisted (`[a-z0-9-].png|json`).
  - Files are write-once (never overwritten) and capped at 20 MB.
  - Every file is hashed with SHA-256, and its provenance (job, adapter, request, seed, hash) is recorded in `gen_candidates`, which cannot be modified.
- **Review:** approve (a candidate must be named), reject, or request regeneration (a new job with attempt + 1). A note is always required. Decisions go to `gen_reviews`, which the database makes append-only.
- **Approval never changes registries or artwork.** It creates a **registry proposal** (`gen_registry_proposals`) with the next version for that entry; an existing registry entry counts as version 1, so a new pose 02 is proposed as `02@v2`. Approval refuses a candidate whose file changed since it was recorded. Synthetic fixtures are recorded as **not promotable**.
- **Promotion** of an approved proposal into a character registry is a separate owner decision (see "Registry promotion" below).
- **Restart:** queued jobs resume. Jobs left running are marked `failed` (interrupted, retryable), because in-process work cannot survive a restart.
- **API:** `GET /api/generation`, `GET|POST /api/generation/jobs`, `GET /api/generation/jobs/:id`, `POST /api/generation/jobs/:id/cancel`, `POST /api/generation/jobs/:id/reviews`, and `GET /media/generation/:id/<name>` (whitelisted, served as data).
- **Dashboard:** `#/generation` (jobs and a new-job form) and `#/generation/<job-id>` (candidates with previews, hash and provenance, review, history, proposals).

## Asset intelligence, reference packs and validation (AP-84B2)

All of this reads the repository and never writes to it (`lib/asset-intel.mjs`, `config/canonical-references.json`).

- **Story requirements.** For each story, the studio builds every scene's timeline with the engine's own format code. From that timeline it lists the characters, the poses each cast member uses (with use counts and scenes), and the environments. Each requirement gets one status, with a reason when it is not simply available:
  - **available:** the registry entry exists, its file exists, its SHA-256 matches, and its approval class is approved.
  - **missing:** the pose or environment is not in the registry, or its file is absent.
  - **unapproved:** the entry exists, but its approval or status is not an approved class. Approved pose classes are `APPROVED_WORKING_ASSET`, `APPROVED_WORKING_TEST_ASSET` and `APPROVED_EXTRACT`. Environments with status `APPROVED…` or `ALTERNATIVE…` count as approved.
  - **unresolved:** there is no registry for the character, the file's hash differs from the registry, a scene format is not implemented, or the scene gives a direct file path instead of an environment ID.
- **Reference packs** (`gen_reference_packs`) are immutable snapshots: database triggers refuse update and delete. Each pack is recorded for a character or a story.
  - **Items:** the canonical references in `config/canonical-references.json` (canon scene, master v3), every approved pose, and the story's approved environments. **Only approved, verified references are included.** In a story pack, any unapproved, missing or unresolved pose or environment is left out, named as a problem, and the pack is marked incomplete.
  - **Fields per item:** identifier and role, SHA-256, dimensions, approval and version, the registered feet anchor (poses), and measurements taken from the pixels: silhouette, measured feet anchor, transparency, edge statistics, and a palette (cut-outs) or colour histogram (opaque plates).
  - **Source paths stay internal.** The database keeps each item's repository-relative source so it can be re-verified. API responses never include it.
  - **Pack hash and completeness:** each pack gets a pack SHA-256 and is marked complete or incomplete, with the problems named.
  - **Older packs:** a pack recorded before measurements existed is measured when it is used for validation, but only for files that still match the recorded hash.
  - **Re-verification:** opening a pack re-hashes every file now and reports `missing` or `mismatch` (changed since recorded).
  - **Files are never copied or modified.**
  - A generation job can name a pack (`referencePackId`). The pack ID and hash then appear in each candidate's provenance, and a regenerated job keeps the same pack.
- **Candidate validation** (`gen_validations`) is append-only and advisory. It runs automatically before a job becomes `candidate_ready`, and on demand.
  - **Results:** each check reports `pass`, `warn`, `fail` or `n/a`. `n/a` means the check cannot be measured honestly with the data available; it is shown, but it does not count towards the overall result.
  - **Always:**
    - the file still matches its recorded hash;
    - file size (20 MB limit);
    - the PNG decodes;
    - dimensions (sides 256–4096 px).
  - **Character poses** (compared with the approved poses' measurements):
    - **canvas dimensions:** against `validation.expectedCanvas` in the config. The owner approved **1024×1536** for newly generated poses on 2026-11-13, matching master v3. Existing approved poses are tight crops of different sizes and are not affected. If no size is configured, the check reports `n/a`.
    - **transparency:** at least 20% fully transparent pixels. Without transparency there is no separable figure, so the figure checks below fail rather than measure the background.
    - **figure height:** the measured silhouette, with a warning below 1000 px (linked to the soft close-up concern).
    - **pose proportions:** silhouette width/height within ±25% of the approved poses' measured silhouettes, not their canvases.
    - **feet anchor:** a feet anchor can be measured (the centre of the lowest 3% of the silhouette); the figure is not cut off at the bottom; and the anchor's position across the figure is within ±0.15 of the registered anchors of the approved poses. On the approved poses, the measured anchors agree with the registered ones to within 6 px.
    - **palette consistency:** the share of figure pixels in colours used by the approved poses (4-bit bins, ±1 bin tolerance). Pass at 75% or more; fail below 40%.
    - **edge integrity:** fails if the figure is cut off at any canvas edge. Warns on isolated specks or a near-white outline (background-removal halo) beyond the approved poses' own levels.
  - **Environments:**
    - fully opaque;
    - 9:16 aspect ratio within 6%;
    - **canvas dimensions:** configured, or the size shared by every approved plate (941×1672 today);
    - **environment reference:** the registered plate with the same ID. If that plate is not approved it is flagged and not used. A new ID is compared with the approved plates as a style family.
    - **environment reference dimensions:** compared with the same-ID approved plate, otherwise `n/a`;
    - **environment palette:** colour-histogram overlap with the same-ID plate or the closest approved plate. Pass at 60% or more; fail below 25%.
    - **edge integrity:** flat borders that suggest letterboxing or padding.
  - Synthetic fixtures are flagged, and a human-approval reminder is always included, so a report never comes out as a clean "approved".
  - **Validation never changes a job's status and never approves.**
- **Calibration:** an approved pose scaled up 2.2× passes every pose check, and an approved plate re-encoded passes every environment check (both are in the tests).
- **Not measurable yet:** identity likeness, such as face and outfit matching the canon. That needs a person, or a model in a later, approved milestone.
- **Decoding note:** images are loaded from their file path, because `@napi-rs/canvas` fails to decode some valid PNGs (the lookdev plates) from an in-memory buffer.
- **API:**

  | Method | Path | Purpose |
  |---|---|---|
  | GET | `/api/generation/requirements[?story=<file>]` | requirements for all stories, or for one |
  | GET / POST | `/api/generation/reference-packs` | list packs / record a pack (`{kind: character\|story, id, note?}`) |
  | GET | `/api/generation/reference-packs/:id` | pack detail, re-verified now |
  | POST | `/api/generation/jobs/:id/validate` | run validation again (a new, appended report) |

  Job detail now includes `validations` and `referencePack`.
- **Dashboard:** the Generation section has three tabs:
  - **Jobs:** the new-job form can pick a reference pack.
  - **Story requirements:** one table per story with a "Request generation" button for any requirement that is not available. The button pre-fills the job form.
  - **Reference packs:** a list, a new-pack form, and pack detail showing the "now" verification for each item.
  - **Job page:** shows the latest validation report for each candidate, with a "Validate again" button.
- **Registry promotion:** see the next section.

## Registry promotion (owner decisions of 2026-11-13)

`lib/promotion.mjs` implements `docs/oddly-relatable/REGISTRY-PROMOTION-DESIGN.md` for **generated character poses**.

- **What promotion does:** an approved, promotable proposal becomes a **new version** of a pose in the character registry. That version is **never current**:
  - It is recorded under a top-level `promotions` map (`promotions["02"]["2"] = {…}`), not inside `poses`.
  - The production engine reads only `poses`, so no story can pick up a promoted version by accident.
  - The engine's registry validation is unaffected; every pose still needs `file`, `feet` and `figureHeight`.
- **Making a version current** needs a successful preview render with it **and** a separate owner approval. The render is a prerequisite, never an approval. This is not built yet.
- **Checks before promoting** (`GET /api/generation/proposals/:id/promotion-check`, read-only). All must pass:
  1. The proposal is still `proposed`, promotable, and not promoted before.
  2. The asset is a character pose.
  3. A person approved this candidate.
  4. The quarantined file still matches the approved hash, and it is not a synthetic fixture.
  5. Its latest validation report is for this file and is not `fail`.
  6. The job's reference pack still verifies.
  7. The registry is readable and the version number is still free.
  8. The destination file does not exist yet.
  9. The feet anchor and figure height can be measured.
- **The owner's decision** (`POST /api/generation/proposals/:id/promote`):
  - It requires `{confirm: true, note}`.
  - The approval class is fixed to `APPROVED_WORKING_TEST_ASSET` (decision 2).
  - Feet anchor and figure height default to the measured values; the owner can correct them.
- **What a promotion writes:**
  1. **Asset:** a write-once copy, with its hash checked, to `bible/concepts/lookdev-richenv/generated/<character>/pose-<key>_v<N>.png` (decision 3).
  2. **Registry edit:**
     - Only the trailing `promotions` block is inserted or replaced, as text. Every byte before it is verified unchanged, so the hand-formatted registry is not reformatted.
     - The new registry must still load in the production engine (`loadRegistry`) before it replaces the old one.
     - It is written to a temporary file and then renamed into place.
     - The registry's hash must not have changed since the checks ran.
     - A backup of the previous registry goes to `<workspace>/registry-backups/`, outside the repository.
  3. **Audit:** a `gen_promotions` row (append-only, enforced by database triggers), and the proposal is marked `promoted`.
- **If it fails:** a failure before the registry swap removes the copied asset and leaves the registry untouched. A failure after the swap keeps the asset and points to the backup.
- **Afterwards:** update `ASSET_REGISTER.md` and the project records, then commit after review. The studio does not commit.
- **Version numbers:** new proposals count promoted versions, so a second take on pose 02 after v2 is proposed as v3.
- **Not covered yet:** environments are refused, because the owner decisions cover poses only.
- **Dashboard:** on a job page, "Check promotion" on a proposal shows every check, then the form. The form shows the measured feet and figure height (editable), a required note and an explicit confirmation.
- **API:** `GET /api/generation/promotions` lists promotions. Job detail includes `promotions`.
- **Tests** run only against temporary registries and a temporary library in the git-ignored `studio-work/studio-*/`. They assert that the real registries, stories, artwork and the real `generated/` folder are untouched.

## AP-84B3 experiment tooling (D1-6, A5, cumulative limits)

Local tooling for the AP-84B3 three-candidate experiment. **Nothing here runs a GPU, creates an account or spends money, and execution (D1-7) is not authorised.** The procedure is in `docs/oddly-relatable/AP-84B3-RUNBOOK.md`.

- **Experiment lock:** `config/ap84b3-experiment.json` holds every owner-approved value once: model files with revisions and hashes, software pins, prompts, seeds, workflow settings, the provider configuration and the cost and time limits. Decimals are stored as strings.
  - **Canonical hash:** parse strictly (duplicate keys and non-integer numbers are errors), write back with keys sorted by Unicode code point and no whitespace, then SHA-256. Line endings, indentation and key order do not change it.
  - **Approval:** a lock is approved only when its canonical hash appears in `DECISIONS.md` on an approval line, written after the owner's explicit review. Every tool below refuses to run otherwise.
  - **Tests do not approve anything.** They contain no approved hash; they build a temporary decision record from the current file.
- **Import adapter** (`lib/gen-adapters.mjs`, `STUDIO_GEN_ADAPTER=import`): one job per candidate, described as `AP-84B3 candidate A` (or B, C).
  - It imports the local cut-out as a non-synthetic candidate with the full provenance from the lock and the run sheet.
  - It refuses: an unapproved lock, a run sheet that differs from the lock, an unverified transfer, a file whose hash is not recorded, a non-PNG, an oversize file, a symbolic link, a path outside the run folder, a smoke image, a repeat import, and a run folder inside the repository.
  - The default adapter is still `none`.
- **Tools** (`tools/ap84b3/`):

  | Tool | Where it runs | Purpose |
  |---|---|---|
  | `cutout.cjs` | Local | The AP-72 cut-out with input and output as arguments; full-canvas or cropped |
  | `build-pod-bundle.mjs` | Local | Builds the bundle for one prepared session: download lists, checksums, pins, the environment lock and constraints, and the sealed session allowance |
  | `pod-setup.sh` | Pod | In order: `check`, `environment` (tier 1 before installation), `software`, `requirements` (installed under PyTorch constraints, then tier 1 again and the tier 2 record), `models` (free space first, then hash-checked downloads) |
  | `verify-environment.py` | Pod | Probes Python, PyTorch, the GPU, the driver and the package inventory, and checks them against the environment lock |
  | `watchdog.sh` | Pod | Stops the Pod when the cumulative runtime reaches 2 h 50 min or the cumulative estimate reaches $4.75; reads earlier use only from the sealed `session.env`; gates new generations |
  | `collect-outputs.sh` | Pod | Copies each finished output into an outbox and lists it in a checksum manifest |
  | `verify-transfer.mjs` | Local | Verifies a pulled folder against the manifest; writes the success record last |
  | `check-workflow.mjs` | Local | Two-layer graph check of an exported ComfyUI workflow: constraints from the lock, then a freeze of the first export |
  | `pad-reference.mjs` | Local | Pads master v3 to 1536×1536 with RGB (203, 203, 203) for the SDXL baseline's reference |
  | `compare-sheet.mjs` | Local | One-scale comparison sheet for review |
  | `stop-timer.mjs` | Local | Alerts for the manual stop and the 30-minute console checkpoints, at cumulative times read from the ledger |
  | `ledger.mjs` | Local | The session ledger: `init`, `fund`, `prepare`, `close`, `status`, `recover` |
  | `preflight.mjs` | Local | Read-only report of every local check, and the list of checks that need the Pod |

- **Watchdog estimate:** GPU compute at the higher of the recorded rate and the approved cap, plus the container disk, plus every other listed resource. Each rate is normalised to dollars per hour with its billing period and conversion stated; rates with different billing periods are never added directly. It is an estimate, not a billing measurement. $5.00 and 3 hours remain absolute.
- **Watchdog authentication is unresolved until D1-7.** The script holds no credential and assumes none is injected; it calls the stop command it is given. No account-level API key may be placed in the repository or the Pod bundle. The manual stop in the web console is independent of it.
- **Transfers:** an output is safely retained only when it has been transferred and its checksum verified locally. A failed or interrupted verification leaves no success record.
- **Workflow graph check (lock amendment, 2026-11-14):**
  - **Layer 1, in the lock:** one entry per node (type and literal settings) and the connections between them. The world is closed: an extra node, a missing node, a changed setting or a rewired connection fails. Node numbers are ignored. Settings are not duplicated: each constraint points at the lock field that holds the approved value.
  - **Unlisted settings stop the run.** A literal setting the constraints do not list is not judged harmless by the tool or the operator: the result is "stop", for the owner's review.
  - **Layer 2, at execution:** the first export that passes is frozen. Later exports may differ only in the seed, and for a smoke run also the latent size and the step count. The real API export has not been seen and is not pre-approved.
  - **The freeze is mandatory and fails closed.** The frozen graph is `frozen-q.json` or `frozen-s.json` in the run folder. Only candidate A (Qwen) and candidate C (SDXL) can create it, once. Every other export, including every smoke export, is compared with it; a missing, altered or mismatched frozen graph fails the check. A smoke export never creates one.
  - **Qwen latent node:** `EmptySD3LatentImage` is an **unverified compatibility gate**, tested in the smoke run. If it is incompatible the run stops; no other node is substituted.
  - **Qwen shift:** recorded from the export, not pinned.
- **Smoke runs:** 512×768, 8 steps, seed 8403900, at most one per workflow. The lock is invalid if the smoke seed equals a candidate seed. Smoke outputs are verified into their own folder, recorded in the run sheet and can never be imported as a candidate.
- **Environment lock (A5):** `config/ap84b3-environment.json`, separate from the experiment lock. It pins the image by digest (`runpod/pytorch@sha256:e745…`), Python 3.12, PyTorch 2.13.0+cu130, torchvision 0.28.0+cu130, torchaudio 2.11.0+cu130, CUDA 13.0 and ComfyUI's requirements hash. These were read from public registry and package metadata; nothing was pulled or installed. The bundle is built only when its hash is on an `AP-84B3-ENVIRONMENT-APPROVED-SHA256=` line in `DECISIONS.md`.
- **Cumulative limits:** the $5.00 ceiling, the 3 hours and the single $10 deposit cover every Pod session of the experiment. They are enforced through the session ledger (`lib/experiment-ledger.mjs`): chained records of the deposit, each session and each freeze; a session is prepared only with what remains and only if the console balance agrees with the record; the watchdog applies the totals from the sealed `session.env`. The ledger is local and consumption is entered by a person from the console: no tool here can impose a hard billing cap.
- **Frozen-graph protection:** each freeze is recorded in the ledger with the file's hash, and the file is made read-only. Deletion, replacement, tampering or a frozen file without a ledger record stops the workflow; recovery needs the owner's approval line naming the exact ledger state. Before any import, the run sheet, the ledger, the frozen graph and the lock must agree.
- **Run folders, bundles and outputs live outside the repository** and are never committed.
- **Tests:** `tests/ap84b3.test.mjs` (39 tests) uses temporary folders, synthetic fixtures and a stand-in stop command. It needs Bash for the shell scripts and Python for the environment check. Steps of `pod-setup.sh` that stop before any network access are run locally; the steps that clone, install or download are never run. `pod-setup.sh` is checked statically and is never executed.

## Security

- **Network:** binds to `127.0.0.1` only; a `Host` header check blocks DNS rebinding.
- **Writes:** must be same-origin, `application/json`, and at most 16 kB.
- **Input validation:** IDs, story names (only `production/stories/*.story.json`), decisions and text lengths are validated.
- **Process:** child processes are started with an argument array (no shell).
- **Media:** keys are whitelisted by pattern and resolved inside the run folder (no traversal, no symlinks).
- **Nothing leaked:** no filesystem paths (absolute or repository-relative) or environment values in responses. Requirements and reference packs expose identifiers, roles, hashes, sizes, approvals, measurements and verification results only; source paths stay inside the database. Tests check every requirements, pack and validation response for paths. Only files inside the repository are ever read.
- **Read-only artwork:** asset intelligence, reference packs and validation only read and hash registry and artwork files. Tests assert that registries, stories, canon and every registered pose and environment are byte-identical after each run.
- **Browser:** a strict Content-Security-Policy; all user text is rendered as text, never HTML.

## Limitations

- Single user, no login (loopback only by design).
- One production at a time. A 54 s episode takes about 4 minutes on this machine.
- Local storage only; the storage interface is ready for S3/Garage later, but nothing is deployed.
- Playback was verified at the HTTP level (range requests, valid MP4); the owner should confirm it plays in their browser.
- `node:sqlite` prints an "experimental" notice under plain `node`. The npm script suppresses it.
