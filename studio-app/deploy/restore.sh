#!/usr/bin/env bash
# Restore Oddly Relatable Studio from a backup folder made by backup.sh.
#   restore.sh /srv/stickman/backups/<stamp> [--media]
# Restores the database (always) and the media volume (with --media). Stops api/worker/web during the restore and
# starts them again afterwards. Verifies checksums first. Destructive for the current data: backup.sh runs first,
# so the state being replaced is kept as its own backup.
set -euo pipefail
ROOT=${STICKMAN_ROOT:-/srv/stickman}
src=${1:?usage: restore.sh <backup folder> [--media]}
media=${2:-}
COMPOSE=(docker compose -p oddstudio --env-file "$ROOT/shared/.env" -f "$ROOT/current/studio-app/deploy/docker-compose.yml")

( cd "$src" && sha256sum -c SHA256SUMS )
"$(dirname "$0")/backup.sh"     # keep what is about to be replaced

"${COMPOSE[@]}" stop web worker api
"${COMPOSE[@]}" exec -T postgres pg_restore -U oddstudio -d oddstudio --clean --if-exists --no-owner < "$src/db.dump"
if [[ "$media" == "--media" ]]; then
  docker run --rm -v oddstudio_work_data:/data -v "$src":/backup:ro alpine:3.20 \
    sh -c 'find /data -mindepth 1 -delete && tar -xzf /backup/media.tar.gz -C /data'
fi
"${COMPOSE[@]}" start api worker web
echo "restore: done from $src (media: ${media:-not restored})"
