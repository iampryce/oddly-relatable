// Studio API, job runner, storage safety, reviews and restart recovery. Uses a fake production engine
// (tests/fixtures/fake-produce.mjs) so jobs finish in well under a second; the real engine is exercised manually.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import http from 'node:http';
import {fileURLToPath} from 'node:url';
import {createStudio} from '../lib/app.mjs';
import {isAlive, killTree} from '../lib/jobs.mjs';
import {logEvent} from '../lib/db.mjs';

const FAKE = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures', 'fake-produce.mjs');
let mode = 'ok';
const command = (story, out) => [process.execPath, [FAKE, story, out, mode]];
let nextPort = 4600 + Math.floor(Math.random() * 300);

async function start(workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'studio-'))) {
  const port = nextPort++;
  const s = createStudio({workspace, port, command, pollMs: 100});
  await s.listen();
  const base = `http://127.0.0.1:${port}`;
  const call = async (p, {method = 'GET', body, headers = {}} = {}) => {
    const res = await fetch(base + p, {method, headers: {...(body !== undefined ? {'Content-Type': 'application/json'} : {}), ...headers}, body: body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body)});
    const text = await res.text();
    let json; try { json = JSON.parse(text); } catch { json = null; }
    return {status: res.status, json, text, headers: res.headers};
  };
  return {s, call, workspace, base};
}
async function waitFor(call, runId, statuses, ms = 8000) {
  const t = Date.now();
  while (Date.now() - t < ms) { const r = (await call(`/api/runs/${runId}`)).json; if (statuses.includes(r.status)) return r; await new Promise(r => setTimeout(r, 80)); }
  throw new Error(`run ${runId} did not reach ${statuses}`);
}

test('first start registers Short 001; listing and detail return story info', async () => {
  const {s, call} = await start();
  try {
    const eps = (await call('/api/episodes')).json;
    assert.equal(eps.length, 1);
    assert.equal(eps[0].id, 'short-001-v2'); assert.equal(eps[0].duration, 54); assert.equal(eps[0].story.valid, true);
    const d = (await call('/api/episodes/short-001-v2')).json;
    assert.equal(d.title, 'We Need to Talk'); assert.deepEqual(d.history, []);
    assert.equal((await call('/api/episodes/nope')).status, 404);
    assert.equal((await call('/api/stories')).json[0].file, 'short-001-v2.story.json');
  } finally { await s.close(); }
});

test('episode creation is validated and never touches the story file', async () => {
  const {s, call} = await start();
  try {
    const storyFile = path.join(fileURLToPath(new URL('../../production/stories/short-001-v2.story.json', import.meta.url)));
    const before = fs.readFileSync(storyFile);
    assert.equal((await call('/api/episodes', {method: 'POST', body: {storyFile: '../../etc/passwd'}})).status, 400);
    assert.equal((await call('/api/episodes', {method: 'POST', body: {storyFile: 'missing.story.json'}})).status, 404);
    assert.equal((await call('/api/episodes', {method: 'POST', body: {storyFile: 'short-001-v2.story.json'}})).status, 409, 'duplicate id');
    assert.equal((await call('/api/episodes', {method: 'POST', body: {storyFile: 'short-001-v2.story.json', id: 'Bad ID'}})).status, 400);
    const ok = await call('/api/episodes', {method: 'POST', body: {storyFile: 'short-001-v2.story.json', id: 'short-001-alt', title: 'Alt cut', note: 'test'}});
    assert.equal(ok.status, 201); assert.equal(ok.json.title, 'Alt cut'); assert.equal(ok.json.storyFile, 'short-001-v2.story.json');
    assert.deepEqual(fs.readFileSync(storyFile), before);
  } finally { await s.close(); }
});

test('a run is queued immediately, runs in the background, captures stages and logs, and serves its outputs', async () => {
  const {s, call} = await start();
  try {
    mode = 'ok';
    const t = Date.now(), res = await call('/api/episodes/short-001-v2/runs', {method: 'POST', body: {}});
    assert.equal(res.status, 202); assert.ok(Date.now() - t < 1500, 'request returns without waiting for production');
    assert.equal(res.json.status, 'queued');
    assert.equal((await call('/api/episodes/short-001-v2/runs', {method: 'POST', body: {}})).status, 409, 'no duplicate active run');
    const r = await waitFor(call, res.json.id, ['produced']);
    assert.equal(r.exitCode, 0); assert.ok(r.stages.some(x => x.stage === 'render' && x.status === 'done'));
    assert.equal(r.qa.status, 'pass');
    assert.equal(r.review.state, 'awaiting-review', 'QA pass never approves');
    const log = (await call(`/api/runs/${r.id}/log`)).json;
    assert.match(log.text, /fake produce short-001-v2\.story\.json/);
    const partial = await call(`/media/runs/${r.id}/render/fake.mp4`, {headers: {Range: 'bytes=0-9'}});
    assert.equal(partial.status, 206); assert.equal(partial.text, '0123456789'); assert.equal(partial.headers.get('content-type'), 'video/mp4');
    assert.equal((await call(`/media/runs/${r.id}/render/fake.mp4`)).text.length, 25);
    assert.ok(r.artifacts.some(a => a.key === 'storyboard/frames/01-t0.70.png'));
  } finally { await s.close(); }
});

test('failed and QA-failed runs are recorded with their reason', async () => {
  const {s, call} = await start();
  try {
    mode = 'crash';
    const a = (await call('/api/episodes/short-001-v2/runs', {method: 'POST', body: {}})).json;
    const fa = await waitFor(call, a.id, ['failed']);
    assert.equal(fa.exitCode, 1); assert.match(fa.error, /exited with code 1/);
    assert.match((await call(`/api/runs/${a.id}/log`)).json.text, /simulated engine failure/);
    mode = 'qa-fail';
    const b = (await call('/api/episodes/short-001-v2/runs', {method: 'POST', body: {}})).json;
    const qb = await waitFor(call, b.id, ['qa-failed']);
    assert.equal(qb.exitCode, 2); assert.equal(qb.qa.status, 'fail');
    const o = (await call('/api/overview')).json;
    assert.equal(o.failed, 2); assert.equal(o.runs, 2);
  } finally { await s.close(); mode = 'ok'; }
});

test('reviews: validated, audited, separate from QA, only for finished runs', async () => {
  const {s, call} = await start();
  try {
    mode = 'ok';
    const run = await waitFor(call, (await call('/api/episodes/short-001-v2/runs', {method: 'POST', body: {}})).json.id, ['produced']);
    const post = body => call(`/api/runs/${run.id}/reviews`, {method: 'POST', body});
    assert.equal((await post({decision: 'publish', note: 'go'})).status, 400);
    assert.equal((await post({decision: 'approved-next-step'})).status, 400, 'note required');
    assert.equal((await post({decision: 'approved-next-step', note: 'x'})).status, 400, 'note too short');
    const r1 = await post({decision: 'changes-requested', note: 'Close-ups too soft.'});
    assert.equal(r1.status, 201); assert.equal(r1.json.review.state, 'changes-requested'); assert.equal(r1.json.status, 'produced', 'review never changes the run status');
    const r2 = await post({decision: 'approved-next-step', note: 'Fixed in the next pass.', reviewer: 'owner'});
    assert.deepEqual(r2.json.reviews.map(v => v.decision), ['changes-requested', 'approved-next-step']);
    const ep = (await call('/api/episodes/short-001-v2')).json;
    assert.equal(ep.reviews.length, 2); assert.equal(ep.reviews[0].runId, run.id);
    mode = 'crash';
    const failed = await waitFor(call, (await call('/api/episodes/short-001-v2/runs', {method: 'POST', body: {}})).json.id, ['failed']);
    assert.equal((await call(`/api/runs/${failed.id}/reviews`, {method: 'POST', body: {decision: 'rejected', note: 'nothing to see'}})).status, 409);
  } finally { await s.close(); mode = 'ok'; }
});

test('cancel stops a running production', async () => {
  const {s, call} = await start();
  try {
    mode = 'hang';
    const id = (await call('/api/episodes/short-001-v2/runs', {method: 'POST', body: {}})).json.id;
    await waitFor(call, id, ['running']);
    assert.equal((await call(`/api/runs/${id}/cancel`, {method: 'POST', body: {}})).status, 200);
    const r = await waitFor(call, id, ['cancelled']);
    assert.ok(r.finishedAt);
  } finally { await s.close(); mode = 'ok'; }
});

test('restart recovery: unfinished runs become interrupted, finished ones are adopted, live ones are watched, queued ones resume', async () => {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'studio-restart-'));
  let {s, call} = await start(workspace);
  mode = 'hang';
  const live = (await call('/api/episodes/short-001-v2/runs', {method: 'POST', body: {}})).json.id;
  await waitFor(call, live, ['running']);
  // Two more runs left "running" with a dead process: one whose run file says produced, one that never finished.
  const dead = spawnSync(process.execPath, ['-e', '0']).pid;
  const db = s.db, insert = (id, status) => db.prepare(`INSERT INTO episodes (id, title, story_file, story_sha256, created_at) VALUES (?, ?, 'short-001-v2.story.json', 'x', '2026-01-01') ON CONFLICT DO NOTHING`).run(`ep-${id.slice(-6)}`, 't') &&
    db.prepare(`INSERT INTO runs (id, episode_id, status, story_file, story_sha256, pid, created_at, started_at) VALUES (?, ?, ?, 'short-001-v2.story.json', 'x', ?, '2026-01-01', '2026-01-01')`).run(id, `ep-${id.slice(-6)}`, status, dead);
  const doneId = 'r-20260101-000000-aaaaaa', lostId = 'r-20260101-000000-bbbbbb', queuedId = 'r-20260101-000000-cccccc';
  insert(doneId, 'running'); insert(lostId, 'running');
  fs.mkdirSync(path.join(workspace, 'runs', doneId), {recursive: true});
  fs.writeFileSync(path.join(workspace, 'runs', doneId, 'production-run.json'), JSON.stringify({status: 'produced', stages: [{stage: 'qa', status: 'done'}]}));
  fs.mkdirSync(path.join(workspace, 'runs', lostId), {recursive: true});
  fs.writeFileSync(path.join(workspace, 'runs', lostId, 'production-run.json'), JSON.stringify({status: 'running', stages: [{stage: 'render', status: 'running'}]}));
  logEvent(db, 'test', 'seeded');
  const livePid = db.prepare('SELECT pid FROM runs WHERE id = ?').get(live).pid;
  await s.close();                                            // server stops; the live production keeps running
  assert.ok(isAlive(livePid), 'production survives a server stop');
  mode = 'ok';
  ({s, call} = await start(workspace));                       // restart on the same workspace (recover() runs in listen)
  try {
    assert.equal((await call(`/api/runs/${doneId}`)).json.status, 'produced', 'finished while the server was down: adopted');
    const lost = (await call(`/api/runs/${lostId}`)).json;
    assert.equal(lost.status, 'interrupted'); assert.match(lost.error, /stopped before finishing/);
    assert.equal((await call(`/api/runs/${live}`)).json.status, 'running', 'still-alive process is watched, not marked done');
    killTree(livePid);
    const after = await waitFor(call, live, ['interrupted', 'failed', 'cancelled'], 10000);
    assert.equal(after.status, 'interrupted', 'a killed run that never finished is never reported as successful');
    // queued runs resume after restart
    s.db.prepare(`INSERT INTO runs (id, episode_id, status, story_file, story_sha256, created_at) VALUES (?, 'short-001-v2', 'queued', 'short-001-v2.story.json', 'x', '2026-01-02')`).run(queuedId);
    s.jobs.kick();
    assert.equal((await waitFor(call, queuedId, ['produced'])).status, 'produced');
    assert.ok((await call('/api/overview')).json.events.length >= 3, 'activity history persisted');
  } finally { await s.close(); }
});

test('HTTP safety: host and origin checks, content type, body limit, whitelisted media keys, no paths or env exposed', async () => {
  const {s, call, workspace, base} = await start();
  try {
    mode = 'ok';
    const id = (await waitFor(call, (await call('/api/episodes/short-001-v2/runs', {method: 'POST', body: {}})).json.id, ['produced'])).id;
    // fetch() cannot set Host, so send this one with node:http
    const hostStatus = await new Promise((resolve, reject) => { const req = http.request({host: '127.0.0.1', port: Number(new URL(base).port), path: '/api/health', headers: {Host: 'evil.example'}}, res => { res.resume(); resolve(res.statusCode); }); req.on('error', reject); req.end(); });
    assert.equal(hostStatus, 421);
    assert.equal((await call('/api/episodes/short-001-v2/runs', {method: 'POST', body: {}, headers: {Origin: 'http://evil.example'}})).status, 403);
    assert.equal((await call('/api/episodes/short-001-v2/runs', {method: 'POST', body: 'x', headers: {'Content-Type': 'text/plain'}})).status, 415);
    assert.equal((await call('/api/episodes', {method: 'POST', body: {storyFile: 'a'.repeat(20000)}})).status, 413);
    for (const bad of ['../studio.db', '..%2F..%2Fstudio.db', 'project/project.json', 'render/../../studio.db', 'production-run.json/../../x'])
      assert.ok([400, 404].includes((await call(`/media/runs/${id}/${bad}`)).status), bad);
    assert.equal((await call('/media/runs/not-a-run/render/fake.mp4')).status, 400);
    const health = (await call('/api/health')).text;
    assert.ok(!health.includes(workspace) && !/FFMPEG=|PATH|\\Users\\/.test(health));
    assert.equal((await call('/api/health', {method: 'DELETE'})).status, 405);
    assert.equal((await call('/')).headers.get('content-security-policy').includes("script-src 'self'"), true);
  } finally { await s.close(); }
});
