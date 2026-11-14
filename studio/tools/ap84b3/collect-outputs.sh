#!/usr/bin/env bash
# AP-84B3 output collector (D1-6, addition A2, required by owner decision D1-5).
#
# Run on the Pod after each output is produced. It copies one finished file into the outbox under a temporary
# name, renames it when complete, and only then adds it to the checksum manifest. A file that is still being
# copied is therefore never listed, and the manifest is replaced atomically.
#
#   collect-outputs.sh add <source-file> <final-name>     e.g. add /workspace/out/00001.png candidate-a-raw.png
#   collect-outputs.sh list                               print the manifest
#
# Setting: AP84B3_OUTBOX (directory; one outbox per candidate, e.g. /workspace/outbox/A).
# Manifest format (file MANIFEST): first line "# ap84b3-manifest/1", then "<sha256>  <bytes>  <name>" per file.
# This script copies and hashes only. It never deletes an output and never extends a time limit: if the Pod is
# stopped while it runs, the file is not in the manifest and counts as not retained.
set -euo pipefail
umask 077

die() { printf 'collect-outputs: %s\n' "$1" >&2; exit 2; }

OUTBOX="${AP84B3_OUTBOX:-}"
[[ -n "$OUTBOX" ]] || die "AP84B3_OUTBOX is required"
MANIFEST="$OUTBOX/MANIFEST"
HEADER="# ap84b3-manifest/1"

cmd_add() {
  local src="${1:-}" name="${2:-}" tmp sum bytes
  [[ -n "$src" && -n "$name" ]] || die "usage: collect-outputs.sh add <source-file> <final-name>"
  [[ "$name" =~ ^[a-z0-9][a-z0-9-]{0,80}\.(png|json)$ ]] || die "final name must be lower-case letters, digits and hyphens, ending in .png or .json"
  [[ -f "$src" && ! -L "$src" ]] || die "source file not found"
  [[ -s "$src" ]] || die "source file is empty"
  mkdir -p "$OUTBOX"
  [[ ! -e "$OUTBOX/$name" ]] || die "$name is already in the outbox (outputs are write-once)"
  tmp="$OUTBOX/.$name.partial.$$"
  cp -- "$src" "$tmp"
  sync -- "$tmp" 2>/dev/null || sync
  sum="$(sha256sum -- "$tmp" | cut -d' ' -f1)"
  [[ "$sum" == "$(sha256sum -- "$src" | cut -d' ' -f1)" ]] || { rm -f -- "$tmp"; die "the copy does not match the source"; }
  bytes="$(wc -c < "$tmp" | tr -d ' ')"
  mv -- "$tmp" "$OUTBOX/$name"                       # the file is complete before it is listed
  { if [[ -f "$MANIFEST" ]]; then cat -- "$MANIFEST"; else printf '%s\n' "$HEADER"; fi
    printf '%s  %s  %s\n' "$sum" "$bytes" "$name"; } > "$MANIFEST.tmp.$$"
  mv -f -- "$MANIFEST.tmp.$$" "$MANIFEST"            # the manifest is replaced in one step
  printf '%s  %s  %s\n' "$sum" "$bytes" "$name"
}

case "${1:-}" in
  add) shift; cmd_add "$@" ;;
  list) [[ -f "$MANIFEST" ]] || die "no manifest yet"; cat -- "$MANIFEST" ;;
  *) die "usage: collect-outputs.sh add <source-file> <final-name> | list" ;;
esac
