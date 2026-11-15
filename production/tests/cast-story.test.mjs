// Cast model, story layer, format strategies, Short 001 story mapping, and renderer-backed AP-79 checks.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {validateCast, resolveCast} from '../lib/cast.mjs';
import {FORMATS, formatFor} from '../lib/formats/index.mjs';
import {compileProject} from '../lib/scene.mjs';
import {interpolate} from '../lib/layout.mjs';
import {PRODUCTION_ROOT, REPO_ROOT, rendererModules} from '../lib/runtime.mjs';

const STORY = path.join(PRODUCTION_ROOT, 'stories', 'short-001-v2.story.json');
const FIXTURE = path.join(PRODUCTION_ROOT, 'fixtures', 'short-001-v2.conversation.json');
const SYNTH = path.join(PRODUCTION_ROOT, 'fixtures', 'synthetic-two-member-cast.story.json');
const SCRIPT = path.join(REPO_ROOT, 'bible', 'episodes', 'short-001-we-need-to-talk', 'SCRIPT_V2.md');
const needsRenderer = {skip: process.env.FFPROBE ? false : 'set FFMPEG/FFPROBE to run renderer-backed checks'};
const tmp = n => fs.mkdtempSync(path.join(os.tmpdir(), `or79-${n}-`));
const json = f => JSON.parse(fs.readFileSync(f, 'utf8'));
const sha = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');

// ---------- cast
test('cast validation: ids, duplicates, character IDs, facing support', () => {
  assert.throws(() => validateCast([{id: 'A b', character: 'character-01'}]), /lowercase identifier/);
  assert.throws(() => validateCast([{id: 'a', character: 'character-01'}, {id: 'a', character: 'character-01'}]), /duplicate/);
  assert.throws(() => validateCast([{id: 'a'}]), /character ID is required/);
  assert.throws(() => validateCast([{id: 'a', character: 'character-01', facing: 'mirrored'}]), /facing "mirrored" is not one of native, left, right, front/);
});

test('cast resolution: registry by character ID, z-order sorting, missing characters and unknown members fail', async () => {
  const cast = await resolveCast([{id: 'front', character: 'character-01', z: 2}, {id: 'back', character: 'character-01', z: 0}],
    {front: [{pose: '03', start: 0, end: 1}], back: [{pose: '02', start: 0, end: 1}]});
  assert.deepEqual(cast.map(m => m.id), ['back', 'front']);
  assert.equal(cast[0].infos.get('02').width, 270);
  await assert.rejects(resolveCast([{id: 'x', character: 'character-99'}], {}), /no registry for character "character-99"/);
  await assert.rejects(resolveCast([{id: 'x', character: 'character-01'}], {ghost: [{pose: '02', start: 0, end: 1}]}), /unknown cast member "ghost"/);
});

test('registry: poses 02, 05 and 06 point at the approved corrected files; 03 unchanged; hashes verified', async () => {
  const reg = json(path.join(PRODUCTION_ROOT, 'characters', 'character-01.json'));
  assert.match(reg.poses['02'].file, /ap75-pose02-test\/.*skin-only_test\.png$/);
  assert.match(reg.poses['05'].file, /ap76-pose05-test\/.*skin-only_test\.png$/);
  assert.match(reg.poses['06'].file, /ap80-pose06-test\/.*skin-only_test\.png$/);
  for (const id of ['02', '05', '06']) assert.equal(reg.poses[id].approval, 'APPROVED_WORKING_ASSET');
  assert.equal(reg.poses['03'].approval, 'APPROVED_WORKING_TEST_ASSET');
  assert.ok(!JSON.stringify(reg).includes('FINAL'), 'no pose is labelled a final master');
  for (const [id, p] of Object.entries(reg.poses)) {
    assert.equal(sha(path.join(REPO_ROOT, p.file)), p.sha256, `pose ${id} file hash`);
    if (p.source) assert.equal(sha(path.join(REPO_ROOT, p.source.file)), p.source.sha256, `pose ${id} source hash`);
  }
});

test('registry hash mismatch is caught', async () => {
  const reg = json(path.join(PRODUCTION_ROOT, 'characters', 'character-01.json'));
  reg.poses['02'].sha256 = '0'.repeat(64);
  const f = path.join(tmp('reg'), 'character-01.json'); fs.writeFileSync(f, JSON.stringify(reg));
  await assert.rejects(resolveCast([{id: 'x', character: 'character-01', registry: f}], {x: [{pose: '02', start: 0, end: 1}]}), /hash does not match/);
});

// ---------- formats and story
test('format strategies: text-chat and face-to-face implemented; the other formats are declared but not implemented', async () => {
  assert.equal(FORMATS['text-chat'].implemented, true);
  assert.equal(FORMATS['face-to-face'].implemented, true);   // AP-85 P1
  for (const id of ['phone-call', 'split-screen', 'solo']) {
    assert.equal(FORMATS[id].implemented, false);
    assert.throws(() => FORMATS[id].sequence({}), /designed but not implemented/);
  }
  assert.throws(() => formatFor('musical'), /Unknown scene format/);
});

test('Short 001 story: 19 beats, same dialogue as the fixture, camera notes verbatim from SCRIPT_V2, approved hook', () => {
  const story = json(STORY), fx = json(FIXTURE), events = story.scenes[0].events;
  assert.equal(events.length, 19);
  const strip = e => { const {camera, ...rest} = e; return rest; };
  assert.deepEqual(events.map(strip), fx.events, 'dialogue, durations, poses and SFX identical to the AP-78 fixture');
  const rows = fs.readFileSync(SCRIPT, 'utf8').split('\n').filter(l => /^\| \d+ \|/.test(l)).map(l => l.split('|').slice(1, -1).map(s => s.trim()));
  assert.equal(rows.length, 19);
  assert.deepEqual(events.map(e => e.camera), rows.map(r => r[2]));
  for (const [i, r] of rows.entries()) { const said = (r[4] || r[5]).replace(/\*/g, ''); if (events[i].type === 'message') assert.equal(events[i].text, said, `beat ${i + 1}`); }
  assert.equal(story.hook.text, 'Four words. No warning.');
  assert.deepEqual(story.scenes[0].cast.map(m => m.character), ['character-01'], 'Short 001 has only Character 01 on screen');
});

test('Short 001 story compiles: script camera notes become the expected cuts and moves; duration unchanged', async () => {
  const {report} = await compileProject(STORY, {outDir: tmp('s001')});
  assert.equal(report.duration, 54);
  assert.equal(report.messages.length, 17); assert.equal(report.typing.length, 2);
  const cam = report.camera[0];
  assert.deepEqual(cam.moves.map(m => [m.start, +m.end.toFixed(3), m.from, m.to]), [[3, 6, 1, 1.2], [45.5, 46.7, 1.5, 1]]);
  assert.deepEqual(cam.cuts.map(c => [c.t, c.to]), [[9, 1.5], [11.5, 1.3], [14, 1], [20, 1.5], [23, 1.3], [28.5, 1.5], [30.5, 1], [33.5, 1.3], [43.5, 1.5]]);
  assert.ok(report.checks.ok, JSON.stringify(report.checks.issues));
});

test('AP-78 episode format still compiles to the same timeline (no camera, cuts only)', async () => {
  const {report} = await compileProject(FIXTURE, {outDir: tmp('ap78')});
  const ap78 = json(path.join(PRODUCTION_ROOT, 'evidence', 'ap78', 'short-001-v2-layout-report.json'));
  assert.deepEqual(report.messages, ap78.messages);
  assert.deepEqual(report.typing, ap78.typing);
  assert.deepEqual(report.poses.map(p => [p.pose, p.start, p.end]), ap78.poses.map(p => [p.pose, p.start, p.end]));
  assert.deepEqual(report.layout, ap78.layout);
  assert.equal(report.camera[0].cuts.length + report.camera[0].moves.length, 0);
});

test('multi-scene story: one shot per scene, contiguous, SFX offset, end card in the last shot', async () => {
  const sc = (id, text, pose) => ({id, format: 'text-chat', environment: 'living-room-empty-03', cast: [{id: 'him', character: 'character-01'}],
    speakers: {a: {side: 'left', style: 'her'}}, events: [{type: 'message', speaker: 'a', text, duration: 2, pose, sfx: 'chime', camera: 'Wide'}]});
  const story = {schema: 'oddly-relatable/story@1', id: 'two-scenes', scenes: [sc('one', 'First scene.', '02'), sc('two', 'Second scene.', '03')], endCard: {duration: 1, caption: 'End'}};
  const out = tmp('multi');
  const {report} = await compileProject(story, {outDir: out});
  const p = json(path.join(out, 'project.json'));
  assert.deepEqual(p.shots.map(s => [s.start, s.end]), [[0, 2], [2, 5]]);
  assert.deepEqual(p.sfx.map(s => s.time), [0, 2]);
  assert.equal(report.scenes.length, 2);
  assert.ok(p.shots[1].layers.some(l => l.path.includes('endcard-')) && !p.shots[0].layers.some(l => l.path.includes('endcard-')));
});

test('a story using a planned format fails clearly', async () => {
  const story = {schema: 'oddly-relatable/story@1', id: 'call', scenes: [{id: 'c', format: 'phone-call'}]};
  await assert.rejects(compileProject(story, {outDir: tmp('planned')}), /designed but not implemented/);
});

// ---------- synthetic two-member cast
test('synthetic two-member cast: independent placement, z-order layering, per-member transitions', async () => {
  const out = tmp('synth');
  const {report} = await compileProject(SYNTH, {outDir: out});
  assert.ok(report.checks.ok, JSON.stringify(report.checks.issues));
  const layers = json(path.join(out, 'project.json')).shots[0].layers;
  // Members are told apart by where they stand: back member feet at x=520, front member at x=760 (first key, before any zoom).
  const poseLayers = layers.filter(l => l.path.includes('character-01-pose-')), centre = l => l.keys[0].x + l.keys[0].w / 2;
  const back = poseLayers.filter(l => centre(l) < 640), front = poseLayers.filter(l => centre(l) >= 640);
  assert.ok(back.length && front.length, 'both members drawn');
  const lastBack = layers.lastIndexOf(back.at(-1)), firstFront = layers.indexOf(front[0]);
  assert.ok(lastBack < firstFront, 'back member (z 0) drawn before front member (z 1)');
  assert.notEqual(back[0].keys[0].x, front[0].keys[0].x, 'independent x');
  const trans = report.character.map(c => `${c.cast}:${c.pose}:${c.transition}`);
  assert.ok(trans.includes('front:05:pop') && trans.includes('back:06:crossfade'));
});

// ---------- renderer-backed
test('renderer: Short 001 story validates; bubbles stay fixed while the camera pushes in; world layers share one transform', needsRenderer, async () => {
  const out = tmp('render');
  const {projectFile} = await compileProject(STORY, {outDir: out});
  const {core, render} = await rendererModules();
  const p = core.loadProject(projectFile);
  assert.equal(p.duration, 54); assert.equal(p.width, 1080); assert.equal(p.height, 1920); assert.equal(p.fps, 30);
  const layers = json(projectFile).shots[0].layers;
  const bg = layers.find(l => l.path.includes('background-')), pose02 = layers.find(l => l.path.includes('character-01-pose-02-'));
  // During the push-in (3–6 s) background and character keys follow the same zoom about the same pivot.
  for (const t of [3.5, 4.5, 5.5]) {
    const z = interpolate(bg.keys, 'w', t) / bg.keys[0].w;
    const dx = interpolate(pose02.keys, 'x', t) - interpolate(bg.keys, 'x', t), dx0 = pose02.keys[0].x - bg.keys[0].x;
    assert.ok(Math.abs(dx - dx0 * z) < 0.05, `consistent transform at ${t}s`);
  }
  // Bubbles are screen-space: identical pixels at 1.07x and 1.2x zoom, while the room behind changes.
  const draw = await render.painter(p);
  const grab = t => { const f = draw(t), ctx = f.getContext('2d'); return [...ctx.getImageData(0, 0, f.width, f.height).data]; };
  const a = grab(3.6), b = grab(5.95), W = 1080, ppu = 1080 / 1280;
  const bubble = layers.find(l => l.path.includes('msg-m2-')), y = interpolate(bubble.keys, 'y', 4);
  const px = (buf, x, yy) => buf.slice(((Math.round(yy * ppu)) * W + Math.round(x * ppu)) * 4, ((Math.round(yy * ppu)) * W + Math.round(x * ppu)) * 4 + 3);
  assert.deepEqual(px(a, bubble.x + bubble.w - 40, y + 14), px(b, bubble.x + bubble.w - 40, y + 14), 'bubble pixel unchanged by zoom');
  assert.notDeepEqual(px(a, 40, 1900), px(b, 40, 1900), 'world pixel changes with zoom');
});
