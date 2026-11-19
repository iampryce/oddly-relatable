# GPU and on-demand worker infrastructure: research and recommendation

**Status (2026-11-16): RESEARCH AND PROPOSAL ONLY.** Nothing has been signed up for, bought or provisioned. No paid resource may be created until the owner approves the decisions in §8. The Shorts workflow, the local CPU worker and the existing job queue stay as they are.

**Prices checked on 2026-11-16.** Figures marked **(official)** come from the provider's own pricing page or documentation. Figures marked **(secondary)** come from third-party trackers or blogs and were not confirmed on the provider's page. Figures marked **(estimate)** are this document's own calculations. GPU prices change often, and spot prices change hourly, so check them again before any approval.

---

## 1. Summary

- **Most of our pipeline does not benefit from a GPU today.**
  - The 2D renderer (Node + canvas + FFmpeg) is CPU-bound.
  - Scripts, character art and voices already come from hosted APIs, at a few dollars a month.
  - A GPU becomes worthwhile only for **self-hosted image models** (FLUX/SDXL with LoRA or IP-Adapter for character consistency) and **AI video clips**. Both are optional, future work.
- **The real near-term need is CPU, for long-form turnaround.** A 6-minute episode costs cents of CPU on a burst instance. The reason to burst is speed, and keeping the VPS free; money is not the reason.
- **Recommendation:**

  | Role | Primary | Fallback |
  |---|---|---|
  | GPU work (when approved) | **RunPod on-demand pods**, Secure Cloud, **RTX 4090 24 GB**: per-second billing, prepaid balance (a natural hard cap), Docker image = our worker image | **Modal** serverless (L4 24 GB / L40S 48 GB), per-second, scale to zero, $30/month free credit |
  | CPU long-form segment rendering | **AWS EC2 spot `c7i.4xlarge` / `c7a.4xlarge`** (16 vCPU), in the same region as the S3 bucket | The existing VPS (slower, $0 extra) |
  | AI video clips | **Hosted API (fal.ai, Kling)** per second of output; no self-hosting | Replicate |

- **Expected monthly spend (estimate)**, for 30 Shorts, 4–8 long episodes and 3–4 new characters: **about $10–$20 for compute and storage**. With AI-video experiments it is **about $25–$45**. Recommended hard cap: **$50/month** for compute, inside the $150 overall target (§6).

---

## 2. Which jobs would gain from a GPU (honest assessment)

| Job (`tasks.py`) | Where the time goes | GPU benefit |
|---|---|---|
| `generate_script`, `regenerate_*`, `generate_storyboard` | Remote LLM API / Codex CLI | **None.** Network-bound |
| `scene_reference`, `scene_prepare` | Node engine `build` + `storyboard` stills | **None.** CPU canvas |
| `render_episode` (and future long-form segments) | Node canvas paints each frame, then FFmpeg encodes with libx264 | **None without a rewrite.** The canvas library paints on the CPU. NVENC could encode on a GPU, but painting dominates (about 0.07–0.08 s per frame), and NVENC output differs from today's encoder settings. Not worth it |
| `scene_voice`, `voice_preview` | OpenAI TTS / ElevenLabs API; Piper on CPU | **None** for APIs. Piper is already fast on CPU |
| `character_pose`, `character_sheet` | OpenAI Images API / Codex (gpt-image) | **Only if we self-host** FLUX/SDXL. The cost saving is a few dollars a month. The real gain would be **consistency**: a per-character LoRA, IP-Adapter or reference conditioning, and control over a flat background for cut-out |
| `publish_youtube` | Upload | None |
| *Future:* LoRA training per character | Training 15–40 minutes per character on a 24 GB card **(estimate, not benchmarked)** | **Yes.** Needs a GPU |
| *Future:* image-to-video clips | Diffusion video model | **Yes**, but hosted APIs are cheaper at our volume (§5) |

**Conclusion.** A GPU is a capability purchase (consistent characters, AI clips), not a speed-up of anything that runs today. It should come only after the owner decides that self-hosted image models are wanted.

---

## 3. Provider comparison (GPU)

### 3.1 Table

| Provider | Relevant GPUs (VRAM) | Price per hour | Billing | Storage | Egress | Automation | Cold start |
|---|---|---|---|---|---|---|---|
| **RunPod pods** | RTX 4090 24 GB; L4 24 GB; A40 48 GB; L40S 48 GB; RTX 5090 32 GB; A100 80 GB; H100 80 GB | Secure Cloud: 4090 $0.89, L4 $0.69, A40 $0.59, L40S $1.09, 5090 $1.39, A100 80 GB PCIe $2.09, H100 PCIe $2.89 / SXM $4.39. Community Cloud: 4090 $0.34, L40S $0.79, A100 PCIe $1.19 **(official)** | Per second **(official)** | Container disk $0.10/GB-month; volume $0.10 running / $0.20 idle; network volume $0.07/GB-month (<1 TB) **(official)** | None charged **(secondary; not stated on the pricing page)** | REST/GraphQL API, `runpodctl`, Python SDK; create/terminate pod | Pod start plus image pull: minutes for a large image **(secondary)** |
| **RunPod Serverless** | Same pool, by VRAM tier | Flex: 24 GB (L4/A5000/3090) $0.75; 24 GB 4090 $1.34; 48 GB L40S $1.89; 48 GB A40/A6000 $1.22; 80 GB A100 $2.99; H100 $5.89 **(official)** | Per second, including cold start and a 5 s default idle timeout **(official)** | As pods | As pods | Endpoint API (`/run`, `/status`); its own request queue | FlashBoot about 0.2–1 s when warm; 8–50 s+ for a cold model load **(secondary)** |
| **Vast.ai** | Marketplace: 4090, 5090, 3090, A100, H100 | 4090 about $0.14–$0.35 **(secondary)**; interruptible "at least 50% cheaper" **(official)** | Per second **(official)** | About $0.11/GB-month, charged while stopped **(secondary)** | Host-set rate per TB **(secondary)** | CLI and API with offer search | Varies by host |
| **Lambda Cloud** | A10 24 GB (30 vCPU), A6000 48 GB (14 vCPU), A100 40 GB (30 vCPU), GH200 96 GB, H100 80 GB (26 vCPU), B200 | A10 $1.29; A6000 $1.09; A100 40 GB $1.99; GH200 $2.59; H100 PCIe $3.79 / SXM $4.89 **(official)** | Not stated on the page | Not stated on the page | Not stated on the page | Cloud API: launch/terminate | Minutes (VM boot) **(secondary)**; capacity often limited |
| **Modal** | T4, L4 24 GB, A10 24 GB, L40S 48 GB, A100 40/80 GB, H100, H200, B200 | L4 $0.80; A10 $1.10; L40S $1.95; A100 40 GB $2.10; A100 80 GB $2.50; H100 $3.95 (derived from per-second rates); CPU $0.047 per physical core-hour; memory $0.008/GiB-hour **(official)** | Per second; $30/month free credit on Starter; region pinning ×1.15–1.75 **(official)** | Volumes $0.09/GiB-month, 1 TiB free **(official)** | $0.04/GiB **(official)** | Python SDK: functions, `spawn`, scale to zero | About 2–4 s container start, plus model load **(secondary)** |
| **Replicate** | T4, L40S 48 GB, A100 80 GB, H100 | L40S $3.51; A100 $5.04; H100 $5.49. FLUX: schnell about $0.003, dev $0.025, 1.1-pro $0.04 per image **(official)** | Per second. Private models are billed for all online time, including idle **(official)** | n/a | n/a | HTTP API | Public models are warm; private models cold |
| **fal.ai** | Hosted models; custom H100 / RTX PRO 6000 | FLUX schnell $0.003/MP; dev $0.025/MP; dev + LoRA $0.035/MP. Kling 2.5 Turbo/2.6 Pro image-to-video $0.07 per second of output; Kling v3 $0.14/s. H100 $4.50/h list **(official)** | Per output | n/a | n/a | HTTP API / queue | Hosted: warm |
| **AWS EC2 G-family** | g5 A10G 24 GB; g6 L4 24 GB (g6.xlarge 4 vCPU … g6.16xlarge 64 vCPU, **official**); g6e L40S 48 GB | us-east-1 on-demand: g5.xlarge $1.006, g6.xlarge $0.805, g6e.xlarge $1.861. Spot: g6.xlarge about $0.35–0.37, g5.xlarge about $0.43, g6e.xlarge $0.87–1.83 **(secondary)** | Per second (Linux, 60 s minimum) | EBS gp3 about $0.08/GB-month **(not re-verified)** | $0.09/GB after 100 GB/month free; S3 in the same region free **(secondary)** | EC2 API / boto3, launch templates, Terraform | 1–3 min boot plus image pull **(estimate)** |
| **Google Cloud** | g2-standard-4 L4 24 GB (4 vCPU) | $0.707 on-demand (us-central1) **(official)**; spot about $0.28 **(official table, column read by inference)**; a tracker shows $0.62 **(secondary)** | Per second (1 min minimum) | PD extra | Internet egress extra **(not re-verified)** | gcloud / API | 1–3 min **(estimate)** |
| **DigitalOcean GPU Droplets** | RTX 4000 Ada 20 GB (8 vCPU); L40S 48 GB | $0.76; $1.57 **(official page via search)** | Per second with a 5-minute minimum **(secondary, unverified)** | Droplet disk included | Bundled transfer | API / `doctl` | Minutes |
| **Salad** | RTX 5090 32 GB, 4090 24 GB, 3090 24 GB (consumer) | 4090 $0.16–$0.44 by priority; 5090 $0.25–$0.60 **(official)** | Per second while running; image download free **(official)** | n/a | Not stated | Container-group API | Minutes (image pull to consumer nodes); nodes can disconnect |
| **Paperspace** | Now part of DigitalOcean | Not evaluated separately | | | | | |

### 3.2 Suitability

| Provider | (a) Image generation (FLUX/SDXL, LoRA) | (b) Video models | (c) CPU-heavy rendering |
|---|---|---|---|
| RunPod pods | **Good.** A 4090 runs FLUX.1-dev FP8 in about 4.6 s per 1024² image at 28 steps; FP16 about 6.2 s at 30 steps **(secondary benchmarks)**. Network volume keeps weights between pods | 4090: Wan 2.2 TI2V-5B about 9 min per 5 s 720p clip **(secondary)**. 14B models want 48–80 GB | Fair. vCPU count depends on the host and is shown per offer (not verified) |
| RunPod Serverless | Good for bursty inference. It has its own queue, so it fits a handler model rather than our pull worker | Possible on 48–80 GB tiers | Poor (not its purpose) |
| Vast.ai | Cheapest. Hosts are unvetted, so never send secrets; reliability varies | As RunPod | Varies |
| Lambda | Good, but no 24 GB consumer cards; A10 at $1.29 | A100/H100 | **Good**: A10 instance has 30 vCPU |
| Modal | **Good**, simplest scale-to-zero. L4 is about 1.5–2× slower than a 4090 for FLUX **(secondary, rough)** | L40S/A100/H100 per second | **Good** for burst CPU: about $0.63/h for 16 vCPU + 32 GiB **(estimate from official rates)** |
| Replicate / fal.ai | **Best for low volume**: no ops. FLUX dev with LoRA is $0.035 per image on fal | **Best at our volume**: Kling $0.35–$0.70 per 5 s clip | n/a |
| AWS g6/g6e | Good. g6.4xlarge gives an L4 with 16 vCPU | g6e (L40S 48 GB) | Good, but CPU-only spot instances are far cheaper for rendering |
| GCP g2 | Good; L4 | g2 / A2 | As AWS |
| DigitalOcean | Adequate; RTX 4000 Ada is a smaller card | L40S | 8 vCPU |
| Salad | Cheap for stateless batch inference; nodes are consumer PCs | Limited | CPU-only groups are very cheap but interruptible |

---

## 4. CPU render workers on demand (long-form)

**Measured basis:** about 0.075 s per 1080×1920 frame on the desktop PC, per render process. A 6-minute episode is 10,800 frames, which is about 13.5 minutes in one process. The 4 vCPU VPS takes an estimated 25–30 minutes (`LONG-FORM-PLAN.md` §2).

Long-form already renders as independent segments of at most 60 s (D-L2 A), so segments parallelise across cores and machines.

**Model (estimate):**
- A 16 vCPU instance runs about 6 segment processes at once. Each segment is about 1,800 frames, assuming 2 vCPU per process (Node plus FFmpeg).
- Cloud vCPUs are assumed about 1.5–2× slower per process than the desktop. One segment then takes about 3.5–4.5 minutes.
- Add boot and image pull (about 3 minutes), plus S3 transfer and the final concat (about 2 minutes).
- That gives **about 10–12 billed minutes per episode** on one 16 vCPU instance.

| Option | Price per hour | Billing | Per 6 min episode (estimate) | 8 episodes, each rendered twice (revisions) |
|---|---|---|---|---|
| Existing VPS (4 vCPU) | $0 extra | n/a | $0, about 25–30 min wall | $0, about 8 h of VPS time |
| AWS `c7i.4xlarge` spot (16 vCPU, 32 GiB) | about $0.25–$0.27 **(secondary)** | Per second | **about $0.05** | about $0.80 |
| AWS `c7a.4xlarge` on-demand (16 vCPU) | $0.821 **(secondary)** | Per second | about $0.16 | about $2.60 |
| Hetzner CCX43 (16 dedicated vCPU) | about €0.44 after the 2026 increases **(secondary)** | Hourly | about €0.44 (1 h minimum) | about €7 |
| Modal CPU (8 physical cores = 16 vCPU, 32 GiB) | about $0.63 **(estimate from official rates)** | Per second | about $0.12 | about $2 |
| Salad CPU-only (16 vCPU, 32 GB) | about $0.11 **(estimate from official rates)** | Per second | about $0.02 | negligible; nodes are interruptible consumer PCs |

**Takeaway.** CPU burst rendering costs under $3 a month at any reasonable volume. Its value is **turnaround**: an episode in about 10 minutes instead of 30, without blocking Shorts on the VPS. AWS spot in the same region as the S3 bucket is preferred because S3 transfer in the same region is free, billing is per second, and Terraform/IAM are mature. A spot interruption costs only one segment, which is retried alone.

**Still to measure:** peak memory of a 60 s segment render, and real throughput per vCPU on a cloud instance (planned in long-form phase "Test").

---

## 5. Recommendation

### 5.1 Primary: RunPod on-demand pods, Secure Cloud, RTX 4090 24 GB

- **Spec:**
  - RTX 4090 with 24 GB VRAM; $0.89/h **(official)**, billed per second.
  - Our own worker image, pinned by digest, launched by API per batch of GPU jobs and terminated when idle.
  - A 50–60 GB network volume holds FLUX/SDXL weights and LoRAs: about $3.50–$4.20/month **(official rate, estimate size)**.
- **Why:**
  1. The cheapest 24 GB card with published FLUX throughput, enough for FLUX.1-dev FP8, SDXL and LoRA training.
  2. Pods run any Docker image, so the remote worker is the same Python worker with a different capability. Serverless would instead need a separate handler model.
  3. Billing is per second, with no idle cost after termination.
  4. The account is prepaid, so the balance is a provider-side hard stop.
  5. Secure Cloud, not Community, because job inputs and outputs pass through the host.
- **When to use L40S 48 GB ($1.09/h) instead:** only if the owner later approves self-hosted 14B video models.

### 5.2 Fallback: Modal

- L4 24 GB at $0.80/h, or L40S 48 GB at $1.95/h. Per second, scale to zero, cold start in seconds, and $30/month free credit **(official)**. At our volume, the credit alone may cover the GPU work.
- **Drawbacks:**
  - Modal-specific Python deployment.
  - $0.04/GiB egress.
  - Region pinning costs extra.
  - Slower per image on L4 than on a 4090.
- Modal is also a reasonable single-provider choice for **both** CPU burst and GPU, if the owner prefers one vendor over AWS + RunPod.

### 5.3 Video clips

Use hosted APIs (fal.ai Kling, $0.07 per second of output **(official)**, so about $0.35 per 5 s clip). Self-hosting Wan-class models costs minutes of 48–80 GB GPU per clip **(secondary, widely varying figures)**, plus model engineering. That does not pay off below hundreds of clips a month.

### 5.4 Monthly cost scenario (estimate)

**Assumptions:**
- 30 Shorts on the VPS, as today.
- 6 long episodes, each rendered about twice (revisions), on spot CPU.
- 4 new characters × 8 images × 2 rounds = 64 images.
- Optional per-character LoRA training.

| Item | Basis | Per month |
|---|---|---|
| Shorts rendering | Existing VPS | $0 |
| Long-form burst CPU | 12 runs × about $0.05–$0.16 | $1–$2 |
| Character images, today's path (OpenAI gpt-image-1) | 64 × $0.042 medium / $0.167 high **(official)** | $3–$11 |
| *or* character images, self-hosted 4090 | 64 × about 6 s, plus about 5 min model load × 4 sessions, at $0.89/h | about $0.50 |
| LoRA training (optional) | 4 × about 30 min at $0.89/h **(estimate; not benchmarked)** | about $2 |
| RunPod network volume (weights) | 60 GB × $0.07 | $4.20 |
| S3 media | About 20 GB × $0.023 **(secondary)**; viewing egress within the 100 GB free tier | about $0.50 |
| Spot/idle overhead and failed runs | +50% buffer on compute | $2–$3 |
| **Subtotal (no AI video)** | | **about $10–$20** |
| AI video clips (optional) | 40 clips × 5 s × $0.07 (fal Kling) | +$14 |
| **With video experiments** | | **about $25–$45** |

Voices and writing (about $2–$5, `VOICE-AND-CASTING.md` §4) are unchanged. Everything fits in the $150/month target. The recommended **hard compute cap is $50/month** to start.

---

## 6. Integration design: replaceable on-demand workers

**Principle:** the control plane (VPS: API, Postgres, Redis, dashboard) stays the single source of truth. Remote workers are disposable. They hold no database or Redis credentials and no long-lived cloud keys, and they can disappear at any moment without losing state.

### 6.1 How a remote worker reaches the queue

| Option | Security | Fit |
|---|---|---|
| A. Postgres + Redis over a WireGuard tunnel (as the workstation worker in `DEPLOYMENT.md` §7) | Full database credentials on a third-party host; a compromised worker can read or alter all workflow state | Reuses `worker.py` unchanged, but the blast radius is too large for rented hosts. Also, unprivileged containers (RunPod, Modal) usually cannot create a kernel WireGuard interface |
| B. **Narrow worker API** (`/api/worker/*`) on the control plane | The worker can only claim jobs of its capability, heartbeat, upload through presigned URLs and complete its **own** attempt; the token is per worker and short-lived | **Recommended contract.** It needs a network path to the API |
| C. Managed queue relay (AWS SQS) | No inbound port on the VPS at all: the dispatcher pushes job envelopes to SQS, and the worker sends events back over SQS | Most locked-down, but adds moving parts and an AWS dependency |

**Recommendation: B, the narrow worker API.** The transport depends on the deployment's "nothing public" rule:
- **Now** (private deployment): expose *only* the worker API on the VPS's WireGuard address, through one UDP port. WireGuard does not answer unauthenticated packets.
  - Each launched worker gets its own WireGuard peer key, created at launch and removed at teardown.
  - Containers without TUN use a userspace client, for example `wireproxy` or `wireguard-go` with netstack. Its fitness on RunPod and Modal is **not verified** and needs a test.
  - EC2 uses kernel WireGuard.
  - Firewall rules allow tunnel peers to reach only the worker API port, never Postgres (5432) or Redis (6379).
- **Later**, if going public is approved (`DEPLOYMENT.md` §8): serve the same API over TLS on its own hostname, keeping token auth and rate limits. Option C remains available if the owner wants zero inbound exposure.

**Worker API (sketch):**
- `POST /api/worker/claim {capabilities, worker_id}` → `{job, attempt, lease_seconds, inputs: [presigned GET], outputs: [presigned PUT]}`, or 204 when nothing is queued.
- `POST /api/worker/jobs/{id}/heartbeat {attempt, progress, log_tail}`, which extends the lease.
- `POST /api/worker/jobs/{id}/complete {attempt, result, timings}`, or `/fail {attempt, error, retryable}`.
- **Auth:** an HMAC-signed bearer token bound to `worker_id`, the capability set and an expiry (the instance's maximum lifetime), minted by the provisioner and passed in at launch.
- **Writes:** the API refuses a heartbeat or completion whose `(job_id, attempt, worker_id)` does not match the current claim.

### 6.2 Capability routing

- New nullable column `jobs.capability` (additive migration). Existing kinds keep `NULL` and the existing list `oddstudio:jobs`, so the local worker and the Shorts path are **unchanged**.
- New Redis lists carry IDs for the provisioner's queue-depth view: `oddstudio:jobs:cpu-render` (long-form segment render), `oddstudio:jobs:gpu-image` (self-hosted pose/sheet, LoRA training), and later `oddstudio:jobs:gpu-video`.
- The claim itself is the existing conditional `UPDATE … WHERE status='queued'` plus `capability IN (…)`, so a job delivered twice still runs once. Postgres stays authoritative, and Redis remains a hint.
- The image provider setting picks the route. `openai`/`codex-cli` stay local; a new `selfhosted-flux` enqueues to `gpu-image`.

### 6.3 Storage (S3) with scoped access

- Workers never receive AWS keys. Each claim returns presigned GET URLs for inputs (for example the approved neutral pose, or the segment story bundle) and presigned PUT URLs for outputs. Output keys are attempt-scoped, such as `…/job{id}-a{attempt}/…`, valid for the lease lifetime plus margin.
- **EC2 alternative:** an instance profile limited to `s3:GetObject`/`PutObject` on the job prefix.
- Completion records the sha256 of each output, and the control plane verifies it before creating the `Asset` rows. The same `store_asset` path is used, so the dashboard sees the same assets as today.
- Bucket: versioning and lifecycle rules (`DEPLOYMENT.md` §4). Workers and buckets live in the same region where possible, so transfer is free.

### 6.4 Heartbeats, timeouts and lost workers

- **Heartbeat** every 20 s; lease 90 s. A **reaper** on the control plane marks a running job whose lease has expired as `failed` with "The remote worker stopped responding (provider, instance). Retry it." This is the same outcome `recover()` gives today.
- **Required change:** `queue.recover()` currently fails *every* running job when the local worker starts. It must be limited to jobs claimed by the local worker (new `jobs.worker_id`). Otherwise restarting the VPS worker would fail healthy remote jobs.
- **Per-kind execution timeout**, for example 30 min for a segment and 20 min for an image batch, enforced by the worker and backstopped by the reaper.
- **Spot interruption** (EC2 sends a 2-minute notice): the worker fails the job with `retryable=true, reason=interrupted`.

### 6.5 Failure and retry semantics

- These match today's model: **each failed job is retried individually from the dashboard**, the error and log are kept, and a long-form segment retry re-renders only that segment (D-L2).
- **Optional owner decision:** automatically re-queue once when the cause is infrastructure (spot interruption, lost worker), never for content or provider errors. The attempt count shows it.
- Late completions from a worker whose lease was reaped are refused by the attempt check, so a job never ends up with two results.

### 6.6 Cost tracking per job

- The provisioner records each instance: provider, type, GPU, price per hour at launch (from the provider API or a configured table), and launch/terminate times.
- The worker reports `started_at`/`finished_at` per job.
- The control plane writes into `job.result["compute"]`: `{provider, instance_type, gpu, price_per_hour, billed_seconds, cost_usd, estimate: true}`. During the run, `job.progress["compute"]` shows the running cost. Boot and idle time are recorded per instance and shown on the dashboard as "overhead".
- Dashboard: cost per job, per episode (sum of its jobs) and month-to-date against the cap.
- **Monthly reconciliation** with provider billing (RunPod balance and spend via its API; AWS Cost Explorer, which lags about a day). The reconciled figure replaces `estimate: true`.

### 6.7 Provisioning lifecycle

A small **provisioner** loop runs on the control plane (inside the API container, or its own container) every 30 s, for each capability:
1. **Scale up:** when the queued depth is above 0, live workers are below that capability's maximum (start with 1 GPU, 1–2 CPU), and the spend guard allows it, launch one instance. Launches go through the provider API (RunPod REST, EC2 `RunInstances` from a launch template) with the worker image digest, token and WireGuard peer.
2. **Idle shutdown:** the worker exits after **N = 5 minutes** without a claim. The provisioner then **terminates** it (not "stops": stopped RunPod volumes and Vast instances still bill storage).
3. **Hard limits:**
   - Every instance has a maximum lifetime (for example 2 h). EC2 also uses `shutdown -h +120` with terminate-on-shutdown.
   - The provisioner terminates anything it does not have recorded, so no orphans remain.
4. **Spend guard:** no launch when month-to-date plus the projected cost (price × maximum lifetime) exceeds the **monthly cap**. At 80% the dashboard warns; at 100% queued remote jobs wait, shown as "Paused: monthly compute cap reached".
   - **Provider-side backstops:** RunPod prepaid balance with auto-top-up off; AWS Budgets alert, with an optional action that denies `RunInstances`.
5. **Infrastructure as code:** static resources go in **Terraform**: S3 bucket and policies, IAM roles, EC2 launch template, security groups, WireGuard config on the VPS. Per-job instances are created by the provisioner through the API, not by Terraform.

### 6.8 What stays unchanged

- The Shorts workflow, approval gates, the local worker on the VPS, `oddstudio:jobs`, the existing job kinds and the engine/renderer CLIs.
- Remote capability is opt-in per job kind. With no provider configured, the new kinds fail with a clear "Not configured" message, as other providers do today.

---

## 7. Security notes (DevSecOps)

- **No secrets on rented hosts beyond a short-lived worker token.** GPU and CPU render jobs do not need OpenAI, ElevenLabs or YouTube keys. Keep provider API calls on the control plane.
- **No Community Cloud or Vast/Salad consumer hosts** for jobs with unreleased content, unless the owner accepts that risk. Prefer Secure Cloud / EC2.
- Worker images are built in CI, pinned by digest and scanned. They run as non-root with no inbound ports.
- The token is revoked and the WireGuard peer removed at teardown. Tokens expire with the instance's maximum lifetime.
- The worker API validates every field, takes storage keys only from the server (`check_key`), and rate-limits claims.
- Model weights come only from pinned sources with checksums. Licences must be checked: FLUX.1-dev is non-commercial unless licensed. FLUX.1-schnell (Apache-2.0) and SDXL (OpenRAIL++) allow commercial use. **This affects a monetised channel.**

---

## 8. Owner decisions and approvals needed

**Decisions:**
1. **Is a GPU wanted at all now?** The alternative is to stay on hosted image APIs and revisit when character-consistency work starts. *Recommendation:* approve the CPU burst path first; approve GPU only with the self-hosted image decision.
2. **GPU provider:** RunPod Secure Cloud (primary) or Modal (fallback / single-vendor option).
3. **GPU type:** RTX 4090 24 GB (images, LoRA). L40S 48 GB only if self-hosted video is wanted.
4. **CPU burst provider:** AWS EC2 spot in the S3 region (recommended), Modal, or stay on the VPS.
5. **Monthly hard cap for remote compute** (recommended **$50**), the warning threshold (80%) and the per-capability maximum number of instances.
6. **Image model and licence:** FLUX.1-schnell / SDXL (commercial use allowed), or a FLUX.1-dev commercial licence.
7. **Transport:** WireGuard to the worker API now (opens one UDP port on the VPS), or SQS relay (no inbound port).
8. **Retry policy:** dashboard-only retries (as today), or one automatic re-queue for infrastructure failures only.
9. **AI video:** whether to try hosted image-to-video (fal.ai Kling), and its share of the cap.

**Approvals before any paid resource is created** (each separately, in writing):
- Creating accounts with the chosen providers and adding a payment method or prepaid balance (RunPod: amount of the first top-up, auto-top-up **off**).
- Creating the S3 bucket and IAM roles (Terraform plan reviewed first).
- Opening the WireGuard UDP port on the VPS (changes "only SSH is listening").
- The first test launch of each instance type (expected cost under $1 each), to measure real FLUX throughput, segment render time and memory.
- Enabling the provisioner in production with the approved cap.

---

## 9. Figures not verified

- RunPod egress (believed free; not on the pricing page) and vCPU count per 4090 pod.
- Lambda billing granularity, storage and egress pricing (not on the pricing page).
- Vast.ai prices, storage and bandwidth (live marketplace; secondary sources only).
- AWS EC2 spot/on-demand rates and S3/egress rates (third-party trackers; consistent with each other, not re-checked on aws.amazon.com).
- GCP g2 spot rate (official table column read by inference; a tracker disagrees).
- DigitalOcean per-second billing and 5-minute minimum.
- Hetzner post-increase hourly rates (secondary).
- FLUX throughput per GPU, and the L4 figure in particular (benchmarks disagree by about 2×). Wan video timings (sources range from under 1 min to about 20 min per clip).
- LoRA training time per character, cloud render throughput per vCPU and segment memory: **to be measured** in the approved test launch.

---

## 10. Sources (checked 2026-11-16)

**Official:**
- RunPod pricing: https://www.runpod.io/pricing
- RunPod serverless billing: https://docs.runpod.io/serverless/pricing
- Modal pricing: https://modal.com/pricing
- Lambda pricing: https://lambda.com/pricing (redirect from lambda.ai/pricing)
- Replicate pricing: https://replicate.com/pricing
- fal.ai pricing: https://fal.ai/pricing
- Vast.ai pricing (billing model only; live prices did not load): https://vast.ai/pricing
- Salad pricing: https://salad.com/pricing
- AWS G6 instance specs: https://aws.amazon.com/ec2/instance-types/g6/
- Google Cloud accelerator-optimized pricing: https://cloud.google.com/products/compute/pricing/accelerator-optimized
- DigitalOcean GPU Droplets pricing: https://digitalocean.com/pricing/gpu-droplets
- OpenAI gpt-image-1 model page: https://developers.openai.com/api/docs/models/gpt-image-1
- Hetzner price adjustment notice: https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/
- RunPod FlashBoot: https://www.runpod.io/blog/introducing-flashboot-serverless-cold-start

**Secondary:**
- AWS g6/g5/g6e on-demand and spot: https://compute.doit.com/spot/us-east-1/g6.xlarge, https://compute.doit.com/spot/us-east-1/g5.xlarge, https://compute.doit.com/spot/us-east-1/g6e.xlarge
- AWS c7i/c7a spot: https://calculator.holori.com/aws/ec2/c7i.4xlarge/us-east-1, https://aws-pricing.com/c7a.4xlarge.html
- AWS egress and S3 rates: https://www.cloudzero.com/blog/aws-egress-costs, https://infratally.com/articles/aws-s3-pricing-explained-2026/
- GCP g2 spot: https://gcloud-compute.com/g2-standard-4.html, https://calculator.holori.com/gcp/vm/g2-standard-4
- Vast.ai prices and fees: https://www.activepieces.com/blog/vast-ai-gpu-pricing-per-hour-in-2026-and-extra-fees.md, https://computeprices.com/providers/vast/gpus/rtx4090
- Hetzner 2026 prices: https://spendark.com/instances/ccx43/, https://www.bitdoze.com/hetzner-cloud-cost-optimized-plans/
- FLUX throughput: https://www.spheron.network/blog/best-gpu-ai-image-generation-2026/, https://gigagpu.com/rtx-4090-24gb-flux-dev-benchmark/, https://jarvislabs.ai/ai-faqs/best-gpu-for-stable-diffusion
- Wan 2.2 video timings: https://www.spheron.network/blog/image-to-video-gpu-cloud-ltx-wan-hunyuan/, https://github.com/ac4k/Wan2.2, https://instasd.com/post/wan2-1-performance-testing-across-gpus
- Serverless cold starts: https://blog.premai.io/serverless-llm-deployment-runpod-vs-modal-vs-lambda-2026, https://www.runpod.io/blog/serverless-gpu-cold-starts-flashboot
- DigitalOcean billing granularity: https://computeprices.com/providers/digitalocean/gpus/rtx4000ada

**Internal:** `studio-app/README.md`, `docs/DEPLOYMENT.md`, `docs/LONG-FORM-PLAN.md` (measured render times), `docs/VOICE-AND-CASTING.md` (API costs), `api/oddstudio/queue.py`, `worker.py`, `tasks.py`, `storage.py`, `providers.py`.
