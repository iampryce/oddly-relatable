// AP-86 S3: staging and props (approved 2026-11-16). The staging resolver, prop placement, the stand-at, sit-on, lean-on
// and hold actions, anchor alignment and its QA, on the two worked examples of the AP-86 proposal (bar §6, office §7).
//
// S3 ONLY: no framing or camera changes, no movement, no artwork, no audio or export changes (S4 to S7). Actors, sets,
// props and the action library are SYNTHETIC, labelled test fixtures written to temporary folders. Positions are checked
// independently: expected world points are worked out here from the fixture numbers and the floor model formula, and
// compared with what the render plan actually draws (layer keys), not with the resolver's own report.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {compileProject} from '../lib/scene.mjs';
import {resolveStaging, ALIGN_TOLERANCE, poseMatches} from '../lib/staging.mjs';
import {loadSet, resolvePlate, plateWorldRect} from '../lib/sets.mjs';
import {loadActionLibrary} from '../lib/actions.mjs';
import {designPlane, rendererModules} from '../lib/runtime.mjs';
import {writeS3Examples, ACTOR_COLOURS, PROP_COLOURS} from './fixtures/ap86-s3-examples.mjs';

const needsRenderer = {skip: process.env.FFPROBE ? false : 'set FFMPEG/FFPROBE to run renderer-backed checks'};
const tmp = n => fs.mkdtempSync(path.join(os.tmpdir(), `ap86s3-${n}-`));
const json = f => JSON.parse(fs.readFileSync(f, 'utf8'));
const sha = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const PLANE = designPlane(1080, 1920);
const R = plateWorldRect({width: 480, height: 480}, PLANE);
const W = p => ({x: R.x + p.x * R.w, y: R.y + p.y * R.h});
const FLOOR = {horizonY: 0.38, refFeetY: 0.86, refFigureHeight: 0.42};
const height = v => FLOOR.refFigureHeight * (v - FLOOR.horizonY) / (FLOOR.refFeetY - FLOOR.horizonY) * R.h;
const near = (a, b, tol, msg) => assert.ok(Math.hypot(a.x - b.x, a.y - b.y) <= tol, `${msg}: (${a.x.toFixed(2)}, ${a.y.toFixed(2)}) vs (${b.x.toFixed(2)}, ${b.y.toFixed(2)})`);
const EX = writeS3Examples(tmp('kit'));
const build = async (story, opts = {}) => { const dir = tmp('build'), r = await compileProject(story, {outDir: dir, allowSynthetic: true, ...opts}); return {...r, dir, project: json(r.projectFile)}; };
const layers = b => b.project.shots[0].layers;
const find = (b, frag) => layers(b).filter(l => l.path.includes(frag));
const keyAt = (l, t) => l.keys.reduce((k0, k) => (k.t <= t + 1e-6 ? k : k0));
// World point of an image anchor in a layer at time t (wide shot: zoom 1, so render-plan units are world units).
const anchorWorld = (l, t, imgW, a) => { const k = keyAt(l, t), s = k.w / imgW; return {x: k.x + a.x * s, y: k.y + a.y * s, s}; };
const P = EX.POSES;
const idx = (b, frag) => layers(b).findIndex(l => l.path.includes(frag));
const variant = (file, mutate) => { const d = json(file); mutate(d); const f = path.join(path.dirname(file), `v-${crypto.randomBytes(4).toString('hex')}-${path.basename(file)}`); fs.writeFileSync(f, JSON.stringify(d)); return f; };

// ------------------------------------------------------------------------------------------------ bar (§6)
test('S3 bar example: sit on a stool prop, hold a glass, lean on the counter; every contact lands on its target', async () => {
  const b = await build(EX.barConversation()), st = b.report.scenes[0].staging;
  assert.ok(b.report.checks.ok, JSON.stringify(b.report.checks.issues));
  // Stool on mark stool-1: its floor anchor on the mark's floor point, sized by the floor model at that line.
  const stool = find(b, '/prop-synthetic-stool-default-')[0], stoolFloor = W({x: 0.38, y: 0.8});
  near(anchorWorld(stool, 0, 120, {x: 60, y: 198}), stoolFloor, 0.05, 'stool floor anchor on the mark floor');
  assert.ok(Math.abs(keyAt(stool, 0).w / 120 * 200 - 0.2 * (0.8 - 0.38) / 0.48 * R.h) < 0.05, 'stool height from its "height" and the floor model');
  const seat = anchorWorld(stool, 0, 120, {x: 60, y: 22});
  // A sits: the seat anchor of every pose A uses is on the stool's seat; A's size is the floor model at the stool's line.
  const aSit = find(b, '/synthetic-actor-a-pose-sit-')[0], aRaise = find(b, '/synthetic-actor-a-pose-sit-raise-')[0];
  near(anchorWorld(aSit, 0.5, 300, P.sit.anchors.seat), seat, ALIGN_TOLERANCE, 'A sit pose on the seat');
  near(anchorWorld(aRaise, 3.5, 300, P['sit-raise'].anchors.seat), seat, ALIGN_TOLERANCE, 'A raised pose still on the seat');
  assert.ok(Math.abs(anchorWorld(aSit, 0.5, 300, {x: 0, y: 0}).s * 600 - height(0.8)) < 0.05, 'A sized at the stool floor line');
  // The glass follows A's right hand in each pose: two layers, each visible only for its pose.
  const glasses = find(b, '/prop-synthetic-glass-full-');
  assert.equal(glasses.length, 2);
  assert.deepEqual(glasses.map(g => [g.from, g.to]), [[0, 3], [3, 5.5]]);
  near(anchorWorld(glasses[0], 0.5, 20, {x: 10, y: 15}), anchorWorld(aSit, 0.5, 300, P.sit.anchors.handRight), ALIGN_TOLERANCE, 'grip in the sitting hand');
  near(anchorWorld(glasses[1], 3.5, 20, {x: 10, y: 15}), anchorWorld(aRaise, 3.5, 300, P['sit-raise'].anchors.handRight), ALIGN_TOLERANCE, 'grip in the raised hand');
  // B leans: its left hand on the counter-top line at 0.62 along it; sized at the counter's floor line.
  const bLean = find(b, '/synthetic-actor-b-pose-lean-')[0];
  near(anchorWorld(bLean, 0.5, 300, P.lean.anchors.handLeft), {x: W({x: 0.05 + 0.62 * 0.9, y: 0}).x, y: W({x: 0, y: 0.6}).y}, ALIGN_TOLERANCE, 'B hand on the counter');
  assert.ok(Math.abs(anchorWorld(bLean, 0.5, 300, {x: 0, y: 0}).s * 600 - height(0.7)) < 0.05, 'B sized at the counter floor line');
  // The second glass stands on the counter at 0.3 along it (base anchor on the line).
  const gb = find(b, '/prop-synthetic-glass-empty-')[0];
  near(anchorWorld(gb, 0, 20, {x: 10, y: 38}), {x: W({x: 0.05 + 0.3 * 0.9, y: 0}).x, y: W({x: 0, y: 0.6}).y}, 0.05, 'glass on the counter');
  // Draw order: counter, glass on it, B (in front of the counter), the stool, A, the stool's front rim, A's glass.
  assert.deepEqual(st.drawOrder, ['occluder:counter', 'prop:glass-b', 'member:b', 'prop:stool-a', 'member:a', 'prop-front:stool-a', 'prop:glass-a']);
  const order = ['set-synthetic-bar-wide-counter-', 'prop-synthetic-glass-empty-', 'synthetic-actor-b-pose-lean-', 'prop-synthetic-stool-default-', 'synthetic-actor-a-pose-sit-', 'prop-synthetic-stool-default-front-', 'prop-synthetic-glass-full-'].map(f => idx(b, f));
  assert.deepEqual([...order].sort((x, y) => x - y), order, `render plan order ${order}`);
  // A sits (feet off the floor line): no feet shadow. B stands: one shadow.
  assert.equal(find(b, '/shadow-').length, 1);
  // Report: placement sources, actions and contacts.
  assert.deepEqual(st.members.map(m => [m.id, m.placement, m.action, m.target, m.layering]), [['a', 'action', 'sit-on-prop', 'prop:stool-a.seat', 'depth'], ['b', 'action', 'lean-on', 'surface:counter-top@0.62', 'depth']]);
  assert.deepEqual(st.members[0].contacts.map(c => [c.anchor, c.target, c.poses.map(p => p.pose)]), [['seat', 'prop:stool-a.seat', ['sit', 'sit-raise']], ['handRight', 'prop:glass-a.grip', ['sit', 'sit-raise']]]);
  assert.deepEqual(st.props.map(p => [p.id, p.placement, p.layering]), [['stool-a', 'mark:stool-1', 'with-member'], ['glass-a', 'held-by:a', 'with-member'], ['glass-b', 'surface:counter-top@0.3', 'depth']]);
});

// ------------------------------------------------------------------------------------------------ office (§7)
test('S3 office example: sit at a desk mark behind the desk front, a mug on the desk, a visitor standing at a mark', async () => {
  const b = await build(EX.officeDesk()), st = b.report.scenes[0].staging;
  assert.ok(b.report.checks.ok, JSON.stringify(b.report.checks.issues));
  const aSit = find(b, '/synthetic-actor-a-pose-sit-')[0], aRaise = find(b, '/synthetic-actor-a-pose-sit-raise-')[0];
  near(anchorWorld(aSit, 0.5, 300, P.sit.anchors.seat), W({x: 0.42, y: 0.7}), ALIGN_TOLERANCE, 'A seat on the desk-chair mark');
  near(anchorWorld(aRaise, 3.5, 300, P['sit-raise'].anchors.seat), W({x: 0.42, y: 0.7}), ALIGN_TOLERANCE, 'A seat on the mark in every pose');
  assert.ok(Math.abs(anchorWorld(aSit, 0.5, 300, {x: 0, y: 0}).s * 600 - height(0.76)) < 0.05, 'A sized at the mark floor line (scaleFrom mark.floor)');
  const bStand = find(b, '/synthetic-actor-b-pose-stand-')[0];
  near(anchorWorld(bStand, 0.5, 300, P.stand.feet), W({x: 0.66, y: 0.9}), ALIGN_TOLERANCE, 'B feet on the visitor mark');
  assert.ok(Math.abs(anchorWorld(bStand, 0.5, 300, {x: 0, y: 0}).s * 600 - height(0.9)) < 0.05, 'B sized at its mark');
  const mug = find(b, '/prop-synthetic-mug-default-')[0];
  near(anchorWorld(mug, 0, 30, {x: 15, y: 29}), {x: W({x: 0.15 + 0.25 * 0.55, y: 0}).x, y: W({x: 0, y: 0.66}).y}, 0.05, 'mug on the desk');
  // A sits behind the desk front (its depth is in front of the chair's floor line but behind the desk's baseline).
  assert.deepEqual(st.drawOrder, ['member:a', 'occluder:desk-front', 'prop:mug', 'member:b']);
  assert.ok(idx(b, 'synthetic-actor-a-pose-sit-') < idx(b, 'set-synthetic-office-desk-desk-front-'));
  assert.deepEqual(st.members.map(m => [m.id, m.action, m.target]), [['a', 'sit-on', 'mark:desk-chair.point'], ['b', 'stand-at', 'mark:visitor.point']]);
});

// ------------------------------------------------------------------------------------------------ precedence
test('S3 precedence: explicit placement overrides action-derived placement (O3); explicit z overrides depth (O4)', async () => {
  // O3: B is blocked "stand-at visitor" but also has an explicit plate placement: the explicit placement wins.
  const s = EX.officeDesk(); s.scenes[0].cast[1].placement = {plateX: 0.6, plateY: 0.92};
  const b = await build(s), m = b.report.scenes[0].staging.members[1];
  assert.deepEqual([m.placement, m.overriddenAction, m.action], ['explicit-plate', 'stand-at', undefined]);
  near(anchorWorld(find(b, '/synthetic-actor-b-pose-stand-')[0], 0.5, 300, P.stand.feet), W({x: 0.6, y: 0.92}), ALIGN_TOLERANCE, 'B at its explicit placement, not the mark');
  // A holder with an explicit placement still holds: the glass follows the hand of the explicitly placed member.
  const h = EX.barConversation(); h.scenes[0].cast[0].placement = {plateX: 0.45, plateY: 0.86}; h.scenes[0].lines[0].poses.a = 'stand'; h.scenes[0].lines[2].pose = 'stand';
  const hb = await build(h), ha = hb.report.scenes[0].staging.members[0];
  assert.deepEqual([ha.placement, ha.overriddenAction], ['explicit-plate', 'sit-on-prop']);
  near(anchorWorld(find(hb, '/prop-synthetic-glass-full-')[0], 0.5, 20, {x: 10, y: 15}), anchorWorld(find(hb, '/synthetic-actor-a-pose-stand-')[0], 0.5, 300, P.stand.anchors.handRight), ALIGN_TOLERANCE, 'the glass is in the explicitly placed hand');
  // O4: an explicit z puts the visitor behind the desk front although it stands in front of it.
  const z = EX.officeDesk(); z.scenes[0].cast[1].z = 0.5;
  const zb = await build(z);
  assert.deepEqual(zb.report.scenes[0].staging.drawOrder, ['member:b', 'member:a', 'occluder:desk-front', 'prop:mug']);
  assert.equal(zb.report.scenes[0].staging.members[1].layering, 'explicit-z');
});

// ------------------------------------------------------------------------------------------------ QA
test('S3 anchor-alignment QA: poses that land their anchor off target fail with the distance; within tolerance passes', async () => {
  assert.equal(ALIGN_TOLERANCE, 1);
  const off = EX.barConversation(); off.scenes[0].lines[2].pose = 'sit-bad';
  // sit-bad's seat is 50 px lower relative to its feet; at A's scale (k = height(0.8) / 600) that is 50 × k units.
  const expected = (50 * height(0.8) / 600).toFixed(2);
  await assert.rejects(build(off), new RegExp(`anchor "seat" of pose "sit-bad" lands ${expected.replace('.', '\\.')} units from prop:stool-a\\.seat \\(tolerance 1\\)`));
  const ok = EX.barConversation(); ok.scenes[0].lines[2].pose = 'sit-near';
  const b = await build(ok), c = b.report.scenes[0].staging.members[0].contacts[0];
  const err = c.poses.find(p => p.pose === 'sit-near').error;
  assert.ok(err > 0.5 && err < ALIGN_TOLERANCE, `0.5 px at this scale is ${err} units: within tolerance`);
  assert.ok(poseMatches({tags: {stance: 'sit', action: ['wave', 'talk']}}, {stance: 'sit', action: 'talk'}));
  assert.ok(!poseMatches({tags: {stance: 'stand'}}, {stance: 'sit'}) && !poseMatches({}, {stance: 'sit'}));
});

// ------------------------------------------------------------------------------------------------ validation
test('S3 validation: missing or mismatched poses, anchors, marks, surfaces, props, states, assets and sizes are refused', async () => {
  const fail = async (mutate, pattern, base = EX.barConversation) => { const s = base(); mutate(s.scenes[0], s); await assert.rejects(build(s), pattern, String(pattern)); };
  // Poses and anchors.
  await fail(sc => { sc.lines[0].poses.a = 'stand'; }, /cast member "a": pose "stand" does not match action "sit-on-prop" \(needs \{"stance":"sit"\}\)/);
  await fail(sc => { sc.blocking.push({who: 'b', do: 'hold', prop: 'glass-b'}); delete sc.props[2].on; delete sc.props[2].at; }, /cast member "b": pose "lean" has no "handRight" anchor, which action "hold" needs/);
  // Marks, surfaces, incompatible targets.
  await fail(sc => { sc.blocking[0] = {who: 'a', do: 'sit-on', mark: 'nowhere'}; }, /plate "wide" has no mark "nowhere"/);
  await fail(sc => { sc.blocking[2] = {who: 'b', do: 'lean-on', mark: 'bar-end'}; }, /action "lean-on" needs a surface, not a mark/);
  await fail(sc => { sc.blocking[2] = {who: 'b', do: 'stand-at', mark: 'stool-1'}; }, /mark "stool-1" is a seat mark; action "stand-at" needs a stand mark/);
  await fail(sc => { sc.blocking[2] = {who: 'b', do: 'lean-on', surface: 'counter-top'}; }, /needs "at": where along the surface/);
  await fail(sc => { sc.setRegistry = variant(EX.sets.bar, d => { delete d.plates.wide.surfaces['counter-top'].floorY; }); }, /surface "counter-top" has no "floorY"/);
  await fail(sc => { sc.setRegistry = variant(EX.sets.bar, d => { delete d.plates.wide.floor; }); }, /no floor model/);
  // Members with no placing action.
  await fail(sc => { sc.blocking = sc.blocking.filter(x => x.who !== 'b'); sc.blocking.push({who: 'b', do: 'hold', prop: 'glass-b'}); delete sc.props[2].on; delete sc.props[2].at; sc.lines[0].poses.b = 'stand'; },
    /cast member "b": has no placement: give it a placing action/);
  // Props: states, anchors, assets, hashes, splits, sizes.
  await fail(sc => { sc.props[2].state = 'broken'; }, /prop "synthetic-glass" has no state "broken"/);
  await fail(sc => { sc.props[0].registry = variant(EX.props.stool, d => { delete d.states.default.anchors.floor; }); }, /state "default" of "synthetic-stool" has no "floor" anchor/);
  await fail(sc => { sc.props[0].registry = variant(EX.props.stool, d => { d.states.default.sha256 = '0'.repeat(64); }); }, /prop synthetic-stool state default: file hash does not match the registry/);
  await fail(sc => { sc.props[0].registry = variant(EX.props.stool, d => { d.states.default.file = 'art/missing.png'; delete d.states.default.sha256; }); }, /missing file art\/missing\.png/);
  await fail(sc => { sc.props[0].registry = variant(EX.props.stool, d => { delete d.height; }); }, /prop "synthetic-stool" has no "height"; S3 sizes props from it/);
  await fail(sc => { sc.props[0].registry = variant(EX.props.stool, d => { d.splits.default.front = {file: 'art/prop-glass.png'}; }); }, /its "front" split is 20×40 but state "default" is 120×200; splits must align with the state image/);
  await fail(sc => { sc.props[0].registry = variant(EX.props.stool, d => { d.states.default.anchors.seat = {x: 500, y: 10}; }); }, /anchor "seat" \(500, 10\) is outside the 120×200 image/);
  // Synthetic fixtures never reach production.
  await assert.rejects(compileProject(EX.barConversation(), {outDir: tmp('nosyn')}), /SYNTHETIC test fixture/);
});

// ------------------------------------------------------------------------------------------------ determinism
test('S3 determinism: identical inputs give identical staging, render plans and reports', async () => {
  const a = await build(EX.barConversation()), b = await build(EX.barConversation());
  assert.equal(sha(a.projectFile), sha(b.projectFile));
  assert.equal(sha(path.join(a.dir, 'layout-report.json')), sha(path.join(b.dir, 'layout-report.json')));
  const scene = EX.officeDesk().scenes[0];
  const stage = await resolvePlate(loadSet('synthetic-office', {file: scene.setRegistry, allowSynthetic: true}), 'desk', {plane: PLANE, registryFile: scene.setRegistry});
  const seq = {castPoses: {a: [{pose: 'sit', start: 0, end: 3}, {pose: 'sit-raise', start: 3, end: 5.5}], b: [{pose: 'stand', start: 0, end: 5.5}]}};
  const library = loadActionLibrary(EX.actions), run = () => resolveStaging({scene, seq, stage, plane: PLANE, library, allowSynthetic: true});
  const [r1, r2] = [await run(), await run()];
  assert.deepEqual(r1.report, r2.report);
  assert.equal(JSON.stringify(r1.report), JSON.stringify(r2.report));
});

// ------------------------------------------------------------------------------------------------ pixels
test('S3 rendered frames: the stool front rim is drawn over the sitter, the glass is in the hand, the desk front hides the sitter', needsRenderer, async () => {
  const {core, render} = await rendererModules();
  const paint = async (b, drop = null) => {
    let f = b.projectFile;
    if (drop) { const p = structuredClone(b.project); p.shots[0].layers = p.shots[0].layers.filter(l => !l.path.includes(drop)); f = path.join(path.dirname(b.projectFile), `no-${crypto.randomBytes(4).toString('hex')}.json`); fs.writeFileSync(f, JSON.stringify(p)); }
    const draw = await render.painter(core.loadProject(f));
    return t => { const c = draw(t); return {w: c.width, d: c.getContext('2d').getImageData(0, 0, c.width, c.height).data}; };
  };
  const colourAt = (fr, x, y) => { const i = (Math.round(y) * fr.w + Math.round(x)) * 4; return [fr.d[i], fr.d[i + 1], fr.d[i + 2]]; };
  const is = (c, ref, tol = 12) => c.every((v, i) => Math.abs(v - ref[i]) <= tol);
  const ppu = 1080 / PLANE.width;
  // Bar: the rim of the stool (stool image rows 10–22) covers A's thighs; without the front split, A's body shows there.
  const b = await build(EX.barConversation()), t = 0.75;
  const stool = find(b, '/prop-synthetic-stool-default-')[0], k = keyAt(stool, 0), s = k.w / 120;
  const rim = {x: (k.x + 60 * s) * ppu, y: (k.y + 16 * s) * ppu};
  const full = (await paint(b))(t), noFront = (await paint(b, 'prop-synthetic-stool-default-front-'))(t);
  assert.ok(is(colourAt(full, rim.x, rim.y), PROP_COLOURS.stoolFront), `stool rim over the sitter: ${colourAt(full, rim.x, rim.y)}`);
  assert.ok(is(colourAt(noFront, rim.x, rim.y), ACTOR_COLOURS['synthetic-actor-a'].body), `without the rim the sitter shows: ${colourAt(noFront, rim.x, rim.y)}`);
  // The glass is drawn at the hand: its centre is glass-coloured.
  const g = find(b, '/prop-synthetic-glass-full-')[0], gk = keyAt(g, t), gs = gk.w / 20;
  assert.ok(is(colourAt(full, (gk.x + 10 * gs) * ppu, (gk.y + 25 * gs) * ppu), PROP_COLOURS.glass), 'glass visible in the hand');
  // Office: A's body below the desk-top line is hidden by the desk front; without it, A's body shows.
  const o = await build(EX.officeDesk()), a = find(o, '/synthetic-actor-a-pose-sit-')[0], ak = keyAt(a, t), as = ak.w / 300;
  const hip = {x: (ak.x + 150 * as) * ppu, y: (ak.y + 455 * as) * ppu};
  const of = (await paint(o))(t), noDesk = (await paint(o, 'set-synthetic-office-desk-desk-front-'))(t);
  assert.ok(is(colourAt(of, hip.x, hip.y), [90, 90, 100]), `desk front over the sitter: ${colourAt(of, hip.x, hip.y)}`);
  assert.ok(is(colourAt(noDesk, hip.x, hip.y), ACTOR_COLOURS['synthetic-actor-a'].body), `without the desk front the sitter shows: ${colourAt(noDesk, hip.x, hip.y)}`);
});
