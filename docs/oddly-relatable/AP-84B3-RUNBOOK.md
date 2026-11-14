# AP-84B3 runbook: three-candidate experiment

**Status (2026-11-13): NOT AUTHORISED TO EXECUTE.**
- This runbook was written under owner decision D1-6 (implementation). It describes a future run.
- Execution is owner decision **D1-7**, which has not been given. No account, funding, Pod, download or image generation is authorised.
- Two further gates sit before D1-7:
  1. **Experiment lock approval.** The owner reviews `studio/config/ap84b3-experiment.json` and its canonical hash. Only then is the hash recorded in `DECISIONS.md`. Until then every tool refuses to run.
  2. **Environment proposal.** A separately reviewed, reproducible proposal for the PyTorch version and the Pod base image. `pod-setup.sh` refuses to run without the `environment.lock` that proposal would add.
- Every D1-7 approval must name the approved lock hash.

Related: `AP-84B3-D1-EXPERIMENT-SPECIFICATION.md` (what is being tested) and `DECISIONS.md` (the authoritative record).

## 1. Fixed limits

| Limit | Value | Kind |
|---|---|---|
| Funding | One $10 deposit. No additional funding without fresh owner approval | Cash committed; credits are non-refundable |
| Consumption ceiling | $5.00 for the whole experiment | Absolute |
| Watchdog estimate stop | $4.75 | Conservative estimated threshold |
| Pod runtime | 3 hours | Absolute |
| GPU rate cap | L40S $1.09/hour; A40 $0.59/hour | Do not deploy above the cap |

- The $0.25 between $4.75 and $5.00 is a margin for estimate error and stopping delay. **It is not permission to continue.**
- Nothing in this runbook extends a limit. A transfer, retry or shutdown step in progress is cut off.

## 2. Milestones

Conservative operational targets. None changes the 3-hour limit.

| Time from Pod start | Rule |
|---|---|
| 2 h 20 min | No new generation or retry may start |
| 2 h 35 min | All transfers complete and verified |
| 2 h 45 min | Local timer alert: prepare to stop manually |
| 2 h 50 min | The watchdog stops the Pod unconditionally |
| 2 h 55 min | Stop the Pod in the web console if it is still running |
| 3 h 00 min | Absolute limit |

## 3. Unresolved until D1-7

These cannot be verified without a Pod. Each is checked in the live test (§8) before anything is downloaded. If any cannot be resolved as written, **stop and return to the owner**.

| # | Item | Position |
|---|---|---|
| U1 | How the on-Pod stop command authenticates | Unknown. Nothing is assumed about injected credentials. An account-level API key must never be placed on the Pod, in the bundle or in the repository |
| U2 | Where the Pod identifier comes from | Unknown. The watchdog refuses to start without one |
| U3 | Whether RunPod's SSH mode supports file copy | Unverified. A direct SSH connection is believed to be needed |
| U4 | Whether the pinned ComfyUI and IP-Adapter node run together | Execution risk. No substitution and no pin change |
| U5 | PyTorch version and Pod base image | Decided by the separate environment proposal |
| U6 | How RunPod converts monthly prices to per-second billing | Unverified. The estimate uses a 672-hour month, which errs high |
| U7 | The exact Qwen node graph and shift value as exported | Exported, checked, hashed and recorded on the Pod (§10) |

## 4. Step 0: confirm the lock hash

1. Compute the canonical hash with the project tool:
   ```
   node -e "import('./studio/lib/experiment-spec.mjs').then(m=>console.log(m.loadLock({requireApproved:false}).sha256))"
   ```
2. Compute it independently, with no project code. Save this as `check_lock.py` outside the repository and run `python check_lock.py` from the repository root:
   ```python
   import json, hashlib

   def no_duplicates(pairs):
       d = {}
       for k, v in pairs:
           if k in d:
               raise SystemExit('duplicate key ' + k)
           d[k] = v
       return d

   def no_decimals(s):
       raise SystemExit('non-integer number ' + s)

   text = open('studio/config/ap84b3-experiment.json', encoding='utf-8-sig').read()
   lock = json.loads(text, object_pairs_hook=no_duplicates, parse_float=no_decimals)
   canonical = json.dumps(lock, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
   print(hashlib.sha256(canonical.encode('utf-8')).hexdigest())
   ```
3. Both must equal the hash named in the D1-7 approval and the `AP-84B3-LOCK-APPROVED-SHA256=` line in `DECISIONS.md`.

**Canonical hashing procedure:** read as UTF-8 and drop a byte-order mark; parse as JSON, rejecting duplicate keys and any non-integer number (decimals are stored as strings); write back with keys sorted by Unicode code point, arrays in order, no whitespace and strings as stored; SHA-256 of the UTF-8 bytes, lowercase hexadecimal.

**Evidence:** both hashes, and the commit of the repository used.

## 5. Step 1: local preparation ($0)

1. Verify master v3 and the approved pose 02 against the hashes in the lock.
2. Build the `character-01` reference pack in the studio. Record its ID and hash.
3. Create the run folder **outside the repository**, named `r-YYYYMMDD-HHMMSS`. Outputs are never committed.
4. Build the Pod bundle:
   ```
   node studio/tools/ap84b3/build-pod-bundle.mjs --out <folder outside the repository>
   ```
5. Add the approved `environment.lock` to the bundle (from the environment proposal).
6. Start a run sheet (`run-sheet.json`, schema `ap84b3-run-sheet/1`) with the lock hash.

**Evidence:** reference pack ID and hash; bundle `BUNDLE.SHA256SUMS`.

## 6. Step 2: account and funding

Each record needs a timestamp and a screenshot.

1. **Auto-pay.** Confirm in the billing page that auto-pay is **disabled**. Do not fund until this is recorded.
2. **Before funding.** Record the account balance. Confirm no Pod, volume disk, network volume or other resource exists.
3. **Deposit.** Make one $10 deposit by a regular credit or debit card. A prepaid card requires $100 per transaction and must not be used.
4. **After funding.** Record the balance. This is the **baseline**.
5. **Check.** After-funding balance minus before-funding balance must equal $10.00. If not, do not deploy; return to the owner.

**Actual consumption** is worked out two ways during the run:
- **Balance method:** baseline balance minus current balance.
- **Usage method:** RunPod's displayed usage or billing for this Pod, where the console shows it.

The balance alone does not prove experiment-specific consumption: credits, adjustments or other account activity would distort it. Where both figures exist, reconcile them and use the higher. No other resource may run on the account during the experiment.

## 7. Step 3: billable resources and deployment

1. **Rate check.** In the console, the L40S must be at most $1.09/hour. If no L40S is available, the A40 must be at most $0.59/hour. If neither is available within its cap, do not deploy; return to the owner.
2. **Billable-resource table.** Fill in one row per resource the console shows as billable. Every rate is normalised to dollars per hour. Rates with different billing periods are never added directly.

   | Resource | Published rate and period | Source | Quantity | Conversion | Billing-period assumption | Hourly rate |
   |---|---|---|---|---|---|---|
   | GPU compute | $ ___ /hour | Console at deployment | 1 | Published hourly rate; the higher of this and the cap is used | None | $ ___ |
   | Container disk | $0.10/GB/month | RunPod pricing page | 80 GB | 0.10 × 80 ÷ 672 | 672-hour month (28 days), errs high | $0.011905 |
   | (any other) | | | | | | |

   Conversions: per second × 3,600; per day ÷ 24; per month ÷ 672; per GB per month × GB ÷ 672. A one-off charge is added in full at the start. A resource whose billing period cannot be established cannot be normalised: do not start the watchdog; return to the owner.
3. Enter every extra resource in `resources.tsv` in the bundle (period, quantity, conversion and hourly rate). The watchdog recomputes each hourly figure and refuses a mismatch.
4. **Deploy:** RunPod Secure Cloud, on-demand, the approved GPU, 80 GB container disk, **no volume disk and no network volume**.
5. Record the Pod start time. Start the local timer:
   ```
   node studio/tools/ap84b3/stop-timer.mjs --start <Pod start time, ISO 8601>
   ```

**Evidence:** rate screenshot; the completed table; Pod start time; confirmation that no volume or network storage exists.

## 8. Step 4: watchdog live test and start

Do this **before any download**.

1. Resolve U1 and U2: establish how a stop command run on the Pod authenticates, and how the Pod identifier is obtained. Record both. If the only mechanism is an account-level API key on the Pod, **stop and return to the owner**.
2. Write a small stop command for the Pod that takes the Pod identifier as its only argument. It must contain no credential.
3. **Live test.** Start the watchdog with a one-minute limit and confirm in the console that the Pod stops. This costs a few cents and counts toward the ceiling and the runtime.
4. Start the Pod again if needed, then start the watchdog for the real run, using the settings in `watchdog.env` plus the operator settings:
   ```
   nohup setsid ./watchdog.sh run > /dev/null 2>&1 &
   ./watchdog.sh status
   ```
5. Confirm `status` shows `mode=production`, the hourly total from the table in §7, and a fresh heartbeat.

The watchdog's consumption figure is an **estimate**: elapsed time × (GPU + container disk + every listed resource), plus one-off charges. It is not a provider billing measurement.

**Evidence:** how the stop command authenticates; the live-test result; the watchdog `status` output.

## 9. Step 5: SSH transfer procedure

1. Create a dedicated key pair for this run. Keep the private key **outside the repository**. Never commit it.
2. Add the public key to the account for this run only.
3. Read the Pod's SSH host key fingerprint through the RunPod web terminal. Pin it in a dedicated known-hosts file and connect with strict host key checking.
4. **Pull only:** the local machine fetches from the Pod. The Pod holds no credential for the local machine. Agent forwarding stays off.
5. Upload master v3 over the same channel. Check its SHA-256 on the Pod against the lock.
6. If file copy over SSH is not available (U3), **stop and return to the owner**.
7. After the run, remove the public key from the account and delete the private key.

**Evidence:** host key fingerprint; master v3 hash on the Pod.

## 10. Step 6: setup and workflows

1. `./pod-setup.sh check`, then `software`, then `models`. Each stops on any mismatch. `models` verifies every file against the approved hashes.
2. If the pinned ComfyUI and IP-Adapter node will not run together (U4), **stop and return to the owner**. Do not change a pin or substitute an implementation.
3. Load the built-in "Qwen Image Edit 2511" template. Apply only the approved differences: the pinned model files, the approved prompt and a single-space negative prompt, the candidate's seed, 40 steps, CFG 4.0, euler / simple, **no LoRA node**, and an explicit empty-latent node at 1024×1536 connected to the sampler.
4. Build the SDXL + IP-Adapter Plus workflow to the approved settings.
5. Export each workflow in API format. Copy the exports to the local machine and check them:
   ```
   node studio/tools/ap84b3/check-workflow.mjs --workflow Q --candidate A --file <export.json>
   ```
6. Record each export's SHA-256 and the reported shift value in the run sheet **before any candidate is generated**. No workflow change after this point.

**Evidence:** `pod-setup.sh` output; both workflow hashes; the shift value; installed software versions.

## 11. Step 7: generation and copying

Before each generation or retry, run `./watchdog.sh gate`. If the gate is closed, do not start.

1. **Smoke run:** at most one per workflow, 512×768, 8 steps, a seed not used by any candidate. It is saved and hashed, labelled `smoke`, and is never a candidate.
2. Generate A, then B, then C. One generation each. No retries for quality.
3. A retry is allowed only for a technical failure, with identical settings, and is recorded.
4. **After each output, before the next generation:**
   ```
   AP84B3_OUTBOX=/workspace/outbox/A ./collect-outputs.sh add <output file> candidate-a-raw.png
   ```
   Pull the outbox into a local staging folder over SSH, then verify:
   ```
   node studio/tools/ap84b3/verify-transfer.mjs --run <run folder> --candidate A --staging <staging folder>
   ```

**Output-retention rule.** An output is safely retained only when it has been transferred to local storage and its checksum verified there. An output still on the Pod, or part-way through transfer, when the Pod stops is lost. A lost output is recorded as `lost` in the run sheet and is not regenerated without fresh owner approval. The limits take priority over completing a transfer.

**Evidence:** every output's SHA-256 on the Pod and locally; each `transfers/<candidate>.verified.json`.

## 12. Console checkpoints (every 30 minutes)

At each checkpoint the local timer alerts. Record, with a timestamp:

| Figure | Value |
|---|---|
| Balance method (baseline − current balance) | $ ___ |
| Usage method (console usage for this Pod) | $ ___ |
| Watchdog estimate (`./watchdog.sh status`) | $ ___ |

**Stop the Pod now if:**
- neither the balance method nor the usage method can be read;
- the two methods differ by more than $0.25;
- either method exceeds the watchdog estimate by more than $0.25;
- either method has reached $4.75;
- the balance shows any change the experiment does not explain;
- any charge appears that is not in the table in §7.

## 13. Manual stop (independent of the Pod)

The manual stop works if the watchdog never started, crashed or could not authenticate.

1. Open the RunPod web console in the browser.
2. Press **Stop** on the Pod, then **Terminate**.
3. Confirm no Pod, volume disk or network volume remains.
4. Record the time and the final balance.

Use it at 2 h 55 min if the Pod is still running, at any stop condition in §12, if the watchdog raises an `ALARM`, or whenever in doubt. With one $10 deposit and auto-pay off, RunPod also terminates the Pod when the balance reaches $0.

## 14. Shutdown

1. Confirm every retained output has a verification record locally.
2. Stop, then terminate, the Pod. Confirm in the console that nothing remains.
3. Record the Pod end time, the final balance and the consumption by both methods.
4. Remove the SSH public key from the account.

## 15. After the Pod (local, $0)

1. Cut out each retained raw output, full canvas:
   ```
   node studio/tools/ap84b3/cutout.cjs --in <raw.png> --out <run folder>/cutouts/candidate-a-cutout.png --meta <file.json>
   ```
   Raw and cut-out stay separate, each with its own hash. Report the cut-out's thresholds; do not change them.
2. Complete the run sheet: Pod times and rate, software commits, workflow hashes, and for each candidate its status (`retained`, `lost` or `not-generated`) and file hashes.
3. Start the studio with the import adapter and the run folder:
   ```
   STUDIO_GEN_ADAPTER=import STUDIO_GEN_IMPORT_DIR=<absolute run folder> node studio/server.mjs
   ```
4. Create **one job per candidate**, each with the reference pack, described as `AP-84B3 candidate A` (then B, then C). Each gets its own validation report.
5. Build the comparison sheet (master v3, approved pose 02, A, B, C):
   ```
   node studio/tools/ap84b3/compare-sheet.mjs --out <sheet.png> --item "Master v3=<path>" --item "Pose 02 v1=<path>" --item "A=<path>" ...
   ```
6. Owner review of each candidate, with a note. Approval creates a registry proposal only. Promotion and "make current" keep their own gates.

## 16. Evidence checklist

- [ ] Lock hash, computed two ways, equal to the hash in the D1-7 approval
- [ ] Auto-pay disabled (screenshot)
- [ ] Balance before and after the $10 deposit (screenshots), difference $10.00
- [ ] No pre-existing Pod, volume or network storage
- [ ] Rate at deployment within the cap (screenshot)
- [ ] Completed billable-resource table
- [ ] Stop-command authentication and Pod identifier source (U1, U2)
- [ ] Watchdog live test result
- [ ] Watchdog `status` in production mode
- [ ] SSH host key fingerprint
- [ ] Master v3 hash on the Pod
- [ ] `pod-setup.sh` verification output; installed versions
- [ ] Both workflow export hashes and the shift value, recorded before any candidate
- [ ] Each output's hash on the Pod and locally; each verification record
- [ ] Checkpoint records every 30 minutes
- [ ] Pod start and end times; final balance; consumption by both methods
- [ ] Console confirmation that nothing remains
- [ ] Run sheet, including any output recorded as lost
