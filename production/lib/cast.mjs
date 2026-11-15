// Cast model (AP-79, AP-85 P1): a scene declares cast members; each member is an instance of a character identified by
// a stable ID (character-01, later character-02, ...) with its own placement, height, layer order, facing and speech.
// Characters resolve to their own pose registries; stories never reference image paths directly.
//
// AP-85 P1 rules (no silent defaults):
//   - Every registry names its character ("character"), and it must be the character the cast member asks for.
//   - Facing is data. "native" (the default) uses each pose as drawn. Any other facing must resolve, for every pose the
//     member uses, to artwork declared as facing that way in the registry (the pose itself or a declared variant).
//     Artwork is never mirrored: the renderer cannot mirror, and mirroring an asymmetric design changes the character.
//   - A registry marked "synthetic" (a labelled test placeholder) is refused unless the caller passes allowSynthetic,
//     which only tests do. Production runs never pass it, so a placeholder can never reach a produced episode.
//   - A member that speaks carries its own speech configuration ({style, side?}); styling never comes from the side.
//     The face-to-face format places each bubble where its speaker stands; a declared side is checked against that.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {PRODUCTION_ROOT, REPO_ROOT} from './runtime.mjs';
import {loadRegistry, poseInfo, PLACEMENT_DEFAULTS, POSE_FACINGS} from './character.mjs';
import {BUBBLE_STYLES} from './palette.mjs';

const ID = /^[a-z0-9][a-z0-9-]{0,63}$/;
export const FACINGS = Object.freeze(['native', ...POSE_FACINGS]);

// Registry file for a character ID: production/characters/<id>.json unless an explicit registry path is given.
export function registryPathFor(member, repoRoot = REPO_ROOT) {
  if (member.registry) return path.resolve(repoRoot, member.registry);
  return path.join(PRODUCTION_ROOT, 'characters', `${member.character}.json`);
}

// A bubble style is a named style or an explicit {fill, text, outline} object.
export function validateBubbleStyle(style, where) {
  if (typeof style === 'string') { if (!BUBBLE_STYLES[style]) throw new Error(`${where}: unknown bubble style "${style}" (known: ${Object.keys(BUBBLE_STYLES).join(', ')})`); return style; }
  if (style && typeof style === 'object' && ['fill', 'text', 'outline'].every(k => typeof style[k] === 'string')) return style;
  throw new Error(`${where}: bubble style must be a known style name or {fill, text, outline}`);
}

export function validateCast(cast) {
  if (!Array.isArray(cast)) throw new Error('cast must be an array');
  const seen = new Set();
  for (const [i, m] of cast.entries()) {
    const where = `cast[${i}]`;
    if (!m || !ID.test(m.id || '')) throw new Error(`${where}: id must be a lowercase identifier`);
    if (seen.has(m.id)) throw new Error(`${where}: duplicate cast id "${m.id}"`);
    seen.add(m.id);
    if (!ID.test(m.character || '')) throw new Error(`${where} (${m.id}): character ID is required (e.g. "character-01")`);
    if (m.mirror !== undefined) throw new Error(`${where} (${m.id}): "mirror" is not supported. Artwork is never mirrored; request a facing that the registry has artwork for`);
    if (m.facing !== undefined && !FACINGS.includes(m.facing)) throw new Error(`${where} (${m.id}): facing "${m.facing}" is not one of ${FACINGS.join(', ')}`);
    if (m.z !== undefined && !Number.isFinite(m.z)) throw new Error(`${where} (${m.id}): z must be a number`);
    if (m.speech !== undefined) {
      if (!m.speech || typeof m.speech !== 'object') throw new Error(`${where} (${m.id}): speech must be {style, side?}`);
      validateBubbleStyle(m.speech.style, `${where} (${m.id}) speech`);
      if (m.speech.side !== undefined && !['left', 'right'].includes(m.speech.side)) throw new Error(`${where} (${m.id}) speech: side must be "left" or "right"`);
    }
  }
  return cast;
}

// The pose ID to draw for a requested facing. "native" keeps the pose as drawn. Anything else needs artwork declared
// as facing that way: the pose itself, or the variant it names in facingVariants. Otherwise this is an error.
export function resolvePoseForFacing(registry, poseId, facing, character) {
  const p = registry.poses[poseId];
  if (!p) throw new Error(`Unknown pose "${poseId}" of ${character} (registry has: ${Object.keys(registry.poses).join(', ')})`);
  if (facing === 'native' || p.facing === facing) return poseId;
  const v = p.facingVariants?.[facing];
  if (v !== undefined) {
    if (registry.poses[v]?.facing !== facing) throw new Error(`pose "${poseId}" of ${character}: its "${facing}" variant "${v}" is missing or not declared as facing "${facing}"`);
    return v;
  }
  throw new Error(`pose "${poseId}" of ${character} has no artwork facing "${facing}"${p.facing ? ` (it faces "${p.facing}")` : ' (its facing is not declared)'}. `
    + `Artwork is never mirrored: add a pose drawn facing "${facing}" to the registry`);
}

const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');

// Resolve every member: registry, facing, placement, and info for each pose it uses (verifying file hashes when recorded).
export async function resolveCast(cast, posesByMember, repoRoot = REPO_ROOT, {allowSynthetic = false} = {}) {
  validateCast(cast);
  const registries = new Map(), out = [];
  for (const m of cast) {
    const file = registryPathFor(m, repoRoot), rel = path.relative(repoRoot, file);
    if (!fs.existsSync(file)) throw new Error(`cast member "${m.id}": no registry for character "${m.character}" (${rel})`);
    if (!registries.has(file)) registries.set(file, loadRegistry(file));
    const registry = registries.get(file);
    if (!registry.character) throw new Error(`cast member "${m.id}": registry ${rel} does not name its character ("character" is required)`);
    if (registry.character !== m.character) throw new Error(`cast member "${m.id}": registry is for "${registry.character}", not "${m.character}"`);
    if (registry.synthetic === true && !allowSynthetic) {
      throw new Error(`cast member "${m.id}": registry for "${m.character}" is a SYNTHETIC test placeholder, not artwork. It is never used in production`);
    }
    const facing = m.facing ?? 'native';
    const segments = (posesByMember[m.id] || []).map(seg => ({...seg, requestedPose: seg.pose, pose: resolvePoseForFacing(registry, seg.pose, facing, m.character)}));
    const infos = new Map();
    for (const seg of segments) {
      if (infos.has(seg.pose)) continue;
      const info = await poseInfo(registry, seg.pose, repoRoot);
      const expected = registry.poses[seg.pose].sha256;
      if (expected && sha(info.file) !== expected) throw new Error(`pose ${seg.pose} of ${m.character}: file hash does not match the registry`);
      infos.set(seg.pose, info);
    }
    out.push({...m, z: m.z ?? 0, facing, synthetic: registry.synthetic === true, placement: {...PLACEMENT_DEFAULTS, ...(m.placement || {})}, registry, registryFile: file, infos, segments});
  }
  for (const id of Object.keys(posesByMember)) if (!cast.some(m => m.id === id)) throw new Error(`poses reference unknown cast member "${id}"`);
  return out.sort((a, b) => a.z - b.z);   // draw order: lower z first (further back)
}
