// Depth (AP-86 S2, approved 2026-11-16): explicit placement in set coordinates, depth-derived draw order, occluder
// interleaving and per-layer parallax. Pure functions; nothing here reads files or renders.
//
// Precedence (owner decisions, 2026-11-15):
//   O3  named marks and actions are the default placement (the staging resolver is AP-86 S3, not here); an explicit
//       placement always wins. S2 resolves explicit placements only: world units {feetX, feetY, figureHeight} as
//       before, or plate coordinates {plateX, plateY, plateHeight?} whose height defaults to the floor model.
//   O4  depth-derived layering is the default; an explicit z wins.
//
// The depth scale. A member's depth is how far down its feet stand: in a set scene, the plate fraction of the feet
// line (0 = top of the plate, far away; 1 = bottom, nearest); in a story@2 scene without a set, the feet line as a
// fraction of the frame height. An explicit z is a depth on that same scale, so it can be compared with other
// members and with occluder baselines. Lower depth is drawn first (further back).
// Ties are broken deterministically: an occluder is drawn before a member at exactly its baseline (the member is in
// front of it), and members at the same depth keep their order of declaration in the cast.
// story@1 is untouched: it keeps z (default 0) and declaration order, exactly as before.
import {fail, finite, fraction} from './schema.mjs';

export const PLATE_PLACEMENT_KEYS = Object.freeze(['plateX', 'plateY', 'plateHeight']);
const WORLD_PLACEMENT_KEYS = ['feetX', 'feetY', 'figureHeight'];
const SHARED_KEYS = ['maxUpscale', 'shadow'];

// Which kind of explicit placement a member has: 'world', 'plate' or null (none).
export function placementKind(placement, where = 'placement') {
  if (placement === undefined) return null;
  if (placement === null || typeof placement !== 'object' || Array.isArray(placement)) fail(where, 'must be an object');
  const keys = Object.keys(placement), plate = keys.filter(k => PLATE_PLACEMENT_KEYS.includes(k)), world = keys.filter(k => WORLD_PLACEMENT_KEYS.includes(k));
  for (const k of keys) if (![...PLATE_PLACEMENT_KEYS, ...WORLD_PLACEMENT_KEYS, ...SHARED_KEYS].includes(k)) fail(where, `unknown field "${k}"`);
  if (plate.length && world.length) fail(where, `mixes plate coordinates (${plate.join(', ')}) with world units (${world.join(', ')}); use one or the other`);
  if (plate.length) {
    if (placement.plateX === undefined || placement.plateY === undefined) fail(where, 'plate placement needs "plateX" and "plateY"');
    fraction(placement.plateX, `${where}.plateX`); fraction(placement.plateY, `${where}.plateY`);
    if (placement.plateHeight !== undefined) { fraction(placement.plateHeight, `${where}.plateHeight`); if (placement.plateHeight <= 0) fail(`${where}.plateHeight`, 'must be greater than 0'); }
    return 'plate';
  }
  return 'world';
}

// Explicit placement -> world placement {feetX, feetY, figureHeight, ...shared}. Plate placement needs the scene's
// resolved plate; its height comes from "plateHeight" when given (explicit wins), otherwise from the floor model.
export function worldPlacement(placement, stage, where) {
  const kind = placementKind(placement, where);
  if (kind !== 'plate') return placement;
  if (!stage) fail(where, 'plate coordinates need a scene "set"');
  const shared = Object.fromEntries(SHARED_KEYS.filter(k => placement[k] !== undefined).map(k => [k, placement[k]]));
  const feet = stage.toWorld({x: placement.plateX, y: placement.plateY});
  const figureHeight = placement.plateHeight !== undefined ? placement.plateHeight * stage.rect.h : stage.heightAt(placement.plateY, `${where} (floor model)`);
  return {...shared, feetX: feet.x, feetY: feet.y, figureHeight};
}

// Depth of a member placed in world units: plate fraction in a set scene, frame fraction otherwise.
export function depthOf(placementWorld, {stage = null, plane}) {
  return stage ? (placementWorld.feetY - stage.rect.y) / stage.rect.h : placementWorld.feetY / plane.height;
}

// Layering key of a member: explicit z (O4 override) or its depth.
export function layeringKey(member, placementWorld, ctx) {
  if (member.z !== undefined) return {mode: 'explicit-z', key: finite(member.z, `cast member "${member.id}" z`)};
  return {mode: 'depth', key: depthOf(placementWorld, ctx)};
}

// Back-to-front draw order of members and occluder layers (deterministic; see the header for ties).
// members: [{id, key, index}]; occluders: [{id, baselineY, index}] in declared order.
export function drawOrder(members, occluders = []) {
  const items = [
    ...occluders.map(o => ({kind: 'occluder', id: o.id, key: o.baselineY, rank: 0, index: o.index})),
    ...members.map(m => ({kind: 'member', id: m.id, key: m.key, rank: 1, index: m.index})),
  ];
  return items.sort((a, b) => a.key - b.key || a.rank - b.rank || a.index - b.index);
}

// Parallax (S2): a layer with factor p moves and zooms p times as much as the camera does (1 = with the characters,
// below 1 = further away, above 1 = nearer). Wide shots (zoom 1, no offset) are unaffected for every factor.
export function parallaxCamera(cam, p) {
  if (p === 1) return cam;
  return {...cam, z: 1 + (cam.z - 1) * p, ox: cam.ox * p, oy: cam.oy * p};
}
