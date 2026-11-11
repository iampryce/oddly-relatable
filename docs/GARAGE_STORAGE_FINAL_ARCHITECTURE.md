# Garage Storage — Final Architecture Proposal (Stickman Comedy Studio)

> ## ⚠️ Architecture approval is **not** deployment approval
> The owner has approved the **design principles** in §2. That is a decision about *how storage should work*. It does **not** authorise installing or configuring Garage, creating buckets or credentials, installing any client or dependency, writing synchronisation code, changing Terraform, uploading any asset, or starting backups. **Each of those is a separate approval** (§12). As of this document **nothing has been built, installed, created or changed.**

**Status:** final architecture proposal; **second owner review recorded 2026-11-11 (architecture direction approved; deployment and production cutover not approved; the owner's message was cut off, so further details are awaited)**. Originally: final architecture proposal for owner review · **Date:** 2026-11-11 · **Author:** Claude Code
**Builds on:** [GARAGE_STORAGE_ARCHITECTURE.md](GARAGE_STORAGE_ARCHITECTURE.md) (the evidence-based assessment; kept as the evidence base).
**Independence:** this project is independent of Kids Animation Studio. That project was not inspected or touched.

| Marker | Meaning |
|---|---|
| ✅ **APPROVED** | An architectural decision the owner has approved |
| 🟡 **PROPOSED** | My recommendation, awaiting approval |
| ⏳ **OPEN** | Deliberately unresolved, usually until server specifications are known |
| **[CODE] [MEASURED] [GARAGE-DOCS] [ASSUMED]** | Evidence labels, as in the assessment |

---

## 1. Summary

Garage is a **shared, self-hosted, S3-compatible object store** used as the **durable home for approved assets and finished outputs**. All active work stays on the local disk. The renderer is **not changed**. A small set of **future, separately approved** tools (outside the renderer) will move files between the local working folder and the project's own private Garage bucket, verifying checksums on every transfer. Backups are held **outside the Garage server**. The Kids Animation project shares only the Garage *service*; its bucket, keys, folders, configuration names and backups are completely separate.

## 2. Approved architectural decisions ✅

Approved by the owner on 2026-11-11 and recorded as **AP-25 to AP-36** in `DECISIONS.md`.

| # | Approved principle | ID | Meaning in practice |
|---|---|---|---|
| 1 | **Local-first rendering**; assets are downloaded to local working storage before rendering | AP-25 | Rendering never reads from or writes to Garage |
| 2 | Garage is the **shared self-hosted S3-compatible** object-storage service | AP-26 | Replaces the earlier "considering Garage vs AWS S3" |
| 3 | This project has its **own dedicated bucket and credentials** | AP-27 | Specific names and permissions are proposed in §4 |
| 4 | The Kids Animation project has a **completely separate bucket and credentials** | AP-28 | See §9 |
| 5 | **Active rendering, cache, lock and temporary files stay local** | AP-29 | See §6.2 |
| 6 | **Upload approved assets and completed production outputs** to Garage | AP-30 | Drafts and work-in-progress stay local |
| 7 | **Private by default**; no public links without explicit approval | AP-31 | No public buckets, no shareable or presigned links unless separately approved |
| 8 | **Independent backups outside the Garage server** | AP-32 | Design in §7; target and schedule remain open |
| 9 | **TLS and secure credential handling** | AP-33 | Rules in §8; storage method remains open |
| 10 | **Selective synchronisation**, not the whole working directory | AP-34 | Include/exclude rules in §6.3 |
| 11 | **No direct streaming from, and no mounting of, Garage as a filesystem** | AP-35 | The renderer rejects URLs and needs a real local `output/` **[CODE]** |
| 12 | **No publishing automation** at this stage | AP-36 | Reinforces AP-24; exports are retrieved and uploaded to platforms manually |
| 13 | **Write-once production versions**: new version prefixes and checksum manifests | AP-37 | Added at the owner's second review; see §5.3 |
| 14 | **Fixed working directory**: an approved project stays at one absolute path | AP-38 | Added at the owner's second review; see §6.4 |
| 15 | **Deployment and production cutover are not approved** | AP-39 | The owner approved the architecture direction only; details are to be settled first |

## 3. Decisions deliberately left open ⏳

| ID | Decision | Why it is open |
|---|---|---|
| **G2** | **Garage deployment topology**: host(s), operating system, disks, network, node count, replication factor, who administers it, whether a server already exists | **Waiting for server specifications.** Nothing below assumes a topology |
| **G4** | Secret-storage method on the workstation | Needs the owner's choice (§8) |
| **G5** | Transfer client (AWS CLI, rclone, or small project scripts) | Each option is a new install or new code; needs approval |
| **G6** | Backup target, schedule, retention, recovery objectives | Depends on the available hardware and the owner's tolerance |
| **G7** | Retention rules in detail (write-once versions and manifests are ✅ approved, AP-37) | Proposed in §5.5, awaiting approval |
| **G8** | Encryption at rest (Garage offers SSE-C only; disk encryption is the alternative) | Depends on the host plan |
| **G10** | Terraform scope for the Garage host | Org standard is Terraform; depends on G2 |
| **G13** | One bucket, or an additional write-once **archive bucket** (§4.4) | New proposal |
| **G14** | Final key set and bucket name (§4.2) | New proposal |
| **G15** | The exact selective-sync include/exclude list (§6.3) | Principle approved; list proposed |
| **G16** | Export file-naming convention (§5.4) | New proposal |
| **G17** | The **exact value** of the fixed absolute working root (§6.4). The principle is ✅ approved (AP-38) | Confirm the path |
| **G18** | How the repository itself is backed up (it has no `.git`) | New |

## 4. Proposed bucket and access model 🟡

### 4.1 Bucket
- **Name (placeholder, not created):** `stickman-studio`.
- **One bucket per project.** In Garage, **the bucket is the unit of isolation**: access is granted to a key per bucket as `read`, `write` and/or `owner`, and Garage has **no bucket policies**, so permissions **cannot be restricted by prefix** **[GARAGE-DOCS]**. Everything inside the bucket is therefore equally reachable by any key that has access to it, which is why the layout (§5) relies on conventions and a separate backup, not on prefix permissions.
- **Private only:** no public website mode, no anonymous access, no presigned/shareable links (AP-31).
- **Quota:** set a size quota sized from the host's capacity **if the chosen version supports it** **[OPEN: unconfirmed in the docs read]**. See the estimates in the assessment (§8): tens of GB per year.
- **Incomplete-upload cleanup:** enable only the lifecycle action that Garage supports for this (`AbortIncompleteMultipartUpload`) **[GARAGE-DOCS]**. **Do not enable expiration rules** that delete real objects.

### 4.2 Keys (roles; none created) 🟡
| Role | Placeholder name | Permission on `stickman-studio` | Used by | Notes |
|---|---|---|---|---|
| Working | `stickman-rw` | `read` + `write` | The future pull/push tools on the workstation | No `owner`. If the version allows, **forbid creating buckets** **[OPEN]** |
| Read-only | `stickman-ro` | `read` | Retrieval of exports for manual platform uploads; listing; verification | Used whenever no write is needed |
| Backup | `stickman-backup-ro` | `read` | The independent backup job on a **different system** | Read-only so a compromised backup host cannot alter the source |
| Admin | `stickman-admin` | `owner` | A human administrator only | **Not stored on the workstation by default, never used by scripts or agents** |

**Important limit [OPEN]:** Garage documents only read/write/owner; **`write` very likely includes delete**. So the working key *could* delete objects. Mitigations: the future tools **never call delete** (they copy only, never "sync with delete"); a separate **backup** exists; the **read-only** key is the default for anything that doesn't upload; and an optional **archive bucket** (§4.4).

### 4.3 What to confirm on a **test** instance before relying on it
Bucket quotas · a no-create-bucket key flag · whether a key can see or list buckets it has no access to · whether `write` includes delete · checksum behaviour on upload · behaviour of large multipart uploads through the reverse proxy.

### 4.4 Optional archive bucket (G13) 🟡
Because permissions are per bucket, the only **native** way to make published releases hard to change is a **second bucket** (e.g. `stickman-studio-archive`) whose write key is used **only** at release time and otherwise kept offline, while day-to-day work uses the main bucket. **Trade-off:** more keys and more procedure for stronger protection. **Recommendation:** start with a **single bucket** plus an independent backup; add the archive bucket if published masters become hard to replace.

## 5. Proposed object-prefix structure 🟡

### 5.1 Layout (logical; nothing created)
```
stickman-studio/
  shared/
    fonts/            licences/            export-presets/
    overlay-guides/   templates/           caption-styles/
  characters/<character-id>/v001/          source vectors, model sheet, puppet-kit PNGs, manifest.json
  environments/<set-id>/v001/              superframe plates, depth layers, masks, tint overlays, manifest.json
  props/<prop-id>/v001/                    manifest.json
  episodes/<episode-id>/
    brief/            script/               storyboard/
    scene-graph/v001/                       platform-neutral scene description + project files
    audio/
      stems/v001/                           per-character dialogue, SFX, music, ambience
      mix/v001/                             master mixes
    captions/v001/                          transcript, per-ratio layouts, SRT/VTT
    masters/                                PRODUCTION MASTERS
      master-916/v001/                      video, contact sheet, render report, approval record
      master-169/v001/
    exports/                                PLATFORM EXPORTS (re-encoded or reframed deliverables)
      youtube-shorts/v001/
      youtube-long/v001/
      tiktok/v001/
      facebook-reels/v001/
      facebook-video/v001/
    thumbnails/v001/   covers/v001/         16:9 thumbnails, 9:16 covers
    publish/                                per-platform metadata (youtube-shorts.json, tiktok.json, ...)
    rights-ledger/                          music, SFX, font, voice licences and proof
    releases/<release-id>/manifest.json     one manifest per release (see §5.3)
  archive/<episode-id>/<release-id>/        frozen copy of what was actually published (optional, G13)
```
- **Platform folders mirror the multi-platform direction** (`bible/MULTI_PLATFORM_ARCHITECTURE.md`): YouTube Shorts and long-form, TikTok, Facebook Reels and video (Facebook scope is still decision M14).
- **No publishing automation:** these folders hold files for manual upload; a `publish/` JSON records what was prepared, not that anything was posted automatically.

### 5.2 Naming rules
**Lowercase ASCII only, no spaces**, sortable IDs (`e001`, `v001`). This avoids collisions when a Windows folder (case-insensitive) is rebuilt from case-sensitive object keys.

### 5.3 Versioning and releases (Garage has no versioning) ✅ approved: AP-37
- **Write-once:** a `vNNN/` prefix is **never modified** after upload. A change is a new `vNNN+1/`.
- **Every `vNNN/` carries a `manifest.json`** listing each file's size and SHA-256. Garage has no object tagging, so metadata lives in manifests.
- A **release** groups the exact versions that make up one publishable episode state:
```json
{
  "schema": "stickman-release-manifest-v1",
  "episode": "e001",
  "release": "r001",
  "created": "<ISO-8601 timestamp>",
  "renderer": {"skill": "directing-stickman-videos", "node": "<version>", "ffmpeg": "<version>"},
  "render_fingerprint": "<value from the render report>",
  "approval_record": "masters/master-169/v001/approval.json",
  "components": {"scene-graph": "v001", "audio-mix": "v001", "captions": "v001", "master-169": "v001"},
  "files": [{"key": "<object key>", "bytes": 0, "sha256": "<hash>"}]
}
```
*(Illustrative only. No values are real and no such file exists.)*

### 5.4 Export file naming (G16) 🟡
`<episode-id>_<platform>_<ratio>_<release-id>.<ext>`, for example `e001_youtube-shorts_9x16_r001.mp4`, with matching `.srt` and `.vtt` and `_thumb` / `_cover` images.

### 5.5 Retention (G7) 🟡
- **Keep every release and every `vNNN/`** (storage is cheap; the estimate is tens of GB per year).
- **No automated deletion of any kind.** Removing anything from Garage is a deliberate, owner-approved human action.
- **Never upload** the render cache or any other regenerable intermediate (§6.2); they can be rebuilt from the uploaded sources.

## 6. Local-first workflow 🟡 (design approved: AP-25, 29, 30, 34, 35)

### 6.1 Flow
```
   Garage (private, TLS)                     local working root (fixed path)
 ┌──────────────────────┐   1 pull (read-only key, selective, checksum-verified)  ┌─────────────────────────┐
 │ approved assets      │ ─────────────────────────────────────────────────────▶ │ assets/  scene/  audio/ │
 │ episode sources      │                                                         │ project.json            │
 │                      │                                                         │ 2 render (unchanged)    │
 │                      │                                                         │ output/  cache  locks   │
 │                      │ ◀──────────────────────────────────────────────────────  │ 3 package + manifest    │
 │ masters, exports,    │   4 push (write key, new vNNN only, verify after upload)│ 5 owner approval (human)│
 │ captions, reports    │                                                         └─────────────────────────┘
 └──────────┬───────────┘
            │ 6 retrieve exports (read-only key) → local to-upload/<platform>/ → MANUAL platform upload
            └──── backup job on a different system (read-only key), see §7
```
1. **Pull** only what the episode needs, by manifest, using the read-only key. **Verify every SHA-256**; stop on any mismatch.
2. **Render locally** with the existing `validate`, `preview`, `approve` and `render` commands, **unchanged**. The owner's approval stays a human decision.
3. **Post-process outside the renderer** (external caption burn-in and platform exports; see the multi-platform document).
4. **Package** a release manifest locally, then **push** to **new** `vNNN/` prefixes with the write key. **Never overwrite.** Verify after upload by comparing sizes and re-downloading and hashing the masters.
5. Record the object keys in the episode's local records and mark the release "uploaded and verified".
6. **Retrieve** the final exports with the read-only key into a local `to-upload/<platform>/` folder for **manual** platform upload. Record manually that it was posted.

### 6.2 What stays local, always (AP-29) ✅
`output/` while a render is active, including `output/cache/**` · `render.lock` · `*.partial.mp4` · `*.tmp` · `concat.txt` and `sfx.wav` · in-progress `checkpoint.json` · B5 frame sequences · `node_modules/` · scratch and test folders · Codex's original generated files (`~/.codex/generated_images`) · the local backups. Rendering must never depend on Garage being reachable **[CODE: all of these are plain local-file operations]**.

### 6.3 Selective synchronisation: what goes up (AP-30, AP-34; exact list is G15) 🟡

| Tier | Uploaded when | Content | Prefix |
|---|---|---|---|
| **1 · Approved assets** | After the owner approves the asset | Character sources and puppet-kit PNGs; environment plates, layers, masks; props; fonts and licences | `characters/`, `environments/`, `props/`, `shared/` |
| **2 · Episode sources** | When the episode stage is approved | Script, storyboard; scene graph and project files; audio stems and mixes; caption sources | `episodes/<id>/…` |
| **3 · Production outputs** | After an **approved** full render | Master MP4s; `*.srt` / `*.vtt`; contact sheet; render report (`*-report.json`); the approval record (`approval.json`, kept as **provenance only**) | `masters/` |
| **3 · Platform exports** | After export and owner review | Per-platform videos, captions, thumbnails and covers | `exports/<platform>/`, `thumbnails/`, `covers/` |
| **4 · Records** | With each release | `publish/*.json`, rights ledger, release manifest, QA checklist | `publish/`, `rights-ledger/`, `releases/` |

**Never uploaded:** everything in §6.2. **Drafts and unapproved previews stay local.** (An approved 20-second preview may be uploaded with its master as part of the approval record.)

### 6.4 A verified constraint: keep a **fixed absolute working path** [VERIFIED] ✅ approved: AP-38 ⚠️
I tested the same project (identical `project.json` and narration, byte for byte) in three different folders. **The renderer produced three different fingerprints** (`58fc908e…`, `f1b3ef22…`, `a4784f4c…`), because absolute file paths are part of the fingerprint (`autopilot-core.mjs:135-137`) and of each shot's cache key (`autopilot-render.mjs:194`).
**Consequences**
- A project pulled into a **different folder** gets a new fingerprint, so a previous **preview approval no longer matches** and **cached shots are not reused**.
- So the working root must be a **fixed absolute path** (G17), for example `C:\Users\PC\Desktop\Works\stickman-video-director\studio-work\<episode-id>\`, and an approved project must **not be relocated**. If a relocation ever happens, the preview and approval must be redone.
- The stored `approval.json` is **provenance** for a release; it is **not** a portable approval that can be reused from another path or machine.
**This corrects the assessment**, which listed `approval.json` as "machine-bound, do not store". The accurate position: **store it as a read-only record, never as a live input.**

### 6.5 Failure handling
| Situation | Behaviour |
|---|---|
| Garage unreachable | **Rendering continues** from local files. Finished outputs queue for upload |
| Interrupted pull | Re-verify checksums; re-pull only missing or mismatched files |
| Checksum mismatch on pull | **Stop**; do not render; report |
| Partial upload | Resume the **same** `vNNN/` only after verifying what arrived; never overwrite an existing object |
| Prefix already exists | Refuse; create the next version |
| Upload verified | Only then may the owner choose to clear local working folders. **Nothing is deleted automatically** |

## 7. Backup and recovery workflow 🟡 (principle approved: AP-32; specifics open: G2, G6)

### 7.1 Layers
| Layer | What | Where | Status |
|---|---|---|---|
| **1 · Garage's own durability** | Replication (Garage recommends 3 replicas on at least 3 nodes) and **metadata snapshots** | On the Garage host(s) | ⏳ depends on G2 |
| **2 · Independent backup** ✅ | One-way copy of the whole bucket, **on a different system and a different location from the Garage server** | Backup target (G6) | Principle approved; target ⏳ |
| **3 · Local working copies** | Approved projects stay on the workstation until the owner clears them | `…\studio-work\` | Existing practice |
| **4 · Server configuration record** | A written record of buckets, key **names and permissions** (never secrets), and Garage layout settings | In IaC when approved, plus this repository's docs | ⏳ |

### 7.2 Independent backup job (design)
- Runs on a **different host** than Garage, with the **backup key** (`read` only) so it cannot alter the source.
- **Copies new and changed objects; never deletes** from the backup (no "mirror with delete").
- Stores results in **dated trees** and writes a **backup log** with SHA-256 values, compared against the release manifests.
- **Trigger:** after each upload (event-driven) and a periodic integrity check; exact schedule ⏳.
- **Retention:** keep everything (small volumes) unless the owner decides otherwise ⏳.

### 7.3 Recovery scenarios
| Scenario | Recovery |
|---|---|
| An object is deleted or overwritten by mistake | Restore it from the backup copy; verify against the manifest |
| A local working folder is lost | Re-pull from Garage by manifest, **into the same absolute path** (§6.4) |
| One Garage node fails | Handled by replication **if** the topology has replicas; otherwise restore from backup |
| Garage metadata is corrupted (e.g. after an unclean shutdown) | Restore from a metadata snapshot **[GARAGE-DOCS]**; otherwise rebuild and restore objects |
| The whole Garage server is lost | Rebuild the service from the configuration record (IaC when approved), recreate the bucket and **new** keys, restore objects from the independent backup, verify every manifest, then rotate credentials |
| A key is exposed | Revoke it, create a replacement, review activity, and re-verify recent uploads |
| The backup host fails | Create a new backup target and run a full copy from Garage |

### 7.4 Restore drill
Before any irreplaceable asset is stored: restore **one release** from the backup into a scratch folder and verify every hash against its manifest. Repeat on a schedule (⏳, suggest quarterly). **Backups that have never been restored are untrusted.**

### 7.5 Not covered by this bucket
The repository itself (documents, scripts) is not in Garage and **has no `.git`**, so it currently relies on a single local backup folder (G18).

## 8. Credential handling and TLS 🟡 (principle approved: AP-33; method open: G4)

### 8.1 Rules (no actual secrets appear anywhere)
1. **Never in the repository**, in `project.json`, scripts, documents, logs, chat, screenshots or agent output. Documents use **placeholders only**. (`.env` and `.env.*` are already git-ignored **[CODE]**, but a plain `.env` file is still weak storage on a workstation.)
2. **Environment-variable names are project-prefixed** (below) so they cannot collide with another project's settings on the same machine. **Do not use the generic `AWS_*` names or a default profile** in a shell shared with other projects.
3. **Separate credentials per role** (§4.2); a tool receives only the role it needs.
4. **Injected at run time**, scoped to the process or session, not persisted in the user environment; secrets are not passed as command-line arguments (they can appear in process lists).
5. **Agents and tools never print, log or echo a secret**; a storage "doctor" check reports **presence and reachability only**, like the renderer's existing `doctor` does for API keys **[CODE]**.
6. **Rotation:** on a schedule (⏳) and immediately after any suspected exposure; a rotation changes the secret in the chosen store, not in any file here.
7. **Least privilege** and **no admin key on the workstation** by default.
8. **Secret scanning** of changes before any future commit (once the repository has git).

### 8.2 Proposed variable names (placeholders; nothing is set)
`STICKMAN_GARAGE_ENDPOINT` · `STICKMAN_GARAGE_REGION` (default `garage`) · `STICKMAN_GARAGE_BUCKET` · `STICKMAN_GARAGE_RW_ACCESS_KEY_ID` / `STICKMAN_GARAGE_RW_SECRET_ACCESS_KEY` · `STICKMAN_GARAGE_RO_ACCESS_KEY_ID` / `STICKMAN_GARAGE_RO_SECRET_ACCESS_KEY` · optional `STICKMAN_GARAGE_CA_BUNDLE` · `STICKMAN_WORK_ROOT` (the fixed local path, G17).

### 8.3 Storage options for the secret (G4, decide later)
OS credential store · a password-manager CLI that injects variables at run time · a per-user profile file outside the repository with restricted file permissions. **Not recommended:** a plain `.env` in the repository folder, or persistent user-level environment variables.

### 8.4 TLS and network
- **HTTPS only**, through a **reverse proxy with CA-issued certificates** **[GARAGE-DOCS]**; **certificate verification always on** (never disable it; for a private CA, supply its certificate).
- Do not expose Garage's internal RPC or admin ports publicly; protect the metrics endpoint with its token **[GARAGE-DOCS]**.
- Limit who can reach the endpoint (VPN or firewall) ⏳.
- Test large-upload limits and timeouts on the reverse proxy; the docs are silent on them.

## 9. Independence from the Kids Animation repository ✅ principle (AP-28)

| Dimension | This project | Kids Animation project | Shared? |
|---|---|---|---|
| Repository and code | `stickman-video-director` | Its own | **No** |
| Bucket | `stickman-studio` (+ optional archive) | Its own bucket | **No** |
| Access keys | Roles in §4.2 | Its own keys | **No**; no key has access to the other project's bucket |
| Configuration names | `STICKMAN_*` | Its own prefix | **No**; never reuse generic names |
| Local folders | `…\studio-work\` | Its own | **No** |
| Backups | Its own backup tree and read-only backup key | Its own | **No** |
| Documentation | Never names the other project's bucket, keys or endpoints | Same | **No** |
| **The Garage service itself** | Capacity, nodes, network, TLS proxy, monitoring, maintenance, outages | Same | **Yes: this is the only shared fate** |

**Mitigations for the shared service:** a per-bucket quota (if supported); capacity alerts; advance notice of maintenance; an independent backup and restore per project; and a rule that **agents working on this project never read the Kids repository, its secrets or its bucket**; any cross-project operation needs explicit owner approval.

## 10. What would eventually need to change to support Garage (not implemented) 🟡

| Area | Change needed | Implemented now? |
|---|---|---|
| **Renderer** (`skills/directing-stickman-videos`) | **None.** The design keeps it unchanged; its only requirement is a **stable absolute working path** (§6.4) | No change |
| **`package.json`** | **None** for the renderer. Any transfer tool is separate | No change |
| **New project-level tooling** (proposed home `tools/storage/`, **outside the Skill**) | Config loader with presence/reachability check (no secret output) · manifest builder and verifier · selective **pull** (read-only key, checksum-verified, fail-closed) · **push** (write key, new version only, never delete, verify) · release packager · retrieval into `to-upload/` · restore-drill helper · storage `doctor` | **No: not created** |
| **Transfer client** | Choose **AWS CLI**, **rclone**, or a small script (SigV4 signing is security-sensitive, so a vetted client is preferable). **Each needs install approval** | **No** |
| **Garage infrastructure** | The Garage host(s), reverse proxy, certificates, DNS, monitoring, backup target; defined with **Terraform** per org standard where applicable | **No: Terraform not touched** |
| **Bucket and keys** | Create `stickman-studio` and the four roles; verify the unconfirmed features (§4.3) on a test instance | **No** |
| **Docs and runbooks** | Operations runbook, restore-drill procedure, secret-rotation procedure, `.env.example` containing **names only** | Not yet |
| **Per-episode records** | Release manifests and object-key records under `publish/` and `releases/` | Not yet |
| **Tests** | A dry run on a **non-production** project: push, delete the local copy, pull, re-render at the same path, compare hashes | Not yet |

## 11. Multi-platform alignment
The layout in §5 keeps **production masters**, **YouTube, TikTok and Facebook exports**, and **captions, thumbnails and supporting files** in separate, predictable places, matching the per-episode package in `bible/MULTI_PLATFORM_ARCHITECTURE.md`. Storage does not decide which platforms are used, and **no publishing automation is built** (AP-36). Platform specifications and policies still need official-source research before export presets are finalised.

## 12. Next implementation steps awaiting approval ⛔ (none started)

| Step | What | Needs |
|---|---|---|
| **N1** | **Owner supplies Garage server specifications** (existing server or new; hosts, OS, disks, network, node count, replication, administrator) → decide **G2** and update this document | Owner input |
| **N2** | Owner decides the remaining open items: G4, G5, G6, G8, G13, G14, G15, G16, G17, G18 | Owner decision |
| **N3** | **Deployment approval**: provision a **test** Garage instance behind TLS (Terraform-defined where applicable) | **Separate approval** |
| **N4** | Create the bucket and keys **on the test instance** and verify quotas, the no-create-bucket flag, delete behaviour and large uploads | **Separate approval** |
| **N5** | Choose and install the transfer client, or approve small scripts | **Separate approval** |
| **N6** | Build `tools/storage/` (config check, manifest, pull, push, verify). **No renderer change** | **Separate approval** |
| **N7** | Dry run on the Phase 0 example as a non-production episode (push, remove local copy, pull, re-render at the same path, compare) | **Separate approval** |
| **N8** | Backup target, backup job and a restore drill on test data | **Separate approval** |
| **N9** | Production cut-over: real bucket and keys, first real assets | **Separate approval** |

## 13. Risks (updated)
| Risk | Mitigation |
|---|---|
| **Absolute paths are baked into the fingerprint and cache keys** [VERIFIED] | Fixed working root (G17); never relocate an approved project; redo preview and approval if it happens |
| No versioning, object lock or prefix permissions; `write` likely includes delete | Write-once versions, manifests, no-delete tooling, independent backup, read-only default key, optional archive bucket |
| Shared service couples this project to the Kids project's capacity and outages | Quota, alerts, maintenance notice, independent backups, local-first workflow |
| Single-node topology has no redundancy | Decide G2; otherwise rely on the independent backup and local copies |
| Secret exposure on a workstation | Role-separated keys, injection at run time, never printed, rotation |
| Backups never restored | Mandatory restore drill (§7.4) |
| Large uploads fail behind a reverse proxy | Test limits and timeouts on the test instance |
| Case-insensitive Windows vs case-sensitive keys | Lowercase-only naming |
| Documentation drift (Garage's S3-compatibility page is dated 2022) | Re-verify against the deployed version |

## 14. Not done, by instruction
Garage was not installed, deployed or configured. No bucket, key or credential was created. No application code, renderer, workflow, dependency or Terraform was changed. No file was deleted, committed or pushed. All existing artwork, test outputs, scratch files and backups were preserved. No secret was read, copied or written. The one experiment performed (§6.4) used **copies of two project files in the session's scratch folder** and changed nothing else.
