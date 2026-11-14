#!/usr/bin/env bash
# AP-84B3 runtime watchdog (D1-6, addition A1, required by owner decision D1-5).
#
# Stops the Pod at the approved runtime milestone or when ESTIMATED consumption reaches the approved threshold,
# whichever comes first. It does not look at what else is running: a transfer, retry or shutdown step in
# progress never delays it.
#
# CUMULATIVE ACROSS SESSIONS (owner decision A2). The limits cover the whole experiment, not one Pod session.
# The watchdog reads the session's allowance from the sealed session file in the Pod bundle (session.env,
# generated from the local session ledger and covered by BUNDLE.SHA256SUMS): the session number, the runtime
# already used and the consumption already used. It adds those to this session's elapsed time and estimate, and
# applies the fixed thresholds to the TOTALS. A session therefore only ever gets what remains, never a fresh
# full allowance. The prior values cannot be given on the command line or in the environment.
# Limits of this control: the session file is only as good as the ledger it came from, and the consumption in the
# ledger is entered by a person from the provider's console. The provider's balance (one $10 deposit, auto-pay
# off) and the manual stop in the web console remain the independent safeguards.
#
#   watchdog.sh run      start the watchdog loop (keep it alive with: nohup setsid watchdog.sh run &)
#   watchdog.sh gate     exit 0 only if a new generation or retry may start now
#   watchdog.sh status   print the last recorded state
#
# AUTHENTICATION IS UNRESOLVED UNTIL D1-7. This script holds no credential, accepts none as an argument and
# makes no assumption that the platform injects one. It calls the stop command it is given:
#       "$WD_STOP_CMD" "$WD_POD_ID"
# How that command authenticates, and where the Pod identifier comes from, must be verified in the D1-7 live
# test. Never place an account-level API key in the repository or the Pod bundle. The manual stop in the web
# console (see the runbook) is independent of this script.
#
# THE CONSUMPTION FIGURE IS AN ESTIMATE, not a provider billing measurement. It is never GPU compute alone:
#   hourly total = max(recorded GPU rate, approved GPU rate cap)
#                + container disk (GB x $/GB/month / hours-per-month assumption)
#                + every extra resource in WD_RESOURCES_FILE, each already normalised to an hourly rate
#   estimate     = consumption already used in earlier sessions
#                + this session's elapsed seconds x hourly total / 3600 + one-off charges   (all rounded up)
# Rates with different billing periods are never added directly: the resources file must state each rate's
# period and conversion, and this script recomputes the hourly figure and refuses a mismatch.
#
# Required settings (environment):
#   WD_STATE_DIR                  directory for state, heartbeat and log
#   WD_POD_START_EPOCH            Pod start time (Unix seconds), as recorded by the operator
#   WD_POD_ID                     Pod identifier, passed to the stop command
#   WD_STOP_CMD                   path to an executable that stops the Pod (no default)
#   WD_GPU_RATE_USD_PER_HOUR      GPU rate recorded in the console at deployment
#   WD_GPU_RATE_CAP_USD_PER_HOUR  approved cap for this GPU (1.09 for the L40S, 0.59 for the A40)
#   WD_DISK_GB                    container disk size in GB
#   WD_DISK_USD_PER_GB_MONTH      container disk price
#   WD_RESOURCES_FILE             extra billable resources (see below); must exist even when there are none
#   WD_BUNDLE_DIR                 the Pod bundle; its session.env must match BUNDLE.SHA256SUMS
# Optional (may only tighten the approved limits, never loosen them):
#   WD_STOP_SECONDS (default and maximum 10200)          WD_NO_NEW_GENERATION_SECONDS (default and maximum 8400)
#   WD_ESTIMATE_STOP_USD (default and maximum 4.75)      WD_HOURS_PER_MONTH (default and maximum 672)
#   WD_TICK_SECONDS (default 10, 1 to 30)                WD_WORK_PID_FILE (process to end if the stop command fails)
# Test only (requires WD_TEST_MODE=1; never set on a Pod): WD_NOW_CMD, WD_TIME_SCALE, WD_RETRY_SECONDS.
#
# Resources file: first line "# ap84b3-resources/1", then one tab-separated line per resource:
#   name <TAB> published_rate_usd <TAB> period <TAB> quantity <TAB> conversion <TAB> hourly_usd
# period is one of: hour, second, day, month, gb-month, one-off. For one-off, hourly_usd must be 0.
set -euo pipefail
umask 077

MAX_STOP_SECONDS=10200           # 2 h 50 min: the watchdog stop milestone (the absolute limit is 3 h)
MAX_NO_NEW_GENERATION=8400       # 2 h 20 min
MAX_ESTIMATE_STOP_MICRO=4750000  # $4.75: conservative estimated stop threshold (the absolute ceiling is $5.00)
MAX_HOURS_PER_MONTH=672          # 28-day month, so monthly prices err high

die() { printf 'watchdog: %s\n' "$1" >&2; exit 2; }

# Decimal dollars ("1.09") -> integer micro-dollars. Rejects anything that is not a plain decimal.
usd_to_micro() {
  local v="$1" w f
  [[ "$v" =~ ^[0-9]+(\.[0-9]{1,6})?$ ]] || return 1
  w="${v%%.*}"; f=""
  [[ "$v" == *.* ]] && f="${v#*.}"
  f="${f}000000"; f="${f:0:6}"
  printf '%d' "$(( 10#$w * 1000000 + 10#$f ))"
}
is_uint() { [[ "$1" =~ ^[0-9]+$ ]]; }
ceil_div() { printf '%d' "$(( ($1 + $2 - 1) / $2 ))"; }

now() {
  if [[ "${WD_TEST_MODE:-0}" == "1" && -n "${WD_NOW_CMD:-}" ]]; then "$WD_NOW_CMD"; else date +%s; fi
}

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >> "$WD_STATE_DIR/watchdog.log"; }

# Atomic file write: temporary file in the same directory, then rename.
put() { local f="$WD_STATE_DIR/$1"; printf '%s\n' "$2" > "$f.tmp.$$"; mv -f "$f.tmp.$$" "$f"; }

load_config() {
  [[ -n "${WD_STATE_DIR:-}" ]] || die "WD_STATE_DIR is required"
  mkdir -p "$WD_STATE_DIR"
  MODE=production; SCALE=1
  if [[ "${WD_TEST_MODE:-0}" == "1" ]]; then
    MODE=test
    SCALE="${WD_TIME_SCALE:-1}"
    is_uint "$SCALE" && (( SCALE >= 1 )) || die "WD_TIME_SCALE must be an integer of at least 1"
  else
    [[ -z "${WD_NOW_CMD:-}" && -z "${WD_TIME_SCALE:-}" && -z "${WD_RETRY_SECONDS:-}" ]] || die "WD_NOW_CMD, WD_TIME_SCALE and WD_RETRY_SECONDS are test-only settings"
  fi
  START="${WD_POD_START_EPOCH:-}"
  is_uint "$START" && (( START > 0 )) || die "WD_POD_START_EPOCH is missing or invalid"
  STOP_SECONDS="${WD_STOP_SECONDS:-$MAX_STOP_SECONDS}"
  is_uint "$STOP_SECONDS" && (( STOP_SECONDS >= 1 && STOP_SECONDS <= MAX_STOP_SECONDS )) || die "WD_STOP_SECONDS must be 1 to $MAX_STOP_SECONDS"
  NO_NEW="${WD_NO_NEW_GENERATION_SECONDS:-$MAX_NO_NEW_GENERATION}"
  is_uint "$NO_NEW" && (( NO_NEW >= 0 && NO_NEW <= MAX_NO_NEW_GENERATION && NO_NEW < STOP_SECONDS )) || die "WD_NO_NEW_GENERATION_SECONDS must be 0 to $MAX_NO_NEW_GENERATION and below the stop time"
  TICK="${WD_TICK_SECONDS:-10}"
  is_uint "$TICK" && (( TICK >= 1 && TICK <= 30 )) || die "WD_TICK_SECONDS must be 1 to 30"
  RETRY="${WD_RETRY_SECONDS:-$TICK}"
  is_uint "$RETRY" && (( RETRY >= 1 && RETRY <= 30 )) || die "WD_RETRY_SECONDS must be 1 to 30"
}

# The sealed session allowance. Values come only from the bundle's session.env, which must match the bundle
# checksums. Sets SESSION, PRIOR_RUNTIME, PRIOR_CONSUMED (micro-dollars) and LEDGER_HEAD.
load_session() {
  local f line key val sum want got
  for v in WD_SESSION_NUMBER WD_PRIOR_RUNTIME_SECONDS WD_PRIOR_CONSUMED_USD WD_LEDGER_HEAD; do
    [[ -z "${!v:-}" ]] || die "$v must come from the sealed session file, not from the environment"
  done
  [[ -n "${WD_BUNDLE_DIR:-}" && -d "${WD_BUNDLE_DIR:-}" ]] || die "WD_BUNDLE_DIR is required (the Pod bundle holding session.env)"
  f="$WD_BUNDLE_DIR/session.env"
  [[ -f "$f" && ! -L "$f" ]] || die "session.env is missing from the bundle: no session allowance, so the watchdog will not start"
  [[ -f "$WD_BUNDLE_DIR/BUNDLE.SHA256SUMS" ]] || die "BUNDLE.SHA256SUMS is missing from the bundle"
  want="$(awk '$2 == "session.env" { print $1 }' "$WD_BUNDLE_DIR/BUNDLE.SHA256SUMS")"
  [[ "$want" =~ ^[0-9a-f]{64}$ ]] || die "BUNDLE.SHA256SUMS does not cover session.env"
  got="$(sha256sum -- "$f" | cut -d' ' -f1)"
  [[ "$got" == "$want" ]] || die "session.env does not match BUNDLE.SHA256SUMS (it was changed after the bundle was built)"
  SESSION=""; PRIOR_RUNTIME=""; PRIOR_CONSUMED=""; LEDGER_HEAD=""
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" =~ ^(WD_SESSION_NUMBER|WD_PRIOR_RUNTIME_SECONDS|WD_PRIOR_CONSUMED_USD|WD_LEDGER_HEAD)=([A-Za-z0-9.]+)$ ]] || die "session.env has an unexpected line"
    key="${BASH_REMATCH[1]}"; val="${BASH_REMATCH[2]}"
    case "$key" in
      WD_SESSION_NUMBER) SESSION="$val" ;;
      WD_PRIOR_RUNTIME_SECONDS) PRIOR_RUNTIME="$val" ;;
      WD_PRIOR_CONSUMED_USD) PRIOR_CONSUMED="$(usd_to_micro "$val")" || die "WD_PRIOR_CONSUMED_USD in session.env is not a number" ;;
      WD_LEDGER_HEAD) LEDGER_HEAD="$val" ;;
    esac
  done < "$f"
  is_uint "$SESSION" && (( SESSION >= 1 )) || die "session.env: WD_SESSION_NUMBER is missing or invalid"
  is_uint "$PRIOR_RUNTIME" || die "session.env: WD_PRIOR_RUNTIME_SECONDS is missing or invalid"
  is_uint "$PRIOR_CONSUMED" || die "session.env: WD_PRIOR_CONSUMED_USD is missing or invalid"
  [[ "$LEDGER_HEAD" =~ ^[0-9a-f]{64}$ ]] || die "session.env: WD_LEDGER_HEAD is missing or invalid"
  if (( SESSION == 1 )); then
    (( PRIOR_RUNTIME == 0 && PRIOR_CONSUMED == 0 )) || die "session.env: session 1 cannot have earlier runtime or consumption"
  fi
}

load_run_config() {
  load_config
  load_session
  [[ -n "${WD_POD_ID:-}" ]] || die "WD_POD_ID is required (the Pod identifier is not assumed)"
  [[ "$WD_POD_ID" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || die "WD_POD_ID has an unexpected format"
  [[ -n "${WD_STOP_CMD:-}" ]] || die "WD_STOP_CMD is required (there is no default stop command)"
  [[ -f "$WD_STOP_CMD" && -x "$WD_STOP_CMD" ]] || die "WD_STOP_CMD must be an executable file"

  local recorded cap disk_rate thr
  recorded="$(usd_to_micro "${WD_GPU_RATE_USD_PER_HOUR:-}")" || die "WD_GPU_RATE_USD_PER_HOUR is missing or not a number"
  cap="$(usd_to_micro "${WD_GPU_RATE_CAP_USD_PER_HOUR:-}")" || die "WD_GPU_RATE_CAP_USD_PER_HOUR is missing or not a number"
  (( recorded > 0 && cap > 0 )) || die "GPU rates must be greater than zero"
  (( recorded <= cap )) || die "the recorded GPU rate is above the approved cap"
  GPU_HOURLY=$(( recorded > cap ? recorded : cap ))        # the higher of the recorded rate and the cap

  is_uint "${WD_DISK_GB:-}" && (( WD_DISK_GB >= 1 )) || die "WD_DISK_GB is missing or invalid"
  disk_rate="$(usd_to_micro "${WD_DISK_USD_PER_GB_MONTH:-}")" || die "WD_DISK_USD_PER_GB_MONTH is missing or not a number"
  (( disk_rate > 0 )) || die "WD_DISK_USD_PER_GB_MONTH must be greater than zero"
  HOURS_PER_MONTH="${WD_HOURS_PER_MONTH:-$MAX_HOURS_PER_MONTH}"
  is_uint "$HOURS_PER_MONTH" && (( HOURS_PER_MONTH >= 1 && HOURS_PER_MONTH <= MAX_HOURS_PER_MONTH )) || die "WD_HOURS_PER_MONTH must be 1 to $MAX_HOURS_PER_MONTH"
  DISK_HOURLY="$(ceil_div $(( WD_DISK_GB * disk_rate )) "$HOURS_PER_MONTH")"

  thr="$(usd_to_micro "${WD_ESTIMATE_STOP_USD:-4.75}")" || die "WD_ESTIMATE_STOP_USD is not a number"
  (( thr >= 1 && thr <= MAX_ESTIMATE_STOP_MICRO )) || die "WD_ESTIMATE_STOP_USD must not exceed 4.75"
  THRESHOLD="$thr"

  load_resources
  HOURLY_TOTAL=$(( GPU_HOURLY + DISK_HOURLY + EXTRA_HOURLY ))
  # Nothing remains: the earlier sessions already reached a threshold. Refuse to start.
  (( PRIOR_RUNTIME < STOP_SECONDS )) || die "no runtime remains: earlier sessions used ${PRIOR_RUNTIME}s of the ${STOP_SECONDS}s allowance"
  (( PRIOR_RUNTIME < NO_NEW )) || die "no generation can start: earlier sessions used ${PRIOR_RUNTIME}s, past the ${NO_NEW}s cut-off"
  (( PRIOR_CONSUMED + ONE_OFF < THRESHOLD )) || die "no consumption allowance remains: earlier sessions used ${PRIOR_CONSUMED} of ${THRESHOLD} micro-dollars"
}

# Extra billable resources. Every entry must state its billing period and conversion; the hourly figure is
# recomputed here and must match. A missing file is an error: an omitted resource must never count as zero.
load_resources() {
  EXTRA_HOURLY=0; ONE_OFF=0; RESOURCE_COUNT=0
  [[ -n "${WD_RESOURCES_FILE:-}" && -f "${WD_RESOURCES_FILE:-}" ]] || die "WD_RESOURCES_FILE is required (list of other billable resources, even if empty)"
  local first=1 line name rate period qty conv hourly r h expect
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    if (( first )); then
      [[ "$line" == "# ap84b3-resources/1" ]] || die "WD_RESOURCES_FILE must start with '# ap84b3-resources/1'"
      first=0; continue
    fi
    [[ -z "$line" || "$line" == \#* ]] && continue
    IFS=$'\t' read -r name rate period qty conv hourly <<< "$line"
    [[ -n "${name:-}" && -n "${conv:-}" && -n "${hourly:-}" ]] || die "resource entry needs name, rate, period, quantity, conversion and hourly rate"
    r="$(usd_to_micro "${rate:-}")" || die "resource '$name': published rate is not a number"
    h="$(usd_to_micro "$hourly")" || die "resource '$name': hourly rate is not a number"
    is_uint "${qty:-}" && (( qty >= 1 )) || die "resource '$name': quantity must be a positive integer"
    case "${period:-}" in
      hour)     expect=$(( r * qty )) ;;
      second)   expect=$(( r * qty * 3600 )) ;;
      day)      expect="$(ceil_div $(( r * qty )) 24)" ;;
      month)    expect="$(ceil_div $(( r * qty )) "$HOURS_PER_MONTH")" ;;
      gb-month) expect="$(ceil_div $(( r * qty )) "$HOURS_PER_MONTH")" ;;
      one-off)  expect=0; ONE_OFF=$(( ONE_OFF + r * qty )) ;;
      *)        die "resource '$name': billing period '${period:-}' is not recognised, so it cannot be normalised to an hourly rate" ;;
    esac
    (( h == expect )) || die "resource '$name': the hourly rate does not match its published rate and billing period (rates with different billing periods are never added directly)"
    EXTRA_HOURLY=$(( EXTRA_HOURLY + expect ))
    RESOURCE_COUNT=$(( RESOURCE_COUNT + 1 ))
  done < "$WD_RESOURCES_FILE"
  (( first == 0 )) || die "WD_RESOURCES_FILE is empty (it must start with '# ap84b3-resources/1')"
}

estimate_micro() { printf '%d' "$(( PRIOR_CONSUMED + ($1 * HOURLY_TOTAL + 3599) / 3600 + ONE_OFF ))"; }

stop_pod() {
  local reason="$1" attempt=0
  put stop-reason "$reason"                        # closes the gate: no new generation may start
  log "STOP reason=$reason"
  while :; do
    attempt=$(( attempt + 1 ))
    if "$WD_STOP_CMD" "$WD_POD_ID" >> "$WD_STATE_DIR/stop-command.log" 2>&1; then
      put stopped "reason=$reason attempts=$attempt"
      log "stop command succeeded attempts=$attempt"
      exit 0
    fi
    log "stop command FAILED attempt=$attempt"
    if (( attempt == 3 )); then
      # The Pod is still billing. Raise the alarm and end the work process so nothing new starts.
      # This does NOT stop billing: the operator must stop the Pod in the web console now.
      put ALARM "stop command failed $attempt times (reason=$reason). STOP THE POD IN THE WEB CONSOLE NOW."
      if [[ -n "${WD_WORK_PID_FILE:-}" && -f "$WD_WORK_PID_FILE" ]]; then
        local pid; pid="$(head -n 1 "$WD_WORK_PID_FILE" | tr -cd '0-9')"
        [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
      fi
    fi
    sleep "$RETRY"
  done
}

cmd_run() {
  load_run_config
  local t prev elapsed total est
  t="$(now)"; is_uint "$t" || die "the clock did not return a valid time"
  (( START <= t )) || die "WD_POD_START_EPOCH is in the future"
  rm -f "$WD_STATE_DIR/stopped" "$WD_STATE_DIR/ALARM"
  log "start mode=$MODE session=$SESSION prior_runtime_seconds=$PRIOR_RUNTIME prior_consumed_micro=$PRIOR_CONSUMED ledger_head=$LEDGER_HEAD stop_seconds=$STOP_SECONDS no_new_generation_seconds=$NO_NEW threshold_micro=$THRESHOLD gpu_hourly_micro=$GPU_HOURLY disk_hourly_micro=$DISK_HOURLY extra_hourly_micro=$EXTRA_HOURLY one_off_micro=$ONE_OFF resources=$RESOURCE_COUNT hourly_total_micro=$HOURLY_TOTAL tick=$TICK"
  prev=""
  while :; do
    t="$(now)"
    is_uint "$t" || stop_pod "clock-unreadable"
    if [[ -n "$prev" ]]; then
      # A clock that runs backwards, or a gap far longer than one tick (clock jump or suspended process),
      # makes the elapsed time and the estimate unreliable: stop early.
      (( t >= prev )) || stop_pod "clock-went-backwards"
      (( t - prev <= TICK * 3 + 5 )) || stop_pod "clock-jump-or-heartbeat-gap"
    fi
    prev="$t"
    elapsed=$(( (t - START) * SCALE ))
    total=$(( PRIOR_RUNTIME + elapsed ))
    est="$(estimate_micro "$elapsed")"
    put state "mode=$MODE session=$SESSION prior_runtime_seconds=$PRIOR_RUNTIME prior_consumed_micro_usd=$PRIOR_CONSUMED total_elapsed_seconds=$total elapsed_seconds=$elapsed estimate_micro_usd=$est threshold_micro_usd=$THRESHOLD hourly_total_micro_usd=$HOURLY_TOTAL gpu_hourly_micro_usd=$GPU_HOURLY disk_hourly_micro_usd=$DISK_HOURLY extra_hourly_micro_usd=$EXTRA_HOURLY one_off_micro_usd=$ONE_OFF stop_seconds=$STOP_SECONDS"
    put heartbeat "$t"
    (( total < STOP_SECONDS )) || stop_pod "runtime-limit"
    (( est < THRESHOLD )) || stop_pod "estimated-consumption"
    sleep "$TICK"
  done
}

# May a new generation or retry start? Only before the cut-off, with no stop under way and a live watchdog.
cmd_gate() {
  load_config
  load_session
  local t hb elapsed
  [[ ! -f "$WD_STATE_DIR/stop-reason" ]] || { echo "gate: closed (the watchdog is stopping the Pod)"; exit 1; }
  [[ -f "$WD_STATE_DIR/heartbeat" ]] || { echo "gate: closed (the watchdog is not running)"; exit 1; }
  t="$(now)"; hb="$(head -n 1 "$WD_STATE_DIR/heartbeat" | tr -cd '0-9')"
  is_uint "$t" && is_uint "$hb" || { echo "gate: closed (time or heartbeat unreadable)"; exit 1; }
  (( t >= hb && t - hb <= TICK * 3 + 5 )) || { echo "gate: closed (the watchdog heartbeat is stale)"; exit 1; }
  elapsed=$(( (t - START) * SCALE ))
  (( elapsed >= 0 && PRIOR_RUNTIME + elapsed < NO_NEW )) || { echo "gate: closed (past the no-new-generation cut-off, counting earlier sessions)"; exit 1; }
  echo "gate: open (session ${SESSION}: ${elapsed}s here, $(( PRIOR_RUNTIME + elapsed ))s in total, cut-off ${NO_NEW}s)"
}

cmd_status() {
  load_config
  for f in state heartbeat stop-reason stopped ALARM; do
    [[ -f "$WD_STATE_DIR/$f" ]] && printf '%s: %s\n' "$f" "$(head -n 1 "$WD_STATE_DIR/$f")"
  done
  return 0
}

case "${1:-}" in
  run) cmd_run ;;
  gate) cmd_gate ;;
  status) cmd_status ;;
  *) die "usage: watchdog.sh run|gate|status" ;;
esac
