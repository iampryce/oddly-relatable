// AP-84B2: story asset requirements, immutable reference packs, candidate validation, studio API.
// Every test checks that registries, stories and artwork are byte-identical afterwards.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {createStudio} from '../lib/app.mjs';
import {requirementsFor, analyseStory, buildReferencePack, verifyPack, validateCandidate, referencesForAsset, publicPackItem, ensureFeatures} from '../lib/asset-intel.mjs';
import {canvas} from '../../production/lib/runtime.mjs';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const STORY = 'short-001-v2.story.json';
const sha = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const readJson = f => JSON.parse(fs.readFileSync(path.join(REPO, f), 'utf8'));
// Everything AP-84B2 must never modify: registries, the story, canon and every registered pose / environment file.
const PROTECTED = (() => {
  const reg = readJson('production/characters/character-01.json'), env = readJson('production/environments/environments.json');
  return ['production/characters/character-01.json', 'production/environments/environments.json', `production/stories/${STORY}`,
    'bible/concepts/lookdev-richenv/lookdev-scene-01.png', 'bible/concepts/lookdev-richenv/production-candidates/corrected/candidate-04_corrected-v3.png',
    ...Object.values(reg.poses).map(p => p.file), ...Object.values(env.environments).map(e => e.file)];
})();
const snapshot = () => PROTECTED.map(f => [f, sha(path.join(REPO, f))]);

// Temporary registries live in the git-ignored studio-work/studio-*/ area (inside the repository, as the
// analyser only accepts repository files), never in production/.
function tempSources() {
  const dir = path.join(REPO, 'studio-work', `studio-test-intel-${crypto.randomBytes(4).toString('hex')}`);
  fs.mkdirSync(path.join(dir, 'characters'), {recursive: true});
  return {dir, charactersDir: path.join(dir, 'characters'), environmentsFile: path.join(dir, 'environments.json'), canonFile: path.join(dir, 'canon.json'),
    cleanup: () => fs.rmSync(dir, {recursive: true, force: true})};
}
const writeJson = (f, v) => fs.writeFileSync(f, JSON.stringify(v, null, 2));

async function png(file, W, H, draw) {
  const c = canvas.createCanvas(W, H), ctx = c.getContext('2d'); draw(ctx);
  fs.writeFileSync(file, await c.encode('png'));
  return file;
}

let nextPort = 5300 + Math.floor(Math.random() * 300);
async function start(opts = {}) {
  const port = nextPort++, workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'intel-'));
  const s = createStudio({workspace, port, genAdapter: 'fake', command: () => [process.execPath, ['-e', '0']], ...opts});
  await s.listen();
  const call = async (p, {method = 'GET', body} = {}) => {
    const res = await fetch(`http://127.0.0.1:${port}${p}`, {method, headers: body !== undefined ? {'Content-Type': 'application/json'} : {}, body: body === undefined ? undefined : JSON.stringify(body)});
    const t = await res.text(); let json = null; try { json = JSON.parse(t); } catch {}
    return {status: res.status, json, text: t};
  };
  return {s, call, workspace};
}
async function until(call, id, statuses, ms = 10000) {
  const t = Date.now();
  while (Date.now() - t < ms) { const j = (await call(`/api/generation/jobs/${id}`)).json; if (statuses.includes(j.status)) return j; await new Promise(r => setTimeout(r, 50)); }
  throw new Error(`job ${id} did not reach ${statuses}`);
}

test('requirements: Short 001 needs character-01 poses 02, 03, 05, 06 and living-room-empty-03, all available', () => {
  const before = snapshot();
  const r = requirementsFor(STORY);
  assert.equal(r.valid, true); assert.equal(r.storyId, readJson(`production/stories/${STORY}`).id);
  assert.equal(r.characters.length, 1); assert.equal(r.characters[0].character, 'character-01'); assert.deepEqual(r.characters[0].castIds, ['him']);
  assert.deepEqual(r.characters[0].poses.map(p => p.pose).sort(), ['02', '03', '05', '06']);
  for (const p of r.characters[0].poses) { assert.equal(p.status, 'available', `pose ${p.pose}`); assert.match(p.sha256, /^[0-9a-f]{64}$/); assert.ok(p.uses >= 1); }
  assert.equal(r.characters[0].poses.find(p => p.pose === '03').approval, 'APPROVED_WORKING_TEST_ASSET');
  assert.deepEqual(r.environments.map(e => [e.id, e.status]), [['living-room-empty-03', 'available']]);
  assert.deepEqual(r.summary, {available: 5, missing: 0, unapproved: 0, unresolved: 0});
  assert.throws(() => requirementsFor('../production/characters/character-01.json'), e => e.status === 400);
  assert.throws(() => requirementsFor('no-such-story.story.json'), e => e.status === 404);
  assert.deepEqual(snapshot(), before);
});

test('requirements: missing, unapproved and unresolved assets are told apart, with reasons', () => {
  const before = snapshot(), src = tempSources();
  try {
    const reg = readJson('production/characters/character-01.json');
    reg.poses['02'].approval = 'PROPOSED';                                  // unapproved
    delete reg.poses['03'];                                                 // missing (not in registry)
    reg.poses['05'].file = 'bible/concepts/does-not-exist.png'; delete reg.poses['05'].sha256; // missing (file absent)
    reg.poses['06'].sha256 = '0'.repeat(64);                                // unresolved (hash mismatch)
    writeJson(path.join(src.charactersDir, 'character-01.json'), reg);
    const env = readJson('production/environments/environments.json');
    env.environments['living-room-empty-03'].status = 'REJECTED';          // unapproved environment
    writeJson(src.environmentsFile, env);
    const story = readJson(`production/stories/${STORY}`);
    const r = analyseStory(story, {sources: src});
    const st = Object.fromEntries(r.characters[0].poses.map(p => [p.pose, p]));
    assert.equal(st['02'].status, 'unapproved'); assert.match(st['02'].reason, /PROPOSED/);
    assert.equal(st['03'].status, 'missing'); assert.match(st['03'].reason, /not in the registry/);
    assert.equal(st['05'].status, 'missing'); assert.match(st['05'].reason, /file not found/);
    assert.equal(st['06'].status, 'unresolved'); assert.match(st['06'].reason, /hash does not match/);
    assert.equal(r.environments[0].status, 'unapproved');
    assert.deepEqual(r.summary, {available: 0, missing: 2, unapproved: 2, unresolved: 1});

    // Unknown character registry, unknown environment ID, unimplemented format.
    const other = structuredClone(story);
    other.scenes[0].cast[0].character = 'character-99';
    other.scenes[0].environment = 'no-such-room';
    const r2 = analyseStory(other, {sources: src});
    assert.ok(r2.characters[0].poses.every(p => p.status === 'unresolved' && /no registry/.test(p.reason)));
    assert.equal(r2.environments[0].status, 'missing'); assert.match(r2.environments[0].reason, /not in the registry/);
    const planned = structuredClone(story); planned.scenes[0].format = 'phone-call';
    const r3 = analyseStory(planned, {sources: src});
    if (r3.valid) { assert.ok(r3.summary.unresolved >= 1); assert.match(r3.characters[0].poses[0].reason, /not implemented/); }
    else assert.match(r3.error, /phone-call|format/);
    const bad = analyseStory({id: 'x'}, {sources: src});
    assert.equal(bad.valid, false); assert.ok(bad.error);
  } finally { src.cleanup(); }
  assert.deepEqual(snapshot(), before);
});

test('reference pack: records source, SHA-256, dimensions, approval and version; detects missing files and hash mismatches', async () => {
  const before = snapshot();
  const pack = await buildReferencePack({kind: 'story', id: STORY});
  assert.equal(pack.complete, true); assert.deepEqual(pack.problems, []); assert.match(pack.packSha256, /^[0-9a-f]{64}$/);
  const refs = pack.items.map(i => i.ref);
  for (const r of ['character-01:canon-scene', 'character-01:master-v3', 'character-01:pose-02', 'character-01:pose-03', 'character-01:pose-06', 'env:living-room-empty-03']) assert.ok(refs.includes(r), r);
  const canon = pack.items.find(i => i.ref === 'character-01:canon-scene');
  assert.deepEqual([canon.width, canon.height, canon.sha256, canon.approval], [941, 1672, '36b7c97e8b9c31673d6b04dbc9c95b0a6b433dd14dee133fff9c87ad3ebff016', 'PROTECTED']);
  assert.equal(pack.items.find(i => i.ref === 'character-01:master-v3').version, 3);
  for (const i of pack.items) { assert.ok(!path.isAbsolute(i.source), 'repository-relative sources only (internal)'); assert.ok(i.width > 0 && i.height > 0); assert.ok(i.features, i.ref); }
  const p02 = pack.items.find(i => i.ref === 'character-01:pose-02');
  assert.deepEqual(p02.feet, {x: 102, y: 560}); assert.equal(p02.features.cutout, true); assert.ok(p02.features.silhouette.height > 500);
  assert.equal(canon.features.cutout, false, 'the canon scene is an opaque image, not a cut-out');
  // The public view carries no paths.
  for (const i of pack.items) { const pub = publicPackItem(i); assert.equal(pub.source, undefined); assert.ok(!JSON.stringify(pub).includes('bible/')); }
  assert.equal((await buildReferencePack({kind: 'story', id: STORY})).packSha256, pack.packSha256, 'deterministic pack hash');
  assert.equal(verifyPack(pack.items).ok, true);

  // Drift: a copy of a reference that later changes or disappears (temp files only; real artwork is never touched).
  const src = tempSources();
  try {
    const a = path.join(src.dir, 'ref-a.png'), b = path.join(src.dir, 'ref-b.png');
    // Copy bytes, not the file: canon artwork is read-only on disk and copyFile would keep that attribute.
    const bytes = fs.readFileSync(path.join(REPO, canon.source)); fs.writeFileSync(a, bytes); fs.writeFileSync(b, bytes);
    const rel = f => path.relative(REPO, f).split(path.sep).join('/');
    const items = [{ref: 'a', source: rel(a), sha256: sha(a)}, {ref: 'b', source: rel(b), sha256: sha(b)}];
    assert.equal(verifyPack(items).ok, true);
    fs.appendFileSync(a, Buffer.from([0])); fs.rmSync(b);
    const v = verifyPack(items);
    assert.equal(v.ok, false); assert.deepEqual(v.results.map(r => r.state), ['mismatch', 'missing']);
    // Registry hash disagreeing at build time makes the pack incomplete with a named problem.
    const reg = readJson('production/characters/character-01.json'); reg.poses['02'].sha256 = 'f'.repeat(64);
    writeJson(path.join(src.charactersDir, 'character-01.json'), reg); writeJson(src.canonFile, {characters: {}});
    const p2 = await buildReferencePack({kind: 'character', id: 'character-01'}, src);
    assert.equal(p2.complete, false); assert.ok(p2.problems.some(x => /pose-02.*hash does not match/.test(x)));
    // Story pack with an unapproved environment and an unapproved pose: excluded, named as problems, pack incomplete.
    const reg2 = readJson('production/characters/character-01.json'); reg2.poses['05'].approval = 'PROPOSED';
    writeJson(path.join(src.charactersDir, 'character-01.json'), reg2);
    const env = readJson('production/environments/environments.json'); env.environments['living-room-empty-03'].status = 'REJECTED';
    writeJson(src.environmentsFile, env);
    const p3 = await buildReferencePack({kind: 'story', id: STORY}, src);
    assert.equal(p3.complete, false);
    assert.ok(!p3.items.some(i => i.ref === 'env:living-room-empty-03'), 'unapproved environment is not a reference');
    assert.ok(!p3.items.some(i => i.ref === 'character-01:pose-05'), 'unapproved pose is not a reference');
    assert.ok(p3.problems.some(x => /^env:living-room-empty-03: unapproved .*not used as a reference/.test(x)));
    assert.ok(p3.problems.some(x => /^character-01:pose-05: unapproved/.test(x)));
    await assert.rejects(buildReferencePack({kind: 'character', id: '../x'}), e => e.status === 400);
    await assert.rejects(buildReferencePack({kind: 'character', id: 'character-99'}, src), e => e.status === 422);
    await assert.rejects(buildReferencePack({kind: 'other', id: 'x'}), e => e.status === 400);
  } finally { src.cleanup(); }
  assert.deepEqual(snapshot(), before);
});

test('candidate validation: realistic candidates pass; each measurable defect is caught; unmeasurable checks say n/a', async () => {
  const before = snapshot();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cand-'));
  const poseRefs = await referencesForAsset('character-pose', 'character-01/pose-07');
  const envRefs = await referencesForAsset('environment', 'living-room-empty-03');
  const pose02 = poseRefs.find(r => r.ref === 'character-01:pose-02'), plate = envRefs.find(r => r.ref === 'env:living-room-empty-03');
  assert.ok(pose02.features.cutout && pose02.features.palette.length && pose02.features.edge); assert.equal(pose02.feet.x, 102);
  assert.ok(Math.abs(pose02.features.feet.x - pose02.feet.x) <= 6, 'measured feet anchor agrees with the registered anchor');
  assert.ok(plate.approved && plate.features.histogram.length === 512);
  const run = async (file, assetType, assetKey, refs) => validateCandidate({file, bytes: fs.statSync(file).size, assetType, assetKey, referenceItems: refs});
  const byId = r => Object.fromEntries(r.checks.map(c => [c.id, c.status]));
  const POSE = 'character-01/pose-07';
  // Approved pose 02 scaled up 2.2x on a transparent canvas: a realistic, on-model candidate.
  const art = await canvas.loadImage(path.join(REPO, pose02.source));
  const good = await run(await png(path.join(dir, 'good.png'), 800, 1400, c => c.drawImage(art, 100, 40, art.width * 2.2, art.height * 2.2)), 'character-pose', POSE, poseRefs);
  assert.deepEqual(byId(good), {'file-size': 'pass', 'image-integrity': 'pass', dimensions: 'pass', 'canvas-dimensions': 'n/a', transparency: 'pass', 'figure-height': 'pass',
    'pose-proportions': 'pass', 'feet-anchor': 'pass', 'palette-consistency': 'pass', 'edge-integrity': 'pass', 'human-approval': 'warn'});
  assert.equal(good.status, 'warn', 'never "approved": a person must review (n/a checks do not count)');
  // Opaque pose: no separable figure, so the figure checks fail instead of measuring the background.
  const opaque = await run(await png(path.join(dir, 'opaque.png'), 800, 800, c => { c.fillStyle = '#fff'; c.fillRect(0, 0, 800, 800); }), 'character-pose', POSE, poseRefs);
  assert.equal(byId(opaque).transparency, 'fail'); assert.equal(byId(opaque)['feet-anchor'], 'fail'); assert.equal(opaque.status, 'fail');
  // Thin bar: proportions measured from the silhouette, not the canvas.
  const thin = await run(await png(path.join(dir, 'thin.png'), 800, 800, c => { c.fillStyle = '#000'; c.fillRect(380, 100, 40, 600); }), 'character-pose', POSE, poseRefs);
  assert.equal(byId(thin)['figure-height'], 'warn'); assert.equal(byId(thin)['pose-proportions'], 'warn');
  // Off-palette figure cut off at the bottom edge: palette, feet anchor and edge integrity fail.
  const clipped = await run(await png(path.join(dir, 'clipped.png'), 800, 1400, c => { c.fillStyle = '#ff00ff'; c.fillRect(150, 200, 520, 1200); }), 'character-pose', POSE, poseRefs);
  assert.equal(byId(clipped)['palette-consistency'], 'fail'); assert.equal(byId(clipped)['feet-anchor'], 'fail'); assert.equal(byId(clipped)['edge-integrity'], 'fail');
  // White fringe around the figure (a background-removal halo) and stray specks: edge-integrity warns.
  const whiteSil = canvas.createCanvas(800, 1400), w = whiteSil.getContext('2d');
  w.drawImage(art, 100, 40, art.width * 2.2, art.height * 2.2); w.globalCompositeOperation = 'source-in'; w.fillStyle = '#ffffff'; w.fillRect(0, 0, 800, 1400);
  const halo = await run(await png(path.join(dir, 'halo.png'), 800, 1400, c => {
    for (const [dx, dy] of [[-4, 0], [4, 0], [0, -4], [0, 4]]) c.drawImage(whiteSil, dx, dy);      // white fringe behind the figure
    c.drawImage(art, 100, 40, art.width * 2.2, art.height * 2.2);
    c.fillStyle = '#000'; for (let i = 0; i < 400; i++) c.fillRect(20 + (i % 20) * 3, 20 + Math.floor(i / 20) * 3, 1, 1);   // stray specks
  }), 'character-pose', POSE, poseRefs);
  const haloDetail = halo.checks.find(c => c.id === 'edge-integrity').detail;
  assert.equal(byId(halo)['edge-integrity'], 'warn'); assert.match(haloDetail, /specks/); assert.match(haloDetail, /halo/);
  // No references at all: comparisons report n/a rather than inventing a measurement.
  const noRefs = await run(path.join(dir, 'good.png'), 'character-pose', POSE, []);
  assert.equal(byId(noRefs)['pose-proportions'], 'n/a'); assert.equal(byId(noRefs)['palette-consistency'], 'n/a'); assert.equal(byId(noRefs)['feet-anchor'], 'warn');

  // Environment: the approved plate re-encoded is fully consistent with itself and the approved family.
  const plateImg = await canvas.loadImage(path.join(REPO, plate.source));
  const env = await run(await png(path.join(dir, 'env.png'), plateImg.width, plateImg.height, c => c.drawImage(plateImg, 0, 0)), 'environment', 'living-room-empty-03', envRefs);
  assert.deepEqual(byId(env), {'file-size': 'pass', 'image-integrity': 'pass', dimensions: 'pass', opacity: 'pass', 'aspect-ratio': 'pass', 'canvas-dimensions': 'pass',
    'environment-reference': 'pass', 'environment-reference-dimensions': 'pass', 'environment-palette': 'pass', 'edge-integrity': 'pass', 'human-approval': 'warn'});
  // Wrong size, off-palette, letterboxed, for an existing ID: dimensions warn, palette fails, flat border warns.
  const envOff = await run(await png(path.join(dir, 'env-off.png'), 900, 1600, c => { c.fillStyle = '#ff00ff'; c.fillRect(0, 0, 900, 1600); c.fillStyle = '#00ff00'; c.fillRect(0, 80, 900, 1440);
    c.fillStyle = '#000'; c.fillRect(0, 0, 900, 80); }), 'environment', 'living-room-empty-03', envRefs);
  assert.equal(byId(envOff)['canvas-dimensions'], 'warn'); assert.equal(byId(envOff)['environment-reference-dimensions'], 'warn');
  assert.equal(byId(envOff)['environment-palette'], 'fail'); assert.equal(byId(envOff)['edge-integrity'], 'warn');
  // A new environment: compared with the approved family; same-ID dimensions are n/a.
  const envNew = await run(path.join(dir, 'env.png'), 'environment', 'new-room', envRefs);
  assert.match(envNew.checks.find(c => c.id === 'environment-reference').detail, /style family/); assert.equal(byId(envNew)['environment-reference-dimensions'], 'n/a');
  assert.equal(byId(envNew)['environment-palette'], 'pass');
  const envBad = await run(await png(path.join(dir, 'env-bad.png'), 1600, 900, c => { c.fillStyle = '#d9c7a8'; c.fillRect(0, 0, 800, 900); }), 'environment', 'new-room', []);
  assert.equal(byId(envBad).opacity, 'fail'); assert.equal(byId(envBad)['aspect-ratio'], 'warn'); assert.equal(byId(envBad)['canvas-dimensions'], 'n/a');
  // An unapproved environment with the same ID is flagged and never used as a reference.
  const src = tempSources();
  try {
    const reg = readJson('production/environments/environments.json'); reg.environments['living-room-empty-03'].status = 'REJECTED';
    writeJson(src.environmentsFile, reg);
    const refs2 = await referencesForAsset('environment', 'living-room-empty-03', src);
    assert.equal(refs2.find(r => r.ref === 'env:living-room-empty-03').approved, false);
    const r2 = await run(path.join(dir, 'env.png'), 'environment', 'living-room-empty-03', refs2);
    assert.equal(byId(r2)['environment-reference'], 'warn'); assert.match(r2.checks.find(c => c.id === 'environment-reference').detail, /not approved/);
    assert.equal(byId(r2)['environment-reference-dimensions'], 'n/a');
  } finally { src.cleanup(); }
  assert.deepEqual(snapshot(), before);
  // Broken file, too small, empty.
  const broken = path.join(dir, 'broken.png'); fs.writeFileSync(broken, Buffer.from('not a png at all'));
  const rb = await run(broken, 'character-pose', 'character-01/pose-07', poseRefs);
  assert.equal(byId(rb)['image-integrity'], 'fail'); assert.equal(rb.status, 'fail');
  const small = await run(await png(path.join(dir, 'small.png'), 100, 100, () => {}), 'character-pose', 'character-01/pose-07', poseRefs);
  assert.equal(byId(small).dimensions, 'fail');
  const empty = path.join(dir, 'empty.png'); fs.writeFileSync(empty, Buffer.alloc(0));
  assert.equal(byId(await run(empty, 'environment', 'x', []))['file-size'], 'fail');
  fs.rmSync(dir, {recursive: true, force: true});
});

test('studio: requirements, reference packs (immutable, re-verified) and validation reports through the API', async () => {
  const before = snapshot();
  const {s, call, workspace} = await start();
  try {
    const all = await call('/api/generation/requirements');
    assert.equal(all.status, 200); assert.ok(all.json.some(r => r.storyFile === STORY));
    const one = await call(`/api/generation/requirements?story=${STORY}`);
    assert.equal(one.json.summary.available, 5);
    assert.equal((await call('/api/generation/requirements?story=..%2Fx.json')).status, 400);
    // No filesystem paths (absolute or repository-relative) leave the studio.
    const noPaths = (t, what) => {
      assert.ok(!t.includes(REPO) && !t.includes(REPO.replace(/\\/g, '\\\\')), `${what}: no absolute paths`);
      for (const s of ['bible/', 'production/', '"source"', '"file"', '"registry"', '"legacyFile"']) assert.ok(!t.includes(s), `${what}: must not contain ${s}`);
    };
    noPaths(all.text, 'requirements'); noPaths(one.text, 'requirements?story');

    const created = await call('/api/generation/reference-packs', {method: 'POST', body: {kind: 'character', id: 'character-01', note: 'pose 07 references'}});
    assert.equal(created.status, 201); assert.equal(created.json.complete, true); assert.equal(created.json.verification.ok, true);
    assert.ok(created.json.items.length >= 8);
    const packId = created.json.id;
    const listed = await call('/api/generation/reference-packs'), detail = await call(`/api/generation/reference-packs/${packId}`);
    assert.equal(listed.json[0].id, packId); assert.equal(detail.json.packSha256, created.json.packSha256);
    noPaths(created.text, 'pack create'); noPaths(listed.text, 'pack list'); noPaths(detail.text, 'pack detail');
    const pub02 = detail.json.items.find(i => i.ref === 'character-01:pose-02');
    assert.deepEqual(pub02.registeredFeet, {x: 102, y: 560}); assert.ok(pub02.measured.silhouette.height > 500); assert.equal(pub02.features, undefined);
    assert.equal((await call('/api/generation/reference-packs/999999')).status, 404);
    assert.equal((await call('/api/generation/reference-packs', {method: 'POST', body: {kind: 'character', id: '../etc'}})).status, 400);
    assert.throws(() => s.db.prepare(`UPDATE gen_reference_packs SET pack_sha256 = 'x'`).run(), /immutable/);
    assert.throws(() => s.db.prepare('DELETE FROM gen_reference_packs').run(), /immutable/);

    // A job tied to the pack: provenance names the pack; automatic validation is recorded before the job is ready.
    assert.equal((await call('/api/generation/jobs', {method: 'POST', body: {assetType: 'character-pose', assetKey: 'character-01/pose-07', description: 'surprised', referencePackId: 999999}})).status, 404);
    const r = await call('/api/generation/jobs', {method: 'POST', body: {assetType: 'character-pose', assetKey: 'character-01/pose-07', description: 'Test request: surprised pose', referencePackId: packId}});
    assert.equal(r.status, 202); assert.equal(r.json.referencePackId, packId);
    const j = await until(call, r.json.id, ['candidate_ready']);
    assert.equal(j.referencePack.id, packId); assert.equal(j.candidates[0].provenance.referencePack.packSha256, created.json.packSha256);
    assert.equal(j.validations.length, 1); const v = j.validations[0];
    assert.equal(v.trigger, 'auto'); assert.equal(v.referencePackId, packId); assert.equal(v.candidateSha256, j.candidates[0].sha256);
    assert.ok(v.checks.some(c => c.id === 'synthetic' && c.status === 'warn'), 'synthetic fixtures are flagged');
    assert.ok(['warn', 'fail'].includes(v.status), 'a synthetic fixture never passes cleanly');
    assert.equal(j.status, 'candidate_ready', 'validation never approves or rejects');
    assert.equal(j.proposals.length, 0);

    // Manual re-validation appends a report; tampering with the quarantined file is detected.
    const m = await call(`/api/generation/jobs/${j.id}/validate`, {method: 'POST', body: {}});
    assert.equal(m.status, 201); assert.equal(m.json.validations.length, 2); assert.equal(m.json.validations[1].trigger, 'manual');
    fs.appendFileSync(path.join(workspace, 'quarantine', j.id, j.candidates[0].name), Buffer.from([0]));
    const t = await call(`/api/generation/jobs/${j.id}/validate`, {method: 'POST', body: {}});
    assert.equal(t.json.reports[0].status, 'fail'); assert.match(t.json.reports[0].checks[0].detail, /changed since it was recorded/);
    assert.throws(() => s.db.prepare(`UPDATE gen_validations SET status = 'pass'`).run(), /append-only/);
    assert.throws(() => s.db.prepare('DELETE FROM gen_validations').run(), /append-only/);
    const after = await call(`/api/generation/jobs/${j.id}`);
    assert.equal(after.json.status, 'candidate_ready'); noPaths(JSON.stringify(after.json.validations), 'validation reports');

    // A pack recorded before measurements existed (no features stored) is measured at validation time, hash-checked first.
    const items = JSON.parse(s.db.prepare('SELECT items_json FROM gen_reference_packs WHERE id = ?').get(packId).items_json).map(({features, ...rest}) => rest);
    const oldId = Number(s.db.prepare(`INSERT INTO gen_reference_packs (subject_kind, subject_id, pack_sha256, complete, items_json, problems_json, note, created_by, created_at)
      VALUES ('character', 'character-01', ?, 1, ?, '[]', 'pre-measurement pack', 'test', '2026-11-12')`).run(created.json.packSha256, JSON.stringify(items)).lastInsertRowid);
    const oj = await until(call, (await call('/api/generation/jobs', {method: 'POST', body: {assetType: 'character-pose', assetKey: 'character-01/pose-07', description: 'Old pack check', referencePackId: oldId}})).json.id, ['candidate_ready']);
    assert.equal(oj.validations.length, 1, 'validation ran with the pre-measurement pack');
    const remeasured = await ensureFeatures(structuredClone(items));
    const orig = JSON.parse(s.db.prepare('SELECT items_json FROM gen_reference_packs WHERE id = ?').get(packId).items_json);
    assert.deepEqual(remeasured.find(i => i.ref === 'character-01:pose-02').features.silhouette, orig.find(i => i.ref === 'character-01:pose-02').features.silhouette);
    // A file that no longer matches its recorded hash is not measured (its drift is reported by verification instead).
    const tampered = [{...items.find(i => i.ref === 'character-01:pose-02'), sha256: '0'.repeat(64)}];
    assert.equal((await ensureFeatures(tampered))[0].features, undefined);
    assert.equal((await call('/api/generation/jobs/g-bad/validate', {method: 'POST', body: {}})).status, 400);
    assert.equal((await call('/api/generation/jobs/g-20260101-000000-abcdef/validate', {method: 'POST', body: {}})).status, 404);
  } finally { await s.close(); }
  assert.deepEqual(snapshot(), before, 'registries, stories and artwork untouched');
});

test('migration: a database created before AP-84B2 gains the reference_pack_id column and keeps its jobs', async () => {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'mig-'));
  const {DatabaseSync} = await import('node:sqlite');
  fs.mkdirSync(workspace, {recursive: true});
  // Open once (creates the current schema), drop to an AP-84B1-shaped gen_jobs table, then reopen.
  let st = await start({workspace});
  await st.s.close();
  const db = new DatabaseSync(path.join(workspace, 'studio.db'));
  db.exec(`CREATE TABLE old_jobs AS SELECT id, episode_id, asset_type, asset_key, description, status, adapter, initiated_by, attempt, parent_job_id, progress, error, retryable, created_at, updated_at, started_at, finished_at FROM gen_jobs;
    DROP TABLE gen_jobs; ALTER TABLE old_jobs RENAME TO gen_jobs;
    INSERT INTO gen_jobs (id, asset_type, asset_key, description, status, adapter, initiated_by, attempt, progress, retryable, created_at, updated_at) VALUES ('g-20260101-000000-abcdef', 'environment', 'room-x', 'old job', 'failed', 'none', 'owner', 1, 0, 0, '2026-01-01', '2026-01-01');`);
  db.close();
  const port = nextPort++;
  const s = createStudio({workspace, port, genAdapter: 'none', command: () => [process.execPath, ['-e', '0']]});
  await s.listen();
  try {
    const res = await fetch(`http://127.0.0.1:${port}/api/generation/jobs/g-20260101-000000-abcdef`).then(r => r.json());
    assert.equal(res.description, 'old job'); assert.equal(res.referencePackId, null); assert.deepEqual(res.validations, []);
  } finally { await s.close(); }
});
