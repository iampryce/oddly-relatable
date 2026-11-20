#!/usr/bin/env bash
# Simulation of deploy.sh with public HTTPS against a fake /srv/stickman and stub docker / curl / sleep: no Docker, no
# network. Checks that a bad Caddyfile stops the deploy before anything changes, that a proxy which does not route the
# media upload to the API is rolled back, and that a good deploy passes. Run on Linux with bash (CI: ubuntu):
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
  printf '#!/usr/bin/env bash\nexit 0\n' > "$R/releases/$rel/studio-app/deploy/backup.sh"   # simulated separately
done
ln -s releases/old "$R/current"

# stubs: CADDY_VALID (0/1), UPLOAD_CODE (what the proxy answers for the unauthenticated upload)
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
if [[ "$args" == *"-X PUT"* ]]; then printf '%s' "${UPLOAD_CODE:-401}"; exit 0; fi
exit 0
EOF
printf '#!/usr/bin/env bash\nexit 0\n' > "$SIM/bin/sleep"
chmod +x "$SIM/bin/"*
export PATH="$SIM/bin:$PATH"

fails=0
check() { if eval "$1"; then echo "  ok    $2"; else echo "  FAIL  $2"; fails=$((fails + 1)); fi; }
run() { env "$@" bash "$R/releases/new/studio-app/deploy/deploy.sh" new > "$SIM/out" 2>&1; echo $?; }

echo "1. an invalid Caddyfile stops the deploy before anything changes"
rc=$(run CADDY_VALID=0)
check '[[ $rc == 1 ]]' "deploy fails"
check '[[ "$(readlink "$R/current")" == releases/old ]]' "current still points to the old release"
check '! grep -q " up -d" "$SIM/docker.log"' "no container was started or recreated"
check 'grep -q "Caddyfile is not valid" "$SIM/out"' "the reason is printed"

echo "2. a proxy that does not route the upload to the API is rolled back"
: > "$SIM/docker.log"
rc=$(run UPLOAD_CODE=502)
check '[[ $rc == 1 ]]' "deploy fails"
check '[[ "$(readlink "$R/current")" == releases/old ]]' "current points back to the old release"
check 'grep -q "rolling back to old" "$SIM/out"' "the rollback ran"

echo "3. a good deploy passes through the proxy"
rc=$(run UPLOAD_CODE=401)
check '[[ $rc == 0 ]]' "deploy succeeds"
check '[[ "$(readlink "$R/current")" == releases/new ]]' "current points to the new release"
check 'grep -q "also through the HTTPS proxy" "$SIM/out"' "the proxy checks ran"

echo
if (( fails )); then echo "simulate-deploy: $fails check(s) FAILED"; exit 1; fi
echo "simulate-deploy: all checks passed"
