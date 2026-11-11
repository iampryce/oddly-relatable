# Garage Storage Architecture — Assessment for Stickman Comedy Studio

> **UPDATE 2026-11-11 · see the FINAL ARCHITECTURE proposal:** [GARAGE_STORAGE_FINAL_ARCHITECTURE.md](GARAGE_STORAGE_FINAL_ARCHITECTURE.md). The owner approved the design principles (AP-25 to AP-36); this document remains the **evidence base**. **One correction:** §4.3 lists `approval.json` under "what not to store" as machine-bound. A later test showed the renderer's fingerprint depends on the absolute folder path, so `approval.json` is **path-bound provenance**: store it as a read-only record with each release, never as a live input, and keep a fixed working path. **Architecture approval is not deployment approval.**

**Status:** architecture-planning assessment only. **Nothing is installed, deployed, configured, created or changed.** No Garage server exists as far as this repository shows, no bucket or access key has been created, and no application code, renderer behaviour or dependency was touched.
**Date:** 2026-11-11 · **Author:** Claude Code · **Approval:** every item marked **[DECISION]** needs the owner.
**Independence:** this project stays independent of Kids Animation Studio. The Kids project was not inspected or touched.

**Evidence labels**
| Label | Meaning |
|---|---|
| **[CODE]** | Confirmed by reading this repository's code (file:line given) |
| **[MEASURED]** | Measured from real files produced in this project |
| **[GARAGE-DOCS]** | Read on Garage's official documentation today (v2.5.0 appears in its examples) |
| **[PROPOSED]** | My recommendation; not a decision |
| **[ASSUMED]** | An estimate or inference, not verified |
| **[OPEN]** | A question only the owner (or later research) can answer |

---

## 1. Summary

- **The renderer cannot read from or write to object storage, and shouldn't be made to.** It accepts local file paths only and rejects URLs **[CODE]**. Nothing in the repository uses S3, Garage, MinIO or any AWS SDK **[CODE]**.
- **Recommended pattern: local-first.** Garage is the durable system of record; rendering stays local. Pull assets to a local working folder, render with the unchanged Node and FFmpeg workflow, push results back, then download final exports for manual uploads. Do **not** stream from Garage or mount it as a drive.
- **The files are small.** Measured outputs run about 0.2 MB per second of 1080p video, so one 3-minute episode with all its exports is roughly **0.3–1 GB [ASSUMED from two small tests]**.
- **Garage's limits shape the design.** It has **no object versioning, no object lock and no bucket policies [GARAGE-DOCS]**, so protection against deletion and overwrites must come from conventions (write-once version prefixes), least-privilege keys and a separate backup, not from the storage layer.
- **Shared service, separate buckets:** one bucket and one key per project, no cross-access. Note that a shared service still shares capacity, maintenance and failure risk with the Kids project (§6).

## 2. Confirmed existing implementation (what the repository does today)

### 2.1 How the renderer reads and writes files **[CODE]**

| Rule | Evidence |
|---|---|
| Media must be a **local path**; anything that looks like a URL is rejected | `scripts/autopilot-core.mjs:31` (`Media must be a local path`) |
| Paths resolve against `project.json`'s folder, or to bundled `@b1/…` assets; every path is `realpath`-resolved | `autopilot-core.mjs:30-36` |
| The project folder **must be outside the installed Skill** | `autopilot.mjs:26` |
| Output goes to a project-local `output/` that **must be a real directory, not a symlink**, and **must contain no symlinks** | `autopilot-core.mjs:141,145` |
| **Input assets may not live inside `output/`** | `autopilot-core.mjs:151` |
| JSON is written to a temp file then **renamed** into place (atomic) | `autopilot-core.mjs:18-20` |
| Rendering takes a **lock file** created exclusively (`wx`) holding the process id | `autopilot-render.mjs:169-175` |
| Each shot is encoded to a **content-addressed clip** `output/cache/<sha256>.mp4`, written as `.partial.mp4` then renamed | `autopilot-render.mjs:195-197` |
| FFmpeg joins clips with the **concat demuxer** from a list file of basenames (`-safe 1`), then writes `film.mp4` via a partial file and rename | `autopilot-render.mjs:201-217` |
| B5 (the code-authored route) **requires local scene code** (`require`d from the project) and writes a **PNG file per video frame** to disk before encoding | `character-explainer.mjs:22, 44-45` |

### 2.2 Where each kind of file lives today

| Artefact | Location now | Written by | Needs fast local access? |
|---|---|---|---|
| Source artwork, character sprites, backgrounds (PNG/JPEG only) | Project folder or any local path; read **once at start** into memory | Us / generators | At render start only |
| Fonts | Skill's `assets/fonts/` or a project path | Bundled / us | At render start |
| Narration / audio | One local file per film (`voice.path`) | Us / TTS | Yes (FFmpeg reads it) |
| Scene files | `project.json` (declarative JSON); B5 uses a `scene/` folder of JavaScript | Us | Yes |
| Shot cache clips, `concat.txt`, `sfx.wav`, `*.partial.mp4` | `output/cache/` | Renderer | **Yes, heavy** |
| `render.lock`, `checkpoint.json`, `approval.json` | `output/` | Renderer | **Yes** (lock semantics) |
| Rendered video | `output/preview.mp4`, `output/film.mp4` | Renderer | Final copy only |
| Captions | `output/*.srt`, `output/*.vtt` | Renderer | Final copy only |
| Contact sheets | `output/*-contact-sheet.png` | Renderer | Final copy only |
| Reports | `output/*-report.json` | Renderer | Final copy only |
| Codex-generated images | `~/.codex/generated_images/` (outside any project) | Codex | Copy then use |

**Fast local access is required for:** the whole `output/` working area (cache, partial files, lock, concat list), the project folder during a render, and B5 frame sequences. The *final* deliverables (MP4, captions, sheets, reports) are small and only need to be uploaded once.

### 2.3 Existing object-storage and network use **[CODE]**
- **No** use of S3, Garage, MinIO, buckets, presigned URLs or an AWS SDK anywhere in the upstream code, tests, docs or scripts (strict word-boundary search).
- **Only network call:** `scripts/gemini-media.mjs` makes one optional request to Google's API (`fetch`), with `GEMINI_API_KEY` from the environment.
- **Dependencies:** only `@napi-rs/canvas` and `sharp` (`package.json`). There is no HTTP, S3 or SDK client.
- **Secret handling already follows environment variables:** the adapter reads keys from the environment and refuses pasted keys; `doctor` reports key *presence* but never values; `.gitignore` excludes `.env` and `.env.*` (except `.env.example`).

### 2.4 Where this project's own files are today **[CODE / MEASURED]**
- Repo: `bible/` (documents and concept boards), progress files at the root. No `.git`.
- Workspace outside the repo: `C:\Users\PC\Desktop\Works\stickman-video-director\studio-work\` (Phase 0 render, layered-depth spike, private reference copy).
- Backups: `C:\Users\PC\Desktop\Works\_backups\stickman-pre-lf-20261111` (332 MB, local only, no off-machine copy).

## 3. What Garage's official documentation confirms **[GARAGE-DOCS]**

Read today: the S3-compatibility, quick-start, deployment, features, monitoring and reverse-proxy pages. The S3-compatibility page itself warns that *"some entries will be inexact or outdated"* and its history ends in May 2022, so **re-verify against the exact Garage version before relying on any row**.

| Topic | What the docs say |
|---|---|
| Multipart upload | Implemented |
| Presigned URLs | Implemented |
| CORS, website hosting | Implemented |
| **Object versioning** | **Not supported** ("Garage does not (yet) support object versioning") |
| **Object lock / retention / legal hold** | **Missing** |
| **Bucket policies** | **Missing** |
| ACLs | Mostly missing; read-only view of the key's read/write/owner rights |
| Lifecycle | **Partial: only expiration and aborting incomplete multipart uploads** |
| Server-side encryption | **Only SSE-C** (customer-provided keys); no SSE-S3 or KMS |
| Key permissions | Per bucket: `--read`, `--write`, `--owner` (e.g. `garage bucket allow --read --write --owner <bucket> --key <key>`) |
| Defaults | S3 API on port 3900; region name `garage` |
| Replication | Configurable replica count; **3 recommended**, at least 3 nodes for the safest mode |
| Disk guidance | XFS for data (not EXT4); metadata on SSD; data on large disks |
| Metadata engine | LMDB (default, most tested) can corrupt after an unclean shutdown, so use **snapshots** (automatic snapshots exist, e.g. `metadata_auto_snapshot_interval = "6h"`); SQLite is the alternative |
| TLS | Plain HTTP by default; the docs' approach is a **reverse proxy** (nginx, Caddy, Traefik, Apache) with ACME certificates |
| Monitoring | Prometheus metrics at the admin port 3903 `/metrics`; `metrics_token` protects it; a Grafana dashboard exists |
| Data features | Deduplication of blocks; optional Zstd compression |
| Single-node | Possible (`--single-node`), but **the docs do not discuss its risks**; with `replication_factor = 1` there is **no redundancy** |

**Not confirmed in this pass [OPEN, check in the CLI/admin reference for the chosen version]:** per-bucket **quotas**; whether a key can be **forbidden from creating buckets**; whether a **separate delete permission** exists (only read/write/owner are documented, so assume **write includes delete**); checksum support; scrub/repair behaviour; encryption at rest beyond SSE-C.

## 4. Proposed architecture **[PROPOSED]**

### 4.1 Topology and isolation
```
                 one shared Garage service (S3-compatible, HTTPS via reverse proxy)
                      │                                   │
          bucket: stickman-studio                bucket: <the Kids project's own bucket>
          key:    stickman-rw                    key:    <the Kids project's own key>
          (read+write on this bucket only)       (read+write on that bucket only)
```
- **Dedicated bucket** for this project. `stickman-studio` is a **placeholder name**, not created.
- **Dedicated access key** with `read` + `write` on that bucket **only**. No `owner`, and (if the version supports it) **no permission to create buckets**. An admin key, kept separate and not used by agents or scripts, holds `owner`.
- **No cross-bucket access** in either direction; the Kids project's bucket is never named in this repository's configuration.
- **Quotas:** set a size/object quota on each bucket if the chosen version supports it **[OPEN]**, so one project cannot fill the shared disks.
- **Independence caveat:** a shared service still shares **disk capacity, network, maintenance windows and outages** with the Kids project, even though data and credentials are separate. See decision G9.

### 4.2 How tools would connect
Garage speaks the S3 protocol, so a client points at its endpoint instead of AWS:
- **Endpoint:** the service's HTTPS URL; **region:** `garage` (default); **addressing:** path-style (vhost-style needs a configured root domain).
- **Configuration by environment variables**, never files in the repository. Suggested names (not created anywhere): `GARAGE_ENDPOINT`, `GARAGE_REGION`, `GARAGE_BUCKET`, `GARAGE_ACCESS_KEY_ID`, `GARAGE_SECRET_ACCESS_KEY`. Many S3 tools also honour the standard `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` names.
- **Secrets:** `.env` files are already git-ignored **[CODE]**, but a plain `.env` on a Windows workstation is weak storage. Better options (decision G4): the OS credential store, a password-manager CLI that injects variables at run time, or a per-user profile file outside the repository. Agents must **never print or log** the secret, and `doctor`-style checks should report presence only.
- **Org standard:** infrastructure for the Garage host (VM or container, disks, DNS, reverse proxy, certificates) should be defined with **Terraform** where applicable. Whether a maintained Terraform provider exists for Garage's own bucket/key objects is **unverified**; bucket and key creation can use Garage's own CLI/admin API.

### 4.3 Object layout (logical; nothing created)
Because Garage has **no versioning**, use **write-once, versioned prefixes**: never overwrite an object; publish a new `vNNN/` and a manifest.

```
stickman-studio/                              (bucket)
  shared/
    fonts/  licenses/  export-presets/  overlay-guides/  templates/
  characters/<character-id>/v001/             source SVG, model sheet, puppet-kit PNGs, manifest.json
  environments/<set-id>/v001/                 superframe plates, back/mid/front layers, masks, tint overlays
  props/<prop-id>/v001/
  episodes/<episode-id>/
    brief/  script/  storyboard/
    scene-graph/v001/                         platform-neutral scene description + project.json files
    audio/stems/v001/                         per-character dialogue, SFX, music, ambience
    audio/mix/v001/                           master mixes
    captions/v001/                            transcript, per-ratio layouts, SRT/VTT
    renders/master-169/v001/                  master videos, contact sheets, reports, checkpoint
    renders/master-916/v001/
    exports/
      youtube-shorts/v001/   youtube-long/v001/
      tiktok/v001/           facebook-reels/v001/   facebook-video/v001/
    thumbnails/v001/   covers/v001/
    publish/<platform>.json                   metadata per platform (see MULTI_PLATFORM_ARCHITECTURE.md)
    rights-ledger/
  archive/<episode-id>/<release-id>/          frozen copies of what was actually published
```
**Naming rules:** lowercase ASCII, no spaces, sortable IDs (`e001`, `v001`). **Case matters in object keys but not on Windows**, so two keys differing only by case would collide when pulled; the lowercase-only rule prevents that.
**Each `vNNN/` carries `manifest.json`** listing every file with its SHA-256 and size. Garage has no object tagging, so metadata lives in manifests.
**What not to store:** `render.lock`, `*.partial.mp4`, `*.tmp`, `approval.json` (it is machine-bound), and (by default) `output/cache/`, which is regenerable and roughly doubles a render's size **[MEASURED]**. Cache can be archived on request.

## 5. Rendering and publishing workflow: three options assessed

| Option | How | Verdict | Why |
|---|---|---|---|
| **A. Stream from Garage** | Renderer reads and writes the bucket directly | ❌ **Not feasible without renderer changes** | The renderer **rejects URLs** (`autopilot-core.mjs:31`) and needs a local `output/` with locks, renames and no symlinks |
| **B. Mount Garage as a drive** (FUSE / network drive via an S3 mount tool) | Present the bucket as a folder | ❌ **Not recommended** | Atomic rename, exclusive lock files and heavy small-file cache writes are exactly what object-store mounts handle poorly; a network outage would break a render mid-run; on Windows it needs a FUSE layer **[ASSUMED, not tested]** |
| **C. Local-first sync (recommended)** | Pull → render locally → push → retrieve | ✅ **Recommended** | Uses the renderer exactly as it is; Garage is never on the render path; the data volumes are small |

### Recommended flow (C) **[PROPOSED]**
1. **Pull** the needed assets by manifest into a local working folder **outside the Skill and outside the repo**, e.g. `studio-work\<episode-id>\`. Verify every SHA-256.
2. **Render locally** with the existing `validate`, `preview`, `approve` and `render` commands, unchanged. The owner's approval step stays a human decision.
3. **Post-process outside the renderer** (external caption burn-in, platform exports; see `bible/MULTI_PLATFORM_ARCHITECTURE.md`).
4. **Push** finished outputs to **new** versioned prefixes with a manifest; never overwrite. Record the object keys in the episode's records.
5. **Retrieve** the final platform exports into a local `to-upload` folder for **manual** upload to YouTube, TikTok and Facebook (no publishing automation).
6. **Archive** what was published under `archive/`.

**Performance and compatibility reasoning**
- Source assets are read **once at render start** into memory **[CODE]**, so there is no sustained read stream to serve from the network.
- The write-heavy parts (cache clips, partial files, lock, concat list) stay on the local disk.
- Measured final deliverables are small (§8), so uploads and downloads should be quick on a home or office network **[ASSUMED]**.

**If Garage is unavailable**
- **Rendering does not depend on Garage**, because it only touches local folders.
- Work continues from the local working copy; completed outputs queue for upload and are pushed when Garage returns. The local copy stays authoritative **until the push has been verified**.
- Do not delete local working folders until upload and checksum verification succeed.

## 6. Reliability and security **[PROPOSED unless marked]**

| Area | Recommendation |
|---|---|
| **Redundancy** | Garage's docs recommend **3 replicas on at least 3 nodes**. A single node (`replication_factor = 1`) has **no redundancy** **[GARAGE-DOCS]**. Which applies depends on the host plan (G2). |
| **Backup and recovery** | Replication is not a backup. Keep a **second copy** of the bucket on a different system (periodic one-way copy with a checksum-comparing tool), take Garage's **metadata snapshots** **[GARAGE-DOCS]**, and **test a restore** before trusting it. The current local backup of the repository is a single copy on one machine. |
| **TLS and access** | Put Garage behind a **reverse proxy with ACME certificates** **[GARAGE-DOCS]**. Do not expose Garage's internal RPC or admin ports publicly. Protect the metrics endpoint with `metrics_token` **[GARAGE-DOCS]**. Restrict who can reach the endpoint (VPN or firewall) **[OPEN]**. Check the proxy's request-size and timeout limits for large uploads (the docs are silent on this). |
| **Credentials** | One key per project, least privilege (§4.1), rotated on a schedule and on any suspected exposure, never in the repository, logs or chat. |
| **Capacity and monitoring** | Prometheus metrics (port 3903) with disk-usage alerts; bucket quotas if supported; review growth against the estimates in §8. |
| **Accidental deletion and overwrite** | **Garage cannot enforce this:** no versioning, no object lock, no bucket policy **[GARAGE-DOCS]**, and the documented permissions are read/write/owner, so **write likely includes delete** **[OPEN]**. Mitigate with write-once `vNNN/` prefixes, manifests with checksums, a **separate backup**, a **read-only key** for retrieval and listing tasks, and a rule that automation never deletes. Do not enable lifecycle expiration. |
| **Encryption at rest** | Garage offers **SSE-C only** **[GARAGE-DOCS]**. Alternatives: disk-level encryption on the host, or none if the host is physically secure and the content is non-sensitive (decision G8). |
| **Local working copies** | Keep §5's local-first rule; do not make Garage a single point of failure for production. |
| **Shared-service independence** | Separate buckets and keys do not isolate **capacity, maintenance, outages or admin mistakes**. Agree quotas, maintenance notices and a rule that Stickman agents never touch the other project's bucket (G9). |

## 7. Integration compatibility

| Tool | Needs local filesystem? | Can use an S3-compatible endpoint? | Notes |
|---|---|---|---|
| **Renderer** (`autopilot.mjs`, `character-explainer.mjs`) | **Yes, always** | No | Local paths only; no change proposed |
| **FFmpeg / FFprobe** | Yes, as invoked by the renderer | Can read HTTP URLs in general, but the renderer passes local files | Not used with remote inputs |
| **`sharp`, `@napi-rs/canvas`** | Yes (via the renderer) | No | |
| **Python / Whisper helper** | Yes | No | Not installed |
| **`gemini-media.mjs`** | Local files | n/a (calls Google, not S3) | Unrelated to storage |
| **Codex CLI** | Local paths in its sandbox; outputs land in `~/.codex/generated_images` | No | Copy outputs to the working folder, then push |
| **AWS CLI** | No | **Yes**, with `--endpoint-url` | **Would be a new install** (approval) |
| **rclone** | No | **Yes** (generic S3 provider) | **New install**; its mount mode is **not recommended** here |
| **`curl --aws-sigv4`** | No | Yes, manual signing | No install, but laborious |
| **A Node S3 SDK** | No | Yes | **Adds a dependency**; avoid unless approved |
| **Garage's own CLI/admin API** | n/a | n/a | Server administration only |

I have **not tested** any of these against a Garage server. The "can use an endpoint" column reflects the S3 standard and Garage's documented compatibility, not a run.

## 8. Storage estimates from actual repository evidence

### Measured
| Item | Size | Notes |
|---|---|---|
| Phase 0 B1 film (16.4 s, 1280×720) | 704,145 B | about **43 KB/s** (≈343 kbps) |
| Layered spike preview (6 s, 1920×1080) | 1,162,725 B | about **194 KB/s** (≈1.55 Mbps) |
| Shot cache for the spike | 1,158,144 B (3 clips) | **≈ the final video**, so keeping cache doubles a render |
| Spike source PNGs (10 files) | 736 KB total | plates 85–220 KB each at 1920×1080; sprites 32–46 KB each |
| Codex-generated plate (1672×941 painted) | 1,564,970 B | about **7× a flat vector plate of similar size** |
| Contact sheet / report / SRT+VTT | 95–225 KB / 3.5 KB / under 1 KB | |
| Repository total today | 337.8 MB (mostly upstream demo videos) | **Not** part of the Garage plan; stays in the repo/local |
| Local backup | 332 MB | single copy, local |

### Estimated for production **[ASSUMED, extrapolated from two small tests]**
| Item | Estimate |
|---|---|
| 3-minute 1080p video at the spike's rate | ≈ **35 MB**; allow up to ≈ **100 MB** for busier scenes |
| One 3-min episode: two masters, three 60-s cut-downs, about 14 platform exports, audio stems (~6 mono 48 kHz files, 35–50 MB), sources and reports, **without** cache | ≈ **0.3–0.7 GB** |
| Same, **with** archived render cache | ≈ **0.35–0.9 GB** |
| 8-minute episode | roughly 2.7× the above |
| Asset libraries (characters, environments, props) | tens of MB if vector/flat; **up to about 1 GB** if many high-resolution AI plates (a 3840×2160 painted plate may be ≈ 8 MB) |
| Growth at one episode every two weeks | ≈ **8–25 GB/year**; weekly ≈ **16–50 GB/year** |
| With 3-way replication, or a second backup copy | multiply by 2–3 |

**Conclusion:** capacity is modest (well under 1 TB for years). **Treat these as order-of-magnitude figures** and re-measure on the proof-of-concept render and a first real episode.

## 9. Risks

| Risk | Mitigation |
|---|---|
| No versioning or object lock; write likely includes delete | Write-once prefixes, manifests, backup, read-only retrieval key |
| Single-node Garage = no redundancy | Decide the host plan (G2); keep local working copies and a second backup |
| Shared service couples this project to the Kids project's capacity and outages | Quotas, separate keys, agreed maintenance, local-first workflow |
| Secrets on a workstation | Credential store or injected variables; never in repo, logs or chat |
| Mounting or streaming tempts later "optimisations" | Keep the rule: render local, sync around it |
| Windows vs object-key case sensitivity | Lowercase-only naming |
| Upload timeouts through a reverse proxy | Configure and test proxy limits (docs are silent) |
| Documentation drift (S3-compat page is dated 2022) | Re-verify against the deployed version |
| Quota or key-permission features unconfirmed | Check the CLI reference for the chosen version before relying on them |

## 10. Open questions **[OPEN]**
1. Is a Garage server already running, or to be built? Where (host, OS, disks, network), how many nodes, who administers it?
2. Which Garage version, and does it support per-bucket quotas, a no-create-bucket key flag and a separate delete permission?
3. How is the Windows workstation to hold the credentials safely?
4. What second backup location exists?
5. Should the render cache and `approval.json` ever be stored?
6. Do exports need shareable links (presigned URLs), or is access strictly through keys?
7. Should the two projects' admins and maintenance windows be coordinated, and by whom?

## 11. Decisions requiring approval **[DECISION]**

| ID | Decision | Recommendation |
|---|---|---|
| **G1** | Adopt the **local-first** workflow (pull, render locally, push, retrieve); **no streaming and no mounting** | Approve |
| **G2** | Garage host plan: where it runs, node count, replication, administrator | Owner to specify; prefer 3 replicas if hardware allows, otherwise add a strong second backup |
| **G3** | Bucket and credential policy: bucket `stickman-studio` (placeholder), one read+write key, a separate admin key, no cross-project access, quotas | Approve in principle |
| **G4** | Secret-management method on the workstation | OS credential store or password-manager injection; not a plain `.env` |
| **G5** | Client tool for transfers: AWS CLI, rclone or none yet (each is a new install, which needs approval) | Decide when Garage exists; none for now |
| **G6** | Backup strategy: second location, snapshot schedule, restore test | Approve a plan before storing anything irreplaceable |
| **G7** | Retention and archive rules (write-once versions, what to keep, cache policy) | Approve the §4.3 layout and rules |
| **G8** | Encryption at rest: SSE-C, disk encryption or none | Disk encryption if the host is shared or exposed |
| **G9** | Independence safeguards with the Kids project (quotas, maintenance notice, no cross-access) | Approve |
| **G10** | Terraform scope for provisioning the Garage host (org standard) | Approve; verify whether a Garage provider exists |
| **G11** | What is synced: assets only, or also episode sources, renders and exports | Everything except cache, locks and approvals |
| **G12** | Whether presigned (shareable) links are allowed | Off by default |

## 12. Not done, by instruction
Garage was not installed, deployed or configured; no bucket or access key was created; no secret was read, copied or written; no application code, renderer workflow or dependency was changed; nothing was committed or pushed; all existing assets, backups and scratch files were preserved.

## Sources
Garage official documentation (read 2026-11-11; examples show v2.5.0):
- S3 compatibility: <https://garagehq.deuxfleurs.fr/documentation/reference-manual/s3-compatibility/>
- Quick start: <https://garagehq.deuxfleurs.fr/documentation/quick-start/>
- Deployment on a cluster: <https://garagehq.deuxfleurs.fr/documentation/cookbook/real-world/>
- Features: <https://garagehq.deuxfleurs.fr/documentation/reference-manual/features/>
- Monitoring: <https://garagehq.deuxfleurs.fr/documentation/cookbook/monitoring/>
- Reverse proxy: <https://garagehq.deuxfleurs.fr/documentation/cookbook/reverse-proxy/>

Repository evidence: `skills/directing-stickman-videos/scripts/autopilot-core.mjs`, `autopilot-render.mjs`, `autopilot.mjs`, `character-explainer.mjs`, `gemini-media.mjs`, `package.json`, `.gitignore`; measured files under `C:\Users\PC\Desktop\Works\stickman-video-director\studio-work\` and `bible/concepts/`.
