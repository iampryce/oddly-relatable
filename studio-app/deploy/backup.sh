#!/usr/bin/env bash
# Oddly Relatable Studio backup (run on the server as the deploy user; nightly from cron, and by deploy.sh before
# every deployment). Writes to /srv/stickman/backups/<UTC timestamp>-<kind>/ (kind: nightly | deploy):
#   db.dump       PostgreSQL custom-format dump (all workflow state: ideas, scripts, approvals, jobs, publish records)
#   media.tar.gz  the work_data volume (local media storage: videos, stills, poses, voice clips), without work/uploads
#                 (temporary upload files: a video waiting for its audio to be extracted, sampled frames)
#   SHA256SUMS    checksums of both
# Redis is not backed up: it only carries job IDs, and the worker re-announces queued jobs from PostgreSQL on start.
# Retention per kind (owner decision 2026-11-20), so frequent deploys never push out the nightly history:
#   BACKUP_KIND=nightly (the cron job): keeps the newest $KEEP_NIGHTLY nightly backups (default 7)
#   BACKUP_KIND=deploy  (default; deploy.sh, restore.sh): keeps the newest $KEEP_DEPLOY deploy-time backups (default 5)
#   Folders without a kind suffix (made before this split) count as deploy-time. KEEP, if set, still works: it sets the
#   count for the kind being written (the installed ci-deploy.sh passes it).
# Nightly runs also put a copy of the database dump in /srv/stickman/db-dumps/<stamp>-nightly.dump (+ .sha256), kept
#   for $DUMP_DAYS days (default 30) by age; the newest dump is never removed. Dumps are small, so a month of database
#   history costs little while full backup folders (with media) are kept for a week.
# BACKUP_PROTECT=<folder>: never prune this folder (restore.sh protects the backup it is restoring from).
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
DUMP_DAYS=${DUMP_DAYS:-30}
(( DUMP_DAYS >= 1 )) || { echo "backup: DUMP_DAYS must be at least 1" >&2; exit 2; }
PROTECT=$( [[ -n "${BACKUP_PROTECT:-}" && -d "$BACKUP_PROTECT" ]] && cd "$BACKUP_PROTECT" && pwd -P || true)
COMPOSE=(docker compose -p oddstudio --env-file "$ROOT/shared/.env" -f "$ROOT/current/studio-app/deploy/docker-compose.yml")
if grep -q "^PUBLIC_HOST=." "$ROOT/shared/.env"; then COMPOSE+=(-f "$ROOT/current/studio-app/deploy/docker-compose.public.yml"); fi
stamp=$(date -u +%Y%m%dT%H%M%SZ)
out="$ROOT/backups/$stamp-$KIND"
umask 077
mkdir -p "$out"

"${COMPOSE[@]}" exec -T postgres pg_dump -U oddstudio -d oddstudio -Fc > "$out/db.dump"
# Media: read the volume through a throwaway container (no host path assumptions).
docker run --rm -v oddstudio_work_data:/data:ro -v "$out":/backup alpine:3.20 \
  tar -czf /backup/media.tar.gz --exclude=./work/uploads -C /data .
( cd "$out" && sha256sum db.dump media.tar.gz > SHA256SUMS )
test -s "$out/db.dump" || { echo "backup: empty database dump" >&2; exit 1; }
echo "backup: $out ($(du -sh "$out" | cut -f1))"

if [[ -n "${OFFSITE_S3:-}" ]]; then
  aws s3 cp --recursive --only-show-errors "$out" "$OFFSITE_S3/$stamp-$KIND/"
  echo "backup: copied to $OFFSITE_S3/$stamp-$KIND/"
fi

# The 30-day database-dump folder (nightly only): a copy of this dump, then pruning by age (never the newest dump).
if [[ "$KIND" == nightly ]]; then
  dumps="$ROOT/db-dumps"
  mkdir -p "$dumps"
  cp "$out/db.dump" "$dumps/$stamp-nightly.dump"
  ( cd "$dumps" && sha256sum "$stamp-nightly.dump" > "$stamp-nightly.dump.sha256" )
  newest_dump=$(ls -1 "$dumps"/*.dump 2>/dev/null | sort | tail -n 1)
  while read -r f; do
    [[ -z "$f" || "$f" == "$newest_dump" ]] && continue
    rm -f -- "$f" "$f.sha256"
  done < <(find "$dumps" -maxdepth 1 -type f -name '*.dump' -mmin +$(( DUMP_DAYS * 1440 )))
  echo "backup: database dump kept in $dumps/$stamp-nightly.dump (dumps older than $DUMP_DAYS days are pruned)"
fi

# Retention: the newest $KEEP_THIS local backups of this kind (the one just written is the newest and always stays;
# BACKUP_PROTECT is never removed).
if [[ "$KIND" == nightly ]]; then
  pick=$(ls -1d "$ROOT"/backups/*-nightly/ 2>/dev/null | sort | head -n -"$KEEP_THIS" || true)
else
  pick=$(ls -1d "$ROOT"/backups/*/ 2>/dev/null | grep -v -- '-nightly/$' | sort | head -n -"$KEEP_THIS" || true)
fi
while read -r b; do
  [[ -z "$b" ]] && continue
  [[ -n "$PROTECT" && "$(cd "$b" && pwd -P)" == "$PROTECT" ]] && { echo "backup: keeping $b (being restored from)"; continue; }
  rm -rf -- "$b"
done <<< "$pick"
