#!/usr/bin/env node
// AP-84B3 Pod bundle builder (D1-6, item I4; environment lock A5; cumulative session allowance A2).
//
// Generates everything the Pod needs from the owner-approved experiment lock, the owner-approved environment lock
// and the session ledger, so that no hash, URL, commit, version or limit is typed by hand:
//   ap84b3-experiment.json   a copy of the lock            LOCK_SHA256          its canonical SHA-256
//   environment.lock         a copy of the environment lock ENVIRONMENT_SHA256  its canonical SHA-256
//   environment.env          the values pod-setup.sh needs from it (Python, requirements hash, free disk, launch options)
//   env-constraints.txt      exact pins that stop pip replacing PyTorch, torchvision or torchaudio
//   session.env              this session's allowance from the ledger: session number, runtime and consumption
//                            already used in earlier sessions (the watchdog refuses to start without it)
//   downloads.tsv            url <TAB> destination <TAB> sha256, one line per model file
//   MODELS.SHA256SUMS        "sha256  destination" for `sha256sum --check`
//   software.tsv             name <TAB> repository <TAB> commit <TAB> destination
//   watchdog.env             the approved limits as watchdog settings (rate cap per GPU, disk, thresholds)
//   resources.tsv            other billable resources, normalised to hourly rates (none by default)
//   pod-setup.sh, watchdog.sh, collect-outputs.sh, verify-environment.py   copies of the reviewed scripts
//   BUNDLE.SHA256SUMS        checksums of every file above
// The bundle contains no credential.
//
//   node studio/tools/ap84b3/build-pod-bundle.mjs --run <run folder> --out <directory outside the repository>
// A bundle is built for ONE prepared session: the ledger must hold a session that has been prepared and not closed.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {loadLock, loadEnvironment, modelDownloadUrl, normaliseHourly, microToUsd, sha256Buffer, isInside, REPO_ROOT, LOCK_FILE, ENVIRONMENT_FILE, RESOURCES_HEADER} from '../../lib/experiment-spec.mjs';
import {readLedger, sessionEnvText} from '../../lib/experiment-ledger.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SCRIPTS = ['pod-setup.sh', 'watchdog.sh', 'collect-outputs.sh', 'verify-environment.py'];

// extraResources: [{name, rate, period, quantity}] — each is normalised to an hourly rate with its conversion
// and billing-period assumption written out. Rates with different billing periods are never added directly.
export function bundleFiles({lock, lockSha256, lockText, environment, environmentSha256, environmentText, session, extraResources = []}) {
  const L = lock.limits, files = {};
  files['ap84b3-experiment.json'] = lockText;
  files['LOCK_SHA256'] = lockSha256 + '\n';
  files['environment.lock'] = environmentText;
  files['ENVIRONMENT_SHA256'] = environmentSha256 + '\n';
  // Free space needed before downloads: every pinned model plus the margin, in KB (sizes are decimal GB).
  const modelBytes = lock.models.reduce((n, m) => n + Math.round(Number(m.sizeGB) * 1e9), 0) + environment.disk.marginGB * 1e9;
  files['environment.env'] = [
    '# AP-84B3 environment values for pod-setup.sh, generated from the approved environment lock. Contains no credential.',
    `ENV_PYTHON=${environment.tier1.python}`,
    `ENV_COMFY_REQUIREMENTS_SHA256=${environment.tier1.comfyuiRequirementsSha256}`,
    `ENV_MIN_FREE_KB=${Math.ceil(modelBytes / 1024)}`,
    `ENV_LAUNCH_OPTIONS=${environment.tier2.launchOptions.join(' ')}`,
  ].join('\n') + '\n';
  files['env-constraints.txt'] = '# Exact pins: pip may not replace these while installing ComfyUI\'s requirements.\n' + environment.installConstraints.join('\n') + '\n';
  files['session.env'] = sessionEnvText(session.data, session.ledgerHead);
  files['downloads.tsv'] = '# url\tdestination\tsha256\n' + lock.models.map(m => `${modelDownloadUrl(m)}\t${m.saveAs}\t${m.sha256}`).join('\n') + '\n';
  files['MODELS.SHA256SUMS'] = lock.models.map(m => `${m.sha256}  ${m.saveAs}`).join('\n') + '\n';
  files['software.tsv'] = '# name\trepository\tcommit\tdestination\n'
    + `comfyui\t${lock.software.comfyui.repo}\t${lock.software.comfyui.commit}\t.\n`
    + `ipadapter-plus\t${lock.software.ipadapterPlus.repo}\t${lock.software.ipadapterPlus.commit}\t${lock.software.ipadapterPlus.saveAs}\n`;
  const M = L.milestoneSeconds;
  files['watchdog.env'] = [
    '# AP-84B3 watchdog settings generated from the approved experiment lock. Not a secret; contains no credential.',
    '# The cumulative allowance (earlier runtime and consumption) is NOT here: the watchdog reads it from session.env.',
    '# Set by the operator at deployment (not generated): WD_STATE_DIR, WD_POD_START_EPOCH, WD_POD_ID, WD_STOP_CMD,',
    '# WD_BUNDLE_DIR, WD_GPU_RATE_USD_PER_HOUR (the rate shown in the console) and WD_GPU_RATE_CAP_USD_PER_HOUR (the cap for the GPU deployed).',
    ...Object.entries(L.gpuRateCapUSDPerHour).map(([gpu, cap]) => `# approved rate cap for ${gpu}: ${cap}`),
    `WD_DISK_GB=${lock.provider.containerDiskGB}`,
    `WD_DISK_USD_PER_GB_MONTH=${L.containerDiskUSDPerGBMonth}`,
    `WD_HOURS_PER_MONTH=${L.hoursPerMonthAssumption}`,
    `WD_ESTIMATE_STOP_USD=${L.watchdogEstimateStopUSD}`,
    `WD_STOP_SECONDS=${M.watchdogStop}`,
    `WD_NO_NEW_GENERATION_SECONDS=${M.noNewGeneration}`,
    'WD_RESOURCES_FILE=resources.tsv',
  ].join('\n') + '\n';
  files['resources.tsv'] = RESOURCES_HEADER + '\n'
    + '# name\tpublished_rate_usd\tperiod\tquantity\tconversion\thourly_usd\n'
    + extraResources.map(r => {
      const n = normaliseHourly({...r, hoursPerMonth: L.hoursPerMonthAssumption});
      if (!r.name || /[\t\n]/.test(r.name)) throw new Error('resource name is required and must not contain tabs');
      return `${r.name}\t${r.rate}\t${r.period}\t${r.quantity ?? 1}\t${n.conversion}\t${microToUsd(n.hourlyMicro)}\n`;
    }).join('');
  for (const s of SCRIPTS) files[s] = fs.readFileSync(path.join(HERE, s), 'utf8');
  for (const [name, text] of Object.entries(files)) if (text.includes('\r')) throw new Error(`${name} contains carriage returns; Pod files must use LF line endings`);
  files['BUNDLE.SHA256SUMS'] = Object.keys(files).sort().map(n => `${sha256Buffer(Buffer.from(files[n], 'utf8'))}  ${n}`).join('\n') + '\n';
  return files;
}

// Write the bundle for the prepared session into a new, empty directory outside the repository.
// Requires an owner-approved experiment lock, an owner-approved environment lock and a valid ledger.
export function buildBundle({outDir, runDir, lockFile = LOCK_FILE, environmentFile = ENVIRONMENT_FILE, decisionsFile, extraResources = []}) {
  const dec = decisionsFile ? {decisionsFile} : {};
  const {lock, sha256} = loadLock({lockFile, ...dec});                                       // refuses an unapproved lock
  const env = loadEnvironment({environmentFile, lock, ...dec});                              // refuses an unapproved environment
  if (!runDir) throw new Error('the run folder (with its session ledger) is required');
  const led = readLedger(runDir, lock);                                                       // refuses a broken or missing ledger
  if (led.state.lockSha256 !== sha256) throw new Error('the ledger belongs to a different experiment lock');
  const open = led.state.sessions.find(s => s.status === 'prepared');
  if (!open) throw new Error('no prepared session in the ledger: prepare the session first (it fixes the allowance this bundle carries)');
  const out = path.resolve(outDir);
  if (isInside(path.dirname(out), REPO_ROOT) || isInside(out, REPO_ROOT)) throw new Error('the bundle must be written outside the repository');
  if (fs.existsSync(out) && fs.readdirSync(out).length) throw new Error('the bundle directory must be new or empty');
  const lockText = fs.readFileSync(lockFile, 'utf8').replace(/\r\n/g, '\n');
  const environmentText = fs.readFileSync(environmentFile, 'utf8').replace(/\r\n/g, '\n');
  const files = bundleFiles({lock, lockSha256: sha256, lockText, environment: env.env, environmentSha256: env.sha256, environmentText,
    session: {data: open.prepared, ledgerHead: open.preparedHash}, extraResources});
  fs.mkdirSync(out, {recursive: true});
  for (const [name, text] of Object.entries(files)) fs.writeFileSync(path.join(out, name), text, {flag: 'wx', mode: /\.(sh|py)$/.test(name) ? 0o755 : 0o644});
  return {outDir: out, lockSha256: sha256, environmentSha256: env.sha256, session: open.number, files: Object.keys(files).sort()};
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const arg = n => { const i = process.argv.indexOf(n); return i >= 0 ? process.argv[i + 1] : undefined; };
    if (!arg('--out') || !arg('--run')) throw new Error('usage: build-pod-bundle.mjs --run <run folder> --out <directory outside the repository>');
    console.log(JSON.stringify(buildBundle({outDir: arg('--out'), runDir: arg('--run')}), null, 1));
  } catch (e) { console.error(`build-pod-bundle: ${e.message}`); process.exit(1); }
}
