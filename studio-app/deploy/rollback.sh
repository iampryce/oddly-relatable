#!/usr/bin/env bash
# Roll back to an earlier release (its images are still on the host, tagged with its git sha).
#   rollback.sh <release sha> [<backup folder to restore>]
# Code rollback only, unless a backup folder is given: then the database is restored to that backup too (needed only
# when the newer release ran a migration the older code cannot work with; see docs/DEPLOYMENT.md "Migrations").
set -euo pipefail
ROOT=${STICKMAN_ROOT:-/srv/stickman}
rel=$(basename "${1:?usage: rollback.sh <release sha> [<backup folder>]}")
test -d "$ROOT/releases/$rel" || { echo "rollback: no release $rel" >&2; exit 1; }
docker image inspect "oddstudio-api:$rel" >/dev/null || { echo "rollback: images for $rel are gone; run deploy.sh $rel" >&2; exit 1; }
ln -sfn "releases/$rel" "$ROOT/current"
f=(-f "$ROOT/releases/$rel/studio-app/deploy/docker-compose.yml")
if grep -q "^PUBLIC_HOST=." "$ROOT/shared/.env" && test -f "$ROOT/releases/$rel/studio-app/deploy/docker-compose.public.yml"; then
  f+=(-f "$ROOT/releases/$rel/studio-app/deploy/docker-compose.public.yml"); fi
RELEASE="$rel" docker compose -p oddstudio --env-file "$ROOT/shared/.env" "${f[@]}" up -d --remove-orphans
if [[ -n "${2:-}" ]]; then "$ROOT/releases/$rel/studio-app/deploy/restore.sh" "$2"; fi
echo "rollback: now running $rel"
