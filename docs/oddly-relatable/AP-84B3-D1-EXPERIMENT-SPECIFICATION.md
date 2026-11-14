# AP-84B3-D1: experiment specification and cost validation

**Status (2026-11-14):** specification approved in parts; nothing has been run.
- No account, payment method, instance, API call, model download or image generation. Spend to date: **$0**.
- **Approved by the owner:** D1-1 to D1-5 (2026-11-13), D1-6 implementation (2026-11-13), and the lock amendment L1 to L12 with cumulative limits (2026-11-14). See §8 and §10.
- **Implemented locally ($0):** the tooling in §7.1, the experiment lock `studio/config/ap84b3-experiment.json` and the runbook `AP-84B3-RUNBOOK.md`.
- **Not approved:** the experiment lock itself. Every tool refuses to run until the owner approves its hash (gate A4).
- **Not authorised:** the environment proposal (A5) and execution (D1-7). No approval so far authorises account creation, funding, provisioning, model downloads or image generation.
- `DECISIONS.md` is the authoritative record. Where this document and the lock differ, the lock holds the exact values.

**How the facts were gathered (all free, read-only, no login):**
- Model files, sizes, SHA-256 hashes and revisions: Hugging Face public metadata API, 2026-11-13.
- Software versions: GitHub public API, 2026-11-13.
- Prices: provider pricing pages, fetched 2026-11-13. They are published list prices, not quotes.
- Local facts: this repository.
- Anything not verified is marked **unverified**.

Follows `AP-84B3-TECHNICAL-DECISION-REPORT.md`.

## 1. Findings that change the earlier report

1. **"Qwen-Image-Edit" is three releases, not one.** The report did not say which.

   | Release | Published | Notes from the model card |
   |---|---|---|
   | Qwen-Image-Edit | 2025-08 | Original |
   | Qwen-Image-Edit-2509 | 2025-09 | Better single-subject consistency, multi-image input |
   | Qwen-Image-Edit-2511 | 2025-12 | "Mitigates image drift", better character consistency |

   All three are Apache 2.0. Because the experiment tests identity preservation, this specification pins **2511**. The owner approved 2511 on 2026-11-13 (D1-1, §8).
2. **A quantised set is about 30 GB, not 57.7 GB.** The 57.7 GB figure is the full-precision repository. ComfyUI's repackaged FP8 files are about half that (§2).
3. **Cheaper 48 GB GPUs exist on RunPod.** A40 ($0.59/h) and RTX A6000 ($0.69/h) have the same 48 GB as the L40S ($1.09/h). They are slower, which matters little for three images.
4. **Price corrections.** RunPod now lists the RTX 5090 at $1.39/h (the report said $1.19/h). Other RunPod figures match. RunPod's hosted endpoint also offers the 2511 release at $0.02 per request.
5. **Vast.ai prices could not be verified.** Its pricing page loads rates dynamically, so the $0.13/h and $0.37/h examples in the report remain unconfirmed.
6. **The local cut-out tool needs a small change.** `bible/concepts/src/ap72-cutout.cjs` has the master v3 path hard-coded. Using it on a generated candidate needs an input-path parameter. That is implementation (§7).

## 2. Pinned model and software manifest

Every file is pinned by repository revision and SHA-256. At execution, each downloaded file is hashed and compared before use; a mismatch stops the run.

### 2.1 Workflow Q: Qwen-Image-Edit-2511 (candidates A and B)

| Role | File | Size | SHA-256 | Repository @ revision | Licence |
|---|---|---|---|---|---|
| Diffusion model | `split_files/diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors` | 20.53 GB | `c9fdc158e46d3b61ef75f21ae866ca2fe808bf4a53643120d1c1e87c19280a4e` | `Comfy-Org/Qwen-Image-Edit_ComfyUI` @ `f68ace85e60b4a02a323e394253731947657b7d2` | Apache-2.0 |
| Text encoder | `split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors` | 9.38 GB | `cb5636d852a0ea6a9075ab1bef496c0db7aef13c02350571e388aea959c5c0b4` | `Comfy-Org/Qwen-Image_ComfyUI` @ `1f12b17be14c89b026c51a91d67c32f84bb047bc` | Apache-2.0 |
| VAE | `split_files/vae/qwen_image_vae.safetensors` | 0.25 GB | `a70580f0213e67967ee9c95f05bb400e8fb08307e017a924bf3441223e023d1f` | same as text encoder | Apache-2.0 |

- **Total: 30.16 GB.**
- **Upstream:** `Qwen/Qwen-Image-Edit-2511` @ `6f3ccc0b56e431dc6a0c2b2039706d7d26f22cb9` (Apache-2.0, not gated).
- **Not used:** the Lightning 4-step LoRA. It would add a second variable and a third-party file.
- **Alternatives in the same repository, not pinned:** `qwen_image_edit_2511_bf16.safetensors` (40.86 GB, full precision) and `qwen_image_edit_2511_int8_convrot.safetensors` (20.50 GB).

### 2.2 Workflow S: SDXL 1.0 + IP-Adapter (candidate C)

| Role | File | Size | SHA-256 | Repository @ revision | Licence |
|---|---|---|---|---|---|
| Checkpoint (includes VAE and text encoders) | `sd_xl_base_1.0.safetensors` | 6.94 GB | `31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b` | `stabilityai/stable-diffusion-xl-base-1.0` @ `462165984030d82259a11f4367a4eed129e94a7b` | CreativeML Open RAIL++-M |
| IP-Adapter | `sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors` | 0.85 GB | `3f5062b8400c94b7159665b21ba5c62acdcd7682262743d7f2aefedef00e6581` | `h94/IP-Adapter` @ `018e402774aeeddd60609b4ecdb7e298259dc729` | Apache-2.0 |
| Image encoder (CLIP ViT-H/14) | `models/image_encoder/model.safetensors`, saved as `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` | 2.53 GB | `6ca9667da1ca9e0b0f75e46bb030f7e011f44f86cbfb8d5a36590fcd7507b030` | same as IP-Adapter | Apache-2.0 (repository licence) |

- **Total: 10.32 GB.**
- **Not used:** the SDXL refiner, and ControlNet. An OpenPose ControlNet (`xinsir/controlnet-openpose-sdxl-1.0`, 2.50 GB, Apache-2.0) is the obvious extension, but pose detectors are trained on realistic people and are **unverified** on this stick-limbed character. It stays out of the baseline.

### 2.3 Software

| Component | Pin | Licence |
|---|---|---|
| ComfyUI | tag `v0.45.3`, commit `71096d1af6c9d1c34fc42094ec4ec59768104786` | GPL-3.0 |
| ComfyUI_IPAdapter_plus (workflow S only) | commit `a0f451a5113cf9becb0847b92884cb10cbdec0ef` (2025-04-14) | GPL-3.0 |
| Local cut-out | `bible/concepts/src/ap72-cutout.cjs` at the commit used | project |
| Local validator | `studio/lib/asset-intel.mjs` at the commit used | project |

- The GPL covers the software, which we run and do not distribute. It places no condition on the images.
- Open RAIL++-M permits commercial use of outputs, subject to its use restrictions. This is a reading of the licence text, not legal advice.
- ComfyUI_IPAdapter_plus has been in "maintenance only" mode since 2025-04-14. Whether it runs on ComfyUI v0.45.3 is **unverified** (risk R4).

### 2.4 Inputs from this repository

| Input | File | Size | SHA-256 |
|---|---|---|---|
| Edit input and identity reference (master v3) | `bible/concepts/lookdev-richenv/production-candidates/corrected/candidate-04_corrected-v3.png` | 1024×1536, flat grey background | `d4dcb8082317ec2ab76c91e1bbcaf6ea20d9667ab721596f0e02718bbf07da51` |
| Control for comparison (approved pose 02 v1) | `bible/concepts/lookdev-richenv/ap75-pose02-test/character-01_pose-02-worried-phone_skin-only_test.png` | 270×571, figure 549 px | `ee921285d86a356dfd9e7bb5e316a284384dc54b7f23745738eb046ea5584e26` |

- The reference pack for `character-01` is built by the studio (`buildReferencePack`) at execution; its pack ID and pack hash are recorded then.
- The approved pose 02 is **not** given to either model. It is only the yardstick for review.

## 3. Workflow Q specification (Qwen-Image-Edit-2511)

| Setting | Value |
|---|---|
| Input image | master v3, unmodified |
| Output size | 1024×1536 (latent set explicitly, not derived from the scaled input) |
| Steps | 40 |
| CFG (true CFG) | 4.0 |
| Sampler / scheduler | euler / simple |
| Negative prompt | a single space |
| LoRA | none |
| Seeds | A: `8403001`; B: `8403002` |
| Batch size | 1 |

- Steps, CFG and the negative prompt are the values on the 2511 model card.
- **Graph (amended 2026-11-14, owner decisions L5, L6, L12):** ComfyUI's built-in "Qwen Image Edit 2511" template, changed to meet the constraints in the experiment lock.

  | Setting | Value | Status |
  |---|---|---|
  | Denoise | 1.0 | Approved (L5) |
  | Input scaling | None: the template's input-scaling node is removed, and master v3 goes to both text encoders as the only reference image | Approved (L6) |
  | Latent | `EmptySD3LatentImage`, 1024×1536, batch 1, connected directly to the sampler | **Unverified compatibility gate** (see below) |
  | Model chain | Loader → model-sampling shift → CFGNorm (strength 1.0) → sampler; no LoRA, switch or primitive nodes | Approved (L12) |
  | Reference-latent method | `index_timestep_zero` on both conditionings | Approved (L12), from the pinned template |
  | Shift | Recorded from the export, not pinned. The pinned template uses 3.1 | D1-2 caveat |

  - **Latent compatibility gate.** `EmptySD3LatentImage` is not verified with Qwen-Image-Edit-2511. It is tested in the Qwen smoke run during authorised execution. If it is incompatible, the run stops and returns to the owner. No other node is substituted.
  - **Graph validation.** The lock holds the constraints (node types, counts, settings and connections). An extra node, missing node, changed setting or rewired connection fails. A setting the constraints do not list stops the run for owner review. The actual API export is not pre-approved: it is inspected and frozen during execution, and every later export must match the frozen graph apart from the seed (and, for a smoke run, the latent size and steps).
- **Prompt (approved by the owner, D1-3, 2026-11-13):**

  > Keep exactly the same character: the same round bald head, large round eyes, ears, skin colour, rust-orange turtleneck with a ribbed collar and ribbed hem, thin black limbs, black mitten hands, brown shoes, thick black outlines and flat colours. Change only the pose and expression. He stands, full body, turned slightly toward the right of the image, holding a dark smartphone up in the hand on the right of the image and looking at its screen. His other hand is raised to his chest. He looks worried: eyebrows slanted up in the middle, mouth open and turned down. Keep the plain flat light-grey background. Show the whole figure from head to shoes with space around it. No shadows, no text, no extra objects.

  - The pose mirrors the approved pose 02 so that the comparison is like for like. Orientation is given from the viewer's side.
  - The three-quarter turn is intentional: the experiment tests whether the model can change the pose without changing Character 01's identity.

**Known uncertainties to observe, not fix in advance:**
- The text encoder resizes its own copy of the reference to about 1 megapixel internally (fixed by the pinned code). Output at 1024×1536 (1.57 MP) is within the model's range, but sharpness at that size is **unverified**.
- Whether the model keeps the background flat enough for the cut-out tool (it expects grey with low saturation near the border level).

## 4. Workflow S specification (SDXL 1.0 + IP-Adapter Plus)

| Setting | Value |
|---|---|
| Reference image | master v3, padded **locally** to a 1536×1536 square with RGB (203, 203, 203), so the whole figure reaches the image encoder (L10). The node's own padding fills with black and is not used |
| IP-Adapter | Plus (ViT-H), weight 0.8, weight type linear, start 0.0, end 1.0 |
| IP-Adapter options | combine embeds `concat`, embeds scaling `V only`, no negative image, no attention mask (L9) |
| Loaders | Explicit `IPAdapterModelLoader` and `CLIPVisionLoader`, naming the pinned files (L8) |
| Prompt encoder | `CLIPTextEncode` for both prompts (L7) |
| Denoise | 1.0 (L5) |
| Generation size | 832×1248 (exactly 2:3, about 1.04 MP, close to SDXL's training size) |
| Final size | 1024×1536 by Lanczos resize (factor 1.2308) in the workflow, crop disabled, no upscaler model; the 832×1248 raw output is also saved (L11) |
| Steps | 30 |
| CFG | 6.0 |
| Sampler / scheduler | dpmpp_2m / karras |
| Seed | C: `8403001` |
| Batch size | 1 |

- **Prompt (approved by the owner, D1-3, 2026-11-13):** *flat 2D cartoon character, round bald head, large round eyes, rust-orange turtleneck with a ribbed collar and ribbed hem, thin black limbs, black mitten hands, brown shoes, thick black outlines, flat colours, standing full body, holding a smartphone in one raised hand and looking at it, worried expression, plain flat light-grey background*
- **Negative prompt (approved, D1-3):** *photo, realistic, 3d, shading, gradient, shadow, text, watermark, cropped, extra limbs, extra fingers, background scene*
- Prompt S is deliberately less precise than Prompt Q. It must not be silently improved to match it.
- Both the 832×1248 raw output and the 1024×1536 resize are kept and hashed.

**Why this is a fair but weak baseline.** IP-Adapter carries appearance, not identity, and it also carries the reference's neutral pose. The prompt has to pull the pose away from the reference. A poor result is informative: it shows what a lighter, cheaper stack costs in identity. The SDXL settings are conventional defaults, not tuned; tuning would mean more generations and a larger budget.

## 5. Cost validation

### 5.1 Published rates (RunPod, page dated 2026-11-12)

| GPU | VRAM | Secure Cloud | Community Cloud |
|---|---|---|---|
| A40 | 48 GB | $0.59/h | $0.35/h |
| RTX A6000 | 48 GB | $0.69/h | $0.33/h |
| RTX 4090 | 24 GB | $0.89/h | $0.34/h |
| L40S | 48 GB | $1.09/h | $0.79/h |

- **Billing:** per second for compute and disk.
- **Disk:** container disk $0.10/GB/month, erased when the Pod stops, not billed while stopped. Volume disk $0.20/GB/month while stopped.
- **Data transfer:** no ingress or egress fees (RunPod documentation).
- **To start a Pod:** the account needs at least one hour's worth of credit for the configuration.
- **Minimum funding:** RunPod's billing documentation says "you can start with as little as $10". Prepaid cards should deposit at least $100 per transaction.
- **Refunds:** "Runpod credits are non-refundable and cannot be withdrawn once deposited."
- **At $0 balance:** RunPod stops all Pods and terminates those without a network volume.

### 5.2 Storage plan

- Models: 30.16 GB + 10.32 GB = **40.48 GB**.
- One **80 GB container disk**, no volume and no network storage. Nothing persists, so nothing bills after the Pod is terminated.
- Cost: 80 GB × $0.10 ÷ 730 h = **about $0.011 per hour**.

### 5.3 Time budget (estimates, unmeasured)

| Step | Planned | Worst case |
|---|---|---|
| Pod start, ComfyUI and custom node at pinned commits | 15 min | 30 min |
| Download 40.48 GB (7 min at 100 MB/s; 27 min at 25 MB/s) | 15 min | 45 min |
| Hash all six files | 5 min | 10 min |
| Upload master v3, load and freeze both workflows | 15 min | 30 min |
| Smoke runs and three candidates (§6.3) | 25 min | 50 min |
| Download outputs, verify hashes locally, terminate | 10 min | 15 min |
| **Total** | **about 1.5 h** | **3 h** |

### 5.4 Cost per option

| Option | Planned (1.5 h) | Worst case (3 h) |
|---|---|---|
| RunPod A40 48 GB, Secure | $0.89 + $0.02 disk = **$0.91** | $1.77 + $0.03 = **$1.80** |
| RunPod L40S 48 GB, Secure | $1.64 + $0.02 = **$1.66** | $3.27 + $0.03 = **$3.30** |
| RunPod RTX 4090 24 GB, Secure | $1.34 + $0.02 = **$1.36** | $2.67 + $0.03 = **$2.70** |
| RunPod hosted endpoint, 2511, 2 requests | **$0.04** | n/a |
| Modal L40S ($1.95/h, plus CPU and memory) | about **$3.00** | about **$6.00** |

- **RTX 4090:** the 20.53 GB model alone is 86% of 24 GB, before the encoder and working memory. ComfyUI can offload, but a failed fit wastes paid time. 48 GB removes the question for under $1.
- **Hosted endpoint:** covers candidates A and B only. No SDXL baseline, no pinned checkpoint or settings, and the artwork goes to a shared service. Useful later as a price reference, not for this experiment.
- **Modal:** the Starter plan advertises $30/month of free compute. Whether a card is required is **unverified**. It needs code to be written first, so it is more implementation, not less.
- **Vast.ai:** not costed; prices unverified (§1).

### 5.5 Approved limits and required safeguards (D1-4, D1-5)

**Owner-approved limits.** These are three separate things.

| Limit | Approved value | Decision |
|---|---|---|
| Funding commitment | **One $10 RunPod deposit.** Credits are non-refundable, so $10 is the cash committed. No additional funding without fresh owner approval | D1-5 |
| Consumption ceiling | **$5.00** maximum for the entire experiment | D1-5 |
| Runtime limit | **3 hours** maximum Pod runtime | D1-5 |
| Configuration | RunPod Secure Cloud; L40S 48 GB primary, A40 48 GB fallback, no L40 second fallback; 80 GB container disk, no volume disk and no network volume | D1-4 |

- At the published rates, 3 hours costs about $3.30 on the L40S and about $1.80 on the A40 (§5.4), so the runtime limit is reached before the consumption ceiling.
- Expected consumption is about $1.66 (L40S, 1.5 h, an unmeasured estimate). Unspent credit stays on the account and cannot be withdrawn.

**Safeguards required by D1-5.** The owner has approved these as conditions. **None has been verified yet.** Each must be verified, and the evidence recorded, before execution.

| # | Safeguard | When it is verified |
|---|---|---|
| S1 | Auto-pay is disabled | Before any funding |
| S2 | The L40S rate does not exceed $1.09/hour; the A40 rate does not exceed $0.59/hour | In the console, before deploying |
| S3 | A runtime watchdog is running, and a manual stop backup is in place | Watchdog tested before the run and confirmed running when the Pod starts |
| S4 | Outputs are copied to durable storage and their checksums verified | Before the Pod is stopped |

- RunPod has no built-in per-Pod budget or auto-terminate setting, so the consumption ceiling and runtime limit are enforced by the operator and the watchdog, not by the provider.
- With $10 funded and auto-pay off, the account balance is the provider-side hard stop.
- The watchdog and the scripts that apply these safeguards are implementation (§7.1) and are not authorised.
- **Why this configuration:** the L40S costs about $0.75 more than the A40 over the planned run and is markedly faster, which shortens the window in which something can go wrong. Secure Cloud is used because the artwork is uploaded to the machine and Community hosts are third parties.
- D1-5 sets limits only. The deposit may be made only as part of authorised execution (D1-7).
- **The limits are cumulative (owner decision A2, 2026-11-14).** The $5.00 ceiling, the 3-hour runtime and the single $10 deposit cover the entire experiment, including any additional Pod sessions. A failed session does not reset them. No additional deposit or funding is authorised.

## 6. Three-candidate experiment protocol

### 6.1 Candidates

| Candidate | Workflow | Seed | Purpose |
|---|---|---|---|
| A | Q (Qwen-Image-Edit-2511) | 8403001 | Primary |
| B | Q, identical except the seed | 8403002 | Consistency between generations |
| C | S (SDXL + IP-Adapter Plus) | 8403001 | Baseline |

Target: `character-01`, pose 02 (worried, looking at phone), proposed as **version 2**. Version 1 is untouched.

### 6.2 Before the Pod starts (local, $0)

1. Owner approvals in §8 are recorded.
2. Verify the hashes of master v3 and approved pose 02 against §2.4.
3. Build the `character-01` reference pack; record its ID and hash.
4. Implementation dependencies in §7 are built, tested and accepted.
5. Prompts, seeds and settings are frozen in a run sheet. No changes after this point.

**Funding and deployment checks (only once execution is authorised under D1-7; safeguards S1 to S3 in §5.5):**

6. Verify that auto-pay is disabled, and record the evidence, before any funding.
7. Make one $10 deposit. No additional funding without fresh owner approval.
8. Check the rate in the console before deploying: L40S at most $1.09/hour. If no L40S is available, A40 at most $0.59/hour. If neither is available within its cap, do not deploy; return to the owner.
9. Start the runtime watchdog when the Pod starts and confirm it is running. Keep the manual stop backup ready.

### 6.3 On the Pod

The step-by-step procedure is in `AP-84B3-RUNBOOK.md`. In outline:

1. Install ComfyUI and the custom node at the pinned commits (needs the approved environment, gate A5).
2. Download the six files; hash each; stop on any mismatch.
3. **Freeze each workflow.** Export it in API format for its first candidate (A for Qwen, C for SDXL) and check it against the lock's constraints. If it passes with nothing unlisted, it is frozen and its hashes and the shift value are recorded. Every later export must match the frozen graph.
4. **Smoke run:** at most **one** per workflow, 512×768, 8 steps, seed **8403900** (not used by any candidate). It only proves the pipeline runs. It is saved, hashed, verified into its own folder and recorded; it is never a candidate and cannot be imported as one.
5. **Qwen latent compatibility gate:** the Qwen smoke run must complete without error and return a decodable image. If not, stop and return to the owner; no other latent node is substituted.
6. Generate A, B, then C. **One generation each. No retries for quality.**
7. A retry is allowed only for a technical failure (crash, out of memory, corrupt file), with identical settings, and is recorded.
8. Copy every output to durable storage off the Pod as it is produced. Hash on the Pod and again after copying; the two must match (safeguard S4).
9. Only after every output is copied and its checksum verified, stop and terminate the Pod. Confirm in the console that no Pod, volume or network storage remains.

**Every image generated is kept and recorded.** Nothing is discarded, so nothing is cherry-picked.

### 6.4 Stop rules

Stop the Pod if any of these happens:
- 3 hours of Pod runtime in total across all sessions (D1-5, A2);
- $5.00 consumed in total across all sessions (D1-5, A2);
- a hash mismatch on any model file;
- the pinned software will not run without changing a pin (record it and return to the owner);
- a workflow export contains a setting the lock's constraints do not list (owner review);
- the Qwen latent compatibility gate fails.

- The runtime watchdog enforces the runtime limit and the estimated-consumption threshold; the manual stop is the backup (safeguard S3).
- An output is safely retained only once it has been transferred and its checksum verified locally. An output still on the Pod, or part-way through transfer, when the Pod stops is lost. The limits are not extended to finish a run.
- A run stopped at a limit or a gate is not restarted, and no funds are added, without fresh owner approval. A later session uses only what remains of the cumulative limits.

### 6.5 After the Pod (local, $0)

1. Import the raw outputs into quarantine with full provenance (§6.6).
2. Cut out each raw output locally. Raw and cut-out are separate, hashed files.
3. Run the studio validator on each cut-out (1024×1536 canvas, transparency, edge integrity, figure height ≥ 1000 px, palette, proportions and feet against the approved poses).
4. Build one comparison sheet: master v3, approved pose 02 v1, A, B, C at the same scale, plus close-ups of the head and hands.
5. Owner review of each candidate against the criteria below, with a note.

### 6.6 Provenance recorded per image

- Model files, sizes, hashes and repository revisions (§2).
- ComfyUI commit, custom node commit, workflow API JSON hash.
- Reference pack ID and hash; input file hash.
- Prompt, negative prompt, seed, size, steps, CFG, sampler, scheduler, IP-Adapter settings.
- Provider, GPU, region, Pod start and end times, cost at the published rate.
- Output SHA-256 (raw, and cut-out separately).
- Validator report ID; review outcome and note.

### 6.7 Review criteria

| Criterion | Pass means |
|---|---|
| Character identity | Reads as Character 01 beside master v3 |
| Head and face | Head shape, eye size and spacing, ears, brows consistent |
| Outfit | Rust ribbed turtleneck, same colour and hem |
| Hands and shoes | Black mitten hands, brown shoes |
| Body proportions | Head-to-body ratio and limb thickness as master v3 |
| Line and colour | Thick black outline, flat colours, no shading |
| Pose | Clearly worried, clearly looking at a phone |
| Technical | Validator has no `fail` |

**Reading the result:**
- **A and B both pass:** evidence that the Qwen route preserves identity and is repeatable. Two images are a small sample; a larger batch would be the next question.
- **A and B differ in identity:** the route is not yet reliable, whatever the better one looks like.
- **C passes:** the cheaper stack deserves a second look.
- **All fail:** AI pose generation is not ready for this character with these tools; the manual pose route stays.

No outcome promotes anything. Approval of a candidate creates a registry proposal only; promotion and "make current" keep their own gates.

## 7. Implementation dependencies and risks

### 7.1 Implementation before execution (D1-6: approved and built, 2026-11-13; amended 2026-11-14)

| # | Item | Built as |
|---|---|---|
| I1 | Quarantine import adapter | `import` adapter in `studio/lib/gen-adapters.mjs`; the default adapter stays `none` |
| I2 | Parameterised cut-out | `studio/tools/ap84b3/cutout.cjs` |
| I3 | Run sheet and provenance schema | `studio/lib/experiment-spec.mjs` and the lock `studio/config/ap84b3-experiment.json` |
| I4 | Pod setup script | `studio/tools/ap84b3/pod-setup.sh` and `build-pod-bundle.mjs`. Never executed; refuses to run without the approved environment (A5) |
| I5 | Comparison sheet script | `studio/tools/ap84b3/compare-sheet.mjs` |
| A1 | Runtime watchdog and local stop timer (required by D1-5) | `watchdog.sh`, `stop-timer.mjs` |
| A2 | Output checksums and atomic transfer verifier (required by D1-5) | `collect-outputs.sh`, `verify-transfer.mjs` |
| A3 | Runbook (required by D1-5) | `docs/oddly-relatable/AP-84B3-RUNBOOK.md` |
| A4 | Workflow graph checker (required by the D1-2 caveat; two-layer since the amendment) | `check-workflow.mjs` |
| — | Local reference padding (lock amendment, L10) | `pad-reference.mjs` |

- All of it is local, $0 work with tests. Nothing has been run on a Pod.
- Every tool refuses to run until the owner approves the experiment lock's hash.
- A live RunPod/ComfyUI adapter is not built. It would be a later milestone, if the experiment succeeds.

### 7.2 Risks

| # | Risk | Effect | Mitigation |
|---|---|---|---|
| R1 | Qwen redraws the character (drift) | Candidates fail review | This is what the experiment measures |
| R2 | Background not flat enough for the cut-out | Validator fails on transparency or edges | Prompt asks for flat grey; raw files are kept; cut-out thresholds are reported, not silently changed |
| R3 | Soft output at 1.57 MP | Figure-height target met but edges soft | Observed in review; a later run could test 1 MP plus resize |
| R4 | IP-Adapter node will not run on ComfyUI v0.45.3 | Candidate C cannot be produced as specified | Stop rule applies; the fallback (a short diffusers script with the same model files) would need owner approval as a specification change |
| R5 | Download slower than assumed | More paid time | Budgeted to 45 min; 3 h limit |
| R6 | Storage left billing | Cost after the run | Container disk only; termination check in §6.3 |
| R7 | Artwork on a third-party machine | Master v3 leaves local control for the run | Secure Cloud; one file; Pod terminated and disk erased |
| R8 | Minimum deposit larger than the ceiling | More cash committed than consumed | Verified: $10 minimum, non-refundable (§5.1). The owner approved one $10 deposit (D1-5) |
| R9 | Upstream files moved or changed | Download fails or hash differs | Revisions pinned; hash check stops the run |
| R10 | Two images are a small sample | Over-reading one good result | §6.7 states what each outcome does and does not show |
| R11 | Published prices change | Estimate off | Re-check the rate on the day; the ceiling is in dollars, not hours |

## 8. Owner decisions

Status on 2026-11-14. Each decision is separate. `DECISIONS.md` is the authoritative record.

| # | Decision | Outcome | Status |
|---|---|---|---|
| D1-1 | Qwen release to test | Qwen-Image-Edit-2511, FP8 mixed (§2.1) | **APPROVED** |
| D1-2 | Manifest and both workflow specifications | Accepted as pinned in §2 to §4 | **APPROVED with four caveats** (below) |
| D1-3 | Prompts (§3, §4) | Revised prompts Q and S | **APPROVED with revised prompts**; wording only |
| D1-4 | Provider and GPU for the experiment | RunPod Secure Cloud; L40S 48 GB primary, A40 48 GB fallback; 80 GB container disk only | **APPROVED**; selection only |
| D1-5 | Cost ceiling and funding | One $10 deposit; $5.00 consumption ceiling; 3-hour Pod runtime limit; four safeguards (§5.5) | **APPROVED**; limits only |
| D1-6 | Implementation work in §7.1 | Built and tested locally, $0; 30-minute console checkpoints; $0.25 reconciliation tolerance; every D1-7 approval must name the approved lock hash | **APPROVED and implemented** |
| Lock amendment | L1 to L12, the Qwen latent compatibility gate and two-layer graph validation (§10) | Implemented locally, $0 | **APPROVED** (2026-11-14) |
| A2 | Cumulative limits across all sessions | $5.00, 3 hours and one $10 deposit for the whole experiment | **APPROVED** (2026-11-14) |
| A4 | Experiment lock review | The owner reviews the lock and its canonical hash; only then is an approval line written | **Not approved** |
| A5 | Environment proposal | PyTorch version and Pod base image, reviewed and reproducible | **Not approved** |
| D1-7 | Execution | Only after D1-1 to D1-6 and after §7.1 is accepted | **Not authorised** |

**D1-1.** The 2511 consistency improvements are publisher claims; the experiment exists to test them.

**D1-2 caveats (part of the approval):**
1. **Quantisation:** FP8 is accepted to reduce download size and VRAM pressure. Image fidelity must be evaluated during review.
2. **Qwen workflow:** the exact node graph and shift value must be exported, hashed and recorded before any candidate is generated. No silent workflow changes.
3. **SDXL:** the baseline is deliberately untuned. Its result is for comparison, not expected to outperform Qwen.
4. **Compatibility:** if IP-Adapter does not work with the pinned ComfyUI version, stop and return for a decision. Do not substitute another implementation.

**D1-3 changes and caveats (part of the approval):**
- "rust-orange ribbed turtleneck" became "rust-orange turtleneck with a ribbed collar and ribbed hem" in both prompts, because master v3 has a ribbed collar and hem but a smooth sweater body.
- Prompt Q gives orientation from the viewer's side instead of the character's left and right.
- The three-quarter turn is intentional.
- Prompt S stays a deliberately less precise baseline.
- Identity drift in SDXL is an expected comparison risk, not permission to accept a redesigned character.
- Master v3 remains the reference. No change to canonical artwork or approved character identity.

**D1-4 (hardware and provider selection only):**
- Provider: RunPod Secure Cloud.
- Primary GPU: NVIDIA L40S 48 GB. Fallback GPU: NVIDIA A40 48 GB. No L40 second fallback.
- Storage: 80 GB container disk, no volume disk and no network volume.
- It does not authorise account creation, adding credits, provisioning, model downloads or execution.

**D1-5 (limits only):**
- **Funding commitment:** one $10 RunPod deposit. No additional funding without fresh owner approval.
- **Consumption ceiling:** $5.00 maximum for the entire experiment.
- **Runtime limit:** maximum Pod runtime 3 hours.
- **Safeguards that must be verified before execution:**
  - auto-pay disabled and verified before any funding;
  - L40S rate at most $1.09/hour and A40 rate at most $0.59/hour;
  - a verified runtime watchdog and a manual stop backup;
  - outputs copied to durable storage and checksums verified before the Pod is stopped.
- The deposit may be made only as part of authorised execution.

**Not authorised:** the lock approval (A4), the environment proposal (A5) and D1-7 (execution). Until they are approved, there is no account creation, funding, provisioning, model download, image generation or cost.

## 9. Sources

- Hugging Face model metadata (API, 2026-11-13): `Qwen/Qwen-Image-Edit`, `Qwen/Qwen-Image-Edit-2509`, `Qwen/Qwen-Image-Edit-2511`, `Comfy-Org/Qwen-Image-Edit_ComfyUI`, `Comfy-Org/Qwen-Image_ComfyUI`, `stabilityai/stable-diffusion-xl-base-1.0`, `h94/IP-Adapter`, `xinsir/controlnet-openpose-sdxl-1.0`.
- https://huggingface.co/Qwen/Qwen-Image-Edit-2511 (model card: improvements, steps and CFG).
- https://docs.comfy.org/tutorials/image/qwen/qwen-image-edit-2511 and https://docs.comfy.org/tutorials/image/qwen/qwen-image-edit (model files, folders, 1 MP input scaling).
- https://github.com/Comfy-Org/ComfyUI (tag `v0.45.3`) and https://github.com/cubiq/ComfyUI_IPAdapter_plus (maintenance notice, folders, encoder files).
- https://www.runpod.io/pricing (dated 2026-11-12) and https://docs.runpod.io/pods/pricing (billing, storage, no transfer fees).
- https://modal.com/pricing (GPU, CPU, memory, volume and egress rates; Starter credits).
- https://vast.ai/pricing (market-set pricing; rates not readable).

## 10. Lock amendment (owner decisions, 2026-11-14)

These decisions were made after the lock review. The exact values are in the experiment lock.

| # | Decision |
|---|---|
| L1 | The seven model and node save paths are accepted as documented by the pinned ComfyUI source and the pinned IP-Adapter README |
| L2 | Smoke runs: 512×768, 8 steps, at most one per workflow, seed 8403900 |
| L3 | The smoke seed is validated, and smoke outputs can never enter candidate selection |
| L4 | The 672-hour month is retained for the disk estimate (conservative: about $0.0119 per hour for the 80 GB disk) |
| L5 | Denoise is pinned to 1.0 in both workflows |
| L6 | The Qwen input-scaling node must be absent |
| L7 | SDXL uses `CLIPTextEncode` |
| L8 | Explicit IP-Adapter and CLIP Vision loaders |
| L9 | IP-Adapter options: `concat`, `V only`, no negative image, no attention mask |
| L10 | The reference is padded locally to 1536×1536 with RGB (203, 203, 203) |
| L11 | SDXL final resize is Lanczos, with the raw output retained |
| L12 | Complete workflow graph validation in two layers: constraints in the lock, and a mandatory freeze of the real export at execution |
| Gate | The Qwen latent node is an unverified compatibility gate: tested in the smoke run; on failure stop; no substitution |
| A2 | The limits are cumulative across all Pod sessions; no additional funding |

**Still unresolved until execution:** the Qwen latent node, the shift value, the real API export, how the on-Pod stop command authenticates, SSH file copy, and whether the pinned ComfyUI and IP-Adapter node run together.
