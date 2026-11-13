// Registry promotion (owner decisions of 2026-11-13). All writes go to TEMPORARY registries and a temporary library
// inside the git-ignored studio-work/studio-*/ area; every test asserts the real registries, stories, artwork and the
// real generated/ library are untouched.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {createStudio} from '../lib/app.mjs';
import {Quarantine} from '../lib/quarantine.mjs';
import {writePromotionsBlock} from '../lib/promotion.mjs';
import {requirementsFor} from '../lib/asset-intel.mjs';
import {loadRegistry} from '../../production/lib/character.mjs';
import {canvas} from '../../production/lib/runtime.mjs';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const REAL_REG = path.join(REPO, 'production/characters/character-01.json');
const REAL_LIBRARY = path.join(REPO, 'bible/concepts/lookdev-richenv/generated');
const sha = b => crypto.createHash('sha256').update(b).digest('hex');
const PROTECTED = ['production/characters/character-01.json', 'production/environments/environments.json', 'production/stories/short-001-v2.story.json',
  'bible/concepts/lookdev-richenv/lookdev-scene-01.png', 'bible/concepts/lookdev-richenv/ap75-pose02-test/character-01_pose-02-worried-phone_skin-only_test.png'];
const snapshot = () => [...PROTECTED.map(f => [f, sha(fs.readFileSync(path.join(REPO, f)))]), ['generated library exists', fs.existsSync(REAL_LIBRARY)]];

let nextPort = 5700 + Math.floor(Math.random() * 250);
let pngCache = {};
// A realistic candidate: approved pose 02 scaled onto the approved 1024x1536 canvas (or an opaque card when opaque=true).
async function candidatePng({opaque = false} = {}) {
  const key = opaque ? 'opaque' : 'good';
  if (pngCache[key]) return pngCache[key];
  const reg = JSON.parse(fs.readFileSync(REAL_REG, 'utf8'));
  const art = await canvas.loadImage(path.join(REPO, reg.poses['02'].file));
  const c = canvas.createCanvas(1024, 1536), x = c.getContext('2d');
  if (opaque) { x.fillStyle = '#ffffff'; x.fillRect(0, 0, 1024, 1536); }
  x.drawImage(art, 200, 80, art.width * 2.2, art.height * 2.2);
  return (pngCache[key] = await c.encode('png'));
}

async function setup() {
  const dir = path.join(REPO, 'studio-work', `studio-test-promo-${crypto.randomBytes(4).toString('hex')}`);
  fs.mkdirSync(path.join(dir, 'characters'), {recursive: true});
  fs.copyFileSync(REAL_REG, path.join(dir, 'characters', 'character-01.json'));       // byte-identical copy
  fs.chmodSync(path.join(dir, 'characters', 'character-01.json'), 0o644);
  fs.copyFileSync(path.join(REPO, 'production/environments/environments.json'), path.join(dir, 'environments.json'));
  fs.chmodSync(path.join(dir, 'environments.json'), 0o644);
  const sources = {charactersDir: path.join(dir, 'characters'), environmentsFile: path.join(dir, 'environments.json')};
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'promo-')), port = nextPort++;
  const s = createStudio({workspace, port, genAdapter: 'fake', command: () => [process.execPath, ['-e', '0']], assetSources: sources, promotionLibrary: path.join(dir, 'library')});
  await s.listen();
  const call = async (p, {method = 'GET', body} = {}) => {
    const res = await fetch(`http://127.0.0.1:${port}${p}`, {method, headers: body !== undefined ? {'Content-Type': 'application/json'} : {}, body: body === undefined ? undefined : JSON.stringify(body)});
    const t = await res.text(); let json = null; try { json = JSON.parse(t); } catch {}
    return {status: res.status, json, text: t};
  };
  const regFile = path.join(dir, 'characters', 'character-01.json');
  return {s, call, dir, workspace, sources, regFile, library: path.join(dir, 'library'), cleanup: async () => { await s.close(); fs.rmSync(dir, {recursive: true, force: true}); }};
}

// A job with one real (non-synthetic) candidate, validated, then approved by a person through the API.
let seq = 0;
async function approvedProposal(env, {assetKey = 'character-01/02', opaque = false, assetType = 'character-pose'} = {}) {
  const {s, call, workspace} = env;
  const t = new Date(Date.UTC(2026, 10, 13, 10, 0, seq++)), p = n => String(n).padStart(2, '0');
  const id = `g-${t.getUTCFullYear()}${p(t.getUTCMonth() + 1)}${p(t.getUTCDate())}-${p(t.getUTCHours())}${p(t.getUTCMinutes())}${p(t.getUTCSeconds())}-${crypto.randomBytes(3).toString('hex')}`;
  const now = new Date().toISOString();
  s.db.prepare(`INSERT INTO gen_jobs (id, asset_type, asset_key, description, status, adapter, initiated_by, created_at, updated_at) VALUES (?, ?, ?, 'test candidate', 'candidate_ready', 'test', 'owner', ?, ?)`)
    .run(id, assetType, assetKey, now, now);
  const buf = await candidatePng({opaque});
  const w = new Quarantine(workspace).write(id, 'candidate-1.png', buf);
  s.db.prepare(`INSERT INTO gen_candidates (job_id, name, sha256, bytes, media_type, width, height, synthetic, provenance_json, created_at) VALUES (?, ?, ?, ?, 'image/png', 1024, 1536, 0, ?, ?)`)
    .run(id, w.name, w.sha256, w.bytes, JSON.stringify({adapter: 'test', synthetic: false}), now);
  assert.equal((await call(`/api/generation/jobs/${id}/validate`, {method: 'POST', body: {}})).status, 201);
  const cand = (await call(`/api/generation/jobs/${id}`)).json.candidates[0];
  const r = await call(`/api/generation/jobs/${id}/reviews`, {method: 'POST', body: {decision: 'approve', candidateId: cand.id, note: 'Looks on-model; approve for promotion test'}});
  assert.equal(r.status, 201, r.text);
  return {jobId: id, proposal: r.json.proposals[0], candidate: cand};
}

test('writePromotionsBlock keeps every existing byte and only appends or replaces the trailing promotions block', () => {
  const text = fs.readFileSync(REAL_REG, 'utf8');
  const one = writePromotionsBlock(text, {'02': {'2': {file: 'x.png'}}});
  const head = text.slice(0, text.lastIndexOf('}')).trimEnd();
  assert.ok(one.startsWith(head), 'original bytes preserved');
  const o = JSON.parse(one); assert.deepEqual(o.poses, JSON.parse(text).poses); assert.equal(o.promotions['02']['2'].file, 'x.png');
  const two = writePromotionsBlock(one, {'02': {'2': {file: 'x.png'}, '3': {file: 'y.png'}}});
  assert.ok(two.startsWith(head)); assert.deepEqual(Object.keys(JSON.parse(two).promotions['02']), ['2', '3']);
  assert.throws(() => writePromotionsBlock('{\n  "promotions": {},\n  "poses": {}\n}\n', {}), /not last/);
});

test('promotion: checks, explicit owner decision, write-once asset, byte-preserving registry edit, backup, audit, never current', async () => {
  const before = snapshot(), env = await setup();
  try {
    const {call, s, regFile, library, workspace, sources} = env;
    const original = fs.readFileSync(regFile, 'utf8');
    const {proposal, jobId} = await approvedProposal(env);
    assert.equal(proposal.version, 2, 'existing pose 02 is v1, so the proposal is v2'); assert.equal(proposal.promotable, true);

    const chk = await call(`/api/generation/proposals/${proposal.id}/promotion-check`);
    assert.equal(chk.status, 200); assert.equal(chk.json.ok, true, JSON.stringify(chk.json.checks.filter(c => c.status !== 'pass')));
    assert.equal(chk.json.plan.asset, 'pose-02_v2.png'); assert.equal(chk.json.current, false); assert.equal(chk.json.approval, 'APPROVED_WORKING_TEST_ASSET');
    assert.ok(chk.json.measured.figureHeight > 1000 && chk.json.measured.feet.x > 0);
    assert.ok(!chk.text.includes('bible/') && !chk.text.includes('studio-work') && !chk.text.includes('_internal'), 'no paths in the check response');

    // Explicit decision required; approval class fixed by the owner decision.
    assert.equal((await call(`/api/generation/proposals/${proposal.id}/promote`, {method: 'POST', body: {note: 'promote'}})).status, 400);
    assert.equal((await call(`/api/generation/proposals/${proposal.id}/promote`, {method: 'POST', body: {note: 'promote', confirm: true, approval: 'APPROVED_WORKING_ASSET'}})).status, 400);
    assert.equal((await call(`/api/generation/proposals/${proposal.id}/promote`, {method: 'POST', body: {note: 'x', confirm: true}})).status, 400);
    assert.equal((await call(`/api/generation/proposals/${proposal.id}/promote`, {method: 'POST', body: {note: 'promote', confirm: true, feet: {x: -1, y: 5}}})).status, 400);

    const r = await call(`/api/generation/proposals/${proposal.id}/promote`, {method: 'POST', body: {note: 'Owner promotes pose 02 v2 as a test asset', confirm: true}});
    assert.equal(r.status, 201, r.text);
    assert.equal(r.json.version, 2); assert.equal(r.json.current, false); assert.equal(r.json.approval, 'APPROVED_WORKING_TEST_ASSET'); assert.equal(r.json.asset, 'pose-02_v2.png');
    assert.ok(!r.text.includes('bible/') && !r.text.includes('studio-work'), 'no paths in the promotion response');

    // Asset: write-once copy with the approved hash.
    const asset = path.join(library, 'character-01', 'pose-02_v2.png');
    assert.equal(sha(fs.readFileSync(asset)), proposal.candidateSha256);
    // Registry: every original byte kept; poses unchanged; new version only under promotions; engine still loads it.
    const after = fs.readFileSync(regFile, 'utf8');
    assert.ok(after.startsWith(original.slice(0, original.lastIndexOf('}')).trimEnd()), 'existing registry bytes unchanged');
    const reg = JSON.parse(after);
    assert.deepEqual(reg.poses, JSON.parse(original).poses, 'current pose entries unchanged');
    const v2 = reg.promotions['02']['2'];
    assert.equal(v2.sha256, proposal.candidateSha256); assert.equal(v2.approval, 'APPROVED_WORKING_TEST_ASSET'); assert.match(v2.status, /NOT CURRENT/);
    assert.equal(v2.width, 1024); assert.equal(v2.height, 1536); assert.equal(v2.source.jobId, jobId); assert.equal(v2.source.proposalId, proposal.id);
    assert.ok(!path.isAbsolute(v2.file) && v2.file.endsWith('library/character-01/pose-02_v2.png'));
    assert.doesNotThrow(() => loadRegistry(regFile), 'the production engine still accepts the registry');
    assert.equal(requirementsFor('short-001-v2.story.json', sources).summary.available, 5, 'stories keep using the current versions');
    // Backup of the previous registry in the studio workspace (outside the repository).
    const backups = fs.readdirSync(path.join(workspace, 'registry-backups'));
    assert.equal(backups.length, 1); assert.equal(fs.readFileSync(path.join(workspace, 'registry-backups', backups[0]), 'utf8'), original);
    // Audit: append-only; proposal marked promoted; job detail lists it; cannot promote twice.
    assert.throws(() => s.db.prepare(`UPDATE gen_promotions SET note = 'x'`).run(), /append-only/);
    assert.throws(() => s.db.prepare('DELETE FROM gen_promotions').run(), /append-only/);
    const job = (await call(`/api/generation/jobs/${jobId}`)).json;
    assert.equal(job.proposals[0].status, 'promoted'); assert.equal(job.promotions.length, 1); assert.equal(job.promotions[0].current, false);
    const again = await call(`/api/generation/proposals/${proposal.id}/promote`, {method: 'POST', body: {note: 'again', confirm: true}});
    assert.equal(again.status, 409); assert.ok(again.json.details.checks.some(c => c.id === 'not-promoted-yet' && c.status === 'fail'));
    assert.equal((await call('/api/generation/promotions')).json.length, 1);

    // A second take on pose 02 is proposed as v3 (promoted versions count) and keeps every earlier byte.
    const second = await approvedProposal(env);
    assert.equal(second.proposal.version, 3);
    assert.equal((await call(`/api/generation/proposals/${second.proposal.id}/promote`, {method: 'POST', body: {note: 'Second take as v3', confirm: true, feet: {x: 400, y: 1300}, figureHeight: 1200}})).status, 201);
    const reg3 = JSON.parse(fs.readFileSync(regFile, 'utf8'));
    assert.deepEqual(Object.keys(reg3.promotions['02']), ['2', '3']); assert.deepEqual(reg3.promotions['02']['3'].feet, {x: 400, y: 1300});
    assert.deepEqual(reg3.promotions['02']['2'], v2, 'earlier promoted version unchanged');
    assert.ok(fs.readFileSync(regFile, 'utf8').startsWith(original.slice(0, original.lastIndexOf('}')).trimEnd()));
    assert.doesNotThrow(() => loadRegistry(regFile));
  } finally { await env.cleanup(); }
  assert.deepEqual(snapshot(), before, 'real registries, stories, artwork and the real generated library untouched');
});

test('promotion refuses: synthetic fixtures, failed validation, changed candidates, taken versions, existing files, environments', async () => {
  const before = snapshot(), env = await setup();
  try {
    const {call, s, regFile, library, workspace} = env;
    const original = fs.readFileSync(regFile, 'utf8');
    const failing = id => async (proposalId) => {
      const c = (await call(`/api/generation/proposals/${proposalId}/promotion-check`)).json;
      assert.equal(c.ok, false); const f = c.checks.find(x => x.id === id); assert.equal(f.status, 'fail', `${id}: ${JSON.stringify(c.checks)}`);
      const r = await call(`/api/generation/proposals/${proposalId}/promote`, {method: 'POST', body: {note: 'should be refused', confirm: true}});
      assert.equal(r.status, 409); assert.ok(r.json.details.checks.some(x => x.id === id && x.status === 'fail'));
    };
    // Synthetic fixture from the fake adapter: approved, but never promotable.
    const fake = (await call('/api/generation/jobs', {method: 'POST', body: {assetType: 'character-pose', assetKey: 'character-01/07', description: 'synthetic'}})).json.id;
    let j; for (let i = 0; i < 200; i++) { j = (await call(`/api/generation/jobs/${fake}`)).json; if (j.status === 'candidate_ready') break; await new Promise(r => setTimeout(r, 50)); }
    const fr = await call(`/api/generation/jobs/${fake}/reviews`, {method: 'POST', body: {decision: 'approve', candidateId: j.candidates[0].id, note: 'approve fixture'}});
    await failing('promotable')(fr.json.proposals[0].id);
    await failing('synthetic')(fr.json.proposals[0].id);
    // Opaque candidate: latest validation is "fail".
    await failing('validation')((await approvedProposal(env, {opaque: true})).proposal.id);
    // Candidate file changed after approval.
    const changed = await approvedProposal(env);
    fs.appendFileSync(path.join(workspace, 'quarantine', changed.jobId, 'candidate-1.png'), Buffer.from([0]));
    await failing('candidate-file')(changed.proposal.id);
    // Version already taken in the registry (someone recorded it meanwhile).
    const taken = await approvedProposal(env);
    fs.writeFileSync(regFile, writePromotionsBlock(original, {'02': {[String(taken.proposal.version)]: {file: 'elsewhere.png'}}}));
    await failing('version-free')(taken.proposal.id);
    fs.writeFileSync(regFile, original);
    // Destination file already exists (write-once library).
    const exists = await approvedProposal(env);
    fs.mkdirSync(path.join(library, 'character-01'), {recursive: true});
    fs.writeFileSync(path.join(library, 'character-01', `pose-02_v${exists.proposal.version}.png`), 'occupied');
    await failing('destination')(exists.proposal.id);
    // Environments are not covered by the owner decisions yet.
    await failing('asset-type')((await approvedProposal(env, {assetType: 'environment', assetKey: 'living-room-night'})).proposal.id);
    assert.equal(fs.readFileSync(regFile, 'utf8'), original, 'refused promotions never touch the registry');
    assert.equal(s.db.prepare('SELECT COUNT(*) AS n FROM gen_promotions').get().n, 0);
    assert.ok(!fs.existsSync(path.join(workspace, 'registry-backups')));
  } finally { await env.cleanup(); }
  assert.deepEqual(snapshot(), before);
});
