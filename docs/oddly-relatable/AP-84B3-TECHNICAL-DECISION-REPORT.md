# AP-84B3: GPU and image-model technical decision report

**Status (2026-11-13):** research only.
- No provider and no model is selected.
- Nothing is authorised: GPU budget **$0**, no accounts, payment methods, instances, API calls, model downloads or image generation.
- The next proposed milestone, AP-84B3-D1, needs the owner's explicit approval.

**Sources:**
- §1–§5 summarise the report ChatGPT produced (pasted by the owner on 2026-11-13). Prices and figures are ChatGPT's, quoted from public provider pages; they have not been re-checked here and are not quotes.
- §6 is Claude Code's technical review against this repository.

## 1. Recommendation (ChatGPT)

| Area | Recommendation |
|---|---|
| Providers | **RunPod** evaluated first; **Vast.ai** as price challenger; **Modal** if a serverless worker is preferred later |
| Primary model | **Qwen-Image-Edit**: edits an existing character reference into a new pose; Apache 2.0 |
| Baseline model | **SDXL 1.0**: lighter, mature ecosystem; CreativeML OpenRAIL++-M |
| Experiment | 3 candidates for pose 02 (worried, looking at phone) from the same approved reference: A and B from Qwen-Image-Edit (different seeds), C from SDXL |
| First configuration to test | RunPod L40S 48 GB, ComfyUI, pinned Qwen-Image-Edit checkpoint, temporary storage, destroyed afterwards. RTX 4090 24 GB is the cheaper alternative if the exact quantised workflow fits |

The stated goal is to find out whether AI can reliably create new poses **without changing the approved character**, not to produce attractive images.

## 2. Providers (ChatGPT's figures)

- **RunPod** (published 2026-11-09):
  - GPU rates: RTX 3090 $0.50/h, RTX 4090 $0.89/h, L40S $1.09/h, RTX 5090 $1.19/h.
  - Volume storage: $0.10/GB/month while running, $0.20 while idle.
  - Hosted Qwen Image Edit API: $0.02 per request.
- **Vast.ai:** marketplace rates, e.g. about $0.13/h for an RTX 4090. Host reliability varies. Storage keeps billing until the instance is **destroyed**, not merely stopped.
- **Modal:** per-second billing; L40S about $1.95/h, A100 80 GB about $2.50/h.

## 3. Evaluation criteria (ChatGPT)

- **Visual criteria:**
  - character identity;
  - head and face (shape, eyes, brows);
  - outfit (rust turtleneck);
  - body proportions;
  - pose accuracy;
  - visual style (not a redesign).
- **Technical integrity:** dimensions, transparency, clean edges.
- **Recorded for every candidate:**
  - model, revision and checkpoint hash;
  - ComfyUI workflow and its hash;
  - reference pack ID and hash;
  - prompt, seed, size and settings;
  - GPU, runtime and cost;
  - output SHA-256;
  - validation results and human review.

## 4. Cost (ChatGPT, planning estimate)

- **GPU compute:** 1–2 hours costs $0.89–$2.18 (RTX 4090 to L40S at RunPod's published rates).
- **Not included:** storage, transfer and setup. The total is **not confirmed**.
- **Authorised spend:** $0.

## 5. Safeguards (ChatGPT, matching what the studio already enforces)

1. Generate from the approved reference pack.
2. Save to quarantine with hashes and provenance.
3. Run automated validation.
4. Human review of each candidate, with a note.
5. A registry proposal only for approved, eligible candidates.
6. Promotion is a separate owner decision.
7. Becoming the default version needs a preview render **and** a separate owner approval.

## 6. Technical review against this repository (Claude Code, 2026-11-13)

Facts checked locally, at no cost, that AP-84B3-D1 should build in:

1. **Edit input.**
   - Master v3 (`candidate-04_corrected-v3.png`) is **1024×1536**, the owner-approved generated-pose canvas, on a **flat grey background** (RGB ≈ 203,203,203). It is the natural input for Qwen-Image-Edit.
   - The canon scene (941×1672, character inside a room) is an identity reference, not an edit input.
2. **Transparency is a separate, local step.**
   - Edit models return opaque images. The studio validator *fails* a pose without a transparent background.
   - The project already has a local, deterministic cut-out tool for exactly this background: `bible/concepts/src/ap72-cutout.cjs`. It removes flat grey by flood fill, protects the eye whites and un-mixes the edges. AP-72 validated it on master v3.
   - D1 should therefore:
     - ask the model to keep the plain flat grey background;
     - cut out locally at $0;
     - validate the cut-out;
     - keep the raw output and the cut-out as separate, hashed files.
3. **Resolution.**
   - Master v3 cut out at full size gives a figure **1293 px** tall, above the validator's 1000 px soft-close-up threshold (the current poses are about 550–575 px).
   - Generating at 1024×1536 directly addresses the open soft close-ups concern.
4. **SDXL needs more than SDXL.**
   - 1024×1536 is not a native SDXL resolution (portrait is normally 832×1216), so D1 must say whether to generate at 832×1216 and upscale, or accept the quality risk.
   - "Reference-guided" SDXL normally means IP-Adapter (and possibly ControlNet for the pose). Those are **additional models with their own licences and sizes**, which D1 must pin like the main checkpoints.
5. **A built-in control.**
   - Pose 02 already exists as an approved working asset.
   - Each candidate can be judged side by side against the approved pose 02, both by a person and by the validator's palette, proportion and feet checks.
   - A generated pose 02 would be proposed as **v2**, and could never replace v1 without the promotion and make-current gates.
6. **Getting outputs into the studio.**
   - The studio only accepts candidates through a generation adapter. Only `none` and `fake` exist today, and fake fixtures can never be promoted.
   - A real experiment needs either a RunPod/ComfyUI adapter or a narrowly scoped "import" adapter that records full provenance.
   - Either is implementation work, outside D1 unless approved.
7. **Hosted API option** ($0.02 per request): cheapest, but the canon artwork leaves our control, and model revisions cannot be pinned the way a self-run checkpoint can. That weakens reproducibility. It is worth comparing in D1, not assuming.
8. **Download time is billable.** A model repository of about 57.7 GB is downloaded on rented time and stored on billed volumes. D1 should size the exact files (quantised checkpoint, text encoder, VAE, and IP-Adapter for SDXL) before any cost ceiling is set.

## 7. Decision register

| Decision | Status |
|---|---|
| Provider research | Complete (ChatGPT) |
| RunPod first, Vast.ai price challenger, Modal alternative | Recommended, not selected |
| Qwen-Image-Edit primary, SDXL 1.0 baseline | Recommended, not selected |
| Three-candidate experiment (2 Qwen, 1 SDXL, pose 02) | Proposed |
| GPU budget | **$0** |
| Provider, model and implementation, image generation | **Not authorised** |
| AP-84B3-D1: experiment specification and cost validation (pinned model manifest, workflow specification, cost ceiling proposal, test protocol; research only) | **Proposed, awaiting owner approval** |
