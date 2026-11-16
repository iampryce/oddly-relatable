// Story@2 (AP-86 S1: data model and validation only). Additive to story@1:
//
//   story:  {schema: "oddly-relatable/story@2", actionLibrary?: <path>, ...every story@1 field}
//   scene:  every story@1 scene field, plus
//     set?, plate?, setRegistry?          a v2 set and one of its plates (instead of "environment", never both)
//     props?: [{id, prop, registry?, state?, on?: <surface>, at?: 0–1, mark?: <mark>, placement?: {x, y}, z?, note?}]
//             (at most one of on / mark / placement; a prop with none must be held by a "hold" action)
//     blocking?: [{who: <cast id>, do: <action id>, mark? | surface? | prop?: <scene prop id>, at?: 0–1, note?}]
//             (at most one placing action per member; any number of attaching actions such as "hold")
//
// Precedence (owner decisions, 2026-11-15):
//   O3  named marks and actions are the default placement; an explicit placement wins over blocking.
//   O4  depth-derived layering is the default; an explicit z wins.
// story@1 keeps its existing meaning exactly: explicit or default placement, explicit z (default 0).
//
// S1 validates and describes. S2 (approved 2026-11-16) compiles sets (face-to-face scenes), explicit placement in
// plate coordinates and depth-derived layering (see depth.mjs, sets.mjs). Props, blocking and unplaced members still
// need the staging resolver (S3) and are refused by assertCompilable() with that phase named.
import {loadSet, plateOf} from './sets.mjs';
import {loadProp} from './props.mjs';
import {loadActionLibrary, targetOf, actionKind, ACTIONS_FILE} from './actions.mjs';
import {object, onlyKeys, id, finite, fraction, point01, fail} from './schema.mjs';
import {placementKind} from './depth.mjs';

export const STORY_SCHEMA_V1 = 'oddly-relatable/story@1';
export const STORY_SCHEMA_V2 = 'oddly-relatable/story@2';
export const V2_SCENE_FIELDS = Object.freeze(['set', 'plate', 'setRegistry', 'props', 'blocking']);
// Registry overrides are paths, like the existing cast "registry" (repository-relative, or absolute for test fixtures).
const regPath = (v, w) => { if (typeof v !== 'string' || !v) fail(w, 'must be a path'); return v; };

// ------------------------------------------------------------------------------------------ structure (no files)
export function validateSceneV2(scene, where) {
  const castIds = new Set((Array.isArray(scene.cast) ? scene.cast : []).map(m => m?.id));
  if (scene.set !== undefined) {
    id(scene.set, `${where} set`);
    if (scene.environment !== undefined && scene.environment !== null) fail(where, 'uses both "environment" and "set"; a scene has one or the other');
    id(scene.plate, `${where} plate`);
  } else {
    for (const k of ['plate', 'setRegistry']) if (scene[k] !== undefined) fail(where, `"${k}" needs "set"`);
  }
  if (scene.setRegistry !== undefined) regPath(scene.setRegistry, `${where} setRegistry`);
  // Explicit placement (S2): world units, or plate coordinates (which need a set). z, when given, must be a number.
  for (const m of Array.isArray(scene.cast) ? scene.cast : []) {
    const w = `${where} cast member "${m?.id}" placement`;
    if (placementKind(m?.placement, w) === 'plate' && scene.set === undefined) fail(w, 'plate coordinates need a scene "set"');
    if (m?.z !== undefined) finite(m.z, `${where} cast member "${m.id}" z`);
  }

  const propIds = new Set();
  if (scene.props !== undefined) {
    if (!Array.isArray(scene.props)) fail(`${where} props`, 'must be a list');
    if (scene.set === undefined && scene.props.length) fail(`${where} props`, 'props need a "set" (they are placed in set coordinates)');
    scene.props.forEach((p, i) => {
      const w = `${where} prop ${p?.id ?? i + 1}`;
      object(p, w); onlyKeys(p, ['id', 'prop', 'registry', 'state', 'on', 'at', 'mark', 'placement', 'z', 'note'], w);
      id(p.id, `${w} id`); id(p.prop, `${w} prop`);
      if (propIds.has(p.id) || castIds.has(p.id)) fail(w, `id "${p.id}" is already used by another prop or cast member`);
      propIds.add(p.id);
      if (p.registry !== undefined) regPath(p.registry, `${w} registry`);
      if (p.state !== undefined) id(p.state, `${w} state`);
      const where_ = ['on', 'mark', 'placement'].filter(k => p[k] !== undefined);
      if (where_.length > 1) fail(w, 'has more than one of "on" (a surface), "mark" and "placement"');
      if (p.on !== undefined) id(p.on, `${w} on`);
      if (p.at !== undefined) { if (p.on === undefined) fail(`${w} at`, 'needs "on"'); fraction(p.at, `${w} at`); }
      if (p.mark !== undefined) id(p.mark, `${w} mark`);
      if (p.placement !== undefined) point01(p.placement, `${w} placement`);
      if (p.z !== undefined) finite(p.z, `${w} z`);
    });
  }

  if (scene.blocking !== undefined) {
    if (!Array.isArray(scene.blocking)) fail(`${where} blocking`, 'must be a list');
    scene.blocking.forEach((b, i) => {
      const w = `${where} blocking ${i + 1}`;
      object(b, w); onlyKeys(b, ['who', 'do', 'mark', 'surface', 'prop', 'at', 'note'], w);
      if (!castIds.has(b.who)) fail(w, `"who": "${b.who}" is not a cast member of this scene`);
      id(b.do, `${w} do`);
      if (b.at !== undefined) { if (b.surface === undefined) fail(`${w} at`, 'needs "surface"'); fraction(b.at, `${w} at`); }
      const targets = ['mark', 'surface', 'prop'].filter(k => b[k] !== undefined);
      if (targets.length > 1) fail(w, `names more than one target (${targets.join(', ')})`);
      for (const k of targets) id(b[k], `${w} ${k}`);
      if ((b.mark !== undefined || b.surface !== undefined) && scene.set === undefined) fail(w, 'marks and surfaces need a "set"');
      if (b.prop !== undefined && !propIds.has(b.prop)) fail(w, `"prop": "${b.prop}" is not a prop of this scene`);
    });
  }
  return scene;
}

// ------------------------------------------------------------------------------------------ precedence (O3, O4)
// Where a cast member's position comes from: explicit placement wins (O3); otherwise its blocking; otherwise, in
// story@1 only, the existing default placement.
export function placementMode(member, blocking, schema) {
  if (member.placement !== undefined) return 'explicit';
  if (schema === STORY_SCHEMA_V2) return blocking ? 'blocking' : 'unplaced';
  return 'default';
}
// How a member or prop is layered: explicit z wins (O4); otherwise depth-derived in story@2. story@1 keeps its
// existing rule (z, default 0).
export function layeringMode(item, schema) {
  if (item.z !== undefined) return 'explicit-z';
  return schema === STORY_SCHEMA_V2 ? 'depth' : 'z-default-0';
}

// ------------------------------------------------------------------------------------------ references (files)
// Checks every reference of a story@2 against the registries: set and plate, props (registry, state, surface, mark),
// blocking (action, its target kind, mark kind, surface, prop affordance). Returns a description of each scene with
// the precedence that applies to every member and prop. Synthetic (test) sets and props need allowSynthetic.
export function validateStoryReferences(story, {allowSynthetic = false} = {}) {
  if (story.schema !== STORY_SCHEMA_V2) fail('story', `validateStoryReferences applies to ${STORY_SCHEMA_V2}`);
  let library = null;
  const lib = () => library ??= loadActionLibrary(story.actionLibrary ?? ACTIONS_FILE);
  return {scenes: story.scenes.map(scene => {
    const where = `scene ${scene.id}`;
    const set = scene.set !== undefined ? loadSet(scene.set, {file: scene.setRegistry ?? null, allowSynthetic}) : null;
    const plate = set ? plateOf(set, scene.plate, `${where} set ${set.set}`) : null;
    const marks = plate?.marks || {}, surfaces = plate?.surfaces || {};
    const props = new Map();
    for (const p of scene.props || []) {
      const w = `${where} prop ${p.id}`;
      const reg = loadProp(p.prop, {file: p.registry ?? null, allowSynthetic});
      if (p.state !== undefined && !reg.states[p.state]) fail(w, `prop "${reg.prop}" has no state "${p.state}" (states: ${Object.keys(reg.states).join(', ')})`);
      if (p.on !== undefined && !surfaces[p.on]) fail(w, `plate "${scene.plate}" has no surface "${p.on}"`);
      if (p.mark !== undefined && !marks[p.mark]) fail(w, `plate "${scene.plate}" has no mark "${p.mark}"`);
      props.set(p.id, {...p, registryData: reg});
    }
    const blockingOf = new Map(), heldBy = new Map(), usedAsTarget = new Set();
    for (const [i, b] of (scene.blocking || []).entries()) {
      const w = `${where} blocking ${i + 1} (${b.who} ${b.do})`;
      const action = lib().actions[b.do];
      if (!action) fail(w, `unknown action "${b.do}" (library has: ${Object.keys(lib().actions).join(', ')})`);
      const need = targetOf(action), given = ['mark', 'surface', 'prop'].filter(k => b[k] !== undefined)[0] ?? null;
      if (need !== given) fail(w, need ? `action "${b.do}" needs a ${need}${given ? `, not a ${given}` : ''}` : `action "${b.do}" takes no target`);
      if (need === 'mark') {
        const m = marks[b.mark];
        if (!m) fail(w, `plate "${scene.plate}" has no mark "${b.mark}"`);
        if (action.needs.mark !== 'any' && m.kind !== action.needs.mark) fail(w, `mark "${b.mark}" is a ${m.kind} mark; action "${b.do}" needs a ${action.needs.mark} mark`);
      }
      if (need === 'surface' && !surfaces[b.surface]) fail(w, `plate "${scene.plate}" has no surface "${b.surface}"`);
      if (need === 'surface' && actionKind(action) === 'place' && b.at === undefined) fail(w, 'needs "at": where along the surface (0 to 1)');
      if (need === 'prop') {
        const p = props.get(b.prop);
        if (!(p.registryData.affordances || []).includes(action.needs.prop)) fail(w, `prop "${b.prop}" (${p.prop}) does not offer "${action.needs.prop}"`);
      }
      // S3 rules: one placing action per member; a prop is held by at most one member; a held prop is not also placed,
      // sat on or given a z (it is drawn with its holder).
      if (actionKind(action) === 'place') {
        if (blockingOf.has(b.who)) fail(w, `cast member "${b.who}" already has a placing action ("${blockingOf.get(b.who).do}")`);
        blockingOf.set(b.who, b);
        if (need === 'prop') usedAsTarget.add(b.prop);
      }
      if (actionKind(action) === 'attach') {
        if (heldBy.has(b.prop)) fail(w, `prop "${b.prop}" is already held by "${heldBy.get(b.prop)}"`);
        heldBy.set(b.prop, b.who);
      }
    }
    for (const [pid, p] of props) {
      const w = `${where} prop ${pid}`, placed = ['on', 'mark', 'placement'].some(k => p[k] !== undefined);
      if (heldBy.has(pid) && placed) fail(w, `is held by "${heldBy.get(pid)}", so it cannot also be placed ("on", "mark" or "placement")`);
      if (!heldBy.has(pid) && !placed) fail(w, 'is neither placed ("on", "mark" or "placement") nor held');
      if (heldBy.has(pid) && usedAsTarget.has(pid)) fail(w, 'cannot be both held and used as a placing target');
      if ((heldBy.has(pid) || usedAsTarget.has(pid)) && p.z !== undefined) fail(w, 'is used by a cast member and is drawn with it; remove its "z"');
      if (p.on !== undefined && p.at === undefined) fail(w, 'needs "at": where along the surface (0 to 1)');
    }
    return {
      id: scene.id, set: set?.set ?? null, plate: scene.plate ?? null,
      members: (scene.cast || []).map(m => ({id: m.id, placement: placementMode(m, blockingOf.get(m.id), story.schema),
        ...(m.placement !== undefined && blockingOf.has(m.id) ? {blockingOverriddenByExplicitPlacement: true} : {}), layering: layeringMode(m, story.schema)})),
      props: [...props.values()].map(p => ({id: p.id, prop: p.prop, placement: heldBy.has(p.id) ? `held-by:${heldBy.get(p.id)}` : p.placement !== undefined ? 'explicit' : p.on !== undefined ? 'surface' : 'mark', layering: heldBy.has(p.id) ? 'with-holder' : layeringMode(p, story.schema)})),
    };
  })};
}

// ------------------------------------------------------------------------------------------ compile gate
// What can be compiled from a story@2 after S3: explicit placement, depth-derived or explicit-z layering, sets in
// face-to-face scenes, and (S3, approved 2026-11-16) props and blocking resolved by the staging resolver. A member with
// neither an explicit placement nor any blocking is refused here; one whose blocking places nothing is refused by the
// resolver. Everything that needs a later phase is refused rather than approximated.
export const SET_FORMATS = Object.freeze(['face-to-face']);
export function assertCompilable(story) {
  if (story.schema !== STORY_SCHEMA_V2) return;
  for (const s of story.scenes) {
    const where = `story@2 scene ${s.id}`;
    if (s.set !== undefined && !SET_FORMATS.includes(s.format)) fail(where, `uses a set in a "${s.format}" scene; AP-86 S2 renders sets in ${SET_FORMATS.join(', ')} scenes only`);
    if ((s.props?.length || s.blocking?.length) && s.set === undefined) fail(where, 'props and blocking need a "set"');
    const blocked = new Set((s.blocking || []).map(b => b.who));
    for (const m of Array.isArray(s.cast) ? s.cast : []) {
      if (placementMode(m, blocked.has(m.id) ? true : null, story.schema) === 'unplaced') fail(where, `cast member "${m.id}" has no placement. In story@2 a member is placed by a placing action at a mark, surface or prop (O3) or by an explicit "placement"`);
    }
  }
}
