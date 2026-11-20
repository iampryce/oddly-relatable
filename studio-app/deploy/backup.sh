#!/usr/bin/env bash
# Oddly Relatable Studio backup (run on the server as the deploy user; nightly from cron, and by deploy.sh before
# every deployment). Writes to /srv/stickman/backups/<UTC timestamp>-<kind>/ (kind: nightly | deploy):
#   db.dump       PostgreSQL custom-format dump (all workflow state: ideas, scripts, approvals, jobs, publish records)
#   media.tar.gz  the work_data volume (local media storage: videos, stills, poses, voice clips)
#   SHA256SUMS    checksums of both
# Redis is not backed up: it only carries job IDs, and the worker re-announces queued jobs from PostgreSQL on start.
# Retention per kind (owner decision 2026-11-20), so frequent deploys never push out the nightly history:
#   BACKUP_KIND=nightly (the cron job): keeps the newest $KEEP_NIGHTLY nightly backups (default 7)
#   BACKUP_KIND=deploy  (default; deploy.sh, restore.sh): keeps the newest $KEEP_DEPLOY deploy-time backups (default 5)
#   Folders without a kind suffix (made before this split) count as deploy-time. KEEP, if set, still works: it sets the
#   count for the kind being written (the installed ci-deploy.sh passes it).
# Optional off-box copy: set OFFSITE_S3=s3://bucket/prefix and have the AWS CLI configured for this user.
set -euo pipefail
ROOT=${STICKMAN_ROOT:-/srv/stickman}
KIND=${BACKUP_KIND:-deploy}
case "$KIND" in
  nightly) KEEP_THIS=${KEEP_NIGHTLY:-${KEEP:-7}} ;;
  deploy)  KEEP_THIS=${KEEP_DEPLOY:-${KEEP:-5}} ;;
  *) echo "backup: BACKUP_KIND must be nightly or deploy" >&2; exit 2 ;;
esac
(( KEEP_THIS >= 1 )) || { echo "backup: keep at least 1 backup" >&2; exit 2; }
COMPOSE=(docker compose -p oddstudio --env-file "$ROOT/shared/.env" -f "$ROOT/current/studio-app/deploy/docker-compose.yml")
if grep -q "^PUBLIC_HOST=." "$ROOT/shared/.env"; then COMPOSE+=(-f "$ROOT/current/studio-app/deploy/docker-compose.public.yml"); fi
stamp=$(date -u +%Y%m%dT%H%M%SZ)
out="$ROOT/backups/$stamp-$KIND"
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
  aws s3 cp --recursive --only-show-errors "$out" "$OFFSITE_S3/$stamp-$KIND/"
  echo "backup: copied to $OFFSITE_S3/$stamp-$KIND/"
fi

# Retention: the newest $KEEP_THIS local backups of this kind (the one just written is the newest and always stays).
if [[ "$KIND" == nightly ]]; then
  ls -1d "$ROOT"/backups/*-nightly/ 2>/dev/null | sort | head -n -"$KEEP_THIS" | xargs -r rm -rf --
else
  ls -1d "$ROOT"/backups/*/ 2>/dev/null | grep -v -- '-nightly/$' | sort | head -n -"$KEEP_THIS" | xargs -r rm -rf --
fi
