# VPS Production Readiness — Stickman Comedy Studio

> ## ⚠️ Planning only. Nothing was installed, deployed or changed.
> The owner authorised **read-only inspection** and **preparing the plan**. This document records what the inspection found and proposes a design. **No package or service was installed, Garage was not deployed, no firewall or DNS rule was changed, no application code or Terraform was modified, no asset was moved or deleted, no heavy job was run, and nothing was committed.** Shared infrastructure is to be implemented **once, in a coordinated way, by the owner's plan**, not independently by this session or the Kids session. *Architecture approval is not deployment approval.*

**Status:** readiness assessment and proposal · **Date:** 2026-11-11 · **Author:** Claude Code (Stickman session)
**Scope:** this repository only. The Kids Animation project's repository, files and secrets were **not inspected**.
**Not recorded here, deliberately:** the server's address, hostname, key names, credentials or any secret.

| Label | Meaning |
|---|---|
| **[SERVER]** | Observed on the VPS on 2026-11-11 with read-only commands |
| **[CODE]** | Confirmed by reading this repository's code or lockfile |
| **[LOCAL]** | Observed on the Windows machine (help text, measured files) |
| **[PROPOSED]** | My recommendation, awaiting approval |
| **[ASSUMED]** | An estimate; to be replaced by measurement |
| **[OPEN]** | A decision or fact still needed |
| ✅ **APPROVED** | Decided by the owner |

---

## 1. Direction change recorded (owner, 2026-11-11) ✅

| ID | Decision |
|---|---|
| **AP-40** | The **Contabo VPS is the central production environment for both animation projects** (Kids Animation Studio and Stickman Comedy Studio), plus one shared Garage S3-compatible service, shared monitoring, backup and security infrastructure. |
| **AP-41** | The owner's **Windows machine is for remote administration and talking to Claude only.** It must **not** be required for rendering, asset processing or any production workload. |
| **AP-42** | **Each project stays isolated** (own directory, runtime, assets, bucket, credentials). Shared infrastructure is built **once, in a coordinated plan**; **neither Claude session deploys it independently.** |
| **AP-43** | **Read-only inspection and planning are authorised.** Installing, deploying Garage, changing firewall/DNS/Terraform/code, moving or deleting assets, changing fixed paths, heavy rendering and committing are **not**. |
| **AP-44** | **Owner-confirmed (2026-11-11): the Kids Animation Claude session is the SOLE shared-infrastructure coordinator for BOTH projects**, authorised across both repositories. The coordinator owns planning and execution coordination for: Garage deployment and administration; reverse proxy and TLS; shared monitoring and alerting; independent backup and recovery infrastructure; host-wide rendering coordination; shared server security and operational runbooks. **Stickman keeps:** its repository and renderer, its production environment, its bucket and credentials, its storage integration, its animation and multi-platform export workflow, and its testing and documentation. Stickman coordinates with the Kids session and **does not independently deploy or modify shared services.** |
| **AP-45** | **Mandatory safeguard 1:** Caddy must pass **real large multipart upload testing** before production use. |
| **AP-46** | **Mandatory safeguard 2:** **no irreplaceable production assets in Garage** until an **independent off-server backup** exists and a **restore test has succeeded**. |
| **AP-47** | **Mandatory safeguard 3:** **only one heavy rendering job may run across both projects initially.** |
| **AP-48** | **Mandatory safeguard 4:** **SSH hardening requires verified key-based access and a rollback procedure.** |
| **AP-49** | **Mandatory safeguard 5:** public web services use **ports 80 and 443**; **SSH is separately restricted.** |
| **AP-50** | **This confirmation establishes ownership and architectural direction. It is NOT blanket approval to execute every infrastructure change.** Each separate implementation gate still needs the owner's approval. Acknowledging it required no install, deployment, SSH change, firewall change or code change. |

**Effect on earlier decisions:** "local" in *local-first rendering* (AP-25) now means **the VPS's local disk**. The **fixed absolute working path** (AP-38) becomes a **Linux path**; its proposed value is in §5. The Windows paths used so far are test artefacts only.

**Owner's execution order:** (1) server security, directories, storage; (2) independent backup and monitoring; (3) Garage; (4) separate project buckets and credentials; (5) both production environments; (6) integrate each project separately; (7) test rendering and recovery.

## 2. Server evidence [SERVER]

Two SSH sessions, strict host-key checking against an already-trusted key, key-based login, fixed read-only command lists. No environment variables, config files, secrets or the Kids project's files were read.

| Item | Observed |
|---|---|
| Provider / type | Contabo VPS, **KVM** full virtualisation |
| OS | **Ubuntu 24.04.5 LTS**, kernel 6.8, **x86_64**, **glibc 2.39** |
| CPU | **4 vCPU**, AMD EPYC, 1 thread per core |
| Memory | **7.8 GiB total, about 7.2 GiB available, no swap** |
| Disk | **One 100 GB disk**: `/` is 96 GB ext4, **93 GB free (4% used)**; separate small `/boot` and EFI; **no second disk**; `/tmp` and `/srv` are on the same filesystem as `/` |
| Inodes | 1% used |
| Load / uptime | Up 5 days; load ≈ 0.08; **CPU 99.75% idle on average today, steal 0.00**; memory use about 2.4%; pressure-stall values near zero |
| Init / cgroups | systemd 255, **cgroup v2** (resource limits are available) |
| Time | NTP synchronised; timezone Europe/Berlin |
| Containers | **Docker 29.9.3 installed; no containers, no volumes, no compose projects**; 3 unused images (478 MB) |
| Listening ports | **Only SSH (22)**. No web, S3 or monitoring port |
| Firewall | **UFW active**, default deny incoming, **only 22/tcp allowed** |
| Intrusion control | **fail2ban active** with an `sshd` jail; unattended upgrades active; no reboot pending |
| **SSH settings** | **`PermitRootLogin yes` and `PasswordAuthentication yes`**, in addition to key login ⚠️ |
| Accounts | `root` and one ordinary account (`ubuntu`) |
| `/srv` | **Empty**. `/opt` holds only `containerd` |
| Git repositories found (shallow) | One, under `/root` (the other project's). **No Stickman files exist on the server** |
| **Installed** | Python 3.12.3 and pip, git 2.43, **Terraform 1.6.0**, fail2ban, ufw, Docker |
| **Not installed** | **Node.js, npm, FFmpeg/FFprobe, Codex CLI, Garage, a reverse proxy (Caddy/nginx/Traefik), rclone/AWS CLI, restic/borg, Prometheus/Grafana** |
| Packages the Ubuntu repos offer | **Node 18.19.1** (below the renderer's requirement), **FFmpeg 6.1.1** |

**Reading of the evidence:** the server is **clean, idle and unprepared**: ready to be configured, but nothing for either project beyond one existing repository in a root-owned home folder.

## 3. Stickman project and renderer on the VPS

### 3.1 Can the renderer run without the Windows machine? **[CODE]** Yes, in principle.
- **No OS-specific code** in the Autopilot renderer, its B3/B4 helpers, the B5 route or the adapters (strict search for `win32`, `process.platform`, `.exe`, drive letters, user-home or macOS paths found none).
- **Linux binaries are in the lockfile:** `sharp` and `@napi-rs/canvas` ship `linux-x64-gnu` builds, which match this server's glibc **[CODE]**. They would be installed by `npm ci` with no version change.
- **Fonts are bundled** (Caveat, Noto Sans); the Skill's `FFMPEG`, `FFPROBE` and `AUTOPILOT_FONT` environment variables select tools and fonts **[CODE]**.
- **Only OS-specific paths** are macOS font paths in the A6 finishing helper (a different mode, not used by the Autopilot route).
- **Not yet verified by running on Linux**, because installing Node and FFmpeg is not authorised. The Windows tests that failed were Windows-only (a path-separator bug in one upstream test), so a Linux run should be cleaner **[REASONED]**.

### 3.2 What the VPS lacks for this project
| Need | State | Note |
|---|---|---|
| **Node.js ≥ 20** | Missing; **Ubuntu's own package is 18.19, too old** | Needs another install source (decision P2) |
| **FFmpeg + FFprobe** | Missing | Ubuntu's 6.1.1 is fine |
| `npm ci` (two packages, locked) | Not run | Works offline-lockfile style; needs outbound network to the npm registry |
| The repository | **Not on the server**; locally it has **no `.git`** | Decision P1 |
| Python/Whisper | Python 3.12 present; Whisper not installed | Optional, later |
| Codex CLI | Missing | See §4 |

### 3.3 What still ties our workflow to Windows [LOCAL]
The only working copy of this repository; the Codex CLI login; FFmpeg's location; the Phase 0 and spike outputs; and Claude Code itself (which would remain an *administration client*). None is a renderer dependency; they are **workflow dependencies to move** (§8).

## 4. Generation and audio workflows, and Codex on the VPS

| Workflow | Today | On the VPS |
|---|---|---|
| Rendering (Autopilot, B5) | Local Node + FFmpeg | Runs natively as the project user |
| Voice | Optional Gemini adapter (`GEMINI_API_KEY`, paid); other providers via project-local adapters; voice choice still open (D8) | Same, with the key supplied by the credential mechanism, **never in the repository** |
| Sound effects | Built-in synthesised sounds, or an external mix | Same; the mixer is future tooling |
| Caption timing | Optional Whisper helper | Needs Python packages (approval) |
| Image generation | **Codex CLI** with a ChatGPT login, scratch-directory workflow | Needs Node, the CLI install, and a **headless login** |

**Codex from the VPS [PROPOSED; nothing installed]:**
- Codex supports `codex login --device-auth` (a device-code flow suited to a server with no browser), as well as `--with-api-key` (a **paid API** key: not allowed without approval) and `--with-access-token` **[LOCAL: help text]**.
- It stores its login under the running user's home (`~/.codex`), which is a **secret**. Use **one Linux user per project** so logins, generated images and scratch areas stay separate.
- The ChatGPT login belongs to the **owner's account**: both projects would share one quota, and whether **server-side use of a personal subscription** is within its terms is **[OPEN]**. Check before relying on it.
- Keep the existing rules: one image per task, scratch directory only, review before use, never the `--dangerously-bypass…` flags, and no use to bypass an approval gate.

## 5. Proposed Stickman production design on the VPS [PROPOSED]

### 5.1 Identity, directories and fixed path
| Item | Proposal |
|---|---|
| Service user | `stickman` (no password, no sudo; key-less service account) |
| Project root | `/srv/stickman/` (owner `stickman:stickman`, mode `0750`) |
| Repository | `/srv/stickman/repo/` |
| **Fixed working root (AP-38)** | **`/srv/stickman/work/`**, one folder per episode: `/srv/stickman/work/<episode-id>/` **(never relocated once approved)** |
| Render output and cache | `<episode>/output/` (local only, never synced) |
| Temporary files | `/srv/stickman/tmp/` (set as `TMPDIR`) |
| Retrieved exports for manual upload | `/srv/stickman/to-upload/<platform>/` |
| Logs | `/srv/stickman/logs/` |
| Environment configuration | `/etc/stickman/stickman.env` (non-secret settings) and a separate root-owned, `0600` credential file or systemd credential for secrets |
| Not under `/root` | The other project's repository sits under `/root`; this project must **not** |

### 5.2 Environment configuration (names only; nothing set)
`STICKMAN_WORK_ROOT=/srv/stickman/work` · `STICKMAN_GARAGE_ENDPOINT` · `STICKMAN_GARAGE_REGION` (`garage`) · `STICKMAN_GARAGE_BUCKET` (`stickman-studio`, placeholder) · `STICKMAN_GARAGE_RW_*` and `STICKMAN_GARAGE_RO_*` credential names · `FFMPEG` and `FFPROBE` (to point at a limiting wrapper, §6) · `TMPDIR`. Only the `STICKMAN_` prefix is used, so the other project's names cannot collide.

### 5.3 Garage bucket and credentials
As in `docs/GARAGE_STORAGE_FINAL_ARCHITECTURE.md`: bucket `stickman-studio` (placeholder, **not created**), four key roles (working, read-only, backup read-only, admin), private by default, write-once `vNNN/` prefixes. **Created only in step 4 of the owner's order, after the single coordinated Garage deployment.**

### 5.4 Local working storage budget (single 96 GB disk) [ASSUMED]
| Use | Estimate |
|---|---|
| OS, Docker, logs, packages | about 5–10 GB |
| Stickman repo, dependencies | under 1 GB |
| Active episode working areas | about 0.5–2 GB each, up to about 1 GB more for B5 frame folders |
| Garage data (both projects, single replica) | tens of GB over the first year (see the Garage assessment: about 8–25 GB per project per year) |
| Backups | **must not live on this disk** (§5.6) |
Capacity is adequate for the first year or two, **but it is one disk shared by everything**, so monitor free space and plan growth (decision P11).

### 5.5 Isolation and resource limits (starting points, to be tuned by measurement)
| Mechanism | Proposal |
|---|---|
| Linux users/groups | `stickman` and the other project's own user; `0750` directories; **no shared writable data directory** |
| systemd slices (cgroup v2 is available [SERVER]) | A `stickman.slice` and a matching one for the other project, plus an infrastructure slice for Garage, proxy and monitoring |
| Memory | Hard `MemoryMax` per project slice (**about 3 GiB each**) with a lower soft `MemoryHigh`; protect Garage and Docker from the OOM killer, because there is **no swap** |
| CPU | `CPUWeight` equal per project; heavy jobs also limited by affinity or quota (§6) |
| I/O | `IOWeight` equal per project |
| Tasks/files | `TasksMax` and `LimitNOFILE` raised for the render user (default `ulimit -n` is 1024 [SERVER]) |
| One heavy job at a time | A **shared lock** (§6.4) |
Final numbers must be agreed **jointly with the Kids session**, because total memory is only 7.8 GiB.

### 5.6 Backup and recovery [PROPOSED]
- **A single VPS with a single disk is not its own backup.** The approved principle (AP-32) requires backups **outside the Garage server**; here that means **a different machine or location**. **No such target exists yet** (decision P4).
- Layers: Garage replication is **not possible on one node** (replica count 1); **metadata snapshots** (Garage's documented 6-hourly option) must be **copied off-box**; a **one-way, no-delete copy** of each project's bucket to the off-box target with a **read-only backup key**; a periodic **restore drill**.
- Provider snapshots, if offered, are a convenience but are **not independent** of the provider and datacentre; their availability is **[OPEN]**.
- **Recovery** scenarios follow the Garage final proposal §7: object restore, metadata restore, full-server rebuild from the configuration record and the off-box copy, key rotation.
- The Windows machine may hold an **optional** extra copy but is **not required** for recovery (AP-41).

### 5.7 Platform export organisation (unchanged)
Masters, YouTube Shorts and long-form, TikTok, Facebook Reels and video exports, captions, thumbnails and covers keep the prefix layout in the Garage final proposal §5, matching `bible/MULTI_PLATFORM_ARCHITECTURE.md`. Exports are retrieved to `/srv/stickman/to-upload/<platform>/` and then fetched to the Windows machine over SSH **for manual platform upload**. **No publishing automation** (AP-36).

## 6. Resource and rendering assessment (no heavy jobs were run)

### 6.1 Server baseline [SERVER]
Idle: about 2.4% memory used, 99.75% CPU idle, no steal, no pressure. **The whole 4 vCPU and about 7.2 GiB are currently free.**

### 6.2 What a render consumes
| Aspect | What the code shows | Estimate |
|---|---|---|
| **CPU** | Node draws frames on **one thread**; each frame is piped to **FFmpeg `libx264 -preset fast -crf 20`**, which by default **uses all cores**. The renderer passes **no `-threads` option** **[CODE]** | One render: about 1–2 cores on average, **up to all 4 in bursts** [ASSUMED] |
| **Speed** | **Measured on the Windows machine:** about 0.43 s per frame at 1080p with 5–6 full-frame layers (180 frames in 77 s) **[LOCAL]** | A 2:45 episode (about 4,950 frames) is about 35 min there; **the VPS's speed is unknown** (EPYC at about 2 GHz, shared) [ASSUMED] |
| **Memory** | Images are decoded **once** into memory **[CODE]**. A 1080p RGBA layer is about 8 MB, a 4K layer about 33 MB. Plus Node and the FFmpeg encoder | About **1–3 GiB** per heavy render [ASSUMED]; **not measured** |
| **Temporary disk** | Shot cache ≈ the final video size **[MEASURED]**; B5 writes one PNG per frame to disk **[CODE]** | Under 100 MB for ordinary B1–B4 renders; **up to about 1 GB or more** for B5 films [ASSUMED] |
| **Existing guard** | A per-project `render.lock` stops two renders of the **same** project **[CODE]**. **Nothing coordinates different projects** | A host-level guard is needed |

### 6.3 Contention and risks
- **Two simultaneous heavy renders** (one per project) could each want all cores and 2–3 GiB, leaving little headroom with **no swap**, so the kernel **OOM killer could terminate a render, Docker or Garage**.
- **CPU steal** from other tenants on a shared host is currently 0, but is not guaranteed.
- A **B5** render also saturates disk writes.
- `fail2ban`, unattended upgrades and Garage will add small, steady load.

### 6.4 Recommended controls [PROPOSED; to be validated by testing]
1. **A shared mutex for heavy jobs:** each project's render wrapper takes a common lock (for example `flock` on one agreed lock file) before starting. This needs no new software. Move to a real queue **only if** waiting becomes a problem; at present volumes (an episode every couple of weeks per project) a lock should suffice [ASSUMED].
2. **Limit FFmpeg without touching the renderer:** point the `FFMPEG` environment variable at a **wrapper script** that runs FFmpeg under `nice`/`ionice` and a **CPU affinity or cgroup limit**, e.g. 2 of 4 cores. (The renderer reads `FFMPEG` **[CODE]**, so no code change is needed.)
3. **cgroup memory caps** per project slice, and **OOM protection** for Garage and Docker.
4. **Pre-flight checks** before a heavy job: free disk above a threshold, free memory above a threshold, no other heavy job running.
5. **Decide on swap** (a small swap file would soften OOM risk but is a shared-server change; decision P5).
6. **Never run heavy jobs while a backup or restore drill is running.**
7. **Monitoring** for CPU, memory, disk, I/O pressure and job duration (§8).

### 6.5 Benchmark plan for later (not run)
After the owner approves installation: render a 5 s, a 60 s and a 3-minute project; record **peak memory** (`/usr/bin/time -v`), CPU, disk I/O, wall time and temporary disk; test the FFmpeg limiter; then test **two projects behind the shared lock** and one deliberate over-limit case in a safe window. Replace every [ASSUMED] figure above with measurements.

## 7. Security readiness [SERVER + PROPOSED]
| Finding | Recommendation (shared infrastructure: for the coordinated plan, **not applied**) |
|---|---|
| ⚠️ **Root SSH login and password authentication are both enabled** (fail2ban mitigates but does not remove the risk) | Create a named admin account; **key-only authentication**; disable password login; restrict root login; keep fail2ban |
| UFW allows only SSH | Opening **80/443** will be needed for TLS and a public endpoint **if** one is wanted; **do not open Garage's own ports publicly** |
| No TLS or reverse proxy | One shared proxy with CA-issued certificates; **needs a DNS name** (decision P3) |
| Both projects would share root | **Per-project Linux users**; secrets readable only by the owning user |
| Secrets | Credential files `0600`, loaded by systemd credentials or an environment file; **never in repositories, logs or chat** |
| Docker present | Not needed by the renderer; if used later, never mount the Docker socket into project jobs |
| Terraform 1.6.0 is on the server | Org standard is Terraform; **not touched**; scope is decision G10 |
| Unattended upgrades active | Keep; plan reboot windows with both projects |

## 8. Integration plan: what must eventually change (nothing implemented)

| Area | Change needed | Done now? |
|---|---|---|
| **Renderer** | **None.** Only the fixed absolute path, the `FFMPEG` wrapper and the shared lock are wrapped around it | No |
| **Server preparation** (owner's steps 1–2) | Admin and per-project users; `/srv/stickman` and the other project's tree; systemd slices; SSH hardening; swap decision; off-box backup target; monitoring | No (shared; coordinated) |
| **Runtime install** | Node ≥ 20 (**not** the Ubuntu 18.19 package), FFmpeg/FFprobe, `npm ci` from the lockfile as the project user; optional Python packages and Codex CLI | No (approval) |
| **Repository transfer and VCS** | Get the working tree to `/srv/stickman/repo/`; it currently has **no `.git`** (P1) | No |
| **Garage** (steps 3–4) | One coordinated deployment, TLS proxy, then `stickman-studio` bucket and key roles | No (not by this session alone) |
| **Storage synchronisation** | `tools/storage/` (config check, manifest, pull, push, verify) running **on the VPS** as the project user; no renderer change | No |
| **Environment configuration** | `/etc/stickman/stickman.env` and credentials; `STICKMAN_*` names; a configuration check that reports presence only | No |
| **Platform exports** | Prefix layout unchanged; export presets and external caption burn-in (future tools) | No |
| **Operational monitoring** | Disk free, memory, CPU and pressure, render job status and duration, Garage health, backup freshness, certificate expiry, failed SSH logins; alerts | No (shared stack, P8) |
| **Administration from Windows** | SSH only; deliverables fetched over SSH for manual platform uploads | No |
| **Documentation** | Runbooks, restore drill, key rotation; Linux path replaces Windows examples | Partly (this document) |

## 9. Coordination with the Kids session
The Kids session (`youtube-automation`) reported that it is doing the same read-only inspection, will **not** install or deploy any shared component, and asked for this project's names so they do not collide. This project's proposals are in the message sent to it and in the table below. **The Kids session has replied with matching proposals and no collisions** (below). These remain proposals; **nothing is agreed or built**, and the owner will reconcile both reports.

| Convention | Stickman proposes | Confirm with Kids |
|---|---|---|
| Linux user / group | `stickman` | Its own distinct name |
| Project root | `/srv/stickman/` | Its own `/srv/<name>/` |
| Fixed working root | `/srv/stickman/work/<episode-id>/` | Its own |
| Env prefix and file | `STICKMAN_*`, `/etc/stickman/` | Its own prefix, never generic |
| Bucket (placeholder) | `stickman-studio` | Its own; no cross-access |
| systemd slice | `stickman.slice` | Its own |
| Shared heavy-job lock | One agreed lock file and rule | **Agree one** |
| Memory/CPU caps | About 3 GiB memory each | **Agree jointly** |
| Garage ports and proxy host names | Not claimed by this project | **One owner** (infrastructure) |

**Kids session's reply (relayed, 2026-11-11):** it proposes a user `yta`, root `/srv/yta/` (repo, fixed work root `/srv/yta/work/<episode-id>/`, tmp, to-upload), `/etc/yta/`, variables prefixed `YTA_*`, bucket `yta-media` with key roles `yta-rw`, `yta-ro`, `yta-backup-ro`, `yta-admin`, and `yta.slice`: **no collision with Stickman's names**. It agrees that Garage, proxy host names, monitoring and the backup target need **one owner**, and that nobody should assume they are that owner; it is raising that with its own owner and is **not** touching `sshd_config`. It suggests the shared render lock at `/var/lock/animation-render.lock` and notes its own Node needs are met by 18.19 (so the Node ≥ 20 gap is Stickman's). **Both sessions have flagged the root-login/password-authentication setting as a security item for the owner.**

**Later update from the Kids session (relayed, 2026-11-11; **since confirmed by the owner, AP-44**):** it reports that its owner assigned **it** as **sole coordinator for the shared infrastructure** (Garage, reverse proxy/TLS, shared monitoring, independent backup, host-wide render coordination, shared security and runbooks), as **coordination ownership, not deployment approval**; that its planning-only proposal has **only ports 80/443 newly opened** (Caddy) with Garage's S3, admin, RPC and metrics bound to localhost; a **single-node, Docker-deployed Garage with replica 1 and two buckets at bring-up** (its own and `stickman-studio`); **soft disk alerts at 70% and 85%** rather than hard quotas (unless Garage supports bucket quotas); an off-box **rclone** backup with a per-project read-only key and the destination undecided; a **`flock`** lock at `/var/lock/animation-render.lock` limited to heavy render/encode jobs; per-project memory caps **deferred until measured**; SSH hardening documented as a gated procedure only. **Stickman's reply:** the lock should cover `render`, `preview`, the B5 `frames`/`encode` steps and future FFmpeg/Whisper steps but not Codex image generation, `validate`, `probe`, `doctor` or transfers; 80/443-only fits (Stickman needs outbound access only); large-upload limits on the proxy must be tested; **the independent backup is a prerequisite before any irreplaceable asset is uploaded**; `stickman-studio` must be listed as *planned, not created*. **This session has not read the Kids repository.** The owner has since confirmed the coordinator role and five safeguards (AP-44 to AP-49), but **that is not blanket approval** (AP-50): each implementation gate still needs the owner's approval.

## 10. Blockers and decisions requested## 10. Blockers and decisions requested

| ID | Decision / blocker | Recommendation |
|---|---|---|
| **P1** | How the repository reaches the server and gets version control (it has no `.git`) | `git init`, then a private remote or a bare repository on the server; or a one-time copy |
| **P2** | Node ≥ 20 source (the Ubuntu package is 18.19) | A pinned, verified installer or tarball; avoid unpinned `latest` |
| **P3** | A DNS name for the storage endpoint and who controls DNS | Decide before TLS |
| **P4** | **Off-box backup target** (blocker for step 2) | Required; none exists yet |
| **P5** | Swap, memory caps and CPU limits | Small swap plus per-project caps, tuned by testing |
| **P6** | SSH hardening and admin accounts | Do it first (step 1) |
| **P7** | Garage on one node (replica 1) and where its data lives on a single disk | Accept single-node only with the off-box backup in place |
| **P8** | Monitoring stack (shared) | One lightweight shared stack; do not install two |
| **P9** | Codex on the VPS: device-auth login, and whether server use of the personal subscription is permitted | Check terms first |
| **P10** | Whether to run Claude Code sessions **on the VPS** over SSH instead of on Windows | Consider; it removes more Windows dependence |
| **P11** | Disk growth plan (one 96 GB disk) | Alert early; plan more storage |
| **P12** | The shared render lock/queue design | Simple lock first |
| **P13** | Confirm naming with the Kids session | Reconcile via the owner |
| **P14** | Which account agents run as (never root for rendering) | The project user |
| **P15** | How finished exports reach the Windows machine for manual uploads | SSH copy; no public links |
| **P16** | Who owns and stands up the shared pieces (Garage, proxy, monitoring, backup target) | **RESOLVED by AP-44:** the Kids session is the sole shared-infrastructure coordinator (owner-confirmed) |

## 11. Exact next implementation actions awaiting approval ⛔ (none started)

| Step (owner's order) | Stickman-specific action | Gate |
|---|---|---|
| **0** | Owner reconciles the Kids and Stickman reports and answers P1–P15 | Owner |
| **1** Server security, directories, storage | Create the `stickman` user and `/srv/stickman/…` tree, the slice and limits; SSH hardening; swap decision | **Separate approval; shared; coordinated** |
| **2** Backup and monitoring | Provision the off-box target and monitoring; verify | **Separate approval; shared** |
| **3** Garage | One coordinated deployment with TLS | **Not by this session independently** |
| **4** Buckets and credentials | Create `stickman-studio` and the four key roles; test isolation and the unconfirmed features | **Separate approval** |
| **5** Stickman environment | Install Node ≥ 20 and FFmpeg; transfer the repository; `npm ci`; environment file; FFmpeg wrapper; shared lock | **Separate approval** |
| **6** Integration | Build `tools/storage/`; dry run on the Phase 0 example | **Separate approval** |
| **7** Test and recover | Benchmark plan (§6.5), restore drill, concurrency test with the other project | **Separate approval** |

## 12. Not done, by instruction
No packages or services were installed. Garage was not deployed. No firewall, DNS, Terraform or application code was changed. No assets were moved or deleted. No fixed project path was changed. No heavy job ran. Nothing was committed. The inspection used two read-only SSH sessions with strict host-key checking and no state changes; the server's address, hostname and key details are not written into this repository.
