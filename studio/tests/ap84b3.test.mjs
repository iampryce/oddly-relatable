// AP-84B3 D1-6: experiment lock, import adapter, cut-out, Pod bundle, watchdog, transfers, workflow checker,
// comparison sheet and stop timer. Everything runs locally with temporary folders, synthetic fixtures and a
// stand-in stop command. No network, GPU, account or model file is used, and pod-setup.sh is never executed.
//
// These tests contain NO approved lock hash. They build a fixture decision record at run time from whatever the
// lock file currently contains, so a passing test never authorises a change to an approved value: only a hash
// recorded in DECISIONS.md after the owner's explicit review does that.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {spawn, spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createStudio} from '../lib/app.mjs';
import {ADAPTERS, adapterFor, createImportAdapter, importAdapter} from '../lib/gen-adapters.mjs';
import * as spec from '../lib/experiment-spec.mjs';
import {bundleFiles, buildBundle} from '../tools/ap84b3/build-pod-bundle.mjs';
import {verifyTransfer, checkStaging, isRetained, parseManifest, TransferRejected} from '../tools/ap84b3/verify-transfer.mjs';
import {checkWorkflow, freeze, compareToFrozen, graphHash, validateExport, checkExportInRun, frozenFileName, FREEZING_CANDIDATE} from '../tools/ap84b3/check-workflow.mjs';
import {padReference, padFromLock} from '../tools/ap84b3/pad-reference.mjs';
import {schedule, due} from '../tools/ap84b3/stop-timer.mjs';
import {buildSheet, layout} from '../tools/ap84b3/compare-sheet.mjs';
import {canvas} from '../../production/lib/runtime.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '..', '..');
const TOOLS = path.join(REPO, 'studio', 'tools', 'ap84b3');
const FIX = path.join(HERE, 'fixtures', 'ap84b3');
const {cutout} = createRequire(import.meta.url)('../tools/ap84b3/cutout.cjs');
const sha = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const shaBuf = b => crypto.createHash('sha256').update(b).digest('hex');
const tmp = (p = 'ap84b3-') => fs.mkdtempSync(path.join(os.tmpdir(), p));
const fwd = p => p.replace(/\\/g, '/');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const MASTER = path.join(REPO, 'bible/concepts/lookdev-richenv/production-candidates/corrected/candidate-04_corrected-v3.png');
const POSE02 = path.join(REPO, 'bible/concepts/lookdev-richenv/ap75-pose02-test/character-01_pose-02-worried-phone_skin-only_test.png');

// Protected files must be byte-identical before and after this whole file runs.
const PROTECTED = ['production/characters/character-01.json', 'production/environments/environments.json', 'production/stories/short-001-v2.story.json',
  'bible/concepts/lookdev-richenv/lookdev-scene-01.png', 'bible/concepts/lookdev-richenv/production-candidates/corrected/candidate-04_corrected-v3.png',
  'bible/concepts/lookdev-richenv/ap75-pose02-test/character-01_pose-02-worried-phone_skin-only_test.png', 'bible/concepts/src/ap72-cutout.cjs',
  'studio/config/canonical-references.json', 'studio/lib/generation.mjs', 'studio/lib/quarantine.mjs', 'studio/lib/asset-intel.mjs', 'studio/lib/promotion.mjs'];
const protectedBefore = PROTECTED.map(f => [f, sha(path.join(REPO, f))]);

// ---------------------------------------------------------------------------------------------------
// Fixtures
const REAL = spec.loadLock({requireApproved: false});
// A fixture "approved" lock: a copy of the current lock plus a temporary decision record naming its hash.
function fixture({approve = true, mutate = null} = {}) {
  const dir = tmp('ap84b3-fx-');
  let text = fs.readFileSync(spec.LOCK_FILE, 'utf8');
  if (mutate) { const o = JSON.parse(text); mutate(o); text = JSON.stringify(o, null, 2); }
  const lockFile = path.join(dir, 'lock.json'), decisionsFile = path.join(dir, 'DECISIONS.md');
  fs.writeFileSync(lockFile, text);
  const sha256 = spec.canonicalHash(text);
  fs.writeFileSync(decisionsFile, approve ? `fixture record\nAP-84B3-LOCK-APPROVED-SHA256=${sha256}\n` : 'fixture record with no approval\n');
  return {dir, lockFile, decisionsFile, sha256, lock: spec.parseStrictJson(text)};
}
// A small, distinct PNG (synthetic test image, not artwork).
function png(label, w = 96, h = 144, alpha = false) {
  const c = canvas.createCanvas(w, h), ctx = c.getContext('2d');
  if (!alpha) { ctx.fillStyle = '#cbcbcb'; ctx.fillRect(0, 0, w, h); }
  ctx.fillStyle = '#d2601a'; ctx.fillRect(w / 4, h / 4, w / 2, h / 2);
  ctx.fillStyle = '#000000'; ctx.font = '12px sans-serif'; ctx.fillText(label, 4, 14);
  return c.toBuffer('image/png');
}
function writeManifest(dir, files) {
  fs.writeFileSync(path.join(dir, 'MANIFEST'), spec.MANIFEST_HEADER + '\n' + files.map(n => { const b = fs.readFileSync(path.join(dir, n)); return `${shaBuf(b)}  ${b.length}  ${n}`; }).join('\n') + '\n');
}
function stage(run, id, files) {
  const dir = path.join(run, `staging-${id}-${crypto.randomBytes(3).toString('hex')}`);
  fs.mkdirSync(dir, {recursive: true});
  for (const [n, b] of Object.entries(files)) fs.writeFileSync(path.join(dir, n), b);
  writeManifest(dir, Object.keys(files));
  return dir;
}
const entry = (name, buf) => ({name, sha256: shaBuf(buf), bytes: buf.length});
const smokeEntry = (fx, workflow, sha256) => ({workflow, name: `smoke-${workflow.toLowerCase()}.png`, sha256, seed: fx.lock.smoke.seed, width: fx.lock.smoke.width, height: fx.lock.smoke.height, steps: fx.lock.smoke.steps});
function sheetFor(fx, cands, extra = {}) {
  const L = fx.lock;
  const candidates = Object.fromEntries(spec.CANDIDATE_IDS.map(id => [id, {workflow: L.candidates[id].workflow, seed: L.candidates[id].seed, status: 'not-generated', ...(cands[id] || {})}]));
  return {schema: spec.RUN_SHEET_SCHEMA, runId: 'r-20261120-140500', lockSha256: fx.sha256,
    pod: {provider: L.provider.name, cloud: L.provider.cloud, gpu: L.provider.gpuPrimary, region: 'test-region', startedAt: '2026-11-20T14:05:00Z', endedAt: '2026-11-20T15:35:00Z', gpuRateUSDPerHour: L.limits.gpuRateCapUSDPerHour[L.provider.gpuPrimary], consumedUSD: '1.66'},
    software: {comfyuiCommit: L.software.comfyui.commit, ipadapterCommit: L.software.ipadapterPlus.commit},
    workflows: {Q: {apiSha256: 'a'.repeat(64)}, S: {apiSha256: 'b'.repeat(64)}}, candidates, priorSessions: [], smoke: [], ...extra};
}
// A complete, verified run folder holding candidate A (small synthetic images unless raw/cut are given).
function buildRun(fx, {raw = png('raw A'), cut = png('cutout A', 96, 144, true), sheetExtra = {}} = {}) {
  const run = tmp('ap84b3-run-');
  const record = verifyTransfer({runDir: run, candidate: 'A', stagingDir: stage(run, 'A', {'candidate-a-raw.png': raw})});
  fs.mkdirSync(path.join(run, 'cutouts'));
  fs.writeFileSync(path.join(run, 'cutouts', 'candidate-a-cutout.png'), cut);
  const sheet = sheetFor(fx, {A: {status: 'retained', raw: entry('candidate-a-raw.png', raw), cutout: entry('candidate-a-cutout.png', cut)}}, sheetExtra);
  const writeSheet = s => fs.writeFileSync(path.join(run, 'run-sheet.json'), JSON.stringify(s, null, 1));
  writeSheet(sheet);
  return {run, sheet, record, writeSheet, adapter: createImportAdapter({dir: run, lockFile: fx.lockFile, decisionsFile: fx.decisionsFile})};
}
const REQ = {assetType: 'character-pose', assetKey: 'character-01/02', description: 'AP-84B3 candidate A: import for owner review'};

// Bash is required for the shell-script tests. They fail loudly if it is missing; they are never skipped.
const BASH = (() => {
  for (const b of [process.env.AP84B3_BASH, 'C:/Program Files/Git/bin/bash.exe', 'C:/Program Files/Git/usr/bin/bash.exe', 'bash'].filter(Boolean)) {
    try { const r = spawnSync(b, ['-c', 'echo ok'], {encoding: 'utf8'}); if (r.status === 0 && r.stdout.trim() === 'ok') return b; } catch {}
  }
  return null;
})();
const needBash = () => assert.ok(BASH, 'bash is required for the AP-84B3 shell-script tests (set AP84B3_BASH to its path)');
const baseEnv = () => ({PATH: process.env.PATH, SYSTEMROOT: process.env.SYSTEMROOT || '', TEMP: process.env.TEMP || '', TMP: process.env.TMP || ''});
// A watchdog test bed: state directory, a stand-in stop command that writes a marker, an empty resources file.
function wdBed({stopBody = 'echo "stopped $1" >> "$(dirname "$0")/marker"'} = {}) {
  const dir = tmp('ap84b3-wd-');
  fs.writeFileSync(path.join(dir, 'stop.sh'), `#!/usr/bin/env bash\n${stopBody}\n`, {mode: 0o755});
  fs.writeFileSync(path.join(dir, 'resources.tsv'), spec.RESOURCES_HEADER + '\n');
  const env = {...baseEnv(), WD_STATE_DIR: fwd(path.join(dir, 'state')), WD_POD_START_EPOCH: String(Math.floor(Date.now() / 1000)), WD_POD_ID: 'pod-fixture-1',
    WD_STOP_CMD: fwd(path.join(dir, 'stop.sh')), WD_GPU_RATE_USD_PER_HOUR: '1.09', WD_GPU_RATE_CAP_USD_PER_HOUR: '1.09', WD_DISK_GB: '80', WD_DISK_USD_PER_GB_MONTH: '0.10',
    WD_RESOURCES_FILE: fwd(path.join(dir, 'resources.tsv')), WD_TEST_MODE: '1', WD_TICK_SECONDS: '1'};
  const read = f => { try { return fs.readFileSync(path.join(dir, 'state', f), 'utf8').trim(); } catch { return null; } };
  const state = () => Object.fromEntries((read('state') || '').split(' ').filter(Boolean).map(kv => kv.split('=')));
  // A deterministic stand-in clock (test mode only): each call returns one second more than the previous call,
  // starting at the Pod start time. The tests then do not depend on how busy this machine is: a slow tick cannot
  // look like a clock jump, and the elapsed time at each tick is exact.
  fs.writeFileSync(path.join(dir, 'step-n'), '0\n');
  fs.writeFileSync(path.join(dir, 'step-clock.sh'), `#!/usr/bin/env bash\nd="$(dirname "$0")"; n="$(cat "$d/step-n")"; echo $(( n + 1 )) > "$d/step-n"; echo $(( ${env.WD_POD_START_EPOCH} + n ))\n`, {mode: 0o755});
  env.WD_NOW_CMD = fwd(path.join(dir, 'step-clock.sh'));
  return {dir, env, read, state, marker: () => { try { return fs.readFileSync(path.join(dir, 'marker'), 'utf8').trim(); } catch { return null; } }};
}
const wd = (env, cmd = 'run', timeout = 40000) => spawnSync(BASH, [fwd(path.join(TOOLS, 'watchdog.sh')), cmd], {env, encoding: 'utf8', timeout});

// ---------------------------------------------------------------------------------------------------
test('canonical hash: equivalent JSON gives the same hash; any change in content gives a different one', () => {
  const a = '{"b": [1, 2, {"y": "é", "x": null}], "a": "4.0", "c": true}';
  const h = spec.canonicalHash(a);
  assert.match(h, /^[0-9a-f]{64}$/);
  assert.equal(spec.canonicalize(spec.parseStrictJson(a)), '{"a":"4.0","b":[1,2,{"x":null,"y":"é"}],"c":true}');
  // same content: reordered keys, different indentation, CRLF line endings, byte-order mark
  assert.equal(spec.canonicalHash('{"c":true,"a":"4.0","b":[1,2,{"x":null,"y":"é"}]}'), h);
  assert.equal(spec.canonicalHash('{\n    "a": "4.0",\n    "b": [\n 1,\n 2,\n {"y": "é", "x": null}\n ],\n "c": true\n}\n'), h);
  assert.equal(spec.canonicalHash(a.replace(/, /g, ',\r\n ')), h);
  assert.equal(spec.canonicalHash('\ufeff' + a), h);
  assert.equal(spec.canonicalHash(Buffer.from('\ufeff' + a, 'utf8')), h);
  // different content: a value, the order of an array, case or spacing inside a string
  for (const changed of ['{"b":[1,2,{"y":"é","x":null}],"a":"4.1","c":true}', '{"b":[2,1,{"y":"é","x":null}],"a":"4.0","c":true}',
    '{"b":[1,2,{"y":"É","x":null}],"a":"4.0","c":true}', '{"b":[1,2,{"y":"é ","x":null}],"a":"4.0","c":true}', '{"b":[1,2,{"y":"é","x":null}],"a":"4.0","c":false}'])
    assert.notEqual(spec.canonicalHash(changed), h);
  // keys are sorted by Unicode code point, not UTF-16 code unit
  assert.equal(spec.canonicalize({'\u{1F600}': 1, '\uFFFF': 2}), '{"\uFFFF":2,"\u{1F600}":1}');
  // rejected: duplicate keys, non-integer numbers, trailing content
  assert.throws(() => spec.canonicalHash('{"a":1,"a":2}'), /duplicate key/);
  assert.throws(() => spec.canonicalHash('{"a":{"b":1,"b":1}}'), /duplicate key/);
  for (const n of ['4.0', '1e3', '0.8', '-0']) assert.throws(() => spec.canonicalHash(`{"a":${n}}`), /non-integer|out of range/);
  assert.throws(() => spec.canonicalHash('{"a":1} x'), /trailing content/);
  // the lock's own hash does not depend on its line endings or indentation
  const text = fs.readFileSync(spec.LOCK_FILE, 'utf8');
  assert.equal(spec.canonicalHash(text.replace(/\r?\n/g, '\r\n')), REAL.sha256);
  assert.equal(spec.canonicalHash(JSON.stringify(JSON.parse(text))), REAL.sha256);
});

test('lock: structurally valid and consistent with the recorded decisions; approval comes only from DECISIONS.md', () => {
  const L = REAL.lock, decisions = fs.readFileSync(spec.DECISIONS_FILE, 'utf8');
  const specDoc = fs.readFileSync(path.join(REPO, 'docs/oddly-relatable/AP-84B3-D1-EXPERIMENT-SPECIFICATION.md'), 'utf8');
  // Prompts appear verbatim in the decision record; pins, hashes, seeds and settings appear in the specification.
  for (const p of [L.workflows.Q.prompt, L.workflows.S.prompt, L.workflows.S.negativePrompt]) assert.ok(decisions.includes(p), 'prompt is recorded verbatim in DECISIONS.md');
  assert.equal(L.workflows.Q.negativePrompt, ' ');
  for (const m of L.models) for (const v of [m.sha256, m.revision, m.repo, m.file, `${m.sizeGB} GB`]) assert.ok(specDoc.includes(v), `specification contains ${v}`);
  for (const v of [L.software.comfyui.commit, L.software.comfyui.tag, L.software.ipadapterPlus.commit, L.inputs.editInput.sha256, L.inputs.control.sha256,
    ...Object.values(L.candidates).map(c => String(c.seed))]) assert.ok(specDoc.includes(v), `specification contains ${v}`);
  assert.equal(L.inputs.editInput.sha256, sha(path.join(REPO, L.inputs.editInput.file)));
  assert.equal(L.inputs.control.sha256, sha(path.join(REPO, L.inputs.control.file)));
  assert.equal(spec.sha256File(MASTER), L.inputs.editInput.sha256);
  // Decimals are strings; the limits keep their approved relationship.
  assert.deepEqual([L.limits.depositUSD, L.limits.consumptionCeilingUSD, L.limits.watchdogEstimateStopUSD], ['10.00', '5.00', '4.75']);
  assert.equal(L.limits.maxRuntimeSeconds, 3 * 3600);
  assert.deepEqual(L.limits.milestoneSeconds, {noNewGeneration: 8400, transfersComplete: 9300, timerAlert: 9900, watchdogStop: 10200, manualStop: 10500, absoluteLimit: 10800});
  // Whatever the real approval state is, the tools follow it: refused unless the hash is recorded in DECISIONS.md.
  if (spec.readApprovals(decisions).isApproved(REAL.sha256)) assert.doesNotThrow(() => spec.loadLock());
  else assert.throws(() => spec.loadLock(), e => e.code === 'LOCK_NOT_APPROVED' && /owner's explicit review/.test(e.message));
  // Fixture records: approved, not approved, revoked, and a changed value.
  const ok = fixture();
  assert.equal(spec.loadLock(ok).approved, true);
  assert.throws(() => spec.loadLock(fixture({approve: false})), e => e.code === 'LOCK_NOT_APPROVED');
  fs.appendFileSync(ok.decisionsFile, `AP-84B3-LOCK-REVOKED-SHA256=${ok.sha256}\n`);
  assert.throws(() => spec.loadLock(ok), e => e.code === 'LOCK_NOT_APPROVED');
  for (const change of [o => { o.workflows.Q.prompt += ' '; }, o => { o.models[0].sha256 = 'f'.repeat(64); }, o => { o.software.comfyui.commit = '0'.repeat(40); },
    o => { o.candidates.A.seed += 1; }, o => { o.workflows.Q.steps = 20; }, o => { o.limits.consumptionCeilingUSD = '6.00'; }]) {
    const changed = fixture({mutate: change});
    assert.notEqual(changed.sha256, REAL.sha256, 'a changed value changes the canonical hash');
    // the changed lock is refused against a record that approves only the original hash
    fs.writeFileSync(changed.decisionsFile, `AP-84B3-LOCK-APPROVED-SHA256=${REAL.sha256}\n`);
    assert.throws(() => spec.loadLock(changed), e => e.code === 'LOCK_NOT_APPROVED');
  }
  // Structural problems are rejected whatever the record says.
  assert.throws(() => spec.loadLock(fixture({mutate: o => { o.limits.milestoneSeconds.watchdogStop = 10900; }})), /milestones must be strictly increasing/);
  assert.throws(() => spec.loadLock(fixture({mutate: o => { o.limits.watchdogEstimateStopUSD = '5.00'; }})), /stop threshold < ceiling/);
  assert.throws(() => spec.loadLock(fixture({mutate: o => { delete o.candidates.C; }})), /candidates/);
});

test('consumption estimate: GPU at the higher of rate and cap, plus disk, plus every extra resource normalised to hourly', () => {
  const L = REAL.lock, gpu = L.provider.gpuPrimary;
  const est = s => spec.estimateConsumptionMicro({lock: L, gpu, recordedGpuRate: '1.09', elapsedSeconds: s});
  const disk = spec.normaliseHourly({rate: '0.10', period: 'gb-month', quantity: 80, hoursPerMonth: 672});
  assert.equal(disk.hourlyMicro, 11905);                                  // $8.00 a month / 672 h, rounded up
  assert.equal(est(3600).hourlyMicro, 1090000 + 11905);
  assert.ok(est(10800).estimateMicro > 3 * 1090000, 'never GPU compute alone');
  assert.ok(est(10800).estimateMicro < spec.usdToMicro(L.limits.watchdogEstimateStopUSD), 'three hours at the cap stays below the stop threshold');
  // a recorded rate below the cap still uses the cap; above the cap is refused
  assert.equal(spec.estimateConsumptionMicro({lock: L, gpu, recordedGpuRate: '0.90', elapsedSeconds: 3600}).hourlyMicro, 1090000 + 11905);
  assert.throws(() => spec.estimateConsumptionMicro({lock: L, gpu, recordedGpuRate: '1.10', elapsedSeconds: 1}), e => e.code === 'RATE_CAP');
  assert.equal(spec.estimateConsumptionMicro({lock: L, gpu: L.provider.gpuFallback, recordedGpuRate: '0.59', elapsedSeconds: 3600}).hourlyMicro, 590000 + 11905);
  // every period converts to an hourly figure; periods are never mixed
  assert.equal(spec.normaliseHourly({rate: '0.50', period: 'hour'}).hourlyMicro, 500000);
  assert.equal(spec.normaliseHourly({rate: '0.0001', period: 'second'}).hourlyMicro, 360000);
  assert.equal(spec.normaliseHourly({rate: '2.40', period: 'day'}).hourlyMicro, 100000);
  assert.equal(spec.normaliseHourly({rate: '7.00', period: 'month'}).hourlyMicro, Math.ceil(7000000 / 672));
  assert.equal(spec.normaliseHourly({rate: '0.07', period: 'gb-month', quantity: 100}).hourlyMicro, Math.ceil(7000000 / 672));
  assert.deepEqual([spec.normaliseHourly({rate: '0.50', period: 'one-off'}).hourlyMicro, spec.normaliseHourly({rate: '0.50', period: 'one-off'}).oneOffMicro], [0, 500000]);
  assert.throws(() => spec.normaliseHourly({rate: '1.00', period: 'week'}), /unknown billing period/);
  assert.throws(() => spec.normaliseHourly({rate: '1', period: undefined}), /unknown billing period/);
  const withExtra = spec.estimateConsumptionMicro({lock: L, gpu, recordedGpuRate: '1.09', elapsedSeconds: 3600, extraResources: [{rate: '7.00', period: 'month'}, {rate: '0.50', period: 'one-off'}]});
  assert.equal(withExtra.estimateMicro, 1090000 + 11905 + Math.ceil(7000000 / 672) + 500000);
});

test('run sheet: a complete sheet is valid; every frozen value is checked against the lock', () => {
  const fx = fixture(), raw = png('r'), cut = png('c');
  const good = () => sheetFor(fx, {A: {status: 'retained', raw: entry('candidate-a-raw.png', raw), cutout: entry('candidate-a-cutout.png', cut)}});
  assert.deepEqual(spec.validateRunSheet(good(), fx.lock, fx.sha256), []);
  // a sheet with an earlier (failed) session and both smoke runs is still valid while the cumulative totals stay inside the limits
  const multi = good(); multi.priorSessions = [{startedAt: '2026-11-19T10:00:00Z', endedAt: '2026-11-19T10:25:00Z', gpu: multi.pod.gpu, consumedUSD: '0.50', reason: 'stopped at the freeze step for owner review'}];
  multi.smoke = [smokeEntry(fx, 'Q', 'd'.repeat(64)), smokeEntry(fx, 'S', 'e'.repeat(64))];
  assert.deepEqual(spec.validateRunSheet(multi, fx.lock, fx.sha256), []);
  const cases = [
    [s => { s.lockSha256 = 'c'.repeat(64); }, /lockSha256/], [s => { s.candidates.A.seed = 1; }, /seed differs/], [s => { s.candidates.B.workflow = 'S'; }, /workflow or seed/],
    [s => { s.software.comfyuiCommit = '1'.repeat(40); }, /comfyuiCommit/], [s => { s.software.ipadapterCommit = '1'.repeat(40); }, /ipadapterCommit/],
    [s => { s.pod.gpu = 'NVIDIA RTX 4090 24 GB'; }, /approved primary or fallback/], [s => { s.pod.gpuRateUSDPerHour = '1.10'; }, /rate cap/], [s => { s.pod.cloud = 'Community Cloud'; }, /approved provider/],
    [s => { s.pod.endedAt = '2026-11-20T17:05:01Z'; }, /total Pod runtime across all sessions exceeds/], [s => { delete s.workflows.Q.apiSha256; }, /apiSha256/], [s => { delete s.candidates.C; }, /exactly A, B and C/],
    [s => { s.candidates.A.cutout.name = '../escape.png'; }, /safe \.png name/], [s => { s.candidates.A.raw.sha256 = 'xyz'; }, /sha256/], [s => { s.candidates.A.status = 'kept'; }, /status must be/],
    [s => { s.smoke = [smokeEntry(fx, 'Q', 'd'.repeat(64)), smokeEntry(fx, 'Q', 'e'.repeat(64))]; }, /more than 1 smoke run/], [s => { delete s.smoke; }, /smoke must be a list/],
    [s => { s.smoke = [{...smokeEntry(fx, 'Q', 'd'.repeat(64)), seed: s.candidates.A.seed}]; }, /seed differs from the lock's smoke seed/],
    [s => { s.smoke = [{...smokeEntry(fx, 'Q', 'd'.repeat(64)), steps: 40}]; }, /size or steps differ/], [s => { s.smoke = [{...smokeEntry(fx, 'S', 'd'.repeat(64)), width: 1024}]; }, /size or steps differ/],
    [s => { s.smoke = [{...smokeEntry(fx, 'Q', 'd'.repeat(64)), name: 'candidate-a-raw.png'}]; }, /name smoke-q\.png or smoke-s\.png/], [s => { s.smoke = [{...smokeEntry(fx, 'Q', 'd'.repeat(64)), name: 'smoke-s.png'}]; }, /name smoke-q\.png or smoke-s\.png/],
    [s => { s.smoke = [smokeEntry(fx, 'Q', s.candidates.A.raw.sha256)]; }, /candidate A: raw is a smoke image/], [s => { s.candidates.A.cutout.name = 'smoke-q.png'; }, /named as a smoke image/],
    [s => { delete s.priorSessions; }, /priorSessions must be a list/], [s => { delete s.pod.consumedUSD; }, /pod\.consumedUSD/],
    [s => { s.priorSessions = [{startedAt: '2026-11-19T10:00:00Z', endedAt: '2026-11-19T11:31:00Z', gpu: s.pod.gpu, consumedUSD: '1.70', reason: 'stopped at the freeze step'}]; }, /total Pod runtime across all sessions exceeds/],
    [s => { s.priorSessions = [{startedAt: '2026-11-19T10:00:00Z', endedAt: '2026-11-19T10:20:00Z', gpu: s.pod.gpu, consumedUSD: '3.40', reason: 'stopped at the latent gate'}]; }, /total consumption across all sessions exceeds/],
    [s => { s.priorSessions = [{startedAt: '2026-11-19T10:00:00Z', endedAt: '2026-11-19T10:20:00Z', gpu: s.pod.gpu, consumedUSD: '0.40'}]; }, /each prior session needs/],
    [s => { s.priorSessions = [{startedAt: '2026-11-19T10:00:00Z', endedAt: '2026-11-19T10:20:00Z', gpu: 'NVIDIA RTX 4090 24 GB', consumedUSD: '0.40', reason: 'x'}]; }, /prior session used a GPU that is not approved/],
  ];
  for (const [mutate, pattern] of cases) { const s = good(); mutate(s); assert.ok(spec.validateRunSheet(s, fx.lock, fx.sha256).some(p => pattern.test(p)), `caught: ${pattern}`); }
});

test('import adapter: a verified candidate is imported with full provenance; default behaviour is unchanged', async () => {
  // Defaults: the import adapter exists but nothing is configured, and the studio default stays "none".
  assert.deepEqual(Object.keys(ADAPTERS), ['none', 'fake', 'import']);
  assert.equal(importAdapter.status().available, false);
  await assert.rejects(importAdapter.generate(REQ), /no run folder is configured/);
  assert.equal(adapterFor('none').id, 'none');
  assert.throws(() => adapterFor('runpod'), /Unknown generation adapter/);
  assert.match(fs.readFileSync(path.join(REPO, 'studio/server.mjs'), 'utf8'), /process\.env\.STUDIO_GEN_ADAPTER \|\| 'none'/);

  const fx = fixture(), {run, adapter, sheet, record} = buildRun(fx);
  assert.equal(adapter.status().available, true);
  const [out] = await adapter.generate(REQ);
  assert.equal(out.name, 'ap84b3-candidate-a-cutout.png'); assert.equal(out.synthetic, false);
  assert.deepEqual([out.width, out.height], [96, 144]);
  assert.equal(shaBuf(out.buffer), sheet.candidates.A.cutout.sha256);
  const p = out.provenance, L = fx.lock;
  assert.equal(p.synthetic, false); assert.equal(p.candidate, 'A'); assert.equal(p.lockSha256, fx.sha256); assert.equal(p.runId, sheet.runId);
  assert.equal(p.seed, L.candidates.A.seed); assert.equal(p.prompt, L.workflows.Q.prompt); assert.equal(p.negativePrompt, ' ');
  assert.deepEqual(p.models.map(m => m.sha256), L.models.filter(m => m.workflow === 'Q').map(m => m.sha256));
  assert.deepEqual(p.software, {comfyui: L.software.comfyui.commit, ipadapterPlus: L.software.ipadapterPlus.commit});
  assert.equal(p.workflow.apiSha256, 'a'.repeat(64)); assert.equal(p.workflow.settings.steps, 40); assert.equal(p.workflow.settings.cfg, '4.0');
  assert.equal(p.raw.sha256, sheet.candidates.A.raw.sha256); assert.equal(p.cutout.sha256, sheet.candidates.A.cutout.sha256);
  assert.equal(p.transfer.manifestSha256, record.manifestSha256); assert.equal(p.input.sha256, L.inputs.editInput.sha256);
  assert.equal(p.pod.gpu, L.provider.gpuPrimary);
  // an import is never repeated
  assert.ok(fs.existsSync(path.join(run, 'imported', 'A.json')));
  await assert.rejects(adapter.generate(REQ), /already been imported/);
});

test('import adapter: every unsafe or unverified bundle is refused and nothing is imported', async () => {
  const fx = fixture();
  const refuse = async (pattern, prepare, request = REQ, fxUsed = fx) => {
    const r = buildRun(fxUsed);
    const a = (await prepare?.(r)) || r.adapter;
    await assert.rejects(a.generate(request), e => e.code === 'IMPORT_REFUSED' && pattern.test(e.message), `refused: ${pattern}`);
    assert.ok(!fs.existsSync(path.join(r.run, 'imported', 'A.json')), 'no import marker');
  };
  const cutFile = r => path.join(r.run, 'cutouts', 'candidate-a-cutout.png');
  const reSheet = (r, f) => { const s = structuredClone(r.sheet); f(s); r.writeSheet(s); };
  await refuse(/transfer verification record is missing/, r => { fs.rmSync(path.join(r.run, 'transfers', 'A.verified.json')); });
  await refuse(/has not been verified/, r => { fs.writeFileSync(path.join(r.run, 'transfers', 'A.verified.json'), JSON.stringify({...r.record, status: 'rejected'})); });
  await refuse(/cut-out does not match its recorded SHA-256/, r => { fs.writeFileSync(cutFile(r), png('different')); });
  await refuse(/raw output does not match its recorded SHA-256/, r => { fs.writeFileSync(path.join(r.run, 'transfers', 'A', 'candidate-a-raw.png'), png('changed raw')); });
  await refuse(/transfer manifest changed/, r => { fs.appendFileSync(path.join(r.run, 'transfers', 'A', 'MANIFEST'), '# edited\n'); });
  await refuse(/raw output is not in the verified transfer/, r => reSheet(r, s => { s.candidates.A.raw.sha256 = 'c'.repeat(64); }));
  await refuse(/does not match the approved experiment: .*lockSha256/, r => reSheet(r, s => { s.lockSha256 = 'c'.repeat(64); }));
  await refuse(/does not match the approved experiment: .*seed/, r => reSheet(r, s => { s.candidates.A.seed = 42; }));
  await refuse(/not recorded as owner-approved/, r => createImportAdapter({dir: r.run, lockFile: fx.lockFile, decisionsFile: fixture({approve: false}).decisionsFile}));
  await refuse(/not recorded as owner-approved/, r => createImportAdapter({dir: r.run, lockFile: fixture({approve: false, mutate: o => { o.candidates.A.seed = 7; }}).lockFile, decisionsFile: fx.decisionsFile}));
  await refuse(/cut-out is not a PNG/, r => { const b = Buffer.from('this is not a PNG, only text\n'); fs.writeFileSync(cutFile(r), b); reSheet(r, s => { s.candidates.A.cutout = entry('candidate-a-cutout.png', b); }); });
  await refuse(/raw output is not a PNG/, r => {
    fs.rmSync(path.join(r.run, 'transfers'), {recursive: true});
    const b = Buffer.from('raw text, not an image\n');
    const rec = verifyTransfer({runDir: r.run, candidate: 'A', stagingDir: stage(r.run, 'A', {'candidate-a-raw.json': b})});
    fs.renameSync(path.join(r.run, 'transfers', 'A', 'candidate-a-raw.json'), path.join(r.run, 'transfers', 'A', 'candidate-a-raw.png'));
    fs.writeFileSync(path.join(r.run, 'transfers', 'A.verified.json'), JSON.stringify({...rec, files: [{...rec.files[0], name: 'candidate-a-raw.png'}]}));
    reSheet(r, s => { s.candidates.A.raw = entry('candidate-a-raw.png', b); });
  });
  await refuse(/size must be 1 byte to/, r => { const b = Buffer.alloc(20 * 1024 * 1024 + 1, 1); fs.writeFileSync(cutFile(r), b); reSheet(r, s => { s.candidates.A.cutout = entry('candidate-a-cutout.png', b); }); });
  await refuse(/safe \.png name/, r => reSheet(r, s => { s.candidates.A.cutout.name = '../../escape.png'; }));
  await refuse(/symbolic links are not allowed/, r => {
    const real = path.join(r.run, 'cutouts-real'); fs.renameSync(path.join(r.run, 'cutouts'), real);
    fs.symlinkSync(real, path.join(r.run, 'cutouts'), process.platform === 'win32' ? 'junction' : 'dir');
  });
  await refuse(/smoke images are never candidates/, r => reSheet(r, s => { s.smoke = [smokeEntry(fx, 'Q', s.candidates.A.cutout.sha256)]; }));
  await refuse(/description must start with/, null, {...REQ, description: 'AP-84B3 candidate smoke'});
  await refuse(/recorded as lost/, r => reSheet(r, s => { s.candidates.A = {workflow: s.candidates.A.workflow, seed: s.candidates.A.seed, status: 'lost'}; }));
  await refuse(/run sheet is missing/, r => { fs.rmSync(path.join(r.run, 'run-sheet.json')); });
  await refuse(/run sheet is not valid/, r => { fs.writeFileSync(path.join(r.run, 'run-sheet.json'), '{"schema": "x", "schema": "y"}'); });
  await refuse(/description must start with/, null, {...REQ, description: 'Please import candidate A'});
  await refuse(/description must start with/, null, {...REQ, description: 'AP-84B3 candidate D'});
  await refuse(/the job must be for character-pose character-01\/02/, null, {...REQ, assetKey: 'character-01/05'});
  await refuse(/recorded as not-generated/, null, {...REQ, description: 'AP-84B3 candidate B'});
  // the run folder must exist and must be outside the repository
  await assert.rejects(createImportAdapter({dir: path.join(REPO, 'studio'), lockFile: fx.lockFile, decisionsFile: fx.decisionsFile}).generate(REQ), /must be outside the repository/);
  await assert.rejects(createImportAdapter({dir: path.join(os.tmpdir(), 'ap84b3-does-not-exist'), lockFile: fx.lockFile, decisionsFile: fx.decisionsFile}).generate(REQ), /run folder does not exist/);
  assert.equal(spec.isInside(os.tmpdir(), REPO), false, 'the temporary run folders are outside the Git work tree');
});

test('server configuration: the import adapter needs an absolute run folder outside the repository', () => {
  const run = (env) => spawnSync(process.execPath, ['--disable-warning=ExperimentalWarning', path.join(REPO, 'studio', 'server.mjs')], {env: {...baseEnv(), STUDIO_PORT: '4898', STUDIO_WORKSPACE: tmp('ap84b3-ws-'), ...env}, encoding: 'utf8', timeout: 20000});
  assert.match(run({STUDIO_GEN_ADAPTER: 'import'}).stderr, /STUDIO_GEN_IMPORT_DIR must be an absolute path/);
  assert.match(run({STUDIO_GEN_ADAPTER: 'import', STUDIO_GEN_IMPORT_DIR: path.join(REPO, 'studio-work')}).stderr, /must be outside the repository/);
  assert.match(run({STUDIO_GEN_ADAPTER: 'runpod'}).stderr, /must be none, fake or import/);
});

test('cut-out: reproduces the AP-72 record byte for byte; full-canvas mode keeps 1024x1536 with transparency; input unchanged', async () => {
  const before = sha(MASTER), dir = tmp('ap84b3-cut-');
  const ap72 = JSON.parse(fs.readFileSync(path.join(REPO, 'bible/concepts/lookdev-richenv/ap72-validation/character-01_master-v3_cutout_test.json'), 'utf8'));
  const crop = await cutout({input: MASTER, output: path.join(dir, 'crop.png'), mode: 'crop', metaFile: path.join(dir, 'crop.json')});
  assert.equal(crop.output_sha256, ap72.output_sha256, 'byte-identical to the AP-72 cut-out');
  assert.equal(sha(path.join(dir, 'crop.png')), ap72.output_sha256);
  assert.deepEqual(crop.crop, ap72.crop); assert.equal(crop.enclosed_pockets_removed, ap72.enclosed_pockets_removed);
  const full = await cutout({input: MASTER, output: path.join(dir, 'full.png'), mode: 'full'});
  assert.deepEqual(full.output_size, {width: 1024, height: 1536});
  assert.ok(full.figure.height >= 1000, 'figure is tall enough to avoid soft close-ups');
  const img = await canvas.loadImage(path.join(dir, 'full.png'));
  const c = canvas.createCanvas(img.width, img.height), ctx = c.getContext('2d'); ctx.drawImage(img, 0, 0);
  assert.equal(ctx.getImageData(2, 2, 1, 1).data[3], 0, 'background is transparent');
  assert.equal(ctx.getImageData(512, 700, 1, 1).data[3], 255, 'figure is opaque');
  assert.equal(sha(MASTER), before, 'the input is unchanged');
  // write-once, and never inside the repository
  await assert.rejects(cutout({input: MASTER, output: path.join(dir, 'full.png')}), /already exists/);
  await assert.rejects(cutout({input: MASTER, output: path.join(REPO, 'studio', 'x-never-written.png')}), /outside the repository/);
  assert.ok(!fs.existsSync(path.join(REPO, 'studio', 'x-never-written.png')));
  await assert.rejects(cutout({input: path.join(dir, 'missing.png'), output: path.join(dir, 'y.png')}), /input file not found/);
  // the command-line tool refuses an unapproved lock (true today; once approved it would proceed)
  if (!REAL.approved) {
    const r = spawnSync(process.execPath, [path.join(TOOLS, 'cutout.cjs'), '--in', MASTER, '--out', path.join(dir, 'cli.png')], {encoding: 'utf8'});
    assert.equal(r.status, 1); assert.match(r.stderr, /not recorded as owner-approved/); assert.ok(!fs.existsSync(path.join(dir, 'cli.png')));
  }
});

test('Pod bundle: every list is generated from the lock; no credential; no environment lock; unapproved locks refused', () => {
  const fx = fixture(), out = path.join(tmp('ap84b3-bundle-'), 'bundle'), L = fx.lock;
  const b = buildBundle({outDir: out, lockFile: fx.lockFile, decisionsFile: fx.decisionsFile, extraResources: [{name: 'example monthly add-on', rate: '7.00', period: 'month', quantity: 1}]});
  assert.equal(b.lockSha256, fx.sha256);
  const read = n => fs.readFileSync(path.join(out, n), 'utf8');
  assert.equal(read('LOCK_SHA256').trim(), fx.sha256);
  assert.equal(spec.canonicalHash(read('ap84b3-experiment.json')), fx.sha256);
  const downloads = read('downloads.tsv').trim().split('\n').filter(l => !l.startsWith('#')).map(l => l.split('\t'));
  assert.deepEqual(downloads, L.models.map(m => [`https://huggingface.co/${m.repo}/resolve/${m.revision}/${m.file}`, m.saveAs, m.sha256]));
  assert.equal(read('MODELS.SHA256SUMS'), L.models.map(m => `${m.sha256}  ${m.saveAs}\n`).join(''));
  assert.deepEqual(read('software.tsv').trim().split('\n').slice(1).map(l => l.split('\t')), [['comfyui', L.software.comfyui.repo, L.software.comfyui.commit, '.'],
    ['ipadapter-plus', L.software.ipadapterPlus.repo, L.software.ipadapterPlus.commit, L.software.ipadapterPlus.saveAs]]);
  const env = Object.fromEntries(read('watchdog.env').split('\n').filter(l => l && !l.startsWith('#')).map(l => l.split('=')));
  assert.deepEqual(env, {WD_DISK_GB: '80', WD_DISK_USD_PER_GB_MONTH: '0.10', WD_HOURS_PER_MONTH: '672', WD_ESTIMATE_STOP_USD: '4.75', WD_STOP_SECONDS: '10200', WD_NO_NEW_GENERATION_SECONDS: '8400', WD_RESOURCES_FILE: 'resources.tsv'});
  assert.match(read('resources.tsv'), /^# ap84b3-resources\/1\n/);
  assert.match(read('resources.tsv'), /example monthly add-on\t7\.00\tmonth\t1\tper-month rate × quantity ÷ 672\t0\.010417\n/);
  // checksums cover every file, and nothing has Windows line endings
  const sums = read('BUNDLE.SHA256SUMS').trim().split('\n').map(l => l.split('  '));
  assert.deepEqual(sums.map(s => s[1]).sort(), fs.readdirSync(out).filter(n => n !== 'BUNDLE.SHA256SUMS').sort());
  for (const [h, n] of sums) { assert.equal(sha(path.join(out, n)), h); assert.ok(!read(n).includes('\r'), `${n} uses LF line endings`); }
  // no environment lock and no credential in the bundle
  assert.ok(!fs.existsSync(path.join(out, 'environment.lock')), 'the environment lock is not created in D1-6');
  for (const n of fs.readdirSync(out)) assert.ok(!/api[_-]?key\s*[:=]\s*\S|RUNPOD_API_KEY|BEGIN [A-Z ]*PRIVATE KEY|password\s*[:=]/i.test(read(n)), `${n} holds no credential`);
  // refusals
  assert.throws(() => buildBundle({outDir: out, lockFile: fx.lockFile, decisionsFile: fx.decisionsFile}), /new or empty/);
  assert.throws(() => buildBundle({outDir: path.join(REPO, 'studio-work', 'bundle-never-written'), lockFile: fx.lockFile, decisionsFile: fx.decisionsFile}), /outside the repository/);
  assert.ok(!fs.existsSync(path.join(REPO, 'studio-work', 'bundle-never-written')));
  const un = fixture({approve: false});
  assert.throws(() => buildBundle({outDir: path.join(tmp(), 'b'), lockFile: un.lockFile, decisionsFile: un.decisionsFile}), e => e.code === 'LOCK_NOT_APPROVED');
  assert.throws(() => bundleFiles({lock: L, lockSha256: fx.sha256, lockText: read('ap84b3-experiment.json'), extraResources: [{name: 'weekly thing', rate: '1.00', period: 'week'}]}), /unknown billing period/);
});

test('Pod setup script (never executed here): static checks of its gates and safety', () => {
  const s = fs.readFileSync(path.join(TOOLS, 'pod-setup.sh'), 'utf8');
  assert.ok(!s.includes('\r'), 'LF line endings');
  assert.match(s, /^#!\/usr\/bin\/env bash\n/); assert.match(s, /\nset -euo pipefail\n/);
  // the environment gate comes first, before any other precondition or action
  const pre = s.slice(s.indexOf('preconditions() {'), s.indexOf('\n}\n', s.indexOf('preconditions() {')));
  assert.ok(pre.indexOf('environment.lock') > 0 && pre.indexOf('environment.lock') < pre.indexOf('BUNDLE.SHA256SUMS'), 'environment.lock is checked first');
  for (const cmd of ['check', 'software', 'models', 'verify']) assert.match(s, new RegExp(`\\n  ${cmd}\\) preconditions;`), `"${cmd}" runs the preconditions first`);
  assert.match(s, /sha256sum --check --strict --quiet BUNDLE\.SHA256SUMS/); assert.match(s, /sha256sum --check --strict --quiet "\$BUNDLE\/MODELS\.SHA256SUMS"/);
  assert.match(s, /--proto '=https' --proto-redir '=https'/); assert.match(s, /SHA-256 mismatch for/); assert.match(s, /the runtime watchdog is not running/);
  assert.match(s, /git -C "\$target" checkout --quiet --detach "\$commit"/); assert.match(s, /not the pinned commit/);
  assert.ok((s.match(/\n    gate\n/g) || []).length >= 2, 'the watchdog gate is consulted before each download and checkout');
  // it installs no Python packages, pipes nothing into a shell and holds no credential
  assert.ok(!/pip3? install|conda install|curl[^\n]*\|\s*(ba)?sh|wget[^\n]*\|\s*(ba)?sh|\beval\b/.test(s));
  assert.ok(!/api[_-]?key|token|password|RUNPOD_API_KEY|Authorization/i.test(s));
});

// ---------------------------------------------------------------------------------------------------
test('watchdog: stops at the 2 h 50 min milestone (scaled clock), even while a stand-in transfer is running', async () => {
  needBash();
  const b = wdBed();
  const transfer = spawn(BASH, ['-c', 'sleep 60'], {env: baseEnv(), stdio: 'ignore'});   // a "transfer" still in progress
  try {
    const r = wd({...b.env, WD_TIME_SCALE: '1200'});                                       // one clock step = twenty minutes
    assert.equal(r.status, 0, r.stderr);
    assert.equal(b.marker(), 'stopped pod-fixture-1', 'the stand-in stop command was called once with the Pod identifier');
    assert.equal(b.read('stop-reason'), 'runtime-limit');
    assert.match(b.read('stopped'), /^reason=runtime-limit attempts=1$/);
    const st = b.state();
    assert.equal(st.mode, 'test'); assert.equal(st.stop_seconds, '10200');
    // Ticks see 1200, 2400 ... scaled seconds. 9600 (2 h 40 min) is below the milestone; 10800 is the first tick at or after it.
    assert.equal(st.elapsed_seconds, '10800', 'fired at the first tick at or after 2 h 50 min, and not before');
    assert.equal(transfer.exitCode, null, 'the watchdog did not wait for the transfer');
  } finally { transfer.kill(); }
});

test('watchdog: the estimate is GPU + disk + listed resources, uses the cap, and stops at the estimated threshold', () => {
  needBash();
  // Recorded rate below the cap: the cap is used. Disk is included. Extra resources are normalised and added.
  const b = wdBed();
  fs.appendFileSync(path.join(b.dir, 'resources.tsv'), 'example add-on\t7.00\tmonth\t1\tper-month rate x quantity / 672\t0.010417\nsetup fee\t0.50\tone-off\t1\tone-off charge, added in full at the start\t0\n');
  let r = wd({...b.env, WD_GPU_RATE_USD_PER_HOUR: '0.90', WD_STOP_SECONDS: '3', WD_NO_NEW_GENERATION_SECONDS: '1'});
  assert.equal(r.status, 0, r.stderr);
  let st = b.state();
  assert.equal(st.gpu_hourly_micro_usd, '1090000', 'the higher of the recorded rate and the cap');
  assert.equal(st.disk_hourly_micro_usd, '11905'); assert.equal(st.extra_hourly_micro_usd, '10417'); assert.equal(st.one_off_micro_usd, '500000');
  assert.equal(st.hourly_total_micro_usd, String(1090000 + 11905 + 10417));
  const elapsed = Number(st.elapsed_seconds);
  assert.equal(Number(st.estimate_micro_usd), Math.ceil(elapsed * (1090000 + 11905 + 10417) / 3600) + 500000, 'same figure as the documented formula');
  assert.ok(Number(st.estimate_micro_usd) > Math.ceil(elapsed * 1090000 / 3600), 'never GPU compute alone');
  // The JavaScript estimate agrees with the watchdog.
  const js = spec.estimateConsumptionMicro({lock: REAL.lock, gpu: REAL.lock.provider.gpuPrimary, recordedGpuRate: '0.90', elapsedSeconds: elapsed, extraResources: [{rate: '7.00', period: 'month'}, {rate: '0.50', period: 'one-off'}]});
  assert.equal(js.estimateMicro, Number(st.estimate_micro_usd));

  // With a (deliberately huge) disk charge the $4.75 estimate is reached long before a GPU-only figure would reach it.
  const d = wdBed();
  r = wd({...d.env, WD_DISK_GB: '80000', WD_TIME_SCALE: '600'});
  assert.equal(r.status, 0, r.stderr);
  st = d.state();
  assert.equal(d.read('stop-reason'), 'estimated-consumption');
  assert.ok(Number(st.estimate_micro_usd) >= 4750000 && Number(st.elapsed_seconds) < 10200);
  assert.ok(Math.ceil(Number(st.elapsed_seconds) * 1090000 / 3600) < 4750000, 'a GPU-only calculation would not have stopped yet');
  assert.equal(st.threshold_micro_usd, '4750000');
  assert.equal(d.marker(), 'stopped pod-fixture-1');
});

test('watchdog: refuses to start without its settings, with a rate above the cap, or with loosened limits', () => {
  needBash();
  const refuse = (pattern, change) => {
    const b = wdBed(), env = {...b.env}; change(env, b);
    const r = wd(env);
    assert.equal(r.status, 2, `exit code for ${pattern}`); assert.match(r.stderr, pattern);
    assert.equal(b.marker(), null, 'the stop command was not called'); assert.equal(b.read('heartbeat'), null, 'the watchdog did not start');
  };
  refuse(/WD_STOP_CMD is required/, e => { delete e.WD_STOP_CMD; });
  refuse(/WD_STOP_CMD must be an executable file/, e => { e.WD_STOP_CMD += '-missing'; });
  refuse(/WD_POD_ID is required/, e => { delete e.WD_POD_ID; });
  refuse(/WD_POD_ID has an unexpected format/, e => { e.WD_POD_ID = 'pod; rm -rf x'; });
  refuse(/WD_POD_START_EPOCH is missing or invalid/, e => { delete e.WD_POD_START_EPOCH; });
  refuse(/WD_POD_START_EPOCH is missing or invalid/, e => { e.WD_POD_START_EPOCH = 'yesterday'; });
  refuse(/WD_POD_START_EPOCH is in the future/, e => { delete e.WD_NOW_CMD; e.WD_POD_START_EPOCH = String(Math.floor(Date.now() / 1000) + 5000); });
  refuse(/WD_GPU_RATE_USD_PER_HOUR is missing or not a number/, e => { delete e.WD_GPU_RATE_USD_PER_HOUR; });
  refuse(/WD_GPU_RATE_USD_PER_HOUR is missing or not a number/, e => { e.WD_GPU_RATE_USD_PER_HOUR = '$1.09'; });
  refuse(/recorded GPU rate is above the approved cap/, e => { e.WD_GPU_RATE_USD_PER_HOUR = '1.10'; });
  refuse(/WD_GPU_RATE_CAP_USD_PER_HOUR is missing/, e => { delete e.WD_GPU_RATE_CAP_USD_PER_HOUR; });
  refuse(/WD_DISK_GB is missing or invalid/, e => { delete e.WD_DISK_GB; });
  refuse(/WD_DISK_USD_PER_GB_MONTH is missing/, e => { delete e.WD_DISK_USD_PER_GB_MONTH; });
  refuse(/WD_RESOURCES_FILE is required/, e => { delete e.WD_RESOURCES_FILE; });
  refuse(/WD_RESOURCES_FILE is required/, e => { e.WD_RESOURCES_FILE += '-missing'; });
  refuse(/must start with '# ap84b3-resources\/1'/, (e, b) => { fs.writeFileSync(path.join(b.dir, 'resources.tsv'), 'gpu\t1.09\thour\t1\tx\t1.09\n'); });
  // limits may only be tightened
  refuse(/WD_STOP_SECONDS must be 1 to 10200/, e => { e.WD_STOP_SECONDS = '10800'; });
  refuse(/WD_ESTIMATE_STOP_USD must not exceed 4\.75/, e => { e.WD_ESTIMATE_STOP_USD = '5.00'; });
  refuse(/WD_NO_NEW_GENERATION_SECONDS must be/, e => { e.WD_NO_NEW_GENERATION_SECONDS = '9000'; });
  refuse(/WD_HOURS_PER_MONTH must be 1 to 672/, e => { e.WD_HOURS_PER_MONTH = '744'; });
  // test-only settings are refused outside test mode
  refuse(/test-only settings/, e => { delete e.WD_TEST_MODE; delete e.WD_NOW_CMD; e.WD_TIME_SCALE = '10'; });
  refuse(/test-only settings/, e => { delete e.WD_TEST_MODE; });                                    // the stand-in clock alone is refused in production mode
  refuse(/test-only settings/, e => { delete e.WD_TEST_MODE; delete e.WD_NOW_CMD; e.WD_RETRY_SECONDS = '1'; });
  refuse(/WD_TIME_SCALE must be an integer of at least 1/, e => { e.WD_TIME_SCALE = '0'; });
});

test('watchdog: extra resources must be normalised to hourly rates with their period and conversion stated', () => {
  needBash();
  const refuse = (pattern, line) => {
    const b = wdBed(); fs.appendFileSync(path.join(b.dir, 'resources.tsv'), line + '\n');
    const r = wd(b.env);
    assert.equal(r.status, 2); assert.match(r.stderr, pattern); assert.equal(b.marker(), null); assert.equal(b.read('heartbeat'), null);
  };
  refuse(/hourly rate does not match its published rate and billing period/, 'storage\t7.00\tmonth\t1\tper-month rate x quantity / 672\t7.00');         // a monthly price entered as if hourly
  refuse(/hourly rate does not match/, 'storage\t0.07\tgb-month\t100\tper-GB-month rate x GB / 672\t0.07');
  refuse(/hourly rate does not match/, 'per-second thing\t0.0001\tsecond\t1\tx 3600\t0.0001');
  refuse(/billing period 'week' is not recognised/, 'weekly thing\t1.00\tweek\t1\tper-week / 168\t0.005953');
  refuse(/needs name, rate, period, quantity, conversion and hourly rate/, 'storage\t7.00\tmonth\t1\t0.010417');                                      // conversion missing
  refuse(/published rate is not a number/, 'storage\tseven\tmonth\t1\tper-month / 672\t0.010417');
  refuse(/quantity must be a positive integer/, 'storage\t7.00\tmonth\t0\tper-month / 672\t0.010417');
  refuse(/hourly rate does not match/, 'setup fee\t0.50\tone-off\t1\tone-off charge\t0.50');                                                          // a one-off has no hourly rate
  // each valid period is accepted and matches the JavaScript conversion
  const b = wdBed();
  const rows = [['hourly add-on', '0.05', 'hour', 1], ['per-second add-on', '0.0001', 'second', 1], ['daily add-on', '2.40', 'day', 1], ['monthly add-on', '7.00', 'month', 1], ['storage', '0.07', 'gb-month', 100]];
  let total = 0;
  for (const [name, rate, period, quantity] of rows) {
    const n = spec.normaliseHourly({rate, period, quantity, hoursPerMonth: 672}); total += n.hourlyMicro;
    fs.appendFileSync(path.join(b.dir, 'resources.tsv'), `${name}\t${rate}\t${period}\t${quantity}\t${n.conversion}\t${spec.microToUsd(n.hourlyMicro)}\n`);
  }
  const r = wd({...b.env, WD_STOP_SECONDS: '2', WD_NO_NEW_GENERATION_SECONDS: '1'});
  assert.equal(r.status, 0, r.stderr);
  assert.equal(b.state().extra_hourly_micro_usd, String(total));
});

test('watchdog: stops early when the clock is unreliable; retries a failed stop, raises the alarm and ends the work process', async () => {
  needBash();
  // A stand-in clock that replays a list of offsets from the Pod start time.
  const clock = (b, offsets) => {
    fs.writeFileSync(path.join(b.dir, 'offsets'), offsets.join('\n') + '\n'); fs.writeFileSync(path.join(b.dir, 'n'), '0\n');
    fs.writeFileSync(path.join(b.dir, 'now.sh'), `#!/usr/bin/env bash\nd="$(dirname "$0")"; n="$(cat "$d/n")"; n=$((n + 1)); echo "$n" > "$d/n"\nline="$(sed -n "\${n}p" "$d/offsets")"; [ -n "$line" ] || line="$(tail -n 1 "$d/offsets")"\necho $(( ${b.env.WD_POD_START_EPOCH} + line ))\n`, {mode: 0o755});
    return {...b.env, WD_NOW_CMD: fwd(path.join(b.dir, 'now.sh'))};
  };
  let b = wdBed(), r = wd(clock(b, [0, 0, 1, 2, 600]));                    // first value: the start-up check
  assert.equal(r.status, 0, r.stderr); assert.equal(b.read('stop-reason'), 'clock-jump-or-heartbeat-gap'); assert.equal(b.marker(), 'stopped pod-fixture-1');
  b = wdBed(); r = wd(clock(b, [0, 0, 5, 3]));
  assert.equal(r.status, 0, r.stderr); assert.equal(b.read('stop-reason'), 'clock-went-backwards'); assert.equal(b.marker(), 'stopped pod-fixture-1');

  // The stop command fails four times, then works. After three failures the alarm is raised and the work process ended.
  b = wdBed({stopBody: 'd="$(dirname "$0")"; n="$(cat "$d/tries" 2>/dev/null || echo 0)"; n=$((n + 1)); echo "$n" > "$d/tries"; [ "$n" -ge 5 ] || exit 1; echo "stopped $1" >> "$d/marker"'});
  const work = spawn(BASH, ['-c', `sleep 60 & echo $! > "${fwd(path.join(b.dir, 'work.pid'))}"; wait`], {env: baseEnv(), stdio: 'ignore'});
  const workExited = new Promise(res => work.on('exit', res));
  for (let i = 0; i < 50 && !fs.existsSync(path.join(b.dir, 'work.pid')); i++) await sleep(100);
  r = wd({...b.env, WD_STOP_SECONDS: '2', WD_NO_NEW_GENERATION_SECONDS: '1', WD_RETRY_SECONDS: '1', WD_WORK_PID_FILE: fwd(path.join(b.dir, 'work.pid'))});
  assert.equal(r.status, 0, r.stderr);
  assert.match(b.read('stopped'), /attempts=5$/); assert.equal(b.marker(), 'stopped pod-fixture-1');
  assert.match(b.read('ALARM'), /STOP THE POD IN THE WEB CONSOLE NOW/);
  await Promise.race([workExited, sleep(8000).then(() => { work.kill(); throw new Error('the work process was not ended'); })]);
  assert.match(b.read('watchdog.log'), /stop command FAILED attempt=3/);
});

test('watchdog: the gate refuses a generation or retry after the cut-off, during a stop, or with no live watchdog; nothing from the environment is logged', async () => {
  needBash();
  const b = wdBed();
  const canary = ['canary', 'secret', 'value', '7731'].join('-'), fakeKey = ['rp', 'a_', 'FAKE', 'KEY', '000111222'].join('');
  const env = {...b.env, WD_STOP_SECONDS: '18', WD_NO_NEW_GENERATION_SECONDS: '9', AP84B3_CANARY: canary, RUNPOD_API_KEY: fakeKey};
  assert.match(wd(env, 'gate').stdout, /closed \(the watchdog is not running\)/);
  // started the way the runbook starts it: detached, so it survives the shell that launched it
  const launch = spawnSync(BASH, ['-c', `nohup "${fwd(path.join(TOOLS, 'watchdog.sh'))}" run > /dev/null 2>&1 & disown; exit 0`], {env, encoding: 'utf8', timeout: 15000});
  assert.equal(launch.status, 0, launch.stderr);
  for (let i = 0; i < 40 && b.read('heartbeat') === null; i++) await sleep(100);
  const early = wd(env, 'gate');
  assert.equal(early.status, 0, early.stdout + early.stderr); assert.match(early.stdout, /gate: open/);
  for (let i = 0; i < 400 && !(Number(b.state().elapsed_seconds) >= 9); i++) await sleep(100);
  const late = wd(env, 'gate');
  assert.equal(late.status, 1); assert.match(late.stdout, /past the no-new-generation cut-off/);
  for (let i = 0; i < 600 && b.marker() === null; i++) await sleep(100);
  assert.equal(b.marker(), 'stopped pod-fixture-1', 'the watchdog kept running after its launching shell exited, and stopped the Pod');
  const after = wd(env, 'gate');
  assert.equal(after.status, 1); assert.match(after.stdout, /the watchdog is stopping the Pod/);
  assert.match(wd(env, 'status').stdout, /stop-reason: runtime-limit/);
  // nothing from the environment reaches the log or the state files, and the scripts assume no injected credential
  for (const f of fs.readdirSync(path.join(b.dir, 'state'))) { const t = fs.readFileSync(path.join(b.dir, 'state', f), 'utf8'); assert.ok(!t.includes(canary) && !t.includes(fakeKey), `${f} holds no environment value`); }
  for (const s of ['watchdog.sh', 'collect-outputs.sh', 'pod-setup.sh']) {
    const src = fs.readFileSync(path.join(TOOLS, s), 'utf8');
    assert.ok(!/RUNPOD_API_KEY|printenv|\benv\b\s*(>|\|)|set -x|export -p/.test(src), `${s} neither assumes nor prints a credential`);
    assert.ok(!src.includes('\r'), `${s} uses LF line endings`);
  }
  assert.match(fs.readFileSync(path.join(TOOLS, 'watchdog.sh'), 'utf8'), /AUTHENTICATION IS UNRESOLVED UNTIL D1-7/);
});

// ---------------------------------------------------------------------------------------------------
test('transfer: outputs collected on the "Pod" verify locally; the success record is written last', () => {
  needBash();
  const pod = tmp('ap84b3-pod-'), outbox = path.join(pod, 'outbox', 'A'), env = {...baseEnv(), AP84B3_OUTBOX: fwd(outbox)};
  const raw = png('raw from pod'), api = Buffer.from('{"1": {"class_type": "KSampler", "inputs": {}}}\n');
  fs.writeFileSync(path.join(pod, 'out.png'), raw); fs.writeFileSync(path.join(pod, 'wf.json'), api);
  const collect = (...a) => spawnSync(BASH, [fwd(path.join(TOOLS, 'collect-outputs.sh')), ...a], {env, encoding: 'utf8', timeout: 20000});
  let r = collect('add', fwd(path.join(pod, 'out.png')), 'candidate-a-raw.png');
  assert.equal(r.status, 0, r.stderr); assert.equal(r.stdout.trim(), `${shaBuf(raw)}  ${raw.length}  candidate-a-raw.png`);
  r = collect('add', fwd(path.join(pod, 'wf.json')), 'workflow-q-api.json'); assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(parseManifest(fs.readFileSync(path.join(outbox, 'MANIFEST'), 'utf8')), [entry('candidate-a-raw.png', raw), entry('workflow-q-api.json', api)].map(e => ({sha256: e.sha256, bytes: e.bytes, name: e.name})));
  assert.deepEqual(fs.readdirSync(outbox).sort(), ['MANIFEST', 'candidate-a-raw.png', 'workflow-q-api.json'], 'no temporary files are left behind');
  // write-once, safe names only, real files only
  assert.match(collect('add', fwd(path.join(pod, 'out.png')), 'candidate-a-raw.png').stderr, /already in the outbox/);
  assert.match(collect('add', fwd(path.join(pod, 'out.png')), '../escape.png').stderr, /final name must be/);
  assert.match(collect('add', fwd(path.join(pod, 'missing.png')), 'candidate-b-raw.png').stderr, /source file not found/);
  // "pull" the outbox into a local staging folder, then verify
  const run = tmp('ap84b3-run-'), staging = path.join(run, 'staging-A');
  fs.cpSync(outbox, staging, {recursive: true});
  assert.equal(isRetained(run, 'A'), false, 'not retained before verification');
  const rec = verifyTransfer({runDir: run, candidate: 'A', stagingDir: staging});
  assert.equal(rec.status, 'verified'); assert.equal(rec.files.length, 2); assert.equal(rec.manifestSha256, sha(path.join(run, 'transfers', 'A', 'MANIFEST')));
  assert.equal(isRetained(run, 'A'), true); assert.ok(!fs.existsSync(staging), 'the staging folder was moved, not copied');
  assert.deepEqual(fs.readdirSync(path.join(run, 'transfers')).sort(), ['A', 'A.verified.json']);
  assert.throws(() => verifyTransfer({runDir: run, candidate: 'A', stagingDir: stage(run, 'A', {'x.png': png('x')})}), /already has a transfer/);
  assert.throws(() => verifyTransfer({runDir: path.join(REPO, 'studio'), candidate: 'A', stagingDir: staging}), /does not exist|outside the repository/);
});

test('transfer: an incomplete, mismatched or interrupted transfer never receives a success record', async () => {
  const fx = fixture(), good = png('complete output');
  const rejected = (pattern, prepare) => {
    const run = tmp('ap84b3-run-'), staging = stage(run, 'A', {'candidate-a-raw.png': good, 'workflow-q-api.json': Buffer.from('{}\n')});
    prepare(staging);
    assert.throws(() => verifyTransfer({runDir: run, candidate: 'A', stagingDir: staging}), e => e instanceof TransferRejected && e.problems.some(p => pattern.test(p)), `rejected: ${pattern}`);
    assert.equal(isRetained(run, 'A'), false, 'reported as not retained');
    assert.ok(!fs.existsSync(path.join(run, 'transfers', 'A.verified.json')), 'no success record');
    assert.ok(!fs.existsSync(path.join(run, 'transfers', 'A')), 'nothing where the import adapter reads');
    const rej = fs.readdirSync(path.join(run, 'rejected'));
    assert.ok(rej.some(n => n.endsWith('.failed.json')) && rej.some(n => !n.endsWith('.json')), 'moved to rejected/ with a failure record');
    return run;
  };
  rejected(/SHA-256 does not match/, s => { const f = path.join(s, 'candidate-a-raw.png'), b = fs.readFileSync(f); b[b.length - 5] ^= 0xff; fs.writeFileSync(f, b); });        // corrupted, same size
  rejected(/incomplete or changed/, s => { const f = path.join(s, 'candidate-a-raw.png'); fs.writeFileSync(f, fs.readFileSync(f).subarray(0, 200)); });                         // half-copied
  rejected(/missing/, s => { fs.rmSync(path.join(s, 'workflow-q-api.json')); });
  rejected(/extra file/, s => { fs.writeFileSync(path.join(s, 'unexpected.png'), png('extra')); });
  rejected(/extra file/, s => { fs.writeFileSync(path.join(s, '.candidate-b-raw.png.partial.123'), good.subarray(0, 100)); });                                                  // a copy still in progress on the Pod
  rejected(/not a PNG/, s => { fs.writeFileSync(path.join(s, 'candidate-a-raw.png'), Buffer.from('text')); writeManifest(s, ['candidate-a-raw.png', 'workflow-q-api.json']); });
  rejected(/MANIFEST is missing/, s => { fs.rmSync(path.join(s, 'MANIFEST')); });
  rejected(/manifest lists no files|manifest must start/, s => { fs.writeFileSync(path.join(s, 'MANIFEST'), 'not a manifest\n'); });
  // An interruption after the files were moved but before the record was written: still no success record,
  // and the import adapter refuses the candidate.
  const run = tmp('ap84b3-run-'), cut = png('cut', 96, 144, true);
  assert.throws(() => verifyTransfer({runDir: run, candidate: 'A', stagingDir: stage(run, 'A', {'candidate-a-raw.png': good}), beforeRecord: () => { throw new Error('power cut'); }}), /power cut/);
  assert.equal(isRetained(run, 'A'), false);
  assert.ok(!fs.existsSync(path.join(run, 'transfers', 'A.verified.json')) && !fs.existsSync(path.join(run, 'transfers', 'A')));
  fs.mkdirSync(path.join(run, 'cutouts')); fs.writeFileSync(path.join(run, 'cutouts', 'candidate-a-cutout.png'), cut);
  fs.writeFileSync(path.join(run, 'run-sheet.json'), JSON.stringify(sheetFor(fx, {A: {status: 'retained', raw: entry('candidate-a-raw.png', good), cutout: entry('candidate-a-cutout.png', cut)}})));
  await assert.rejects(createImportAdapter({dir: run, lockFile: fx.lockFile, decisionsFile: fx.decisionsFile}).generate(REQ), /transfer verification record is missing/);
  // An output that was never transferred is simply not retained.
  assert.equal(isRetained(run, 'B'), false); assert.equal(isRetained(tmp(), 'C'), false);
  assert.deepEqual(checkStaging(stage(tmp(), 'A', {'a.png': good})).problems, []);
});

// ---------------------------------------------------------------------------------------------------
// Build an export-shaped graph from a hand-written fixture template. The fixtures are synthetic: the real API export
// has not been seen, and these do not pre-approve it. mode: {candidate} or {smoke: true}.
function graph(workflow, lock, mode) {
  const W = lock.workflows[workflow], models = Object.fromEntries(lock.models.filter(m => m.workflow === workflow).map(m => [m.role, path.posix.basename(m.saveAs)]));
  const sm = mode.smoke ? lock.smoke : null;
  const values = {__PROMPT__: W.prompt, __NEGATIVE__: W.negativePrompt, __SEED__: sm ? sm.seed : lock.candidates[mode.candidate].seed, __STEPS__: sm ? sm.steps : W.steps, __CFG__: Number(W.cfg), __SAMPLER__: W.sampler, __SCHEDULER__: W.scheduler,
    __WIDTH__: sm ? sm.width : W.width, __HEIGHT__: sm ? sm.height : W.height, __UNET__: models['diffusion-model'], __CLIP__: models['text-encoder'], __VAE__: models.vae, __CHECKPOINT__: models.checkpoint,
    __IPA__: models['ip-adapter'], __CLIPVISION__: models['image-encoder'],
    __IPA_WEIGHT__: Number(W.ipAdapter?.weight), __IPA_WEIGHT_TYPE__: W.ipAdapter?.weightType, __IPA_START__: Number(W.ipAdapter?.startAt), __IPA_END__: Number(W.ipAdapter?.endAt),
    __RESIZE__: W.finalResize, __FINAL_WIDTH__: W.finalWidth, __FINAL_HEIGHT__: W.finalHeight};
  const g = JSON.parse(fs.readFileSync(path.join(FIX, `${workflow.toLowerCase()}.api.template.json`), 'utf8'));
  for (const n of Object.values(g)) for (const [k, v] of Object.entries(n.inputs)) if (typeof v === 'string' && v in values) n.inputs[k] = values[v];
  return g;
}
// The same graph with different node numbers, in a different order.
function renumber(g) {
  const ids = Object.keys(g), map = Object.fromEntries(ids.map((id, i) => [id, String(900 - i * 7)]));
  return Object.fromEntries(ids.slice().reverse().map(id => [map[id], {class_type: g[id].class_type, inputs: Object.fromEntries(Object.entries(g[id].inputs).map(([k, v]) => [k, Array.isArray(v) ? [map[v[0]], v[1]] : v]))}]));
}
test('workflow checker, layer 1: exports that meet every constraint pass, whatever their node numbers', () => {
  const lock = REAL.lock;
  const hashes = {};
  for (const [w, mode] of [['Q', {candidate: 'A'}], ['Q', {candidate: 'B'}], ['S', {candidate: 'C'}], ['Q', {smoke: true}], ['S', {smoke: true}]]) {
    const args = {workflow: w, lock, candidate: mode.candidate ?? null, smoke: !!mode.smoke};
    const res = checkWorkflow({graph: graph(w, lock, mode), ...args});
    assert.deepEqual([res.problems, res.unlisted], [[], []], `${w} ${JSON.stringify(mode)} meets the constraints`);
    assert.equal(res.ok, true); assert.equal(res.stop, false); assert.match(res.graphSha256, /^[0-9a-f]{64}$/);
    const again = checkWorkflow({graph: renumber(graph(w, lock, mode)), ...args});
    assert.equal(again.ok, true); assert.equal(again.graphSha256, res.graphSha256, 'node numbers and order do not matter');
    hashes[`${w}${mode.candidate ?? 'smoke'}`] = res.graphSha256;
  }
  assert.notEqual(hashes.QA, hashes.QB, 'a different seed is a different graph');
  const q = checkWorkflow({graph: graph('Q', lock, {candidate: 'A'}), workflow: 'Q', lock, candidate: 'A'});
  assert.deepEqual(q.recorded, {shift: 3.1}, 'the shift value is recorded for the run sheet, not judged');
  assert.deepEqual(q.free, {'image.image': 'master-v3.png', 'save.filename_prefix': 'ap84b3'}, 'free values are reported');
  // The lock names the Qwen latent node as an unverified compatibility gate, never as confirmed.
  assert.match(lock.workflows.Q.latentNodeStatus, /^compatibility-gate: unverified; test in the smoke run; on failure stop, no substitution$/);
  assert.equal(lock.workflows.Q.shift, 'recorded-at-export');
});

test('workflow checker, layer 1: any extra node, missing node, changed setting or rewired connection fails', () => {
  const lock = REAL.lock;
  const refuse = (w, mode, pattern, change) => {
    const g = graph(w, lock, mode); change(g);
    const res = checkWorkflow({graph: g, workflow: w, lock, candidate: mode.candidate ?? null, smoke: !!mode.smoke});
    assert.equal(res.ok, false, `${pattern} must not pass`); assert.equal(res.graphSha256, null);
    assert.ok(res.problems.some(p => pattern.test(p)), `${w}: ${pattern} in ${JSON.stringify(res.problems)}`);
  };
  const A = {candidate: 'A'}, C = {candidate: 'C'};
  // changed settings
  refuse('Q', A, /"seed" is 8403002, approved 8403001/, g => { g['10'].inputs.seed = 8403002; });
  refuse('Q', A, /"seed" is 8403900/, g => { g['10'].inputs.seed = lock.smoke.seed; });                 // the smoke seed in a candidate export
  refuse('Q', {smoke: true}, /"seed" is 8403001, approved 8403900/, g => { g['10'].inputs.seed = 8403001; });   // a candidate seed in a smoke export
  refuse('Q', {smoke: true}, /"steps" is 40, approved 8/, g => { g['10'].inputs.steps = 40; });
  refuse('Q', {smoke: true}, /"width" is 1024, approved 512/, g => { g['9'].inputs.width = 1024; });
  refuse('Q', A, /"steps" is 20, approved 40/, g => { g['10'].inputs.steps = 20; });
  refuse('Q', A, /"cfg" is 2\.5, approved 4/, g => { g['10'].inputs.cfg = 2.5; });
  refuse('Q', A, /"sampler_name"/, g => { g['10'].inputs.sampler_name = 'dpmpp_2m'; });
  refuse('Q', A, /"scheduler"/, g => { g['10'].inputs.scheduler = 'karras'; });
  refuse('Q', A, /"denoise" is 0\.8, approved 1/, g => { g['10'].inputs.denoise = 0.8; });
  refuse('Q', A, /"denoise" is missing/, g => { delete g['10'].inputs.denoise; });
  refuse('Q', A, /"unet_name"/, g => { g['1'].inputs.unet_name = 'qwen_image_edit_2509_fp8_e4m3fn.safetensors'; });
  refuse('Q', A, /"unet_name"/, g => { g['1'].inputs.unet_name = 'qwen_image_edit_2511_bf16.safetensors'; });
  refuse('Q', A, /"weight_dtype"/, g => { g['1'].inputs.weight_dtype = 'fp8_e4m3fn_fast'; });
  refuse('Q', A, /"clip_name"/, g => { g['2'].inputs.clip_name = 'qwen_2.5_vl_7b.safetensors'; });
  refuse('Q', A, /"type" is "flux2"/, g => { g['2'].inputs.type = 'flux2'; });
  refuse('Q', A, /"vae_name"/, g => { g['3'].inputs.vae_name = 'other_vae.safetensors'; });
  refuse('Q', A, /"prompt"/, g => { g['7'].inputs.prompt += ' Add a hat.'; });
  refuse('Q', A, /"prompt"/, g => { g['7'].inputs.prompt = g['7'].inputs.prompt.replace('a ribbed collar and ribbed hem', 'ribbing'); });
  refuse('Q', A, /"prompt"/, g => { g['8'].inputs.prompt = ''; });                                       // the template's empty string is not the approved single space
  refuse('Q', A, /"reference_latents_method"/, g => { g['13'].inputs.reference_latents_method = 'offset'; });
  refuse('Q', A, /"strength" is 0\.5/, g => { g['6'].inputs.strength = 0.5; });
  refuse('Q', A, /"pre_cfg" is true/, g => { g['6'].inputs.pre_cfg = true; });
  refuse('Q', A, /"height" is 1024, approved 1536/, g => { g['9'].inputs.height = 1024; });
  refuse('Q', A, /"batch_size" is 2/, g => { g['9'].inputs.batch_size = 2; });
  refuse('Q', A, /"shift" must be a number/, g => { g['5'].inputs.shift = 'auto'; });
  // extra and missing nodes; the unmodified template's nodes are not accepted
  refuse('Q', A, /node type LoraLoaderModelOnly is not part of the approved workflow/, g => { g['20'] = {class_type: 'LoraLoaderModelOnly', inputs: {lora_name: 'Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors', strength_model: 1, model: ['6', 0]}}; });
  refuse('Q', A, /node type FluxKontextImageScale is not part of the approved workflow/, g => { g['21'] = {class_type: 'FluxKontextImageScale', inputs: {image: ['4', 0]}}; g['7'].inputs.image1 = ['21', 0]; });
  refuse('Q', A, /expected 1 node\(s\) of type EmptySD3LatentImage, found 0/, g => { g['9'] = {class_type: 'VAEEncode', inputs: {pixels: ['4', 0], vae: ['3', 0]}}; });
  refuse('Q', A, /expected 1 node\(s\) of type EmptySD3LatentImage, found 0/, g => { g['9'].class_type = 'EmptyLatentImage'; });   // no substitute latent node
  refuse('Q', A, /expected 1 node\(s\) of type KSampler, found 2/, g => { g['30'] = structuredClone(g['10']); });
  refuse('Q', A, /expected 1 node\(s\) of type CFGNorm, found 0/, g => { delete g['6']; g['10'].inputs.model = ['5', 0]; });
  refuse('Q', A, /expected 2 node\(s\) of type FluxKontextMultiReferenceLatentMethod, found 1/, g => { delete g['14']; g['10'].inputs.negative = ['8', 0]; });
  refuse('Q', A, /node type CheckpointLoaderSimple is not part/, g => { g['31'] = {class_type: 'CheckpointLoaderSimple', inputs: {ckpt_name: 'sd_xl_base_1.0.safetensors'}}; });
  refuse('Q', A, /node type PrimitiveFloat is not part/, g => { g['32'] = {class_type: 'PrimitiveFloat', inputs: {value: 4}}; });
  // rewired connections
  refuse('Q', A, /"model" is connected to shift, expected cfgnorm/, g => { g['10'].inputs.model = ['5', 0]; });                          // CFGNorm bypassed
  refuse('Q', A, /expected/, g => { [g['10'].inputs.positive, g['10'].inputs.negative] = [g['10'].inputs.negative, g['10'].inputs.positive]; });   // prompts swapped
  refuse('Q', A, /unexpected connection on "image2"/, g => { g['7'].inputs.image2 = ['4', 0]; });                                         // a second reference image
  refuse('Q', A, /required connection "image1" from image is missing/, g => { delete g['8'].inputs.image1; });                            // negative encoder without the image
  refuse('Q', A, /required connection "vae" from vae is missing/, g => { delete g['7'].inputs.vae; });
  refuse('Q', A, /"steps" must be a literal setting, but it is connected/, g => { g['10'].inputs.steps = ['9', 0]; });
  refuse('Q', A, /"model" must be connected to unet, but it is a literal value/, g => { g['5'].inputs.model = 'x'; });
  // SDXL + IP-Adapter
  refuse('S', C, /"ckpt_name"/, g => { g['1'].inputs.ckpt_name = 'sd_xl_base_1.0_0.9vae.safetensors'; });
  refuse('S', C, /"ipadapter_file"/, g => { g['3'].inputs.ipadapter_file = 'ip-adapter_sdxl_vit-h.safetensors'; });
  refuse('S', C, /"clip_name"/, g => { g['12'].inputs.clip_name = 'CLIP-ViT-bigG-14-laion2B-39B-b160k.safetensors'; });
  refuse('S', C, /"weight" is 1, approved 0\.8/, g => { g['4'].inputs.weight = 1; });
  refuse('S', C, /"weight_type"/, g => { g['4'].inputs.weight_type = 'style transfer'; });
  refuse('S', C, /"combine_embeds" is "average"/, g => { g['4'].inputs.combine_embeds = 'average'; });
  refuse('S', C, /"embeds_scaling" is "K\+V"/, g => { g['4'].inputs.embeds_scaling = 'K+V'; });
  refuse('S', C, /"end_at" is 0\.8/, g => { g['4'].inputs.end_at = 0.8; });
  refuse('S', C, /unexpected connection on "image_negative"/, g => { g['4'].inputs.image_negative = ['2', 0]; });
  refuse('S', C, /unexpected connection on "attn_mask"/, g => { g['4'].inputs.attn_mask = ['2', 1]; });
  refuse('S', C, /required connection "clip_vision" from visionloader is missing/, g => { delete g['4'].inputs.clip_vision; });
  refuse('S', C, /node type IPAdapterUnifiedLoader is not part/, g => { g['3'] = {class_type: 'IPAdapterUnifiedLoader', inputs: {preset: 'PLUS (high strength)', model: ['1', 0]}}; });
  refuse('S', C, /node type PrepImageForClipVision is not part/, g => { g['40'] = {class_type: 'PrepImageForClipVision', inputs: {interpolation: 'LANCZOS', crop_position: 'pad', sharpening: 0, image: ['2', 0]}}; });
  refuse('S', C, /expected 2 node\(s\) of type CLIPTextEncode, found 1/, g => { g['5'].class_type = 'CLIPTextEncodeSDXL'; });
  refuse('S', C, /node type CLIPSetLastLayer is not part/, g => { g['41'] = {class_type: 'CLIPSetLastLayer', inputs: {stop_at_clip_layer: -2, clip: ['1', 1]}}; });
  refuse('S', C, /node type ControlNetApplyAdvanced is not part/, g => { g['42'] = {class_type: 'ControlNetApplyAdvanced', inputs: {strength: 1}}; });
  refuse('S', C, /node type VAELoader is not part/, g => { g['43'] = {class_type: 'VAELoader', inputs: {vae_name: 'sdxl_vae.safetensors'}}; });
  refuse('S', C, /"width" is 1024, approved 832/, g => { g['7'].inputs.width = 1024; g['7'].inputs.height = 1536; });
  refuse('S', C, /"upscale_method" is "bicubic"/, g => { g['10'].inputs.upscale_method = 'bicubic'; });
  refuse('S', C, /"crop" is "center"/, g => { g['10'].inputs.crop = 'center'; });
  refuse('S', C, /expected 2 node\(s\) of type SaveImage, found 1/, g => { delete g['13']; });            // the raw output must also be saved
  refuse('S', C, /"text"/, g => { g['6'].inputs.text += ', blurry'; });
  refuse('S', C, /"steps" is 40, approved 30/, g => { g['8'].inputs.steps = 40; });
  refuse('S', C, /"denoise"/, g => { g['8'].inputs.denoise = 0.9; });
  refuse('S', C, /"model" is connected to checkpoint, expected ipadapter/, g => { g['8'].inputs.model = ['1', 0]; });   // IP-Adapter bypassed
  // wrong pairing and wrong format
  const bad = (args, pattern) => { const r = checkWorkflow({lock, ...args}); assert.equal(r.ok, false); assert.match(r.problems[0], pattern); };
  bad({graph: graph('S', lock, C), workflow: 'S', candidate: 'A'}, /candidate A does not use workflow S/);
  bad({graph: graph('Q', lock, A), workflow: 'Q', candidate: 'A', smoke: true}, /either a candidate .* or a smoke run/);
  bad({graph: graph('Q', lock, A), workflow: 'Q'}, /either a candidate .* or a smoke run/);
  bad({graph: {nodes: [], links: []}, workflow: 'Q', candidate: 'A'}, /not an API-format export/);
  bad({graph: {'1': {inputs: {}}}, workflow: 'Q', candidate: 'A'}, /every node needs a class_type/);
});

test('workflow checker: an unlisted setting stops for owner review; layer 2 freezes the first export and compares the rest', () => {
  const lock = REAL.lock, A = {candidate: 'A'};
  const run = (g, mode = A, w = 'Q') => checkWorkflow({graph: g, workflow: w, lock, candidate: mode.candidate ?? null, smoke: !!mode.smoke});
  // A literal setting that the constraints do not list is never waved through: not ok, stop, nothing to freeze.
  for (const [id, name, value] of [['10', 'control_after_generate', 'fixed'], ['4', 'upload', 'image'], ['1', 'some_new_option', true], ['9', 'channels', 16]]) {
    const g = graph('Q', lock, A); g[id].inputs[name] = value;
    const r = run(g);
    assert.equal(r.ok, false); assert.equal(r.stop, true, `"${name}" needs the owner's review`); assert.deepEqual(r.problems, []);
    assert.equal(r.unlisted.length, 1); assert.match(r.unlisted[0], new RegExp(`setting "${name}" = .* is not listed in the approved constraints`));
    assert.equal(r.graphSha256, null);
    assert.throws(() => freeze({result: r, workflow: 'Q', candidate: 'A', lockSha256: REAL.sha256, apiSha256: 'a'.repeat(64)}), /only an export that passes every constraint/);
  }
  const sG = graph('S', lock, {candidate: 'C'}); sG['4'].inputs.unfold_batch = false;
  assert.equal(run(sG, {candidate: 'C'}, 'S').stop, true);
  // A real defect together with an unlisted setting is a failure, not merely a stop.
  const both = graph('Q', lock, A); both['10'].inputs.steps = 20; both['10'].inputs.extra = 1;
  assert.deepEqual([run(both).ok, run(both).stop], [false, false]);

  // Freeze candidate A's export. B and the smoke run must equal it apart from the values allowed to differ.
  const first = run(graph('Q', lock, A));
  const frozen = freeze({result: first, workflow: 'Q', candidate: 'A', lockSha256: REAL.sha256, apiSha256: 'a'.repeat(64)});
  assert.equal(frozen.graphSha256, first.graphSha256); assert.equal(frozen.graphSha256, graphHash(frozen.normalForm)); assert.deepEqual(frozen.recorded, {shift: 3.1});
  assert.deepEqual(Object.keys(frozen.normalForm).sort(), lock.workflows.Q.graphConstraints.nodes.map(n => n.role).sort(), 'the frozen form is keyed by role, not by node number');
  const cmp = (g, mode) => compareToFrozen({frozen, result: run(g, mode), lock, workflow: 'Q', smoke: !!mode.smoke});
  assert.deepEqual(cmp(graph('Q', lock, {candidate: 'B'}), {candidate: 'B'}), [], 'B differs from A only in its seed');
  assert.deepEqual(cmp(renumber(graph('Q', lock, {candidate: 'B'})), {candidate: 'B'}), []);
  assert.deepEqual(cmp(graph('Q', lock, {smoke: true}), {smoke: true}), [], 'the smoke run differs only in seed, latent size and steps');
  // Things layer 1 cannot pin are pinned by the freeze: the shift, the output slots and the file names.
  const d = (change, mode = {candidate: 'B'}) => { const g = graph('Q', lock, mode); change(g); return cmp(g, mode); };
  assert.match(d(g => { g['5'].inputs.shift = 3.0; })[0], /^shift\.shift: 3 differs from the frozen 3\.1$/);
  assert.match(d(g => { g['11'].inputs.vae = ['3', 1]; })[0], /^decode\.vae: \["@vae",1\] differs from the frozen \["@vae",0\]$/);
  assert.match(d(g => { g['4'].inputs.image = 'another-image.png'; })[0], /^image\.image:/);
  assert.match(d(g => { g['5'].inputs.shift = 3.0; }, {smoke: true})[0], /^shift\.shift:/, 'a smoke run may not change the shift either');
  // B compared as if it were a smoke run still passes; but a candidate's steps may not differ from the frozen graph.
  assert.deepEqual(compareToFrozen({frozen, result: run(graph('Q', lock, {smoke: true}), {smoke: true}), lock, workflow: 'Q', smoke: false}).map(x => x.split(':')[0]).sort(), ['latent.height', 'latent.width', 'sampler.steps']);
  assert.deepEqual(compareToFrozen({frozen: {...frozen, workflow: 'S'}, result: first, lock, workflow: 'Q'}), ['the frozen graph is missing or is for a different workflow']);
  assert.match(compareToFrozen({frozen, result: run(both), lock, workflow: 'Q'})[0], /did not pass the constraints/);
});

test('comparison sheet: one scale for every figure; labels and hashes recorded; inputs unchanged', async () => {
  const before = [sha(MASTER), sha(POSE02)];
  const {buffer, sheet} = await buildSheet([{label: 'Master v3 (reference)', file: MASTER}, {label: 'Pose 02 v1 (approved)', file: POSE02}]);
  assert.ok(spec.pngSize(buffer), 'the sheet is a PNG');
  assert.deepEqual(spec.pngSize(buffer), {width: sheet.width, height: sheet.height});
  assert.equal(sheet.items.length, 2);
  for (const it of sheet.items) {
    assert.equal(it.scale, sheet.scale, 'every item is drawn at the same scale');
    assert.equal(it.width, Math.round(it.sourceWidth * sheet.scale)); assert.equal(it.height, Math.round(it.sourceHeight * sheet.scale));
  }
  assert.deepEqual(sheet.items.map(i => i.label), ['Master v3 (reference)', 'Pose 02 v1 (approved)']);
  assert.deepEqual(sheet.items.map(i => i.sha256), before);
  assert.deepEqual(sheet.items.map(i => [i.sourceWidth, i.sourceHeight]), [[1024, 1536], [270, 571]]);
  assert.equal(sheet.items[0].y + sheet.items[0].height, sheet.items[1].y + sheet.items[1].height, 'figures share a baseline');
  assert.equal(layout([{label: 'big', width: 2048, height: 3072, sha256: 'x'}, {label: 'small', width: 100, height: 100, sha256: 'y'}]).scale, 0.5);
  assert.throws(() => layout([]), /at least one item/);
  assert.deepEqual([sha(MASTER), sha(POSE02)], before);
});

test('stop timer: alerts at every approved milestone and console checkpoint; none is past the absolute limit', () => {
  const L = REAL.lock.limits, start = Date.parse('2026-11-20T14:05:00Z'), alerts = schedule(REAL.lock, start);
  const at = kind => alerts.filter(a => a.kind === kind).map(a => a.seconds);
  assert.deepEqual(at('checkpoint'), [1800, 3600, 5400, 7200, 9000], 'a console checkpoint every 30 minutes');
  assert.deepEqual(at('milestone'), [8400, 9300, 10200]); assert.deepEqual(at('alert'), [9900]); assert.deepEqual(at('stop'), [10500]); assert.deepEqual(at('limit'), [10800]);
  assert.ok(alerts.every(a => a.seconds <= L.maxRuntimeSeconds)); assert.equal(Math.max(...alerts.map(a => a.seconds)), 3 * 3600);
  assert.equal(alerts.find(a => a.kind === 'limit').at, '2026-11-20T17:05:00.000Z');
  assert.match(alerts.find(a => a.kind === 'stop').message, /STOP IT IN THE WEB CONSOLE NOW/);
  assert.match(alerts.find(a => a.kind === 'checkpoint').message, /\$0\.25.*\$4\.75/);
  const announced = new Set();
  assert.deepEqual(due(alerts, start, start + 1799 * 1000, announced), []);
  const first = due(alerts, start, start + 1800 * 1000, announced);
  assert.deepEqual(first.map(a => a.seconds), [1800]); first.forEach(a => announced.add(`${a.seconds}:${a.kind}`));
  assert.deepEqual(due(alerts, start, start + 1900 * 1000, announced), [], 'an alert is announced once');
  assert.equal(due(alerts, start, start + 10800 * 1000, announced).length, alerts.length - 1, 'a late start announces everything that is overdue');
});

// ---------------------------------------------------------------------------------------------------
test('end to end: three separate jobs through the studio; quarantine, validation report and review; nothing is promoted', async () => {
  const fx = fixture(), run = tmp('ap84b3-run-'), dir = tmp('ap84b3-e2e-');
  // Stand-in "outputs": the real master v3 as the raw image and its local cut-out. Read only; nothing is generated.
  const raw = fs.readFileSync(MASTER), cands = {};
  fs.mkdirSync(path.join(run, 'cutouts'));
  for (const id of ['A', 'B']) {
    const rawName = `candidate-${id.toLowerCase()}-raw.png`, cutName = `candidate-${id.toLowerCase()}-cutout.png`;
    verifyTransfer({runDir: run, candidate: id, stagingDir: stage(run, id, {[rawName]: raw})});
    if (id === 'A') await cutout({input: path.join(run, 'transfers', id, rawName), output: path.join(run, 'cutouts', cutName), mode: 'full'});
    else fs.copyFileSync(path.join(run, 'cutouts', 'candidate-a-cutout.png'), path.join(run, 'cutouts', cutName));
    cands[id] = {status: 'retained', raw: entry(rawName, raw), cutout: entry(cutName, fs.readFileSync(path.join(run, 'cutouts', cutName)))};
  }
  cands.C = {status: 'lost'};
  fs.writeFileSync(path.join(run, 'run-sheet.json'), JSON.stringify(sheetFor(fx, cands), null, 1));

  const port = 4780 + Math.floor(Math.random() * 100);
  const s = createStudio({workspace: dir, port, genAdapter: createImportAdapter({dir: run, lockFile: fx.lockFile, decisionsFile: fx.decisionsFile}), command: () => [process.execPath, ['-e', '0']]});
  await s.listen();
  const call = async (p, {method = 'GET', body} = {}) => {
    const res = await fetch(`http://127.0.0.1:${port}${p}`, {method, headers: body !== undefined ? {'Content-Type': 'application/json'} : {}, body: body === undefined ? undefined : JSON.stringify(body)});
    const t = await res.text(); let json = null; try { json = JSON.parse(t); } catch {}
    return {status: res.status, json, text: t};
  };
  const until = async (id, statuses) => { for (let i = 0; i < 400; i++) { const j = (await call(`/api/generation/jobs/${id}`)).json; if (statuses.includes(j.status)) return j; await sleep(50); } throw new Error(`job ${id} did not reach ${statuses}`); };
  const job = d => call('/api/generation/jobs', {method: 'POST', body: {assetType: 'character-pose', assetKey: 'character-01/02', description: d}});
  try {
    const cfg = (await call('/api/generation')).json;
    assert.equal(cfg.adapter, 'import'); assert.equal(cfg.available, true);
    const ids = {};
    for (const id of ['A', 'B']) {
      const r = await job(`AP-84B3 candidate ${id}: import for owner review`);
      assert.equal(r.status, 202, r.text);
      const j = await until(r.json.id, ['candidate_ready', 'failed']);
      assert.equal(j.status, 'candidate_ready', j.error); assert.equal(j.adapter, 'import'); assert.equal(j.candidates.length, 1);
      const c = j.candidates[0];
      assert.equal(c.synthetic, false); assert.equal(c.sha256, cands[id].cutout.sha256); assert.deepEqual([c.width, c.height], [1024, 1536]);
      assert.equal(c.provenance.candidate, id); assert.equal(c.provenance.seed, fx.lock.candidates[id].seed); assert.equal(c.provenance.lockSha256, fx.sha256);
      assert.equal(sha(path.join(dir, 'quarantine', j.id, c.name)), c.sha256, 'the candidate is in quarantine');
      assert.ok(j.validations.length >= 1, 'a validation report was recorded');
      const checks = j.validations[j.validations.length - 1].checks;
      assert.ok(!checks.some(k => k.id === 'synthetic'), 'not treated as a synthetic fixture');
      assert.equal(checks.find(k => k.id === 'canvas-dimensions')?.status, 'pass', 'the full-canvas cut-out has the approved 1024x1536 canvas');
      ids[id] = j;
    }
    assert.notEqual(ids.A.id, ids.B.id, 'one job per candidate');
    // Candidate C was lost, and a repeat of A is refused: both jobs fail and import nothing.
    for (const d of ['AP-84B3 candidate C: import', 'AP-84B3 candidate A: again']) {
      const j = await until((await job(d)).json.id, ['candidate_ready', 'failed']);
      assert.equal(j.status, 'failed'); assert.match(j.error, /Import refused/); assert.equal(j.candidates.length, 0); assert.equal(j.retryable, false);
    }
    // Separate review records: A approved (a registry proposal only), B rejected.
    const a = await call(`/api/generation/jobs/${ids.A.id}/reviews`, {method: 'POST', body: {decision: 'approve', candidateId: ids.A.candidates[0].id, note: 'Fixture review: test of the review path only.'}});
    assert.equal(a.status, 201, a.text); assert.equal(a.json.status, 'approved');
    const proposal = a.json.proposals[a.json.proposals.length - 1];
    assert.equal(proposal.version, 2, 'proposed as version 2; version 1 is untouched'); assert.equal(proposal.promotable, true); assert.equal(proposal.status, 'proposed');
    const b = await call(`/api/generation/jobs/${ids.B.id}/reviews`, {method: 'POST', body: {decision: 'reject', note: 'Fixture review: rejected.'}});
    assert.equal(b.status, 201, b.text); assert.equal(b.json.status, 'rejected');
    assert.equal(a.json.reviews.length, 1); assert.equal(b.json.reviews.length, 1);
  } finally { await s.close(); }
});

test('boundaries: protected files are byte-identical, no credential is in the D1-6 files, and nothing was left in the repository', () => {
  for (const [f, h] of protectedBefore) assert.equal(sha(path.join(REPO, f)), h, `${f} is unchanged`);
  const files = ['studio/config/ap84b3-experiment.json', 'studio/lib/experiment-spec.mjs', 'studio/lib/gen-adapters.mjs', 'studio/server.mjs',
    ...fs.readdirSync(TOOLS).map(n => `studio/tools/ap84b3/${n}`), ...fs.readdirSync(FIX).map(n => `studio/tests/fixtures/ap84b3/${n}`), 'docs/oddly-relatable/AP-84B3-RUNBOOK.md'];
  assert.deepEqual(fs.readdirSync(TOOLS).sort(), ['build-pod-bundle.mjs', 'check-workflow.mjs', 'collect-outputs.sh', 'compare-sheet.mjs', 'cutout.cjs', 'pad-reference.mjs', 'pod-setup.sh', 'stop-timer.mjs', 'verify-transfer.mjs', 'watchdog.sh']);
  assert.deepEqual(fs.readdirSync(FIX).sort(), ['q.api.template.json', 's.api.template.json']);
  const secret = /rpa_[A-Za-z0-9]{16,}|hf_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(api[_-]?key|secret|password|token)\b\s*[:=]\s*['"][^'"\s]{8,}['"]|AKIA[0-9A-Z]{16}/i;
  for (const f of files) assert.ok(!secret.test(fs.readFileSync(path.join(REPO, f), 'utf8')), `${f} holds no credential`);
  // no run folder, bundle or output was written into the repository by these tests
  for (const d of ['studio/tools/ap84b3/transfers', 'studio/tools/ap84b3/rejected', 'studio/quarantine', 'studio/cutouts']) assert.ok(!fs.existsSync(path.join(REPO, d)));
});

// ---------------------------------------------------------------------------------------------------
// Lock amendment (owner decisions A1 to A3): smoke seed, pinned node settings, local reference padding,
// cumulative limits.
test('lock amendment: approved additions are present; the smoke seed and the latent gate are enforced by the lock itself', () => {
  const L = REAL.lock;
  assert.deepEqual({seed: L.smoke.seed, width: L.smoke.width, height: L.smoke.height, steps: L.smoke.steps, max: L.smoke.maxPerWorkflow}, {seed: 8403900, width: 512, height: 768, steps: 8, max: 1});
  assert.ok(!Object.values(L.candidates).some(c => c.seed === L.smoke.seed));
  assert.deepEqual([L.workflows.Q.denoise, L.workflows.S.denoise], ['1.0', '1.0']);
  assert.deepEqual([L.workflows.Q.inputScaling, L.workflows.Q.latentNode, L.workflows.Q.referenceLatentsMethod], ['none', 'EmptySD3LatentImage', 'index_timestep_zero']);
  assert.deepEqual(L.workflows.Q.referenceImages, {image1: 'master-v3', image2: 'none', image3: 'none'});
  assert.deepEqual([L.workflows.S.promptEncoder, L.workflows.S.clipSkip, L.workflows.S.finalResize, L.workflows.S.finalResizeCrop, L.workflows.S.rawOutputRetained], ['CLIPTextEncode', 'none', 'lanczos', 'disabled', true]);
  const I = L.workflows.S.ipAdapter;
  assert.deepEqual([I.loader, I.imageEncoderLoader, I.combineEmbeds, I.embedsScaling, I.imageNegative, I.attnMask], ['IPAdapterModelLoader', 'CLIPVisionLoader', 'concat', 'V only', 'none', 'none']);
  assert.deepEqual([I.weight, I.weightType, I.startAt, I.endAt], ['0.8', 'linear', '0.0', '1.0'], 'the previously approved IP-Adapter settings are unchanged');
  assert.deepEqual({w: L.workflows.S.reference.canvasWidth, h: L.workflows.S.reference.canvasHeight, rgb: L.workflows.S.reference.padColourRGB, local: L.workflows.S.reference.preparedLocally}, {w: 1536, h: 1536, rgb: [203, 203, 203], local: true});
  assert.equal(L.limits.cumulativeAcrossSessions, true);
  // The seven save paths, as documented by the pinned sources.
  assert.deepEqual(L.models.map(m => m.saveAs), ['models/diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors', 'models/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors', 'models/vae/qwen_image_vae.safetensors',
    'models/checkpoints/sd_xl_base_1.0.safetensors', 'models/ipadapter/ip-adapter-plus_sdxl_vit-h.safetensors', 'models/clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors']);
  assert.equal(L.software.ipadapterPlus.saveAs, 'custom_nodes/ComfyUI_IPAdapter_plus');
  // The lock refuses to be valid if these safeguards are weakened.
  const invalid = (mutate, pattern) => assert.throws(() => spec.loadLock(fixture({mutate})), pattern);
  invalid(o => { o.smoke.seed = o.candidates.A.seed; }, /smoke seed must differ from every candidate seed/);
  invalid(o => { o.smoke.seed = o.candidates.B.seed; }, /smoke seed must differ from every candidate seed/);
  invalid(o => { delete o.smoke.seed; }, /smoke\.seed/);
  invalid(o => { o.smoke.maxPerWorkflow = 2; }, /smoke needs/);
  invalid(o => { o.workflows.Q.latentNodeStatus = 'verified'; }, /unverified compatibility gate/);
  invalid(o => { delete o.workflows.Q.latentNodeStatus; }, /unverified compatibility gate/);
  invalid(o => { o.workflows.Q.inputScaling = 'FluxKontextImageScale'; }, /inputScaling must be "none"/);
  invalid(o => { o.workflows.Q.shift = '3.1'; }, /shift "recorded-at-export"/);
  invalid(o => { delete o.workflows.S.denoise; }, /denoise and latentNode are required/);
  invalid(o => { o.workflows.S.promptEncoder = 'CLIPTextEncodeSDXL'; }, /prompt encoder/);
  invalid(o => { o.workflows.S.ipAdapter.attnMask = 'mask.png'; }, /no attention mask/);
  invalid(o => { o.workflows.S.reference.padColourRGB = [0, 0, 0, 0]; }, /padColourRGB/);
  invalid(o => { o.limits.cumulativeAcrossSessions = false; }, /cumulative across sessions/);
  // Graph constraints must be well formed, closed, and free of forbidden nodes.
  const G = o => o.workflows.Q.graphConstraints;
  invalid(o => { G(o).closedWorld = false; }, /needs closedWorld/);
  invalid(o => { G(o).connections.push({from: 'unet', to: 'nowhere', input: 'model'}); }, /unknown role/);
  invalid(o => { G(o).connections.push({from: 'unet', to: 'sampler', input: 'model'}); }, /defined twice/);
  invalid(o => { G(o).nodes.push({role: 'lora', type: 'LoraLoaderModelOnly', literals: {}}); }, /forbidden node type/);
  invalid(o => { G(o).nodes.push({role: 'scale', type: 'FluxKontextImageScale', literals: {}}); }, /forbidden node type/);
  invalid(o => { G(o).nodes.find(n => n.role === 'latent').type = 'EmptyLatentImage'; }, /exactly one latent node of the pinned type/);
  invalid(o => { G(o).nodes.find(n => n.role === 'sampler').literals.steps = {ref: 'workflows.Q.nope', type: 'integer'}; }, /no value at workflows\.Q\.nope/);
  invalid(o => { G(o).nodes.find(n => n.role === 'sampler').literals.cfg = {ref: 'workflows.Q.cfg', type: 'integer'}; }, /not an integer/);
  invalid(o => { o.workflows.S.graphConstraints.nodes.push({role: 'x', type: 'IPAdapterUnifiedLoader', literals: {}}); }, /forbidden node type/);
  // Settings are single-sourced: the constraints point at the lock's own fields, so changing an approved value changes what the checker expects.
  const changed = fixture({mutate: o => { o.workflows.Q.steps = 20; }}).lock;
  assert.equal(spec.resolveLiteral(changed, 'Q', G(changed).nodes.find(n => n.role === 'sampler').literals.steps, {seed: 1}).value, 20);
  assert.equal(spec.resolveLiteral(L, 'Q', G(L).nodes.find(n => n.role === 'sampler').literals.steps, {seed: 1, smoke: true}).value, 8);
  assert.equal(spec.resolveLiteral(L, 'Q', G(L).nodes.find(n => n.role === 'sampler').literals.cfg, {seed: 1}).value, 4);
});

test('reference padding: 1536x1536, grey (203,203,203) borders, original pixels copied unchanged, repeatable, input untouched', async () => {
  const before = sha(MASTER), L = REAL.lock, ref = L.workflows.S.reference, dir = tmp('ap84b3-pad-');
  const a = await padReference({input: MASTER, canvasWidth: ref.canvasWidth, canvasHeight: ref.canvasHeight, padColourRGB: ref.padColourRGB});
  const b = await padReference({input: MASTER, canvasWidth: ref.canvasWidth, canvasHeight: ref.canvasHeight, padColourRGB: ref.padColourRGB});
  assert.equal(a.meta.output_sha256, b.meta.output_sha256, 'the result is repeatable');
  assert.equal(a.meta.output_sha256, ref.sha256, 'the lock records this exact file');
  assert.deepEqual(spec.pngSize(a.buffer), {width: 1536, height: 1536});
  assert.deepEqual(a.meta.placement, {left: 256, top: 0}); assert.equal(a.meta.source_sha256, L.inputs.editInput.sha256);
  // Pixels: borders are exactly the pad colour; the centre is master v3, pixel for pixel.
  fs.writeFileSync(path.join(dir, 'padded.png'), a.buffer);
  const px = async (file) => { const img = await canvas.loadImage(file); const c = canvas.createCanvas(img.width, img.height), ctx = c.getContext('2d'); ctx.drawImage(img, 0, 0); return (x, y) => [...ctx.getImageData(x, y, 1, 1).data]; };
  const padded = await px(path.join(dir, 'padded.png')), master = await px(MASTER);
  for (const [x, y] of [[0, 0], [255, 768], [128, 1535], [1280, 0], [1535, 1535], [1400, 700]]) assert.deepEqual(padded(x, y), [203, 203, 203, 255], `border pixel ${x},${y}`);
  for (const [x, y] of [[0, 0], [512, 300], [512, 700], [400, 1340], [1023, 1535], [300, 900], [700, 250]]) assert.deepEqual(padded(x + 256, y), master(x, y), `master pixel ${x},${y} is unchanged`);
  assert.equal(sha(MASTER), before, 'the input is unchanged');
  // From the lock: written once, outside the repository, and only if the hash matches the lock.
  const fx = fixture(), out = path.join(dir, 'reference.png');
  const meta = await padFromLock({lock: fx.lock, outFile: out});
  assert.equal(sha(out), ref.sha256); assert.equal(meta.output_sha256, ref.sha256);
  await assert.rejects(padFromLock({lock: fx.lock, outFile: out}), /EEXIST/);
  await assert.rejects(padFromLock({lock: fx.lock, outFile: path.join(REPO, 'studio', 'never-written.png')}), /outside the repository/);
  const other = fixture({mutate: o => { o.workflows.S.reference.padColourRGB = [0, 0, 0]; }});      // the node's own black padding is not the approved grey
  await assert.rejects(padFromLock({lock: other.lock, outFile: path.join(dir, 'black.png')}), /differs from the lock/);
  assert.ok(!fs.existsSync(path.join(dir, 'black.png')) && !fs.existsSync(path.join(REPO, 'studio', 'never-written.png')));
  await assert.rejects(padReference({input: MASTER, canvasWidth: 1000, canvasHeight: 1536, padColourRGB: [203, 203, 203]}), /larger than the canvas/);
  await assert.rejects(padReference({input: MASTER, canvasWidth: 1537, canvasHeight: 1536, padColourRGB: [203, 203, 203]}), /cannot be centred exactly/);
  await assert.rejects(padReference({input: MASTER, canvasWidth: 1536, canvasHeight: 1536, padColourRGB: [203, 203, 300]}), /padColourRGB/);
  if (!REAL.approved) {
    const r = spawnSync(process.execPath, [path.join(TOOLS, 'pad-reference.mjs'), '--out', path.join(dir, 'cli.png')], {encoding: 'utf8'});
    assert.equal(r.status, 1); assert.match(r.stderr, /not recorded as owner-approved/); assert.ok(!fs.existsSync(path.join(dir, 'cli.png')));
  }
});

test('cumulative limits: earlier sessions reduce what a later session may use; nothing resets and no funding is added', () => {
  const L = REAL.lock, none = spec.remainingLimits(L, []);
  assert.deepEqual([none.remainingRuntimeSeconds, none.watchdogStopSeconds, none.noNewGenerationSeconds, none.estimateStopUSD, none.sessionAllowed, none.additionalFunding], [10800, 10200, 8400, '4.750000', true, 'none']);
  const one = spec.remainingLimits(L, [{startedAt: '2026-11-20T14:00:00Z', endedAt: '2026-11-20T14:30:00Z', consumedUSD: '0.60'}]);
  assert.deepEqual([one.priorRuntimeSeconds, one.remainingRuntimeSeconds, one.watchdogStopSeconds, one.noNewGenerationSeconds, one.estimateStopUSD, one.sessionAllowed], [1800, 9000, 8400, 6600, '4.150000', true]);
  const two = spec.remainingLimits(L, [{startedAt: '2026-11-20T14:00:00Z', endedAt: '2026-11-20T14:30:00Z', consumedUSD: '0.60'}, {startedAt: '2026-11-21T09:00:00Z', endedAt: '2026-11-21T10:00:01Z', consumedUSD: '1.15'}]);
  assert.deepEqual([two.priorRuntimeSeconds, two.watchdogStopSeconds, two.estimateStopUSD], [5401, 4799, '3.000000']);
  // The reduced values are always tighter than the approved maxima, so the watchdog accepts them as they are.
  for (const r of [one, two]) assert.ok(r.watchdogStopSeconds < 10200 && r.noNewGenerationSeconds < 8400 && r.estimateStopMicro < 4750000);
  // When the runtime or the estimate margin is used up, no further session is allowed.
  assert.equal(spec.remainingLimits(L, [{startedAt: '2026-11-20T14:00:00Z', endedAt: '2026-11-20T16:20:00Z', consumedUSD: '2.60'}]).sessionAllowed, false, 'past the no-new-generation point');
  assert.equal(spec.remainingLimits(L, [{startedAt: '2026-11-20T14:00:00Z', endedAt: '2026-11-20T14:10:00Z', consumedUSD: '4.75'}]).sessionAllowed, false, 'the estimate margin is used up');
  assert.throws(() => spec.remainingLimits(L, [{startedAt: 'yesterday', endedAt: '2026-11-20T14:10:00Z', consumedUSD: '1.00'}]), /valid startedAt and endedAt/);
  assert.throws(() => spec.remainingLimits(L, [{startedAt: '2026-11-20T14:00:00Z', endedAt: '2026-11-20T14:10:00Z', consumedUSD: 1}]), /not a decimal dollar amount/);
});

test('smoke outputs: verified into their own folder, recorded in the run sheet, and never importable as a candidate', async () => {
  const fx = fixture(), smokeQ = png('smoke q', 64, 96), {run, sheet, writeSheet, adapter} = buildRun(fx);
  const rec = verifyTransfer({runDir: run, candidate: 'smoke', stagingDir: stage(run, 'smoke', {'smoke-q.png': smokeQ})});
  assert.equal(rec.candidate, 'smoke'); assert.equal(isRetained(run, 'smoke'), true);
  assert.deepEqual(fs.readdirSync(path.join(run, 'transfers')).sort(), ['A', 'A.verified.json', 'smoke', 'smoke.verified.json']);
  assert.throws(() => verifyTransfer({runDir: run, candidate: 'D', stagingDir: stage(run, 'D', {'x.png': smokeQ})}), /candidate must be A, B, C or smoke/);
  // Recorded in the run sheet with the lock's seed, size and steps: the sheet stays valid and candidate A still imports.
  const s = structuredClone(sheet); s.smoke = [smokeEntry(fx, 'Q', shaBuf(smokeQ))]; writeSheet(s);
  assert.deepEqual(spec.validateRunSheet(s, fx.lock, fx.sha256), []);
  // No job can ask for the smoke output, whatever it is called.
  for (const d of ['AP-84B3 candidate smoke', 'AP-84B3 smoke', 'AP-84B3 candidate S', 'smoke-q.png']) await assert.rejects(adapter.generate({...REQ, description: d}), /description must start with/);
  // Passing the smoke image off as candidate B is refused: by its name, and by its hash.
  const cut = png('cut b', 96, 144, true);
  fs.writeFileSync(path.join(run, 'cutouts', 'candidate-b-cutout.png'), cut);
  verifyTransfer({runDir: run, candidate: 'B', stagingDir: stage(run, 'B', {'candidate-b-raw.png': smokeQ})});
  const asB = structuredClone(s); asB.candidates.B = {...asB.candidates.B, status: 'retained', raw: entry('candidate-b-raw.png', smokeQ), cutout: entry('candidate-b-cutout.png', cut)}; writeSheet(asB);
  await assert.rejects(adapter.generate({...REQ, description: 'AP-84B3 candidate B'}), /candidate B: raw is a smoke image; smoke images are never candidates/);
  assert.ok(!fs.existsSync(path.join(run, 'imported', 'B.json')));
  // While the run sheet is invalid nothing imports, candidate A included. With the valid sheet restored, A imports.
  await assert.rejects(adapter.generate(REQ), /run sheet does not match the approved experiment/);
  assert.ok(!fs.existsSync(path.join(run, 'imported', 'A.json')));
  writeSheet(s);
  const [out] = await adapter.generate(REQ);
  assert.equal(out.provenance.candidate, 'A');
});

// ---------------------------------------------------------------------------------------------------
// The freeze is mandatory. There is no way to accept a later export without comparing it with the frozen graph.
test('workflow freeze is mandatory and fails closed: only A (Qwen) and C (SDXL) may create it; everything else must match it', () => {
  const lock = REAL.lock, lockSha256 = REAL.sha256, run = tmp('ap84b3-freeze-');
  const A = {candidate: 'A'}, B = {candidate: 'B'}, C = {candidate: 'C'}, SMOKE = {smoke: true};
  const check = (w, mode, change = null, dir = run) => {
    const g = graph(w, lock, mode); if (change) change(g);
    return checkExportInRun({runDir: dir, graph: g, workflow: w, lock, lockSha256, candidate: mode.candidate ?? null, smoke: !!mode.smoke, apiSha256: 'a'.repeat(64)});
  };
  const fileQ = path.join(run, frozenFileName('Q')), fileS = path.join(run, frozenFileName('S'));
  assert.deepEqual([frozenFileName('Q'), frozenFileName('S'), FREEZING_CANDIDATE.Q, FREEZING_CANDIDATE.S], ['frozen-q.json', 'frozen-s.json', 'A', 'C']);

  // 1. Nothing is frozen yet: a later candidate and every smoke export fail closed, and create nothing.
  for (const [w, mode, pattern] of [['Q', B, /Only candidate A's export may create it/], ['Q', SMOKE, /A smoke export cannot create one: freeze candidate A's export first/], ['S', SMOKE, /A smoke export cannot create one: freeze candidate C's export first/]]) {
    const r = check(w, mode);
    assert.equal(r.ok, false, 'fails closed without a frozen graph'); assert.equal(r.graphSha256, null); assert.equal(r.toFreeze, null); assert.equal(r.frozenRequired, true);
    assert.match(r.problems[0], /no frozen graph exists/); assert.match(r.problems[0], pattern);
  }
  assert.ok(!fs.existsSync(fileQ) && !fs.existsSync(fileS), 'nothing was frozen by a smoke or later-candidate export');
  // 2. A faulty or unreviewed export of the freezing candidate creates nothing either.
  assert.equal(check('Q', A, g => { g['10'].inputs.steps = 20; }).ok, false);
  const stopped = check('Q', A, g => { g['10'].inputs.control_after_generate = 'fixed'; });
  assert.deepEqual([stopped.ok, stopped.stop, stopped.toFreeze], [false, true, null]);
  assert.ok(!fs.existsSync(fileQ));
  // 3. The first valid export of A freezes workflow Q; the first valid export of C freezes workflow S. Written once.
  const a = check('Q', A), c = check('S', C);
  for (const [r, file, from, w] of [[a, fileQ, 'candidate A', 'Q'], [c, fileS, 'candidate C', 'S']]) {
    assert.equal(r.ok, true); assert.equal(r.frozenRequired, false); assert.equal(r.frozenWritten, file);
    const f = JSON.parse(fs.readFileSync(file, 'utf8'));
    assert.deepEqual([f.workflow, f.frozenFrom, f.lockSha256, f.graphSha256], [w, from, lockSha256, r.graphSha256]); assert.equal(graphHash(f.normalForm), f.graphSha256);
  }
  const frozenBytes = sha(fileQ);
  // 4. From now on every export is compared. The permitted differences pass: seed (B), and seed, size and steps (smoke).
  for (const [w, mode] of [['Q', A], ['Q', B], ['Q', SMOKE], ['S', C], ['S', SMOKE]]) {
    const r = check(w, mode);
    assert.equal(r.ok, true, `${w} ${JSON.stringify(mode)} equals the frozen graph apart from the permitted values`);
    assert.deepEqual(r.differencesFromFrozen, []); assert.equal(r.toFreeze, null); assert.equal(r.frozenWritten, undefined);
  }
  // 5. Nothing frozen may change silently: the shift, an output slot, a file name. None of these is caught by layer 1.
  const differs = (w, mode, change, pattern) => {
    const g = graph(w, lock, mode); change(g);
    assert.equal(checkWorkflow({graph: g, workflow: w, lock, candidate: mode.candidate ?? null, smoke: !!mode.smoke}).ok, true, 'layer 1 alone would pass this export');
    const r = check(w, mode, change);
    assert.equal(r.ok, false); assert.equal(r.graphSha256, null); assert.deepEqual(r.problems, ['the export differs from the frozen graph']);
    assert.ok(r.differencesFromFrozen.some(d => pattern.test(d)), `${pattern} in ${JSON.stringify(r.differencesFromFrozen)}`);
  };
  for (const mode of [A, B, SMOKE]) {
    differs('Q', mode, g => { g['5'].inputs.shift = 3.0; }, /^shift\.shift: 3 differs from the frozen 3\.1$/);                         // changed shift
    differs('Q', mode, g => { g['11'].inputs.vae = ['3', 1]; }, /^decode\.vae: \["@vae",1\] differs from the frozen \["@vae",0\]$/);   // changed output slot
    differs('Q', mode, g => { g['10'].inputs.model = ['6', 1]; }, /^sampler\.model: \["@cfgnorm",1\]/);                                // changed output slot on the model chain
    differs('Q', mode, g => { g['4'].inputs.image = 'other.png'; }, /^image\.image:/);                                                 // changed input file name
  }
  differs('S', C, g => { g['9'].inputs.vae = ['1', 0]; }, /^decode\.vae: \["@checkpoint",0\] differs from the frozen \["@checkpoint",2\]$/);
  differs('S', SMOKE, g => { g['5'].inputs.clip = ['1', 0]; }, /^positive\.clip:/);
  // A changed connection or node setting fails as well (at layer 1, before the comparison is even reached).
  for (const change of [g => { g['10'].inputs.model = ['5', 0]; }, g => { g['7'].inputs.image2 = ['4', 0]; }, g => { g['6'].inputs.strength = 0.5; }, g => { g['10'].inputs.cfg = 3.5; }]) {
    for (const mode of [B, SMOKE]) { const r = check('Q', mode, change); assert.equal(r.ok, false); assert.ok(r.problems.length > 0); assert.equal(r.differencesFromFrozen, null); }
  }
  // And a connection difference is detected by the comparison itself.
  const frozenQ = JSON.parse(fs.readFileSync(fileQ, 'utf8')), layer1 = checkWorkflow({graph: graph('Q', lock, B), workflow: 'Q', lock, candidate: 'B'});
  const rewired = structuredClone(layer1); rewired.normalForm.sampler.inputs.positive = ['@refneg', 0];
  assert.deepEqual(compareToFrozen({frozen: frozenQ, result: rewired, lock, workflow: 'Q'}), ['sampler.positive: ["@refneg",0] differs from the frozen ["@refpos",0]']);
  const retyped = structuredClone(layer1); retyped.normalForm.latent.class_type = 'EmptyLatentImage';
  assert.deepEqual(compareToFrozen({frozen: frozenQ, result: retyped, lock, workflow: 'Q'}), ['latent: node type EmptyLatentImage differs from the frozen EmptySD3LatentImage']);
  // The permitted differences are exactly these, and no others: a candidate's size and steps may not differ.
  assert.deepEqual(compareToFrozen({frozen: frozenQ, result: checkWorkflow({graph: graph('Q', lock, SMOKE), workflow: 'Q', lock, smoke: true}), lock, workflow: 'Q', smoke: false}).map(d => d.split(':')[0]).sort(), ['latent.height', 'latent.width', 'sampler.steps']);
  // 6. The frozen graph is never replaced: a different "first" export of A is compared, not re-frozen.
  assert.equal(check('Q', A, g => { g['5'].inputs.shift = 2.9; }).ok, false);
  assert.equal(sha(fileQ), frozenBytes, 'the frozen graph is unchanged');
  // 7. An unusable frozen graph fails closed: altered, unreadable, made under another lock, for another workflow, or not from the freezing candidate.
  const withFrozen = (content, w = 'Q', mode = B) => { const dir = tmp('ap84b3-frz-'); fs.writeFileSync(path.join(dir, frozenFileName(w)), typeof content === 'string' ? content : JSON.stringify(content)); return check(w, mode, null, dir); };
  const altered = structuredClone(frozenQ); altered.normalForm.shift.inputs.shift = 3.0;                       // edited to match a changed export
  for (const [content, pattern] of [[altered, /has been altered/], ['{not json', /not a valid frozen record/], ['[]', /not a valid frozen record/], ['null', /not a valid frozen record/],
    [{...frozenQ, lockSha256: 'c'.repeat(64)}, /different experiment lock/], [{...frozenQ, frozenFrom: 'candidate B'}, /not made from candidate A/], [{...frozenQ, schema: 'something-else'}, /not a valid frozen record/]]) {
    const r = withFrozen(content);
    assert.equal(r.ok, false); assert.equal(r.graphSha256, null); assert.ok(r.problems.some(x => pattern.test(x)), `${pattern} in ${JSON.stringify(r.problems)}`);
  }
  assert.ok(withFrozen(JSON.parse(fs.readFileSync(fileS, 'utf8'))).problems.some(x => /is for workflow S, not Q/.test(x)));
  assert.equal(withFrozen(altered, 'Q', SMOKE).ok, false); assert.equal(withFrozen('{not json', 'Q', A).ok, false, 'even candidate A cannot overwrite an unusable frozen graph');
  // 8. Remove the frozen graph and the later exports fail closed again.
  const gone = tmp('ap84b3-gone-');
  for (const mode of [B, SMOKE]) assert.match(check('Q', mode, null, gone).problems[0], /no frozen graph exists/);
  // 9. The decision function itself fails closed with no frozen record, and a smoke export can never be frozen.
  const direct = m => validateExport({graph: graph('Q', lock, m), workflow: 'Q', lock, lockSha256, candidate: m.candidate ?? null, smoke: !!m.smoke, frozen: null});
  assert.deepEqual([direct(B).ok, direct(SMOKE).ok, direct(A).ok], [false, false, true]); assert.equal(direct(SMOKE).toFreeze, null); assert.ok(direct(A).toFreeze);
  assert.throws(() => freeze({result: layer1, workflow: 'Q', candidate: 'B', lockSha256, apiSha256: 'a'.repeat(64)}), /only candidate A may freeze workflow Q/);
  assert.throws(() => freeze({result: checkWorkflow({graph: graph('S', lock, C), workflow: 'S', lock, candidate: 'C'}), workflow: 'S', candidate: 'A', lockSha256, apiSha256: 'a'.repeat(64)}), /only candidate C may freeze workflow S/);
  // 10. The run folder must exist and be outside the repository; the command line has no way to skip or redirect the freeze.
  assert.throws(() => check('Q', A, null, path.join(REPO, 'studio')), /outside the repository/);
  assert.throws(() => check('Q', A, null, path.join(os.tmpdir(), 'ap84b3-no-such-run')), /run folder does not exist/);
  const cli = (...args) => spawnSync(process.execPath, [path.join(TOOLS, 'check-workflow.mjs'), ...args], {encoding: 'utf8'});
  const exportFile = path.join(run, 'export-b.json'); fs.writeFileSync(exportFile, JSON.stringify(graph('Q', lock, B)));
  for (const flag of ['--frozen', '--write-frozen']) { const r = cli('--run', run, '--workflow', 'Q', '--candidate', 'B', '--file', exportFile, flag, fileQ); assert.equal(r.status, 1); assert.match(r.stderr, /not accepted: the frozen graph is always the one in the run folder/); }
  assert.match(cli('--workflow', 'Q', '--candidate', 'B', '--file', exportFile).stderr, /usage: check-workflow\.mjs --run <run folder>/);
  assert.match(cli('--run', run, '--workflow', 'Q', '--candidate', 'B', '--smoke', '--file', exportFile).stderr, /usage:/);
  if (!REAL.approved) assert.match(cli('--run', run, '--workflow', 'Q', '--candidate', 'B', '--file', exportFile).stderr, /not recorded as owner-approved/);
});

test('cumulative limits cannot silently reset: a later session with default or over-generous watchdog settings is refused before it starts', () => {
  const L = REAL.lock;
  const prior = [{startedAt: '2026-11-20T14:00:00Z', endedAt: '2026-11-20T14:30:00Z', consumedUSD: '0.60'}];
  // First session: the watchdog's defaults are the full limits, which is correct.
  assert.deepEqual(spec.checkSessionSettings(L, [], {}).problems, []);
  assert.deepEqual(spec.checkSessionSettings(L, [], {}).required, {WD_STOP_SECONDS: '10200', WD_NO_NEW_GENERATION_SECONDS: '8400', WD_ESTIMATE_STOP_USD: '4.750000'});
  // Later session with nothing set: every limit would silently reset to the full value. Refused, with the values to use.
  const reset = spec.checkSessionSettings(L, prior, {});
  assert.equal(reset.ok, false); assert.equal(reset.problems.length, 3);
  for (const name of ['WD_STOP_SECONDS', 'WD_NO_NEW_GENERATION_SECONDS', 'WD_ESTIMATE_STOP_USD']) assert.ok(reset.problems.some(p => p.startsWith(`${name} is not set, so the watchdog would use the full limit`)));
  assert.deepEqual(reset.required, {WD_STOP_SECONDS: '8400', WD_NO_NEW_GENERATION_SECONDS: '6600', WD_ESTIMATE_STOP_USD: '4.150000'});
  // The full limits passed explicitly are refused too; so is any one value left too high.
  assert.equal(spec.checkSessionSettings(L, prior, {WD_STOP_SECONDS: '10200', WD_NO_NEW_GENERATION_SECONDS: '8400', WD_ESTIMATE_STOP_USD: '4.75'}).problems.length, 3);
  assert.match(spec.checkSessionSettings(L, prior, {WD_STOP_SECONDS: '8401', WD_NO_NEW_GENERATION_SECONDS: '6600', WD_ESTIMATE_STOP_USD: '4.15'}).problems[0], /^WD_STOP_SECONDS is 8401, above what remains/);
  assert.match(spec.checkSessionSettings(L, prior, {WD_STOP_SECONDS: '8400', WD_NO_NEW_GENERATION_SECONDS: '6600', WD_ESTIMATE_STOP_USD: '4.16'}).problems[0], /^WD_ESTIMATE_STOP_USD is 4\.16, above what remains/);
  assert.match(spec.checkSessionSettings(L, prior, {WD_STOP_SECONDS: '8400', WD_NO_NEW_GENERATION_SECONDS: 'soon', WD_ESTIMATE_STOP_USD: '4.15'}).problems[0], /WD_NO_NEW_GENERATION_SECONDS is not a valid value/);
  // The reduced values, or tighter ones, are accepted.
  assert.equal(spec.checkSessionSettings(L, prior, reset.required).ok, true);
  assert.equal(spec.checkSessionSettings(L, prior, {WD_STOP_SECONDS: '6000', WD_NO_NEW_GENERATION_SECONDS: '5000', WD_ESTIMATE_STOP_USD: '3.00'}).ok, true);
  // Test mode is never acceptable for a real session, and an exhausted budget allows no session at all.
  assert.match(spec.checkSessionSettings(L, prior, {...reset.required, WD_TEST_MODE: '1'}).problems[0], /WD_TEST_MODE must not be set/);
  const spent = spec.checkSessionSettings(L, [{startedAt: '2026-11-20T14:00:00Z', endedAt: '2026-11-20T16:30:00Z', consumedUSD: '2.80'}], {WD_STOP_SECONDS: '1200', WD_NO_NEW_GENERATION_SECONDS: '0', WD_ESTIMATE_STOP_USD: '1.95'});
  assert.equal(spent.ok, false); assert.match(spent.problems[0], /no further session is allowed/);
  // The run record enforces the same totals after the fact: a sheet that omits earlier sessions' field is invalid,
  // and sessions that together exceed the runtime or the ceiling make it invalid (so nothing can be imported).
  const fx = fixture(), sheet = sheetFor(fx, {});
  const noField = structuredClone(sheet); delete noField.priorSessions;
  assert.ok(spec.validateRunSheet(noField, fx.lock, fx.sha256).some(p => /priorSessions must be a list/.test(p)));
  const over = structuredClone(sheet); over.priorSessions = [{startedAt: '2026-11-19T10:00:00Z', endedAt: '2026-11-19T11:40:00Z', gpu: sheet.pod.gpu, consumedUSD: '3.50', reason: 'earlier session'}];
  const overProblems = spec.validateRunSheet(over, fx.lock, fx.sha256);
  assert.ok(overProblems.some(p => /total Pod runtime across all sessions exceeds/.test(p)) && overProblems.some(p => /total consumption across all sessions exceeds/.test(p)));
  // The watchdog accepts the reduced values as they are: they are always at or below its fixed maxima.
  const wdSrc = fs.readFileSync(path.join(TOOLS, 'watchdog.sh'), 'utf8');
  assert.match(wdSrc, /MAX_STOP_SECONDS=10200/); assert.match(wdSrc, /MAX_ESTIMATE_STOP_MICRO=4750000/); assert.match(wdSrc, /MAX_NO_NEW_GENERATION=8400/);
});
