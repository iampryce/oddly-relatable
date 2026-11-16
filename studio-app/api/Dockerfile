# API and worker image. Build context: the repository root (the worker runs the existing Node production engine).
#   docker build -f studio-app/api/Dockerfile -t oddstudio-api .
FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv ffmpeg fonts-dejavu-core ca-certificates \
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
COPY studio-app/api/ studio-app/api/
ENV PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1 ODD_REPO_ROOT=/app ODD_WORK_DIR=/data/work FFMPEG=/usr/bin/ffmpeg FFPROBE=/usr/bin/ffprobe
RUN mkdir -p /data/work && chown -R studio /data
USER studio
WORKDIR /app/studio-app/api
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn oddstudio.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
