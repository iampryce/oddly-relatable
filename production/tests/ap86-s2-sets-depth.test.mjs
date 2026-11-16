// AP-86 S2: sets and depth (approved 2026-11-16). Plate-to-world mapping, the floor model, layered plates, depth-derived
// draw order with occluders, explicit z and explicit placement precedence (O3, O4), and per-layer parallax.
//
// S2 ONLY: no staging resolver, props, actions, framing profiles, camera moves or movement (S3 to S5). Sets and the
// second figure are SYNTHETIC, labelled test fixtures written to temporary folders; nothing here is artwork. Pixel
// checks use the UNMODIFIED renderer's painter and need FFMPEG/FFPROBE (skipped, not faked, without them).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {compileProject} from '../lib/scene.mjs';
import {validateStory, STORY_SCHEMA, STORY_SCHEMA_V2} from '../lib/story.mjs';
import {validateStoryReferences, assertCompilable} from '../lib/story-v2.mjs';
import {validateSet, loadSet, resolvePlate, plateWorldRect, plateToWorld, worldToPlate, floorHeightAt} from '../lib/sets.mjs';
import {drawOrder, parallaxCamera, worldPlacement, placementKind, layeringKey} from '../lib/depth.mjs';
import {loadRegistry, poseInfo} from '../lib/character.mjs';
import {designPlane, rendererModules, PRODUCTION_ROOT, REPO_ROOT} from '../lib/runtime.mjs';
import {writePlaceholder, PLACEHOLDER_CHARACTER, PLACEHOLDER_COLOURS} from './fixtures/ap85-placeholder.mjs';
import {writeS2Set, writeSyntheticKit, S2_COLOURS} from './fixtures/ap86-synthetic.mjs';

const needsRenderer = {skip: process.env.FFPROBE ? false : 'set FFMPEG/FFPROBE to run renderer-backed checks'};
const tmp = n => fs.mkdtempSync(path.join(os.tmpdir(), `ap86s2-${n}-`));
const json = f => JSON.parse(fs.readFileSync(f, 'utf8'));
const sha = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const PLANE = designPlane(1080, 1920);
const PH_REG = writePlaceholder(tmp('ph'));
const close = (a, b, tol = 1e-6) => Math.abs(a - b) <= tol;

// ------------------------------------------------------------------------------------------------ scene helpers
const c01 = (placement, extra = {}) => ({id: 'c01', character: 'character-01', placement, speech: {style: 'him'}, ...extra});
const ph = (placement, extra = {}) => ({id: 'ph', character: PLACEHOLDER_CHARACTER, registry: PH_REG, placement, speech: {style: 'neutral'}, ...extra});
const LINES = () => [
  {speaker: 'c01', text: 'In front.', duration: 1.5, poses: {c01: '02', ph: 'p1'}, shot: {camera: 'Wide'}},
  {speaker: 'ph', text: 'Behind the counter.', duration: 1.5, shot: {camera: 'Wide'}},
];
// Default staging: the placeholder stands behind the counter's baseline (0.72 < 0.74); Character 01 stands in front.
const CAST = () => [ph({plateX: 0.4, plateY: 0.72}), c01({plateX: 0.6, plateY: 0.9})];
const setStory = (setFile, cast = CAST(), lines = LINES(), extra = {}) => ({schema: STORY_SCHEMA_V2, id: 's2', endCard: {duration: 1, caption: 'Technical test'},
  scenes: [{id: 's2', format: 'face-to-face', set: 'synthetic-s2', plate: 'wide', setRegistry: setFile, cast, lines, ...extra}]});
const build = async (story, opts = {}) => {
  const dir = tmp('build'), r = await compileProject(story, {outDir: dir, allowSynthetic: true, ...opts});
  return {...r, dir, project: json(r.projectFile)};
};
const layers = b => b.project.shots[0].layers;
const idx = (b, pred) => layers(b).findIndex(pred);
const poseLayer = character => l => l.path.includes(`/${character}-pose-`);
const setLayer = id => l => l.path.includes(`/set-synthetic-s2-wide-${id}-`);

// ------------------------------------------------------------------------------------------------ mapping
test('S2 set mapping: a plate is cover-fitted to the design plane; plate points, layers, marks and surfaces map to world units and back', async () => {
  const R = plateWorldRect({width: 480, height: 480}, PLANE);
  assert.ok(close(R.h, PLANE.height) && close(R.w, PLANE.height) && close(R.x, (PLANE.width - PLANE.height) / 2) && R.y === 0, 'a square plate covers the 9:16 frame, centred');
  const R2 = plateWorldRect({width: 900, height: 1600}, PLANE);
  assert.ok(close(R2.w, PLANE.width, 1e-9) && R2.h >= PLANE.height, 'a taller plate fits the width');
  for (const p of [{x: 0, y: 0}, {x: 1, y: 1}, {x: 0.37, y: 0.81}]) {
    const w = plateToWorld(R, p), back = worldToPlate(R, w);
    assert.ok(close(back.x, p.x) && close(back.y, p.y), 'round trip');
  }
  const {file} = writeS2Set(tmp('map'));
  const plate = await resolvePlate(loadSet('synthetic-s2', {file, allowSynthetic: true}), 'wide', {plane: PLANE, registryFile: file});
  assert.deepEqual(plate.rect, R);
  const counter = plate.layers.find(l => l.id === 'counter');
  assert.ok(close(counter.rect.x, R.x) && close(counter.rect.y, 0.62 * R.h) && close(counter.rect.w, R.w) && close(counter.rect.h, R.w * 96 / 480), 'a cut-out layer sits at its plate rectangle, height from its image');
  assert.deepEqual(plate.layers.map(l => [l.id, l.parallax, l.occluder?.baselineY ?? null]), [['backdrop', 1, null], ['counter', 1, 0.74], ['fore', 1, 1]]);
  assert.ok(close(plate.marks.spot.point.x, R.x + 0.5 * R.w) && close(plate.marks.spot.point.y, 0.8 * R.h), 'marks map to world units (for S3)');
  assert.ok(close(plate.surfaces.top.x0, R.x + 0.1 * R.w) && close(plate.surfaces.top.y, 0.62 * R.h), 'surfaces map to world units (for S3)');
  // Plate errors found when resolving the files.
  const bad = async (mutate, pattern) => { const k = writeS2Set(tmp('bad'), {mutate}); await assert.rejects(resolvePlate(loadSet('synthetic-s2', {file: k.file, allowSynthetic: true}), 'wide', {plane: PLANE, registryFile: k.file}), pattern); };
  await bad(s => { delete s.plates.wide.layers[1].rect; }, /layer counter: its image is 480×96, which does not match the plate's 480×480 shape/);
  await bad(s => { s.plates.wide.layers[1].rect.y = 0.95; }, /layer counter: its rectangle extends outside the plate/);
  await bad(s => { s.plates.wide.layers[0].sha256 = '0'.repeat(64); }, /layer backdrop: file hash does not match the registry/);
  await bad(s => { s.plates.wide.superframe = {width: 480, height: 600}; }, /layer backdrop: its image is 480×480, which does not match the plate's 480×600 shape/);
  await assert.rejects(resolvePlate(loadSet('synthetic-s2', {file, allowSynthetic: true}), 'close', {plane: PLANE, registryFile: file}), /no plate "close" \(plates: wide\)/);
});

// ------------------------------------------------------------------------------------------------ floor model
test('S2 floor model: figure height follows the feet line below the horizon; explicit heights and world placements win', async () => {
  const floor = {horizonY: 0.38, refFeetY: 0.86, refFigureHeight: 0.42};
  assert.ok(close(floorHeightAt(floor, 0.86), 0.42), 'the reference line gives the reference height');
  assert.ok(close(floorHeightAt(floor, 0.62), 0.42 * 0.24 / 0.48), 'linear in the distance below the horizon');
  assert.ok(floorHeightAt(floor, 0.5) < floorHeightAt(floor, 0.7) && floorHeightAt(floor, 0.7) < floorHeightAt(floor, 0.95), 'nearer feet, taller figure');
  assert.throws(() => floorHeightAt(floor, 0.38), /on or above the horizon/);
  assert.throws(() => floorHeightAt(floor, 0.2), /on or above the horizon/);
  assert.throws(() => floorHeightAt(null, 0.8), /no floor model; give an explicit height/);

  const {file} = writeS2Set(tmp('floor'));
  const stage = await resolvePlate(loadSet('synthetic-s2', {file, allowSynthetic: true}), 'wide', {plane: PLANE, registryFile: file});
  const auto = worldPlacement({plateX: 0.6, plateY: 0.9}, stage, 'p');
  assert.ok(close(auto.feetX, stage.rect.x + 0.6 * stage.rect.w) && close(auto.feetY, 0.9 * stage.rect.h) && close(auto.figureHeight, floorHeightAt(floor, 0.9) * stage.rect.h));
  const fixed = worldPlacement({plateX: 0.6, plateY: 0.9, plateHeight: 0.2, shadow: false}, stage, 'p');
  assert.ok(close(fixed.figureHeight, 0.2 * stage.rect.h) && fixed.shadow === false, 'an explicit plateHeight wins over the floor model');
  const world = {feetX: 500, feetY: 2000, figureHeight: 700};
  assert.equal(worldPlacement(world, stage, 'p'), world, 'a world-unit placement is used exactly as given');
  assert.throws(() => placementKind({plateX: 0.5, feetY: 2000}, 'p'), /mixes plate coordinates \(plateX\) with world units \(feetY\)/);
  assert.throws(() => placementKind({plateX: 0.5}, 'p'), /plate placement needs "plateX" and "plateY"/);
  assert.throws(() => placementKind({plateX: 0.5, plateY: 1.2}, 'p'), /plateY: must be a number >= 0 and <= 1/);
  assert.throws(() => placementKind({plateX: 0.5, plateY: 0.5, plateHeight: 0}, 'p'), /plateHeight: must be greater than 0/);
  assert.throws(() => placementKind({plateX: 0.5, plateY: 0.5, size: 3}, 'p'), /unknown field "size"/);
  const noFloor = writeS2Set(tmp('nofloor'), {mutate: s => { delete s.plates.wide.floor; }});
  await assert.rejects(build(setStory(noFloor.file)), /cast member "ph" placement \(floor model\): the plate has no floor model; give an explicit height/);
  const story = setStory(file); delete story.scenes[0].set; delete story.scenes[0].plate; delete story.scenes[0].setRegistry; story.scenes[0].environment = 'living-room-empty-03';
  assert.throws(() => validateStory(story), /cast member "ph" placement: plate coordinates need a scene "set"/);

  // In a compiled scene the figure is drawn at exactly that place and size.
  const b = await build(setStory(file));
  const st = b.report.scenes[0].staging, m = st.members.find(x => x.id === 'c01');
  assert.deepEqual([m.placement, m.layering], ['explicit-plate', 'depth']);
  const info = await poseInfo(loadRegistry(path.join(PRODUCTION_ROOT, 'characters', 'character-01.json')), '02', REPO_ROOT);
  const key = layers(b).find(poseLayer('character-01')).keys[0], k = key.w / info.width;
  assert.ok(Math.abs(key.x + info.feet.x * k - auto.feetX) <= 0.02 && Math.abs(key.y + info.feet.y * k - auto.feetY) <= 0.02 && Math.abs(info.figureHeight * k - auto.figureHeight) <= 0.02, 'feet and height as the floor model says');
});

// ------------------------------------------------------------------------------------------------ depth order
test('S2 depth order: back to front by the feet line, occluders between members by their baseline, deterministic ties', async () => {
  // Pure order rules.
  const occ = [{id: 'counter', baselineY: 0.74, index: 1}, {id: 'fore', baselineY: 1, index: 2}];
  const ids = o => o.map(x => `${x.kind}:${x.id}`);
  assert.deepEqual(ids(drawOrder([{id: 'a', key: 0.9, index: 0}, {id: 'b', key: 0.72, index: 1}], occ)), ['member:b', 'occluder:counter', 'member:a', 'occluder:fore']);
  assert.deepEqual(ids(drawOrder([{id: 'a', key: 0.8, index: 0}, {id: 'b', key: 0.8, index: 1}])), ['member:a', 'member:b'], 'equal depth: declaration order');
  assert.deepEqual(ids(drawOrder([{id: 'b', key: 0.8, index: 1}, {id: 'a', key: 0.8, index: 0}])), ['member:a', 'member:b'], 'the same whatever order they are passed in');
  assert.deepEqual(ids(drawOrder([{id: 'a', key: 0.74, index: 0}], occ)), ['occluder:counter', 'member:a', 'occluder:fore'], 'a member exactly on a baseline is in front of that occluder');

  // In a compiled scene: the declared order of the cast does not matter, depth does.
  const {file} = writeS2Set(tmp('order'));
  for (const cast of [CAST(), [...CAST()].reverse()]) {
    const b = await build(setStory(file, cast));
    assert.deepEqual(b.report.scenes[0].staging.drawOrder, ['member:ph', 'occluder:counter', 'member:c01', 'occluder:fore']);
    const iPh = idx(b, poseLayer(PLACEHOLDER_CHARACTER)), iCounter = idx(b, setLayer('counter')), iC01 = idx(b, poseLayer('character-01')), iFore = idx(b, setLayer('fore'));
    assert.ok(idx(b, setLayer('backdrop')) === 0 && iPh < iCounter && iCounter < iC01 && iC01 < iFore, `render plan order ${[iPh, iCounter, iC01, iFore]}`);
    assert.ok(layers(b)[iPh - 1].path.includes('/shadow-') && layers(b)[iC01 - 1].path.includes('/shadow-'), "each member's shadow is drawn just before it");
  }
  // Equal depth in a compiled scene: declaration order.
  const tie = await build(setStory(file, [c01({plateX: 0.38, plateY: 0.9}), ph({plateX: 0.62, plateY: 0.9})]));
  assert.deepEqual(tie.report.scenes[0].staging.drawOrder, ['occluder:counter', 'member:c01', 'member:ph', 'occluder:fore']);

  // story@2 without a set: depth from the feet line on the frame; story@1 with the same data keeps declaration order.
  const flat = schema => ({schema, id: 'flat', endCard: {duration: 1, caption: 'Technical test'}, scenes: [{id: 'flat', format: 'face-to-face', environment: 'living-room-empty-03',
    cast: [c01({feetX: 420, feetY: 2150, figureHeight: 800}), ph({feetX: 860, feetY: 1950, figureHeight: 640})], lines: LINES()}]});
  const v2 = await build(flat(STORY_SCHEMA_V2)), v1 = await build(flat(STORY_SCHEMA));
  assert.ok(idx(v2, poseLayer(PLACEHOLDER_CHARACTER)) < idx(v2, poseLayer('character-01')), 'story@2: the nearer member (larger feet y) is drawn later');
  assert.ok(idx(v1, poseLayer('character-01')) < idx(v1, poseLayer(PLACEHOLDER_CHARACTER)), 'story@1: declaration order, unchanged');
  assert.equal(v1.report.scenes[0].staging, undefined, 'story@1 reports no staging');
  assert.deepEqual(v2.report.scenes[0].staging.members.map(x => [x.id, x.layering, x.key]), [['c01', 'depth', +(2150 / PLANE.height).toFixed(6)], ['ph', 'depth', +(1950 / PLANE.height).toFixed(6)]]);
});

// ------------------------------------------------------------------------------------------------ precedence
test('S2 precedence: explicit z overrides depth (O4); explicit placement overrides blocking (O3), which still needs S3', async () => {
  const {file, art} = writeS2Set(tmp('prec'));
  // ph stands behind the counter (0.72) but has an explicit z of 0.9: it is drawn in front of the counter.
  const b = await build(setStory(file, [ph({plateX: 0.4, plateY: 0.72}, {z: 0.9}), c01({plateX: 0.6, plateY: 0.92})]));
  const st = b.report.scenes[0].staging;
  assert.deepEqual(st.members.map(m => [m.id, m.layering, m.key]), [['ph', 'explicit-z', 0.9], ['c01', 'depth', 0.92]]);
  assert.deepEqual(st.drawOrder, ['occluder:counter', 'member:ph', 'member:c01', 'occluder:fore']);
  assert.ok(idx(b, setLayer('counter')) < idx(b, poseLayer(PLACEHOLDER_CHARACTER)));
  assert.equal(layeringKey({id: 'x', z: 0.1}, {feetY: 2000}, {plane: PLANE}).key, 0.1);
  assert.throws(() => validateStory(setStory(file, [ph({plateX: 0.4, plateY: 0.72}, {z: 'front'}), c01({plateX: 0.6, plateY: 0.9})])), /cast member "ph" z: must be a number/);
  // An explicit z larger than every occluder baseline puts a member in front of the foreground too.
  const top = await build(setStory(file, [ph({plateX: 0.4, plateY: 0.72}, {z: 2}), c01({plateX: 0.6, plateY: 0.9})]));
  assert.deepEqual(top.report.scenes[0].staging.drawOrder, ['occluder:counter', 'member:c01', 'occluder:fore', 'member:ph']);
  // Explicit world placement in a set scene is used as given (O3 override); its depth comes from where its feet are.
  const w = await build(setStory(file, [ph({feetX: 420, feetY: 0.72 * PLANE.height, figureHeight: 600}), c01({plateX: 0.6, plateY: 0.9})]));
  assert.deepEqual(w.report.scenes[0].staging.members[0], {id: 'ph', placement: 'explicit-world', layering: 'depth', key: 0.72, index: 0, world: {feetX: 420, feetY: +(0.72 * PLANE.height).toFixed(3), figureHeight: 600}});
  // Explicit placement wins over blocking in the data model (S1); blocking itself still needs the S3 resolver.
  const kit = writeSyntheticKit(tmp('kit'));
  const blocked = setStory(file); blocked.actionLibrary = kit.actionsFile;
  blocked.scenes[0].blocking = [{who: 'c01', do: 'stand-at', mark: 'spot'}];
  const d = validateStoryReferences(blocked, {allowSynthetic: true}).scenes[0];
  assert.deepEqual(d.members.find(m => m.id === 'c01'), {id: 'c01', placement: 'explicit', blockingOverriddenByExplicitPlacement: true, layering: 'depth'});
  assert.throws(() => assertCompilable(blocked), /uses blocking; the staging resolver needs AP-86 S3/);
  const unplaced = setStory(file, [ph({plateX: 0.4, plateY: 0.72}), {...c01(undefined)}]); delete unplaced.scenes[0].cast[1].placement;
  assert.throws(() => assertCompilable(unplaced), /cast member "c01" has no placement\. In story@2 members are placed by marks and actions \(O3, needs AP-86 S3\)/);
  assert.ok(art.counter.sha256);
});

// ------------------------------------------------------------------------------------------------ layered plates
test('S2 layered plates: layers must be a true back-to-front order; invalid or incomplete sets are refused', () => {
  const {set} = writeS2Set(tmp('val'));
  validateSet(set);
  const cases = [
    [s => { s.plates.wide.layers.push({id: 'late', file: 'art/x.png'}); }, /layer late: a backdrop layer cannot come after the occluder layer "fore"/],
    [s => { s.plates.wide.layers[2].occluder.baselineY = 0.6; }, /layer fore: occluder baseline 0\.6 is behind the previous occluder's 0\.74/],
    [s => { s.plates.wide.layers[0].occluder = {baselineY: 0.5}; }, /layer backdrop: the first layer is the backdrop/],
    [s => { s.plates.wide.layers[0].rect = {x: 0, y: 0, w: 1}; }, /layer backdrop: the first layer is the backdrop/],
    [s => { s.plates.wide.layers[1].rect.w = 0; }, /rect\.w: must be greater than 0/],
    [s => { s.plates.wide.layers[1].rect.h = 0.2; }, /unknown field "h"/],
    [s => { s.assetRoot = 'somewhere'; }, /assetRoot: must be "repository" or "registry"/],
    [s => { s.plates.wide.layers = []; }, /at least one layer/],
    [s => { delete s.plates.wide.floor.refFeetY; }, /floor\.refFeetY: must be a number/],
  ];
  for (const [mutate, pattern] of cases) { const x = structuredClone(set); mutate(x); assert.throws(() => validateSet(x), pattern, String(pattern)); }
  assert.throws(() => loadSet('synthetic-s2', {file: writeS2Set(tmp('syn')).file}), /SYNTHETIC test fixture, not artwork/);
});

// ------------------------------------------------------------------------------------------------ pixels
async function painter(b, without = null) {
  const {core, render} = await rendererModules();
  if (!without) return render.painter(core.loadProject(b.projectFile));
  const p = structuredClone(b.project); p.shots[0].layers = p.shots[0].layers.filter(l => !without(l));
  const f = path.join(path.dirname(b.projectFile), `without-${crypto.randomBytes(4).toString('hex')}.json`); fs.writeFileSync(f, JSON.stringify(p));
  return render.painter(core.loadProject(f));
}
const frame = (draw, t) => { const f = draw(t); return {w: f.width, h: f.height, d: f.getContext('2d').getImageData(0, 0, f.width, f.height).data}; };
const near = (fr, x, y, c, tol = 12) => { const i = (y * fr.w + x) * 4; return Math.abs(fr.d[i] - c[0]) <= tol && Math.abs(fr.d[i + 1] - c[1]) <= tol && Math.abs(fr.d[i + 2] - c[2]) <= tol; };
// Output-pixel box of a world rectangle in a wide shot (zoom 1).
const box = (r, ppu) => ({x0: Math.ceil(r.x0 * ppu), x1: Math.floor(r.x1 * ppu), y0: Math.ceil(r.y0 * ppu), y1: Math.floor(r.y1 * ppu)});

test('S2 occlusion in rendered frames: an occluder covers a member behind its baseline and not one in front; explicit z lifts a member over it', needsRenderer, async () => {
  const {file} = writeS2Set(tmp('px'));
  const b = await build(setStory(file)), ppu = b.project.width / PLANE.width, t = 0.75;
  const st = b.report.scenes[0].staging, R = (await resolvePlate(loadSet('synthetic-s2', {file, allowSynthetic: true}), 'wide', {plane: PLANE, registryFile: file})).rect;
  const counterRows = {y0: 0.62 * R.h + 2, y1: 0.82 * R.h - 2};
  const full = frame(await painter(b), t), noPh = frame(await painter(b, poseLayer(PLACEHOLDER_CHARACTER)), t), noC01 = frame(await painter(b, poseLayer('character-01')), t);
  // A member's visible pixels are where the frame changes when that member is removed.
  const changed = (a, b2, bx) => { let n = 0; for (let y = bx.y0; y <= bx.y1; y++) for (let x = bx.x0; x <= Math.min(bx.x1, a.w - 1); x++) { const i = (y * a.w + x) * 4; if (a.d[i] !== b2.d[i] || a.d[i + 1] !== b2.d[i + 1] || a.d[i + 2] !== b2.d[i + 2]) n++; } return n; };
  // The placeholder stands behind the counter: above the counter it is visible, inside the counter band it is not.
  const phM = st.members.find(m => m.id === 'ph'), phX = phM.world.feetX;
  const above = box({x0: phX - 150, x1: phX + 150, y0: phM.world.feetY - phM.world.figureHeight, y1: counterRows.y0 - 4}, ppu);
  const phBand = box({x0: phX - 150, x1: phX + 150, y0: counterRows.y0, y1: Math.min(counterRows.y1, phM.world.feetY + 4)}, ppu);
  assert.ok(changed(full, noPh, above) > 5000, `the placeholder is visible above the counter (${changed(full, noPh, above)} px)`);
  assert.equal(changed(full, noPh, phBand), 0, 'inside the counter band nothing of the placeholder shows: the counter covers it');
  // Character 01 stands in front: inside the counter band its pixels are drawn over the red.
  let c01Over = 0;
  const c01X = st.members.find(m => m.id === 'c01').world.feetX, cBand = box({x0: c01X - 150, x1: c01X + 150, y0: counterRows.y0, y1: counterRows.y1}, ppu);
  for (let y = cBand.y0; y <= cBand.y1; y++) for (let x = cBand.x0; x <= cBand.x1; x++) {
    const i = (y * full.w + x) * 4;
    if (Math.abs(full.d[i] - noC01.d[i]) + Math.abs(full.d[i + 1] - noC01.d[i + 1]) + Math.abs(full.d[i + 2] - noC01.d[i + 2]) > 60) { c01Over++; assert.ok(!near(full, x, y, S2_COLOURS.counter, 20), `Character 01 is visible over the counter at ${x},${y}`); }
  }
  assert.ok(c01Over > 2000, `Character 01 is drawn over the counter (${c01Over} px)`);
  // The foreground occluder (baseline 1) is in front of everyone: inside its band no member shows, though Character 01's
  // feet reach into it.
  const fb = box({x0: 0, x1: PLANE.width - 1, y0: 0.9 * R.h + 2, y1: Math.min(PLANE.height, 0.9 * R.h + R.w * 48 / 480) - 2}, ppu);
  assert.equal(changed(full, noC01, fb) + changed(full, noPh, fb), 0, 'the foreground band hides every member');
  const c01M = st.members.find(m => m.id === 'c01'), shoes = box({x0: c01M.world.feetX - 150, x1: c01M.world.feetX + 150, y0: c01M.world.feetY - 30, y1: c01M.world.feetY + 2}, ppu);
  const noFore = frame(await painter(b, setLayer('fore')), t), noForeNoC01 = frame(await painter(b, l => setLayer('fore')(l) || poseLayer('character-01')(l)), t);
  assert.ok(changed(noFore, noForeNoC01, shoes) > 200, 'without the foreground layer, the feet of Character 01 would show there');

  // Explicit z (O4 override): the same placeholder, z 0.9, is drawn in front of the counter, so its blue body shows there.
  const lifted = await build(setStory(file, [ph({plateX: 0.4, plateY: 0.72}, {z: 0.9}), c01({plateX: 0.6, plateY: 0.9})]));
  const lf = frame(await painter(lifted), t);
  let blue = 0; for (let y = phBand.y0; y <= phBand.y1; y += 2) for (let x = phBand.x0; x <= phBand.x1; x += 2) if (near(lf, x, y, PLACEHOLDER_COLOURS.body, 12)) blue++;
  assert.ok(blue > 50, `with z 0.9 the placeholder's body is visible over the counter (${blue} px)`);
});

test('S2 parallax: each set layer zooms by 1 + (zoom - 1) × factor about the shot pivot; wide shots and factor 1 are unchanged', needsRenderer, async () => {
  const cam = {z: 1.5, ox: 10, oy: -4, pivot: {x: 100, y: 200}};
  assert.deepEqual(parallaxCamera(cam, 0.5), {z: 1.25, ox: 5, oy: -2, pivot: {x: 100, y: 200}});
  assert.equal(parallaxCamera(cam, 1), cam);
  assert.deepEqual(parallaxCamera({z: 1, ox: 0, oy: 0, pivot: {x: 1, y: 1}}, 0.7), {z: 1, ox: 0, oy: 0, pivot: {x: 1, y: 1}}, 'a wide shot is the same for every factor');
  const lines = () => [
    {speaker: 'c01', text: 'Wide.', duration: 1.5, poses: {c01: '02', ph: 'p1'}, shot: {camera: 'Wide'}},
    {speaker: 'c01', text: 'Medium.', duration: 1.5, shot: {camera: 'Medium 1.3x', focus: 'c01', single: true}},
  ];
  const plain = writeS2Set(tmp('par1')), deep = writeS2Set(tmp('par2'), {mutate: s => { s.plates.wide.layers[0].parallax = 0.8; }});
  const a = await build(setStory(plain.file, CAST(), lines())), b = await build(setStory(deep.file, CAST(), lines()));
  assert.ok(a.report.checks.ok && b.report.checks.ok, JSON.stringify(b.report.checks.issues));
  const back = x => layers(x).find(setLayer('backdrop')), counterOf = x => layers(x).find(setLayer('counter'));
  const at = (l, t) => l.keys.reduce((k0, k) => (k.t <= t + 1e-6 ? k : k0));
  const R = plateWorldRect({width: 480, height: 480}, PLANE);
  // Wide shot (t 0.5): identical for both. Medium shot (t 2): the backdrop zooms 1 + 0.3 × 0.8 = 1.24 instead of 1.3.
  assert.deepEqual(at(back(a), 0.5), at(back(b), 0.5));
  assert.ok(Math.abs(at(back(a), 2).w - R.w * 1.3) < 0.02 && Math.abs(at(back(b), 2).w - R.w * 1.24) < 0.02, `backdrop widths ${at(back(a), 2).w} ${at(back(b), 2).w}`);
  assert.deepEqual(at(counterOf(a), 2), at(counterOf(b), 2), 'a factor-1 layer moves with the characters, unchanged');
  // Rendered: in the wide shot the frames are identical; in the medium shot only the backdrop differs.
  const pa = await painter(a), pb = await painter(b), wa = frame(pa, 0.5), wb = frame(pb, 0.5), ma = frame(pa, 2), mb = frame(pb, 2);
  assert.ok(Buffer.from(wa.d).equals(Buffer.from(wb.d)), 'wide shot: pixel-identical');
  assert.ok(!Buffer.from(ma.d).equals(Buffer.from(mb.d)), 'medium shot: the backdrop moves with its own factor');
});

// ------------------------------------------------------------------------------------------------ compatibility
test('S2 compatibility and determinism: set scenes compile identically twice; story@2 with explicit z matches story@1; Short 001 is unchanged', async () => {
  const {file} = writeS2Set(tmp('det'));
  const a = await build(setStory(file)), b = await build(setStory(file));
  assert.equal(sha(a.projectFile), sha(b.projectFile));
  assert.equal(sha(path.join(a.dir, 'layout-report.json')), sha(path.join(b.dir, 'layout-report.json')));
  assert.ok(a.report.checks.ok, JSON.stringify(a.report.checks.issues));
  // Explicit z in story@2 orders exactly as story@1 does: the same project.
  const two = schema => ({schema, id: 'compat', endCard: {duration: 1, caption: 'Technical test'}, scenes: [{id: 'compat', format: 'face-to-face', environment: 'living-room-empty-03',
    cast: [c01({feetX: 400, feetY: 2070, figureHeight: 760}, {z: 0}), ph({feetX: 880, feetY: 2070, figureHeight: 760}, {z: 1})], lines: LINES()}]});
  const v1 = await build(two(STORY_SCHEMA)), v2 = await build(two(STORY_SCHEMA_V2));
  assert.equal(sha(v1.projectFile), sha(v2.projectFile));
  // Short 001 (story@1, text-chat) as story@2 compiles to the same project.
  const short = json(path.join(PRODUCTION_ROOT, 'stories', 'short-001-v2.story.json'));
  const s1 = await compileProject(short, {outDir: tmp('s1')}), s2 = await compileProject({...structuredClone(short), schema: STORY_SCHEMA_V2}, {outDir: tmp('s2')});
  assert.equal(sha(s1.projectFile), sha(s2.projectFile));
  // Sets render in face-to-face scenes only in S2.
  const chat = setStory(file); chat.scenes[0].format = 'text-chat';
  assert.throws(() => assertCompilable(chat), /AP-86 S2 renders sets in face-to-face scenes only/);
  // Synthetic sets never reach production: refused without allowSynthetic.
  await assert.rejects(compileProject(setStory(file), {outDir: tmp('nosyn')}), /set "synthetic-s2" is a SYNTHETIC test fixture/);
});
