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
  - RunPod and ComfyUI adapters are future milestones.
- **Quarantine:** `<workspace>/quarantine/<job-id>/` only, never inside `production/`, `bible/` or `skills/`.
  - File names are whitelisted (`[a-z0-9-].png|json`).
  - Files are write-once (never overwritten) and capped at 20 MB.
  - Every file is hashed with SHA-256, and its provenance (job, adapter, request, seed, hash) is recorded in `gen_candidates`, which cannot be modified.
- **Review:** approve (a candidate must be named), reject, or request regeneration (a new job with attempt + 1). A note is always required. Decisions go to `gen_reviews`, which the database makes append-only.
- **Approval never changes registries or artwork.** It creates a **registry proposal** (`gen_registry_proposals`) with the next version for that entry; an existing registry entry counts as version 1, so a new pose 02 is proposed as `02@v2`. Approval refuses a candidate whose file changed since it was recorded. Synthetic fixtures are recorded as **not promotable**.
- **Not built yet:** promoting an approved proposal into `production/characters/*.json` or `environments.json` (a new version entry with feet anchor, figure height and approval class) is a later milestone.
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
- **Registry promotion** is designed in `docs/oddly-relatable/REGISTRY-PROMOTION-DESIGN.md` and is **not implemented**.

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
