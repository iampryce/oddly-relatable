#!/usr/bin/env bash
# Deploy one release of Oddly Relatable Studio on the server (run on the server as the deploy user).
#   deploy.sh <release folder under /srv/stickman/releases>
# Layout (isolated from every other project on the host):
#   /srv/stickman/releases/<git sha>/   unpacked `git archive` of that commit (read-only after unpacking)
#   /srv/stickman/current -> releases/<git sha>
#   /srv/stickman/shared/.env           secrets (mode 600, never in git)
#   /srv/stickman/backups/<stamp>-<kind>/  backup.sh output (kind: nightly | deploy)
# Steps: backup (if a release is running) -> build images tagged with the release -> switch `current` ->
# start (the API applies database migrations on start) -> health check. On a failed health check it rolls back to
# the previous release's images automatically (see rollback.sh).
set -euo pipefail
ROOT=${STICKMAN_ROOT:-/srv/stickman}
rel=$(basename "${1:?usage: deploy.sh <release sha>}")
dir="$ROOT/releases/$rel"
test -f "$dir/studio-app/deploy/docker-compose.yml" || { echo "deploy: $dir is not a release" >&2; exit 1; }
test -f "$ROOT/shared/.env" || { echo "deploy: $ROOT/shared/.env is missing" >&2; exit 1; }
prev=$(readlink "$ROOT/current" 2>/dev/null | xargs -r basename || true)

if [[ -n "$prev" ]]; then "$dir/studio-app/deploy/backup.sh"; fi

# Public HTTPS (Caddy on PUBLIC_PORT) is added when shared/.env sets PUBLIC_HOST; see docker-compose.public.yml.
compose() {
  local f=(-f "$ROOT/releases/$1/studio-app/deploy/docker-compose.yml")
  if grep -q "^PUBLIC_HOST=." "$ROOT/shared/.env"; then f+=(-f "$ROOT/releases/$1/studio-app/deploy/docker-compose.public.yml"); fi
  RELEASE="$1" docker compose -p oddstudio --env-file "$ROOT/shared/.env" "${f[@]}" "${@:2}"
}
compose "$rel" build
ln -sfn "releases/$rel" "$ROOT/current"
compose "$rel" up -d --remove-orphans

for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:3000/api/health >/dev/null 2>&1; then echo "deploy: $rel is healthy"; exit 0; fi
  sleep 5
done
echo "deploy: $rel did not become healthy" >&2
if [[ -n "$prev" ]]; then
  echo "deploy: rolling back to $prev" >&2
  ln -sfn "releases/$prev" "$ROOT/current"
  compose "$prev" up -d --remove-orphans
fi
exit 1
