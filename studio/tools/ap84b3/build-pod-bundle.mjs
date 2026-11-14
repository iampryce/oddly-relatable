#!/usr/bin/env node
// AP-84B3 Pod bundle builder (D1-6, item I4).
//
// Generates everything the Pod needs from the owner-approved experiment lock, so that no hash, URL, commit or
// limit is typed by hand:
//   ap84b3-experiment.json   a copy of the lock            LOCK_SHA256          its canonical SHA-256
//   downloads.tsv            url <TAB> destination <TAB> sha256, one line per model file
//   MODELS.SHA256SUMS        "sha256  destination" for `sha256sum --check`
//   software.tsv             name <TAB> repository <TAB> commit <TAB> destination
//   watchdog.env             the approved limits as watchdog settings (rate cap per GPU, disk, thresholds)
//   resources.tsv            other billable resources, normalised to hourly rates (none by default)
//   pod-setup.sh, watchdog.sh, collect-outputs.sh   copies of the reviewed scripts
//   BUNDLE.SHA256SUMS        checksums of every file above
// The bundle contains no credential and no environment.lock: pod-setup.sh refuses to run until the separately
// approved PyTorch and base-image proposal adds one.
//
//   node studio/tools/ap84b3/build-pod-bundle.mjs --out <directory outside the repository>
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {loadLock, modelDownloadUrl, normaliseHourly, microToUsd, sha256Buffer, isInside, REPO_ROOT, LOCK_FILE, RESOURCES_HEADER} from '../../lib/experiment-spec.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SCRIPTS = ['pod-setup.sh', 'watchdog.sh', 'collect-outputs.sh'];

// extraResources: [{name, rate, period, quantity}] — each is normalised to an hourly rate with its conversion
// and billing-period assumption written out. Rates with different billing periods are never added directly.
export function bundleFiles({lock, lockSha256, lockText, extraResources = []}) {
  const L = lock.limits, files = {};
  files['ap84b3-experiment.json'] = lockText;
  files['LOCK_SHA256'] = lockSha256 + '\n';
  files['downloads.tsv'] = '# url\tdestination\tsha256\n' + lock.models.map(m => `${modelDownloadUrl(m)}\t${m.saveAs}\t${m.sha256}`).join('\n') + '\n';
  files['MODELS.SHA256SUMS'] = lock.models.map(m => `${m.sha256}  ${m.saveAs}`).join('\n') + '\n';
  files['software.tsv'] = '# name\trepository\tcommit\tdestination\n'
    + `comfyui\t${lock.software.comfyui.repo}\t${lock.software.comfyui.commit}\t.\n`
    + `ipadapter-plus\t${lock.software.ipadapterPlus.repo}\t${lock.software.ipadapterPlus.commit}\t${lock.software.ipadapterPlus.saveAs}\n`;
  const M = L.milestoneSeconds;
  files['watchdog.env'] = [
    '# AP-84B3 watchdog settings generated from the approved experiment lock. Not a secret; contains no credential.',
    '# Set by the operator at deployment (not generated): WD_STATE_DIR, WD_POD_START_EPOCH, WD_POD_ID, WD_STOP_CMD,',
    '# WD_GPU_RATE_USD_PER_HOUR (the rate shown in the console) and WD_GPU_RATE_CAP_USD_PER_HOUR (the cap for the GPU deployed).',
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

// Write the bundle into a new, empty directory outside the repository. Requires an owner-approved lock.
export function buildBundle({outDir, lockFile = LOCK_FILE, decisionsFile, extraResources = []}) {
  const {lock, sha256} = loadLock({lockFile, ...(decisionsFile ? {decisionsFile} : {})});          // refuses an unapproved lock
  const out = path.resolve(outDir);
  if (isInside(path.dirname(out), REPO_ROOT) || isInside(out, REPO_ROOT)) throw new Error('the bundle must be written outside the repository');
  if (fs.existsSync(out) && fs.readdirSync(out).length) throw new Error('the bundle directory must be new or empty');
  const lockText = fs.readFileSync(lockFile, 'utf8').replace(/\r\n/g, '\n');
  const files = bundleFiles({lock, lockSha256: sha256, lockText, extraResources});
  fs.mkdirSync(out, {recursive: true});
  for (const [name, text] of Object.entries(files)) fs.writeFileSync(path.join(out, name), text, {flag: 'wx', mode: name.endsWith('.sh') ? 0o755 : 0o644});
  return {outDir: out, lockSha256: sha256, files: Object.keys(files).sort()};
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const i = process.argv.indexOf('--out');
    if (i < 0 || !process.argv[i + 1]) throw new Error('usage: build-pod-bundle.mjs --out <directory outside the repository>');
    console.log(JSON.stringify(buildBundle({outDir: process.argv[i + 1]}), null, 1));
  } catch (e) { console.error(`build-pod-bundle: ${e.message}`); process.exit(1); }
}
