# AP-84B3 runbook: three-candidate experiment

**Status (2026-11-14): NOT AUTHORISED TO EXECUTE.**
- Execution is owner decision **D1-7**, which has not been given. No account, funding, Pod, download or image generation is authorised.
- Two approval lines must be in `DECISIONS.md` before any tool will run, each written only on the owner's confirmation:
  1. `AP-84B3-LOCK-APPROVED-SHA256=<hash>` for the experiment lock `studio/config/ap84b3-experiment.json`.
  2. `AP-84B3-ENVIRONMENT-APPROVED-SHA256=<hash>` for the environment lock `studio/config/ap84b3-environment.json` (owner decision A5: Option A, two tiers).
- Every D1-7 approval must name the approved lock hash.
- Run the local preflight at any time; it only reads:
  ```
  node studio/tools/ap84b3/preflight.mjs [--run <run folder>]
  ```

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
- **The limits are cumulative across the whole experiment** (owner decision A2). The $5.00 ceiling, the 3 hours and the single $10 deposit cover every Pod session, including a failed one. A failed session does not reset them. No additional deposit or funding is authorised. See §17.
- **How the cumulative limits are enforced.** A local session ledger (`ledger.json` in the run folder, each record chained to the one before) records the deposit and every session. Each session is prepared from the ledger, which gives it only what remains, and the bundle carries that allowance in a sealed `session.env`. The watchdog on the Pod reads it, refuses to start without it, and stops the Pod when the TOTALS reach the thresholds.
- **What this cannot do.** Consumption is entered by a person from the provider's console; no account API key is used. The tools cannot impose a hard billing cap. The provider's balance (one $10 deposit, auto-pay off), the console checkpoints (§12) and the manual stop (§13) remain the independent safeguards.

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
| U5 | PyTorch version and Pod base image | Pinned in the environment lock (A5). `pod-setup.sh environment` checks the image fingerprint, Python, PyTorch, torchvision, torchaudio, the CUDA build and the GPU before anything is installed |
| U9 | Whether RunPod deploys an image pinned by digest (`runpod/pytorch@sha256:e745…`) | Unverified. If it does not, **stop and return to the owner**; do not deploy by tag alone |
| U10 | Whether the 9.72 GB (compressed) image counts against the 80 GB container disk | Unknown. `pod-setup.sh models` checks the real free space before the first download |
| U11 | FP8 on the A40 fallback | The A40 has no FP8 hardware; ComfyUI must up-cast the weights, which is slower. Unverified; observed only if the A40 is used |
| U6 | How RunPod converts monthly prices to per-second billing | Unverified. The estimate uses a 672-hour month, which errs high |
| U7 | The exact API export of each workflow, including the Qwen shift value | Not pre-approved. Inspected, checked against the lock's constraints and frozen on the Pod (§10) |
| U8 | Whether the Qwen latent node `EmptySD3LatentImage` works with Qwen-Image-Edit-2511 | **Unverified compatibility gate.** Tested in the Qwen smoke run (§11). If it is incompatible, stop and return to the owner. No other node is substituted |

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

1. Run the preflight. Every local check must pass:
   ```
   node studio/tools/ap84b3/preflight.mjs
   ```
2. Confirm the environment lock hash the same way as the experiment lock (§4), with `loadEnvironment` in place of `loadLock`, and compare it with the `AP-84B3-ENVIRONMENT-APPROVED-SHA256=` line.
3. Build the `character-01` reference pack in the studio. Record its ID and hash.
4. Create the run folder **outside the repository**, named `r-YYYYMMDD-HHMMSS`, and start its session ledger. The ledger is started only in a new, empty folder:
   ```
   node studio/tools/ap84b3/ledger.mjs init --run <run folder> --run-id r-YYYYMMDD-HHMMSS
   ```
5. Build the padded reference for the SDXL baseline:
   ```
   node studio/tools/ap84b3/pad-reference.mjs --out <run folder>/master-v3-square.png
   ```
   It centres master v3 on a 1536×1536 canvas with RGB (203, 203, 203) borders, copies every original pixel unchanged, and fails unless the result's SHA-256 equals the one in the lock. Its output records the sharp and libvips versions. The IP-Adapter node's own "pad" mode fills with black and must not be used.
6. Start a run sheet (`run-sheet.json`, schema `ap84b3-run-sheet/1`) with the lock hash, an empty `priorSessions` list and an empty `smoke` list.

**Evidence:** preflight output; both lock hashes; reference pack ID and hash; padded reference SHA-256 and library versions; `ledger.mjs status`.

## 6. Step 2: account and funding

Each record needs a timestamp and a screenshot.

1. **Auto-pay.** Confirm in the billing page that auto-pay is **disabled**. Do not fund until this is recorded.
2. **Before funding.** Record the account balance. Confirm no Pod, volume disk, network volume or other resource exists.
3. **Deposit.** Make one $10 deposit by a regular credit or debit card. A prepaid card requires $100 per transaction and must not be used.
4. **After funding.** Record the balance. This is the **baseline**.
5. **Check.** After-funding balance minus before-funding balance must equal $10.00. If not, do not deploy; return to the owner.
6. **Record the deposit in the ledger.** It refuses anything but exactly $10.00, and refuses a second deposit:
   ```
   node studio/tools/ap84b3/ledger.mjs fund --run <run folder> --before <balance> --after <balance>
   ```

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
4. **Prepare the session and build its bundle.** Read the current balance in the console. The ledger refuses if a session is still open, a limit has been reached, the balance is higher than after the deposit, or the balance does not match the recorded consumption within $0.25. It gives the session only what remains:
   ```
   node studio/tools/ap84b3/ledger.mjs prepare --run <run folder> --balance <current balance>
   node studio/tools/ap84b3/build-pod-bundle.mjs --run <run folder> --out <new folder outside the repository>
   ```
   The bundle carries the sealed `session.env` (session number, runtime and consumption already used). Do not edit it: the watchdog checks it against `BUNDLE.SHA256SUMS`.
5. **Deploy:** RunPod Secure Cloud, on-demand, the approved GPU, 80 GB container disk, **no volume disk and no network volume**, image **`runpod/pytorch@sha256:e745934b44a4071b1d20a181cdff9e92dc4af3d304cbaafbd0d23f8dacbe5300`** (U9). Record the image reference as deployed.
   - If the session is prepared but not deployed (for example, no GPU within the cap), close it: `ledger.mjs close --run <run folder> --not-started --reason "<why>"`.
6. Record the Pod start time. Start the local timer; it reads the session from the ledger and alerts at the cumulative times:
   ```
   node studio/tools/ap84b3/stop-timer.mjs --run <run folder> --start <Pod start time, ISO 8601>
   ```

**Evidence:** rate screenshot; the completed table; Pod start time; confirmation that no volume or network storage exists.

## 8. Step 4: watchdog live test and start

Do this **before any download**.

1. Resolve U1 and U2: establish how a stop command run on the Pod authenticates, and how the Pod identifier is obtained. Record both. If the only mechanism is an account-level API key on the Pod, **stop and return to the owner**.
2. Write a small stop command for the Pod that takes the Pod identifier as its only argument. It must contain no credential.
3. **Live test.** Start the watchdog with a one-minute limit and confirm in the console that the Pod stops. This costs a few cents and counts toward the ceiling and the runtime.
4. Start the Pod again if needed, then start the watchdog for the real run, using the settings in `watchdog.env`, the operator settings and `WD_BUNDLE_DIR` (the bundle folder holding `session.env`):
   ```
   nohup setsid ./watchdog.sh run > /dev/null 2>&1 &
   ./watchdog.sh status
   ```
5. Confirm `status` shows `mode=production`, the right `session`, `prior_runtime_seconds` and `prior_consumed_micro_usd` from the ledger, the hourly total from the table in §7, and a fresh heartbeat.
   - The live test in step 3 uses runtime and money. Close it in the ledger as a session of its own and prepare a new one before the real run, so it counts toward the totals.

The watchdog's consumption figure is an **estimate**: consumption already used in earlier sessions + this session's elapsed time × (GPU + container disk + every listed resource), plus one-off charges. It is not a provider billing measurement. The watchdog will not start without the sealed session file, refuses earlier-use values from anywhere else, and refuses to start if nothing remains.

**Evidence:** how the stop command authenticates; the live-test result; the watchdog `status` output.

## 9. Step 5: SSH transfer procedure

1. Create a dedicated key pair for this run. Keep the private key **outside the repository**. Never commit it.
2. Add the public key to the account for this run only.
3. Read the Pod's SSH host key fingerprint through the RunPod web terminal. Pin it in a dedicated known-hosts file and connect with strict host key checking.
4. **Pull only:** the local machine fetches from the Pod. The Pod holds no credential for the local machine. Agent forwarding stays off.
5. Upload master v3 and the padded reference over the same channel. Check both SHA-256 values on the Pod against the lock.
6. If file copy over SSH is not available (U3), **stop and return to the owner**.
7. After the run, remove the public key from the account and delete the private key.

**Evidence:** host key fingerprint; master v3 and padded reference hashes on the Pod.

## 10. Step 6: setup and workflow freeze

1. Run the setup steps in order. Each refuses to run until the step before it has succeeded, and each stops on any mismatch. Set `AP84B3_RECORD_DIR` to a folder outside ComfyUI; the evidence records go there.
   ```
   ./pod-setup.sh check          # bundle checksums, both lock hashes, session allowance, watchdog running
   ./pod-setup.sh environment    # tier 1 before installation: image fingerprint, Python 3.12, torch 2.13.0+cu130,
                                 # torchvision 0.28.0+cu130, torchaudio 2.11.0+cu130, CUDA 13.0, GPU, FP8 type
   ./pod-setup.sh software       # ComfyUI and the IP-Adapter node at their pinned commits
   ./pod-setup.sh requirements   # requirements.txt hash, install under the PyTorch constraints, tier 1 again,
                                 # tier 2 record: package inventory and SHA-256, GPU, driver, CUDA, launch options
   ./pod-setup.sh models         # free disk space first, then every model file, each hash-checked
   ```
   If `environment` or `requirements` fails, **stop and return to the owner**: do not install anything to make it pass.
2. If the pinned ComfyUI and IP-Adapter node will not run together (U4), **stop and return to the owner**. Do not change a pin or substitute an implementation.

**Build the two workflows.** The lock holds the constraints: one entry per node, its settings, and the connections. Nothing outside them is allowed.

- **Qwen (workflow Q).** Start from the built-in "Qwen Image Edit 2511" template and make it match the lock:
  - remove the Lightning LoRA node and the switch and primitive nodes around it, so the model goes loader → shift → CFGNorm → sampler;
  - remove the input-scaling node (`FluxKontextImageScale`): master v3 goes into both text encoders unmodified, as `image1` only;
  - replace the image-derived latent (`VAEEncode`) with an `EmptySD3LatentImage` at 1024×1536, batch 1, connected directly to the sampler;
  - set the approved prompt, a single-space negative prompt, the candidate's seed, 40 steps, CFG 4.0, euler / simple, denoise 1.0;
  - leave the shift value as the template has it. It is recorded, not chosen.
- **SDXL + IP-Adapter (workflow S).** Build it from these nodes only: checkpoint loader, `IPAdapterModelLoader`, `CLIPVisionLoader`, `IPAdapterAdvanced` (weight 0.8, linear, concat, 0.0 to 1.0, V only, no negative image, no mask), two `CLIPTextEncode`, `EmptyLatentImage` 832×1248, sampler (30 steps, CFG 6.0, dpmpp_2m / karras, denoise 1.0), decode, `ImageScale` (lanczos, 1024×1536, crop disabled) and **two** save nodes: one for the raw 832×1248 image and one for the resized image. The reference is the locally padded image.

**Freeze each workflow before anything is generated.** The freeze is mandatory and fails closed. The frozen graph is always `frozen-q.json` or `frozen-s.json` in the run folder; the checker has no option to skip it or to use another file.

1. Export the workflow in API format for its first candidate: **candidate A for workflow Q, candidate C for workflow S**. Copy the export to the local machine.
2. Check it. If it passes, the checker freezes it:
   ```
   node studio/tools/ap84b3/check-workflow.mjs --run <run folder> --workflow Q --candidate A --file <export.json>
   ```
3. Read the result:

   | Result | Meaning | Action |
   |---|---|---|
   | `ok: true` with `frozenWritten` | Every constraint holds and nothing is unlisted | The graph is frozen. Record `apiSha256`, `graphSha256` and the recorded shift in the run sheet |
   | `stop: true` | The export contains a setting the constraints do not list | **Stop. Terminate the Pod. Send the report to the owner.** The operator does not decide that an unlisted setting is harmless |
   | Any `problems` | A node, setting or connection is wrong, missing or extra | Fix the workflow to match the lock and export again. If it cannot be made to match, stop and return to the owner |

4. Every later export uses the same command and is compared with the frozen graph automatically: candidate B, every smoke run, and any later export of A or C.
   ```
   node studio/tools/ap84b3/check-workflow.mjs --run <run folder> --workflow Q --candidate B --file <export.json>
   node studio/tools/ap84b3/check-workflow.mjs --run <run folder> --workflow Q --smoke --file <export.json>
   ```
   - It may differ from the frozen graph only in the seed, and for a smoke run also the latent size and the steps.
   - The shift, output slot numbers, connections, node settings and file names must be identical.
   - If the frozen graph is missing, unreadable, altered or made under a different lock, the check fails. Do not generate.
   - A smoke export never creates a frozen graph. Only candidate A (Q) and candidate C (S) can, and only once.
5. Never delete or edit a frozen graph. No workflow change after the freeze: a change needs the owner's approval.
   - The freeze is recorded in the session ledger with the frozen file's SHA-256, and the file is made read-only.
   - A deleted, replaced or altered frozen graph, or a frozen file the ledger does not know about, **stops the workflow**. It is never re-created automatically, not even by candidate A or C. Recovery is the owner-controlled procedure in §18.
   - A freeze is recorded only while a session is in progress.

**Evidence:** `pod-setup.sh` output; for each workflow the export hash, the frozen graph hash and the checker's report; the shift value; installed software versions.

## 11. Step 7: smoke runs, the latent gate, generation and copying

Before each smoke run, generation or retry, run `./watchdog.sh gate`. If the gate is closed, do not start.

**Smoke runs.** At most one per workflow: 512×768, 8 steps, seed **8403900**, otherwise identical to the frozen graph.

1. Export the smoke version of the workflow and check it with `--smoke` (§10). The workflow must already be frozen. Do not run the smoke unless the check passes.
2. Save the output as `smoke-q.png` or `smoke-s.png`. Collect it into its own outbox and verify it into its own folder:
   ```
   AP84B3_OUTBOX=/workspace/outbox/smoke ./collect-outputs.sh add <output file> smoke-q.png
   node studio/tools/ap84b3/verify-transfer.mjs --run <run folder> --candidate smoke --staging <staging folder>
   ```
3. Record it in the run sheet's `smoke` list: workflow, name, SHA-256, seed, width, height and steps.
4. A smoke image is never a candidate. The import adapter only reads candidates A, B and C, refuses any file named or hashed as a smoke image, and the run sheet is invalid if a smoke image is listed as a candidate.

**Qwen latent compatibility gate (U8).** The Qwen smoke run is the test of `EmptySD3LatentImage`.

| Outcome | Action |
|---|---|
| The run completes without error and returns a decodable 512×768 image | The gate passes. Record it. Continue |
| An error, or an output that is plainly corrupt | **Stop. Terminate the Pod. Request owner approval.** Do not substitute another latent node, and do not fall back to the template's image-derived latent |

The gate shows only that the node works technically.

**Candidates.**

1. Generate A, then B, then C. One generation each. No retries for quality.
2. A retry is allowed only for a technical failure, with identical settings, and is recorded.
3. **After each output, before the next generation:**
   ```
   AP84B3_OUTBOX=/workspace/outbox/A ./collect-outputs.sh add <output file> candidate-a-raw.png
   ```
   Pull the outbox into a local staging folder over SSH, then verify:
   ```
   node studio/tools/ap84b3/verify-transfer.mjs --run <run folder> --candidate A --staging <staging folder>
   ```
   For candidate C, collect the resized 1024×1536 image as `candidate-c-raw.png` and also the 832×1248 image as `candidate-c-raw-832.png`.

**Output-retention rule.** An output is safely retained only when it has been transferred to local storage and its checksum verified there. An output still on the Pod, or part-way through transfer, when the Pod stops is lost. A lost output is recorded as `lost` in the run sheet and is not regenerated without fresh owner approval. The limits take priority over completing a transfer.

**Evidence:** every output's SHA-256 on the Pod and locally; each `transfers/<candidate>.verified.json`; the smoke records; the latent gate result.

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
4. **Close the session in the ledger** with the higher of the two consumption figures:
   ```
   node studio/tools/ap84b3/ledger.mjs close --run <run folder> --gpu "<GPU>" --rate <$/h> --start <ISO> --end <ISO> --consumed <$> --reason "<why the session ended>"
   ```
   If it reports `overLimit`, return to the owner.
5. Remove the SSH public key from the account.

## 15. After the Pod (local, $0)

1. Cut out each retained raw output, full canvas:
   ```
   node studio/tools/ap84b3/cutout.cjs --in <raw.png> --out <run folder>/cutouts/candidate-a-cutout.png --meta <file.json>
   ```
   Raw and cut-out stay separate, each with its own hash. Report the cut-out's thresholds; do not change them.
2. Complete the run sheet: Pod times, rate and consumption (`pod.consumedUSD`, the higher of the two methods), every earlier session in `priorSessions`, software commits, for each frozen workflow its `apiSha256` and `graphSha256`, `ledgerHead` (the newest ledger entry's hash from `ledger.mjs status`), the smoke records, and for each candidate its status (`retained`, `lost` or `not-generated`) and file hashes. The sheet is invalid if total runtime or total consumption across all sessions exceeds the limits.
   - Before anything is imported, the import adapter checks that the run sheet, the ledger, the frozen graph and the lock all agree: the same sessions with the same times and consumption, the same frozen graph hash, no session still open. Any difference refuses the import.
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
- [ ] Padded reference SHA-256, equal to the lock
- [ ] For each workflow: export hash, frozen graph hash and checker report, recorded before any candidate
- [ ] The shift value, as recorded from the export
- [ ] Smoke records (seed 8403900, 512×768, 8 steps) and their verification record
- [ ] Qwen latent compatibility gate result
- [ ] Each output's hash on the Pod and locally; each verification record
- [ ] Checkpoint records every 30 minutes
- [ ] Pod start and end times; final balance; consumption by both methods
- [ ] Console confirmation that nothing remains
- [ ] Run sheet, including any output recorded as lost, every earlier session and total consumption
- [ ] Environment lock hash, equal to its approval line
- [ ] Preflight output
- [ ] `ledger.mjs status` after funding, after each prepare and after each close
- [ ] Image reference as deployed (pinned by digest)
- [ ] `environment.pre.json` and `environment.post.json` (tier 1 checks and the tier 2 record)

## 17. If a session ends early: cumulative limits

A stop at the workflow freeze (§10), the latent gate (§11) or any other stop condition ends the Pod session. The limits do not reset.

1. Terminate the Pod. Close the session in the ledger (§14, step 4) with its start and end time, GPU, rate, consumption (the higher of the balance and usage methods) and the reason. Record the same session in the run sheet's `priorSessions`.
2. Return to the owner. A further session needs the owner's decision on the reason for the stop.
3. For a further session, prepare it from the ledger (§7, step 4). The ledger:
   - refuses if the cumulative runtime has passed 2 h 20 min, or the recorded consumption has reached $4.75 or $5.00;
   - refuses if the console balance does not match the recorded consumption within $0.25, or is higher than after the deposit;
   - otherwise writes a sealed `session.env` with the runtime and consumption already used, carrying forward the higher of the ledger's figure and the balance.
4. Build a new bundle for the session. The watchdog adds the earlier use to this session's and stops at the cumulative thresholds. Its full defaults can no longer apply: it will not start without the session file, and earlier-use values cannot be given any other way.
5. The stop timer reads the session from the ledger and alerts at the cumulative times.
6. **No additional deposit.** The single $10 deposit is the only funding. The ledger refuses a second deposit.
7. **Limits of this control.** The ledger is a local file. Someone who deliberately rewrites the ledger and its head record consistently is not stopped by the chain. The balance check at each prepare, the provider's balance, the console checkpoints and the manual stop are the independent checks.

## 18. Frozen graph recovery (owner-controlled)

A frozen graph that is deleted, replaced or altered, or a frozen file without a ledger record, stops the workflow. There is no automatic recovery.

1. Stop. Do not generate. Record what happened.
2. Return to the owner with `ledger.mjs status`. Recovery is the owner's decision.
3. If the owner approves, the owner records in `DECISIONS.md`:
   ```
   AP-84B3-FREEZE-RECOVERY-APPROVED=<Q|S>:<the ledger head hash shown by status>
   ```
   The approval names the exact ledger state, so it cannot be reused later.
4. Run the recovery. It records the recovery in the ledger and keeps the old frozen file under a `revoked` name; nothing is deleted:
   ```
   node studio/tools/ap84b3/ledger.mjs recover --run <run folder> --workflow Q --reason "<what happened>"
   ```
5. The freeze must then be re-established by the workflow's first candidate (A for Q, C for S) under §10. Outputs made under the old freeze no longer match the run record and cannot be imported.
