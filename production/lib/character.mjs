// Character reaction composition: place existing pose cut-outs beneath the conversation.
// Uses existing assets only (listed in a pose registry); this module never edits artwork, it only
// computes where and how large the renderer should draw each pose.
import fs from 'node:fs';
import path from 'node:path';
import {canvas, REPO_ROOT} from './runtime.mjs';

export const PLACEMENT_DEFAULTS = Object.freeze({feetX: 640, feetY: 2070, figureHeight: 880, maxUpscale: 1.7, shadow: true});

export function loadRegistry(file) {
  const reg = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (!reg.poses || typeof reg.poses !== 'object') throw new Error(`Pose registry ${file}: "poses" is required`);
  for (const [id, p] of Object.entries(reg.poses)) {
    if (typeof p.file !== 'string') throw new Error(`Pose ${id}: "file" is required`);
    if (!p.feet || !Number.isFinite(p.feet.x) || !Number.isFinite(p.feet.y)) throw new Error(`Pose ${id}: feet anchor {x,y} is required`);
    if (!Number.isFinite(p.figureHeight) || p.figureHeight <= 0) throw new Error(`Pose ${id}: figureHeight is required`);
  }
  return reg;
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
