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
#   BACKUP_KIND=deploy  (default; deploy.sh, restore.sh): keeps the newest $KEEP_DEPLOY deploy-time backups (default 3)
#   Folders without a kind suffix (made before this split) count as deploy-time. KEEP, if set, still works: it sets the
#   count for the kind being written (the installed ci-deploy.sh passes it).
# Nightly runs also put a copy of the database dump in /srv/stickman/db-dumps/<stamp>-nightly.dump (+ .sha256), kept
#   for $DUMP_DAYS days (default 30) by age; the newest dump is never removed. Dumps are small, so a month of database
#   history costs little while full backup folders (with media) are kept for a week.
# BACKUP_PROTECT=<folder>: never prune this folder (restore.sh protects the backup it is restoring from).
# Free space first (2026-11-23: a deploy-time backup filled the disk and was left half-written): before writing
#   anything, the backup checks that the disk holding $ROOT/backups has room for it (the media volume's size, without
#   work/uploads, since video barely compresses; twice the last database dump, at least 64 MB), plus $BACKUP_EXTRA_FREE
#   (deploy.sh passes room for the image build) and $BACKUP_HEADROOM left free afterwards (default 2G, so the database
#   and the studio can still write). If not, it stops with exit code 3 and a clear message, and writes nothing.
# A backup that fails part-way removes its own incomplete folder (only the one this run created); every other backup
#   stays. Only complete backups (with SHA256SUMS) count towards the retention, and the one just made is never removed.
# Never touches a Docker volume: the media volume is only ever mounted read-only.
# Optional off-box copy: set OFFSITE_S3=s3://bucket/prefix and have the AWS CLI configured for this user.
set -euo pipefail
ROOT=${STICKMAN_ROOT:-/srv/stickman}
KIND=${BACKUP_KIND:-deploy}
case "$KIND" in
  nightly) KEEP_THIS=${KEEP_NIGHTLY:-${KEEP:-7}} ;;
  deploy)  KEEP_THIS=${KEEP_DEPLOY:-${KEEP:-3}} ;;
  *) echo "backup: BACKUP_KIND must be nightly or deploy" >&2; exit 2 ;;
esac
(( KEEP_THIS >= 1 )) || { echo "backup: keep at least 1 backup" >&2; exit 2; }
DUMP_DAYS=${DUMP_DAYS:-30}
(( DUMP_DAYS >= 1 )) || { echo "backup: DUMP_DAYS must be at least 1" >&2; exit 2; }
PROTECT=$( [[ -n "${BACKUP_PROTECT:-}" && -d "$BACKUP_PROTECT" ]] && cd "$BACKUP_PROTECT" && pwd -P || true)
COMPOSE=(docker compose -p oddstudio --env-file "$ROOT/shared/.env" -f "$ROOT/current/studio-app/deploy/docker-compose.yml")
if grep -q "^PUBLIC_HOST=." "$ROOT/shared/.env"; then COMPOSE+=(-f "$ROOT/current/studio-app/deploy/docker-compose.public.yml"); fi
MEDIA_VOLUME=${MEDIA_VOLUME:-oddstudio_work_data}
mkdir -p "$ROOT/backups"
complete() { [[ -f "$1/SHA256SUMS" ]]; }                       # a finished backup (the checksums are written last)
human() { numfmt --to=iec "$1"; }                               # as df -h writes sizes

# ---------------------------------------------------------------- free space, before anything is written
to_bytes() { numfmt --from=iec "${1%B}" 2>/dev/null || { echo "backup: $2 must be a size such as 2G (got '$1')" >&2; exit 2; }; }
headroom=$(to_bytes "${BACKUP_HEADROOM:-2G}" BACKUP_HEADROOM)
extra=$(to_bytes "${BACKUP_EXTRA_FREE:-0}" BACKUP_EXTRA_FREE)
last=$(for b in $(ls -1d "$ROOT"/backups/*/ 2>/dev/null | sort -r); do if complete "$b"; then echo "${b%/}"; break; fi; done)
# the media volume as the archive will read it (work/uploads is left out); if it cannot be measured, the last backup's
# archive stands in for it
media=$(docker run --rm -v "$MEDIA_VOLUME":/data:ro alpine:3.20 \
          sh -c 'a=$(du -sk /data | cut -f1); u=$(du -sk /data/work/uploads 2>/dev/null | cut -f1); echo $(( (a - ${u:-0}) * 1024 ))' \
          2>/dev/null | tail -n 1 || true)
[[ "$media" =~ ^[0-9]+$ ]] || media=$( [[ -n "$last" ]] && stat -c %s "$last/media.tar.gz" 2>/dev/null || echo 0)
db=$( [[ -n "$last" ]] && stat -c %s "$last/db.dump" 2>/dev/null || echo 0)
db=$(( db * 2 > 67108864 ? db * 2 : 67108864 ))
need=$(( media + db + extra + headroom ))
avail=$(df -B1 --output=avail "$ROOT/backups" | tail -n 1 | tr -d ' ')
if (( avail < need )); then
  echo "backup: not enough free disk space for a $KIND backup: need about $(human "$need") free on the disk holding" \
       "$ROOT/backups (media about $(human "$media"), database about $(human "$db")$( (( extra )) && echo ", $(human "$extra") for the deploy's image build"), $(human "$headroom") left free afterwards), have $(human "$avail")." >&2
  echo "backup: nothing was written and no backup was removed. Free some space first (maintenance.sh, without options, lists what it can remove), then run it again." >&2
  exit 3
fi

# a new folder, never another backup's (two backups in the same second: the second waits for the next stamp)
for try in 1 2 3; do
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  out="$ROOT/backups/$stamp-$KIND"
  [[ -e "$out" ]] || break
  sleep 1
done
umask 077
mkdir "$out"                                   # fails if it exists: this run only ever removes the folder it created
finished=0
discard_partial() {
  (( finished )) && return 0
  rm -rf -- "$out"
  echo "backup: failed part-way; removed the incomplete $out (no other backup was touched)" >&2
}
trap discard_partial EXIT

"${COMPOSE[@]}" exec -T postgres pg_dump -U oddstudio -d oddstudio -Fc > "$out/db.dump"
# Media: read the volume through a throwaway container (no host path assumptions).
docker run --rm -v "$MEDIA_VOLUME":/data:ro -v "$out":/backup alpine:3.20 \
  tar -czf /backup/media.tar.gz --exclude=./work/uploads -C /data .
test -s "$out/db.dump" || { echo "backup: empty database dump" >&2; exit 1; }
test -s "$out/media.tar.gz" || { echo "backup: empty media archive" >&2; exit 1; }
( cd "$out" && sha256sum db.dump media.tar.gz > SHA256SUMS )
finished=1
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

# Retention: the newest $KEEP_THIS complete local backups of this kind (the one just written is the newest and always
# stays; BACKUP_PROTECT is never removed). An incomplete folder (no SHA256SUMS: left by a run that was killed, or a
# backup still being written by another run) is neither counted nor removed.
if [[ "$KIND" == nightly ]]; then
  mine=$(ls -1d "$ROOT"/backups/*-nightly/ 2>/dev/null | sort || true)
else
  mine=$(ls -1d "$ROOT"/backups/*/ 2>/dev/null | grep -v -- '-nightly/$' | sort || true)
fi
pick=$(while read -r b; do if [[ -n "$b" ]] && complete "$b"; then echo "$b"; fi; done <<< "$mine" | head -n -"$KEEP_THIS" || true)
while read -r b; do
  if [[ -n "$b" && "$b" != "$out/" ]] && ! complete "$b"; then echo "backup: $b is incomplete (no SHA256SUMS); not counted and not removed"; fi
done <<< "$mine"
while read -r b; do
  [[ -z "$b" || "$b" == "$out/" ]] && continue                                   # never the backup just made
  [[ -n "$PROTECT" && "$(cd "$b" && pwd -P)" == "$PROTECT" ]] && { echo "backup: keeping $b (being restored from)"; continue; }
  rm -rf -- "$b"
done <<< "$pick"
