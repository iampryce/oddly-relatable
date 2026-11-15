// Environment and set registries (AP-86 S1: data model and validation only).
//
// v1: production/environments/environments.json, {environments: {id: {file, sha256?, status?}}}. Every existing scene
//     uses it through story.resolveEnvironment, unchanged in meaning (a flat plate, cover-fitted to the frame).
// v2: production/environments/<set-id>.json, one SET per file ("schemaVersion": 2): plates (camera angles), each with
//     back-to-front layers, an optional floor model, named marks, surfaces and occluder metadata.
//
// O3 (approved 2026-11-15): named marks and actions in set coordinates are the default way to place people; explicit
// placement overrides. Marks and surfaces are defined here; using them (the staging resolver) is AP-86 S3.
// O4 (approved 2026-11-15): depth-derived layering is the default; explicit z overrides. Occluder baselines are
// recorded here; computing depth and composing occlusion is AP-86 S2.
// NOT DECIDED (O5): superframe size, layer split and other set standards. They are optional and unconstrained here
// beyond structural sanity; nothing in this file renders a set.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {PRODUCTION_ROOT, REPO_ROOT} from './runtime.mjs';
import {POSE_FACINGS} from './character.mjs';
import {object, onlyKeys, id, finite, fraction, point01, asset, idMap, schemaVersion, fail, SHA256} from './schema.mjs';

export const ENVIRONMENTS_FILE = path.join(PRODUCTION_ROOT, 'environments', 'environments.json');
export const SET_SCHEMA_VERSION = 2;
// Kinds of mark. Each kind is something an action can require (stand at, sit on, enter from).
export const MARK_KINDS = Object.freeze(['stand', 'seat', 'entry']);
const RESERVED_SET_IDS = ['environments'];
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');

// ------------------------------------------------------------------------------------------------ v1 registry
export function validateEnvironmentRegistry(reg, where = 'environment registry') {
  object(reg, where);
  schemaVersion(reg.schemaVersion, [undefined, 1], where);
  idMap(object(reg.environments, `${where}.environments`), `${where}.environments`, (k, e, w) => {
    object(e, w);
    if (typeof e.file !== 'string' || !e.file) fail(`${w}.file`, 'is required');
    if (e.sha256 !== undefined && !SHA256.test(e.sha256)) fail(`${w}.sha256`, 'must be 64 lowercase hex characters');
  });
  return reg;
}
export function loadEnvironmentRegistry(file = ENVIRONMENTS_FILE) {
  return validateEnvironmentRegistry(JSON.parse(fs.readFileSync(file, 'utf8')), `environment registry ${path.basename(file)}`);
}

// ------------------------------------------------------------------------------------------------ v2 sets
export function setFile(setId) {
  id(setId, 'set id');
  if (RESERVED_SET_IDS.includes(setId)) fail('set id', `"${setId}" is reserved`);
  return path.join(PRODUCTION_ROOT, 'environments', `${setId}.json`);
}

export function validateSet(set, where = `set ${set?.set ?? '?'}`) {
  object(set, where);
  onlyKeys(set, ['set', 'schemaVersion', 'displayName', 'kind', 'synthetic', 'note', 'plates', 'variants'], where);
  id(set.set, `${where} "set"`);
  schemaVersion(set.schemaVersion, [SET_SCHEMA_VERSION], where);
  if (set.kind !== undefined && (typeof set.kind !== 'string' || !/^[a-z0-9-]+(\/[a-z0-9-]+)*$/.test(set.kind))) fail(`${where}.kind`, 'must be like "interior/bar"');
  if (set.synthetic !== undefined && typeof set.synthetic !== 'boolean') fail(`${where}.synthetic`, 'must be true or false');
  if (!Object.keys(object(set.plates, `${where}.plates`)).length) fail(`${where}.plates`, 'at least one plate is required');
  idMap(set.plates, `${where} plate`, (pid, plate, w) => validatePlate(plate, `${where} plate ${pid}`));
  if (set.variants !== undefined) idMap(set.variants, `${where} variant`, (vid, v, w) => {
    object(v, w); onlyKeys(v, ['overlay', 'note'], w);
    if (v.overlay !== undefined) asset(v.overlay, `${w}.overlay`);
  });
  return set;
}

function validatePlate(plate, where) {
  object(plate, where);
  onlyKeys(plate, ['superframe', 'layers', 'floor', 'marks', 'surfaces', 'actionSafe', 'lighting', 'note'], where);
  if (plate.superframe !== undefined) {
    object(plate.superframe, `${where}.superframe`); onlyKeys(plate.superframe, ['width', 'height'], `${where}.superframe`);
    for (const k of ['width', 'height']) if (!Number.isInteger(plate.superframe[k]) || plate.superframe[k] <= 0) fail(`${where}.superframe.${k}`, 'must be a positive integer (pixels)');
  }
  // Layers, back to front. At least one; ids unique.
  if (!Array.isArray(plate.layers) || !plate.layers.length) fail(`${where}.layers`, 'at least one layer (back to front) is required');
  const layerIds = new Set();
  plate.layers.forEach((l, i) => {
    const w = `${where} layer ${l?.id ?? i + 1}`;
    object(l, w); onlyKeys(l, ['id', 'file', 'sha256', 'parallax', 'occluder', 'note'], w);
    id(l.id, `${w} id`);
    if (layerIds.has(l.id)) fail(w, 'duplicate layer id');
    layerIds.add(l.id);
    asset({file: l.file, ...(l.sha256 !== undefined ? {sha256: l.sha256} : {})}, w);
    if (l.parallax !== undefined) finite(l.parallax, `${w}.parallax`, {min: 0, exclusiveMin: true});
    // Occluder metadata: the floor line (plate fraction) behind which a member is drawn under this layer (used in S2).
    if (l.occluder !== undefined) { object(l.occluder, `${w}.occluder`); onlyKeys(l.occluder, ['baselineY'], `${w}.occluder`); fraction(l.occluder.baselineY, `${w}.occluder.baselineY`); }
  });
  // Floor model (optional): horizon, and the size of a reference figure at a reference floor line (plate fractions).
  if (plate.floor !== undefined) {
    const w = `${where}.floor`;
    object(plate.floor, w); onlyKeys(plate.floor, ['horizonY', 'refFeetY', 'refFigureHeight'], w);
    for (const k of ['horizonY', 'refFeetY', 'refFigureHeight']) fraction(plate.floor[k], `${w}.${k}`);
    if (plate.floor.refFeetY <= plate.floor.horizonY) fail(w, 'refFeetY must be below the horizon (greater than horizonY)');
    if (plate.floor.refFigureHeight <= 0) fail(`${w}.refFigureHeight`, 'must be greater than 0');
  }
  // Marks and surfaces share one namespace per plate, so a reference can never be ambiguous.
  const names = new Set();
  const claim = (k, w) => { if (names.has(k)) fail(w, `"${k}" is already used by another mark or surface in this plate`); names.add(k); };
  if (plate.marks !== undefined) idMap(plate.marks, `${where} mark`, (mid, m, w) => {
    claim(mid, w);
    object(m, w); onlyKeys(m, ['kind', 'point', 'floor', 'faces', 'note'], w);
    if (!MARK_KINDS.includes(m.kind)) fail(`${w}.kind`, `must be one of ${MARK_KINDS.join(', ')} (got ${JSON.stringify(m.kind)})`);
    point01(m.point, `${w}.point`);
    if (m.floor !== undefined) point01(m.floor, `${w}.floor`);
    if (m.faces !== undefined && !POSE_FACINGS.includes(m.faces)) fail(`${w}.faces`, `must be one of ${POSE_FACINGS.join(', ')}`);
  });
  if (plate.surfaces !== undefined) idMap(plate.surfaces, `${where} surface`, (sid, s, w) => {
    claim(sid, w);
    object(s, w); onlyKeys(s, ['kind', 'line', 'floorY', 'note'], w);
    if (s.kind !== undefined && s.kind !== 'surface') fail(`${w}.kind`, 'must be "surface" when given');
    object(s.line, `${w}.line`, 'a line {x0, x1, y} in plate fractions'); onlyKeys(s.line, ['x0', 'x1', 'y'], `${w}.line`);
    for (const k of ['x0', 'x1', 'y']) fraction(s.line[k], `${w}.line.${k}`);
    if (s.line.x1 <= s.line.x0) fail(`${w}.line`, 'x1 must be greater than x0');
    if (s.floorY !== undefined) fraction(s.floorY, `${w}.floorY`);
  });
  if (plate.actionSafe !== undefined) {
    const a = plate.actionSafe, w = `${where}.actionSafe`;
    object(a, w); onlyKeys(a, ['x', 'y', 'w', 'h'], w);
    for (const k of ['x', 'y', 'w', 'h']) fraction(a[k], `${w}.${k}`);
    if (a.w <= 0 || a.h <= 0 || a.x + a.w > 1 + 1e-9 || a.y + a.h > 1 + 1e-9) fail(w, 'must be a non-empty rectangle inside the plate');
  }
  if (plate.lighting !== undefined) {
    object(plate.lighting, `${where}.lighting`);
    for (const [k, v] of Object.entries(plate.lighting)) if (typeof v !== 'string') fail(`${where}.lighting.${k}`, 'must be text');
  }
  return plate;
}

// Load a set by id (production/environments/<id>.json) or from an explicit file (tests, fixtures).
// A set marked "synthetic" (a labelled test fixture) is refused unless allowSynthetic is passed, as for characters.
export function loadSet(ref, {file = null, allowSynthetic = false} = {}) {
  const f = file ? path.resolve(REPO_ROOT, file) : setFile(ref);
  if (!fs.existsSync(f)) throw new Error(`set "${ref}": no set registry (${path.relative(REPO_ROOT, f)})`);
  const set = validateSet(JSON.parse(fs.readFileSync(f, 'utf8')), `set ${ref}`);
  if (set.set !== ref) throw new Error(`set "${ref}": the registry is for "${set.set}"`);
  if (set.synthetic === true && !allowSynthetic) throw new Error(`set "${ref}" is a SYNTHETIC test fixture, not artwork. It is never used in production`);
  return set;
}

export function plateOf(set, plateId, where = `set ${set.set}`) {
  const plate = set.plates[plateId];
  if (!plate) throw new Error(`${where}: no plate "${plateId}" (plates: ${Object.keys(set.plates).join(', ')})`);
  return plate;
}

// Asset checks that need the files: every layer and overlay exists and matches its recorded SHA-256. Read-only.
export function verifySetAssets(set, repoRoot = REPO_ROOT) {
  const check = (a, w) => {
    const f = path.resolve(repoRoot, a.file);
    if (!fs.existsSync(f)) throw new Error(`${w}: missing file ${a.file}`);
    if (a.sha256 && sha(f) !== a.sha256) throw new Error(`${w}: file hash does not match the registry`);
  };
  for (const [pid, plate] of Object.entries(set.plates)) for (const l of plate.layers) check(l, `set ${set.set} plate ${pid} layer ${l.id}`);
  for (const [vid, v] of Object.entries(set.variants || {})) if (v.overlay) check(v.overlay, `set ${set.set} variant ${vid}`);
  return true;
}
