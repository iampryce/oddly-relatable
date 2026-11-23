#!/usr/bin/env bash
# Forced command for the GitHub Actions deploy key. Install it OUTSIDE the repo checkout at
# /srv/stickman/ci-deploy.sh (root-owned, mode 755) and tie the key to it in /root/.ssh/authorized_keys:
#   command="/srv/stickman/ci-deploy.sh",no-pty,no-port-forwarding,no-X11-forwarding,no-agent-forwarding ssh-ed25519 AAAA...
# The key can then do exactly one thing: deploy a commit that is already on origin/main.
#   ssh <host> <40-hex commit sha>
set -euo pipefail
ROOT=${STICKMAN_ROOT:-/srv/stickman}
REPO="$ROOT/repo"
sha="${SSH_ORIGINAL_COMMAND:-}"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "ci-deploy: expected a 40-character commit sha" >&2; exit 2; }

exec 9>"$ROOT/.ci-deploy.lock"
flock -n 9 || { echo "ci-deploy: another deploy is running" >&2; exit 3; }

log="$ROOT/ci-deploy-${sha:0:12}-$(date -u +%Y%m%dT%H%M%SZ).log"
exec > >(tee -a "$log") 2>&1
echo "ci-deploy: $sha"

git -C "$REPO" fetch -q origin main
git -C "$REPO" cat-file -e "$sha^{commit}" || { echo "ci-deploy: unknown commit" >&2; exit 4; }
git -C "$REPO" merge-base --is-ancestor "$sha" origin/main || { echo "ci-deploy: $sha is not on origin/main" >&2; exit 5; }
git -C "$REPO" checkout -q --detach "$sha"
[[ -z "$(git -C "$REPO" status --porcelain)" ]] || { echo "ci-deploy: checkout is not clean" >&2; exit 6; }

tree=$(git -C "$REPO" rev-parse "$sha^{tree}")
current=$(readlink "$ROOT/current" 2>/dev/null | xargs -r basename || true)
if [[ "$current" == "$tree" ]]; then echo "ci-deploy: $tree is already deployed"; exit 0; fi

dir="$ROOT/releases/$tree"
if [[ ! -d "$dir" ]]; then
  mkdir "$dir"
  git -C "$REPO" archive "$sha" | tar -x -C "$dir"
  chmod -R a-w "$dir"
fi
# deploy.sh sets the deploy-time backup retention itself (DEPLOY_KEEP_BACKUPS, default 3) and checks free space first.
"$dir/studio-app/deploy/deploy.sh" "$tree"
echo "ci-deploy: done $tree"
