# GPU worker image

A plain Docker image with ComfyUI and a small HTTP job API. It is the self-hosted half of the proof of concept in
`docs/GPU-INFRASTRUCTURE.md` §11 and §16 (on the `docs/gpu-hard-requirements` branch). The same image runs on a rented
RunPod pod or on a machine we own. The studio only needs its address and token.

## What is here

| File | Purpose |
|---|---|
| `server.py` | The job API (standard library only). Auth on every call, one job at a time, idempotent submit, outputs with SHA-256, cancel and delete, a readiness gate and a self-limit |
| `entrypoint.sh` | Starts the API at once, then fetches the pinned weights and starts ComfyUI on `127.0.0.1` only. Writes `ready` or `failed` for `/health` |
| `fetch_models.py` | Downloads `models.lock` (HTTPS URLs at fixed revisions, SHA-256, licence) and checks every file. Nothing unpinned is accepted |
| `nodes.lock` | ComfyUI custom node repositories and commits |
| `Dockerfile` | CUDA runtime base by digest, ComfyUI at a commit, the nodes from `nodes.lock`. The build refuses to run with any `PIN-ME` left |

## The job API

Every call needs `Authorization: Bearer <WORKER_TOKEN>` (at least 32 characters).

| Call | Purpose |
|---|---|
| `GET /health` | Version, image digest, GPU, ready or failed, busy, queued, self-limit and seconds left |
| `POST /jobs` | `{"id", "kind": "comfyui-workflow", "workflow", "workflow_sha256", "params", "inputs": {name: base64}}`. Returns 202. The same id again returns the existing job and does not run it twice |
| `GET /jobs/<id>` | Status, log tail, `gpu_seconds`, and each output's name, size and SHA-256 |
| `GET /jobs/<id>/outputs/<name>` | One output file |
| `POST /jobs/<id>/cancel` | Cancels a queued or running job |
| `DELETE /jobs/<id>` | Deletes the job's files (the studio calls it once it has the clip) |

**The workflow graph:** it comes from the studio (`studio-app/api/oddstudio/gpu_workflows/`), so the image stays generic. A graph uses `{{input:<file name>}}` and `{{param:<key>}}` placeholders. Every placeholder must be filled, and the worker checks this before it accepts the job.

**Inputs:** files carried in the request (the first frame or clip, and the line audio). Nothing is fetched by URL.

**Self-limit:** after `WORKER_MAX_LIFETIME_S`, or `WORKER_IDLE_S` without a job, the worker refuses new jobs and reports it. It cannot stop billing: the studio terminates the pod (layers 1–3 in `studio-app/api/oddstudio/gpu.py`).

## Running it

Our own machine (the NVIDIA driver and the NVIDIA Container Toolkit installed):

```
docker run --gpus all -p 8000:8000 -e WORKER_TOKEN=<token> -v /srv/models:/models <image>@sha256:<digest>
```

Then in the studio, Settings > GPU worker: mode "Our own machine", the address, and the token under Credentials. The machine needs a way for the studio server to reach it, for example an outbound tunnel. Which tunnel is an owner decision.

A rented pod is launched by the studio itself. It uses mode "Rented", the GPU type and this image's digest, and the studio keeps the RunPod key.

Without a GPU (smoke check of the API only): `WORKER_BACKEND=stub` makes a clip from the input image with FFmpeg, with no model involved.

## Still to do before the paid proof of concept (local, $0)

1. Pin `BASE_IMAGE`, `COMFYUI_REF` and every commit in `nodes.lock`, after confirming each node repository (licence, maintained, the nodes used).
2. Write the three workflows (`infinitetalk-480p`, `wan-2.2-s2v-480p` and `latentsync-1.6`) in ComfyUI's API format with the placeholders above. Put them in `studio-app/api/oddstudio/gpu_workflows/`. Until a workflow is there, its model cannot run in the studio.
3. Fill `models.lock` with the weights those workflows load: Hugging Face URLs at fixed revisions, SHA-256 and licence. All are Apache-2.0 (§14), and the audio and text encoders' licences are to be checked.
4. Build the image and push it to a registry, then put its digest in Settings.
