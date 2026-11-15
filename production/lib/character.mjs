// Character reaction composition: place existing pose cut-outs beneath the conversation.
// Uses existing assets only (listed in a pose registry); this module never edits artwork, it only
// computes where and how large the renderer should draw each pose.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {canvas, REPO_ROOT} from './runtime.mjs';
import {object, onlyKeys, name, id, finite, pixelPoint, schemaVersion, fail} from './schema.mjs';

export const PLACEMENT_DEFAULTS = Object.freeze({feetX: 640, feetY: 2070, figureHeight: 880, maxUpscale: 1.7, shadow: true});
// Directions a pose's artwork can be declared as facing (AP-85 P1). Optional: undeclared poses can only be drawn "native".
export const POSE_FACINGS = Object.freeze(['left', 'right', 'front']);

// Registry versions (AP-86 S1). v1 is every existing registry (no "schemaVersion", or 1) and keeps its meaning exactly.
// v2 ("schemaVersion": 2) may add, all optional: per-pose "tags" and "anchors", and registry "proportions".
// v2 fields in a v1 registry are an error, so a registry never silently mixes versions.
export const REGISTRY_VERSIONS = Object.freeze([undefined, 1, 2]);

export function loadRegistry(file) {
  const reg = JSON.parse(fs.readFileSync(file, 'utf8'));
  return validateRegistry(reg, file);
}

export function validateRegistry(reg, file = 'registry') {
  schemaVersion(reg?.schemaVersion, REGISTRY_VERSIONS, `Pose registry ${file}`);
  if (!reg.poses || typeof reg.poses !== 'object') throw new Error(`Pose registry ${file}: "poses" is required`);
  const v2 = reg.schemaVersion === 2;
  if (reg.proportions !== undefined) {
    if (!v2) throw new Error(`Pose registry ${file}: "proportions" needs "schemaVersion": 2`);
    validateProportions(reg.proportions, `Pose registry ${file} proportions`);
  }
  for (const [id, p] of Object.entries(reg.poses)) {
    for (const k of ['tags', 'anchors']) if (p[k] !== undefined && !v2) throw new Error(`Pose ${id}: "${k}" needs "schemaVersion": 2`);
    if (p.tags !== undefined) validateTags(p.tags, `Pose ${id} tags`);
    if (p.anchors !== undefined) validateAnchors(p.anchors, p.feet, `Pose ${id} anchors`);
    if (typeof p.file !== 'string') throw new Error(`Pose ${id}: "file" is required`);
    if (!p.feet || !Number.isFinite(p.feet.x) || !Number.isFinite(p.feet.y)) throw new Error(`Pose ${id}: feet anchor {x,y} is required`);
    if (!Number.isFinite(p.figureHeight) || p.figureHeight <= 0) throw new Error(`Pose ${id}: figureHeight is required`);
    if (p.facing !== undefined && !POSE_FACINGS.includes(p.facing)) throw new Error(`Pose ${id}: facing must be one of ${POSE_FACINGS.join(', ')}`);
    if (p.facingVariants !== undefined) {
      if (!p.facingVariants || typeof p.facingVariants !== 'object') throw new Error(`Pose ${id}: facingVariants must be {facing: poseId}`);
      for (const [f, v] of Object.entries(p.facingVariants)) {
        if (!POSE_FACINGS.includes(f)) throw new Error(`Pose ${id}: facingVariants key "${f}" must be one of ${POSE_FACINGS.join(', ')}`);
        if (!reg.poses[v]) throw new Error(`Pose ${id}: facingVariants.${f} names unknown pose "${v}"`);
      }
    }
  }
  return reg;
}

// Pose tags (v2): what a pose means, so later phases can choose poses by meaning (stance, action, expression).
// The tag vocabulary is not fixed here (pose standards are owner decision O6): keys are names, values are one
// identifier or a list of distinct identifiers.
export function validateTags(tags, where) {
  object(tags, where, 'an object of tag lists');
  for (const [k, v] of Object.entries(tags)) {
    name(k, `${where} key`);
    const list = Array.isArray(v) ? v : [v];
    if (!list.length) fail(`${where}.${k}`, 'must not be empty');
    list.forEach((x, i) => id(x, `${where}.${k}[${i}]`));
    if (new Set(list).size !== list.length) fail(`${where}.${k}`, 'has duplicate values');
  }
  return tags;
}
// Anchors (v2): named contact points in the pose's image pixels (seat, hands, ...). "feet" stays the canonical
// "feet" field; an anchors.feet, if given, must match it exactly.
export function validateAnchors(anchors, feet, where) {
  object(anchors, where, 'an object of named points');
  for (const [k, p] of Object.entries(anchors)) {
    name(k, `${where} key`);
    pixelPoint(p, `${where}.${k}`);
  }
  if (anchors.feet && feet && (anchors.feet.x !== feet.x || anchors.feet.y !== feet.y)) fail(`${where}.feet`, `must equal the pose's "feet" anchor (${feet.x}, ${feet.y})`);
  return anchors;
}
function validateProportions(p, where) {
  object(p, where);
  onlyKeys(p, ['figureHeightRef', 'headFraction', 'note'], where);
  if (p.figureHeightRef !== undefined) finite(p.figureHeightRef, `${where}.figureHeightRef`, {min: 0, exclusiveMin: true});
  if (p.headFraction !== undefined) finite(p.headFraction, `${where}.headFraction`, {min: 0, max: 1, exclusiveMin: true});
  return p;
}

// Asset checks that need the files (AP-86 S1): every pose file exists, its SHA-256 matches when recorded, and every
// anchor (including "feet") lies inside the image. Read-only; never changes artwork.
export async function verifyRegistryAssets(registry, repoRoot = REPO_ROOT) {
  for (const [poseId, p] of Object.entries(registry.poses)) {
    const file = path.resolve(repoRoot, p.file);
    if (!fs.existsSync(file)) throw new Error(`Pose ${poseId}: missing file ${p.file}`);
    if (p.sha256 && crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex') !== p.sha256) throw new Error(`Pose ${poseId}: file hash does not match the registry`);
    const img = await canvas.loadImage(file);
    for (const [k, a] of Object.entries({feet: p.feet, ...(p.anchors || {})})) {
      if (a.x > img.width || a.y > img.height) throw new Error(`Pose ${poseId}: anchor "${k}" (${a.x}, ${a.y}) is outside the ${img.width}×${img.height} image`);
    }
  }
  return true;
}

// Resolve a pose and read its pixel size from the file itself.
export async function poseInfo(registry, id, repoRoot = REPO_ROOT) {
  const p = registry.poses[id];
  if (!p) throw new Error(`Unknown pose "${id}" (registry has: ${Object.keys(registry.poses).join(', ')})`);
  const file = path.resolve(repoRoot, p.file);
  if (!fs.existsSync(file)) throw new Error(`Pose ${id}: missing file ${p.file}`);
  const img = await canvas.loadImage(file);
  return {id, file, relFile: p.file, width: img.width, height: img.height, feet: p.feet, figureHeight: p.figureHeight, headFraction: p.headFraction ?? 0.42, status: p.status};
}

// Position a pose so its feet anchor lands on (feetX, feetY) and the figure is `figureHeight` units tall.
// ppu (output pixels per design unit) lets us report the real on-screen enlargement of the source pixels.
export function placePose(info, placement = {}, ppu = 1) {
  const pl = {...PLACEMENT_DEFAULTS, ...placement};
  const k = pl.figureHeight / info.figureHeight;           // design units per source pixel
  const x = pl.feetX - info.feet.x * k, y = pl.feetY - info.feet.y * k;
  const top = pl.feetY - info.figureHeight * k;            // top of the figure (head)
  const faceBox = {x, y: top, w: info.width * k, h: pl.figureHeight * info.headFraction};
  const upscale = k * ppu;                                 // output pixels per source pixel
  return {x: +x.toFixed(2), y: +y.toFixed(2), w: +(info.width * k).toFixed(2), scale: k, top, faceBox, upscale, soft: upscale > pl.maxUpscale};
}

// One image layer per pose segment (hard cuts on pose changes, matching the pose-swap style used so far).
export function reactionLayers(segments, infos, placement, assetPathFor, ppu = 1) {
  const layers = [], faceBoxes = [], diagnostics = [];
  for (const seg of segments) {
    const info = infos.get(seg.pose);
    const pl = placePose(info, placement, ppu);
    layers.push({type: 'image', path: assetPathFor(info), x: pl.x, y: pl.y, w: pl.w, from: +seg.start.toFixed(3), to: +seg.end.toFixed(3)});
    faceBoxes.push({...pl.faceBox, from: seg.start, to: seg.end, pose: seg.pose});
    diagnostics.push({pose: seg.pose, from: seg.start, to: seg.end, upscale: +pl.upscale.toFixed(2), soft: pl.soft, status: info.status});
  }
  return {layers, faceBoxes, diagnostics};
}
