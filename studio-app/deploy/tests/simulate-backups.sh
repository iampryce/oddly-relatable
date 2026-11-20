#!/usr/bin/env bash
# Simulation of backup.sh, restore.sh and maintenance.sh against a fake /srv/stickman with a stub `docker`: no Docker,
# no database, nothing outside a temporary folder. Checks the per-kind retention, the 30-day database-dump folder, and
# restores from every kind of backup (nightly, deploy, old unsuffixed folders, a relative path, the oldest kept backup,
# and a dump file). Run on Linux with bash 5 and GNU coreutils (CI: ubuntu):
#   bash studio-app/deploy/tests/simulate-backups.sh
set -uo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd -P)
SIM=$(mktemp -d)
trap 'rm -rf "$SIM"' EXIT
export STICKMAN_ROOT="$SIM/root"
mkdir -p "$STICKMAN_ROOT"/{backups,shared,releases/r1} "$SIM/bin"
ln -s releases/r1 "$STICKMAN_ROOT/current"
echo "POSTGRES_PASSWORD=x" > "$STICKMAN_ROOT/shared/.env"

# stub docker: pg_dump prints a unique dump; pg_restore and the media restore record what they received
cat > "$SIM/bin/docker" <<EOF
#!/usr/bin/env bash
args="\$*"
if [[ "\$1" == compose ]]; then
  [[ "\$args" == *pg_dump* ]] && { echo "dump-\$(date +%s%N)"; exit 0; }
  [[ "\$args" == *pg_restore* ]] && { cat > "$SIM/restored.db"; exit 0; }
  exit 0                                                   # stop / start
fi
if [[ "\$1" == run ]]; then
  for a in "\$@"; do
    [[ "\$a" == *:/backup ]] && echo "media-\$(date +%s%N)" > "\${a%:/backup}/media.tar.gz"
    [[ "\$a" == *:/backup:ro ]] && cp "\${a%:/backup:ro}/media.tar.gz" "$SIM/restored.media"
  done
  exit 0
fi
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

echo
if (( fails )); then echo "simulate-backups: $fails check(s) FAILED"; exit 1; fi
echo "simulate-backups: all checks passed"
