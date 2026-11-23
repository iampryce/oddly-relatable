#!/usr/bin/env bash
# Simulation of maintenance.sh's keep-limits and its disk report (2026-11-23) against a fake /srv/stickman with stub
# `docker` and `journalctl`: no Docker, nothing outside a temporary folder. Checks: the live release and the previous 2
# are kept (deploy order from releases.log, else the order the images were built; a folder that never ran is not a
# previous release); only images no container uses and not the live or rollback release's are removed, with
# `docker image rm` / `docker image prune`; build cache older than 7 days and above the cap; the journal capped at 200M;
# the newest 3 deploy-time backups are never removed; a dry run removes nothing; volumes and containers are never
# touched; the deploy lock; and the JSON report the Overview page reads. Run on Linux with bash 5, GNU coreutils and
# python3 (CI: ubuntu):
#   bash studio-app/deploy/tests/simulate-maintenance.sh
set -uo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd -P)
SIM=$(mktemp -d)
trap 'rm -rf "$SIM"' EXIT
export STICKMAN_ROOT="$SIM/root" LOG_DIR="$SIM/varlog"
R="$STICKMAN_ROOT"
L=1111111111111111111111111111111111111111; P1=2222222222222222222222222222222222222222
P2=3333333333333333333333333333333333333333; P3=4444444444444444444444444444444444444444
F=5555555555555555555555555555555555555555                                  # unpacked, but its deploy failed: never built
mkdir -p "$R"/{backups,shared,releases} "$SIM/bin" "$LOG_DIR" "$SIM/vol/oddstudio_work_data" "$SIM/vol/oddstudio_postgres_data"
head -c 300000 /dev/zero > "$SIM/vol/oddstudio_work_data/clip.mp4"
head -c 70000 /dev/zero > "$SIM/vol/oddstudio_postgres_data/base"
head -c 5000 /dev/zero > "$LOG_DIR/syslog"
age=10
for r in $P3 $P2 $P1 $L $F; do                                               # oldest first; F is the newest folder
  mkdir -p "$R/releases/$r"; head -c 20000 /dev/zero > "$R/releases/$r/files"; touch -d "$age hours ago" "$R/releases/$r"; age=$((age - 2))
done
ln -s "releases/$L" "$R/current"
for i in 1 2 3 4 5; do                                                       # five complete deploy-time backups
  b="$R/backups/2026112${i}T000000Z-deploy"; mkdir -p "$b"; head -c 40000 /dev/zero > "$b/media.tar.gz"; echo x > "$b/db.dump"
  ( cd "$b" && sha256sum db.dump media.tar.gz > SHA256SUMS )
done
mkdir -p "$R/backups/20261126T000000Z-deploy"; echo partial > "$R/backups/20261126T000000Z-deploy/media.tar.gz"   # incomplete

cat > "$SIM/bin/docker" <<EOF
#!/usr/bin/env bash
args="\$*"
echo "\$args" >> "$SIM/docker.calls"
case "\$args" in
  "ps -a --format {{.Image}}") printf 'oddstudio-api:$L\noddstudio-web:$L\noddstudio-api:$L\npostgres:16-alpine\n' ;;
  "ps --format {{.Names}}") echo oddstudio-api-1 ;;
  "images oddstudio-api --format {{.Tag}}") printf '$L\n$P1\n$P2\n$P3\n' ;;
  "images oddstudio-api --format {{.Tag}}|{{.Size}}"|"images oddstudio-web --format {{.Tag}}|{{.Size}}") printf '$L|4.21GB\n$P1|4.21GB\n$P2|4.21GB\n$P3|4.11GB\n' ;;
  "image ls --format {{.Repository}}:{{.Tag}}|{{.Size}}")
    printf 'oddstudio-api:$L|4.21GB\noddstudio-web:$L|424MB\npostgres:16-alpine|420MB\nalpine:3.20|12.2MB\nnginx:1.27-alpine|48MB\nhello-world:latest|10kB\n<none>:<none>|1GB\n' ;;
  "system df --format {{.Type}}|{{.Size}}|{{.Reclaimable}}") printf 'Images|38.45GB|11.06GB (28%%)\nContainers|856kB|0B (0%%)\nLocal Volumes|2.889GB|0B (0%%)\nBuild Cache|15.15GB|9.738GB\n' ;;
  "builder du --filter until=168h") printf 'ID  RECLAIMABLE  SIZE\nabc true 4GB\nTotal:\t4GB\n' ;;
  "volume inspect -f {{.Mountpoint}} "*) echo "$SIM/vol/\${@: -1}" ;;
  "volume inspect "*) exit 0 ;;
  "exec "*) echo "bin: 0 item(s) in the Bin" ;;
esac
exit 0
EOF
cat > "$SIM/bin/journalctl" <<EOF
#!/usr/bin/env bash
echo "\$*" >> "$SIM/journal.calls"
[[ "\$*" == --disk-usage ]] && echo "Archived and active journals take up 300.0M in the file system."
exit 0
EOF
chmod +x "$SIM/bin/"*
export PATH="$SIM/bin:$PATH"

fails=0
check() { if eval "$1"; then echo "  ok    $2"; else echo "  FAIL  $2"; fails=$((fails + 1)); fi; }
M="$HERE/maintenance.sh"; J="$R/reports/disk-report.json"
jq_() { python3 -c "import json,sys; d=json.load(open('$J')); print($1)"; }

echo "1. dry run: what would go, with sizes; nothing is removed"
out=$(bash "$M" 2>&1); rc=$?
check '[[ $rc == 0 ]]' "the dry run succeeds"
check 'grep -q "keeping the live release $L, the previous 2 ($P1 $P2; rollback: $P1)" <<< "$out"' "keeps the live release and the previous 2 (built order: the images)"
check 'grep -q "would remove  release $P3 (20K)" <<< "$out" && grep -q "would remove  release $F (20K), never built" <<< "$out"' "would remove the older release and the never-built folder, with sizes"
check '! grep -qE "would remove  release ($L|$P1|$P2)" <<< "$out"' "never the live or the previous 2"
check 'grep -q "would remove  image oddstudio-api:$P2 (4.21GB" <<< "$out" && grep -q "would remove  image oddstudio-web:$P3" <<< "$out"' "would remove the older releases' images, with sizes"
check '! grep -qE "would remove  image oddstudio-(api|web):($L|$P1)" <<< "$out"' "keeps the live and the rollback release's images"
check 'grep -q "would remove  unused image nginx:1.27-alpine (48MB)" <<< "$out" && grep -q "would remove  unused image hello-world:latest" <<< "$out"' "would remove other images no container uses"
check '! grep -qE "would remove  unused image (postgres|alpine)" <<< "$out" && ! grep -q "<none>" <<< "$out"' "keeps images a container uses and the tool image; dangling ones go by prune"
check 'grep -q "would prune dangling images" <<< "$out"' "would prune dangling images"
check 'grep -q "build cache: 15.2 GB now, kept at most 10GB; would trim about 1.1 GB; older than 168 h: 4.0 GB" <<< "$out"' "build cache older than 7 days, then the cap"
check 'grep -q "the journal capped at 200M (now 300M; would free about 100M)" <<< "$out"' "the journal is capped at 200M"
check 'grep -q "would remove  backup 20261121T000000Z-deploy" <<< "$out" && grep -q "would remove  backup 20261122T000000Z-deploy" <<< "$out"' "backups beyond the newest 3 deploy-time"
check '! grep -qE "would remove  backup 2026112[345]T" <<< "$out"' "never the newest 3 deploy-time backups"
check 'grep -q "incomplete 20261126T000000Z-deploy" <<< "$out" && ! grep -q "would remove  backup 20261126" <<< "$out"' "an incomplete backup is listed, not removed"
check '[[ -d "$R/releases/$P3" && -d "$R/releases/$F" && -d "$R/backups/20261121T000000Z-deploy" ]]' "the dry run removed nothing"
check '! grep -qE "image (rm|prune)|builder prune" "$SIM/docker.calls" && ! grep -q vacuum "$SIM/journal.calls"' "the dry run ran no removal command"

echo "2. the disk report the Overview page reads"
check '[[ -f "$J" ]] && python3 -c "import json; json.load(open(\"$J\"))"' "disk-report.json is valid JSON"
check '[[ "$(jq_ "d[\"mode\"]")" == dry-run && "$(jq_ "0 <= d[\"disk\"][\"percent\"] <= 100")" == True ]]' "mode and disk use"
check '[[ "$(jq_ "\" \".join(sorted(c[\"key\"] for c in d[\"consumers\"]))")" == "backups build_cache database images logs media releases" ]]' "consumers: backups, releases, images, build cache, media, database, logs"
check '[[ "$(jq_ "{c[\"key\"]: c[\"bytes\"] for c in d[\"consumers\"]}[\"images\"]")" == 38450000000 && "$(jq_ "{c[\"key\"]: c[\"bytes\"] for c in d[\"consumers\"]}[\"media\"]")" -ge 300000 ]]' "sizes: Docker's image total and the media volume measured"
check '[[ "$(jq_ "d[\"would_free\"][\"build_cache\"]")" == 5150000000 && "$(jq_ "d[\"would_free\"][\"journal\"]")" == 104857600 && "$(jq_ "d[\"would_free\"][\"total\"] > d[\"would_free\"][\"images\"]")" == True ]]' "what --apply would free, per kind and in total"
check '[[ "$(jq_ "\" \".join([d[\"keep\"][\"live\"]] + d[\"keep\"][\"previous\"] + [d[\"keep\"][\"rollback\"], str(d[\"keep\"][\"deploy_backups\"])])")" == "$L $P1 $P2 $P1 3" ]]' "what is kept"
check '[[ "$(stat -c %a "$J")" == 644 && "$(stat -c %a "$R/reports")" == 755 ]]' "readable by the studio's (non-root) API user"
check '[[ $(wc -l < "$R/reports/disk-history.log") == 1 ]] && grep -q "DRY RUN used" "$R/reports/disk-history.log"' "one line appended to disk-history.log"

echo "3. the release log decides the deploy order"
printf '2026-11-20T00:00:00Z %s\n2026-11-21T00:00:00Z %s\n2026-11-22T00:00:00Z %s\n' "$P2" "$P3" "$L" > "$R/releases.log"
out=$(bash "$M" 2>&1)
check 'grep -q "the previous 2 ($P3 $P2; rollback: $P3)" <<< "$out" && grep -q "would remove  release $P1" <<< "$out"' "previous = the releases that went live before the live one, newest first"
check 'grep -q "would remove  image oddstudio-api:$P1" <<< "$out" && ! grep -q "would remove  image oddstudio-api:$P3" <<< "$out"' "the rollback release's images follow the log too"
rm "$R/releases.log"

echo "4. limits that would break the rules are refused"
check '! KEEP_DEPLOY=2 bash "$M" >/dev/null 2>&1' "KEEP_DEPLOY below 3 is refused"
check '! KEEP_PREVIOUS_RELEASES=0 bash "$M" >/dev/null 2>&1' "no rollback release is refused"
check '! JOURNAL_MAX=lots bash "$M" >/dev/null 2>&1' "a journal cap that is not a size is refused"

echo "5. a deploy holds the lock: releases, images and the build cache wait"
: > "$SIM/docker.calls"
flock "$R/.ci-deploy.lock" sleep 3 & holder=$!
sleep 0.5
out=$(bash "$M" --apply 2>&1)
check 'grep -q "a deploy is running" <<< "$out" && [[ -d "$R/releases/$P3" ]] && ! grep -qE "image rm|builder prune" "$SIM/docker.calls"' "nothing Docker-related or release-related is removed"
check '[[ ! -d "$R/backups/20261121T000000Z-deploy" ]]' "the other steps still run (old backups)"
wait $holder

echo "6. --apply removes exactly what the dry run listed"
: > "$SIM/docker.calls"; : > "$SIM/journal.calls"
out=$(bash "$M" --apply 2>&1); rc=$?
check '[[ $rc == 0 && ! -d "$R/releases/$P3" && ! -d "$R/releases/$F" ]]' "the older release and the never-built folder are removed"
check '[[ -d "$R/releases/$L" && -d "$R/releases/$P1" && -d "$R/releases/$P2" ]]' "the live release and the previous 2 stay"
check '[[ "$(grep "^image rm" "$SIM/docker.calls" | sort | tr "\n" " ")" == "image rm hello-world:latest image rm nginx:1.27-alpine image rm oddstudio-api:$P2 image rm oddstudio-api:$P3 image rm oddstudio-web:$P2 image rm oddstudio-web:$P3 " ]]' "docker image rm: exactly the listed images"
check 'grep -qx "image prune -f" "$SIM/docker.calls"' "dangling images: docker image prune"
check 'grep -q "builder prune -f --filter until=168h" "$SIM/docker.calls" && grep -q "builder prune -f --max-used-space 10GB" "$SIM/docker.calls"' "build cache: older than 7 days, then the cap"
check 'grep -qx -- "--vacuum-size=200M" "$SIM/journal.calls"' "the journal is vacuumed to 200M"
check '[[ $(ls -1d "$R"/backups/*/ | wc -l) == 4 && -d "$R/backups/20261123T000000Z-deploy" && -d "$R/backups/20261126T000000Z-deploy" ]]' "the newest 3 deploy-time backups and the incomplete one stay"
check '! grep -qE "volume (rm|prune)|system prune|container (rm|prune)|^(rm|stop|kill|down) |compose .*down" "$SIM/docker.calls"' "no volume or container is ever removed or stopped"
check '[[ -s "$SIM/vol/oddstudio_work_data/clip.mp4" && -s "$SIM/vol/oddstudio_postgres_data/base" ]]' "media and database files untouched"
check '[[ "$(jq_ "d[\"mode\"]")" == apply && "$(jq_ "\"freed\" in d")" == True ]]' "the report says what was freed"
check '[[ $(wc -l < "$R/reports/disk-history.log") == 4 ]] && [[ "$(tail -n 1 "$R/reports/disk-history.log")" == *" APPLY used "*" freed "* ]]' "disk-history.log has a line per run (4 runs), saying freed after --apply"

echo
if (( fails )); then echo "simulate-maintenance: $fails check(s) FAILED"; exit 1; fi
echo "simulate-maintenance: all checks passed"
