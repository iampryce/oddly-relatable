// AP-85 P1 Track A: composition architecture tests (docs/oddly-relatable/AP-85-MULTI-CHARACTER-VALIDATION-PLAN.md §5).
//
// TRACK A ONLY. These tests prove the ENGINE places, layers, times, voices and frames two independent characters
// correctly. They say NOTHING about identity consistency of any artwork (Track B). Character 01 uses its approved poses
// unchanged; the second character is a SYNTHETIC PLACEHOLDER (tests/fixtures/ap85-placeholder.mjs), written to a
// temporary folder, never artwork, never Character 02.
//
// Scenes: A1 two-shot, A2 swapped positions and z order, A3 overlap (both orders), A4 shot sequence, A5 scale and
// depth, A6 three members. Checks: A-1 to A-10. Pixel checks use the UNMODIFIED renderer's painter and need
// FFMPEG/FFPROBE (local, no cost); they are skipped, not faked, without them.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {compileProject} from '../lib/scene.mjs';
import {validateStory, episodeToStory} from '../lib/story.mjs';
import {resolveCast, validateCast} from '../lib/cast.mjs';
import {loadRegistry, poseInfo} from '../lib/character.mjs';
import {renderBubble, renderTypingShell, BUBBLE_DEFAULTS} from '../lib/graphics.mjs';
import {BUBBLE_STYLES} from '../lib/palette.mjs';
import {FORMATS} from '../lib/formats/index.mjs';
import {FACE_TO_FACE_DEFAULTS} from '../lib/formats/face-to-face.mjs';
import {canvas, PRODUCTION_ROOT, REPO_ROOT, rendererModules} from '../lib/runtime.mjs';
import {writePlaceholder, PLACEHOLDER_CHARACTER, PLACEHOLDER_COLOURS} from './fixtures/ap85-placeholder.mjs';

const needsRenderer = {skip: process.env.FFPROBE ? false : 'set FFMPEG/FFPROBE to run renderer-backed checks'};
const tmp = n => fs.mkdtempSync(path.join(os.tmpdir(), `ap85-${n}-`));
const sha = b => crypto.createHash('sha256').update(b).digest('hex');
const json = f => JSON.parse(fs.readFileSync(f, 'utf8'));
const PH_REG = writePlaceholder(tmp('placeholder'));
const C01 = 'character-01', PH = PLACEHOLDER_CHARACTER;
const EVIDENCE = path.join(PRODUCTION_ROOT, 'evidence', 'ap85', 'regression-baseline.json');

// ---------------------------------------------------------------------------------------------------- scenes
const c01 = (o = {}) => ({id: 'c01', character: C01, placement: {feetX: o.x ?? 400, feetY: o.feetY ?? 2070, figureHeight: o.h ?? 760}, z: o.z ?? 0, speech: {style: 'him', ...(o.side ? {side: o.side} : {})}, ...(o.facing ? {facing: o.facing} : {})});
const ph = (o = {}) => ({id: o.id ?? 'ph', character: PH, registry: o.registry ?? PH_REG, placement: {feetX: o.x ?? 880, feetY: o.feetY ?? 2070, figureHeight: o.h ?? 760}, z: o.z ?? 1,
  speech: {style: o.style ?? 'neutral', ...(o.side ? {side: o.side} : {})}, ...(o.facing ? {facing: o.facing} : {})});
const story = (id, cast, lines, extra = {}) => ({schema: 'oddly-relatable/story@1', id, endCard: {duration: 1, caption: 'Technical test'},
  scenes: [{id, format: 'face-to-face', environment: 'living-room-empty-03', cast, lines, ...extra}]});
const W = c => ({camera: c ?? 'Wide'});
// Eight alternating lines with a pose change on every line (speaker's pose).
const DIALOGUE = () => [
  {speaker: 'c01', text: 'First line.', duration: 1.5, poses: {c01: '02', ph: 'p1'}, shot: W()},
  {speaker: 'ph', text: 'Second line.', duration: 1.5, pose: 'p2', shot: W()},
  {speaker: 'c01', text: 'Third line.', duration: 1.5, pose: '03', shot: W()},
  {speaker: 'ph', text: 'Fourth line.', duration: 1.5, pose: 'p1', shot: W()},
  {speaker: 'c01', text: 'Fifth line.', duration: 1.5, pose: '05', shot: W()},
  {speaker: 'ph', text: 'Sixth line.', duration: 1.5, pose: 'p2', shot: W()},
  {speaker: 'c01', text: 'Seventh line.', duration: 1.5, pose: '06', shot: W()},
  {speaker: 'ph', text: 'Eighth line.', duration: 1.5, pose: 'p1', shot: W()},
];
const SCENES = {
  A1: () => story('a1-two-shot', [c01(), ph({facing: 'left'})], DIALOGUE()),
  A2: () => story('a2-swapped', [c01({x: 880, z: 1}), ph({x: 400, z: 0, facing: 'right'})], DIALOGUE()),
  A3a: () => story('a3-overlap-ph-front', [c01({x: 560, z: 0}), ph({x: 700, z: 1})], [
    {speaker: 'c01', text: 'Behind.', duration: 1.5, poses: {c01: '02', ph: 'p1'}, shot: W()}, {speaker: 'ph', text: 'In front.', duration: 1.5, shot: W()}]),
  A3b: () => story('a3-overlap-ph-behind', [c01({x: 560, z: 1}), ph({x: 700, z: 0})], [
    {speaker: 'c01', text: 'In front.', duration: 1.5, poses: {c01: '02', ph: 'p1'}, shot: W()}, {speaker: 'ph', text: 'Behind.', duration: 1.5, shot: W()}]),
  A4: () => story('a4-shots', [c01(), ph({facing: 'left'})], [
    {speaker: 'c01', text: 'Wide.', duration: 1.5, poses: {c01: '02', ph: 'p1'}, shot: W()},
    {speaker: 'ph', text: 'Single on the placeholder.', duration: 1.5, pose: 'p2', shot: {camera: 'Medium 1.3x', focus: 'ph', single: true}},
    {speaker: 'c01', text: 'Single on Character 01.', duration: 1.5, pose: '03', shot: {camera: 'Medium 1.3x', focus: 'c01', single: true}},
    {speaker: 'ph', text: 'Reaction on Character 01.', duration: 1.5, poses: {c01: '05', ph: 'p1'}, shot: {camera: 'Close', focus: 'c01', single: true}},
    {speaker: 'c01', text: 'Reaction on the placeholder.', duration: 1.5, poses: {c01: '06', ph: 'p2'}, shot: {camera: 'Close', focus: 'ph', single: true}},
    {speaker: 'ph', text: 'Wide again.', duration: 1.5, shot: W()},
  ]),
  A5: () => story('a5-depth', [c01({x: 480, z: 1}), ph({x: 840, feetY: 1950, h: 600, z: 0})], [
    {speaker: 'c01', text: 'Front.', duration: 1.5, poses: {c01: '02', ph: 'p1'}, shot: W()}, {speaker: 'ph', text: 'Further back.', duration: 1.5, pose: 'p2', shot: W()}]),
  A6: () => story('a6-three', [c01({x: 330, h: 700}), ph({id: 'ph-a', x: 700, h: 600, z: 1, style: 'neutral'}), ph({id: 'ph-b', x: 1020, h: 600, z: 2, style: 'her'})], [
    {speaker: 'c01', text: 'Three on screen.', duration: 1.5, poses: {c01: '02', 'ph-a': 'p1', 'ph-b': 'p2'}, shot: W()},
    {speaker: 'ph-a', text: 'Second.', duration: 1.5, pose: 'p2', shot: W()},
    {speaker: 'ph-b', text: 'Third.', duration: 1.5, pose: 'p1', shot: W()},
  ]),
};

const build = async (s, opts = {}) => {
  const outDir = tmp('build');
  const r = await compileProject(s, {outDir, allowSynthetic: true, ...opts});
  return {...r, dir: outDir, project: json(r.projectFile)};
};
const layersOf = (project, character) => project.shots[0].layers.filter(l => l.path.includes(`/${character}-pose-`));
const shotsOf = report => report.camera[0].shots;

// Source info for every pose layer: registry entry and image size, found from the copied file's name.
const regFor = {[C01]: loadRegistry(path.join(PRODUCTION_ROOT, 'characters', `${C01}.json`)), [PH]: loadRegistry(PH_REG)};
async function sourceFor(layer) {
  for (const [character, reg] of Object.entries(regFor)) {
    if (!layer.path.includes(`/${character}-pose-`)) continue;
    for (const id of Object.keys(reg.poses)) {
      const info = await poseInfo(reg, id, REPO_ROOT);
      if (layer.path.endsWith(`-pose-${id}-${path.basename(info.file)}`)) return {character, info};
    }
  }
  throw new Error(`no source for ${layer.path}`);
}
// Screen key -> world placement (feet point and figure height), inverting the shot's camera at the key's time.
function worldOf(key, info, shots) {
  const s = shots.find(x => key.t >= x.start - 1e-6 && key.t < x.end - 1e-6) || shots.at(-1);
  const z = s.zoom, wx = (key.x - s.pivot.x) / z + s.pivot.x, wy = (key.y - s.pivot.y) / z + s.pivot.y, k = key.w / z / info.width;
  return {feetX: wx + info.feet.x * k, feetY: wy + info.feet.y * k, figureHeight: info.figureHeight * k};
}
// Pose layers per cast member (by character, then nearest declared feet x for members of the same character).
async function layersByMember(project, report, cast) {
  const out = Object.fromEntries(cast.map(m => [m.id, []])), shots = shotsOf(report);
  for (const l of project.shots[0].layers) {
    if (!/-pose-/.test(l.path)) continue;
    const {character, info} = await sourceFor(l), w = worldOf(l.keys[0], info, shots);
    const cands = cast.filter(m => m.character === character).sort((a, b) => Math.abs(a.placement.feetX - w.feetX) - Math.abs(b.placement.feetX - w.feetX));
    out[cands[0].id].push({layer: l, info, index: project.shots[0].layers.indexOf(l)});
  }
  return out;
}

// ---------------------------------------------------------------------------------------------------- A-1
test('A-1 registry independence: each member resolves its own registry; wrong, unnamed or synthetic registries are refused; one registry cannot change another member', async () => {
  const cast = await resolveCast([c01(), ph()], {c01: [{pose: '02', start: 0, end: 1}], ph: [{pose: 'p1', start: 0, end: 1}]}, REPO_ROOT, {allowSynthetic: true});
  const byId = Object.fromEntries(cast.map(m => [m.id, m]));
  assert.notEqual(byId.c01.registryFile, byId.ph.registryFile);
  assert.deepEqual([byId.c01.registry.character, byId.ph.registry.character], [C01, PH]);
  assert.deepEqual([byId.c01.synthetic, byId.ph.synthetic], [false, true]);
  await assert.rejects(resolveCast([{id: 'x', character: C01, registry: PH_REG}], {x: [{pose: 'p1', start: 0, end: 1}]}, REPO_ROOT, {allowSynthetic: true}), /registry is for "character-02-placeholder", not "character-01"/);
  const unnamed = writePlaceholder(tmp('unnamed'), {mutate: r => { delete r.character; }});
  await assert.rejects(resolveCast([ph({registry: unnamed})], {ph: [{pose: 'p1', start: 0, end: 1}]}, REPO_ROOT, {allowSynthetic: true}), /does not name its character/);
  await assert.rejects(resolveCast([ph()], {ph: [{pose: 'p1', start: 0, end: 1}]}), /SYNTHETIC test placeholder, not artwork/);
  // Changing the placeholder's registry (sizes and artwork) leaves Character 01's render plan byte-identical.
  const base = await build(SCENES.A1());
  const changedReg = writePlaceholder(tmp('changed'), {mutate: r => { for (const p of Object.values(r.poses)) p.figureHeight = 560; }});
  const s = SCENES.A1(); s.scenes[0].cast[1].registry = changedReg;
  const changed = await build(s);
  assert.equal(JSON.stringify(layersOf(changed.project, C01)), JSON.stringify(layersOf(base.project, C01)), 'Character 01 layers unchanged');
  assert.notEqual(JSON.stringify(layersOf(changed.project, PH)), JSON.stringify(layersOf(base.project, PH)), 'placeholder layers did change');
});

// ---------------------------------------------------------------------------------------------------- A-2
test('A-2 pose timelines: changing one member\'s poses changes no layer of the other member', async () => {
  const base = await build(SCENES.A1());
  const s1 = SCENES.A1(); for (const i of [3, 5, 7]) s1.scenes[0].lines[i].pose = 'p3';
  const phChanged = await build(s1);
  assert.equal(JSON.stringify(layersOf(phChanged.project, C01)), JSON.stringify(layersOf(base.project, C01)));
  assert.notEqual(JSON.stringify(layersOf(phChanged.project, PH)), JSON.stringify(layersOf(base.project, PH)));
  const s2 = SCENES.A1(); s2.scenes[0].lines[2].pose = '06'; s2.scenes[0].lines[6].pose = '02';
  const c01Changed = await build(s2);
  assert.equal(JSON.stringify(layersOf(c01Changed.project, PH)), JSON.stringify(layersOf(base.project, PH)));
  assert.notEqual(JSON.stringify(layersOf(c01Changed.project, C01)), JSON.stringify(layersOf(base.project, C01)));
  // Each member's own timeline: one segment per change, in order, ending where the next begins.
  const segs = id => base.report.character.filter(d => d.cast === id).map(d => [d.pose, d.from, d.to]);
  assert.deepEqual(segs('c01'), [['02', 0, 3], ['03', 3, 6], ['05', 6, 9], ['06', 9, 13]]);
  assert.deepEqual(segs('ph').map(x => x[0]), ['p1', 'p2', 'p1', 'p2', 'p1']);
});

// ---------------------------------------------------------------------------------------------------- A-3
test('A-3 placement: every key of every member puts its feet within 1 px and its height within 1 px of the declared values (every Track A scene)', async () => {
  for (const name of Object.keys(SCENES)) {
    const s = SCENES[name](), b = await build(s), cast = s.scenes[0].cast, by = await layersByMember(b.project, b.report, cast);
    for (const m of cast) {
      assert.ok(by[m.id].length > 0, `${name}: ${m.id} is drawn`);
      for (const {layer, info} of by[m.id]) for (const key of layer.keys) {
        const w = worldOf(key, info, shotsOf(b.report));
        assert.ok(Math.abs(w.feetX - m.placement.feetX) <= 1 && Math.abs(w.feetY - m.placement.feetY) <= 1, `${name} ${m.id} feet at ${key.t}s: ${w.feetX.toFixed(2)},${w.feetY.toFixed(2)}`);
        assert.ok(Math.abs(w.figureHeight - m.placement.figureHeight) <= 1, `${name} ${m.id} height at ${key.t}s: ${w.figureHeight.toFixed(2)}`);
      }
    }
  }
});

// ---------------------------------------------------------------------------------------------------- A-4 (plan)
test('A-4 layering: every layer of a lower-z member is painted before every layer of a higher-z member (A1, A2, A3a, A3b, A5, A6)', async () => {
  for (const name of ['A1', 'A2', 'A3a', 'A3b', 'A5', 'A6']) {
    const s = SCENES[name](), b = await build(s), cast = [...s.scenes[0].cast].sort((x, y) => x.z - y.z), by = await layersByMember(b.project, b.report, cast);
    for (let i = 1; i < cast.length; i++) {
      const lastBack = Math.max(...by[cast[i - 1].id].map(x => x.index)), firstFront = Math.min(...by[cast[i].id].map(x => x.index));
      assert.ok(lastBack < firstFront, `${name}: ${cast[i - 1].id} (z ${cast[i - 1].z}) before ${cast[i].id} (z ${cast[i].z})`);
    }
  }
});

// ---------------------------------------------------------------------------------------------------- renderer pixel helpers
const C01_SIGNATURE = [[252, 222, 180], [188, 76, 21], [132, 86, 59]];      // skin, rust, shoe (palette.mjs CANON)
const PH_SIGNATURE = Object.values(PLACEHOLDER_COLOURS);
const near = (d, i, c, tol) => Math.abs(d[i] - c[0]) <= tol && Math.abs(d[i + 1] - c[1]) <= tol && Math.abs(d[i + 2] - c[2]) <= tol;
async function painters(b, removals) {
  const {core, render} = await rendererModules();
  const out = {full: await render.painter(core.loadProject(b.projectFile))};
  for (const [name, pred] of Object.entries(removals)) {
    const p = structuredClone(b.project); p.shots[0].layers = p.shots[0].layers.filter(l => !pred(l));
    const f = path.join(b.dir, `project-without-${name}.json`); fs.writeFileSync(f, JSON.stringify(p));
    out[name] = await render.painter(core.loadProject(f));
  }
  return out;
}
const pixels = (draw, t) => { const f = draw(t); return {w: f.width, h: f.height, d: f.getContext('2d').getImageData(0, 0, f.width, f.height).data}; };
// Pixels a member contributes at time t: where the frame changes when that member's pose layers are removed.
function contribution(full, without) { const m = []; for (let i = 0; i < full.d.length; i += 4) if (full.d[i] !== without.d[i] || full.d[i + 1] !== without.d[i + 1] || full.d[i + 2] !== without.d[i + 2]) m.push(i); return m; }
// How strongly the member changes a pixel (largest channel difference). At anti-aliased edges a member may cover a
// pixel by only a few per cent; that pixel is still mostly background (e.g. the rug), which can resemble any colour.
// A "foreign" colour only counts where the member visibly paints the pixel.
const STRONG = 60;
const change = (full, without, i) => Math.max(Math.abs(full.d[i] - without.d[i]), Math.abs(full.d[i + 1] - without.d[i + 1]), Math.abs(full.d[i + 2] - without.d[i + 2]));
// Where a member SHOULD be at time t, worked out from the scene's own declarations only (never from the render plan):
// the declared placement, the pose the lines declare at t, and the declared shot's camera. Output pixels. Medium and
// close shots are composed (pan within the background), so their pivot is taken from the report; the composition rules
// are verified independently of this in A-7 and in the review-correction tests.
const ZOOM = {wide: 1, medium: 1.3, close: 1.5};
const zoomOf = cam => { const n = cam.toLowerCase(), m = n.match(/medium ([\d.]+)/); return m ? +m[1] : ZOOM[n.split(/[\s,]/)[0]]; };
async function declaredRect(scene, memberId, t, plane, ppu, report) {
  const m = scene.cast.find(c => c.id === memberId);
  let cursor = 0, pose = null, shot = null, zoom = 1;
  for (const l of scene.lines) {
    const z = zoomOf(l.shot.camera); if (z !== undefined) zoom = z;
    if (cursor > t + 1e-9) break;
    const poses = {...(l.poses || {}), ...(l.pose !== undefined ? {[l.speaker]: l.pose} : {})};
    if (poses[memberId] !== undefined) pose = poses[memberId];
    shot = {focus: l.shot.focus ?? null, zoom};
    cursor += l.duration;
  }
  const reg = loadRegistry(m.registry ?? path.join(PRODUCTION_ROOT, 'characters', `${m.character}.json`)), info = await poseInfo(reg, pose, REPO_ROOT);
  const k = m.placement.figureHeight / info.figureHeight, world = {x: m.placement.feetX - info.feet.x * k, y: m.placement.feetY - info.feet.y * k, w: info.width * k, h: info.height * k};
  const rs = shotsOf(report).find(x => t >= x.start - 1e-9 && t < x.end - 1e-9) ?? shotsOf(report).at(-1);
  const pivot = shot.zoom > 1 ? rs.pivot : {x: plane.width / 2, y: plane.height / 2};
  const sx = v => ((v - pivot.x) * shot.zoom + pivot.x) * ppu, sy = v => ((v - pivot.y) * shot.zoom + pivot.y) * ppu;
  return {x0: sx(world.x), y0: sy(world.y), x1: sx(world.x + world.w), y1: sy(world.y + world.h)};
}
const sampleTimes = (report, until) => {
  const t = new Set();
  for (let x = 0.25; x < until; x += 0.5) t.add(+x.toFixed(3));
  for (const d of report.character) if (d.from > 0 && d.from < until) t.add(+(d.from + 1 / 30).toFixed(4));
  return [...t].sort((a, b) => a - b);
};

// True when pixel i of the full frame is an anti-aliased edge of one of the given flat colours over what lies behind it
// (the frame without that member): full = a*colour + (1-a)*behind for some a in [0, 1], within a few levels. Such a pixel
// is that member's own edge, even when the mix happens to resemble another character's colour (e.g. blue over the rust rug
// looks like a shoe brown).
function blendOf(full, behind, i, colours, tol = 6) {
  const f = [full.d[i], full.d[i + 1], full.d[i + 2]], g = [behind.d[i], behind.d[i + 1], behind.d[i + 2]];
  return colours.some(c => {
    const d = c.map((v, k) => v - g[k]), dd = d.reduce((a, v) => a + v * v, 0);
    const a = Math.min(1, Math.max(0, dd ? d.reduce((s, v, k) => s + v * (f[k] - g[k]), 0) / dd : 0));
    return f.every((v, k) => Math.abs(v - (g[k] + a * d[k])) <= tol);
  });
}
// Identity separation in rendered frames for a Character 01 + placeholder scene. Returns counts for assertions.
// Each artwork's pixels are found by removing that artwork's layers; they must show only that artwork's colours and lie
// inside the rectangle the SCENE declares for that member. A swap therefore shows up as pixels outside their rectangle.
async function separation(b, scene) {
  const ppu = b.project.width / 1280, plane = {width: 1280, height: 1280 * b.project.height / b.project.width};
  const isC01 = l => l.path.includes(`/${C01}-pose-`), isPH = l => l.path.includes(`/${PH}-pose-`);
  const draw = await painters(b, {c01: isC01, ph: isPH});
  const result = {expectedTimes: Math.ceil((b.report.scenes[0].duration - 1.25) / 0.5), times: 0, foreignInC01: 0, foreignInPH: 0, outsideC01: 0, outsidePH: 0, emptyFramed: []};
  const until = b.report.scenes[0].duration - 1;   // before the end card
  for (const t of sampleTimes(b.report, until)) {
    const full = pixels(draw.full, t), wC01 = pixels(draw.c01, t), wPH = pixels(draw.ph, t), cC01 = contribution(full, wC01), cPH = contribution(full, wPH);
    const shot = shotsOf(b.report).find(s => t >= s.start && t < s.end) || shotsOf(b.report).at(-1);
    for (const [id, c] of [['c01', cC01], ['ph', cPH]]) if (!c.length && (shot.focus === null || shot.focus === id)) result.emptyFramed.push(`${id}@${t}`);
    for (const i of cC01) if (change(full, wC01, i) > STRONG && PH_SIGNATURE.some(col => near(full.d, i, col, 40))) result.foreignInC01++;
    for (const i of cPH) if (change(full, wPH, i) > STRONG && C01_SIGNATURE.some(col => near(full.d, i, col, 20)) && !blendOf(full, wPH, i, PH_SIGNATURE)) result.foreignInPH++;
    result.strongC01 = (result.strongC01 || 0) + cC01.filter(i => change(full, wC01, i) > STRONG).length;
    result.strongPH = (result.strongPH || 0) + cPH.filter(i => change(full, wPH, i) > STRONG).length;
    for (const [id, c, key] of [['c01', cC01, 'outsideC01'], ['ph', cPH, 'outsidePH']]) {
      const r = await declaredRect(scene, id, t, plane, ppu, b.report);
      for (const i of c) { const p = i / 4, x = p % full.w, y = Math.floor(p / full.w); if (x < r.x0 - 3 || x > r.x1 + 3 || y < r.y0 - 3 || y > r.y1 + 3) result[key]++; }
    }
    result.times++;
  }
  return result;
}

// ---------------------------------------------------------------------------------------------------- A-4 (pixels)
test('A-4 layering in pixels: where the two overlap, the front member is what is seen, in both orders (A3a, A3b)', needsRenderer, async () => {
  const isC01 = l => l.path.includes(`/${C01}-pose-`), isPH = l => l.path.includes(`/${PH}-pose-`), t = 0.75;
  const a = await build(SCENES.A3a()), b = await build(SCENES.A3b());
  const da = await painters(a, {c01: isC01}), db = await painters(b, {c01: isC01});
  const fa = pixels(da.full, t), fb = pixels(db.full, t);
  // Placeholder body pixels when it is in front (A3a).
  const body = []; for (let i = 0; i < fa.d.length; i += 4) if (near(fa.d, i, PLACEHOLDER_COLOURS.body, 2)) body.push(i);
  assert.ok(body.length > 1000, 'the placeholder body is visible in front');
  // A3a: Character 01 is behind, so removing it changes none of those body pixels.
  const ca = new Set(contribution(fa, pixels(da.c01, t)));
  assert.equal(body.filter(i => ca.has(i)).length, 0, 'Character 01 never paints over the front placeholder');
  // A3b: Character 01 is in front; wherever it is strongly visible over the placeholder body, the pixel is Character 01's, not blue.
  const nb = pixels(db.c01, t), strong = body.filter(i => Math.max(Math.abs(fb.d[i] - nb.d[i]), Math.abs(fb.d[i + 1] - nb.d[i + 1]), Math.abs(fb.d[i + 2] - nb.d[i + 2])) > 100);
  assert.ok(strong.length > 200, `Character 01 overlaps the placeholder body (${strong.length} px)`);
  assert.equal(strong.filter(i => near(fb.d, i, PLACEHOLDER_COLOURS.body, 40)).length, 0, 'the front Character 01 wins every overlapping pixel');
});

// ---------------------------------------------------------------------------------------------------- A-5
test('A-5 identity separation in rendered frames: zero foreign pixels in each member\'s area, all inside its own rectangle (A1, A2, A4, A5)', needsRenderer, async () => {
  for (const name of ['A1', 'A2', 'A4', 'A5']) {
    const s = SCENES[name](), b = await build(s), r = await separation(b, s.scenes[0]);
    assert.ok(r.times >= r.expectedTimes && r.times >= 6, `${name}: sampled ${r.times} times (every 0.5 s needs ${r.expectedTimes}, plus every pose change)`);
    assert.ok(r.strongC01 > 100000 && r.strongPH > 100000, `${name}: both members visibly painted (${r.strongC01}, ${r.strongPH} px)`);
    assert.deepEqual(r.emptyFramed, [], `${name}: every framed member is visible`);
    assert.deepEqual([r.foreignInC01, r.foreignInPH], [0, 0], `${name}: no placeholder colour in Character 01's pixels and no Character 01 colour in the placeholder's`);
    assert.deepEqual([r.outsideC01, r.outsidePH], [0, 0], `${name}: every member's pixels lie within its own rectangle`);
  }
});

test('A-5 sensitivity: a deliberately swapped render plan is caught', needsRenderer, async () => {
  const s = SCENES.A1(), b = await build(s);
  const c01Layer = b.project.shots[0].layers.find(l => l.path.includes(`/${C01}-pose-`)), phLayer = b.project.shots[0].layers.find(l => l.path.includes(`/${PH}-pose-`));
  const swapped = structuredClone(b.project);
  for (const l of swapped.shots[0].layers) { if (l.path === c01Layer.path) l.path = phLayer.path; else if (l.path === phLayer.path) l.path = c01Layer.path; }
  fs.writeFileSync(b.projectFile, JSON.stringify(swapped));
  const r = await separation({...b, project: swapped}, s.scenes[0]);
  assert.ok(r.outsideC01 > 1000 && r.outsidePH > 1000, `the swap is detected: each artwork appears outside its declared place (${r.outsideC01}, ${r.outsidePH} px)`);
});

// ---------------------------------------------------------------------------------------------------- A-6
// Screen geometry of every member at time t, read from the render plan's own keys: null when the member has no layer
// on screen at t (off camera in a single). Design units (the 1280-wide plane).
async function framedAt(b, cast, t) {
  const by = await layersByMember(b.project, b.report, cast), out = {};
  for (const m of cast) {
    const cur = by[m.id].find(({layer}) => t >= layer.from && t < layer.to);
    if (!cur) { out[m.id] = null; continue; }
    const key = cur.layer.keys.reduce((a, k) => (k.t <= t + 1e-6 ? k : a)), k = key.w / cur.info.width;
    out[m.id] = {x0: key.x, x1: key.x + key.w, feetX: key.x + cur.info.feet.x * k, top: key.y + (cur.info.feet.y - cur.info.figureHeight) * k};
  }
  return out;
}
// The framing rules of the owner review, checked on what is actually drawn.
function assertFraming(fr, shot, where, W = 1280) {
  const centre = c => (c.x0 + c.x1) / 2;
  const cut = c => c.x1 > 1 && c.x0 < W - 1 && (c.x0 < -1 || c.x1 > W + 1);
  for (const [id, c] of Object.entries(fr)) if (c) assert.ok(!cut(c), `${where}: ${id} is cut by the frame edge (${c.x0.toFixed(1)}..${c.x1.toFixed(1)})`);
  if (shot.zoom <= 1) return;
  const f = fr[shot.focus];
  assert.ok(f && f.x0 >= -1 && f.x1 <= W + 1, `${where}: the focus member ${shot.focus} is fully in frame`);
  for (const [id, c] of Object.entries(fr)) {
    if (id === shot.focus) continue;
    if (shot.single) { assert.equal(c, null, `${where}: single, so ${id} is off camera`); continue; }
    if (!c || c.x1 <= 1 || c.x0 >= W - 1) continue;                 // fully out of frame
    assert.ok(Math.abs(centre(f) - W / 2) + 0.1 * W <= Math.abs(centre(c) - W / 2) + 1, `${where}: ${shot.focus} is clearly more central than ${id}`);
  }
}
// Which way a bubble's tail points: the mean x of the tail's own pixels (rows below the body and its drop shadow).
async function tailSide(file, ppu) {
  const img = await canvas.loadImage(file), c = canvas.createCanvas(img.width, img.height), ctx = c.getContext('2d'); ctx.drawImage(img, 0, 0);
  const o = BUBBLE_DEFAULTS, H = img.height / ppu, y0 = Math.ceil((H - o.tail - o.outline + 2) * ppu), y1 = Math.floor((H - o.drop - o.outline - 1) * ppu);
  const d = ctx.getImageData(0, y0, img.width, y1 - y0).data; let sx = 0, n = 0;
  for (let i = 0; i < d.length; i += 4) if (d[i + 3] > 128) { sx += (i / 4) % img.width; n++; }
  assert.ok(n > 10, `${path.basename(file)}: the tail is drawn`);
  return sx / n < img.width / 2 ? 'left' : 'right';
}
// Bubble placement rules of the owner review: each bubble is on the side where its speaker stands in that line's shot,
// its tail points that way, and its style is the speaker's own.
async function assertBubbles(b, cast, where) {
  const ppu = b.project.width / 1280, shots = shotsOf(b.report);
  for (const l of b.report.scenes[0].lines) {
    const t = +(l.start + 0.01).toFixed(4), fr = await framedAt(b, cast, t), m = cast.find(c => c.id === l.speaker);
    const shot = shots.find(x => t >= x.start - 1e-9 && t < x.end - 1e-9);
    // Off camera (a single on someone else): where its feet would be through this shot's camera.
    const x = fr[m.id] ? fr[m.id].feetX : (m.placement.feetX - shot.pivot.x) * shot.zoom + shot.pivot.x;
    const side = x < 640 ? 'left' : 'right';
    assert.equal(l.side, side, `${where} line ${l.id}: bubble on the speaker's side (${l.speaker} at x ${x.toFixed(0)})`);
    assert.equal(JSON.stringify(l.style), JSON.stringify(m.speech.style), `${where} line ${l.id}: style from the speaker's configuration`);
    const layer = b.project.shots[0].layers.find(y => y.path.includes(`/line-${l.id}-`));
    if (side === 'left') assert.equal(layer.x, FACE_TO_FACE_DEFAULTS.marginX, `${where} line ${l.id}: left bubble at the left margin`);
    else assert.ok(Math.abs(layer.x + layer.w - (1280 - FACE_TO_FACE_DEFAULTS.marginX)) < 0.6, `${where} line ${l.id}: right bubble at the right margin`);
    assert.equal(await tailSide(path.join(b.dir, layer.path), ppu), side, `${where} line ${l.id}: the tail points to the speaker's side`);
  }
}

test('A-6 speaker attribution: each line is spoken by its cast member; style comes from that member, and the bubble sits on the side where the speaker stands (original and swapped positions)', async () => {
  const a1 = await build(SCENES.A1()), a2 = await build(SCENES.A2());
  const expected = DIALOGUE().map(l => l.speaker);
  for (const [name, b] of [['A1', a1], ['A2', a2]]) {
    const lines = b.report.scenes[0].lines;
    assert.deepEqual(lines.map(l => l.speaker), expected);
    for (const l of lines) assert.deepEqual([l.character, l.style], l.speaker === 'c01' ? [C01, 'him'] : [PH, 'neutral'], `${name} line ${l.id}`);
    await assertBubbles(b, (name === 'A1' ? SCENES.A1() : SCENES.A2()).scenes[0].cast, name);
  }
  // Original positions: Character 01 left, placeholder right. Swapped: the bubbles swap with them; the styles do not.
  assert.deepEqual(a1.report.scenes[0].lines.map(l => [l.speaker, l.side]), expected.map(id => [id, id === 'c01' ? 'left' : 'right']));
  assert.deepEqual(a2.report.scenes[0].lines.map(l => [l.speaker, l.side]), expected.map(id => [id, id === 'c01' ? 'right' : 'left']));
  assert.deepEqual(a1.report.scenes[0].lines.map(l => l.style), a2.report.scenes[0].lines.map(l => l.style), 'swapping positions does not change styling');
  // The drawn bubble's fill is the speaker's style.
  const ppu = a1.project.width / 1280;
  for (const b of [a1, a2]) for (const l of b.report.scenes[0].lines) {
    const layer = b.project.shots[0].layers.find(x => x.path.includes(`/line-${l.id}-`));
    const img = await canvas.loadImage(path.join(b.dir, layer.path)), c = canvas.createCanvas(img.width, img.height), ctx = c.getContext('2d'); ctx.drawImage(img, 0, 0);
    const px = ctx.getImageData(Math.round(img.width / 2), Math.round((BUBBLE_DEFAULTS.outline + 4) * ppu), 1, 1).data;
    const fill = BUBBLE_STYLES[l.style].fill.match(/[0-9a-f]{2}/gi).map(h => parseInt(h, 16));
    assert.ok(fill.every((v, i) => Math.abs(px[i] - v) <= 3), `bubble ${l.id} is drawn in the ${l.style} style`);
  }
  // A declared side is a constraint, never a silent override: it holds where it agrees and fails where it does not.
  const agreeing = SCENES.A1(); agreeing.scenes[0].cast[0].speech.side = 'left'; agreeing.scenes[0].cast[1].speech.side = 'right';
  assert.equal(sha(fs.readFileSync((await build(agreeing)).projectFile)), sha(fs.readFileSync(a1.projectFile)), 'a declared side that agrees changes nothing');
  const contradicting = SCENES.A2(); contradicting.scenes[0].cast.find(c => c.id === 'c01').speech.side = 'left';
  await assert.rejects(build(contradicting), /line 1: speaker "c01" stands on the right of the frame, but its speech\.side is "left"/);
  // Text chat is unchanged: a speaker linked to a cast member takes that member's style, on the speaker's own side.
  const chat = {schema: 'oddly-relatable/story@1', id: 'chat-linked', endCard: {duration: 1, caption: 'Technical test'}, scenes: [{id: 'chat', format: 'text-chat', environment: 'living-room-empty-03',
    cast: [{...c01(), speech: {style: 'him', side: 'right'}}], reactionCast: 'c01', speakers: {me: {side: 'left', cast: 'c01'}, them: {side: 'right', style: 'neutral'}},
    events: [{type: 'message', speaker: 'me', text: 'Linked to the cast member.', duration: 2, pose: '02'}, {type: 'message', speaker: 'them', text: 'Explicit style.', duration: 2}]}]};
  const ch = await build(chat);
  assert.deepEqual(ch.sequence.messages.map(m => [m.speaker, m.side, m.style]), [['me', 'left', 'him'], ['them', 'right', 'neutral']]);
});

// ---------------------------------------------------------------------------------------------------- A-7
test('A-7 camera: each shot frames its declared member; singles show only that member; nobody is cut by the frame edge; positions and scale are kept', async () => {
  const s = SCENES.A4(), b = await build(s), shots = shotsOf(b.report), cast = s.scenes[0].cast;
  assert.deepEqual(shots.map(x => [x.speaker, x.focus, x.zoom, x.single]), [['c01', null, 1, false], ['ph', 'ph', 1.3, true], ['c01', 'c01', 1.3, true], ['ph', 'c01', 1.5, true], ['c01', 'ph', 1.5, true], ['ph', null, 1, false]]);
  assert.deepEqual(shots.filter(x => x.focus && x.focus !== x.speaker).map(x => x.focus), ['c01', 'ph'], 'reaction shots frame the declared reactor, not the speaker');
  const seen = {};
  for (const x of shots) for (const dt of [0.05, 0.75, 1.45]) {
    const t = +(x.start + dt).toFixed(4), fr = await framedAt(b, cast, t);
    assertFraming(fr, x, `A4 line ${x.line} t ${t}`);
    seen[x.line] = Object.keys(fr).filter(id => fr[id] && fr[id].x1 > 1 && fr[id].x0 < 1279);
    // Vertical framing as before: the focus member's head top stays where the pivot holds it.
    if (x.focus) assert.ok(Math.abs(fr[x.focus].top - x.pivot.y) <= 1, `line ${x.line}: ${x.focus}'s head top holds the pivot height`);
  }
  // Distinct medium shots: the single on the placeholder and the single on Character 01 show different members.
  assert.deepEqual([seen[2], seen[3]], [['ph'], ['c01']]);
  assert.deepEqual([seen[4], seen[5]], [['c01'], ['ph']], 'each close reaction shot shows only its subject');
  assert.deepEqual([seen[1], seen[6]], [['c01', 'ph'], ['c01', 'ph']], 'wide shots show both');
  // The focus member is nearer the frame centre than in the previous head-pivot camera, which left it where it stood.
  for (const x of shots.filter(y => y.focus)) {
    const m = cast.find(c => c.id === x.focus), fr = await framedAt(b, cast, +(x.start + 0.75).toFixed(4));
    const oldX = (m.placement.feetX - m.placement.feetX) * x.zoom + m.placement.feetX;   // head pivot: feet x unchanged on screen
    assert.ok(Math.abs(fr[x.focus].feetX - 640) < Math.abs(oldX - 640) - 50, `line ${x.line}: ${x.focus} is framed towards the centre`);
  }
  assert.ok(b.report.checks.ok, JSON.stringify(b.report.checks.issues));
  assert.deepEqual(b.report.camera[0].cuts.map(c => [c.t, c.to, c.focus]), [[1.5, 1.3, 'ph'], [3, 1.3, 'c01'], [4.5, 1.5, 'c01'], [6, 1.5, 'ph'], [7.5, 1, null]]);
});

// ---------------------------------------------------------------------------------------------------- review corrections
// Owner review of A2 and A4: the same rules on stagings other than the test scenes (positions, heights, depth, facing,
// three members), every focus, medium and close, two-shot and single. Nothing here depends on A2 or A4 coordinates.
test('Review corrections: bubble side and framing rules hold for other stagings, cast sizes and shot types', async () => {
  const STAGINGS = {
    apart: [c01({x: 260, h: 640}), ph({x: 1020, h: 640, facing: 'left'})],
    swapped: [c01({x: 900, z: 1}), ph({x: 380, z: 0, facing: 'right'})],
    close: [c01({x: 520}), ph({x: 760, facing: 'left'})],
    depth: [c01({x: 480, z: 1}), ph({x: 840, feetY: 1950, h: 600, z: 0})],
    three: [c01({x: 330, h: 700}), ph({id: 'ph-a', x: 700, h: 600, z: 1, style: 'neutral'}), ph({id: 'ph-b', x: 1020, h: 600, z: 2, style: 'her'})],
    // Small figures near the left edge: the background stops the camera centring Character 01, so the placeholder would
    // be the more central figure in a two-shot on Character 01 (nothing is cut, so only the clear-subject rule can refuse).
    edge: [c01({x: 170, h: 420}), ph({x: 470, h: 420, facing: 'left'})],
  };
  const FRAMING_ERROR = /would cut "[\w-]+" at the frame edge|would not be the clear subject|does not fit inside this frame/;
  const tally = {built: 0, singles: 0, twoShots: 0, refused: 0}, refusals = [];
  for (const [name, cast] of Object.entries(STAGINGS)) {
    const firstPoses = Object.fromEntries(cast.map(m => [m.id, m.character === C01 ? '02' : 'p1']));
    for (const focus of cast.map(m => m.id)) for (const camera of ['Medium 1.3x', 'Close']) for (const single of [false, true]) {
      const other = cast.find(m => m.id !== focus).id;
      const lines = [
        {speaker: cast[0].id, text: 'Wide first.', duration: 1.5, poses: firstPoses, shot: {camera: 'Wide'}},
        {speaker: focus, text: 'On the focus.', duration: 1.5, shot: {camera, focus, ...(single ? {single} : {})}},
        {speaker: other, text: 'Reaction.', duration: 1.5, shot: {camera: 'Hold', focus, ...(single ? {single} : {})}},
      ];
      const where = `${name} ${camera} on ${focus}${single ? ' (single)' : ''}`, sc = story(`rc-${name}`, structuredClone(cast), lines);
      let b;
      try { b = await build(sc); } catch (e) {
        assert.match(e.message, FRAMING_ERROR, `${where}: refused only for a framing reason`);
        assert.ok(!single, `${where}: a single never needs refusing`);
        tally.refused++; refusals.push(`${where}: ${e.message}`); continue;
      }
      tally.built++; tally[single ? 'singles' : 'twoShots']++;
      assert.ok(b.report.checks.ok, `${where}: ${JSON.stringify(b.report.checks.issues)}`);
      const shots = shotsOf(b.report);
      for (const x of shots) for (const dt of [0.05, 0.75, 1.45]) assertFraming(await framedAt(b, sc.scenes[0].cast, +(x.start + dt).toFixed(4)), x, `${where} line ${x.line}`);
      await assertBubbles(b, sc.scenes[0].cast, where);
      // Positions and relative scale are kept in every shot.
      const by = await layersByMember(b.project, b.report, sc.scenes[0].cast);
      for (const m of sc.scenes[0].cast) for (const {layer, info} of by[m.id]) for (const key of layer.keys) {
        const w = worldOf(key, info, shots);
        assert.ok(Math.abs(w.feetX - m.placement.feetX) <= 1 && Math.abs(w.figureHeight - m.placement.figureHeight) <= 1, `${where}: ${m.id} keeps its place and height at ${key.t}s`);
      }
    }
  }
  assert.equal(tally.singles, 2 * (2 + 2 + 2 + 2 + 3 + 2), 'every single builds');
  assert.ok(tally.twoShots >= 4, `some two-shots build with a clear subject (${tally.twoShots})`);
  assert.ok(tally.refused >= 4, `framings that would cut a member or blur the subject are refused (${tally.refused})`);
  assert.ok(refusals.some(r => /^edge Medium 1\.3x on c01: .*"c01" would not be the clear subject \("ph" is about as central/.test(r)), 'a two-shot whose subject is not the most central figure is refused');
  assert.ok(refusals.some(r => /would cut "[\w-]+" at the frame edge/.test(r)), 'a two-shot that would cut a member is refused');
  // The owner's A4 shot 5 case (close on the placeholder, Character 01 at the edge) is refused as a two-shot, with a reason.
  const a4 = SCENES.A4(); delete a4.scenes[0].lines[4].shot.single;
  await assert.rejects(build(a4), /line 5 \(Close on ph\): .*(would cut "c01" at the frame edge|would not be the clear subject)/);
});

// ---------------------------------------------------------------------------------------------------- A-8
test('A-8 no silent defaults: missing or invalid characters, registries, facings, formats, speakers and focus are errors', async () => {
  const bad = async (mutate, pattern) => { const s = SCENES.A1(); mutate(s.scenes[0], s); await assert.rejects(build(s), pattern); };
  // Facing is data: placeholder artwork exists for left and right; Character 01 declares no facing; nothing is mirrored.
  const right = await build(SCENES.A2());
  assert.deepEqual([...new Set(right.report.character.filter(d => d.cast === 'ph').map(d => `${d.requestedPose}>${d.pose}`))].sort(), ['p1>p1-r', 'p2>p2-r']);
  await bad(sc => { sc.cast[0].facing = 'left'; }, /pose "02" of character-01 has no artwork facing "left" \(its facing is not declared\)\. Artwork is never mirrored/);
  await bad(sc => { sc.cast[1].facing = 'right'; sc.lines[3].pose = 'p3'; }, /pose "p3" of character-02-placeholder has no artwork facing "right" \(it faces "left"\)/);
  await bad(sc => { sc.cast[1].facing = 'up'; }, /facing "up" is not one of native, left, right, front/);
  await bad(sc => { sc.cast[0].mirror = true; }, /"mirror" is not supported\. Artwork is never mirrored/);
  const badVariant = writePlaceholder(tmp('variant'), {mutate: r => { r.poses.p1.facingVariants.right = 'p3'; }});
  await bad(sc => { sc.cast[1].registry = badVariant; sc.cast[1].facing = 'right'; }, /its "right" variant "p3" is missing or not declared as facing "right"/);
  assert.throws(() => loadRegistry(writePlaceholder(tmp('ghost'), {mutate: r => { r.poses.p1.facingVariants.right = 'ghost'; }})), /names unknown pose "ghost"/);
  // Characters and registries.
  await bad(sc => { delete sc.cast[0].character; }, /character ID is required/);
  await bad(sc => { sc.cast[0].character = 'character-99'; }, /no registry for character "character-99"/);
  assert.throws(() => episodeToStory({schema: 'oddly-relatable/conversation-episode@1', character: {registry: 'production/characters/missing.json'}}), /cannot read registry/);
  const unnamed = path.join(tmp('unnamed-ep'), 'reg.json'); fs.writeFileSync(unnamed, JSON.stringify({poses: {}}));
  assert.throws(() => episodeToStory({schema: 'oddly-relatable/conversation-episode@1', character: {registry: unnamed}}), /does not name its character/);
  // Formats.
  assert.throws(() => validateStory({schema: 'oddly-relatable/story@1', scenes: [{id: 'x'}]}), /scene x: "format" is required/);
  assert.throws(() => validateStory({schema: 'oddly-relatable/story@1', scenes: [{id: 'x', format: 'musical'}]}), /Unknown scene format "musical"/);
  // Speakers and styles.
  await bad(sc => { sc.lines[1].speaker = 'nobody'; }, /line 2: speaker "nobody" is not a cast member/);
  await bad(sc => { delete sc.cast[1].speech; }, /cast member "ph" has no "speech" configuration/);
  await bad(sc => { sc.cast[1].speech.style = 'sparkly'; }, /unknown bubble style "sparkly"/);
  await bad(sc => { sc.cast[1].speech.side = 'middle'; }, /speech: side must be "left" or "right"/);
  assert.throws(() => renderBubble({text: 'x', side: 'left'}), /Bubble style is required/);
  assert.throws(() => renderTypingShell({side: 'right'}), /Typing indicator style is required/);
  const chat = (speakers, extra = {}) => ({schema: 'oddly-relatable/story@1', id: 'chat', endCard: {duration: 1, caption: 'x'}, scenes: [{id: 'chat', format: 'text-chat', environment: 'living-room-empty-03',
    cast: [c01()], reactionCast: 'c01', speakers, events: [{type: 'message', speaker: 'a', text: 'Hello.', duration: 2, pose: '02'}], ...extra}]});
  await assert.rejects(build(chat({a: {side: 'left'}})), /speaker a: no bubble style.*never chosen from the side/);
  await assert.rejects(build(chat({a: {side: 'left', cast: 'ghost'}})), /cast member "ghost" is not in this scene/);
  await assert.rejects(build(chat({a: {side: 'left', cast: 'c01', style: 'her'}})), /style differs from cast member "c01"/);
  // Camera and cast.
  await assert.rejects(build(chat({a: {side: 'left', style: 'her'}}, {camera: {focus: 'ghost'}})), /camera focus "ghost" is not a cast member/);
  await assert.rejects(build(chat({a: {side: 'left', style: 'her'}}, {reactionCast: 'ghost'})), /reactionCast "ghost" is not a cast member/);
  await bad(sc => { sc.lines[1].shot = {camera: 'Medium 1.3x'}; }, /line 2: a medium or close shot needs a "focus" cast member/);
  await bad(sc => { sc.lines[1].shot = {camera: 'Wide', single: true}; }, /line 2: "single" applies to medium and close shots only/);
  await bad(sc => { sc.lines[1].shot = {camera: 'Close', focus: 'ph', single: 'yes'}; }, /line 2: shot "single" must be true or false/);
  await bad(sc => { sc.cast[0].speech.side = 'right'; }, /line 1: speaker "c01" stands on the left of the frame, but its speech\.side is "right"/);
  await bad(sc => { sc.lines[1].shot = {camera: 'Close', focus: 'ghost'}; }, /shot focus "ghost" is not a cast member/);
  await bad(sc => { sc.lines[1].shot = {camera: 'Slow push-in to 1.2x', focus: 'ph'}; }, /wide \/ medium N× \/ close \/ hold framings only/);
  await bad(sc => { delete sc.lines[0].shot; }, /line 1: "shot" with a camera framing is required/);
  await bad(sc => { sc.lines[0].shot = {camera: 'Hold'}; }, /the first shot needs a framing/);
  await bad(sc => { sc.lines[0].poses = {c01: '02'}; }, /the first reaction pose of "ph" must start at 0/);
  await bad(sc => { sc.lines[0].poses = {c01: '02'}; for (const l of sc.lines) if (l.speaker === 'ph') delete l.pose; }, /cast member "ph" has no pose: give every cast member a pose on the first line/);
  await bad(sc => { sc.lines[0].poses.ghost = '02'; }, /pose for "ghost", which is not a cast member/);
  // The synthetic placeholder never reaches production: refused without allowSynthetic, and the production run never passes it.
  await assert.rejects(compileProject(SCENES.A1(), {outDir: tmp('nosynth')}), /SYNTHETIC test placeholder, not artwork/);
  assert.ok(!fs.readFileSync(path.join(PRODUCTION_ROOT, 'lib', 'produce.mjs'), 'utf8').includes('allowSynthetic'), 'the production run never allows synthetic registries');
  for (const f of fs.readdirSync(path.join(PRODUCTION_ROOT, 'characters'))) {
    const r = json(path.join(PRODUCTION_ROOT, 'characters', f));
    assert.ok(r.synthetic !== true && !/placeholder/i.test(r.character), `${f} is not a placeholder`);
  }
  assert.match((await build(SCENES.A1())).report.syntheticPlaceholder, /SYNTHETIC test placeholder registry/);
});

// ---------------------------------------------------------------------------------------------------- A-9
test('A-9 determinism: the same story gives a byte-identical render plan, report and assets twice (every Track A scene)', async () => {
  for (const name of Object.keys(SCENES)) {
    const a = await build(SCENES[name]()), b = await build(SCENES[name]());
    assert.equal(sha(fs.readFileSync(a.projectFile)), sha(fs.readFileSync(b.projectFile)), `${name} project`);
    assert.equal(sha(fs.readFileSync(path.join(a.dir, 'layout-report.json'))), sha(fs.readFileSync(path.join(b.dir, 'layout-report.json'))), `${name} report`);
    const files = d => Object.fromEntries(['assets/gen', 'assets/src'].flatMap(s => fs.readdirSync(path.join(d, s)).map(f => [`${s}/${f}`, sha(fs.readFileSync(path.join(d, s, f)))])));
    assert.deepEqual(files(a.dir), files(b.dir), `${name} assets`);
  }
});

// ---------------------------------------------------------------------------------------------------- A-10
test('A-10 regression: Short 001, the AP-78 fixture and the AP-79 two-member fixture compile byte-identically to the pre-AP-85 baseline', async () => {
  const ev = json(EVIDENCE);
  for (const [name, src] of Object.entries(ev.sources)) {
    const dir = tmp(`reg-${name}`), r = await compileProject(path.join(REPO_ROOT, src), {outDir: dir});
    const want = ev.builds[name];
    assert.equal(sha(fs.readFileSync(r.projectFile)), want.projectSha256, `${name}: project.json`);
    assert.equal(sha(fs.readFileSync(path.join(dir, 'layout-report.json'))), want.layoutReportSha256, `${name}: layout report`);
    const files = Object.fromEntries(['assets/gen', 'assets/src'].flatMap(s => fs.readdirSync(path.join(dir, s)).sort().map(f => [`${s}/${f}`, sha(fs.readFileSync(path.join(dir, s, f)))])));
    assert.deepEqual(files, want.files, `${name}: assets`);
  }
});

test('A-10 regression in pixels: Short 001 frames painted by the renderer are identical to the pre-AP-85 baseline', needsRenderer, async () => {
  const ev = json(EVIDENCE), dir = tmp('reg-frames'), r = await compileProject(path.join(REPO_ROOT, ev.sources.story), {outDir: dir});
  const {core, render} = await rendererModules(), draw = await render.painter(core.loadProject(r.projectFile));
  for (const [t, want] of Object.entries(ev.builds.story.frames)) {
    const f = draw(Number(t)), d = f.getContext('2d').getImageData(0, 0, f.width, f.height).data;
    assert.equal(sha(Buffer.from(d.buffer)), want, `frame at ${t}s`);
  }
});

// ---------------------------------------------------------------------------------------------------- scenes compile cleanly
test('Track A scenes A1 to A6 compile with no layout issues, and the formats registry lists face-to-face as implemented', async () => {
  for (const name of Object.keys(SCENES)) {
    const b = await build(SCENES[name]());
    assert.ok(b.report.checks.ok, `${name}: ${JSON.stringify(b.report.checks.issues)}`);
    assert.equal(b.report.scenes[0].format, 'face-to-face');
  }
  assert.equal(FORMATS['face-to-face'].implemented, true);
  assert.ok(validateCast([c01(), ph()]));
});
