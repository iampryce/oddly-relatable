// AP-84B1 generation foundation: jobs, adapters (none/fake), quarantine, review, registry proposals, recovery.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {createStudio} from '../lib/app.mjs';
import {Quarantine} from '../lib/quarantine.mjs';
import {fakeAdapter, noneAdapter} from '../lib/gen-adapters.mjs';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const sha = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const protectedFiles = () => ['production/characters/character-01.json', 'production/environments/environments.json', 'production/stories/short-001-v2.story.json',
  'bible/concepts/lookdev-richenv/lookdev-scene-01.png', 'bible/concepts/lookdev-richenv/ap75-pose02-test/character-01_pose-02-worried-phone_skin-only_test.png']
  .map(f => [f, sha(path.join(REPO, f))]);
// Stays below 5060/5061: fetch refuses those (blocked SIP ports), which made this test fail intermittently.
let nextPort = 4910 + Math.floor(Math.random() * 120);

async function start({adapter = 'fake', workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'gen-'))} = {}) {
  const port = nextPort++;
  const s = createStudio({workspace, port, genAdapter: adapter, command: () => [process.execPath, ['-e', '0']]});
  await s.listen();
  const base = `http://127.0.0.1:${port}`;
  const call = async (p, {method = 'GET', body} = {}) => {
    const res = await fetch(base + p, {method, headers: body !== undefined ? {'Content-Type': 'application/json'} : {}, body: body === undefined ? undefined : JSON.stringify(body)});
    const t = await res.text(); let json = null; try { json = JSON.parse(t); } catch {}
    return {status: res.status, json, text: t, headers: res.headers};
  };
  return {s, call, workspace};
}
async function until(call, id, statuses, ms = 8000) {
  const t = Date.now();
  while (Date.now() - t < ms) { const j = (await call(`/api/generation/jobs/${id}`)).json; if (statuses.includes(j.status)) return j; await new Promise(r => setTimeout(r, 50)); }
  throw new Error(`job ${id} did not reach ${statuses}`);
}
const newJob = (call, extra = {}) => call('/api/generation/jobs', {method: 'POST', body: {assetType: 'character-pose', assetKey: 'character-01/pose-07', description: 'Test request: surprised pose', ...extra}});

test('none adapter: jobs persist but fail clearly, and nothing is generated', async () => {
  const {s, call, workspace} = await start({adapter: 'none'});
  try {
    const cfg = (await call('/api/generation')).json;
    assert.equal(cfg.adapter, 'none'); assert.equal(cfg.available, false); assert.match(cfg.reason, /No generation worker is configured/);
    const r = await newJob(call);
    assert.equal(r.status, 202); assert.equal(r.json.status, 'queued'); assert.equal(r.json.adapter, 'none');
    const j = await until(call, r.json.id, ['failed']);
    assert.match(j.error, /No generation worker is configured/); assert.equal(j.candidates.length, 0); assert.equal(j.retryable, false);
    assert.ok(!fs.existsSync(path.join(workspace, 'quarantine', j.id)), 'no quarantine output');
    await assert.rejects(noneAdapter.generate({}), /Nothing was generated/);
  } finally { await s.close(); }
});

test('fake adapter: queued -> running -> candidate_ready with a labelled, deterministic synthetic fixture in quarantine', async () => {
  const before = protectedFiles();
  const {s, call, workspace} = await start();
  try {
    const a = await until(call, (await newJob(call)).json.id, ['candidate_ready']);
    const b = await until(call, (await newJob(call)).json.id, ['candidate_ready']);
    const [ca] = a.candidates, [cb] = b.candidates;
    assert.equal(ca.sha256, cb.sha256, 'identical requests give byte-identical fixtures');
    assert.match(ca.name, /^synthetic-test-fixture-[0-9a-f]{12}\.png$/);
    assert.equal(ca.synthetic, true); assert.equal(ca.provenance.synthetic, true); assert.equal(ca.provenance.jobId, a.id);
    assert.equal(ca.provenance.adapter, 'fake'); assert.equal(ca.provenance.request.assetKey, 'character-01/pose-07');
    const file = path.join(workspace, 'quarantine', a.id, ca.name);
    assert.ok(fs.existsSync(file)); assert.equal(sha(file), ca.sha256, 'recorded SHA-256 matches the file');
    const media = await call(`/media/generation/${a.id}/${ca.name}`);
    assert.equal(media.status, 200); assert.equal(media.headers.get('content-type'), 'image/png');
    const direct = await fakeAdapter.generate({assetType: 'character-pose', assetKey: 'character-01/pose-07', description: 'Test request: surprised pose'}, {attempt: 2});
    assert.notEqual(crypto.createHash('sha256').update(direct[0].buffer).digest('hex'), ca.sha256, 'a new attempt gives a different fixture');
    assert.deepEqual(protectedFiles(), before, 'registries, stories and artwork untouched');
  } finally { await s.close(); }
});

test('job input is validated', async () => {
  const {s, call} = await start();
  try {
    assert.equal((await newJob(call, {assetType: 'video'})).status, 400);
    assert.equal((await newJob(call, {assetKey: '../../etc/passwd'})).status, 400);
    assert.equal((await newJob(call, {assetKey: 'character-99/pose-01'})).status, 422);
    assert.equal((await newJob(call, {assetType: 'environment', assetKey: 'Living Room'})).status, 400);
    assert.equal((await newJob(call, {description: 'x'})).status, 400);
    assert.equal((await newJob(call, {episodeId: 'nope'})).status, 404);
    assert.equal((await newJob(call, {episodeId: 'short-001-v2'})).status, 202);
  } finally { await s.close(); }
});

test('quarantine: invalid names, traversal, oversize and overwrites are refused; storage stays outside the repo', () => {
  const ws = fs.mkdtempSync(path.join(os.tmpdir(), 'quar-')), q = new Quarantine(ws), job = 'g-20260101-000000-abcdef', png = Buffer.from([1, 2, 3]);
  for (const bad of ['../x.png', 'a/b.png', 'X.PNG', '.png', 'x.exe', 'x.png\0.txt', '..\\x.png', 'x'.repeat(90) + '.png'])
    assert.throws(() => q.write(job, bad, png), /invalid candidate file name/, bad);
  assert.throws(() => q.write('../../etc', 'x.png', png), /invalid generation job id/);
  assert.throws(() => q.write(job, 'big.png', Buffer.alloc(20 * 1024 * 1024 + 1)), /candidate size/);
  const w = q.write(job, 'ok.png', png);
  assert.equal(w.sha256, crypto.createHash('sha256').update(png).digest('hex'));
  assert.throws(() => q.write(job, 'ok.png', Buffer.from([9])), /EEXIST/, 'write-once');
  assert.equal(q.resolve(job, '../../studio.db'), null);
  assert.ok(!path.relative(REPO, q.root).startsWith('production') && !path.relative(REPO, q.root).startsWith('bible'));
  assert.throws(() => new Quarantine(path.join(REPO, 'production', 'x')), /must not live inside/);
});

test('review: approve creates a versioned, non-promotable proposal for synthetic fixtures; reject; regenerate; history is append-only', async () => {
  const before = protectedFiles();
  const {s, call} = await start();
  try {
    const j = await until(call, (await newJob(call, {assetKey: 'character-01/02', description: 'New version of existing pose 02'})).json.id, ['candidate_ready']);
    const post = body => call(`/api/generation/jobs/${j.id}/reviews`, {method: 'POST', body});
    assert.equal((await post({decision: 'publish', note: 'xyz'})).status, 400);
    assert.equal((await post({decision: 'approve', note: 'xyz'})).status, 400, 'approve needs a candidate');
    assert.equal((await post({decision: 'approve', candidateId: j.candidates[0].id})).status, 400, 'note required');
    const ok = await post({decision: 'approve', candidateId: j.candidates[0].id, note: 'Pipeline test approval'});
    assert.equal(ok.status, 201); assert.equal(ok.json.status, 'approved');
    const [p] = ok.json.proposals;
    assert.equal(p.registry, 'characters/character-01'); assert.equal(p.entryKey, '02');
    assert.equal(p.version, 2, 'existing pose 02 counts as v1, so the proposal is v2 (never a replacement)');
    assert.equal(p.promotable, false); assert.match(p.reason, /synthetic test fixture/); assert.equal(p.candidateSha256, j.candidates[0].sha256);
    assert.equal((await post({decision: 'reject', note: 'again'})).status, 409, 'an approved job cannot be reviewed again');
    // Second approval of the same entry gets the next version.
    const j2 = await until(call, (await newJob(call, {assetKey: 'character-01/02', description: 'Another take on pose 02'})).json.id, ['candidate_ready']);
    const ok2 = await call(`/api/generation/jobs/${j2.id}/reviews`, {method: 'POST', body: {decision: 'approve', candidateId: j2.candidates[0].id, note: 'Second test approval'}});
    assert.equal(ok2.json.proposals[0].version, 3);
    // Reject and regenerate.
    const j3 = await until(call, (await newJob(call)).json.id, ['candidate_ready']);
    const rj = await call(`/api/generation/jobs/${j3.id}/reviews`, {method: 'POST', body: {decision: 'regenerate', note: 'Wrong expression'}});
    assert.equal(rj.json.status, 'rejected'); assert.ok(rj.json.regeneratedJobId);
    const child = await until(call, rj.json.regeneratedJobId, ['candidate_ready']);
    assert.equal(child.attempt, 2); assert.equal(child.parentJobId, j3.id);
    assert.notEqual(child.candidates[0].sha256, j3.candidates[0].sha256);
    const j4 = await until(call, (await newJob(call)).json.id, ['candidate_ready']);
    assert.equal((await call(`/api/generation/jobs/${j4.id}/reviews`, {method: 'POST', body: {decision: 'reject', note: 'Not needed'}})).json.status, 'rejected');
    // Append-only at the database level.
    assert.throws(() => s.db.prepare(`UPDATE gen_reviews SET note = 'changed'`).run(), /append-only/);
    assert.throws(() => s.db.prepare('DELETE FROM gen_reviews').run(), /append-only/);
    assert.throws(() => s.db.prepare('DELETE FROM gen_registry_proposals').run(), /append-only/);
    assert.throws(() => s.db.prepare(`UPDATE gen_candidates SET sha256 = 'x'`).run(), /immutable/);
    assert.deepEqual(protectedFiles(), before, 'approval never wrote to registries or artwork');
  } finally { await s.close(); }
});

test('approval refuses a candidate whose quarantined file changed after it was recorded', async () => {
  const {s, call, workspace} = await start();
  try {
    const j = await until(call, (await newJob(call)).json.id, ['candidate_ready']);
    fs.appendFileSync(path.join(workspace, 'quarantine', j.id, j.candidates[0].name), Buffer.from([0]));
    const r = await call(`/api/generation/jobs/${j.id}/reviews`, {method: 'POST', body: {decision: 'approve', candidateId: j.candidates[0].id, note: 'Should fail'}});
    assert.equal(r.status, 409); assert.match(r.json.error, /missing or changed/);
  } finally { await s.close(); }
});

test('cancel and status rules', async () => {
  const {s, call} = await start({adapter: 'none'});
  try {
    s.gen.stop();                                              // keep the job queued
    const j = (await newJob(call)).json;
    assert.equal((await call(`/api/generation/jobs/${j.id}/cancel`, {method: 'POST', body: {}})).json.status, 'cancelled');
    assert.equal((await call(`/api/generation/jobs/${j.id}/cancel`, {method: 'POST', body: {}})).status, 409);
    assert.equal((await call(`/api/generation/jobs/${j.id}/reviews`, {method: 'POST', body: {decision: 'reject', note: 'xyz'}})).status, 409);
    assert.equal((await call('/api/generation/jobs/g-bad')).status, 400, 'malformed job id');
    assert.equal((await call('/media/generation/g-20260101-000000-abcdef/..%2F..%2Fstudio.db')).status, 404);
    assert.equal((await call('/media/generation/not-a-job/x.png')).status, 400);
  } finally { await s.close(); }
});

test('restart recovery: running jobs become failed (interrupted, retryable); queued jobs resume; history persists', async () => {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'gen-restart-'));
  let {s, call} = await start({workspace});
  const done = await until(call, (await newJob(call)).json.id, ['candidate_ready']);
  s.gen.stop();
  const q = (await newJob(call)).json;                        // stays queued (runner stopped)
  const stuck = 'g-20260101-000000-aaaaaa';
  s.db.prepare(`INSERT INTO gen_jobs (id, asset_type, asset_key, description, status, adapter, initiated_by, created_at, updated_at, started_at)
    VALUES (?, 'environment', 'living-room-night', 'stuck job', 'running', 'fake', 'owner', '2026-01-01', '2026-01-01', '2026-01-01')`).run(stuck);
  await s.close();
  ({s, call} = await start({workspace}));
  try {
    const st = (await call(`/api/generation/jobs/${stuck}`)).json;
    assert.equal(st.status, 'failed'); assert.match(st.error, /interrupted/); assert.equal(st.retryable, true);
    assert.equal((await until(call, q.id, ['candidate_ready'])).status, 'candidate_ready', 'queued job resumed after restart');
    assert.equal((await call(`/api/generation/jobs/${done.id}`)).json.candidates[0].sha256, done.candidates[0].sha256, 'history persisted');
    // existing studio features still work alongside generation
    assert.equal((await call('/api/episodes')).json[0].id, 'short-001-v2');
  } finally { await s.close(); }
});
