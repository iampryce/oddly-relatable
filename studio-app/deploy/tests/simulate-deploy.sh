#!/usr/bin/env bash
# Simulation of deploy.sh with public HTTPS against a fake /srv/stickman and stub docker / curl / sleep: no Docker, no
# network. Checks that a bad Caddyfile stops the deploy before anything changes, that a proxy which does not route the
# media upload to the API is rolled back, and that a good deploy passes; a backup that cannot be made (not enough free
# space) stops the deploy before anything is built or changed, and the deploy asks for the newest 3 deploy-time backups
# and room for its image build. Run on Linux with bash (CI: ubuntu):
#   bash studio-app/deploy/tests/simulate-deploy.sh
set -uo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd -P)
SIM=$(mktemp -d)
trap 'rm -rf "$SIM"' EXIT
export STICKMAN_ROOT="$SIM/root"
R="$STICKMAN_ROOT"
mkdir -p "$R"/{backups,shared,releases} "$SIM/bin"
printf 'PUBLIC_HOST=studio.example.test\nPUBLIC_PORT=8443\nPOSTGRES_PASSWORD=x\n' > "$R/shared/.env"
for rel in old new; do
  mkdir -p "$R/releases/$rel/studio-app/deploy"
  cp "$HERE"/*.sh "$HERE"/*.yml "$HERE/Caddyfile" "$R/releases/$rel/studio-app/deploy/"
  # backup.sh is simulated separately (simulate-backups.sh): here it records what deploy.sh asked of it
  printf '#!/usr/bin/env bash\necho "KEEP_DEPLOY=$KEEP_DEPLOY KEEP=$KEEP BACKUP_KIND=$BACKUP_KIND BACKUP_EXTRA_FREE=$BACKUP_EXTRA_FREE" > "%s/backup.env"\nexit ${BACKUP_RC:-0}\n' "$SIM" > "$R/releases/$rel/studio-app/deploy/backup.sh"
done
ln -s releases/old "$R/current"

# stubs: CADDY_VALID (0/1), UPLOAD_CODE and UPLOAD_BODY (the proxy's answer to the upload without credentials)
cat > "$SIM/bin/docker" <<EOF
#!/usr/bin/env bash
echo "docker \$*" >> "$SIM/docker.log"
[[ "\$*" == *"caddy validate"* ]] && exit \$(( 1 - \${CADDY_VALID:-1} ))
[[ "\$*" == *pg_dump* ]] && echo dump
exit 0
EOF
cat > "$SIM/bin/curl" <<'EOF'
#!/usr/bin/env bash
args="$*"
if [[ "$args" == *"-X PUT"* ]]; then printf '%s\n%s' "${UPLOAD_BODY-{\"detail\":\"Sign in required\"}}" "${UPLOAD_CODE:-401}"; exit 0; fi
exit 0
EOF
printf '#!/usr/bin/env bash\nexit 0\n' > "$SIM/bin/sleep"
chmod +x "$SIM/bin/"*
export PATH="$SIM/bin:$PATH"

fails=0
check() { if eval "$1"; then echo "  ok    $2"; else echo "  FAIL  $2"; fails=$((fails + 1)); fi; }
run() { env "$@" bash "$R/releases/new/studio-app/deploy/deploy.sh" new > "$SIM/out" 2>&1; echo $?; }

echo "0. a backup that cannot be made stops the deploy before anything changes"
rc=$(run BACKUP_RC=3 KEEP_DEPLOY=5)
check '[[ $rc == 1 ]]' "deploy fails"
check 'grep -q "stopped before building: the backup could not be made" "$SIM/out" && grep -q "still on old" "$SIM/out"' "the reason is printed"
check '[[ "$(readlink "$R/current")" == releases/old && ! -s "$SIM/docker.log" ]]' "nothing was built, started or switched"
check 'grep -q "KEEP_DEPLOY=3 KEEP= BACKUP_KIND=deploy BACKUP_EXTRA_FREE=5G" "$SIM/backup.env"' "deploy asks for the newest 3 deploy-time backups and 5G of build room (an older wrapper's KEEP_DEPLOY=5 is not used)"
rc=$(run BACKUP_RC=3 DEPLOY_KEEP_BACKUPS=4 DEPLOY_BUILD_FREE=8G)
check 'grep -q "KEEP_DEPLOY=4 KEEP= BACKUP_KIND=deploy BACKUP_EXTRA_FREE=8G" "$SIM/backup.env"' "DEPLOY_KEEP_BACKUPS and DEPLOY_BUILD_FREE set them"

echo "1. an invalid Caddyfile stops the deploy before anything changes"
rc=$(run CADDY_VALID=0)
check '[[ $rc == 1 ]]' "deploy fails"
check '[[ "$(readlink "$R/current")" == releases/old ]]' "current still points to the old release"
check '! grep -q " up -d" "$SIM/docker.log"' "no container was started or recreated"
check 'grep -q "Caddyfile is not valid" "$SIM/out"' "the reason is printed"

echo "2. a proxy that does not route the upload to the API is rolled back"
: > "$SIM/docker.log"
rc=$(run UPLOAD_CODE=502 UPLOAD_BODY="bad gateway")
check '[[ $rc == 1 ]]' "deploy fails"
check '[[ "$(readlink "$R/current")" == releases/old ]]' "current points back to the old release"
check 'grep -q "rolling back to old" "$SIM/out"' "the rollback ran"
check '[[ "$(tail -n 1 "$R/releases.log" | cut -d" " -f2)" == old ]]' "releases.log records the release that is live again"

echo "3. a page from the dashboard instead of the API is not good enough"
rc=$(run UPLOAD_CODE=404 UPLOAD_BODY="<html>not found</html>")
check '[[ $rc == 1 && "$(readlink "$R/current")" == releases/old ]]' "an HTML 404 (not the API) is rolled back"

echo "4. sign-in turned off (AUTH_DISABLED=true): the API answers 404 for episode 0"
rc=$(run UPLOAD_CODE=404 UPLOAD_BODY='{"detail":"episode not found"}')
check '[[ $rc == 0 && "$(readlink "$R/current")" == releases/new ]]' "deploy succeeds"
ln -sfn releases/old "$R/current"

echo "5. a good deploy passes through the proxy"
rc=$(run UPLOAD_CODE=401)
check '[[ $rc == 0 ]]' "deploy succeeds"
check '[[ "$(readlink "$R/current")" == releases/new ]]' "current points to the new release"
check 'grep -q "also through the HTTPS proxy" "$SIM/out"' "the proxy checks ran"
check '[[ "$(tail -n 1 "$R/releases.log")" =~ ^[0-9-]+T[0-9:]+Z\ new$ ]]' "releases.log records the release that went live (the deploy order maintenance.sh keeps by)"

echo
if (( fails )); then echo "simulate-deploy: $fails check(s) FAILED"; exit 1; fi
echo "simulate-deploy: all checks passed"
