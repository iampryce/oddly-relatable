#!/usr/bin/env bash
# AP-84B3 Pod setup (D1-6, item I4; environment lock under owner decision A5).
# NOT AUTHORISED TO RUN ON A POD: execution is owner decision D1-7.
#
# Verifies the environment, installs the pinned software, downloads the six pinned model files from
# revision-pinned URLs and verifies every SHA-256. It stops on the first mismatch. All pins and hashes come from the
# Pod bundle, which build-pod-bundle.mjs generates from the owner-approved experiment lock and environment lock;
# nothing is typed by hand here.
#
#   pod-setup.sh check          verify the bundle and the preconditions only (installs and downloads nothing)
#   pod-setup.sh environment    tier 1 BEFORE installation: Python, PyTorch, torchvision, torchaudio, the CUDA build,
#                               the image fingerprint and the GPU must match environment.lock
#   pod-setup.sh software       check out ComfyUI and the IP-Adapter node at their pinned commits
#   pod-setup.sh requirements   verify ComfyUI's requirements.txt hash, install it under constraints that forbid
#                               replacing PyTorch, then re-check tier 1 and record tier 2 (package inventory, GPU,
#                               driver, CUDA runtime, launch options)
#   pod-setup.sh models         check the free disk space, then download and verify the model files
#   pod-setup.sh verify         re-verify every model file already on disk
#
# Order: check, environment, software, requirements, models. Each step after "check" refuses to run until the
# step before it has succeeded (environment.pre.ok, software.done, environment.post.ok). The evidence records
# (environment.pre.json, environment.post.json) are written whether the check passes or fails, and never overwritten.
#
# Settings: AP84B3_BUNDLE (bundle directory), AP84B3_COMFY_DIR (where ComfyUI is installed), AP84B3_RECORD_DIR
#           (where records are written; it must be outside the ComfyUI folder), WD_STATE_DIR (the watchdog state
#           directory: setup refuses to start unless the watchdog is running).
# The image itself (pinned by digest) cannot be identified from inside the container. The operator records the
# deployed image reference in the run sheet; this script checks the image's fingerprint (CUDA, cuDNN, Python and
# PyTorch builds). No credential is used or stored: all downloads are public HTTPS files.
set -euo pipefail
umask 077

die() { printf 'pod-setup: %s\n' "$1" >&2; exit 2; }
say() { printf 'pod-setup: %s\n' "$1"; }

BUNDLE="${AP84B3_BUNDLE:-}"
COMFY="${AP84B3_COMFY_DIR:-}"
RECORD="${AP84B3_RECORD_DIR:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${AP84B3_PYTHON:-python}"

preconditions() {
  [[ -n "$BUNDLE" && -d "$BUNDLE" ]] || die "AP84B3_BUNDLE must point to the Pod bundle directory"
  # 1. The environment gate: without the approved environment lock nothing may be installed.
  [[ -f "$BUNDLE/environment.lock" ]] || die "environment.lock is missing. The environment lock has not been approved, so setup may not run."
  # 2. The bundle must be intact and must carry the approved experiment lock hash and the session allowance.
  for f in BUNDLE.SHA256SUMS LOCK_SHA256 ENVIRONMENT_SHA256 environment.env env-constraints.txt verify-environment.py session.env downloads.tsv MODELS.SHA256SUMS software.tsv; do
    [[ -f "$BUNDLE/$f" ]] || die "bundle file missing: $f"
  done
  ( cd "$BUNDLE" && sha256sum --check --strict --quiet BUNDLE.SHA256SUMS ) || die "the bundle does not match BUNDLE.SHA256SUMS"
  [[ "$(tr -d '\r\n' < "$BUNDLE/LOCK_SHA256")" =~ ^[0-9a-f]{64}$ ]] || die "LOCK_SHA256 is not a SHA-256"
  [[ "$(tr -d '\r\n' < "$BUNDLE/ENVIRONMENT_SHA256")" =~ ^[0-9a-f]{64}$ ]] || die "ENVIRONMENT_SHA256 is not a SHA-256"
  read_environment
  # 3. The runtime watchdog must already be running (owner decision D1-5), from this bundle's session allowance.
  [[ -n "${WD_STATE_DIR:-}" && -f "${WD_STATE_DIR:-}/heartbeat" ]] || die "the runtime watchdog is not running. Start it first."
  [[ ! -f "$WD_STATE_DIR/stop-reason" ]] || die "the watchdog is stopping the Pod"
  [[ -n "$COMFY" ]] || die "AP84B3_COMFY_DIR is required"
  [[ -n "$RECORD" ]] || die "AP84B3_RECORD_DIR is required"
  case "$(cd "$RECORD" 2>/dev/null && pwd)/" in "$(cd "$COMFY" 2>/dev/null && pwd)/"*) die "AP84B3_RECORD_DIR must be outside the ComfyUI folder" ;; esac
  mkdir -p "$RECORD"
  command -v sha256sum >/dev/null && command -v curl >/dev/null && command -v git >/dev/null && command -v df >/dev/null || die "sha256sum, curl, git and df are required"
}

# environment.env is generated from the environment lock: ENV_PYTHON, ENV_COMFY_REQUIREMENTS_SHA256,
# ENV_MIN_FREE_KB and ENV_LAUNCH_OPTIONS. Only these exact keys, with plain values, are accepted.
read_environment() {
  local line key val
  ENV_PYTHON=""; ENV_COMFY_REQUIREMENTS_SHA256=""; ENV_MIN_FREE_KB=""; ENV_LAUNCH_OPTIONS=""
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" =~ ^(ENV_PYTHON|ENV_COMFY_REQUIREMENTS_SHA256|ENV_MIN_FREE_KB|ENV_LAUNCH_OPTIONS)=([A-Za-z0-9.:\ _-]*)$ ]] || die "environment.env has an unexpected line"
    key="${BASH_REMATCH[1]}"; val="${BASH_REMATCH[2]}"
    printf -v "$key" '%s' "$val"
  done < "$BUNDLE/environment.env"
  [[ "$ENV_PYTHON" =~ ^3\.[0-9]+$ && "$ENV_COMFY_REQUIREMENTS_SHA256" =~ ^[0-9a-f]{64}$ && "$ENV_MIN_FREE_KB" =~ ^[0-9]+$ ]] || die "environment.env is incomplete"
}

# The watchdog decides whether work may continue. Setup never extends a limit.
gate() { "$HERE/watchdog.sh" gate >/dev/null || die "the watchdog gate is closed: no further setup step may start"; }
need_record() { [[ -f "$RECORD/$1" ]] || die "run the '$2' step first ($1 is missing)"; }

# Tier 1 before installation. The interpreter must be the pinned Python before anything else is trusted.
cmd_environment() {
  local v
  v="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" || die "no Python interpreter ($PY) found"
  [[ "$v" == "$ENV_PYTHON" ]] || die "Python is $v, the environment lock requires $ENV_PYTHON. Stopping."
  [[ ! -e "$RECORD/environment.pre.json" ]] || die "environment.pre.json already exists; records are written once"
  "$PY" "$BUNDLE/verify-environment.py" run --lock "$BUNDLE/environment.lock" --stage pre --out "$RECORD/environment.pre.json" \
    || die "the environment does not match the environment lock (see environment.pre.json). Stopping: nothing was installed."
  : > "$RECORD/environment.pre.ok"
  say "tier 1 verified before installation"
}

cmd_software() {
  need_record environment.pre.ok environment
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
  : > "$RECORD/software.done"
}

# Install ComfyUI's requirements without letting them replace PyTorch, then check tier 1 again and record tier 2.
cmd_requirements() {
  need_record software.done software
  local got
  got="$(sha256sum -- "$COMFY/requirements.txt" | cut -d' ' -f1)"
  [[ "$got" == "$ENV_COMFY_REQUIREMENTS_SHA256" ]] || die "ComfyUI's requirements.txt does not match the pinned SHA-256 (expected $ENV_COMFY_REQUIREMENTS_SHA256, got $got). Stopping."
  [[ ! -e "$RECORD/environment.post.json" ]] || die "environment.post.json already exists; records are written once"
  gate
  # The constraints pin torch, torchvision and torchaudio to the image's builds, so pip cannot replace them.
  "$PY" -m pip install --no-cache-dir --upgrade-strategy only-if-needed -r "$COMFY/requirements.txt" -c "$BUNDLE/env-constraints.txt" \
    || die "installing ComfyUI's requirements failed under the PyTorch constraints. Stopping."
  "$PY" "$BUNDLE/verify-environment.py" run --lock "$BUNDLE/environment.lock" --stage post --out "$RECORD/environment.post.json" \
    || die "after installation the environment no longer matches the environment lock (see environment.post.json). Stopping."
  printf '%s\n' "$ENV_LAUNCH_OPTIONS" > "$RECORD/launch-options.txt"
  : > "$RECORD/environment.post.ok"
  say "requirements installed; PyTorch unchanged; package inventory recorded in environment.post.json"
}

# Free space must cover every pinned model plus the margin before the first download.
disk_check() {
  local free_kb
  free_kb="$(df -Pk -- "$COMFY" | awk 'NR == 2 { print $4 }')"
  [[ "$free_kb" =~ ^[0-9]+$ ]] || die "could not read the free disk space"
  (( free_kb >= ENV_MIN_FREE_KB )) || die "not enough free disk space for the models: ${free_kb} KB free, ${ENV_MIN_FREE_KB} KB needed. Stopping before any download."
}

cmd_models() {
  need_record environment.post.ok requirements
  disk_check
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
  environment) preconditions; cmd_environment ;;
  software) preconditions; cmd_software ;;
  requirements) preconditions; cmd_requirements ;;
  models) preconditions; cmd_models ;;
  verify) preconditions; cmd_verify ;;
  *) die "usage: pod-setup.sh check|environment|software|requirements|models|verify" ;;
esac
