// AP-86 S1: data models and validation (docs/oddly-relatable/AP-86-STUDIO-ARCHITECTURE-PROPOSAL.md §4, §10, §11).
//
// S1 ONLY. These tests cover schemas, loaders, cross-references and precedence rules (O3, O4). Nothing here renders
// a set, places a prop, runs an action, computes depth or moves a camera (S2 to S5). Synthetic fixtures (labelled
// "SYNTHETIC TEST FIXTURE / NOT ARTWORK", written to temporary folders) stand in for data that does not exist yet.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {loadRegistry, validateRegistry, verifyRegistryAssets} from '../lib/character.mjs';
import {loadEnvironmentRegistry, validateSet, loadSet, verifySetAssets, setFile, MARK_KINDS} from '../lib/sets.mjs';
import {validateProp, loadProp, verifyPropAssets, AFFORDANCES} from '../lib/props.mjs';
import {validateActionLibrary, loadActionLibrary, requiredAnchors, targetOf} from '../lib/actions.mjs';
import {validateStory, STORY_SCHEMA, STORY_SCHEMA_V2} from '../lib/story.mjs';
import {validateStoryReferences, placementMode, layeringMode, assertCompilable} from '../lib/story-v2.mjs';
import {compileProject} from '../lib/scene.mjs';
import {PRODUCTION_ROOT, REPO_ROOT} from '../lib/runtime.mjs';
import {writePlaceholder, PLACEHOLDER_CHARACTER} from './fixtures/ap85-placeholder.mjs';
import {writeSyntheticKit} from './fixtures/ap86-synthetic.mjs';

const tmp = n => fs.mkdtempSync(path.join(os.tmpdir(), `ap86-${n}-`));
const json = f => JSON.parse(fs.readFileSync(f, 'utf8'));
const sha = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const C01_REG = path.join(PRODUCTION_ROOT, 'characters', 'character-01.json');
// Expect every case to fail with its own message: [mutate(copy), pattern].
const rejectsAll = (base, validate, cases) => {
  for (const [mutate, pattern] of cases) { const x = structuredClone(base); mutate(x); assert.throws(() => validate(x), pattern, String(pattern)); }
};

// ---------------------------------------------------------------------------------------------- backward compatibility
test('S1 backward compatibility: every existing registry, environment list and story loads with its existing meaning', async () => {
  const before = fs.readFileSync(C01_REG);
  const reg = loadRegistry(C01_REG);
  assert.equal(reg.schemaVersion, undefined, 'Character 01 registry is v1 and stays so');
  assert.deepEqual(Object.keys(reg.poses), ['01', '02', '03', '04', '05', '06']);
  assert.ok(await verifyRegistryAssets(reg, REPO_ROOT), 'files exist, hashes match, feet anchors inside the images');
  assert.ok(before.equals(fs.readFileSync(C01_REG)), 'loading never changes the registry');
  const envs = loadEnvironmentRegistry();
  assert.deepEqual(Object.keys(envs.environments).sort(), ['living-room-candidate-05', 'living-room-empty-03']);
  for (const dir of ['stories', 'fixtures']) for (const f of fs.readdirSync(path.join(PRODUCTION_ROOT, dir)).filter(n => n.endsWith('.story.json'))) {
    const s = json(path.join(PRODUCTION_ROOT, dir, f));
    assert.equal(s.schema, STORY_SCHEMA, `${f} is story@1`);
    validateStory(s); assertCompilable(s);
    for (const sc of s.scenes) for (const m of sc.cast || []) {
      assert.equal(placementMode(m, null, s.schema), m.placement !== undefined ? 'explicit' : 'default', `${f} ${m.id}: story@1 placement unchanged`);
      assert.equal(layeringMode(m, s.schema), m.z !== undefined ? 'explicit-z' : 'z-default-0', `${f} ${m.id}: story@1 layering unchanged`);
    }
  }
  // The AP-85 placeholder registry (v1 with facings) still loads.
  assert.equal(loadRegistry(writePlaceholder(tmp('ph'))).character, PLACEHOLDER_CHARACTER);
});

// ---------------------------------------------------------------------------------------------- character v2
test('S1 character registry v2: tags, anchors and proportions load; v2 fields are inert for rendering; malformed data is refused', async () => {
  const v2 = r => { r.schemaVersion = 2; r.proportions = {figureHeightRef: 600, headFraction: 0.3};
    r.poses.p1.tags = {stance: 'stand', action: ['talk', 'point'], expression: 'neutral'};
    r.poses.p1.anchors = {feet: {...r.poses.p1.feet}, handRight: {x: 250, y: 300}}; };
  const file = writePlaceholder(tmp('ph-v2'), {mutate: v2}), reg = loadRegistry(file);
  assert.equal(reg.schemaVersion, 2);
  assert.ok(await verifyRegistryAssets(reg, path.dirname(file)));
  const base = json(file);
  rejectsAll(base, r => validateRegistry(r, 'test'), [
    [r => { r.schemaVersion = 3; }, /unsupported schemaVersion 3/],
    [r => { r.schemaVersion = 1; }, /"proportions" needs "schemaVersion": 2/],
    [r => { delete r.schemaVersion; delete r.proportions; }, /Pose p1: "tags" needs "schemaVersion": 2/],
    [r => { r.poses.p1.tags.stance = []; }, /tags\.stance: must not be empty/],
    [r => { r.poses.p1.tags.action = ['talk', 'talk']; }, /tags\.action: has duplicate values/],
    [r => { r.poses.p1.tags.stance = 'Sitting Down'; }, /not a valid identifier/],
    [r => { r.poses.p1.tags['bad key'] = 'x'; }, /tags key: "bad key" is not a valid name/],
    [r => { r.poses.p1.anchors.handRight = {x: -1, y: 3}; }, /anchors\.handRight\.x: must be a number >= 0/],
    [r => { r.poses.p1.anchors.handRight = {x: 1, y: 2, z: 3}; }, /unknown field "z"/],
    [r => { r.poses.p1.anchors.feet = {x: 1, y: 1}; }, /anchors\.feet: must equal the pose's "feet" anchor/],
    [r => { r.proportions.headFraction = 1.5; }, /headFraction: must be a number > 0 and <= 1/],
    [r => { r.proportions.colour = 'red'; }, /unknown field "colour"/],
  ]);
  const outside = writePlaceholder(tmp('ph-out'), {mutate: r => { v2(r); r.poses.p1.anchors.handRight = {x: 5000, y: 10}; }});
  await assert.rejects(verifyRegistryAssets(loadRegistry(outside), path.dirname(outside)), /anchor "handRight" \(5000, 10\) is outside the 300×620 image/);
  // v2 metadata changes nothing in a compiled scene: a v1 and a v2 placeholder registry give byte-identical projects.
  const scene = reg => ({schema: STORY_SCHEMA, id: 'v2-inert', endCard: {duration: 1, caption: 'Technical test'}, scenes: [{id: 's', format: 'face-to-face', environment: 'living-room-empty-03',
    cast: [{id: 'ph', character: PLACEHOLDER_CHARACTER, registry: reg, placement: {feetX: 640, feetY: 2070, figureHeight: 760}, z: 0, speech: {style: 'neutral'}}],
    lines: [{speaker: 'ph', text: 'Same either way.', duration: 1.5, pose: 'p1', shot: {camera: 'Wide'}}]}]});
  const a = await compileProject(scene(writePlaceholder(tmp('ph-v1c'))), {outDir: tmp('out-v1'), allowSynthetic: true});
  const b = await compileProject(scene(file), {outDir: tmp('out-v2'), allowSynthetic: true});
  assert.equal(sha(a.projectFile), sha(b.projectFile));
});

// ---------------------------------------------------------------------------------------------- sets
test('S1 set registry v2: plates, layers, floor model, marks, surfaces and occluders validate; synthetic sets are refused in production', () => {
  const kit = writeSyntheticKit(tmp('set'));
  assert.equal(loadSet('synthetic-bar', {file: kit.setFile, allowSynthetic: true}).set, 'synthetic-bar');
  assert.throws(() => loadSet('synthetic-bar', {file: kit.setFile}), /SYNTHETIC test fixture, not artwork\. It is never used in production/);
  assert.throws(() => loadSet('other', {file: kit.setFile, allowSynthetic: true}), /the registry is for "synthetic-bar"/);
  assert.throws(() => loadSet('no-such-set'), /no set registry \(production[\\/]environments[\\/]no-such-set\.json\)/);
  assert.throws(() => setFile('environments'), /"environments" is reserved/);
  assert.ok(verifySetAssets(json(kit.setFile), kit.dir));
  rejectsAll(kit.data.set, s => validateSet(s), [
    [s => { delete s.schemaVersion; }, /unsupported schemaVersion undefined \(supported: 2\)/],
    [s => { s.schemaVersion = 3; }, /unsupported schemaVersion 3/],
    [s => { s.colour = 'x'; }, /unknown field "colour"/],
    [s => { s.plates = {}; }, /at least one plate is required/],
    [s => { s.plates.wide.layers = []; }, /at least one layer \(back to front\) is required/],
    [s => { s.plates.wide.layers[1].id = 'back'; }, /duplicate layer id/],
    [s => { s.plates.wide.layers[0].file = '../outside.png'; }, /repository-relative path without "\.\."/],
    [s => { s.plates.wide.layers[0].file = 'C:/abs.png'; }, /repository-relative path without "\.\."/],
    [s => { s.plates.wide.layers[0].sha256 = 'abc'; }, /64 lowercase hex characters/],
    [s => { s.plates.wide.layers[0].parallax = 0; }, /parallax: must be a number > 0/],
    [s => { s.plates.wide.layers[1].occluder.baselineY = 1.2; }, /occluder\.baselineY: must be a number >= 0 and <= 1/],
    [s => { s.plates.wide.floor.refFeetY = 0.3; }, /refFeetY must be below the horizon/],
    [s => { delete s.plates.wide.floor.horizonY; }, /floor\.horizonY: must be a number/],
    [s => { s.plates.wide.marks['stool-1'].kind = 'hover'; }, /kind: must be one of stand, seat, entry/],
    [s => { s.plates.wide.marks['stool-1'].point = {x: 1.4, y: 0.5}; }, /mark stool-1\.point\.x: must be a number >= 0 and <= 1/],
    [s => { delete s.plates.wide.marks['stool-1'].point; }, /point: must be a point \{x, y\} in plate fractions/],
    [s => { s.plates.wide.marks['stool-1'].faces = 'up'; }, /faces: must be one of left, right, front/],
    [s => { s.plates.wide.marks.Stool = s.plates.wide.marks['stool-1']; }, /"Stool" is not a valid identifier/],
    [s => { s.plates.wide.surfaces['stool-1'] = {line: {x0: 0.1, x1: 0.2, y: 0.5}}; }, /"stool-1" is already used by another mark or surface/],
    [s => { s.plates.wide.surfaces['counter-top'].line.x1 = 0.1; }, /x1 must be greater than x0/],
    [s => { s.plates.wide.actionSafe.w = 0.9; }, /actionSafe: must be a non-empty rectangle inside the plate/],
    [s => { s.plates.wide.superframe.width = 12.5; }, /superframe\.width: must be a positive integer/],
  ]);
  const broken = json(kit.setFile); broken.plates.wide.layers[0].sha256 = '0'.repeat(64);
  assert.throws(() => verifySetAssets(broken, kit.dir), /layer back: file hash does not match/);
  broken.plates.wide.layers[0].file = 'art/missing.png';
  assert.throws(() => verifySetAssets(broken, kit.dir), /missing file art\/missing\.png/);
  assert.deepEqual(MARK_KINDS, ['stand', 'seat', 'entry']);
});

// ---------------------------------------------------------------------------------------------- props
test('S1 prop registry: states, anchors, affordances and splits validate; synthetic props are refused in production', async () => {
  const kit = writeSyntheticKit(tmp('prop'));
  assert.equal(loadProp('synthetic-stool', {file: kit.propFile, allowSynthetic: true}).prop, 'synthetic-stool');
  assert.throws(() => loadProp('synthetic-stool', {file: kit.propFile}), /SYNTHETIC test fixture, not artwork/);
  assert.throws(() => loadProp('no-such-prop'), /no prop registry \(production[\\/]props[\\/]no-such-prop\.json\)/);
  assert.ok(await verifyPropAssets(json(kit.propFile), kit.dir));
  rejectsAll(kit.data.prop, p => validateProp(p), [
    [p => { p.schemaVersion = 1; }, /unsupported schemaVersion 1 \(supported: 2\)/],
    [p => { p.states = {}; }, /at least one state is required/],
    [p => { delete p.defaultState; }, /defaultState: must name one of its states \(default\)/],
    [p => { p.defaultState = 'broken'; }, /defaultState: must name one of its states/],
    [p => { p.affordances = ['fly']; }, /unknown affordance "fly" \(known: seat, grip, rest\)/],
    [p => { p.affordances = ['seat', 'seat']; }, /affordances: has duplicates/],
    [p => { p.affordances = ['grip']; }, /state default: affordance "grip" needs a "grip" anchor/],
    [p => { p.states.default.anchors.seat = {x: 'a', y: 1}; }, /anchors\.seat\.x: must be a number/],
    [p => { p.states.default.facing = 'diagonal'; }, /facing: must be one of left, right, front/],
    [p => { p.splits = {broken: {front: p.splits.default.front}}; }, /names unknown state "broken"/],
    [p => { p.splits.default = {}; }, /needs a "front" or "back" part/],
    [p => { p.height = 0; }, /height: must be a number > 0/],
    [p => { p.price = 3; }, /unknown field "price"/],
  ]);
  const out = json(kit.propFile); out.states.default.anchors.seat = {x: 61, y: 30};
  await assert.rejects(verifyPropAssets(out, kit.dir), /anchor "seat" \(61, 30\) is outside the 60×120 image/);
  assert.deepEqual(AFFORDANCES, {seat: 'seat', grip: 'grip', rest: 'base'});
});

// ---------------------------------------------------------------------------------------------- actions
test('S1 action definitions: requirements and references must agree; invalid requirements are refused', () => {
  const kit = writeSyntheticKit(tmp('act'));
  const lib = loadActionLibrary(kit.actionsFile);
  assert.deepEqual(Object.fromEntries(Object.entries(lib.actions).map(([k, a]) => [k, targetOf(a)])),
    {'stand-at': 'mark', 'sit-on': 'mark', 'sit-on-prop': 'prop', 'lean-on': 'surface', hold: 'prop', shrug: null});
  assert.deepEqual(requiredAnchors(lib.actions.hold), ['handRight']);
  assert.deepEqual(requiredAnchors(lib.actions['sit-on']), ['seat']);
  assert.throws(() => loadActionLibrary(), /No production action library exists yet/);
  rejectsAll(kit.data.actions, l => validateActionLibrary(l), [
    [l => { l.schemaVersion = 1; }, /unsupported schemaVersion 1/],
    [l => { l.actions = {}; }, /at least one action is required/],
    [l => { l.actions['sit-on'].needs = {mark: 'seat', surface: true}; }, /at most one target \(got mark and surface\)/],
    [l => { l.actions['sit-on'].needs = {mark: 'hover'}; }, /needs\.mark: must be "any" or one of stand, seat, entry/],
    [l => { l.actions['lean-on'].needs = {surface: 'yes'}; }, /needs\.surface: must be true/],
    [l => { l.actions.hold.needs = {prop: 'teleport'}; }, /needs\.prop: must be a prop affordance/],
    [l => { l.actions['lean-on'].align = {handLeft: 'mark.point'}; }, /"mark\.point" needs "needs\.mark"/],
    [l => { l.actions['sit-on'].align = {seat: 'surface.line'}; }, /"surface\.line" needs "needs\.surface"/],
    [l => { l.actions['sit-on'].align = {seat: 'prop.seat'}; }, /"prop\.seat" needs "needs\.prop"/],
    [l => { l.actions['sit-on'].align = {seat: 'chair'}; }, /unknown reference "chair"/],
    [l => { l.actions['sit-on'].align = {}; }, /align: must not be empty when given/],
    [l => { l.actions['sit-on'].attach = {'prop.grip': 'pose.handRight'}; }, /attach: needs "needs\.prop"/],
    [l => { l.actions.hold.attach = {grip: 'pose.handRight'}; }, /key "grip" must be "prop\.<anchor>"/],
    [l => { l.actions.hold.attach = {'prop.grip': 'handRight'}; }, /must be "pose\.<anchor>"/],
    [l => { l.actions['sit-on'].scaleFrom = 'surface.line'; }, /"surface\.line" needs "needs\.surface"/],
    [l => { l.actions['sit-on'].scaleFrom = 'sky'; }, /scaleFrom: must be "mark\.point", "mark\.floor" or "surface\.line"/],
    [l => { l.actions['sit-on'].pose = {stance: 'Sit Down'}; }, /not a valid identifier/],
    [l => { l.actions['sit-on'].speed = 2; }, /unknown field "speed"/],
  ]);
});

// ---------------------------------------------------------------------------------------------- story@2
const castOf = () => [
  {id: 'a', character: 'character-01', speech: {style: 'him'}},
  {id: 'b', character: PLACEHOLDER_CHARACTER, speech: {style: 'neutral'}},
];
function barStory(kit, extra = {}) {
  return {schema: STORY_SCHEMA_V2, id: 'bar', actionLibrary: kit.actionsFile, endCard: {duration: 1, caption: 'Technical test'},
    scenes: [{id: 'bar', format: 'face-to-face', set: 'synthetic-bar', plate: 'wide', setRegistry: kit.setFile, cast: castOf(),
      props: [{id: 'stool-a', prop: 'synthetic-stool', registry: kit.propFile, mark: 'stool-1'},
        {id: 'glass-a', prop: 'synthetic-glass', registry: kit.glassFile, on: 'counter-top', at: 0.35, state: 'full'}],
      blocking: [{who: 'a', do: 'sit-on', mark: 'stool-1'}, {who: 'b', do: 'stand-at', mark: 'counter-2'}],
      lines: [{speaker: 'a', text: 'x', shot: {camera: 'Wide'}}], ...extra}]};
}

test('S1 story@2 structure: sets, props and blocking are validated; story@1 cannot carry story@2 fields', () => {
  const kit = writeSyntheticKit(tmp('story'));
  validateStory(barStory(kit));
  const base = barStory(kit), sc = s => s.scenes[0];
  rejectsAll(base, validateStory, [
    [s => { s.schema = STORY_SCHEMA; delete s.actionLibrary; }, /"set" needs "oddly-relatable\/story@2"/],
    [s => { s.schema = 'oddly-relatable/story@3'; }, /Story schema must be "oddly-relatable\/story@1" or "oddly-relatable\/story@2"/],
    [s => { sc(s).environment = 'living-room-empty-03'; }, /uses both "environment" and "set"/],
    [s => { delete sc(s).plate; }, /plate: "undefined" is not a valid identifier/],
    [s => { delete sc(s).set; delete sc(s).props; delete sc(s).blocking; }, /"plate" needs "set"/],
    [s => { sc(s).props[0].on = 'counter-top'; }, /needs exactly one of "on" \(a surface\), "mark" or "placement"/],
    [s => { delete sc(s).props[0].mark; }, /needs exactly one of "on" \(a surface\), "mark" or "placement"/],
    [s => { sc(s).props[0].at = 0.5; }, /at: needs "on"/],
    [s => { sc(s).props[1].at = 2; }, /at: must be a number >= 0 and <= 1/],
    [s => { sc(s).props[1].id = 'a'; }, /id "a" is already used by another prop or cast member/],
    [s => { sc(s).props[0].colour = 'x'; }, /unknown field "colour"/],
    [s => { sc(s).props[0].placement = {x: 0.5, y: 1.5}; delete sc(s).props[0].mark; }, /placement\.y: must be a number >= 0 and <= 1/],
    [s => { sc(s).blocking[0].who = 'ghost'; }, /"who": "ghost" is not a cast member/],
    [s => { sc(s).blocking.push({who: 'a', do: 'shrug'}); }, /"a" is already blocked/],
    [s => { sc(s).blocking[0].surface = 'counter-top'; }, /names more than one target \(mark, surface\)/],
    [s => { sc(s).blocking[0] = {who: 'a', do: 'hold', prop: 'cup'}; }, /"prop": "cup" is not a prop of this scene/],
    [s => { sc(s).blocking[0].speed = 3; }, /unknown field "speed"/],
  ]);
  const v1 = {schema: STORY_SCHEMA, id: 'x', actionLibrary: 'a.json', scenes: [{id: 's', format: 'face-to-face'}]};
  assert.throws(() => validateStory(v1), /"actionLibrary" needs "oddly-relatable\/story@2"/);
});

test('S1 story@2 references: every set, plate, mark, surface, prop, state and action is checked; O3 and O4 precedence is recorded', () => {
  const kit = writeSyntheticKit(tmp('refs'));
  const desc = validateStoryReferences(barStory(kit), {allowSynthetic: true}).scenes[0];
  assert.deepEqual(desc.members, [{id: 'a', placement: 'blocking', layering: 'depth'}, {id: 'b', placement: 'blocking', layering: 'depth'}]);
  assert.deepEqual(desc.props, [{id: 'stool-a', prop: 'synthetic-stool', placement: 'mark', layering: 'depth'}, {id: 'glass-a', prop: 'synthetic-glass', placement: 'surface', layering: 'depth'}]);
  // O3: explicit placement wins over blocking. O4: explicit z wins over depth.
  const explicit = barStory(kit); explicit.scenes[0].cast[0].placement = {feetX: 400, feetY: 2070, figureHeight: 760}; explicit.scenes[0].cast[0].z = 2;
  explicit.scenes[0].props[0] = {id: 'stool-a', prop: 'synthetic-stool', registry: kit.propFile, placement: {x: 0.4, y: 0.8}, z: 1};
  const d2 = validateStoryReferences(explicit, {allowSynthetic: true}).scenes[0];
  assert.deepEqual(d2.members[0], {id: 'a', placement: 'explicit', blockingOverriddenByExplicitPlacement: true, layering: 'explicit-z'});
  assert.deepEqual(d2.props[0], {id: 'stool-a', prop: 'synthetic-stool', placement: 'explicit', layering: 'explicit-z'});
  const noBlock = barStory(kit); noBlock.scenes[0].blocking = [noBlock.scenes[0].blocking[0]];
  assert.equal(validateStoryReferences(noBlock, {allowSynthetic: true}).scenes[0].members[1].placement, 'unplaced');

  const bad = (mutate, pattern) => { const s = barStory(kit); mutate(s.scenes[0], s); validateStory(s); assert.throws(() => validateStoryReferences(s, {allowSynthetic: true}), pattern, String(pattern)); };
  bad(sc => { sc.plate = 'close'; }, /set synthetic-bar: no plate "close" \(plates: wide\)/);
  bad(sc => { sc.props[0].mark = 'stool-9'; }, /plate "wide" has no mark "stool-9"/);
  bad(sc => { sc.props[1].on = 'shelf'; }, /plate "wide" has no surface "shelf"/);
  bad(sc => { sc.props[1].state = 'broken'; }, /prop "synthetic-glass" has no state "broken" \(states: full, empty\)/);
  bad(sc => { sc.blocking[0].do = 'fly'; }, /unknown action "fly"/);
  bad(sc => { sc.blocking[0].mark = 'counter-2'; }, /mark "counter-2" is a stand mark; action "sit-on" needs a seat mark/);
  bad(sc => { sc.blocking[0] = {who: 'a', do: 'sit-on', surface: 'counter-top'}; }, /action "sit-on" needs a mark, not a surface/);
  bad(sc => { sc.blocking[0] = {who: 'a', do: 'sit-on'}; }, /action "sit-on" needs a mark$/);
  bad(sc => { sc.blocking[0] = {who: 'a', do: 'shrug', mark: 'stool-1'}; }, /action "shrug" takes no target/);
  bad(sc => { sc.blocking[0] = {who: 'a', do: 'hold', prop: 'stool-a'}; }, /prop "stool-a" \(synthetic-stool\) does not offer "grip"/);
  bad(sc => { sc.blocking[0] = {who: 'a', do: 'lean-on', surface: 'shelf'}; }, /plate "wide" has no surface "shelf"/);
  bad((sc, s) => { delete s.actionLibrary; }, /No production action library exists yet/);
  // Holding and sitting on a prop resolve when the prop offers the affordance.
  const ok = barStory(kit); ok.scenes[0].blocking = [{who: 'a', do: 'sit-on-prop', prop: 'stool-a'}, {who: 'b', do: 'hold', prop: 'glass-a'}];
  assert.deepEqual(validateStoryReferences(ok, {allowSynthetic: true}).scenes[0].members.map(m => m.placement), ['blocking', 'blocking']);
  // Synthetic sets and props are refused without allowSynthetic.
  assert.throws(() => validateStoryReferences(barStory(kit)), /set "synthetic-bar" is a SYNTHETIC test fixture/);
});

// ---------------------------------------------------------------------------------------------- compile gate
test('S1 compile gate: story@2 compiles only what needs no later phase; anything else is refused with the phase it needs', async () => {
  const kit = writeSyntheticKit(tmp('gate'));
  const refuse = (s, pattern) => assert.throws(() => assertCompilable(s), pattern, String(pattern));
  refuse(barStory(kit), /uses a set; rendering sets needs AP-86 S2/);
  const noSet = s => { const sc = s.scenes[0]; delete sc.set; delete sc.plate; delete sc.setRegistry; return s; };
  const p = noSet(barStory(kit)); p.scenes[0].blocking = []; p.scenes[0].props = [{id: 'x', prop: 'y', placement: {x: 0.5, y: 0.5}}];
  refuse(p, /uses props; placing props needs AP-86 S3/);
  const b = noSet(barStory(kit)); b.scenes[0].props = [];
  refuse(b, /uses blocking; the staging resolver needs AP-86 S3/);
  const u = noSet(barStory(kit)); u.scenes[0].props = []; u.scenes[0].blocking = [];
  refuse(u, /cast member "a" has no placement\. In story@2 members are placed by marks and actions \(O3, needs AP-86 S3\)/);
  for (const m of u.scenes[0].cast) m.placement = {feetX: 640, feetY: 2070, figureHeight: 760};
  refuse(u, /cast member "a" has no "z"\. In story@2 layering is derived from depth by default \(O4, needs AP-86 S2\)/);

  // What S1 can compile from story@2 compiles exactly as story@1: Short 001 as a story@2 file gives the same project.
  const short = json(path.join(PRODUCTION_ROOT, 'stories', 'short-001-v2.story.json'));
  const v2 = {...structuredClone(short), schema: STORY_SCHEMA_V2};
  const a = await compileProject(short, {outDir: tmp('short-v1')}), c = await compileProject(v2, {outDir: tmp('short-v2')});
  assert.equal(sha(a.projectFile), sha(c.projectFile), 'story@2 with explicit placement and z compiles byte-identically');
});
