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
#         The Docker build cache is kept at most $BUILD_CACHE_MAX (default 10GB, least recently used goes first), on
#         top of the age rule ($BUILD_CACHE_HOURS h): frequent deploys keep the cache "recent", so age alone frees nothing.
# Never touches: $ROOT/incoming, $ROOT/shared, $ROOT/repo, Docker volumes (database, media) except work/uploads, running
#         containers.
# --apply holds the deploy lock ($ROOT/.ci-deploy.lock, the one ci-deploy.sh takes). If a deploy is running, the
#         releases, images and build-cache steps are skipped (a deploy builds images and switches releases); the
#         rest (backups, dumps, uploads, logs) still runs. A deploy that starts meanwhile waits for nothing: it fails
#         with "another deploy is running" and can be re-run.
# The dry run ends with the projected free space after --apply (releases + unused images + build cache above the cap).
set -euo pipefail
ROOT=${STICKMAN_ROOT:-/srv/stickman}
KEEP_RELEASES=${KEEP_RELEASES:-5}
KEEP_NIGHTLY=${KEEP_NIGHTLY:-7}
KEEP_DEPLOY=${KEEP_DEPLOY:-3}
DUMP_DAYS=${DUMP_DAYS:-30}
LOG_DAYS=${LOG_DAYS:-30}
BUILD_CACHE_HOURS=${BUILD_CACHE_HOURS:-168}
BUILD_CACHE_MAX=${BUILD_CACHE_MAX:-10GB}
DEPLOY_LOCK=${DEPLOY_LOCK:-$ROOT/.ci-deploy.lock}
JOURNAL_MAX=${JOURNAL_MAX:-100M}
UPLOAD_HOURS=${UPLOAD_HOURS:-24}
MEDIA_VOLUME=${MEDIA_VOLUME:-oddstudio_work_data}
BIN_DAYS=${BIN_DAYS:-30}
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

to_bytes() {   # "10.76GB" / "111.5MB (2%)" / "10GB" -> bytes (Docker's decimal units)
  awk -v s="${1%% *}" 'BEGIN { if (!match(s, /[A-Za-z]+$/)) { printf "%.0f", s + 0; exit }
    n = substr(s, 1, RSTART - 1); u = substr(s, RSTART)
    f = (u == "kB" || u == "KB") ? 1e3 : (u == "MB") ? 1e6 : (u == "GB") ? 1e9 : (u == "TB") ? 1e12 : 1
    printf "%.0f", n * f }'; }
gb() { awk -v b="$1" 'BEGIN { printf "%.1f GB", b / 1e9 }'; }          # Docker's units (decimal)
gib() { awk -v b="$1" 'BEGIN { printf "%.0fG", b / 1073741824 }'; }     # df -h's units, for the disk lines
cache_max=$(to_bytes "$BUILD_CACHE_MAX")
(( cache_max > 0 )) || { echo "maintenance: BUILD_CACHE_MAX must be a size such as 10GB" >&2; exit 2; }

# A deploy builds images and switches releases: never remove those under it. --apply holds the deploy lock for the run.
deploying=0
if [[ $APPLY == 1 ]]; then
  exec 9>>"$DEPLOY_LOCK"
  flock -n 9 || deploying=1
elif ! flock -n "$DEPLOY_LOCK" true 2>/dev/null; then
  deploying=1
fi
docker_steps() { (( ! deploying )); }
freed=0      # bytes the dry run expects --apply to free (releases, unused images, build cache above the cap)

mode=$([[ $APPLY == 1 ]] && echo "APPLY" || echo "DRY RUN")
echo "maintenance ($mode) $(date -u +%Y-%m-%dT%H:%M:%SZ); disk: $(df -h / | awk 'NR==2 {print $3 " used of " $2 " (" $5 "), " $4 " free"}')"
(( deploying )) && echo "a deploy is running (deploy lock held): releases, images and the build cache are skipped this time"
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
  docker_steps || { echo "  skipped  release $rel (deploy running)"; continue; }
  freed=$(( freed + $(du -sb "$ROOT/releases/$rel" | cut -f1) ))
  remove "release $rel ($(du -sh "$ROOT/releases/$rel" | cut -f1))" rm -rf -- "$ROOT/releases/$rel"
done

# ---------------------------------------------------------------- images and build cache
echo "images:"
sysdf=$(docker system df --format '{{.Type}}|{{.Size}}|{{.Reclaimable}}')
if docker_steps; then
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
  # images no running container uses (the removed releases' images among them): Docker's own estimate, shared layers
  # counted once
  freed=$(( freed + $(to_bytes "$(sed -n 's/^Images|[^|]*|//p' <<< "$sysdf")") ))
else
  echo "  skipped (deploy running)"
fi
echo "  dangling images and build cache older than ${BUILD_CACHE_HOURS} h: $(docker system df --format '{{.Type}} {{.Reclaimable}}' | tr '\n' ';')"
cache=$(to_bytes "$(sed -n 's/^Build Cache|\([^|]*\)|.*/\1/p' <<< "$sysdf")")
over=$(( cache > cache_max ? cache - cache_max : 0 ))
echo "build cache: $(gb "$cache") now, kept at most $BUILD_CACHE_MAX$( (( over )) && echo "; would trim about $(gb "$over")")"
if docker_steps; then
  freed=$(( freed + over ))
  if [[ $APPLY == 1 ]]; then
    docker image prune -f >/dev/null
    docker builder prune -f --filter "until=${BUILD_CACHE_HOURS}h" >/dev/null
    docker builder prune -f --max-used-space "$BUILD_CACHE_MAX" >/dev/null
    echo "  pruned dangling images, build cache older than ${BUILD_CACHE_HOURS} h, and the cache above $BUILD_CACHE_MAX"
  fi
else
  echo "  skipped (deploy running)"
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
# only complete backups (with SHA256SUMS) are counted and pruned; an incomplete folder is listed and left alone
for b in $(ls -1d "$ROOT"/backups/*/ 2>/dev/null | sort); do
  [[ -f "$b/SHA256SUMS" ]] || echo "  incomplete $(basename "$b") ($(du -sh "$b" | cut -f1)): no SHA256SUMS; not counted, not removed (check it, then remove it by hand)"
done
mapfile -t nightly < <(for b in $(ls -1d "$ROOT"/backups/*-nightly/ 2>/dev/null | sort); do [[ -f "$b/SHA256SUMS" ]] && echo "$b"; done)
mapfile -t deploys < <(for b in $(ls -1d "$ROOT"/backups/*/ 2>/dev/null | grep -v -- '-nightly/$' | sort); do [[ -f "$b/SHA256SUMS" ]] && echo "$b"; done)
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

# ---------------------------------------------------------------- the Bin (items deleted in the studio > BIN_DAYS ago)
# Runs inside the API container (it has the database): rows and files of items in the Bin for more than BIN_DAYS days
# are removed for good with --apply and each one is logged; the dry run lists them. Files are only ever removed from
# the studio's storage and work folders (the API refuses any other path).
echo "bin: items deleted in the studio more than $BIN_DAYS days ago"
api=$(docker ps --format '{{.Names}}' | grep -E '(^|[-_])api([-_][0-9]+)?$' | head -n 1)
if [[ -n "$api" ]]; then
  if [[ $APPLY == 1 ]]; then docker exec "$api" python -m oddstudio.bin purge --days "$BIN_DAYS" | sed 's/^/  /' || echo "  FAILED bin purge" >&2
  else docker exec "$api" python -m oddstudio.bin purge --days "$BIN_DAYS" --dry-run | sed 's/^/  /' || true; fi
else
  echo "  the API container is not running; skipped"
fi

# ---------------------------------------------------------------- logs
echo "logs: deploy logs older than $LOG_DAYS days, journal above $JOURNAL_MAX"
while read -r f; do remove "log $(basename "$f")" rm -f -- "$f"; done < <(
  find "$ROOT" -maxdepth 1 -type f \( -name 'deploy-*.log' -o -name 'ci-deploy-*.log' \) -mtime +"$LOG_DAYS")
if [[ $APPLY == 1 ]]; then journalctl --vacuum-size="$JOURNAL_MAX" >/dev/null 2>&1 || true
else echo "  journal now: $(journalctl --disk-usage 2>/dev/null | grep -o '[0-9.]*[KMG]' | head -1 || echo unknown)"; fi

if [[ $APPLY == 0 ]]; then
  free_now=$(( $(df -B1 --output=avail / | tail -n 1) ))
  echo "projected free after --apply: about $(gib $(( free_now + freed ))) (now $(gib "$free_now"), as df -h counts; from releases, unused images and the build cache above $BUILD_CACHE_MAX)"
fi
echo "done ($mode); disk: $(df -h / | awk 'NR==2 {print $3 " used of " $2 " (" $5 "), " $4 " free"}')"
