#!/usr/bin/env bash
# Weekly housekeeping for Oddly Relatable Studio (owner-approved plan 2026-11-20; keep-limits 2026-11-23). See
# studio-app/docs/MAINTENANCE.md.
#
#   maintenance.sh            DRY RUN (default): lists what would be removed, with sizes, and writes the disk report
#   maintenance.sh --apply    removes it (only when the owner turns it on deliberately; the weekly cron is a dry run)
#
# Keep-limits:
#   releases  the live release, the previous $KEEP_PREVIOUS_RELEASES release folders (default 2) and any release a
#             running container uses. "Previous" is the deploy order: $ROOT/releases.log (deploy.sh and rollback.sh
#             write it), then the order the release images were built, then the folders' age. A folder that never
#             ran (a deploy that failed before building) is not a previous release.
#   images    kept: every image a container uses, the live and the previous release's oddstudio-api/web images (so
#             rollback.sh works for the previous release) and $KEEP_IMAGES (tool images the scripts run, default
#             alpine:3.20). Every other image is removed with `docker image rm`, and dangling ones with
#             `docker image prune`: never by deleting files under /var/lib/docker or /var/lib/containerd.
#   build cache  `docker builder prune` for cache older than $BUILD_CACHE_HOURS h (default 168 h = 7 days), and the
#             rest capped at $BUILD_CACHE_MAX (default 10GB; owner decision 2026-11-20).
#   journal   capped at $JOURNAL_MAX (default 200M) with journalctl --vacuum-size.
#   backups   complete backups only: the newest $KEEP_DEPLOY deploy-time (default 3, never fewer than 3) and
#             $KEEP_NIGHTLY nightly ones (none are made since 2026-11-23); the newest backup is never removed.
#   also      database dumps older than $DUMP_DAYS days (never the newest) and deploy logs older than $LOG_DAYS days.
#   listed only (never removed, not even with --apply; owner decision 2026-11-23): upload leftovers in the media
#             volume's work/uploads older than $UPLOAD_HOURS h, and Bin items older than $BIN_DAYS days (the Bin page's
#             Delete forever / Empty Bin removes those, by hand).
# Never touches: Docker volumes, the database, media, running containers, $ROOT/incoming, $ROOT/shared, $ROOT/repo.
# --apply holds the deploy lock ($ROOT/.ci-deploy.lock, the one ci-deploy.sh takes). If a deploy is running, the
#   releases, images and build-cache steps are skipped; the rest still runs.
# The disk report: every run (dry run or --apply) writes $REPORT_DIR/disk-report.json (default $ROOT/reports; the
#   studio's Overview page reads it through a read-only mount) with the disk's size, use and free space, the biggest
#   consumers (backups, releases, images, build cache, media, database, logs) and what --apply would free; and it
#   appends one line to $REPORT_DIR/disk-history.log.
set -euo pipefail
ROOT=${STICKMAN_ROOT:-/srv/stickman}
KEEP_PREVIOUS_RELEASES=${KEEP_PREVIOUS_RELEASES:-2}
KEEP_NIGHTLY=${KEEP_NIGHTLY:-7}
KEEP_DEPLOY=${KEEP_DEPLOY:-3}
DUMP_DAYS=${DUMP_DAYS:-30}
LOG_DAYS=${LOG_DAYS:-30}
BUILD_CACHE_HOURS=${BUILD_CACHE_HOURS:-168}
BUILD_CACHE_MAX=${BUILD_CACHE_MAX:-10GB}
DEPLOY_LOCK=${DEPLOY_LOCK:-$ROOT/.ci-deploy.lock}
JOURNAL_MAX=${JOURNAL_MAX:-200M}
UPLOAD_HOURS=${UPLOAD_HOURS:-24}
MEDIA_VOLUME=${MEDIA_VOLUME:-oddstudio_work_data}
DB_VOLUME=${DB_VOLUME:-oddstudio_postgres_data}
KEEP_IMAGES=${KEEP_IMAGES:-alpine:3.20}
BIN_DAYS=${BIN_DAYS:-30}
REPORT_DIR=${REPORT_DIR:-$ROOT/reports}
LOG_DIR=${LOG_DIR:-/var/log}
APPLY=0
case "${1:-}" in
  --apply) APPLY=1 ;;
  ""|--dry-run) ;;
  *) echo "usage: maintenance.sh [--apply]" >&2; exit 2 ;;
esac
(( KEEP_PREVIOUS_RELEASES >= 1 )) || { echo "maintenance: KEEP_PREVIOUS_RELEASES must be at least 1 (the rollback release)" >&2; exit 2; }
(( KEEP_DEPLOY >= 3 )) || { echo "maintenance: KEEP_DEPLOY must be at least 3 (the newest 3 deploy-time backups are never removed)" >&2; exit 2; }
(( KEEP_NIGHTLY >= 1 )) || { echo "maintenance: keep at least 1 nightly backup" >&2; exit 2; }
(( DUMP_DAYS >= 1 )) || { echo "maintenance: DUMP_DAYS must be at least 1" >&2; exit 2; }
(( UPLOAD_HOURS >= 1 )) || { echo "maintenance: UPLOAD_HOURS must be at least 1" >&2; exit 2; }

to_bytes() {   # "10.76GB" / "111.5MB (2%)" / "10GB" -> bytes (Docker's decimal units)
  awk -v s="${1%% *}" 'BEGIN { if (!match(s, /[A-Za-z]+$/)) { printf "%.0f", s + 0; exit }
    n = substr(s, 1, RSTART - 1); u = substr(s, RSTART)
    f = (u == "kB" || u == "KB") ? 1e3 : (u == "MB") ? 1e6 : (u == "GB") ? 1e9 : (u == "TB") ? 1e12 : 1
    printf "%.0f", n * f }'; }
iec_bytes() { numfmt --from=iec "${1%B}" 2>/dev/null || echo 0; }    # "185.8M" (journalctl, df -h) -> bytes
gb() { awk -v b="$1" 'BEGIN { printf "%.1f GB", b / 1e9 }'; }          # Docker's units (decimal)
gib() { awk -v b="$1" 'BEGIN { printf "%.0fG", b / 1073741824 }'; }     # df -h's units, for the disk lines
dub() { local v; v=$(du -sb "$1" 2>/dev/null | cut -f1 | head -n 1 || true); echo "${v:-0}"; }   # bytes in a folder (0 if missing)
cache_max=$(to_bytes "$BUILD_CACHE_MAX")
(( cache_max > 0 )) || { echo "maintenance: BUILD_CACHE_MAX must be a size such as 10GB" >&2; exit 2; }
journal_max=$(iec_bytes "$JOURNAL_MAX")
(( journal_max > 0 )) || { echo "maintenance: JOURNAL_MAX must be a size such as 200M" >&2; exit 2; }

# A deploy builds images and switches releases: never remove those under it. --apply holds the deploy lock for the run.
deploying=0
if [[ $APPLY == 1 ]]; then
  exec 9>>"$DEPLOY_LOCK"
  flock -n 9 || deploying=1
elif ! flock -n "$DEPLOY_LOCK" true 2>/dev/null; then
  deploying=1
fi
docker_steps() { (( ! deploying )); }
# what --apply frees (dry run) or freed (--apply), per kind, in bytes; images and the build cache are Docker's estimates
declare -A freed=([releases]=0 [images]=0 [build_cache]=0 [backups]=0 [journal]=0 [other]=0)

mode=$([[ $APPLY == 1 ]] && echo "APPLY" || echo "DRY RUN")
echo "maintenance ($mode) $(date -u +%Y-%m-%dT%H:%M:%SZ); disk: $(df -h "$ROOT" | awk 'NR==2 {print $3 " used of " $2 " (" $5 "), " $4 " free"}')"
(( deploying )) && echo "a deploy is running (deploy lock held): releases, images and the build cache are skipped this time"
remove() {   # remove <label> <command...>: only with --apply
  local label=$1; shift
  if [[ $APPLY == 1 ]]; then "$@" && echo "  removed  $label" || echo "  FAILED   $label" >&2
  else echo "  would remove  $label"; fi
}

# ---------------------------------------------------------------- releases: live + the previous KEEP_PREVIOUS_RELEASES
current=$(basename "$(readlink -f "$ROOT/current")")
[[ -n "$current" && -d "$ROOT/releases/$current" ]] || { echo "maintenance: cannot resolve the current release; stopping" >&2; exit 1; }
declare -A running=()      # release tags of oddstudio images that a container uses (running or stopped)
while read -r tag; do [[ -n "$tag" ]] && running[$tag]=1; done < <(
  docker ps -a --format '{{.Image}}' | sed -n 's/^oddstudio-\(api\|web\):\(.*\)$/\2/p' | sort -u)
# the deploy order, most recent first: the release log, then the order the images were built (docker lists the newest
# first), then the folders' age; the live release and folders that no longer exist are left out
declare -A seen=()
order=()
consider() {
  local r=$1
  [[ -z "$r" || "$r" == "$current" || -n "${seen[$r]:-}" || ! -d "$ROOT/releases/$r" ]] && return 0
  seen[$r]=1; order+=("$r")
}
if [[ -f "$ROOT/releases.log" ]]; then
  while read -r _ r _; do consider "$r"; done < <(tac "$ROOT/releases.log")
fi
while read -r t; do consider "$t"; done < <(docker images oddstudio-api --format '{{.Tag}}' 2>/dev/null)
built=${#order[@]}                       # releases that were built (have a log line or images), most recent first
declare -A was_built=()
for r in "${order[@]}"; do was_built[$r]=1; done
while read -r r; do consider "$r"; done < <(ls -1t "$ROOT/releases")
previous=()
for r in "${order[@]:0:$built}"; do (( ${#previous[@]} < KEEP_PREVIOUS_RELEASES )) && previous+=("$r"); done
rollback=${previous[0]:-}
declare -A keep=(["$current"]=1)
for r in "${previous[@]}"; do keep[$r]=1; done
for r in "${!running[@]}"; do keep[$r]=1; done
echo "releases: keeping the live release $current, the previous ${#previous[@]} (${previous[*]:-none}; rollback: ${rollback:-none})$( (( ${#running[@]} )) && echo " and any a container uses")"
for rel in $(ls -1t "$ROOT/releases"); do
  [[ -n "${keep[$rel]:-}" ]] && continue
  docker_steps || { echo "  skipped  release $rel (deploy running)"; continue; }
  size=$(dub "$ROOT/releases/$rel")
  freed[releases]=$(( freed[releases] + size ))
  remove "release $rel ($(numfmt --to=iec "$size"))$([[ -n "${was_built[$rel]:-}" ]] || echo ", never built")" rm -rf -- "$ROOT/releases/$rel"
done

# ---------------------------------------------------------------- images
echo "images: keeping those a container uses, the live and rollback release's oddstudio images${KEEP_IMAGES:+, and $KEEP_IMAGES}"
sysdf=$(docker system df --format '{{.Type}}|{{.Size}}|{{.Reclaimable}}' 2>/dev/null || true)
declare -A used=()            # repo:tag a container uses (running or stopped: a stopped one blocks `docker image rm`)
while read -r i; do [[ -n "$i" ]] && used[$i]=1; done < <(docker ps -a --format '{{.Image}}')
declare -A tool=()
for i in $KEEP_IMAGES; do tool[$i]=1; done
if docker_steps; then
  for repo in oddstudio-api oddstudio-web; do
    while IFS='|' read -r tag size; do
      [[ -z "$tag" || "$tag" == "$current" || "$tag" == "$rollback" || -n "${running[$tag]:-}" || -n "${used[$repo:$tag]:-}" ]] && continue
      remove "image $repo:$tag${size:+ ($size, shared layers counted once below)}" docker image rm "$repo:$tag"
    done < <(docker images "$repo" --format '{{.Tag}}|{{.Size}}')
  done
  while IFS='|' read -r ref size; do
    [[ -z "$ref" || "$ref" == oddstudio-api:* || "$ref" == oddstudio-web:* || "$ref" == *"<none>"* ]] && continue
    [[ -n "${used[$ref]:-}" || -n "${tool[$ref]:-}" ]] && continue
    remove "unused image $ref${size:+ ($size)}" docker image rm "$ref"
  done < <(docker image ls --format '{{.Repository}}:{{.Tag}}|{{.Size}}')
  # images no container uses: Docker's own estimate, shared layers counted once (it also counts the kept rollback and
  # tool images, which are small next to the rest)
  freed[images]=$(to_bytes "$(sed -n 's/^Images|[^|]*|//p' <<< "$sysdf")")
  if [[ $APPLY == 1 ]]; then docker image prune -f >/dev/null && echo "  pruned dangling images"; else echo "  would prune dangling images"; fi
else
  echo "  skipped (deploy running)"
fi

# ---------------------------------------------------------------- build cache
cache=$(to_bytes "$(sed -n 's/^Build Cache|\([^|]*\)|.*/\1/p' <<< "$sysdf")")
old=$(to_bytes "$(docker builder du --filter "until=${BUILD_CACHE_HOURS}h" 2>/dev/null | sed -n 's/^Total:[[:space:]]*//p' | tail -n 1)")
(( old <= cache )) || old=$cache
over=$(( cache - old > cache_max ? cache - old - cache_max : 0 ))
echo "build cache: $(gb "$cache") now, kept at most $BUILD_CACHE_MAX$( (( over )) && echo "; would trim about $(gb "$over")")$( (( old )) && echo "; older than ${BUILD_CACHE_HOURS} h: $(gb "$old")")"
if docker_steps; then
  freed[build_cache]=$(( old + over ))
  if [[ $APPLY == 1 ]]; then
    docker builder prune -f --filter "until=${BUILD_CACHE_HOURS}h" >/dev/null
    docker builder prune -f --max-used-space "$BUILD_CACHE_MAX" >/dev/null
    echo "  pruned build cache older than ${BUILD_CACHE_HOURS} h, and the cache above $BUILD_CACHE_MAX"
  fi
else
  echo "  skipped (deploy running)"
fi

# ---------------------------------------------------------------- backups
echo "backups: keeping the newest $KEEP_DEPLOY deploy-time and $KEEP_NIGHTLY nightly (complete ones; unsuffixed folders count as deploy-time)"
newest=$(ls -1d "$ROOT"/backups/*/ 2>/dev/null | sort | tail -n 1)
prune_kind() {   # prune_kind <keep> <folders, oldest first>
  local keep=$1; shift
  local list=("$@")
  (( ${#list[@]} > keep )) || return 0
  for b in "${list[@]:0:${#list[@]}-keep}"; do
    [[ "$b" == "$newest" ]] && continue                                     # never the newest backup
    local size; size=$(dub "$b")
    freed[backups]=$(( freed[backups] + size ))
    remove "backup $(basename "$b") ($(numfmt --to=iec "$size"))" rm -rf -- "$b"
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
    freed[other]=$(( freed[other] + $(stat -c %s "$f") ))
    remove "dump $(basename "$f") ($(du -sh "$f" | cut -f1))" rm -f -- "$f" "$f.sha256"
  done < <(find "$dumps" -maxdepth 1 -type f -name '*.dump' -mmin +$(( DUMP_DAYS * 1440 )) | sort)
else
  echo "database dumps: none ($dumps was written by nightly backups)"
fi

# ---------------------------------------------------------------- upload leftovers (work/uploads in the media volume)
# Listed only, never removed (owner decision 2026-11-23: housekeeping never touches the media volume). The volume is
# mounted read-only to list them.
echo "uploads: leftovers older than $UPLOAD_HOURS h in work/uploads (listed only; never removed by this script)"
if docker volume inspect "$MEDIA_VOLUME" >/dev/null 2>&1; then
  while read -r f; do
    [[ -z "$f" ]] && continue
    echo "  leftover  $f"
  done < <(docker run --rm -v "$MEDIA_VOLUME:/data:ro" alpine:3.20 \
             find /data/work/uploads -mindepth 1 -maxdepth 1 -mmin +$(( UPLOAD_HOURS * 60 )) -exec basename {} \; 2>/dev/null | sort)
else
  echo "  media volume $MEDIA_VOLUME not found; skipped"
fi

# ---------------------------------------------------------------- the Bin (items deleted in the studio > BIN_DAYS ago)
# Listed only, never purged (owner decision 2026-11-23: housekeeping never touches the database or media). The list
# comes from the API container (it has the database) with --dry-run, in both modes; the Bin page removes items by hand.
echo "bin: items deleted in the studio more than $BIN_DAYS days ago (listed only; never purged by this script)"
api=$(docker ps --format '{{.Names}}' | grep -E '(^|[-_])api([-_][0-9]+)?$' | head -n 1 || true)
if [[ -n "$api" ]]; then
  docker exec "$api" python -m oddstudio.bin purge --days "$BIN_DAYS" --dry-run | sed 's/^/  /' || true
else
  echo "  the API container is not running; skipped"
fi

# ---------------------------------------------------------------- logs and the journal
journal=$(iec_bytes "$(journalctl --disk-usage 2>/dev/null | grep -oE '[0-9.]+[KMGT]' | head -n 1)")
freed[journal]=$(( journal > journal_max ? journal - journal_max : 0 ))
echo "logs: deploy logs older than $LOG_DAYS days; the journal capped at $JOURNAL_MAX (now $( (( journal )) && numfmt --to=iec "$journal" || echo unknown)$( (( freed[journal] )) && echo "; would free about $(numfmt --to=iec "${freed[journal]}")"))"
while read -r f; do
  freed[other]=$(( freed[other] + $(stat -c %s "$f") ))
  remove "log $(basename "$f")" rm -f -- "$f"
done < <(find "$ROOT" -maxdepth 1 -type f \( -name 'deploy-*.log' -o -name 'ci-deploy-*.log' \) -mtime +"$LOG_DAYS")
if [[ $APPLY == 1 ]]; then journalctl --vacuum-size="$JOURNAL_MAX" >/dev/null 2>&1 || true; fi

total_freed=0
for k in "${!freed[@]}"; do total_freed=$(( total_freed + freed[$k] )); done
if [[ $APPLY == 0 ]]; then
  free_now=$(( $(df -B1 --output=avail "$ROOT" | tail -n 1) ))
  echo "projected free after --apply: about $(gib $(( free_now + total_freed ))) (now $(gib "$free_now"), as df -h counts; releases $(numfmt --to=iec "${freed[releases]}"), images about $(gb "${freed[images]}"), build cache about $(gb "${freed[build_cache]}"), backups $(numfmt --to=iec "${freed[backups]}"), journal $(numfmt --to=iec "${freed[journal]}"))"
fi

# ---------------------------------------------------------------- the disk report (read by the Overview page)
# Sizes on disk now. The volumes are measured where Docker keeps them (read only: du); the logs include the journal.
vol_bytes() { local m; m=$(docker volume inspect -f '{{.Mountpoint}}' "$1" 2>/dev/null | head -n 1 || true); if [[ -n "$m" && -d "$m" ]]; then dub "$m"; else echo 0; fi; }
read -r d_size d_used d_avail < <(df -B1 --output=size,used,avail "$ROOT" | tail -n 1)
d_pct=$(( d_used + d_avail > 0 ? (d_used * 100 + d_used + d_avail - 1) / (d_used + d_avail) : 0 ))   # as df rounds
consumers=(
  "backups|Backups|$(dub "$ROOT/backups")"
  "releases|Release folders|$(dub "$ROOT/releases")"
  "images|Docker images|$(to_bytes "$(sed -n 's/^Images|\([^|]*\)|.*/\1/p' <<< "$sysdf")")"
  "build_cache|Docker build cache|$cache"
  "media|Media (videos, stills, voice)|$(vol_bytes "$MEDIA_VOLUME")"
  "database|Database|$(vol_bytes "$DB_VOLUME")"
  "logs|Logs and journal|$(dub "$LOG_DIR")"
)
write_report() {
  mkdir -p "$REPORT_DIR" && chmod 755 "$REPORT_DIR"
  local tmp sep="" c k label bytes
  tmp=$(mktemp "$REPORT_DIR/.disk-report.XXXXXX")
  {
    printf '{\n  "version": 1,\n  "generated_at": "%s",\n  "mode": "%s",\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$([[ $APPLY == 1 ]] && echo apply || echo dry-run)"
    printf '  "disk": {"size": %s, "used": %s, "free": %s, "percent": %s},\n' "$d_size" "$d_used" "$d_avail" "$d_pct"
    printf '  "consumers": ['
    for c in "${consumers[@]}"; do
      IFS='|' read -r k label bytes <<< "$c"
      printf '%s\n    {"key": "%s", "label": "%s", "bytes": %s}' "$sep" "$k" "$label" "${bytes:-0}"; sep=","
    done
    printf '\n  ],\n  "%s": {"releases": %s, "images": %s, "build_cache": %s, "backups": %s, "journal": %s, "other": %s, "total": %s},\n' \
      "$([[ $APPLY == 1 ]] && echo freed || echo would_free)" "${freed[releases]}" "${freed[images]}" "${freed[build_cache]}" \
      "${freed[backups]}" "${freed[journal]}" "${freed[other]}" "$total_freed"
    printf '  "keep": {"live": "%s", "previous": [%s], "rollback": "%s", "deploy_backups": %s}\n}\n' "$current" \
      "$(for r in "${previous[@]}"; do printf '"%s",' "$r"; done | sed 's/,$//')" "$rollback" "$KEEP_DEPLOY"
  } > "$tmp"
  chmod 644 "$tmp"
  mv -f "$tmp" "$REPORT_DIR/disk-report.json"
  printf '%s %s used %s%% free %s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$mode" "$d_pct" "$(numfmt --to=iec "$d_avail")" \
    "$([[ $APPLY == 1 ]] && echo freed || echo would_free)" "$(numfmt --to=iec "$total_freed")" >> "$REPORT_DIR/disk-history.log"
  chmod 644 "$REPORT_DIR/disk-history.log"
}
if write_report; then echo "report: $REPORT_DIR/disk-report.json (the Overview page shows it)"
else echo "report: could not write $REPORT_DIR/disk-report.json" >&2; fi
echo "done ($mode); disk: $(df -h "$ROOT" | awk 'NR==2 {print $3 " used of " $2 " (" $5 "), " $4 " free"}')"
