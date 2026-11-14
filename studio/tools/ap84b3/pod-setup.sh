#!/usr/bin/env bash
# AP-84B3 Pod setup (D1-6, item I4). NOT AUTHORISED TO RUN: execution is owner decision D1-7.
#
# Installs the pinned software, downloads the six pinned model files from revision-pinned URLs and verifies
# every SHA-256. It stops on the first mismatch or missing file. All pins and hashes come from the Pod bundle,
# which build-pod-bundle.mjs generates from the owner-approved experiment lock; nothing is typed by hand here.
#
#   pod-setup.sh check       verify the bundle and the preconditions only (downloads nothing)
#   pod-setup.sh software    check out ComfyUI and the IP-Adapter node at their pinned commits
#   pod-setup.sh models      download and verify the model files
#   pod-setup.sh verify      re-verify every model file already on disk
#
# Settings: AP84B3_BUNDLE (bundle directory), AP84B3_COMFY_DIR (where ComfyUI is installed),
#           WD_STATE_DIR (the watchdog state directory: setup refuses to start unless the watchdog is running).
#
# UNRESOLVED ON PURPOSE: the Python environment (PyTorch version) and the Pod base image. This script installs
# no Python packages. It requires the file environment.lock in the bundle, which only a separately reviewed and
# owner-approved environment proposal may create. Without it, every command stops before doing anything.
# No credential is used or stored: all downloads are public HTTPS files.
set -euo pipefail
umask 077

die() { printf 'pod-setup: %s\n' "$1" >&2; exit 2; }
say() { printf 'pod-setup: %s\n' "$1"; }

BUNDLE="${AP84B3_BUNDLE:-}"
COMFY="${AP84B3_COMFY_DIR:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

preconditions() {
  [[ -n "$BUNDLE" && -d "$BUNDLE" ]] || die "AP84B3_BUNDLE must point to the Pod bundle directory"
  # 1. The environment proposal gate: without an approved environment lock nothing may be installed.
  [[ -f "$BUNDLE/environment.lock" ]] || die "environment.lock is missing. The PyTorch and base-image proposal has not been approved, so setup may not run."
  # 2. The bundle must be intact and must carry the approved experiment lock hash.
  for f in BUNDLE.SHA256SUMS LOCK_SHA256 downloads.tsv MODELS.SHA256SUMS software.tsv; do
    [[ -f "$BUNDLE/$f" ]] || die "bundle file missing: $f"
  done
  ( cd "$BUNDLE" && sha256sum --check --strict --quiet BUNDLE.SHA256SUMS ) || die "the bundle does not match BUNDLE.SHA256SUMS"
  [[ "$(tr -d '\r\n' < "$BUNDLE/LOCK_SHA256")" =~ ^[0-9a-f]{64}$ ]] || die "LOCK_SHA256 is not a SHA-256"
  # 3. The runtime watchdog must already be running (owner decision D1-5).
  [[ -n "${WD_STATE_DIR:-}" && -f "${WD_STATE_DIR:-}/heartbeat" ]] || die "the runtime watchdog is not running. Start it first."
  [[ ! -f "$WD_STATE_DIR/stop-reason" ]] || die "the watchdog is stopping the Pod"
  [[ -n "$COMFY" ]] || die "AP84B3_COMFY_DIR is required"
  command -v sha256sum >/dev/null && command -v curl >/dev/null && command -v git >/dev/null || die "sha256sum, curl and git are required"
}

# The watchdog decides whether work may continue. Setup never extends a limit.
gate() { "$HERE/watchdog.sh" gate >/dev/null || die "the watchdog gate is closed: no further setup step may start"; }

cmd_software() {
  local name repo commit dest target head
  while IFS=$'\t' read -r name repo commit dest || [[ -n "${name:-}" ]]; do
    [[ -z "${name:-}" || "$name" == \#* ]] && continue
    [[ "$repo" =~ ^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ && "$commit" =~ ^[0-9a-f]{40}$ ]] || die "software.tsv: unexpected entry for $name"
    [[ "$dest" != /* && "$dest" != *..* ]] || die "software.tsv: unsafe destination for $name"
    gate
    if [[ "$dest" == "." ]]; then target="$COMFY"; else target="$COMFY/$dest"; fi
    if [[ ! -d "$target/.git" ]]; then
      git clone --no-checkout -- "$repo" "$target"
    fi
    git -C "$target" fetch --quiet origin "$commit" || git -C "$target" fetch --quiet origin
    git -C "$target" checkout --quiet --detach "$commit"
    head="$(git -C "$target" rev-parse HEAD)"
    [[ "$head" == "$commit" ]] || die "$name is at $head, not the pinned commit $commit"
    say "$name at pinned commit $commit"
  done < "$BUNDLE/software.tsv"
}

cmd_models() {
  local url dest sum target got
  while IFS=$'\t' read -r url dest sum || [[ -n "${url:-}" ]]; do
    [[ -z "${url:-}" || "$url" == \#* ]] && continue
    [[ "$url" =~ ^https://huggingface\.co/[A-Za-z0-9._/-]+/resolve/[0-9a-f]{40}/[A-Za-z0-9._/-]+$ ]] || die "downloads.tsv: unexpected URL"
    [[ "$sum" =~ ^[0-9a-f]{64}$ && "$dest" != /* && "$dest" != *..* ]] || die "downloads.tsv: unexpected entry for $dest"
    target="$COMFY/$dest"
    if [[ -f "$target" ]]; then
      got="$(sha256sum -- "$target" | cut -d' ' -f1)"
      [[ "$got" == "$sum" ]] || die "$dest exists but does not match its pinned SHA-256"
      say "$dest already present and verified"
      continue
    fi
    gate
    mkdir -p "$(dirname "$target")"
    curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 --retry 3 --output "$target.partial" -- "$url" || die "download failed: $dest"
    got="$(sha256sum -- "$target.partial" | cut -d' ' -f1)"
    if [[ "$got" != "$sum" ]]; then
      rm -f -- "$target.partial"
      die "SHA-256 mismatch for $dest (expected $sum, got $got). Stopping."
    fi
    mv -- "$target.partial" "$target"
    say "$dest downloaded and verified"
  done < "$BUNDLE/downloads.tsv"
  cmd_verify
}

cmd_verify() {
  ( cd "$COMFY" && sha256sum --check --strict --quiet "$BUNDLE/MODELS.SHA256SUMS" ) || die "a model file is missing or does not match MODELS.SHA256SUMS"
  say "all model files match the approved hashes"
}

case "${1:-}" in
  check) preconditions; say "bundle and preconditions verified" ;;
  software) preconditions; cmd_software ;;
  models) preconditions; cmd_models ;;
  verify) preconditions; cmd_verify ;;
  *) die "usage: pod-setup.sh check|software|models|verify" ;;
esac
