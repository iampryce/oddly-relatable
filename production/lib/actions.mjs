// Action definitions (AP-86 S1: data model and validation only). An action library is a data file:
//
//   {schemaVersion: 2, note?, actions: {actionId: {
//      needs:     {} | {mark: <mark kind> | "any"} | {surface: true} | {prop: <affordance>},   (at most one target)
//      pose?:     {<tag name>: <id>, ..., hasAnchor?: <name> | [<name>...]},   (which kind of pose, by tags)
//      align?:    {<pose anchor>: "mark.point" | "mark.floor" | "surface.line" | "prop.<anchor>"},
//      attach?:   {"prop.<anchor>": "pose.<anchor>"},
//      scaleFrom?: "mark.point" | "mark.floor" | "surface.line",
//      note?}}}
//
// Actions never name a character, set or story: they say what they need (a kind of mark, a surface, a prop
// affordance), which kind of pose, and which anchors to line up. Every reference must agree with "needs", so an
// action can never point at a target it does not require. Running actions (the staging resolver) is AP-86 S3.
// The pose tag vocabulary is not fixed here (pose standards are owner decision O6).
import fs from 'node:fs';
import path from 'node:path';
import {PRODUCTION_ROOT, REPO_ROOT} from './runtime.mjs';
import {MARK_KINDS} from './sets.mjs';
import {AFFORDANCES} from './props.mjs';
import {object, onlyKeys, id, name, idMap, schemaVersion, fail} from './schema.mjs';

export const ACTIONS_SCHEMA_VERSION = 2;
export const ACTIONS_FILE = path.join(PRODUCTION_ROOT, 'actions', 'actions.json');
const MARK_REFS = ['mark.point', 'mark.floor'];

// Which target an action needs: 'mark' | 'surface' | 'prop' | null.
export const targetOf = action => Object.keys(action.needs)[0] ?? null;

// The pose anchors an action requires (align keys, attach targets, hasAnchor), for later pose checks.
export function requiredAnchors(action) {
  const out = new Set(Object.keys(action.align || {}));
  for (const v of Object.values(action.attach || {})) out.add(v.slice('pose.'.length));
  const h = action.pose?.hasAnchor;
  for (const a of h === undefined ? [] : Array.isArray(h) ? h : [h]) out.add(a);
  return [...out].sort();
}

export function validateAction(a, where) {
  object(a, where);
  onlyKeys(a, ['needs', 'pose', 'align', 'attach', 'scaleFrom', 'note'], where);
  // needs: at most one target.
  object(a.needs, `${where}.needs`, 'an object ({} for no target)');
  onlyKeys(a.needs, ['mark', 'surface', 'prop'], `${where}.needs`);
  const targets = Object.keys(a.needs);
  if (targets.length > 1) fail(`${where}.needs`, `an action needs at most one target (got ${targets.join(' and ')})`);
  if ('mark' in a.needs && a.needs.mark !== 'any' && !MARK_KINDS.includes(a.needs.mark)) fail(`${where}.needs.mark`, `must be "any" or one of ${MARK_KINDS.join(', ')}`);
  if ('surface' in a.needs && a.needs.surface !== true) fail(`${where}.needs.surface`, 'must be true');
  if ('prop' in a.needs && !AFFORDANCES[a.needs.prop]) fail(`${where}.needs.prop`, `must be a prop affordance (${Object.keys(AFFORDANCES).join(', ')})`);
  const target = targets[0] ?? null;
  // A reference to a target is only valid when the action needs that target.
  const ref = (r, w) => {
    if (typeof r !== 'string') fail(w, 'must be text');
    if (MARK_REFS.includes(r)) { if (target !== 'mark') fail(w, `"${r}" needs "needs.mark"`); return; }
    if (r === 'surface.line') { if (target !== 'surface') fail(w, '"surface.line" needs "needs.surface"'); return; }
    if (r.startsWith('prop.')) {
      if (target !== 'prop') fail(w, `"${r}" needs "needs.prop"`);
      name(r.slice(5), `${w} prop anchor`); return;
    }
    fail(w, `unknown reference "${r}" (use ${[...MARK_REFS, 'surface.line', 'prop.<anchor>'].join(', ')})`);
  };
  if (a.pose !== undefined) {
    object(a.pose, `${where}.pose`);
    for (const [k, v] of Object.entries(a.pose)) {
      if (k === 'hasAnchor') { (Array.isArray(v) ? v : [v]).forEach((x, i) => name(x, `${where}.pose.hasAnchor[${i}]`)); continue; }
      name(k, `${where}.pose key`); id(v, `${where}.pose.${k}`);
    }
  }
  if (a.align !== undefined) {
    object(a.align, `${where}.align`);
    if (!Object.keys(a.align).length) fail(`${where}.align`, 'must not be empty when given');
    for (const [k, r] of Object.entries(a.align)) { name(k, `${where}.align key`); ref(r, `${where}.align.${k}`); }
  }
  if (a.attach !== undefined) {
    object(a.attach, `${where}.attach`);
    if (target !== 'prop') fail(`${where}.attach`, 'needs "needs.prop"');
    for (const [k, v] of Object.entries(a.attach)) {
      if (!k.startsWith('prop.')) fail(`${where}.attach`, `key "${k}" must be "prop.<anchor>"`);
      name(k.slice(5), `${where}.attach key anchor`);
      if (typeof v !== 'string' || !v.startsWith('pose.')) fail(`${where}.attach.${k}`, 'must be "pose.<anchor>"');
      name(v.slice(5), `${where}.attach.${k} anchor`);
    }
  }
  if (a.scaleFrom !== undefined) {
    if (!['mark.point', 'mark.floor', 'surface.line'].includes(a.scaleFrom)) fail(`${where}.scaleFrom`, 'must be "mark.point", "mark.floor" or "surface.line"');
    ref(a.scaleFrom, `${where}.scaleFrom`);
  }
  return a;
}

export function validateActionLibrary(lib, where = 'action library') {
  object(lib, where);
  onlyKeys(lib, ['schemaVersion', 'note', 'actions'], where);
  schemaVersion(lib.schemaVersion, [ACTIONS_SCHEMA_VERSION], where);
  if (!Object.keys(object(lib.actions, `${where}.actions`)).length) fail(`${where}.actions`, 'at least one action is required');
  idMap(lib.actions, `${where} action`, (aid, a) => validateAction(a, `${where} action ${aid}`));
  return lib;
}

export function loadActionLibrary(file = ACTIONS_FILE) {
  const f = path.resolve(REPO_ROOT, file);
  if (!fs.existsSync(f)) throw new Error(`action library: not found (${path.relative(REPO_ROOT, f)}). No production action library exists yet; its contents follow owner decisions on pose standards (O6)`);
  return validateActionLibrary(JSON.parse(fs.readFileSync(f, 'utf8')), `action library ${path.basename(f)}`);
}
