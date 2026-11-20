#!/usr/bin/env bash
# Restore Oddly Relatable Studio from a backup made by backup.sh.
#   restore.sh /srv/stickman/backups/<stamp>[-nightly|-deploy] [--media]   a backup folder (any of the three name forms)
#   restore.sh /srv/stickman/db-dumps/<stamp>-nightly.dump                  a dump from the 30-day folder (database only)
# Restores the database (always) and the media volume (with --media, folders only). Stops api/worker/web during the
# restore and starts them again afterwards. Verifies checksums first. Destructive for the current data: backup.sh runs
# first, so the state being replaced is kept as its own backup; the source backup is protected from that run's pruning.
set -euo pipefail
ROOT=${STICKMAN_ROOT:-/srv/stickman}
arg=${1:?usage: restore.sh <backup folder | .dump file> [--media]}
media=${2:-}
[[ -e "$arg" ]] || { echo "restore: $arg does not exist" >&2; exit 1; }
if [[ -f "$arg" && "$arg" == *.dump ]]; then
  # a dump from the 30-day folder: database only, verified against its .sha256 file
  [[ -z "$media" ]] || { echo "restore: --media needs a backup folder (a .dump file holds the database only)" >&2; exit 2; }
  dir=$(cd "$(dirname "$arg")" && pwd -P); name=$(basename "$arg")
  [[ -f "$dir/$name.sha256" ]] || { echo "restore: $name.sha256 is missing next to the dump" >&2; exit 1; }
  ( cd "$dir" && sha256sum -c "$name.sha256" )
  dump="$dir/$name"; src="$dir/$name"; protect=""
else
  src=$(cd "$arg" && pwd -P)    # absolute: docker -v needs a path (a relative one would be taken as a volume name)
  for f in SHA256SUMS db.dump; do [[ -f "$src/$f" ]] || { echo "restore: $src has no $f" >&2; exit 1; }; done
  [[ "$media" != "--media" || -f "$src/media.tar.gz" ]] || { echo "restore: $src has no media.tar.gz" >&2; exit 1; }
  ( cd "$src" && sha256sum -c SHA256SUMS )
  dump="$src/db.dump"; protect="$src"
fi
COMPOSE=(docker compose -p oddstudio --env-file "$ROOT/shared/.env" -f "$ROOT/current/studio-app/deploy/docker-compose.yml")
if grep -q "^PUBLIC_HOST=." "$ROOT/shared/.env"; then COMPOSE+=(-f "$ROOT/current/studio-app/deploy/docker-compose.public.yml"); fi

BACKUP_PROTECT="$protect" "$(dirname "$0")/backup.sh"     # keep what is about to be replaced (never pruning the source)

"${COMPOSE[@]}" stop web worker api
"${COMPOSE[@]}" exec -T postgres pg_restore -U oddstudio -d oddstudio --clean --if-exists --no-owner < "$dump"
if [[ "$media" == "--media" ]]; then
  docker run --rm -v oddstudio_work_data:/data -v "$src":/backup:ro alpine:3.20 \
    sh -c 'find /data -mindepth 1 -delete && tar -xzf /backup/media.tar.gz -C /data'
fi
"${COMPOSE[@]}" start api worker web
echo "restore: done from $src (media: ${media:-not restored})"
