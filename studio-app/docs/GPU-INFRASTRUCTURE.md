# GPU and on-demand worker infrastructure: research and recommendation

**Status (2026-11-16; hard requirements added 2026-11-21, §11–§13; self-hosted video investigation added 2026-11-21, §14–§18): RESEARCH AND PROPOSAL ONLY.** Nothing has been signed up for, bought or provisioned. No paid resource may be created until the owner approves the decisions in §8. The Shorts workflow, the local CPU worker and the existing job queue stay as they are.

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

> **Superseded for GPU work by §11.2:** Modal cannot run our plain Docker worker image without its own deployment code. The portable fallback is AWS EC2 g6e or Lambda.

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

> **For GPU work this is replaced by §11.2:** the studio calls an HTTP job API on the worker, so no inbound port is needed. The pull design below remains the proposal for CPU long-form segments.

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

**Further decisions from the hard requirements are in §13.**

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

---

## 11. Hard requirements (owner, 2026-11-21)

These three requirements are binding on any GPU design. Where they conflict with §5 or §6, this section wins. It is still a proposal: nothing is built, bought or provisioned.

### 11.1 Pay-per-use only

**Rule:** nothing GPU-related may bill while no job is running, apart from the few minutes of boot and idle tail described below.

**What this rules out:**
- always-on pods or VMs, reserved or committed instances and savings plans;
- RunPod Serverless "active" (minimum) workers, and any setting that keeps a warm worker;
- a RunPod network volume or a stopped pod with a volume, because storage bills while idle ($0.07–0.20/GB-month, §3.1). Weights are therefore not kept on rented storage between sessions (§11.2, "Weights").

**What is allowed:** RunPod Secure Cloud pods, billed per second **(official)**, created for a batch of jobs and **terminated** (not stopped) afterwards. Other per-second hosts that run a Docker image (AWS EC2 g6/g6e, Lambda, Vast.ai) remain options.

**Overhead per session (estimate):** boot, image pull and weights download take about 5–10 min, and the idle tail is 5 min. On an L40S at $1.09/h that is about **$0.20–0.30 per session**. Queued GPU jobs therefore run together in one session wherever possible.

**The monthly spend cap (in the studio):**
- **Setting:** Settings > GPU worker, `monthly_cap_usd`, default **$50** (the §5.4 recommendation). A warning shows at 80%.
- **Ledger:** every rented session is recorded: provider, pod ID, GPU type, the price per hour at launch, launch and terminate times, and its cost. Cost accrues from launch, not from the first job, so boot and idle time count. Month-to-date spend is the sum. The pattern is the same as the existing fal.ai ledger (`fal.py`: `check_budget` / `reserve`), but this is a separate cap. Whether fal.ai spend should count against the same cap is an owner decision (§11.5).
- **Before a launch:** the studio reserves price × maximum lifetime (for example $1.09 × 2 h = $2.18). If month-to-date plus that reservation would pass the cap, nothing is launched. Queued GPU jobs show "Paused: monthly GPU cap reached" and wait. They are not failed. Because of the reservation, a session cannot push spend past the cap.
- **During a session:** every 30 s the running cost is added to month-to-date. If the total reaches the cap, the running job is cancelled with "Stopped: monthly GPU cap reached. Retry it after raising the cap or next month", and the pod is terminated.
- **Reconciliation:** each month, the ledger is checked against the provider's own billing, which replaces the estimate (§6.6).
- **Provider-side backstop:** a prepaid RunPod balance with auto-top-up **off**. This is the hard limit if the studio itself fails.

**Automatic idle shutdown.** There are four layers, and each works if the one above it fails:

| Layer | What it does | Default |
|---|---|---|
| 1. Studio idle timer | Terminates the pod once no GPU job has run or been queued for N minutes | 5 min |
| 2. Studio maximum lifetime | Terminates the pod after this many minutes, busy or not. A job cut off is failed and can be retried | 120 min |
| 3. Orphan sweep | Runs when the studio worker starts and every 5 min. It lists the account's pods through the provider API and terminates any pod that is not in the ledger, past its lifetime, or belongs to a session already marked ended. Pod IDs are stored in Postgres, so this survives a studio restart | always on |
| 4. Worker self-limit | The worker refuses new jobs after its own lifetime or idle limit and reports "expired" on `/health`. It **cannot stop billing by itself**: stopping a pod from inside needs a credential, and how that works is still unknown (AP-84B3 runbook, U1). No account-level API key is ever placed on the pod | lifetime + 10 min |

The studio holds the only RunPod API key. It is kept in the secrets store and never sent to the worker.

### 11.2 Portable worker: a plain Docker image with an HTTP job API

**Image.** `oddstudio-gpu-worker`, a standard OCI image pinned by digest. It holds a CUDA runtime base, ComfyUI with pinned custom nodes, and a small HTTP server. There is nothing provider-specific in the image. It runs anywhere with an NVIDIA driver and the NVIDIA Container Toolkit:

```
docker run --gpus all -p 8000:8000 -e WORKER_TOKEN=… -v /models:/models oddstudio-gpu-worker@sha256:…
```

**The job API.** The studio calls the worker; the worker never calls the studio.

| Call | Purpose |
|---|---|
| `GET /health` | Version, image digest, GPU and VRAM, loaded models, busy/idle, seconds left before its self-limit |
| `POST /jobs` (multipart: `job.json` plus input files) | Starts a job and returns 202 with `{id}`. The studio's job ID and attempt number form an idempotency key, so a repeated submit does not run twice |
| `GET /jobs/{id}` | Status, progress, log tail, start and finish times, and each output's name, size and SHA-256 |
| `GET /jobs/{id}/outputs/{name}` | Downloads one output. The studio checks its SHA-256 before creating the `Asset` row |
| `POST /jobs/{id}/cancel` | Cancels the job |
| `DELETE /jobs/{id}` | Deletes the job's files on the worker once the studio has its outputs |

- A job is a ComfyUI workflow (JSON, hash recorded) plus its inputs and parameters. Starting with `comfyui-workflow`, the kind is general, so new models need a new workflow and weights, not new API calls.
- The worker runs one job at a time and keeps only in-memory state. The studio's Postgres stays the source of truth. If the worker disappears, only the running job is lost, and it is retried from the dashboard as today (§6.5).
- **Auth:** a bearer token. For a rented pod, the studio generates a random token per session and passes it as an environment variable at launch. For our own machine, the token is a secret in Settings. Every field is validated, uploads are size-limited, and output names come only from the worker's own records.
- **Transport:** HTTPS only. A RunPod pod's HTTP port is reached through RunPod's HTTPS proxy, `https://<pod id>-8000.proxy.runpod.net` **(secondary; to be confirmed)**. Because the API is asynchronous (a submit returns at once, then status is polled), the proxy's request timeout (about 100 s, **secondary**) does not matter.
- **No storage dependency:** inputs travel in the request, and outputs are fetched by the studio. S3 is not needed, so the S3 hold does not block this.

**One address in Settings.** A new "GPU worker" section replaces today's `comfyui.url` (`settings_store.py`; today only a connection test):

| Setting | Rented | Own machine |
|---|---|---|
| `mode` | `rented` | `own` |
| `worker_url` | Filled in by the studio for each session, shown read-only | **The one address to change**, e.g. `https://gpu.example.internal:8000` |
| `token` | Generated per session | A secret in Settings |
| Provider, GPU type, image digest | RunPod, L40S or 4090, the pinned digest | Not used |
| Cap, idle timer, maximum lifetime | Apply | Do not apply, since no rental is billed. Electricity can be recorded as an optional estimate |

Moving from rental to our own machine is then: run the same image on the machine, set `mode: own` and `worker_url`. Nothing else in the studio changes.

**Our own machine needs a network path.** The VPS must reach the worker. Behind a home or office router, that means the machine opens an outbound tunnel (WireGuard to the VPS, or a similar tunnel), so no port is opened at home. Which tunnel is an owner decision when the machine exists.

**Weights.** Weights are not baked into the image (Qwen-Image-Edit alone is about 40 GB at BF16, **estimate**), and not kept on rented storage (§11.1). At boot, the worker downloads them from Hugging Face, pinned by revision and checked against SHA-256, from the same kind of manifest AP-84B3-D1 already uses. On our own machine `/models` is a local folder, filled once.

**This changes earlier sections:**
- §6.1 (remote workers pull jobs over WireGuard) no longer applies to GPU work. The studio makes **outbound** HTTPS calls only, so the VPS opens no port for rented GPUs, and decision 7 in §8 becomes moot for GPU. The pull design in §6.1–§6.4 remains the proposal for CPU long-form segments only.
- §5.2 (Modal as fallback): Modal does not run a plain Docker image with an exposed port in the same way. It needs its own Python deployment, which is lock-in. The portable fallback is AWS EC2 **g6e** (L40S 48 GB, per second, about $1.86/h on demand, **secondary**) or Lambda. Modal stays possible only behind a separate adapter.
- RunPod Serverless stays excluded: its handler and queue model is RunPod-specific.

### 11.3 Where lock-in remains

| Item | Lock-in | Effort to switch |
|---|---|---|
| Launch, list and terminate pods; price lookup | **RunPod-specific.** It sits in one small provider adapter in the studio (`create`, `status`, `terminate`, `list`, `price`) | One new adapter per provider. AWS, Lambda and Vast.ai all have equivalent APIs |
| Reaching the pod | RunPod's proxy URL format | The adapter returns the URL. Other hosts give a public IP or their own proxy |
| Billing reconciliation | Each provider's billing API or console | Per provider; manual entry is the fallback |
| Prepaid balance as the hard backstop | RunPod's prepaid model | AWS has no prepaid balance. Use AWS Budgets with an action that denies `RunInstances` |
| CUDA and driver version | The image needs a host driver new enough for its CUDA version | Generic: true of any NVIDIA host, including our own |
| Image, job API, workflows, weights | **None.** OCI image, our own API, ComfyUI JSON, Hugging Face files | n/a |

### 11.4 Which card class runs the chosen models

The models come from the owner-approved AP-84B3-D1 experiment (Qwen-Image-Edit-2511 primary, SDXL 1.0 baseline) and from §2 and §5 of this report (FLUX for self-hosted images, LoRA training, Wan 2.2 if video is ever self-hosted). VRAM needs are **estimates** from published model sizes and the benchmarks in §3.2; they are to be measured in the first approved test.

| Model | 24 GB (RTX 4090) | 32 GB (RTX 5090) | 48 GB (L40S, A40) | Note |
|---|---|---|---|---|
| SDXL 1.0 + LoRA training | Yes | Yes | Yes | 12–16 GB is enough for inference |
| FLUX.1 schnell / dev (FP8) + LoRA training | Yes | Yes | Yes | FP16 dev is tight on 24 GB |
| Qwen-Image-Edit-2511, BF16 (as approved in D1-4) | No | No | **Yes** | The reason D1-4 chose L40S, with A40 as fallback |
| Qwen-Image-Edit-2511, FP8 or GGUF quantised | Possibly | Likely | Yes | Quality after quantisation is **not tested** |
| Wan 2.2 TI2V-5B (video) | Yes, slow (about 9 min per 5 s clip, **secondary**) | Yes | Yes | Hosted Kling is cheaper at our volume (§5.3) |
| Wan 2.2 14B (video) | No | No | Tight; 80 GB preferred | Not planned |

**Conclusion:** the 48 GB class (L40S) is needed only for Qwen-Image-Edit at full precision. Everything else runs on a 24–32 GB card. If quantised Qwen-Image-Edit proves good enough in the test, a 32 GB card covers every chosen model.

---

## 12. When buying our own GPU makes sense

**Prices checked 2026-11-21; all secondary (retailer listings and trackers), and moving fast because of AI demand and memory shortages:**
- RTX 4090 24 GB: no longer made; used about $2,100–2,600.
- RTX 5090 32 GB: launch price $1,999, but US listings are mostly about $3,300–7,700.
- L40S 48 GB: about $6,200–10,000 per card. It is passively cooled, so it needs a server chassis.
- RTX PRO 6000 Blackwell 96 GB: about $13,250–16,000. Far beyond our needs.

**Assumptions (estimate):**
- **24–32 GB machine:** a used 4090 plus a host PC (CPU, 64 GB RAM, 1,000 W power supply, 2 TB SSD), about $1,500 → about **$4,000** in total.
- **48 GB machine:** an L40S plus a server chassis, about $3,000 → about **$11,000**.
- **Written off over 36 months:** about $111/month and $306/month.
- **Power:** about 0.6 kW under load at $0.20/kWh → about $0.12 per GPU-hour.
- **Rental comparison:** RunPod Secure Cloud at $0.89/h (4090) and $1.09/h (L40S) (§3.1).
- **Not counted:** our own time for setup and maintenance, repairs, internet and the tunnel. All of these favour renting.

**24–32 GB class (owning about $111/month plus $0.12 per GPU-hour, against renting a 4090 at $0.89/h):**

| Monthly rental spend | GPU-hours it buys | Owning would cost | Cheaper |
|---|---|---|---|
| $10 | 11 | about $112 | Rent, by about $100 |
| $25 | 28 | about $114 | Rent, by about $90 |
| $50 (our cap) | 56 | about $118 | Rent, by about $70 |
| $100 | 112 | about $124 | Rent, by about $25 |
| **about $128** | **about 144 (about 5 h a day)** | **about $128** | **Break-even** |
| $150 | 169 | about $131 | Own, by about $20 |
| $300 | 337 | about $151 | Own, by about $150 |

**48 GB class (owning about $306/month plus $0.11 per GPU-hour, against renting an L40S at $1.09/h):** break-even is about **$340/month of rental, about 310 GPU-hours (10 h a day)**. That is above the whole $150/month studio target.

**When buying makes sense:**
1. GPU rental has stayed above about **$130/month for at least three months running**, in reconciled bills rather than estimates. That is over twice the proposed $50 cap and about 5 GPU-hours every day.
2. The chosen models are settled and fit a 24–32 GB card (§11.4). This means quantised Qwen-Image-Edit has passed review, or the work has moved to SDXL/FLUX.
3. Prices are near list again. At today's RTX 5090 listings ($3,300–7,700), the machine costs about $5,000–9,500 and break-even rises to about $160–305 a month of rental.

**Today:** the expected GPU spend is $10–20 a month (§5.4), far below break-even, so **renting is cheaper by about $90–100 a month**. Because of §11.2, buying later is a Settings change, not a redesign. **If we buy, the card should be an RTX 5090 32 GB near list price, or a used RTX 4090 24 GB.** Not an L40S.

## 13. Owner decisions added by §11 and §12

These are added to §8:
1. Approve the push design (§11.2), which replaces §6.1 for GPU work: the studio calls an HTTP job API on the worker, so the VPS opens no port.
2. The monthly GPU cap (recommended $50), its 80% warning, and whether fal.ai spend counts against the same cap or keeps its own experimental budget.
3. The idle timer (recommended 5 min) and the maximum lifetime (recommended 120 min).
4. Weights: download them at each boot (recommended; nothing billed while idle), or keep a network volume at about $5–6/month. The volume breaks the strict pay-per-use rule.
5. The portable fallback host: AWS g6e (recommended) or Lambda, in place of Modal.
6. Buying hardware: not now. Revisit when the §12 trigger is met.

**Sources added (checked 2026-11-21, secondary):**
- RTX 5090 prices: https://gpupoet.com/gpu/learn/price/november-2026/nvidia-geforce-rtx-5090, https://tech-insider.org/nvidia-rtx-50-prices-rise-november-2026-rtx-5090-3340/, https://www.techradar.com/computing/gpu/high-end-pc-gaming-is-in-big-trouble-thanks-to-ai-and-rtx-5090-price-hikes-are-prime-examples
- L40S prices: https://getdeploying.com/gpus/nvidia-l40s, https://www.newegg.com/p/N82E16888892001
- RTX PRO 6000 Blackwell prices: https://tech-insider.org/nvidia-rtx-pro-6000-blackwell-price-2026/, https://www.tweaktown.com/news/113098/nvidias-rtx-pro-6000-blackwell-gpu-price-almost-doubles-reaching-16-000/index.html
- Used RTX 4090 listings: https://www.ebay.com/shop/rtx-4090-gpu

---

# Part 2: Self-hosted video (investigation, 2026-11-21)

**Status: READ-ONLY INVESTIGATION.** No code, accounts or paid calls. Licences, VRAM figures and prices below were read on the providers' and model publishers' own pages on 2026-11-21 **(official)**, unless marked **(secondary)** or **(estimate)**. "Clip" means a 5-second clip throughout.

## 14. Models we could self-host

### 14.1 Image-to-video (no audio input)

| Model | Licence (official) | Size | VRAM (official) | Time per 5 s clip (official, Wan's efficiency table, 1 GPU, default steps) | Disk (estimate) |
|---|---|---|---|---|---|
| **Wan 2.2 I2V-A14B** | Apache 2.0. Commercial use allowed. The model card adds a use policy (nothing unlawful or harmful) | 27B total, 14B active per step (two experts) | "at least 80GB" for the single-GPU command. Peak measured **41.0 GB at 480p**, **59.7 GB at 720p** | H100: **328 s at 480p**, 1,056 s at 720p. A100: 810 s at 480p, 2,811 s at 720p | about 60–70 GB with the text encoder |
| **Wan 2.2 TI2V-5B** | Apache 2.0 | 5B dense | "at least 24GB VRAM (e.g, RTX 4090)". Peak 22.8 GB | RTX 4090: **525 s at 720p, 24 fps** | about 20–25 GB |
| **LTX-2** (Lightricks) | **LTX-2 Community License**, not open source. Free for any purpose, but "Entities with annual revenues of at least $10,000,000" need a paid commercial licence. Derivatives (LoRAs) must be distributed under the same licence. Lightricks claims no rights in outputs | 19B. The README now recommends LTX-2.5 (22B), which is under a **different licence file that was not read** | Not stated. FP8 and FP4 variants and CPU/disk offload exist | Not stated. A distilled variant uses 8 steps | LTX-2.5 bundle "roughly 66 GiB" (official) |

LTX-2 generates its own audio and has an audio-to-video pipeline. That pipeline is conditioned on an input audio file, but lip-sync to supplied speech is **not claimed**.

### 14.2 Audio-driven talking video (speech in, mouth follows it)

| Model | Licence (official) | Built on | Mode | VRAM (official) | Speed | Cartoon claim |
|---|---|---|---|---|---|---|
| **Wan 2.2 S2V-14B** | Apache 2.0 | Wan 2.2 (16B params listed) | Image + speech (+ optional pose video) to video; length follows the audio | "at least 80GB" for the single-GPU command. FP8 and offload via DiffSynth-Studio **(listed on the card; not Wan's own)** | Not stated. **Estimate:** similar to I2V-A14B, about 330 s per 480p clip on an H100 | Not stated |
| **InfiniteTalk** (MeiGen) | Apache 2.0 | Wan 2.1 I2V-14B-480P | Image + audio to video, **and** dubbing of an existing clip. "Unlimited" length in streaming mode; good results "for up to 1 minute" | No GB figure. Low-VRAM and FP8 modes | Not stated. Speed-ups through 4–8-step LoRAs **(third-party)** | Not stated |
| **MultiTalk** (MeiGen) | Apache 2.0 | Wan 2.1 I2V-14B-480P | Image + audio to video; several speakers; up to 15 s | 480p "on a single RTX 4090" in low-VRAM mode | Not stated; TeaCache "2~3x" faster | **Yes:** "cartoon character" |
| **OmniAvatar** | Apache 2.0 | Wan 2.1 T2V-14B or 1.3B, plus a LoRA | Image + audio + prompt to video; 480p only | 36 GB (full), 21 GB, or 8 GB (offloaded); measured on an A800 | 16.0–22.1 s per diffusion step on one A800 | Not stated |
| **HunyuanVideo-Avatar** (Tencent) | **Tencent Hunyuan Community License.** The territory **excludes the EU, UK and South Korea**. Outputs may not be used "to improve any other AI model". Over 100M monthly users needs a licence | HunyuanVideo | Image + audio to video | Minimum 24 GB "but very slow"; 96 GB recommended | Not stated | **Yes:** "cartoon, 3D-rendered, and anthropomorphic" |
| **LatentSync 1.6** (ByteDance) | Apache 2.0 | Stable Diffusion | **Video-to-video** lip-sync on an existing clip | 18 GB (8 GB for v1.5) | Not stated | Demo includes one anime clip; trained on real video |

**Components to check before any use:** each pipeline also loads an audio encoder (for example `chinese-wav2vec2-base` or `wav2vec2-base-960h`), a text encoder and optional speed-up LoRAs. **Their licences were not read.**

**Not on the list, worth checking before a test:** LongCat-Video-Avatar 1.5 (May 2026). The InfiniteTalk README says it "generalizes to stylized domains (anime, animals...)". Its licence and size were not read.

**Shortlist for us (cartoon character, our own line audio):**
1. **InfiniteTalk**: Apache, image + audio, long clips, and it can also dub an existing clip.
2. **Wan 2.2 S2V-14B**: Apache, the newest Wan model with audio input.
3. **MultiTalk**: Apache, and claims cartoon support.
4. **LatentSync**: Apache. A cheap way to lip-sync a clip we already have (a Kling 2.6 Pro clip without audio, or a Wan I2V clip).

HunyuanVideo-Avatar is excluded if the owner, the business or the audience is in the EU, UK or South Korea, and because of its ban on using outputs to improve other models. LTX-2 is excluded until the LTX-2.5 licence is read and lip-sync is shown.

### 14.3 Hosted versions of the same models (for comparison; official, fal.ai)

| Model | Price | Per 5 s clip |
|---|---|---|
| Wan 2.2 A14B image-to-video | $0.04/s at 480p, $0.06/s at 580p, $0.08/s at 720p | $0.20–0.40 |
| Wan 2.2 S2V-14B speech-to-video | $0.10/s at 480p, $0.15/s at 580p, $0.20/s at 720p | $0.50–1.00 |
| Kling AI Avatar v2 Standard (our current talking clip) | $0.0562/s | $0.28 |
| Kling 2.6 Pro image-to-video (our current motion clip) | $0.07/s, or $0.14/s with native audio | $0.35–0.70 |

fal states that both Wan 2.2 endpoints "will be removed on January 4, 2027".

### 14.4 GPU prices used below (official, RunPod pricing page dated 2026-11-12, per second)

| GPU | Secure Cloud | Community Cloud |
|---|---|---|
| RTX 4090 24 GB | $0.89/h | $0.34/h |
| L40S 48 GB | $1.09/h | $0.79/h |
| A100 80 GB PCIe | $2.09/h | $1.19/h |
| RTX PRO 6000 96 GB | $2.69/h | $1.69/h |
| H100 PCIe 80 GB | $2.89/h | $1.99/h |
| H100 SXM 80 GB | $4.39/h | $2.69/h |

**Billing rules (official):**
- Pods are billed per second, with no ingress or egress fees.
- A deploy needs "at least one hour's worth of credits".
- At a $0 balance, pods "are automatically stopped". Without a network volume they are terminated. This confirms the prepaid backstop in §11.1.
- Savings plans are discontinued.

### 14.5 What a clip costs at default settings (estimate from the official times and prices)

| Route | GPU | Time per clip | Cost per clip |
|---|---|---|---|
| Wan 2.2 I2V-A14B, 480p | H100 PCIe / SXM | 328 s | **$0.26 / $0.40** |
| Wan 2.2 I2V-A14B, 480p | A100 80 GB | 810 s | $0.47 |
| Wan 2.2 TI2V-5B, 720p (no audio) | RTX 4090 Secure | 525 s | $0.13 |
| Audio-driven 14B, 480p (S2V or InfiniteTalk) | H100 PCIe | about 330 s **(estimate, same size as I2V-A14B)** | about $0.26 |

**At the publishers' default step counts, self-hosting is not cheaper than Kling** ($0.28–0.35 per clip). It only becomes much cheaper with the third-party 4–8-step speed-up LoRAs, which cut 40–50 steps to 4–8 and give roughly 5–10× faster generation **(secondary; to be measured)**. That would mean about **$0.03–0.08 per clip**. Whether that holds for a cartoon character is the main question for the proof of concept (§16).

---

## 15. Training a small character/style add-on (LoRA) on our own art

**Rule:** training data is **only our own approved art**: approved character poses and sheets, approved sets, and our own rig renders of them. Never third-party images, and never frames from reference videos ("reference, not copy"). The training manifest records every input file's SHA-256 and its approval record. The studio refuses an input that has no approval record or comes from the reference-analysis folders.

**What it is:** a small add-on file (typically 100–600 MB, **estimate**) that teaches the video model what Mortimer, or our flat 2D style, looks like. It reduces drift away from the character. The **base must match the lip-sync model:** a LoRA trained on Wan 2.1 I2V-14B works with InfiniteTalk and MultiTalk (both built on it), but not with Wan 2.2 S2V, and the other way round.

**Needs:**

| Item | Amount |
|---|---|
| Data | 20–40 approved stills per character, plus 10–20 short clips of our own rig renders (2–5 s, 480p), with captions written by us |
| GPU | 48–80 GB for a 14B LoRA (A100 80 GB or H100). 24 GB only with heavy offloading **(secondary)** |
| Time | About 1–3 h per training run **(secondary; to be measured)** |
| Cost | About $2–9 per run (A100 $2.09/h to H100 $2.89/h). Two or three runs per character: **about $5–25 per character**, once |
| Tool | DiffSynth-Studio (listed on the Wan S2V card for LoRA training), or a pinned open-source trainer. It runs in the same worker image as a separate job kind, `lora-train` |

**How it plugs in:**
1. A `lora-train` job takes the approved inputs and returns the LoRA file plus a training manifest: base model revision, settings, input hashes and cost.
2. The LoRA is stored as an asset in quarantine. It is **used only after the owner approves it** (a new approval gate, never self-approved), as with poses.
3. Each video job names the LoRA version and its strength in the workflow. The clip's record keeps both, so every clip can be traced to the exact LoRA and inputs.
4. **Licence:** Apache base models allow derivatives. Under HunyuanVideo-Avatar's licence, training on its outputs is barred. Under LTX-2's, a LoRA would have to be distributed under LTX's licence. Neither matters if we never distribute the LoRA.

The image-model LoRA for poses (SDXL/FLUX/Qwen-Image-Edit) is a separate track, AP-84B3, and is unchanged.

---

## 16. Proof-of-concept plan (under $30)

**Prerequisite, needs its own approval as a separate PR (local engineering, $0):**
- the worker image and RunPod adapter from §11.2, with the cap, the idle timer, the maximum lifetime and the orphan sweep from §11.1;
- one workflow each for InfiniteTalk, Wan 2.2 S2V and LatentSync;
- a new column per self-hosted model in the shot comparison.

It is tested locally with a fake worker. Nothing is launched.

**What you do once:**
1. Create a RunPod account and add **$25** of credit with auto-top-up **off**. The balance is the hard stop (§14.4).
2. Create an API key in RunPod (restricted to pods if RunPod offers that; **not verified**).
3. Store the key in Settings > Secrets as `runpod_api_key`. I never see or print it.
4. In Settings > GPU worker: set `mode: rented`, the monthly cap to **$25**, the idle timer to 5 min and the maximum lifetime to 120 min.
5. Approve the run in writing. Each session is listed with its expected cost.

**Inputs (our own only):**
- Six lines that already have Kling clips in the shot comparison: Kling 2.6 Pro and Kling Avatar v2 Standard.
- For each line, the same start frame (our rig frame, medium framing), the same line audio and the same action text as the Kling runs.
- Mortimer is in at least four of them.

**Steps and budget (estimate, Secure Cloud):**

| Step | What | GPU | Expected cost |
|---|---|---|---|
| 1 | Session A: InfiniteTalk at 480p. Two lines at default steps (reference quality), then all six with a 4–8-step speed-up | H100 PCIe $2.89/h, 120 min max | $4–6 |
| 2 | Session B: Wan 2.2 S2V-14B at 480p, the same six lines, default steps and then sped up | H100 PCIe, 120 min max | $4–6 |
| 3 | Session C: LatentSync over the existing Kling 2.6 Pro clips (motion without audio) of the six lines | RTX 4090 $0.89/h, 60 min max | $1 |
| 4 | Optional, only if steps 1–2 pass the mouth test but drift off-model: one Mortimer LoRA (§15) and a rerun of the best model | A100 80 GB $2.09/h, 180 min max | $6–9 |
| | **Total** | | **about $9–13 without step 4; $15–22 with it.** Studio cap $25, RunPod balance $25 |

Each session's cost includes boot and weights download (about 10–20 min, **estimate**: the 14B models are 60–70 GB). A session the cap would refuse is not launched.

**Pass/fail criteria (all must pass for a "go"):**

| Criterion | How it is measured | Pass |
|---|---|---|
| **Mortimer stays on-model** | Blind review: the owner scores each clip 1–5 with the model names hidden and the order shuffled (face, outfit, proportions, flat 2D style, no photoreal shading). An automated check compares the share of the character's pixels inside the approved palette with the start frame | Average **≥ 4**, no clip below 3, and the palette share within 10% of the start frame |
| **The mouth follows the audio** | Blind review score, plus an automated measure: change in the mouth area per frame (the mouth box comes from the rig's own start frame) against the loudness of the line audio, using correlation and lag. Calibrated first on the Kling Avatar clips | Owner score **≥ 4**; correlation **at least Kling Avatar's minus 0.1**; lag ≤ 2 frames |
| **Length** | The existing check: our audio laid in, length within 1 frame at 30 fps | Every clip |
| **Cost per clip** | From the ledger: GPU seconds × the launch price, including each clip's share of boot and idle time | **≤ $0.10 per 5 s clip** (Kling: $0.28 Avatar, $0.35–0.70 2.6 Pro) |
| **Turnaround** | Wall time per clip, from the ledger | ≤ 10 min, so a 60 s Short fits in one working day |

**How it is compared with the Kling clips we have:**
- The shot comparison already shows the rig render, Kling 2.6 Pro and Kling Avatar side by side for each line, with our audio under each, the length check, and the cost per clip and per second.
- Each self-hosted model becomes another column in the same grid, from the same plan record (same frame, audio and action), so everything is compared like for like.
- The blind review uses the same clips with labels hidden.
- The result is a short table per line (scores, correlation, cost, time), recorded in this document as §19 when the test is done.

**Optional pre-check without a new account:** the existing fal key could run Wan 2.2 S2V on two lines at 480p, about $1 in total, to see cartoon quality before opening a RunPod account. It is a paid call, so it needs your approval, and that fal endpoint is being removed on January 4, 2027.

---

## 17. Monthly cost for video, and what it does to §12

**Assumptions:**
- A 60 s Short is fully talking/acting clips: 12 clips of 5 s each, at 480p, upscaled to 1080×1920.
- On average 1.5 takes per clip.
- One GPU session per Short, with about 12 min of boot and idle time.
- Times come from Wan's official H100 table (§14.5). "Sped up" assumes the 4–8-step LoRAs give about 8× **(secondary; to be measured in §16)**.
- The §5.4 figure of $10–20 a month covers image work only. These amounts come on top of it.

**GPU-minutes per 60 s Short:**

| Setting | Generation | Plus boot/idle | Total |
|---|---|---|---|
| H100, default steps | 12 × 5.5 min × 1.5 = 99 min | 12 min | **about 111 min** |
| H100, sped up | about 12 min | 12 min | **about 24 min** |
| L40S, default steps (assumed about A100 speed, 13.5 min per clip; **estimate**) | 243 min | 12 min | **about 255 min (4.3 h)** |

**Per month:**

| Cadence | H100, default (PCIe $2.89 to SXM $4.39) | H100, sped up | L40S, default ($1.09) | Kling Avatar Standard, same 1.5 takes |
|---|---|---|---|---|
| **1 Short a day (30)** | 56 h: **$160–245** | 12 h: **$35–53** | 128 h: **$139** | 30 × $5.06: **$152** |
| **3 Shorts a week (13)** | 24 h: **$70–106** | 5.2 h: **$15–23** | 55 h: **$60** | 13 × $5.06: **$66** |

At 720p, generation takes about 3.2× as long (official table), and the GPU costs rise by about the same factor.

**What this does to the break-even in §12:**
- **The card class changes.** The audio-driven 14B models peak at about 41 GB at 480p. A 24–32 GB card runs them only with heavy offloading and very slowly. The relevant line in §12 is therefore the **48 GB** one: an L40S build at about $11,000, break-even at about **310 GPU-hours, or $340, a month**. A 96 GB RTX PRO 6000 build (about $16,000 card + $3,000) is about $528 a month written off, with break-even at about **210 h, or $560, a month** against its $2.69/h rental.
- **None of the video scenarios reaches it.** The heaviest case, one Short a day on an L40S at default steps, uses about 128 h a month, under half of the 310 h break-even. With the speed-up, the hours fall about 8×.
- **The real choice for video is self-hosting versus Kling, not buying versus renting.** At default steps, self-hosting costs about the same as Kling Avatar. Only the speed-up makes it clearly cheaper: about $15–53 a month against $66–152. Buying would make sense only from about **2.5 Shorts a day at default steps on 48 GB**, and even then only once the models and quality have been settled.
- **The $50 cap in §11.1** covers 3 Shorts a week with the speed-up ($15–23 plus $10–20 of image work). One Short a day needs about $75 a month with the speed-up ($35–53 plus image work), or $170–265 at default steps. That is a cap decision for you, after the proof of concept.

---

## 18. Risks, unknowns, and when I would recommend against it

**Risks and unknowns:**
1. **Cartoon fidelity.** Most of these models were trained on real people. Only MultiTalk and HunyuanVideo-Avatar claim cartoon support. Likely failures are 3D or photoreal shading, a drifting face or outfit, and realistic lips on a simple cartoon mouth. **Our rig already gives on-model, audio-synced mouths at $0**, so AI video has to beat that, not just work.
2. **Speed-ups are third-party.** The 5–10× gain from 4–8-step LoRAs is not the publishers' claim, it may cost quality, and the LoRAs' licences were not read. Without them, self-hosting does not save money (§14.5).
3. **Resolution.** The audio models are 480p (OmniAvatar is 480p only). Shorts are 1080×1920, so either a 2.25× upscale, with a quality risk, or 720p at about 3.2× the cost.
4. **Continuity across clips.** Each 5 s clip is generated separately, so colour, lighting and identity can jump between clips. InfiniteTalk notes colour shift beyond about a minute.
5. **Licences of the parts.** The main models are Apache 2.0, but the audio encoders, text encoders and speed-up LoRAs were not checked. HunyuanVideo-Avatar's territory exclusion and LTX-2.5's unread licence keep those two out.
6. **Model churn.** fal is retiring the Wan 2.2 endpoints in January 2027, and new avatar models appear every few months. A pipeline built now may be outdated within a year, and the engineering time, not the GPU cost, is the main expense.
7. **Unmeasured figures.** S2V and InfiniteTalk times per clip, VRAM in our workflow, L40S speed and weights download time are all estimates until the proof of concept.
8. **Data handling.** Our frames and audio go to a RunPod Secure Cloud host. There are no secrets on the pod beyond the session token (§11.1).

**I would recommend against it if:**
- the proof of concept fails either the on-model or the mouth test against Kling Avatar on the same lines; or
- the measured cost per clip with the speed-up is above about **$0.15**, when Kling Avatar costs $0.28 with no engineering; or
- output stays at under about **3 Shorts a week**, where the saving over Kling (about $40–50 a month) does not pay for building and maintaining the pipeline; or
- the owner's blind review cannot tell the AI clips from the rig renders in a way that matters for the Shorts. If AI motion does not visibly improve them, the free rig remains the better choice.

**Sources (official, read 2026-11-21):**
- Wan 2.2 I2V-A14B: https://huggingface.co/Wan-AI/Wan2.2-I2V-A14B
- Wan 2.2 TI2V-5B: https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B
- Wan 2.2 S2V-14B: https://huggingface.co/Wan-AI/Wan2.2-S2V-14B
- Wan 2.2 README, efficiency table and licence: https://github.com/Wan-Video/Wan2.2, https://github.com/Wan-Video/Wan2.2/blob/main/LICENSE.txt, https://raw.githubusercontent.com/Wan-Video/Wan2.2/main/assets/comp_effic.png
- LTX-2 card, README and LTX-2 Community License: https://huggingface.co/Lightricks/LTX-2, https://github.com/Lightricks/LTX-2, https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2
- InfiniteTalk: https://github.com/MeiGen-AI/InfiniteTalk, https://huggingface.co/MeiGen-AI/InfiniteTalk
- MultiTalk: https://github.com/MeiGen-AI/MultiTalk
- OmniAvatar: https://github.com/Omni-Avatar/OmniAvatar
- HunyuanVideo-Avatar and its licence: https://github.com/Tencent-Hunyuan/HunyuanVideo-Avatar
- LatentSync: https://github.com/bytedance/LatentSync
- RunPod pricing (dated 2026-11-12): https://www.runpod.io/pricing
- RunPod billing: https://docs.runpod.io/pods/pricing
- fal.ai pricing and model pages: https://fal.ai/pricing, https://fal.ai/models/fal-ai/wan/v2.2-a14b/image-to-video, https://fal.ai/models/fal-ai/wan/v2.2-14b/speech-to-video, https://fal.ai/models/fal-ai/kling-video/ai-avatar/v2/standard, https://fal.ai/models/fal-ai/kling-video/v2.6/pro/image-to-video

# Part 3: Talking shots on rented ComfyUI sessions (built 2026-11-26)

## 19. How the talking-shot step uses the GPU manager

The guided page's step 9 renders talking shots with Wan 2.2 Speech-to-Video (owner-approved settings "B"). Code:
`talking_s2v.py` (the step, its routes and the render job), `comfy_session.py` (the session kind), `comfy.py` (the
ComfyUI client) and `pose_remote.py` (the actor's pose points).

**A second session kind, not a new worker job.** The portable worker image (§11.2) is not built or published yet. The
official image `runpod/comfyui:2.5.0-comfyuiv0.45.0-cuda13.2` ran this exact method on real GPUs, so a session of kind
`comfyui` launches it unchanged and the studio talks to ComfyUI directly. Everything that controls money is shared with
`gpu.py`: the same ledger row, the reservation of price x (maximum lifetime + 5 min) before the pod is created and the
monthly cap, the same pod name prefix (so the orphan sweep covers these pods), the same sweep (idle timer, maximum
lifetime, cap, pod gone) and `terminate_session` (terminate, never stop). The render job carries `"backend": "gpu"`, so
the idle timer never fires while it runs. Worker-image sessions and ComfyUI sessions are never reused for each other.

| Item | Value |
|---|---|
| Image | `runpod/comfyui:2.5.0-comfyuiv0.45.0-cuda13.2`, 120 GB disk, no volume, Secure Cloud |
| Ports | `8188/http` (ComfyUI through `https://<pod>-8188.proxy.runpod.net`), `22/tcp` (pose points only) |
| Auth | a random `COMFYUI_PASSWORD` per session (Bearer); header `User-Agent: curl/8.7.1` (Cloudflare blocks the Python agent) |
| GPU order | NVIDIA L40S, then NVIDIA RTX 6000 Ada Generation (about $1.09/h); NVIDIA A100 80GB PCIe only with Settings > GPU worker "allow expensive GPUs" (off by default). RunPod's HTTP 400 on create means that type is not free: the next is tried, each cap-checked at its own price |
| Models | ComfyUI-Manager `POST /v2/manager/queue/install_model` + `POST /v2/manager/queue/start` (headers `Sec-Fetch-Site: same-origin`, `Origin: <proxy url>`), then `GET /v2/manager/queue/status` until idle; each file is then checked in `GET /models/<folder>` |
| End | the session is terminated when the render ends (unless another talking render is queued); the sweep is the backstop |

**Pose points (MediaPipe 0.10.14) run on the GPU session, not on the studio server.** MediaPipe 0.10.14 has wheels for
Python 3.8-3.12 only; the API image (Debian trixie) runs Python 3.13. The studio cuts the needed reference frames itself
(FFmpeg), copies them to the pod over SSH with a throwaway ed25519 key made for that session (public half as
`PUBLIC_KEY`, private half encrypted in the ledger and dropped when the session ends), runs MediaPipe there and copies
back only the points. The frames are deleted on both sides. ComfyUI and the model only ever receive the drawn head
skeleton, never the reference picture. Host-key checking is off for these throwaway pods (their key cannot be known in
advance). If anything in this part fails, the shots render without a movement guide.

**Cost.** About 11 GPU minutes per 77-frame piece (measured on L40S / RTX 6000 Ada, including model load), scaled by
frames, plus about 10 minutes of start-up and model download per session, plus about 4 minutes when pose points must be
read. "About" uses the first GPU type's price; "at most" the most expensive allowed type plus 25%. The request must carry
"at most" (HTTP 409 otherwise), a render that would pass the monthly cap is refused (409), and the job stops before a
shot that would take the run past the confirmed amount. When a shot would not finish within the maximum session length,
the session is replaced (a new reservation, a new cap check).

# Part 4: Reactions and close-ups on the same ComfyUI sessions (built 2026-11-26)

## 20. Guided steps 6-8 (`reactions.py`)

The owner-tested acting method of 2026-11-26 (scripts `gpu_acting.py` and `compose_acting.py`), run from the dashboard.
A reaction shot is any storyboard shot that is not a talking shot and shows at least one character (one person on a
close or medium shot = close-up; otherwise a group shot). It uses the `comfyui` session kind of §19 unchanged: same
image, GPU order, cap reservation, sweep and termination. A job turns the GPU off at its end unless another ComfyUI job
(`talking_render`, `reaction_poses`, `reaction_animate`) is queued or running (`comfy_session.others_waiting`).

| Stage | Where | What |
|---|---|---|
| Crop (step 6) | studio server, free | Exact zoom crop of the owner-picked seating master of the shot's side (approved storyboard stills only), 16:9, upscaled to 1280x720 with Lanczos. Suggested from the head found in the master (white round regions matched to the side's seat order); the owner moves and zooms it and approves it. |
| Poses (step 7) | GPU | One pose per acting beat (pose 0 = the crop as it is; a big snap adds an overshoot pose). Each changed face is a Qwen-Image-Edit-2511 edit masked with `SetLatentNoiseMask` to an oval over the face interior, then pasted back through the same oval (softened inward only), so no pixel outside the oval changes. Group shots: one masked edit per character, one after another. A face whose exact prompt already has a result in the shot is reused (free). Every prompt carries the eyeline (listeners slightly screen-left toward the main speaker, the speaker screen-right, the camera only when the beat says so). |
| Moves (step 8) | GPU | Wan 2.2 i2v 14B `WanFirstLastFrameToVideo`, 33 frames at 16 fps, 1280x720, high-noise steps 0-2 + low-noise 2-4 with the lightx2v 4-step LoRAs, CFG 1, shift 5. Holds of 0.4 s or more are living holds (same pose first and last, tremble/blink prompt). |
| Assembly (step 8) | studio server, free | Timeline from the poses; moves eased out (power 2.2), living holds at natural speed (looped), the clip shown only inside a feathered box around the character(s) and the crop's own pixels outside; 25 fps H.264 per shot, plus a review copy with the episode's original audio. |

**Models** (ComfyUI-Manager): `qwen_image_edit_2511_fp8mixed`, `qwen_2.5_vl_7b_fp8_scaled`, `qwen_image_vae` for poses;
`wan2.2_i2v_high/low_noise_14B_fp8_scaled`, `wan2.2_i2v_lightx2v_4steps_lora_v1_high/low_noise`,
`umt5_xxl_fp8_e4m3fn_scaled`, `wan_2.1_vae` for moves (URLs in `reactions.QWEN_MODELS` / `WAN_MODELS`).

**Cost.** GPU price per hour x (about 10 min start-up + 60-90 s per masked face edit + about 2.5 min per Wan clip).
"About" uses the first GPU type and 60 s edits; "at most" the most expensive allowed type, 90 s edits and 25% margin. The
request must carry "at most" (`confirm_usd`, HTTP 409 otherwise); a run that would pass the monthly cap or the maximum
session length is refused (409); the job stops before a step that would pass the confirmed amount. Nothing is approved by
itself: the crop, each pose and each assembled shot wait for the owner's click. The chat under each pose
(`pose:<shot>:<pose>`) can propose `redo_pose {prompt}`; the chat under a reaction shot's clip (`clip:<shot>`) offers
`reanimate_shot {move_prompts?}` instead of the stick clip's `rerender_shot`; both go through the same paid routes.

# Part 5: Sets and seating masters (built 2026-11-26)

## 21. Guided step 5 (`room_sets.py`, `cutout_remote.py`)

The owner's Episode 15 lessons, run from the dashboard. The image model cannot move the camera around a room (given the
wide shot and asked for "the other side" it returns the same view), so every wall is its own straight-on picture.

| Stage | Where | What |
|---|---|---|
| Walls | WaveSpeed Nano Banana 2.1 edit, paid per image | One picture per wall, described as seen straight-on with what is on it. The establishing wide shot (owner-chosen, else the first approved wide still) is the only reference, for style, colours and materials. Prompts that ask to move, turn or rotate the camera/view are refused (owner edit: 422; GPT text: the template is kept and labelled). |
| Seating masters | WaveSpeed, paid per image | One picture per side of the room: the side's approved wall (else its set plate) as image 1, then every character's approved master in seat order. Approved seating masters are offered first (suggested) as reactions' seating masters; "Use for the close-ups" is the owner's click (`reactions.set_master`). |
| Background repair | rented ComfyUI session (§19), paid | rembg `birefnet-general` (`rembg[gpu]==2.0.67`) on the pod over SSH with the session's throwaway key, like the MediaPipe step: only the picture goes up, only the people's alpha comes back. Mask = the owner's box minus the people grown by 17 px; Qwen-Image-Edit-2511 masked repaint; second pass on the band between the tight outline (alpha > 40, grown 3 px) and the wide outline (grown 21 px) inside the box ("halo"); the original people pasted back through the tight outline (pixel-exact). Nothing outside the box changes. |
| Face fix | rented ComfyUI session, paid | One oval-masked face edit (`reactions.edit_graph`), pasted back through the oval on the whole picture, with the side's eyeline sentence. |
| Character check | studio server (free) + Gemini (paid, or the free tier when ticked) | Heads counted with `reactions.find_heads`; Gemini asked which listed characters are visible (one-line descriptions). Missing or merged characters are flagged with "Remake this picture" (one Nano image, the cast spelled out). |

**Eyeline** per side lives in `reactions:<id>` (`eyelines`): default from the main speaker (their side screen-right, the
others screen-left toward them); it is written into the seating prompt, the reaction face prompts and the talking-shot
prompt. **Cost**: a background repair is about 10 min start-up + 2 masked edits (60-90 s each) + 4-8 min for the cut-out
tool; a face fix 10 min + 1 edit. The request must carry "at most" (`confirm_usd`, 409 otherwise) and the monthly cap
applies. `room_repair` is one of `comfy_session.JOB_KINDS`, so a session shared with talking shots or reactions is only
turned off when none of them is waiting. Chat threads: `wall:<id>` (`remake_wall {prompt}`), `seating:<side>` and
`repair:<id>` (`repaint_background {prompt, box?}`), applied through the same paid routes.
