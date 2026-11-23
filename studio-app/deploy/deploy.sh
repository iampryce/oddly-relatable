#!/usr/bin/env bash
# Deploy one release of Oddly Relatable Studio on the server (run on the server as the deploy user).
#   deploy.sh <release folder under /srv/stickman/releases>
# Layout (isolated from every other project on the host):
#   /srv/stickman/releases/<git sha>/   unpacked `git archive` of that commit (read-only after unpacking)
#   /srv/stickman/current -> releases/<git sha>
#   /srv/stickman/shared/.env           secrets (mode 600, never in git)
#   /srv/stickman/backups/<stamp>-<kind>/  backup.sh output (kind: nightly | deploy)
# Steps: backup (if a release is running; it first checks the free disk space, including $DEPLOY_BUILD_FREE for the
# image build, default 5G, and stops the deploy before anything changes if there is not enough; it keeps the newest
# $DEPLOY_KEEP_BACKUPS deploy-time backups, default 3) -> build images tagged with the release -> switch `current` ->
# start (the API applies database migrations on start) -> health check. On a failed health check it rolls back to
# the previous release's images automatically (see rollback.sh). With public HTTPS (PUBLIC_HOST), the new Caddyfile is
# validated before anything changes, and the health check also goes THROUGH Caddy: the dashboard's /api/health and the
# direct media-upload route (an upload to episode 0 without credentials must be answered BY THE API: its JSON error,
# 401 with sign-in on, 404 with AUTH_DISABLED=true; a proxy error such as 502 is not). A proxy that does not serve
# both counts as unhealthy, so a bad proxy config is rolled back like any other failed deploy.
set -euo pipefail
ROOT=${STICKMAN_ROOT:-/srv/stickman}
rel=$(basename "${1:?usage: deploy.sh <release sha>}")
dir="$ROOT/releases/$rel"
test -f "$dir/studio-app/deploy/docker-compose.yml" || { echo "deploy: $dir is not a release" >&2; exit 1; }
test -f "$ROOT/shared/.env" || { echo "deploy: $ROOT/shared/.env is missing" >&2; exit 1; }
prev=$(readlink "$ROOT/current" 2>/dev/null | xargs -r basename || true)

# The deploy-time retention is set here (DEPLOY_KEEP_BACKUPS): a KEEP_DEPLOY passed in by an older installed
# ci-deploy.sh is not used. Never a Docker volume: this script only builds, starts and health-checks containers.
if [[ -n "$prev" ]]; then
  KEEP_DEPLOY=${DEPLOY_KEEP_BACKUPS:-3} KEEP= BACKUP_KIND=deploy BACKUP_EXTRA_FREE=${DEPLOY_BUILD_FREE:-5G} \
    "$dir/studio-app/deploy/backup.sh" \
    || { echo "deploy: stopped before building: the backup could not be made (see above). Nothing was changed; still on $prev." >&2; exit 1; }
fi

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
  local out code
  out=$(curl "${via[@]}" -w '\n%{http_code}' -X PUT "https://$host:$port/api/episodes/0/audio") || return 1
  code=${out##*$'\n'}
  [[ "$code" == 401 || "$code" == 404 ]] && [[ "${out%$'\n'*}" == *'"detail"'* ]]
}
# releases.log: one line per release that went live (UTC time, release), the deploy order maintenance.sh keeps by
went_live() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $1" >> "$ROOT/releases.log" || true; }
for i in $(seq 1 30); do
  if healthy; then went_live "$rel"; echo "deploy: $rel is healthy"$( (( public )) && echo " (also through the HTTPS proxy)"); exit 0; fi
  sleep 5
done
echo "deploy: $rel did not become healthy" >&2
if [[ -n "$prev" ]]; then
  echo "deploy: rolling back to $prev" >&2
  ln -sfn "releases/$prev" "$ROOT/current"
  compose "$prev" up -d --remove-orphans
  went_live "$prev"
fi
exit 1
