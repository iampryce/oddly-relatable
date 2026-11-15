// End-to-end: compile episodes and check them with the UNMODIFIED renderer's own loadProject + painter.
// Tests that need ffprobe (the renderer probes the audio track) are skipped when FFPROBE is not set.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {compileEpisode} from '../lib/scene.mjs';
import {PRODUCTION_ROOT, REPO_ROOT, SKILL_ROOT, rendererModules} from '../lib/runtime.mjs';
import {BUBBLE_STYLES, PALETTE} from '../lib/palette.mjs';
import {interpolate} from '../lib/layout.mjs';

const FIXTURE = path.join(PRODUCTION_ROOT, 'fixtures', 'short-001-v2.conversation.json');
const needsRenderer = {skip: process.env.FFPROBE ? false : 'set FFMPEG/FFPROBE to run renderer-backed checks'};
const sha = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const tmp = name => fs.mkdtempSync(path.join(os.tmpdir(), `or-${name}-`));
const hashDir = dir => Object.fromEntries(fs.readdirSync(dir).map(f => [f, sha(path.join(dir, f))]));
const hex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
const near = (a, b, tol = 10) => b.every((v, i) => Math.abs(a[i] - v) <= tol);

test('Short 001 v2 fixture compiles to a single-shot B1 project with all conversation parts', async () => {
  const out = tmp('s001');
  const {report, manifest, sequence} = await compileEpisode(FIXTURE, {outDir: out});
  const p = JSON.parse(fs.readFileSync(path.join(out, 'project.json'), 'utf8'));
  assert.equal(p.style, 'B1'); assert.equal(p.width, 1080); assert.equal(p.height, 1920); assert.equal(p.fps, 30);
  assert.equal(p.shots.length, 1); assert.equal(p.shots[0].end, report.duration);
  assert.equal(report.duration, 54);
  assert.ok(report.checks.ok, JSON.stringify(report.checks.issues));
  assert.equal(sequence.messages.length, 17); assert.equal(sequence.typing.length, 2);
  assert.ok(sequence.messages.some(m => m.side === 'left') && sequence.messages.some(m => m.side === 'right'));
  assert.deepEqual([...new Set(sequence.poses.map(x => x.pose))].sort(), ['02', '03', '05', '06']);
  assert.equal(report.messages.at(-1).text, 'What did you do to the dishwasher.');
  assert.ok(manifest.generated.some(g => g.kind === 'hook') && manifest.generated.some(g => g.kind === 'endcard'));
  // Sources are byte-identical copies of the original artwork.
  for (const s of manifest.sources) assert.equal(sha(path.join(REPO_ROOT, s.source)), s.sha256);
});

test('compiling never changes renderer files or source artwork', async () => {
  const scripts = path.join(SKILL_ROOT, 'scripts'), before = hashDir(scripts);
  const art = ['bible/concepts/lookdev-richenv/lookdev-scene-01.png', 'bible/concepts/lookdev-richenv/lookdev-room-empty-03.png',
    'bible/concepts/lookdev-richenv/production-candidates/corrected/candidate-04_corrected-v3.png'].map(f => [f, sha(path.join(REPO_ROOT, f))]);
  await compileEpisode(FIXTURE, {outDir: tmp('guard')});
  assert.deepEqual(hashDir(scripts), before);
  for (const [f, h] of art) assert.equal(sha(path.join(REPO_ROOT, f)), h, f);
});

test('output folder protection: renderer folder, bible folder and foreign projects are refused', async () => {
  await assert.rejects(compileEpisode(FIXTURE, {outDir: path.join(SKILL_ROOT, 'x')}), /protected folder/);
  await assert.rejects(compileEpisode(FIXTURE, {outDir: path.join(REPO_ROOT, 'bible', 'x')}), /protected folder/);
  const foreign = tmp('foreign'); fs.writeFileSync(path.join(foreign, 'project.json'), '{}');
  await assert.rejects(compileEpisode(FIXTURE, {outDir: foreign}), /not created by this toolkit/);
});

test('the toolkit is generic: a different two-person chat with no character or background compiles', async () => {
  const ep = {schema: 'oddly-relatable/conversation-episode@1', id: 'generic', speakers: {boss: {side: 'left', style: 'neutral'}, me: {side: 'right', style: 'him'}},
    events: [{type: 'message', speaker: 'boss', text: 'Quick question.', duration: 2}, {type: 'typing', speaker: 'boss', duration: 2},
      {type: 'message', speaker: 'boss', text: 'Never mind.', duration: 2}, {type: 'message', speaker: 'me', text: 'Cool cool cool.', duration: 2}],
    endCard: {duration: 2, caption: 'Oddly Relatable'}};
  const {report} = await compileEpisode(ep, {outDir: tmp('generic')});
  assert.ok(report.checks.ok); assert.equal(report.messages.length, 3); assert.equal(report.typing.length, 1);
});

test('the chat zone is clamped above the face; composition conflicts fail the build unless allowed', async () => {
  const ep = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));
  ep.layout = {zoneBottom: 1900};                         // asks for a zone running into the character
  const ok = await compileEpisode(ep, {outDir: tmp('clamp')});
  const faceTop = 2070 - 880;
  assert.ok(ok.report.layout.zoneBottom <= faceTop - 40, 'zone bottom clamped above the face');
  assert.ok(ok.report.checks.ok);
  const clash = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));
  clash.hook.y = 330;                                     // hook placed on top of the header
  await assert.rejects(compileEpisode(clash, {outDir: tmp('clash')}), /Layout check failed: .*overlaps the header/);
  const allowed = await compileEpisode(clash, {outDir: tmp('clash2'), allowIssues: true});
  assert.equal(allowed.report.checks.ok, false);
});

test('an over-enlarged pose is reported as soft', async () => {
  const ep = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));
  ep.character.placement = {feetX: 640, feetY: 2240, figureHeight: 1300};
  ep.layout = {zoneTop: 470};
  const res = await compileEpisode(ep, {outDir: tmp('soft'), allowIssues: true});
  assert.ok(res.report.checks.warnings.some(w => /softness limit/.test(w)));
});

test('the renderer accepts the compiled project and draws bubbles, typing dots, poses and the end card', needsRenderer, async () => {
  const out = tmp('render');
  const {projectFile, sequence} = await compileEpisode(FIXTURE, {outDir: out});
  const {core, render} = await rendererModules();
  const p = core.loadProject(projectFile);              // the renderer's own validation
  assert.equal(p.duration, 54);
  const draw = await render.painter(p), ppu = 1080 / 1280;
  const px = (frame, x, y) => [...frame.getContext('2d').getImageData(Math.round(x * ppu), Math.round(y * ppu), 1, 1).data];
  const report = JSON.parse(fs.readFileSync(path.join(out, 'layout-report.json'), 'utf8'));
  const proj = JSON.parse(fs.readFileSync(projectFile, 'utf8')), layers = proj.shots[0].layers;

  // HIM's first bubble (right side, rust) is on screen once settled.
  const him = layers.find(l => l.path.includes('msg-m2-'));
  const f1 = draw(4.0);
  const y = interpolate(him.keys, 'y', 4.0);              // settled position at t=4 s (it scrolls up later)
  assert.ok(near(px(f1, him.x + him.w - 40, y + 14), hex(BUBBLE_STYLES.him.fill)), 'HIM bubble fill on screen');
  // Typing dots change opacity over time (pulse).
  const dot = layers.find(l => l.path.includes('typing-dot') && l.from === sequence.typing[0].start);
  const at = t => px(draw(t), dot.x + 10, interpolate(dot.keys, 'y', t) + 10);
  const a = at(6.6), b = at(6.9);
  assert.notDeepEqual(a.slice(0, 3), b.slice(0, 3), 'typing dot pulses');
  // End card covers the frame.
  assert.ok(near(px(draw(53), 60, 60), hex(PALETTE.card)), 'end card visible');
  assert.ok(report.storyboardTimes.length >= 20);
});
