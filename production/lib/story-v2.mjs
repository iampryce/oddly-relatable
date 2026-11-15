// Story@2 (AP-86 S1: data model and validation only). Additive to story@1:
//
//   story:  {schema: "oddly-relatable/story@2", actionLibrary?: <path>, ...every story@1 field}
//   scene:  every story@1 scene field, plus
//     set?, plate?, setRegistry?          a v2 set and one of its plates (instead of "environment", never both)
//     props?: [{id, prop, registry?, state?, on?: <surface>, at?: 0–1, mark?: <mark>, placement?: {x, y}, z?, note?}]
//     blocking?: [{who: <cast id>, do: <action id>, mark? | surface? | prop?: <scene prop id>, note?}]
//
// Precedence (owner decisions, 2026-11-15):
//   O3  named marks and actions are the default placement; an explicit placement wins over blocking.
//   O4  depth-derived layering is the default; an explicit z wins.
// story@1 keeps its existing meaning exactly: explicit or default placement, explicit z (default 0).
//
// S1 validates and describes; it does not stage, render or layer anything. A story@2 scene that relies on a set,
// props, blocking or depth-derived layering is refused by assertCompilable() with the phase it needs.
import {loadSet, plateOf} from './sets.mjs';
import {loadProp} from './props.mjs';
import {loadActionLibrary, targetOf, ACTIONS_FILE} from './actions.mjs';
import {object, onlyKeys, id, finite, fraction, point01, fail} from './schema.mjs';

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
      if (where_.length !== 1) fail(w, 'needs exactly one of "on" (a surface), "mark" or "placement"');
      if (p.on !== undefined) id(p.on, `${w} on`);
      if (p.at !== undefined) { if (p.on === undefined) fail(`${w} at`, 'needs "on"'); fraction(p.at, `${w} at`); }
      if (p.mark !== undefined) id(p.mark, `${w} mark`);
      if (p.placement !== undefined) point01(p.placement, `${w} placement`);
      if (p.z !== undefined) finite(p.z, `${w} z`);
    });
  }

  if (scene.blocking !== undefined) {
    if (!Array.isArray(scene.blocking)) fail(`${where} blocking`, 'must be a list');
    const blocked = new Set();
    scene.blocking.forEach((b, i) => {
      const w = `${where} blocking ${i + 1}`;
      object(b, w); onlyKeys(b, ['who', 'do', 'mark', 'surface', 'prop', 'note'], w);
      if (!castIds.has(b.who)) fail(w, `"who": "${b.who}" is not a cast member of this scene`);
      if (blocked.has(b.who)) fail(w, `cast member "${b.who}" is already blocked in this scene`);
      blocked.add(b.who);
      id(b.do, `${w} do`);
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
    const blockingOf = new Map();
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
      if (need === 'prop') {
        const p = props.get(b.prop);
        if (!(p.registryData.affordances || []).includes(action.needs.prop)) fail(w, `prop "${b.prop}" (${p.prop}) does not offer "${action.needs.prop}"`);
      }
      blockingOf.set(b.who, b);
    }
    return {
      id: scene.id, set: set?.set ?? null, plate: scene.plate ?? null,
      members: (scene.cast || []).map(m => ({id: m.id, placement: placementMode(m, blockingOf.get(m.id), story.schema),
        ...(m.placement !== undefined && blockingOf.has(m.id) ? {blockingOverriddenByExplicitPlacement: true} : {}), layering: layeringMode(m, story.schema)})),
      props: [...props.values()].map(p => ({id: p.id, prop: p.prop, placement: p.placement !== undefined ? 'explicit' : p.on !== undefined ? 'surface' : 'mark', layering: layeringMode(p, story.schema)})),
    };
  })};
}

// ------------------------------------------------------------------------------------------ compile gate
// What S1 can compile from a story@2: exactly what story@1 can (explicit placement; explicit z when several members
// share a scene). Everything that needs a later phase is refused, naming that phase, rather than approximated.
export function assertCompilable(story) {
  if (story.schema !== STORY_SCHEMA_V2) return;
  for (const s of story.scenes) {
    const where = `story@2 scene ${s.id}`;
    if (s.set !== undefined) fail(where, 'uses a set; rendering sets needs AP-86 S2 (not implemented)');
    if (s.props?.length) fail(where, 'uses props; placing props needs AP-86 S3 (not implemented)');
    if (s.blocking?.length) fail(where, 'uses blocking; the staging resolver needs AP-86 S3 (not implemented)');
    const cast = Array.isArray(s.cast) ? s.cast : [];
    for (const m of cast) {
      if (placementMode(m, null, story.schema) === 'unplaced') fail(where, `cast member "${m.id}" has no placement. In story@2 members are placed by marks and actions (O3, needs AP-86 S3) or by an explicit "placement"`);
      if (cast.length > 1 && layeringMode(m, story.schema) === 'depth') fail(where, `cast member "${m.id}" has no "z". In story@2 layering is derived from depth by default (O4, needs AP-86 S2); give an explicit "z"`);
    }
  }
}
