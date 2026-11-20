#!/usr/bin/env bash
# Weekly housekeeping for Oddly Relatable Studio (owner-approved plan, 2026-11-20). See studio-app/docs/MAINTENANCE.md.
#
#   maintenance.sh            DRY RUN (default): lists what would be removed and how much space it would free
#   maintenance.sh --apply    removes it
#
# Keeps:  the current release, every release whose images a running container uses, and the newest $KEEP_RELEASES
#         release folders (with their oddstudio-api/web images, so rollback.sh keeps working); the newest
#         $KEEP_NIGHTLY nightly and $KEEP_DEPLOY deploy-time backups (counted separately; the newest backup is never
#         removed); database dumps in $ROOT/db-dumps younger than $DUMP_DAYS days (never the newest dump); deploy logs
#         younger than $LOG_DAYS days.
#         Upload leftovers (work/uploads in the media volume: a video whose audio was never extracted, hint frames)
#         are removed after $UPLOAD_HOURS hours (default 24); nothing else in the media volume is touched.
# Never touches: $ROOT/incoming, $ROOT/shared, $ROOT/repo, Docker volumes (database, media) except work/uploads, running
#         containers.
set -euo pipefail
ROOT=${STICKMAN_ROOT:-/srv/stickman}
KEEP_RELEASES=${KEEP_RELEASES:-5}
KEEP_NIGHTLY=${KEEP_NIGHTLY:-7}
KEEP_DEPLOY=${KEEP_DEPLOY:-5}
DUMP_DAYS=${DUMP_DAYS:-30}
LOG_DAYS=${LOG_DAYS:-30}
BUILD_CACHE_HOURS=${BUILD_CACHE_HOURS:-168}
JOURNAL_MAX=${JOURNAL_MAX:-100M}
UPLOAD_HOURS=${UPLOAD_HOURS:-24}
MEDIA_VOLUME=${MEDIA_VOLUME:-oddstudio_work_data}
APPLY=0
case "${1:-}" in
  --apply) APPLY=1 ;;
  ""|--dry-run) ;;
  *) echo "usage: maintenance.sh [--apply]" >&2; exit 2 ;;
esac
(( KEEP_RELEASES >= 2 )) || { echo "maintenance: KEEP_RELEASES must be at least 2 (current + one rollback)" >&2; exit 2; }
(( KEEP_NIGHTLY >= 1 && KEEP_DEPLOY >= 1 )) || { echo "maintenance: keep at least 1 backup of each kind" >&2; exit 2; }
(( DUMP_DAYS >= 1 )) || { echo "maintenance: DUMP_DAYS must be at least 1" >&2; exit 2; }
(( UPLOAD_HOURS >= 1 )) || { echo "maintenance: UPLOAD_HOURS must be at least 1" >&2; exit 2; }

mode=$([[ $APPLY == 1 ]] && echo "APPLY" || echo "DRY RUN")
echo "maintenance ($mode) $(date -u +%Y-%m-%dT%H:%M:%SZ); disk: $(df -h / | awk 'NR==2 {print $3 " used of " $2 " (" $5 "), " $4 " free"}')"
remove() {   # remove <label> <command...>: only with --apply
  local label=$1; shift
  if [[ $APPLY == 1 ]]; then "$@" && echo "  removed  $label" || echo "  FAILED   $label" >&2
  else echo "  would remove  $label"; fi
}

# ---------------------------------------------------------------- releases
current=$(basename "$(readlink -f "$ROOT/current")")
[[ -n "$current" && -d "$ROOT/releases/$current" ]] || { echo "maintenance: cannot resolve the current release; stopping" >&2; exit 1; }
declare -A keep=(["$current"]=1)
while read -r tag; do [[ -n "$tag" ]] && keep[$tag]=1; done < <(
  docker ps --format '{{.Image}}' | sed -n 's/^oddstudio-\(api\|web\):\(.*\)$/\2/p' | sort -u)
while read -r rel; do keep[$rel]=1; done < <(ls -1t "$ROOT/releases" | head -n "$KEEP_RELEASES")
echo "releases: keeping ${#keep[@]} (current $current)"
for rel in $(ls -1t "$ROOT/releases"); do
  [[ -n "${keep[$rel]:-}" ]] && continue
  remove "release $rel ($(du -sh "$ROOT/releases/$rel" | cut -f1))" rm -rf -- "$ROOT/releases/$rel"
done

# ---------------------------------------------------------------- images and build cache
echo "images:"
for repo in oddstudio-api oddstudio-web; do
  while read -r tag; do
    [[ -z "$tag" || -n "${keep[$tag]:-}" ]] && continue
    remove "image $repo:$tag" docker image rm "$repo:$tag"
  done < <(docker images "$repo" --format '{{.Tag}}')
done
for img in hello-world:latest nginx:1.27-alpine; do
  docker image inspect "$img" >/dev/null 2>&1 || continue
  [[ -n "$(docker ps -a -q --filter "ancestor=$img")" ]] && continue      # used by a container (even stopped): keep
  remove "unused image $img" docker image rm "$img"
done
echo "  dangling images and build cache older than ${BUILD_CACHE_HOURS} h: $(docker system df --format '{{.Type}} {{.Reclaimable}}' | tr '\n' ';')"
if [[ $APPLY == 1 ]]; then
  docker image prune -f >/dev/null
  docker builder prune -f --filter "until=${BUILD_CACHE_HOURS}h" >/dev/null
  echo "  pruned dangling images and old build cache"
fi

# ---------------------------------------------------------------- backups
echo "backups: keeping the newest $KEEP_NIGHTLY nightly and $KEEP_DEPLOY deploy-time (unsuffixed folders count as deploy-time)"
newest=$(ls -1d "$ROOT"/backups/*/ 2>/dev/null | sort | tail -n 1)
prune_kind() {   # prune_kind <keep> <folders, oldest first>
  local keep=$1; shift
  local list=("$@")
  (( ${#list[@]} > keep )) || return 0
  for b in "${list[@]:0:${#list[@]}-keep}"; do
    [[ "$b" == "$newest" ]] && continue                                     # never the newest backup
    remove "backup $(basename "$b") ($(du -sh "$b" | cut -f1))" rm -rf -- "$b"
  done
}
mapfile -t nightly < <(ls -1d "$ROOT"/backups/*-nightly/ 2>/dev/null | sort)
mapfile -t deploys < <(ls -1d "$ROOT"/backups/*/ 2>/dev/null | grep -v -- '-nightly/$' | sort)
prune_kind "$KEEP_NIGHTLY" "${nightly[@]}"
prune_kind "$KEEP_DEPLOY" "${deploys[@]}"

# ---------------------------------------------------------------- the 30-day database-dump folder
dumps="$ROOT/db-dumps"
if [[ -d "$dumps" ]]; then
  newest_dump=$(ls -1 "$dumps"/*.dump 2>/dev/null | sort | tail -n 1)
  echo "database dumps: $(ls -1 "$dumps"/*.dump 2>/dev/null | wc -l) in $dumps ($(du -sh "$dumps" | cut -f1)); keeping $DUMP_DAYS days and always the newest ($(basename "${newest_dump:-none}"))"
  while read -r f; do
    [[ -z "$f" || "$f" == "$newest_dump" ]] && continue
    remove "dump $(basename "$f") ($(du -sh "$f" | cut -f1))" rm -f -- "$f" "$f.sha256"
  done < <(find "$dumps" -maxdepth 1 -type f -name '*.dump' -mmin +$(( DUMP_DAYS * 1440 )) | sort)
else
  echo "database dumps: none yet ($dumps is created by the first nightly backup)"
fi

# ---------------------------------------------------------------- upload leftovers (work/uploads in the media volume)
echo "uploads: leftovers older than $UPLOAD_HOURS h in work/uploads"
if docker volume inspect "$MEDIA_VOLUME" >/dev/null 2>&1; then
  while read -r f; do
    [[ -z "$f" ]] && continue
    remove "upload leftover $f" docker run --rm -v "$MEDIA_VOLUME:/data" alpine:3.20 rm -rf -- "/data/work/uploads/$f"
  done < <(docker run --rm -v "$MEDIA_VOLUME:/data:ro" alpine:3.20 \
             find /data/work/uploads -mindepth 1 -maxdepth 1 -mmin +$(( UPLOAD_HOURS * 60 )) -exec basename {} \; 2>/dev/null | sort)
else
  echo "  media volume $MEDIA_VOLUME not found; skipped"
fi

# ---------------------------------------------------------------- logs
echo "logs: deploy logs older than $LOG_DAYS days, journal above $JOURNAL_MAX"
while read -r f; do remove "log $(basename "$f")" rm -f -- "$f"; done < <(
  find "$ROOT" -maxdepth 1 -type f \( -name 'deploy-*.log' -o -name 'ci-deploy-*.log' \) -mtime +"$LOG_DAYS")
if [[ $APPLY == 1 ]]; then journalctl --vacuum-size="$JOURNAL_MAX" >/dev/null 2>&1 || true
else echo "  journal now: $(journalctl --disk-usage 2>/dev/null | grep -o '[0-9.]*[KMG]' | head -1 || echo unknown)"; fi

echo "done ($mode); disk: $(df -h / | awk 'NR==2 {print $3 " used of " $2 " (" $5 "), " $4 " free"}')"
