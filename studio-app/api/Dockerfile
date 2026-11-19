# API and worker image. Build context: the repository root (the worker runs the existing Node production engine).
#   docker build -f studio-app/api/Dockerfile -t oddstudio-api .
FROM node:22-trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv ffmpeg fonts-dejavu-core ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 studio
WORKDIR /app
# Renderer runtime (its own pinned dependencies, installed for Linux).
COPY skills/directing-stickman-videos/package.json skills/directing-stickman-videos/package-lock.json skills/directing-stickman-videos/
RUN cd skills/directing-stickman-videos && npm ci --omit=dev && npm cache clean --force
COPY skills/directing-stickman-videos/ skills/directing-stickman-videos/
# Production engine, registries and the approved artwork they reference (read-only in the container).
COPY production/ production/
COPY bible/concepts/lookdev-richenv/ bible/concepts/lookdev-richenv/
# Python API and worker.
COPY studio-app/api/requirements.txt studio-app/api/requirements.txt
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir -r studio-app/api/requirements.txt
# Piper (free local voices) and the house voice models, found by file name (PIPER_VOICES_DIR).
RUN /venv/bin/pip install --no-cache-dir piper-tts==1.8.0 && mkdir -p /app/voices && cd /app/voices \
    && for v in en_US/ryan/medium/en_US-ryan-medium en_US/joe/medium/en_US-joe-medium en_US/amy/medium/en_US-amy-medium \
                en_US/lessac/medium/en_US-lessac-medium en_GB/alan/medium/en_GB-alan-medium; do \
         n=$(basename $v); \
         curl -fsSL -o $n.onnx https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/$v.onnx \
         && curl -fsSL -o $n.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/$v.onnx.json; \
       done && ls /app/voices | grep -c onnx.json
# Rhubarb Lip Sync (free, MIT): audio-driven mouth shapes. Local transcription: faster-whisper (CPU, int8); its model
# is downloaded on first use into the data volume (WHISPER_CACHE).
RUN curl -fsSL -o /tmp/rhubarb.zip https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v1.14.0/Rhubarb-Lip-Sync-1.14.0-Linux.zip     && /venv/bin/python -m zipfile -e /tmp/rhubarb.zip /opt/ && mv /opt/Rhubarb-Lip-Sync-1.14.0-Linux /opt/rhubarb     && chmod +x /opt/rhubarb/rhubarb && rm /tmp/rhubarb.zip     && /venv/bin/pip install --no-cache-dir faster-whisper==1.2.1 kokoro-onnx==0.4.7
# Codex CLI (ChatGPT subscription): sign in once on the server, the login is kept in the data volume (CODEX_HOME).
RUN npm install -g @openai/codex@0.167.0 && npm cache clean --force
COPY studio-app/api/ studio-app/api/
ENV PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1 ODD_REPO_ROOT=/app ODD_WORK_DIR=/data/work FFMPEG=/usr/bin/ffmpeg FFPROBE=/usr/bin/ffprobe \
    PIPER_BIN=/venv/bin/piper PIPER_VOICES_DIR=/app/voices CODEX_HOME=/data/codex \
    RHUBARB_BIN=/opt/rhubarb/rhubarb WHISPER_CACHE=/data/models KOKORO_DIR=/data/models/kokoro
RUN mkdir -p /data/work /data/codex /data/models && chown -R studio /data
USER studio
WORKDIR /app/studio-app/api
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn oddstudio.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
