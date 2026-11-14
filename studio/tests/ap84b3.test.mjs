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
import {checkWorkflow} from '../tools/ap84b3/check-workflow.mjs';
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
function sheetFor(fx, cands, extra = {}) {
  const L = fx.lock;
  const candidates = Object.fromEntries(spec.CANDIDATE_IDS.map(id => [id, {workflow: L.candidates[id].workflow, seed: L.candidates[id].seed, status: 'not-generated', ...(cands[id] || {})}]));
  return {schema: spec.RUN_SHEET_SCHEMA, runId: 'r-20261120-140500', lockSha256: fx.sha256,
    pod: {provider: L.provider.name, cloud: L.provider.cloud, gpu: L.provider.gpuPrimary, region: 'test-region', startedAt: '2026-11-20T14:05:00Z', endedAt: '2026-11-20T15:35:00Z', gpuRateUSDPerHour: L.limits.gpuRateCapUSDPerHour[L.provider.gpuPrimary]},
    software: {comfyuiCommit: L.software.comfyui.commit, ipadapterCommit: L.software.ipadapterPlus.commit},
    workflows: {Q: {apiSha256: 'a'.repeat(64)}, S: {apiSha256: 'b'.repeat(64)}}, candidates, smoke: [], ...extra};
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
  const cases = [
    [s => { s.lockSha256 = 'c'.repeat(64); }, /lockSha256/], [s => { s.candidates.A.seed = 1; }, /seed differs/], [s => { s.candidates.B.workflow = 'S'; }, /workflow or seed/],
    [s => { s.software.comfyuiCommit = '1'.repeat(40); }, /comfyuiCommit/], [s => { s.software.ipadapterCommit = '1'.repeat(40); }, /ipadapterCommit/],
    [s => { s.pod.gpu = 'NVIDIA RTX 4090 24 GB'; }, /approved primary or fallback/], [s => { s.pod.gpuRateUSDPerHour = '1.10'; }, /rate cap/], [s => { s.pod.cloud = 'Community Cloud'; }, /approved provider/],
    [s => { s.pod.endedAt = '2026-11-20T17:05:01Z'; }, /runtime exceeds/], [s => { delete s.workflows.Q.apiSha256; }, /apiSha256/], [s => { delete s.candidates.C; }, /exactly A, B and C/],
    [s => { s.candidates.A.cutout.name = '../escape.png'; }, /safe \.png name/], [s => { s.candidates.A.raw.sha256 = 'xyz'; }, /sha256/], [s => { s.candidates.A.status = 'kept'; }, /status must be/],
    [s => { s.smoke = [{workflow: 'Q', sha256: 'd'.repeat(64)}, {workflow: 'Q', sha256: 'e'.repeat(64)}]; }, /more than 1 smoke run/], [s => { delete s.smoke; }, /smoke must be a list/],
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
  await refuse(/smoke images are never candidates/, r => reSheet(r, s => { s.smoke = [{workflow: 'Q', name: 'smoke-q.png', sha256: s.candidates.A.cutout.sha256}]; }));
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
function graph(workflow, lock, candidate) {
  const W = lock.workflows[workflow], models = Object.fromEntries(lock.models.filter(m => m.workflow === workflow).map(m => [m.role, path.posix.basename(m.saveAs)]));
  const values = {__PROMPT__: W.prompt, __NEGATIVE__: W.negativePrompt, __SEED__: lock.candidates[candidate].seed, __STEPS__: W.steps, __CFG__: Number(W.cfg), __SAMPLER__: W.sampler, __SCHEDULER__: W.scheduler,
    __WIDTH__: W.width, __HEIGHT__: W.height, __UNET__: models['diffusion-model'], __CLIP__: models['text-encoder'], __VAE__: models.vae, __CHECKPOINT__: models.checkpoint,
    __IPA_WEIGHT__: Number(W.ipAdapter?.weight), __IPA_WEIGHT_TYPE__: W.ipAdapter?.weightType, __IPA_START__: Number(W.ipAdapter?.startAt), __IPA_END__: Number(W.ipAdapter?.endAt),
    __RESIZE__: W.finalResize, __FINAL_WIDTH__: W.finalWidth, __FINAL_HEIGHT__: W.finalHeight};
  const g = JSON.parse(fs.readFileSync(path.join(FIX, `${workflow.toLowerCase()}.api.template.json`), 'utf8'));
  for (const n of Object.values(g)) for (const [k, v] of Object.entries(n.inputs)) if (typeof v === 'string' && v in values) n.inputs[k] = values[v];
  return g;
}
test('workflow checker: matching exports pass; any changed setting, model, prompt or an added LoRA is refused', () => {
  const lock = REAL.lock;
  for (const [w, c] of [['Q', 'A'], ['Q', 'B'], ['S', 'C']]) {
    const res = checkWorkflow({graph: graph(w, lock, c), workflow: w, candidate: c, lock});
    assert.deepEqual(res.problems, [], `${w}/${c} matches the lock`); assert.equal(res.ok, true);
  }
  assert.equal(checkWorkflow({graph: graph('Q', lock, 'A'), workflow: 'Q', candidate: 'A', lock}).recorded.shift, 3.1, 'the shift value is reported for the run sheet, not judged');
  assert.equal(checkWorkflow({graph: graph('S', lock, 'C'), workflow: 'S', candidate: 'C', lock}).recorded.resizeInWorkflow, true);
  const refuse = (w, c, pattern, change) => {
    const g = graph(w, lock, c); change(g);
    const res = checkWorkflow({graph: g, workflow: w, candidate: c, lock});
    assert.equal(res.ok, false); assert.ok(res.problems.some(p => pattern.test(p)), `${w}: ${pattern} in ${JSON.stringify(res.problems)}`);
  };
  refuse('Q', 'A', /seed is/, g => { g['10'].inputs.seed = 8403002; });                       // candidate B's seed in candidate A's export
  refuse('Q', 'A', /steps is 20/, g => { g['10'].inputs.steps = 20; });
  refuse('Q', 'A', /cfg is 2\.5/, g => { g['10'].inputs.cfg = 2.5; });
  refuse('Q', 'A', /sampler is/, g => { g['10'].inputs.sampler_name = 'dpmpp_2m'; });
  refuse('Q', 'A', /scheduler is/, g => { g['10'].inputs.scheduler = 'karras'; });
  refuse('Q', 'A', /denoise/, g => { g['10'].inputs.denoise = 0.8; });
  refuse('Q', 'A', /diffusion model is/, g => { g['1'].inputs.unet_name = 'qwen_image_edit_2509_fp8_e4m3fn.safetensors'; });
  refuse('Q', 'A', /diffusion model is/, g => { g['1'].inputs.unet_name = 'qwen_image_edit_2511_bf16.safetensors'; });
  refuse('Q', 'A', /text encoder is/, g => { g['2'].inputs.clip_name = 'qwen_2.5_vl_7b.safetensors'; });
  refuse('Q', 'A', /VAE is/, g => { g['3'].inputs.vae_name = 'other_vae.safetensors'; });
  refuse('Q', 'A', /positive prompt differs/, g => { g['7'].inputs.prompt += ' Add a hat.'; });
  refuse('Q', 'A', /positive prompt differs/, g => { g['7'].inputs.prompt = g['7'].inputs.prompt.replace('ribbed collar and ribbed hem', 'ribbed turtleneck'); });
  refuse('Q', 'A', /negative prompt differs/, g => { g['8'].inputs.prompt = ''; });           // the template's empty string is not the approved single space
  refuse('Q', 'A', /LoRA node present/, g => { g['20'] = {class_type: 'LoraLoaderModelOnly', inputs: {lora_name: 'Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors', strength_model: 1, model: ['1', 0]}}; });
  refuse('Q', 'A', /latent size is 1024x1024/, g => { g['9'].inputs.height = 1024; });
  refuse('Q', 'A', /batch size is 2/, g => { g['9'].inputs.batch_size = 2; });
  refuse('Q', 'A', /latent size must be set explicitly/, g => { g['9'] = {class_type: 'VAEEncode', inputs: {pixels: ['4', 0], vae: ['3', 0]}}; });   // the template's image-derived latent
  refuse('Q', 'A', /exactly one KSampler/, g => { g['30'] = structuredClone(g['10']); });
  refuse('Q', 'A', /ModelSamplingAuraFlow/, g => { delete g['5']; g['6'].inputs.model = ['1', 0]; });
  refuse('Q', 'A', /must not load a checkpoint/, g => { g['31'] = {class_type: 'CheckpointLoaderSimple', inputs: {ckpt_name: 'sd_xl_base_1.0.safetensors'}}; });
  refuse('S', 'C', /checkpoint is/, g => { g['1'].inputs.ckpt_name = 'sd_xl_base_1.0_0.9vae.safetensors'; });
  refuse('S', 'C', /IP-Adapter weight is 1/, g => { g['4'].inputs.weight = 1; });
  refuse('S', 'C', /weight type/, g => { g['4'].inputs.weight_type = 'style transfer'; });
  refuse('S', 'C', /IP-Adapter range/, g => { g['4'].inputs.end_at = 0.8; });
  refuse('S', 'C', /latent size is 1024x1536/, g => { g['7'].inputs.width = 1024; g['7'].inputs.height = 1536; });
  refuse('S', 'C', /resize is bicubic/, g => { g['10'].inputs.upscale_method = 'bicubic'; });
  refuse('S', 'C', /ControlNet node present/, g => { g['21'] = {class_type: 'ControlNetApplyAdvanced', inputs: {strength: 1}}; });
  refuse('S', 'C', /negative prompt differs/, g => { g['6'].inputs.text += ', blurry'; });
  refuse('S', 'C', /steps is/, g => { g['8'].inputs.steps = 40; });
  // wrong pairing and wrong format
  assert.match(checkWorkflow({graph: graph('S', lock, 'C'), workflow: 'S', candidate: 'A', lock}).problems[0], /candidate A does not use workflow S/);
  assert.match(checkWorkflow({graph: {nodes: [], links: []}, workflow: 'Q', candidate: 'A', lock}).problems[0], /not an API-format export/);
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
  assert.deepEqual(fs.readdirSync(TOOLS).sort(), ['build-pod-bundle.mjs', 'check-workflow.mjs', 'collect-outputs.sh', 'compare-sheet.mjs', 'cutout.cjs', 'pod-setup.sh', 'stop-timer.mjs', 'verify-transfer.mjs', 'watchdog.sh']);
  assert.deepEqual(fs.readdirSync(FIX).sort(), ['q.api.template.json', 's.api.template.json']);
  const secret = /rpa_[A-Za-z0-9]{16,}|hf_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(api[_-]?key|secret|password|token)\b\s*[:=]\s*['"][^'"\s]{8,}['"]|AKIA[0-9A-Z]{16}/i;
  for (const f of files) assert.ok(!secret.test(fs.readFileSync(path.join(REPO, f), 'utf8')), `${f} holds no credential`);
  // no run folder, bundle or output was written into the repository by these tests
  for (const d of ['studio/tools/ap84b3/transfers', 'studio/tools/ap84b3/rejected', 'studio/quarantine', 'studio/cutouts']) assert.ok(!fs.existsSync(path.join(REPO, d)));
});
