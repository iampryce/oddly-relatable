#!/usr/bin/env bash
# Oddly Relatable Studio backup (run on the server as the deploy user; nightly from cron, and by deploy.sh before
# every deployment). Writes to /srv/stickman/backups/<UTC timestamp>/:
#   db.dump       PostgreSQL custom-format dump (all workflow state: ideas, scripts, approvals, jobs, publish records)
#   media.tar.gz  the work_data volume (local media storage: videos, stills, poses, voice clips)
#   SHA256SUMS    checksums of both
# Redis is not backed up: it only carries job IDs, and the worker re-announces queued jobs from PostgreSQL on start.
# Keeps the newest $KEEP backups (default 14). Optional off-box copy: set OFFSITE_S3=s3://bucket/prefix and have the AWS
# CLI configured for this user.
set -euo pipefail
ROOT=${STICKMAN_ROOT:-/srv/stickman}
KEEP=${KEEP:-14}
COMPOSE=(docker compose -p oddstudio --env-file "$ROOT/shared/.env" -f "$ROOT/current/studio-app/deploy/docker-compose.yml")
stamp=$(date -u +%Y%m%dT%H%M%SZ)
out="$ROOT/backups/$stamp"
umask 077
mkdir -p "$out"

"${COMPOSE[@]}" exec -T postgres pg_dump -U oddstudio -d oddstudio -Fc > "$out/db.dump"
# Media: read the volume through a throwaway container (no host path assumptions).
docker run --rm -v oddstudio_work_data:/data:ro -v "$out":/backup alpine:3.20 \
  tar -czf /backup/media.tar.gz -C /data .
( cd "$out" && sha256sum db.dump media.tar.gz > SHA256SUMS )
test -s "$out/db.dump" || { echo "backup: empty database dump" >&2; exit 1; }
echo "backup: $out ($(du -sh "$out" | cut -f1))"

if [[ -n "${OFFSITE_S3:-}" ]]; then
  aws s3 cp --recursive --only-show-errors "$out" "$OFFSITE_S3/$stamp/"
  echo "backup: copied to $OFFSITE_S3/$stamp/"
fi

# Retention: newest $KEEP local backups.
ls -1d "$ROOT"/backups/*/ 2>/dev/null | sort | head -n -"$KEEP" | xargs -r rm -rf --
