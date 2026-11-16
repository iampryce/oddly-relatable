// AP-86 S4 (approved by the owner; owner decisions: 1080×1920 and 1920×1080 test resolutions, provisional safe margins,
// screen-side switches REPORTED, not failed). Framing profiles, composed windows on the set plate, camera moves and
// continuity reporting. Synthetic labelled fixtures only (temporary folders). Without `profile`, nothing changes (the
// AP-85, Short 001 and S1 to S3 regression tests cover that path).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {compileProject, compileProfiles} from '../lib/scene.mjs';
import {rendererModules} from '../lib/runtime.mjs';
import {STORY_SCHEMA_V2} from '../lib/story-v2.mjs';
import {PROFILES, windowCamera} from '../lib/framing.mjs';
import {applyCamera} from '../lib/camera.mjs';
import {writePlaceholder, PLACEHOLDER_CHARACTER} from './fixtures/ap85-placeholder.mjs';
import {writeS2Set, S2_COLOURS} from './fixtures/ap86-synthetic.mjs';

const needsRenderer = {skip: process.env.FFPROBE ? false : 'set FFMPEG/FFPROBE to run renderer-backed checks'};
const tmp = n => fs.mkdtempSync(path.join(os.tmpdir(), `ap86s4-${n}-`));
const json = f => JSON.parse(fs.readFileSync(f, 'utf8'));
const PH_REG = writePlaceholder(tmp('ph'));
const SET = writeS2Set(tmp('set')).file;

// Two members far enough apart that a medium shot on one leaves the other fully out of frame in portrait.
const CAST = () => [
  {id: 'c01', character: 'character-01', placement: {plateX: 0.35, plateY: 0.86}, speech: {style: 'him'}},
  {id: 'ph', character: PLACEHOLDER_CHARACTER, registry: PH_REG, placement: {plateX: 0.65, plateY: 0.86}, speech: {style: 'neutral'}, facing: 'left'},
];
const story = (lines, extra = {}) => ({schema: STORY_SCHEMA_V2, id: 's4', endCard: {duration: 1, caption: 'Technical test'}, ...extra,
  scenes: [{id: 's4', format: 'face-to-face', set: 'synthetic-s2', plate: 'wide', setRegistry: SET, cast: CAST(), lines}]});
const CUTS = () => [
  {speaker: 'c01', text: 'Wide on both of us.', duration: 1.5, poses: {c01: '02', ph: 'p1'}, shot: {camera: 'Wide'}},
  {speaker: 'c01', text: 'Medium on me.', duration: 1.5, shot: {camera: 'Medium 1.3x', focus: 'c01'}},
  {speaker: 'ph', text: 'Medium on me.', duration: 1.5, pose: 'p2', shot: {camera: 'Medium 1.3x', focus: 'ph'}},
  {speaker: 'c01', text: 'Wide again.', duration: 1.5, shot: {camera: 'Wide'}},
];
const MOVES = () => [
  {speaker: 'c01', text: 'Wide.', duration: 1.5, poses: {c01: '02', ph: 'p1'}, shot: {camera: 'Wide'}},
  {speaker: 'c01', text: 'Push in on me.', duration: 2.0, shot: {camera: 'Push-in to 1.3x', focus: 'c01'}},
  {speaker: 'ph', text: 'Slow pan to me.', duration: 2.0, shot: {camera: 'Slow pan', focus: 'ph'}},
  {speaker: 'ph', text: 'Pull back to wide.', duration: 2.0, shot: {camera: 'Pull back to wide'}},
];
const builds = async (lines, profiles = ['P-916', 'P-169']) => compileProfiles(story(lines), {outDir: tmp('p'), profiles, allowSynthetic: true});
const report = r => r.report.camera[0];

test('S4 profiles: the same staged scene compiles to 9:16 and 16:9, every shot inside the plate, all framing rules met', async () => {
  const out = await builds(CUTS());
  for (const [id, r] of Object.entries(out)) {
    const project = json(r.projectFile), prof = PROFILES[id];
    assert.deepEqual([project.width, project.height], [prof.width, prof.height], `${id} frame size`);
    assert.ok(r.report.checks.ok, `${id}: ${JSON.stringify(r.report.checks.issues)}`);
    assert.equal(report(r).profile, id);   // plate coverage is checked on every frame by the compiler (no issues above)
    for (const s of report(r).shots) assert.ok(s.window && s.visible.length >= 1, `${id} line ${s.line} composed`);
  }
  // Portrait: the superframe gives room to pan, so a medium shot on c01 leaves ph fully OUT of frame: a true single
  // without the `single` cheat (ph is not hidden, simply not in the window).
  const p = report(out['P-916']).shots;
  assert.deepEqual([p[1].visible, p[1].hidden, p[1].out], [['c01'], [], ['ph']]);
  assert.deepEqual([p[2].visible, p[2].out], [['ph'], ['c01']]);
  assert.deepEqual(p[0].visible.sort(), ['c01', 'ph'], 'wide frames everyone');
  // Landscape keeps both in the medium shots (the frame is wider than the cast), and they stay on their sides.
  const l = report(out['P-169']).shots;
  assert.deepEqual(l[1].visible.sort(), ['c01', 'ph']);
});

test('S4 camera moves: push-in, pan and pull-back are frame-by-frame, eased, inside the plate, and composed at both ends', async () => {
  const out = await builds(MOVES(), ['P-916']);
  const r = out['P-916'], cam = report(r);
  assert.ok(r.report.checks.ok, JSON.stringify(r.report.checks.issues));
  assert.deepEqual(cam.moves.map(m => [m.kind, m.from, m.to]), [['push', 1, 1.3], ['pan', 1.3, 1.3], ['pull', 1.3, 1]]);
  assert.deepEqual(cam.cuts, [], 'moves are not reported as cuts');
  // The backdrop's keys change on every frame of a move (no stutter) and move in one direction (eased, no reversal).
  const project = json(r.projectFile), backdrop = project.shots[0].layers.find(l => l.path.includes('-backdrop-'));
  const pan = cam.moves[1], inPan = backdrop.keys.filter(k => k.t >= pan.start - 1e-6 && k.t < pan.end - 1e-6);
  assert.ok(inPan.length >= Math.floor((pan.end - pan.start) * 30) - 1, `a key on every frame of the pan (${inPan.length})`);
  const dx = inPan.slice(1).map((k, i) => k.x - inPan[i].x);
  assert.ok(dx.every(d => d <= 1e-9) || dx.every(d => d >= -1e-9), 'the pan never reverses');
  assert.ok(Math.abs(dx[0]) < Math.abs(dx[Math.floor(dx.length / 2)]), 'eased: slow at the start, faster in the middle');
  // Story-board times include each move.
  assert.equal(r.report.storyboardTimes.filter(t => /move/.test(t.label)).length, 3);
});

test('S4 moves are refused where they cannot work, with an explanation', async () => {
  const mv = MOVES();
  await assert.rejects(builds([{...mv[1], poses: {c01: '02', ph: 'p1'}}], ['P-916']), /first shot needs a framing .*not a camera move/);
  await assert.rejects(builds([mv[0], {...mv[2], shot: {camera: 'Pan', focus: 'ph'}}], ['P-916']), /a pan moves a medium or close framing/);
  // A plain "Pan" lasts min(1 s, the line). c01 -> ph is about 0.65 frame widths: fine over 1 s, unreadable over 0.4 s.
  await assert.doesNotReject(builds([mv[0], mv[1], {...mv[2], duration: 2.0, shot: {camera: 'Pan', focus: 'ph'}}], ['P-916']));
  // Members at the far edges of the plate, in close shots (1.5x): a 1 s pan between them whips across about 1.67
  // frame widths (the windows stop at the plate edges, so at 1.3x the travel would be only 1.31).
  const far = story([{speaker: 'c01', text: 'Close on me.', duration: 2.0, poses: {c01: '02', ph: 'p1'}, shot: {camera: 'Close', focus: 'c01'}},
    {speaker: 'ph', text: 'Pan to me.', duration: 2.0, shot: {camera: 'Pan', focus: 'ph'}}], {profile: 'P-916'});
  far.scenes[0].cast[0].placement.plateX = 0.12; far.scenes[0].cast[1].placement.plateX = 0.88;
  await assert.rejects(compileProject(far, {outDir: tmp('far'), allowSynthetic: true}), /too fast to read; use "slow pan"/);
  far.scenes[0].lines[1].shot.camera = 'Slow pan';
  await assert.doesNotReject(compileProject(far, {outDir: tmp('far2'), allowSynthetic: true}), 'a slow pan over the whole line is fine');
  // Without a profile, moves stay refused exactly as before (story@2 in a set, no profile).
  await assert.rejects(compileProject(story(MOVES()), {outDir: tmp('np'), allowSynthetic: true}), /no moves, shake or drift/);
  // A profile needs story@2, a set and face-to-face.
  await assert.rejects(compileProject({...story(CUTS(), {profile: 'P-916'}), schema: 'oddly-relatable/story@1', scenes: [{id: 'x', format: 'face-to-face', environment: 'living-room-empty-03', cast: CAST().map(c => ({...c, placement: {feetX: 640, feetY: 2070, figureHeight: 700}})), lines: CUTS()}]}, {outDir: tmp('v1'), allowSynthetic: true}), /"profile" needs "oddly-relatable\/story@2"/);
  await assert.rejects(compileProject(story(CUTS(), {profile: 'P-43'}), {outDir: tmp('bad'), allowSynthetic: true}), /unknown framing profile "P-43"/);
});

test('S4 continuity: screen-side switches between shots are REPORTED and do not fail the build (owner decision)', async () => {
  const lines = [CUTS()[0], {speaker: 'c01', text: 'Close, centred on me.', duration: 1.5, shot: {camera: 'Close', focus: 'c01'}}, CUTS()[3]];
  const r = (await builds(lines, ['P-916']))['P-916'];
  assert.ok(r.report.checks.ok);
  const notes = report(r).continuity;
  assert.ok(Array.isArray(notes));
  // c01 is on the left half in the wide shot and centred (right half or left half, depending on the window) in the
  // close shot; whatever the result, it is reported, never an issue.
  for (const n of notes) assert.ok(['screen-side switch', 'left-right order flip'].includes(n.kind));
  assert.ok(!r.report.checks.issues.some(i => /side/.test(i.problem)));
});

test('S4 window camera: shows exactly the window (pivot at the window centre)', () => {
  const plane = {width: 1280, height: 720}, win = {L: -300, T: 120, W: 1280 / 1.3, H: 720 / 1.3};
  const cam = windowCamera(win, plane);
  const tl = applyCamera(cam, {x: win.L, y: win.T, w: win.W});
  assert.ok(Math.abs(tl.x) < 1e-9 && Math.abs(tl.y) < 1e-9 && Math.abs(tl.w - plane.width) < 1e-9);
});

test('S4 rendered frames: both profiles fill the frame with the set (no uncovered edge), at the profile resolution', needsRenderer, async () => {
  const out = await builds(MOVES());
  const {core, render} = await rendererModules();
  for (const [id, r] of Object.entries(out)) {
    const draw = await render.painter(core.loadProject(r.projectFile));
    for (const t of [0.5, 2.0, 4.6, 6.8]) {
      const c = draw(t), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      assert.deepEqual([c.width, c.height], [PROFILES[id].width, PROFILES[id].height]);
      // Top corners show the backdrop colour (grey), never empty canvas, at every sampled time including mid-move.
      for (const [x, y] of [[2, 2], [c.width - 3, 2]]) {
        const k = (y * c.width + x) * 4, px = [d[k], d[k + 1], d[k + 2]];
        assert.ok(px.every((v, i) => Math.abs(v - S2_COLOURS.backdrop[i]) <= 40), `${id} t=${t} corner (${x},${y}) is backdrop: ${px}`);
      }
    }
  }
});
