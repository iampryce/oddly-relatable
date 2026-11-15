// Prop registry (AP-86 S1: data model and validation only). One prop per file: production/props/<prop-id>.json.
//
//   {prop, schemaVersion: 2, displayName?, synthetic?, note?,
//    defaultState, states: {stateId: {file, sha256?, facing?, anchors?: {name: {x, y}}, note?}},
//    affordances?: [kind...], height?, splits?: {stateId: {front?: asset, back?: asset}}}
//
// Anchors are image-pixel points, like a pose's "feet". An affordance says what the prop offers to an action, and
// names the anchor every state must have for it. Splits are optional parts drawn over or under a member using the
// prop (e.g. a stool's front rim over a seated character); composing them is AP-86 S2/S3, not done here.
// NOT DECIDED (O7): prop art standards (sizes, which props are separate from plates). "height" is optional and only
// checked to be positive; no size standard is imposed.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {canvas, PRODUCTION_ROOT, REPO_ROOT} from './runtime.mjs';
import {POSE_FACINGS} from './character.mjs';
import {object, onlyKeys, id, name, finite, pixelPoint, asset, idMap, schemaVersion, fail} from './schema.mjs';

export const PROP_SCHEMA_VERSION = 2;
// Affordance -> the anchor each state must provide for it. Minimal engine semantics; S3 may add kinds in code.
export const AFFORDANCES = Object.freeze({seat: 'seat', grip: 'grip', rest: 'base'});
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');

export const propFile = propId => path.join(PRODUCTION_ROOT, 'props', `${id(propId, 'prop id')}.json`);

export function validateProp(prop, where = `prop ${prop?.prop ?? '?'}`) {
  object(prop, where);
  onlyKeys(prop, ['prop', 'schemaVersion', 'displayName', 'synthetic', 'note', 'defaultState', 'states', 'affordances', 'height', 'splits'], where);
  id(prop.prop, `${where} "prop"`);
  schemaVersion(prop.schemaVersion, [PROP_SCHEMA_VERSION], where);
  if (prop.synthetic !== undefined && typeof prop.synthetic !== 'boolean') fail(`${where}.synthetic`, 'must be true or false');
  if (!Object.keys(object(prop.states, `${where}.states`)).length) fail(`${where}.states`, 'at least one state is required');
  idMap(prop.states, `${where} state`, (sid, s, w) => {
    object(s, w); onlyKeys(s, ['file', 'sha256', 'facing', 'anchors', 'note'], w);
    asset({file: s.file, ...(s.sha256 !== undefined ? {sha256: s.sha256} : {})}, w);
    if (s.facing !== undefined && !POSE_FACINGS.includes(s.facing)) fail(`${w}.facing`, `must be one of ${POSE_FACINGS.join(', ')}`);
    if (s.anchors !== undefined) {
      object(s.anchors, `${w}.anchors`);
      for (const [k, p] of Object.entries(s.anchors)) { name(k, `${w}.anchors key`); pixelPoint(p, `${w}.anchors.${k}`); }
    }
  });
  if (typeof prop.defaultState !== 'string' || !prop.states[prop.defaultState]) fail(`${where}.defaultState`, `must name one of its states (${Object.keys(prop.states).join(', ')})`);
  if (prop.affordances !== undefined) {
    if (!Array.isArray(prop.affordances)) fail(`${where}.affordances`, 'must be a list');
    if (new Set(prop.affordances).size !== prop.affordances.length) fail(`${where}.affordances`, 'has duplicates');
    for (const a of prop.affordances) {
      if (!AFFORDANCES[a]) fail(`${where}.affordances`, `unknown affordance "${a}" (known: ${Object.keys(AFFORDANCES).join(', ')})`);
      for (const [sid, s] of Object.entries(prop.states)) if (!s.anchors?.[AFFORDANCES[a]]) fail(`${where} state ${sid}`, `affordance "${a}" needs a "${AFFORDANCES[a]}" anchor`);
    }
  }
  if (prop.height !== undefined) finite(prop.height, `${where}.height`, {min: 0, exclusiveMin: true});
  if (prop.splits !== undefined) idMap(prop.splits, `${where} split`, (sid, sp, w) => {
    if (!prop.states[sid]) fail(w, `names unknown state "${sid}"`);
    object(sp, w); onlyKeys(sp, ['front', 'back'], w);
    if (!sp.front && !sp.back) fail(w, 'needs a "front" or "back" part');
    for (const k of ['front', 'back']) if (sp[k] !== undefined) asset(sp[k], `${w}.${k}`);
  });
  return prop;
}

// Load a prop by id (production/props/<id>.json) or from an explicit file. Synthetic props (labelled test fixtures)
// are refused unless allowSynthetic is passed; the production run never passes it.
export function loadProp(ref, {file = null, allowSynthetic = false} = {}) {
  const f = file ? path.resolve(REPO_ROOT, file) : propFile(ref);
  if (!fs.existsSync(f)) throw new Error(`prop "${ref}": no prop registry (${path.relative(REPO_ROOT, f)})`);
  const prop = validateProp(JSON.parse(fs.readFileSync(f, 'utf8')), `prop ${ref}`);
  if (prop.prop !== ref) throw new Error(`prop "${ref}": the registry is for "${prop.prop}"`);
  if (prop.synthetic === true && !allowSynthetic) throw new Error(`prop "${ref}" is a SYNTHETIC test fixture, not artwork. It is never used in production`);
  return prop;
}

// Asset checks that need the files: every state and split file exists and matches its SHA-256, and anchors lie inside
// the state's image. Read-only.
export async function verifyPropAssets(prop, repoRoot = REPO_ROOT) {
  const check = (a, w) => {
    const f = path.resolve(repoRoot, a.file);
    if (!fs.existsSync(f)) throw new Error(`${w}: missing file ${a.file}`);
    if (a.sha256 && sha(f) !== a.sha256) throw new Error(`${w}: file hash does not match the registry`);
    return f;
  };
  for (const [sid, s] of Object.entries(prop.states)) {
    const img = await canvas.loadImage(check(s, `prop ${prop.prop} state ${sid}`));
    for (const [k, a] of Object.entries(s.anchors || {})) if (a.x > img.width || a.y > img.height) throw new Error(`prop ${prop.prop} state ${sid}: anchor "${k}" (${a.x}, ${a.y}) is outside the ${img.width}×${img.height} image`);
  }
  for (const [sid, sp] of Object.entries(prop.splits || {})) for (const k of ['front', 'back']) if (sp[k]) check(sp[k], `prop ${prop.prop} split ${sid}.${k}`);
  return true;
}
