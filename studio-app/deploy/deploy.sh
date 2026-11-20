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
# the previous release's images automatically (see rollback.sh). With public HTTPS (PUBLIC_HOST), the new Caddyfile is
# validated before anything changes, and the health check also goes THROUGH Caddy: the dashboard's /api/health and the
# direct media-upload route (an unauthenticated upload must reach the API and get 401). A proxy that does not serve
# both counts as unhealthy, so a bad proxy config is rolled back like any other failed deploy.
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
public=0
if grep -q "^PUBLIC_HOST=." "$ROOT/shared/.env"; then
  public=1
  env_value() { sed -n "s/^$1=//p" "$ROOT/shared/.env" | tail -n 1 | tr -d "\"'"; }
  host=$(env_value PUBLIC_HOST); port=$(env_value PUBLIC_PORT); port=${port:-8443}
fi
compose "$rel" build
if (( public )); then
  compose "$rel" run --rm --no-deps -T proxy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1 \
    || { echo "deploy: the new Caddyfile is not valid; nothing was changed" >&2; exit 1; }
fi
ln -sfn "releases/$rel" "$ROOT/current"
compose "$rel" up -d --remove-orphans

healthy() {
  curl -fsS http://127.0.0.1:3000/api/health >/dev/null 2>&1 || return 1
  (( public )) || return 0
  local via=(-k -s --max-time 10 --resolve "$host:$port:127.0.0.1")
  curl -f "${via[@]}" -o /dev/null "https://$host:$port/api/health" || return 1
  [[ "$(curl "${via[@]}" -o /dev/null -w '%{http_code}' -X PUT "https://$host:$port/api/episodes/0/audio")" == 401 ]]
}
for i in $(seq 1 30); do
  if healthy; then echo "deploy: $rel is healthy"$( (( public )) && echo " (also through the HTTPS proxy)"); exit 0; fi
  sleep 5
done
echo "deploy: $rel did not become healthy" >&2
if [[ -n "$prev" ]]; then
  echo "deploy: rolling back to $prev" >&2
  ln -sfn "releases/$prev" "$ROOT/current"
  compose "$prev" up -d --remove-orphans
fi
exit 1
