#!/usr/bin/env bash
# Simulation of backup.sh, restore.sh and maintenance.sh against a fake /srv/stickman with a stub `docker`: no Docker,
# no database, nothing outside a temporary folder. Checks the per-kind retention, the 30-day database-dump folder, and
# restores from every kind of backup (nightly, deploy, old unsuffixed folders, a relative path, the oldest kept backup,
# and a dump file); the free-space check before a backup, the removal of a backup that fails part-way, and that only
# complete backups count towards the retention (default 3 deploy-time). Run on Linux with bash 5 and GNU coreutils (CI: ubuntu):
#   bash studio-app/deploy/tests/simulate-backups.sh
set -uo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd -P)
SIM=$(mktemp -d)
trap 'rm -rf "$SIM"' EXIT
export STICKMAN_ROOT="$SIM/root"
mkdir -p "$STICKMAN_ROOT"/{backups,shared,releases/r1} "$SIM/bin"
ln -s releases/r1 "$STICKMAN_ROOT/current"
echo "POSTGRES_PASSWORD=x" > "$STICKMAN_ROOT/shared/.env"

# stub df: SIM_AVAIL (bytes) stands in for the free space when set; otherwise the real df
REAL_DF=$(command -v df)
cat > "$SIM/bin/df" <<EOF
#!/usr/bin/env bash
if [[ -n "\${SIM_AVAIL:-}" && "\$*" == *--output=avail* ]]; then echo Avail; echo "\$SIM_AVAIL"; exit 0; fi
exec "$REAL_DF" "\$@"
EOF
chmod +x "$SIM/bin/df"
# stub docker: pg_dump prints a unique dump; pg_restore and the media restore record what they received; every call is
# logged (no call may ever remove a volume); SIM_MEDIA_BYTES is the media volume's measured size; SIM_TAR_FAIL makes the
# media archive fail half-written, as on 2026-11-23
cat > "$SIM/bin/docker" <<EOF
#!/usr/bin/env bash
args="\$*"
echo "\$args" >> "$SIM/docker.calls"
if [[ "\$1" == compose ]]; then
  [[ "\$args" == *pg_dump* ]] && { echo "dump-\$(date +%s%N)"; exit 0; }
  [[ "\$args" == *pg_restore* ]] && { cat > "$SIM/restored.db"; exit 0; }
  exit 0                                                   # stop / start
fi
if [[ "\$1" == run ]]; then
  [[ "\$args" == *"du -sk"* ]] && { echo "\${SIM_MEDIA_BYTES:-1048576}"; exit 0; }
  if [[ "\$args" == *" tar "* && -n "\${SIM_TAR_FAIL:-}" ]]; then
    for a in "\$@"; do [[ "\$a" == *:/backup ]] && head -c 5000 /dev/zero > "\${a%:/backup}/media.tar.gz"; done
    echo "gzip: short write: No space left on device" >&2; exit 1
  fi
  [[ "\$args" == *" tar "* ]] && echo "\$args" > "$SIM/tar.args"
  [[ "\$args" == *"find /data/work/uploads"* ]] && { printf 'hints-7-ef56ab78\nvideo-7-ab12cd34.mp4\n'; exit 0; }
  [[ "\$args" == *"rm -rf -- /data/work/uploads/"* ]] && { echo "\${@: -1}" >> "$SIM/uploads-removed"; exit 0; }
  for a in "\$@"; do
    [[ "\$a" == *:/backup ]] && echo "media-\$(date +%s%N)" > "\${a%:/backup}/media.tar.gz"
    [[ "\$a" == *:/backup:ro ]] && cp "\${a%:/backup:ro}/media.tar.gz" "$SIM/restored.media"
  done
  exit 0
fi
if [[ "\$1 \$2" == "system df" ]]; then
  if [[ "\$args" == *"|"* ]]; then printf 'Images|5.379GB|3.5GB (65%%)\nContainers|811kB|0B (0%%)\nLocal Volumes|1.778GB|0B (0%%)\nBuild Cache|44.91GB|40.17GB\n'
  else printf 'Images 3.5GB (65%%)\nBuild Cache 40.17GB\n'; fi
  exit 0
fi
[[ "\$1 \$2" == "builder prune" ]] && { echo "\$args" >> "$SIM/prune.log"; exit 0; }
[[ "\$1" == ps && "\$args" == *Names* ]] && { echo oddstudio-api-1; exit 0; }
[[ "\$1" == exec ]] && { echo "\$args" >> "$SIM/exec.log"; echo "bin: 0 item(s) in the Bin"; exit 0; }
case "\$1 \$2" in "ps --format") echo "oddstudio-api:r1" ;; "images oddstudio-api"|"images oddstudio-web") echo r1 ;; esac
exit 0
EOF
chmod +x "$SIM/bin/docker"
export PATH="$SIM/bin:$PATH"

fails=0
check() { if eval "$1"; then echo "  ok    $2"; else echo "  FAIL  $2"; fails=$((fails + 1)); fi; }
backup() { "$@" "$HERE/backup.sh" >/dev/null; sleep 1.05; }        # one-second stamps: wait between backups
B="$STICKMAN_ROOT/backups"; D="$STICKMAN_ROOT/db-dumps"
legacy() {   # an old unsuffixed backup folder, as made before the per-kind split
  mkdir -p "$B/$1"; echo "dump-$1" > "$B/$1/db.dump"; echo "media-$1" > "$B/$1/media.tar.gz"
  ( cd "$B/$1" && sha256sum db.dump media.tar.gz > SHA256SUMS )
}

echo "1. per-kind retention"
legacy 20261101T000000Z; legacy 20261102T000000Z; legacy 20261103T000000Z
for i in 1 2 3 4; do backup env KEEP_DEPLOY=5; done
check '[[ $(ls -d "$B"/*/ | grep -vc -- -nightly/) == 5 ]]' "deploy-time: 5 kept (old unsuffixed folders count as deploy-time)"
check '[[ ! -d "$B/20261101T000000Z" && ! -d "$B/20261102T000000Z" && -d "$B/20261103T000000Z" ]]' "the oldest deploy-time folders were pruned first"
for i in 1 2 3; do backup env BACKUP_KIND=nightly KEEP_NIGHTLY=2; done
check '[[ $(ls -d "$B"/*-nightly/ | wc -l) == 2 ]]' "nightly: 2 kept with KEEP_NIGHTLY=2"
check '[[ $(ls -d "$B"/*/ | grep -vc -- -nightly/) == 5 ]]' "nightly runs never prune deploy-time backups"

echo "2. the 30-day database-dump folder"
check '[[ $(ls "$D"/*.dump | wc -l) == 3 ]]' "every nightly run wrote a dump to db-dumps (3)"
check '( cd "$D" && sha256sum -c --quiet *.sha256 )' "each dump has a matching .sha256"
newest_backup=$(ls -1d "$B"/*-nightly/ | sort | tail -n 1)
check 'cmp -s "$newest_backup/db.dump" "$(ls -1 "$D"/*.dump | sort | tail -n 1)"' "the dump is the same as the one in the backup folder"
echo "old" > "$D/20261001T000000Z-nightly.dump"; ( cd "$D" && sha256sum 20261001T000000Z-nightly.dump > 20261001T000000Z-nightly.dump.sha256 )
touch -d "40 days ago" "$D/20261001T000000Z-nightly.dump"
echo "recent" > "$D/20261101T000000Z-nightly.dump"; touch -d "20 days ago" "$D/20261101T000000Z-nightly.dump"
out=$(bash "$HERE/maintenance.sh" 2>&1)
check 'grep -q "would remove  dump 20261001T000000Z-nightly.dump" <<< "$out"' "maintenance dry run lists the 40-day-old dump"
check '! grep -q "would remove  dump 20261101T000000Z" <<< "$out"' "maintenance keeps the 20-day-old dump"
check '[[ -f "$D/20261001T000000Z-nightly.dump" ]]' "the dry run removed nothing"
backup env BACKUP_KIND=nightly KEEP_NIGHTLY=2
check '[[ ! -e "$D/20261001T000000Z-nightly.dump" && ! -e "$D/20261001T000000Z-nightly.dump.sha256" ]]' "the nightly run pruned the 40-day-old dump and its .sha256"
check '[[ -f "$D/20261101T000000Z-nightly.dump" ]]' "the nightly run kept the 20-day-old dump"
mkdir -p "$SIM/lone/db-dumps"; echo "x" > "$SIM/lone/db-dumps/20250101T000000Z-nightly.dump"; touch -d "400 days ago" "$SIM/lone/db-dumps/20250101T000000Z-nightly.dump"
mkdir -p "$SIM/lone/backups" "$SIM/lone/releases/r1"; ln -s releases/r1 "$SIM/lone/current"
STICKMAN_ROOT="$SIM/lone" bash "$HERE/maintenance.sh" --apply >/dev/null 2>&1
check '[[ -f "$SIM/lone/db-dumps/20250101T000000Z-nightly.dump" ]]' "the newest dump is never pruned, however old"

echo "3. restore from every kind of backup"
restore_from() {   # restore_from <label> <path> [--media]: the database (and media) restored must be the source's
  rm -f "$SIM/restored.db" "$SIM/restored.media"
  local src=$2
  ( cd "$B" && bash "$HERE/restore.sh" "$src" ${3:-} >/dev/null 2>&1 ); local rc=$?
  local abs; abs=$(cd "$B" && cd "$(dirname "$src")" && pwd -P)/$(basename "$src")
  check "[[ $rc == 0 ]] && cmp -s '$SIM/restored.db' '${abs%/}$( [[ -d "$abs" ]] && echo /db.dump )'" "$1: database restored from it"
  [[ "${3:-}" == "--media" ]] && check "cmp -s '$SIM/restored.media' '$abs/media.tar.gz'" "$1: media restored from it"
}
# (each restore first makes its own deploy-time safety backup, which prunes old deploy-time folders: the unsuffixed
# folder is restored first, while it is still within the kept five)
check '[[ -d "$B/20261103T000000Z" ]]' "the old unsuffixed folder is still kept before the restores"
restore_from "an old unsuffixed folder" "$B/20261103T000000Z" --media
nightly=$(basename "$(ls -1d "$B"/*-nightly/ | sort | tail -n 1)")
restore_from "a -nightly folder" "$B/$nightly" --media
deploy=$(basename "$(ls -1d "$B"/*-deploy/ | sort | tail -n 1)")
restore_from "a -deploy folder, relative path" "./$deploy" --media
oldest=$(ls -1d "$B"/*/ | grep -v -- -nightly/ | sort | head -n 1); oldest=${oldest%/}
KEEP_DEPLOY=1 restore_from "the oldest kept deploy-time backup (KEEP_DEPLOY=1)" "$oldest"
check '[[ -d "$oldest" ]]' "the safety backup before the restore did not prune the folder being restored"
dump=$(ls -1 "$D"/*.dump | sort | tail -n 1)
restore_from "a dump from the 30-day folder" "$dump"
( bash "$HERE/restore.sh" "$dump" --media >/dev/null 2>&1 ); check '[[ $? == 2 ]]' "a dump with --media is refused (it holds the database only)"
cp "$dump" "$SIM/bad.dump"; cp "$dump.sha256" "$SIM/bad.dump.sha256"; echo "tampered" >> "$SIM/bad.dump"
sed -i "s#$(basename "$dump")#bad.dump#" "$SIM/bad.dump.sha256"
rm -f "$SIM/restored.db"; ( bash "$HERE/restore.sh" "$SIM/bad.dump" >/dev/null 2>&1 )
check '[[ ! -f "$SIM/restored.db" ]]' "a dump that fails its checksum is not restored"
( bash "$HERE/restore.sh" "$B/does-not-exist" >/dev/null 2>&1 ); check '[[ $? == 1 ]]' "a missing backup is refused"

echo "4. temporary uploads (audio-first Stage 1b)"
check 'grep -q -- "--exclude=./work/uploads" "$SIM/tar.args"' "the media backup excludes work/uploads"
out=$(bash "$HERE/maintenance.sh" 2>&1)
check 'grep -q "  leftover  video-7-ab12cd34.mp4" <<< "$out"' "maintenance lists upload leftovers older than 24 h"
check '[[ ! -f "$SIM/uploads-removed" ]]' "the dry run removes nothing"
out=$(bash "$HERE/maintenance.sh" --apply 2>&1)
check '[[ ! -f "$SIM/uploads-removed" ]] && grep -q "  leftover  hints-7-ef56ab78" <<< "$out"' "--apply only lists them too: nothing in the media volume is removed"
check '! grep -E "uploads" "$SIM/docker.calls" | grep -v ":/data:ro" | grep -q "oddstudio_work_data"' "the media volume is only ever mounted read-only by housekeeping"
check 'grep -q "UPLOAD_HOURS:-24" "$HERE/maintenance.sh"' "the default age is 24 h"

echo "5. the build cache cap and the deploy lock"
rm -f "$SIM/prune.log"
out=$(bash "$HERE/maintenance.sh" 2>&1)
check 'grep -q "build cache: 44.9 GB now, kept at most 10GB; would trim about 34.9 GB" <<< "$out"' "dry run: the cache size and what the cap would trim"
check 'grep -qE "^projected free after --apply: about [0-9]+G \(now [0-9]+G, as df -h counts" <<< "$out"' "dry run: the projected free space"
check '[[ ! -f "$SIM/prune.log" ]]' "the dry run prunes nothing"
bash "$HERE/maintenance.sh" --apply >/dev/null 2>&1
check 'grep -q -- "--filter until=168h" "$SIM/prune.log" && grep -q -- "--max-used-space 10GB" "$SIM/prune.log"' "--apply: the age rule, then the cache capped at 10GB"
rm -f "$SIM/prune.log"
BUILD_CACHE_MAX=5GB bash "$HERE/maintenance.sh" --apply >/dev/null 2>&1
check 'grep -q -- "--max-used-space 5GB" "$SIM/prune.log"' "BUILD_CACHE_MAX sets the cap"
check '! BUILD_CACHE_MAX=lots bash "$HERE/maintenance.sh" >/dev/null 2>&1' "a cap that is not a size is refused"
# a deploy holds the lock: nothing Docker-related is touched, the rest still runs
for i in 1 2 3 4 5 6 7; do mkdir -p "$STICKMAN_ROOT/releases/old$i"; touch -d "$i days ago" "$STICKMAN_ROOT/releases/old$i"; done
rm -f "$SIM/prune.log"
flock "$STICKMAN_ROOT/.ci-deploy.lock" sleep 3 & holder=$!      # a stand-in deploy holding the lock for 3 s
sleep 0.5
out=$(bash "$HERE/maintenance.sh" --apply 2>&1)
check 'grep -q "a deploy is running" <<< "$out"' "--apply sees the running deploy"
check '[[ ! -f "$SIM/prune.log" ]]' "no build-cache prune during a deploy"
check '[[ -d "$STICKMAN_ROOT/releases/old7" ]] && ! grep -q "removed  release" <<< "$out"' "no release removed during a deploy"
check 'grep -q "^backups:" <<< "$out" && grep -q "^done (APPLY)" <<< "$out"' "the other steps still run"
wait $holder                                                       # the deploy ends: the lock is free again
out=$(bash "$HERE/maintenance.sh" --apply 2>&1)
check '[[ ! -d "$STICKMAN_ROOT/releases/old7" ]] && grep -q -- "--max-used-space 10GB" "$SIM/prune.log"' "after the deploy: old releases go and the cache is capped"

echo "6. the Bin (items deleted in the studio over 30 days ago)"
rm -f "$SIM/exec.log"
out=$(bash "$HERE/maintenance.sh" 2>&1)
check 'grep -q "python -m oddstudio.bin purge --days 30 --dry-run" "$SIM/exec.log" && grep -q "^bin: items deleted" <<< "$out"' "dry run: the Bin is only listed"
rm -f "$SIM/exec.log"
bash "$HERE/maintenance.sh" --apply >/dev/null 2>&1
check 'grep -q "purge --days 30 --dry-run" "$SIM/exec.log" && ! grep -q "purge --days 30$" "$SIM/exec.log"' "--apply only lists the Bin too: nothing is purged"

echo "7. free space first, a failed backup cleans up after itself, only complete backups count"
export STICKMAN_ROOT="$SIM/space"; S="$STICKMAN_ROOT/backups"
mkdir -p "$S" "$STICKMAN_ROOT"/{shared,releases/r1}; ln -s releases/r1 "$STICKMAN_ROOT/current"
echo "POSTGRES_PASSWORD=x" > "$STICKMAN_ROOT/shared/.env"
backup env KEEP_DEPLOY=5; backup env KEEP_DEPLOY=5
count() { ls -1d "$S"/*/ 2>/dev/null | wc -l; }
complete_count() { local n=0 b; for b in "$S"/*/; do [[ -f "$b/SHA256SUMS" ]] && n=$((n + 1)); done; echo $n; }
before=$(ls -1 "$S")
G=1073741824
out=$(SIM_AVAIL=$(( 3 * G )) SIM_MEDIA_BYTES=$(( 2 * G )) bash "$HERE/backup.sh" 2>&1); rc=$?
check '[[ $rc == 3 ]]' "not enough room (2G media + 2G left free, 3G free): stops with exit code 3"
check 'grep -q "not enough free disk space for a deploy backup" <<< "$out" && grep -q "have 3.0G\." <<< "$out" && grep -q "nothing was written" <<< "$out"' "the message says what is needed, what is free, and that nothing was written"
check '[[ "$(ls -1 "$S")" == "$before" ]]' "no folder was written and no backup was removed"
out=$(SIM_AVAIL=$(( 6 * G )) SIM_MEDIA_BYTES=$(( 2 * G )) BACKUP_EXTRA_FREE=5G bash "$HERE/backup.sh" 2>&1); rc=$?
check '[[ $rc == 3 ]] && grep -q "for the deploy.s image build" <<< "$out"' "the deploy's build room counts too (6G free; 2G + 5G + 2G needed)"
SIM_AVAIL=$(( 10 * G )) SIM_MEDIA_BYTES=$(( 2 * G )) BACKUP_EXTRA_FREE=5G backup env KEEP_DEPLOY=5
check '[[ $(count) == 3 ]]' "with enough room (10G free) the backup is made"
before=$(ls -1 "$S"); sleep 1.05
out=$(SIM_TAR_FAIL=1 bash "$HERE/backup.sh" 2>&1); rc=$?
check '[[ $rc != 0 ]]' "a media archive that fails half-written fails the backup"
check '[[ "$(ls -1 "$S")" == "$before" ]]' "its incomplete folder is removed; every other backup stays"
check 'grep -q "removed the incomplete" <<< "$out"' "and it says so"
mkdir "$S/20200101T000000Z-deploy"; echo partial > "$S/20200101T000000Z-deploy/media.tar.gz"    # left by a killed run
for i in 1 2; do backup; done
check '[[ $(complete_count) == 3 ]]' "default deploy-time retention: the newest 3 complete backups"
check '[[ -d "$S/20200101T000000Z-deploy" ]]' "an incomplete folder is neither counted nor removed"
out=$(KEEP_DEPLOY=1 bash "$HERE/backup.sh" 2>&1); newest=$(ls -1d "$S"/*/ | sort | tail -n 1)
check '[[ $(complete_count) == 1 && -f "$newest/SHA256SUMS" ]]' "KEEP_DEPLOY=1 keeps exactly the backup just made"
mkdir "$S/$(date -u +%Y%m%dT%H%M%SZ)-deploy" 2>/dev/null; taken=$(ls -1 "$S" | sort | tail -n 1)
backup env KEEP_DEPLOY=5
check '[[ -d "$S/$taken" && $(ls -1 "$S" | sort | tail -n 1) != "$taken" ]]' "a stamp already taken is never written into: the backup takes the next second"
rm -rf "${S:?}/$taken"
check 'grep -q "20200101T000000Z-deploy/ is incomplete" <<< "$out"' "the incomplete folder is reported"
out=$(bash "$HERE/maintenance.sh" 2>&1)
check 'grep -q "incomplete 20200101T000000Z-deploy" <<< "$out" && ! grep -q "would remove  backup 20200101T000000Z" <<< "$out"' "maintenance lists the incomplete folder and leaves it"
check '! grep -qE "volume (rm|prune)|system prune|down -v|down --volumes" "$SIM/docker.calls"' "no call ever removed a Docker volume"
check '! grep -E "(tar -czf|du -sk)" "$SIM/docker.calls" | grep -v "oddstudio_work_data:/data:ro" | grep -q .' "backups only ever mount the media volume read-only"

echo
if (( fails )); then echo "simulate-backups: $fails check(s) FAILED"; exit 1; fi
echo "simulate-backups: all checks passed"
