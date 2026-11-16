// Environment and set registries (AP-86 S1 data model; AP-86 S2 plate-to-world mapping, floor model and layers).
//
// v1: production/environments/environments.json, {environments: {id: {file, sha256?, status?}}}. Every existing scene
//     uses it through story.resolveEnvironment, unchanged in meaning (a flat plate, cover-fitted to the frame).
// v2: production/environments/<set-id>.json, one SET per file ("schemaVersion": 2): plates (camera angles), each with
//     back-to-front layers, an optional floor model, named marks, surfaces and occluder metadata.
//
// O3 (approved 2026-11-15): named marks and actions in set coordinates are the default way to place people; explicit
// placement overrides. Marks and surfaces are defined here; using them (the staging resolver) is AP-86 S3.
// O4 (approved 2026-11-15): depth-derived layering is the default; explicit z overrides. Depth ordering and occluder
// interleaving are in depth.mjs (S2).
// NOT DECIDED (O5): superframe size, layer split and other set standards. They are optional and unconstrained here
// beyond structural sanity.
//
// S2 (approved 2026-11-16) adds resolvePlate(): the plate is cover-fitted to the design plane (centred, like a v1
// environment), so plate fractions (0–1) map to world units; the floor model gives a figure height for any floor line;
// layers are placed back to front (full plate, or a cut-out "rect" in plate fractions). Framing windows on the plate
// (superframe profiles) are AP-86 S4; nothing here changes the camera.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {canvas, PRODUCTION_ROOT, REPO_ROOT} from './runtime.mjs';
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
  onlyKeys(set, ['set', 'schemaVersion', 'displayName', 'kind', 'synthetic', 'note', 'assetRoot', 'plates', 'variants'], where);
  // Where layer files are resolved from: the repository (default, like every other registry) or the registry's own
  // folder (self-contained fixtures).
  if (set.assetRoot !== undefined && !['repository', 'registry'].includes(set.assetRoot)) fail(`${where}.assetRoot`, 'must be "repository" or "registry"');
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
    object(l, w); onlyKeys(l, ['id', 'file', 'sha256', 'rect', 'parallax', 'occluder', 'note'], w);
    id(l.id, `${w} id`);
    if (layerIds.has(l.id)) fail(w, 'duplicate layer id');
    layerIds.add(l.id);
    asset({file: l.file, ...(l.sha256 !== undefined ? {sha256: l.sha256} : {})}, w);
    if (l.parallax !== undefined) finite(l.parallax, `${w}.parallax`, {min: 0, exclusiveMin: true});
    // Occluder metadata: the floor line (plate fraction) behind which a member is drawn under this layer (used in S2).
    if (l.occluder !== undefined) { object(l.occluder, `${w}.occluder`); onlyKeys(l.occluder, ['baselineY'], `${w}.occluder`); fraction(l.occluder.baselineY, `${w}.occluder.baselineY`); }
    // A cut-out layer (S2): its top-left corner and width in plate fractions; its height follows the image's aspect.
    if (l.rect !== undefined) {
      object(l.rect, `${w}.rect`, 'a rectangle {x, y, w} in plate fractions'); onlyKeys(l.rect, ['x', 'y', 'w'], `${w}.rect`);
      for (const k of ['x', 'y', 'w']) fraction(l.rect[k], `${w}.rect.${k}`);
      if (l.rect.w <= 0) fail(`${w}.rect.w`, 'must be greater than 0');
    }
  });
  // Order rules (S2): the first layer is the full-plate backdrop; backdrop layers (no occluder) come before occluder
  // layers; occluder baselines never move back up the plate. So the declared order is always a true back-to-front order.
  const first = plate.layers[0];
  if (first.occluder !== undefined || first.rect !== undefined) fail(`${where} layer ${first.id}`, 'the first layer is the backdrop: it covers the whole plate (no "rect") and is not an occluder');
  let lastBaseline = -1, seenOccluder = null;
  for (const l of plate.layers) {
    if (l.occluder === undefined) { if (seenOccluder) fail(`${where} layer ${l.id}`, `a backdrop layer cannot come after the occluder layer "${seenOccluder}" (layers are back to front)`); continue; }
    if (l.occluder.baselineY < lastBaseline) fail(`${where} layer ${l.id}`, `occluder baseline ${l.occluder.baselineY} is behind the previous occluder's ${lastBaseline} (layers are back to front)`);
    lastBaseline = l.occluder.baselineY; seenOccluder = l.id;
  }
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

// ------------------------------------------------------------------------------------------------ S2: plate -> world
// The world rectangle a plate of size (width × height) occupies when cover-fitted to the design plane, centred.
export function plateWorldRect(size, plane) {
  const s = Math.max(plane.width / size.width, plane.height / size.height), w = size.width * s, h = size.height * s;
  return {x: (plane.width - w) / 2, y: (plane.height - h) / 2, w, h};
}
export const plateToWorld = (R, p) => ({x: R.x + p.x * R.w, y: R.y + p.y * R.h});
export const worldToPlate = (R, p) => ({x: (p.x - R.x) / R.w, y: (p.y - R.y) / R.h});
// Floor model: a standing figure's height (as a fraction of the plate height) is proportional to how far its feet are
// below the horizon, calibrated by the reference figure. Feet on or above the horizon have no valid height.
export function floorHeightAt(floor, feetY, where = 'floor model') {
  if (!floor) fail(where, 'the plate has no floor model; give an explicit height');
  if (!(feetY > floor.horizonY + 1e-9)) fail(where, `feet at plate y ${feetY} are on or above the horizon (${floor.horizonY}); no figure can stand there`);
  return floor.refFigureHeight * (feetY - floor.horizonY) / (floor.refFeetY - floor.horizonY);
}

// Resolve one plate for compiling (S2): verify its files, read the image sizes, and place everything in world units.
// root: the folder layer files are relative to (assetRoot "registry": the registry's folder; otherwise the repository).
export async function resolvePlate(set, plateId, {plane, registryFile = null, repoRoot = REPO_ROOT} = {}) {
  const plate = plateOf(set, plateId);
  const root = set.assetRoot === 'registry' ? path.dirname(path.resolve(repoRoot, registryFile ?? setFile(set.set))) : repoRoot;
  verifySetAssets({...set, plates: {[plateId]: plate}, variants: {}}, root);
  const imgs = await Promise.all(plate.layers.map(l => canvas.loadImage(path.resolve(root, l.file))));
  const size = plate.superframe ?? {width: imgs[0].width, height: imgs[0].height};
  const aspect = size.width / size.height, where = `set ${set.set} plate ${plateId}`;
  const R = plateWorldRect(size, plane);
  const layers = plate.layers.map((l, i) => {
    const ia = imgs[i].width / imgs[i].height;
    const r = l.rect ?? {x: 0, y: 0, w: 1};
    // A full-plate layer must have the plate's shape, or it would be stretched or misaligned.
    if (!l.rect && Math.abs(ia - aspect) > aspect * 0.005) fail(`${where} layer ${l.id}`, `its image is ${imgs[i].width}×${imgs[i].height}, which does not match the plate's ${size.width}×${size.height} shape; give it a "rect" or a matching image`);
    const w = r.w * R.w, h = w / ia, x = R.x + r.x * R.w, y = R.y + r.y * R.h;
    if (r.x + r.w > 1 + 1e-9 || (y + h) > R.y + R.h + 1e-6) fail(`${where} layer ${l.id}`, 'its rectangle extends outside the plate');
    return {id: l.id, file: path.resolve(root, l.file), rect: {x, y, w, h}, parallax: l.parallax ?? 1, occluder: l.occluder ? {baselineY: l.occluder.baselineY} : null};
  });
  const marks = Object.fromEntries(Object.entries(plate.marks || {}).map(([k, m]) => [k, {kind: m.kind, point: plateToWorld(R, m.point), ...(m.floor ? {floor: plateToWorld(R, m.floor)} : {})}]));
  const surfaces = Object.fromEntries(Object.entries(plate.surfaces || {}).map(([k, sf]) => [k, {x0: R.x + sf.line.x0 * R.w, x1: R.x + sf.line.x1 * R.w, y: R.y + sf.line.y * R.h}]));
  return {set: set.set, plate: plateId, plateData: plate, size, rect: R, floor: plate.floor ?? null, layers, marks, surfaces,
    toWorld: p => plateToWorld(R, p), toPlate: p => worldToPlate(R, p),
    heightAt: (feetY, w) => floorHeightAt(plate.floor, feetY, w) * R.h};
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
