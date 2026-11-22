# Oddly Relatable GPU worker (docs/GPU-INFRASTRUCTURE.md §11.2): a plain OCI image with ComfyUI and a small HTTP job
# API. Nothing provider-specific: it runs on a rented pod or on our own machine (`docker run --gpus all -p 8000:8000`).
#
# Pinned inputs (the build refuses to run with any placeholder left):
#   BASE_IMAGE      CUDA runtime base, by digest
#   COMFYUI_REF     ComfyUI commit
#   nodes.lock      custom node repositories and commits
#   requirements    torch and friends by exact version (torch from the CUDA wheel index)
# Model weights are NOT in the image: the entrypoint downloads them at boot from models.lock (pinned revisions,
# SHA-256 checked), so nothing is billed for storage while no pod runs (§11.1).
ARG BASE_IMAGE=nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04@sha256:PIN-ME
FROM ${BASE_IMAGE}

ARG COMFYUI_REF=PIN-ME
ARG TORCH_VERSION=2.8.0
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu128

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 COMFYUI_DIR=/opt/ComfyUI WORKER_ROOT=/work/jobs \
    WORKER_STATE_DIR=/work/state WORKER_PORT=8000 MODELS_DIR=/models

RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv python3-pip git ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 worker

COPY nodes.lock models.lock requirements.txt /build/
RUN test "${COMFYUI_REF}" != "PIN-ME" && ! grep -q "PIN-ME" /build/nodes.lock \
    || (echo "pin COMFYUI_REF and every commit in nodes.lock before building" >&2; exit 1)

RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir torch==${TORCH_VERSION} torchvision torchaudio --index-url ${TORCH_INDEX} \
    && git clone https://github.com/Comfy-Org/ComfyUI.git ${COMFYUI_DIR} && git -C ${COMFYUI_DIR} checkout --detach ${COMFYUI_REF} \
    && /opt/venv/bin/pip install --no-cache-dir -r ${COMFYUI_DIR}/requirements.txt -r /build/requirements.txt \
    && grep -v '^#' /build/nodes.lock | while read -r name repo commit; do \
         [ -n "$name" ] || continue; \
         git clone "$repo" "${COMFYUI_DIR}/custom_nodes/$name" && git -C "${COMFYUI_DIR}/custom_nodes/$name" checkout --detach "$commit"; \
         if [ -f "${COMFYUI_DIR}/custom_nodes/$name/requirements.txt" ]; then /opt/venv/bin/pip install --no-cache-dir -r "${COMFYUI_DIR}/custom_nodes/$name/requirements.txt"; fi; \
       done \
    && mkdir -p /work /models && chown -R worker:worker /work /models ${COMFYUI_DIR}

COPY --chown=worker:worker server.py fetch_models.py entrypoint.sh /app/
COPY --chown=worker:worker models.lock /app/models.lock
USER worker
EXPOSE 8000
ENTRYPOINT ["/bin/sh", "/app/entrypoint.sh"]
