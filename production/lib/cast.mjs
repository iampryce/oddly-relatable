// Cast model (AP-79): a scene declares cast members; each member is an instance of a character identified by a
// stable ID (character-01, later character-02, ...) with its own placement, height, layer order and facing.
// Characters resolve to their own pose registries; stories never reference image paths directly.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {PRODUCTION_ROOT, REPO_ROOT} from './runtime.mjs';
import {loadRegistry, poseInfo, PLACEMENT_DEFAULTS} from './character.mjs';

const ID = /^[a-z0-9][a-z0-9-]{0,63}$/;
const FACINGS = ['native'];   // the B1 renderer cannot mirror images; mirrored facing needs separately approved artwork

// Registry file for a character ID: production/characters/<id>.json unless an explicit registry path is given.
export function registryPathFor(member, repoRoot = REPO_ROOT) {
  if (member.registry) return path.resolve(repoRoot, member.registry);
  return path.join(PRODUCTION_ROOT, 'characters', `${member.character}.json`);
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
    if (m.facing !== undefined && !FACINGS.includes(m.facing)) throw new Error(`${where} (${m.id}): facing "${m.facing}" is not supported by the B1 renderer (supported: ${FACINGS.join(', ')})`);
    if (m.z !== undefined && !Number.isFinite(m.z)) throw new Error(`${where} (${m.id}): z must be a number`);
  }
  return cast;
}

const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');

// Resolve every member: registry, placement, and info for each pose it uses (verifying file hashes when recorded).
export async function resolveCast(cast, posesByMember, repoRoot = REPO_ROOT) {
  validateCast(cast);
  const registries = new Map(), out = [];
  for (const m of cast) {
    const file = registryPathFor(m, repoRoot);
    if (!fs.existsSync(file)) throw new Error(`cast member "${m.id}": no registry for character "${m.character}" (${path.relative(repoRoot, file)})`);
    if (!registries.has(file)) registries.set(file, loadRegistry(file));
    const registry = registries.get(file);
    if (registry.character && registry.character !== m.character) throw new Error(`cast member "${m.id}": registry is for "${registry.character}", not "${m.character}"`);
    const infos = new Map();
    for (const seg of posesByMember[m.id] || []) {
      if (infos.has(seg.pose)) continue;
      const info = await poseInfo(registry, seg.pose, repoRoot);
      const expected = registry.poses[seg.pose].sha256;
      if (expected && sha(info.file) !== expected) throw new Error(`pose ${seg.pose} of ${m.character}: file hash does not match the registry`);
      infos.set(seg.pose, info);
    }
    out.push({...m, z: m.z ?? 0, placement: {...PLACEMENT_DEFAULTS, ...(m.placement || {})}, registry, registryFile: file, infos, segments: posesByMember[m.id] || []});
  }
  for (const id of Object.keys(posesByMember)) if (!cast.some(m => m.id === id)) throw new Error(`poses reference unknown cast member "${id}"`);
  return out.sort((a, b) => a.z - b.z);   // draw order: lower z first (further back)
}
