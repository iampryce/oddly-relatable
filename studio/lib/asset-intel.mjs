// Story asset intelligence, reference packs and candidate validation (AP-84B2). Read-only towards the repository:
// registries, stories and artwork are only read and hashed, never written.
//
//  requirementsFor(storyFile)  which characters / poses / environments a story needs, and whether each is
//                              available | missing | unapproved | unresolved (with the reason)
//  buildReferencePack(...)     immutable snapshot of reference files (source, SHA-256, dimensions, approval, version)
//  verifyPack(pack)            re-hash every item now: detects missing files and hash mismatches
//  validateCandidate(...)      measurable checks on a quarantined candidate (never approves anything)
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {canvas, REPO_ROOT, PRODUCTION_ROOT} from '../../production/lib/runtime.mjs';
import {validateStory} from '../../production/lib/story.mjs';
import {formatFor} from '../../production/lib/formats/index.mjs';
import {storyPath} from './stories.mjs';

const CANON_FILE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'config', 'canonical-references.json');
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const repoFile = rel => {
  // Only files inside the repository may be referenced; never absolute or escaping paths.
  if (typeof rel !== 'string' || path.isAbsolute(rel) || rel.includes('\0')) return null;
  const abs = path.resolve(REPO_ROOT, rel), r = path.relative(REPO_ROOT, abs);
  return r.startsWith('..') || path.isAbsolute(r) ? null : abs;
};
const readJson = f => JSON.parse(fs.readFileSync(f, 'utf8'));
const APPROVED_POSE = new Set(['APPROVED_WORKING_ASSET', 'APPROVED_WORKING_TEST_ASSET', 'APPROVED_EXTRACT']);
const approvedEnv = status => /^(APPROVED|ALTERNATIVE)\b/.test(status || '');
// Registry locations. Overridable only by tests (temporary registries inside the git-ignored studio-work/).
const DEFAULT_SOURCES = Object.freeze({charactersDir: path.join(PRODUCTION_ROOT, 'characters'),
  environmentsFile: path.join(PRODUCTION_ROOT, 'environments', 'environments.json'), canonFile: CANON_FILE});
const characterRegistry = (src, id) => path.join(src.charactersDir, `${id}.json`);

// Check one registered file: present, hash matches. Returns {state, reason, sha256, ...}.
function fileState(rel, expected) {
  const abs = repoFile(rel);
  if (!abs) return {state: 'unresolved', reason: 'path is outside the repository'};
  if (!fs.existsSync(abs)) return {state: 'missing', reason: 'file not found'};
  const actual = sha(abs);
  if (expected && actual !== expected) return {state: 'unresolved', reason: 'file hash does not match the registry', sha256: actual};
  return {state: 'ok', sha256: actual};
}

// ---------- 1. story asset requirements
const emptySummary = () => ({available: 0, missing: 0, unapproved: 0, unresolved: 0});
export function requirementsFor(storyFile, sources) {
  const p = storyPath(storyFile);                      // 400/404 for names outside production/stories/
  let story;
  try { story = readJson(p); }
  catch (e) { return {storyFile, valid: false, error: `story is not valid JSON: ${e.message}`, characters: [], environments: [], summary: emptySummary()}; }
  return analyseStory(story, {storyFile, sources});
}

// Analysis of a parsed story object against the registries (read-only). Each requirement is
// available | missing | unapproved | unresolved, with a reason when it is not simply available.
export function analyseStory(story, {storyFile = null, sources} = {}) {
  const src = {...DEFAULT_SOURCES, ...sources};
  const out = {storyFile, valid: true, error: null, characters: [], environments: [], summary: emptySummary()};
  try { validateStory(story); }
  catch (e) { return {...out, valid: false, error: e.message}; }
  out.storyId = story.id; out.title = story.title || story.id;
  const add = item => { out.summary[item.status]++; return item; };
  const charUse = new Map(), envUse = new Map();
  for (const scene of story.scenes) {
    // Environment requirement
    const envId = typeof scene.environment === 'string' ? scene.environment : scene.environment?.id ?? null;
    const envKey = envId ?? (scene.environment?.file ? `file:${scene.environment.file}` : null);
    if (envKey) { if (!envUse.has(envKey)) envUse.set(envKey, {id: envId, legacyFile: envId ? null : scene.environment.file, scenes: []}); envUse.get(envKey).scenes.push(scene.id); }
    // Pose requirements per cast member, from the scene's own timeline (format strategy, read-only)
    let castPoses = {}, seqError = null;
    try { const f = formatFor(scene.format); if (!f.implemented) throw new Error(`format "${scene.format}" is not implemented`); castPoses = f.sequence(scene).castPoses || {}; }
    catch (e) { seqError = e.message; }
    for (const m of scene.cast || []) {
      const key = m.character;
      if (!charUse.has(key)) charUse.set(key, {character: key, registry: m.registry || null, castIds: new Set(), poses: new Map(), errors: []});
      const c = charUse.get(key); c.castIds.add(m.id);
      if (seqError) c.errors.push(`scene ${scene.id}: ${seqError}`);
      for (const seg of castPoses[m.id] || []) {
        if (!c.poses.has(seg.pose)) c.poses.set(seg.pose, {pose: seg.pose, scenes: new Set(), uses: 0});
        const p = c.poses.get(seg.pose); p.scenes.add(scene.id); p.uses++;
      }
    }
  }
  for (const c of charUse.values()) {
    const regRel = c.registry || path.relative(REPO_ROOT, characterRegistry(src, c.character)).split(path.sep).join('/');
    const regAbs = repoFile(regRel);
    let registry = null;
    try { if (regAbs) registry = readJson(regAbs); } catch {}
    const entry = {character: c.character, registry: regRel, castIds: [...c.castIds], errors: c.errors, registryFound: !!registry, poses: []};
    // A scene whose timeline cannot be built leaves its pose needs unknown: report that as unresolved.
    for (const err of c.errors) entry.poses.push(add({pose: null, scenes: [], uses: 0, status: 'unresolved', reason: err}));
    for (const p of c.poses.values()) {
      const base = {pose: p.pose, scenes: [...p.scenes], uses: p.uses};
      if (!registry) { entry.poses.push(add({...base, status: 'unresolved', reason: `no registry for character "${c.character}"`})); continue; }
      const r = registry.poses?.[p.pose];
      if (!r) { entry.poses.push(add({...base, status: 'missing', reason: 'pose is not in the registry'})); continue; }
      const fstate = fileState(r.file, r.sha256);
      const info = {...base, file: r.file, sha256: r.sha256 || fstate.sha256 || null, approval: r.approval || null, version: Number(r.version) || 1, figureHeight: r.figureHeight};
      if (fstate.state !== 'ok') entry.poses.push(add({...info, status: fstate.state, reason: fstate.reason}));
      else if (!APPROVED_POSE.has(r.approval)) entry.poses.push(add({...info, status: 'unapproved', reason: `approval "${r.approval || 'none'}" is not an approved class`}));
      else entry.poses.push(add({...info, status: 'available', reason: r.approval === 'APPROVED_EXTRACT' ? 'approved extract (uncorrected, low resolution)' : null}));
    }
    out.characters.push(entry);
  }
  let envReg = {environments: {}};
  try { envReg = readJson(src.environmentsFile); } catch {}
  for (const e of envUse.values()) {
    const base = {id: e.id, legacyFile: e.legacyFile, scenes: e.scenes};
    if (!e.id) { out.environments.push(add({...base, status: 'unresolved', reason: 'scene uses a direct file path instead of an environment ID'})); continue; }
    const r = envReg.environments?.[e.id];
    if (!r) { out.environments.push(add({...base, status: 'missing', reason: 'environment is not in the registry'})); continue; }
    const fstate = fileState(r.file, r.sha256);
    const info = {...base, file: r.file, sha256: r.sha256 || fstate.sha256 || null, approval: r.status || null, version: Number(r.version) || 1};
    if (fstate.state !== 'ok') out.environments.push(add({...info, status: fstate.state, reason: fstate.reason}));
    else if (!approvedEnv(r.status)) out.environments.push(add({...info, status: 'unapproved', reason: `status "${r.status || 'none'}" is not approved`}));
    else out.environments.push(add({...info, status: 'available', reason: null}));
  }
  return out;
}

// ---------- 2. reference packs (snapshots; persisted immutably by generation.mjs)
async function dims(abs) { try { const i = await canvas.loadImage(abs); return {width: i.width, height: i.height}; } catch { return {width: null, height: null}; } }

// subject: {kind: 'character', id: 'character-01'} or {kind: 'story', id: '<file>.story.json'}
export async function buildReferencePack(subject, sources) {
  const src = {...DEFAULT_SOURCES, ...sources};
  const items = [];
  const push = async (it) => {
    const abs = repoFile(it.file), st = fileState(it.file, it.expected);
    const d = abs && fs.existsSync(abs) ? await dims(abs) : {width: null, height: null};
    items.push({ref: it.ref, role: it.role, source: it.file, sha256: st.sha256 || it.expected || null, expectedSha256: it.expected || null, width: d.width, height: d.height,
      approval: it.approval || null, version: it.version || 1, state: st.state, ...(st.reason ? {reason: st.reason} : {})});
  };
  const characterItems = async id => {
    let canon = {characters: {}};
    try { canon = readJson(src.canonFile); } catch {}
    for (const c of canon.characters?.[id] || []) await push({ref: `${id}:${c.id}`, role: c.role, file: c.file, expected: c.sha256, approval: c.approval, version: c.version});
    const regAbs = characterRegistry(src, id);
    if (!fs.existsSync(regAbs)) throw Object.assign(new Error(`no registry for character "${id}"`), {status: 422});
    const reg = readJson(regAbs);
    for (const [pose, r] of Object.entries(reg.poses || {})) {
      if (!APPROVED_POSE.has(r.approval)) continue;                 // only approved poses are references
      await push({ref: `${id}:pose-${pose}`, role: `pose ${pose} (${r.name || ''})`.trim(), file: r.file, expected: r.sha256, approval: r.approval, version: Number(r.version) || 1});
    }
  };
  if (subject?.kind === 'character') {
    if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(subject.id || '')) throw Object.assign(new Error('character id must be a lowercase identifier'), {status: 400});
    await characterItems(subject.id);
  } else if (subject?.kind === 'story') {
    const req = requirementsFor(subject.id, src);
    if (!req.valid) throw Object.assign(new Error(`story cannot be analysed: ${req.error}`), {status: 422});
    for (const c of req.characters) if (c.registryFound) await characterItems(c.character);
    for (const e of req.environments) if (e.file) await push({ref: `env:${e.id}`, role: 'environment plate', file: e.file, expected: e.sha256, approval: e.approval, version: e.version});
  } else throw Object.assign(new Error('subject must be {kind: "character"|"story", id}'), {status: 400});
  const canonical = items.map(i => ({ref: i.ref, source: i.source, sha256: i.sha256, version: i.version})).sort((a, b) => a.ref.localeCompare(b.ref));
  return {subject, items, packSha256: crypto.createHash('sha256').update(JSON.stringify(canonical)).digest('hex'),
    complete: items.every(i => i.state === 'ok'), problems: items.filter(i => i.state !== 'ok').map(i => `${i.ref}: ${i.reason}`)};
}

// References a candidate is compared with: the character's pack, or the registered environment of the same ID.
export async function referencesForAsset(assetType, assetKey, sources) {
  const src = {...DEFAULT_SOURCES, ...sources};
  if (assetType === 'character-pose') {
    try { return (await buildReferencePack({kind: 'character', id: String(assetKey).split('/')[0]}, src)).items; } catch { return []; }
  }
  let reg = {environments: {}};
  try { reg = readJson(src.environmentsFile); } catch {}
  const e = reg.environments?.[assetKey];
  if (!e) return [];
  const abs = repoFile(e.file), d = abs && fs.existsSync(abs) ? await dims(abs) : {};
  return [{ref: `env:${assetKey}`, source: e.file, sha256: e.sha256 || null, width: d.width ?? null, height: d.height ?? null, approval: e.status || null, version: Number(e.version) || 1}];
}

// Re-hash every pack item now and report drift (missing files, changed files).
export function verifyPack(items) {
  const results = items.map(i => {
    const abs = repoFile(i.source);
    if (!abs || !fs.existsSync(abs)) return {ref: i.ref, state: 'missing', reason: 'file not found'};
    const now = sha(abs);
    return now === i.sha256 ? {ref: i.ref, state: 'ok'} : {ref: i.ref, state: 'mismatch', reason: 'file changed since the pack was recorded', sha256Now: now};
  });
  return {ok: results.every(r => r.state === 'ok'), results};
}

// ---------- 3. candidate validation (measurable checks only; never approval)
export const VALIDATION_LIMITS = Object.freeze({maxBytes: 20 * 1024 * 1024, minSide: 256, maxSide: 4096, minPoseFigureHeight: 1000, environmentAspect: 9 / 16});

export async function validateCandidate({file, bytes, assetType, assetKey, referenceItems = []}) {
  const checks = [];
  const add = (id, status, detail) => checks.push({id, status, detail});
  add('file-size', bytes > 0 && bytes <= VALIDATION_LIMITS.maxBytes ? 'pass' : 'fail', `${bytes} bytes (limit ${VALIDATION_LIMITS.maxBytes})`);
  let img;
  try { img = await canvas.loadImage(fs.readFileSync(file)); add('image-integrity', 'pass', 'PNG decodes'); }
  catch (e) { add('image-integrity', 'fail', `does not decode as an image: ${e.message}`); return finish(checks); }
  const {width: W, height: H} = img;
  const sideOk = Math.min(W, H) >= VALIDATION_LIMITS.minSide && Math.max(W, H) <= VALIDATION_LIMITS.maxSide;
  add('dimensions', sideOk ? 'pass' : 'fail', `${W}×${H} (allowed sides ${VALIDATION_LIMITS.minSide}–${VALIDATION_LIMITS.maxSide})`);
  const c = canvas.createCanvas(W, H), ctx = c.getContext('2d'); ctx.drawImage(img, 0, 0);
  const px = ctx.getImageData(0, 0, W, H).data;
  let transparent = 0, partial = 0, x0 = W, x1 = -1, y0 = H, y1 = -1;
  for (let i = 0; i < W * H; i++) {
    const a = px[i * 4 + 3];
    if (a === 0) transparent++; else if (a < 255) partial++;
    if (a > 128) { const x = i % W, y = (i / W) | 0; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  }
  const tFrac = transparent / (W * H);
  if (assetType === 'character-pose') {
    add('transparency', tFrac >= 0.2 ? 'pass' : 'fail', `${(tFrac * 100).toFixed(1)}% fully transparent pixels (a character cut-out needs a transparent background)`);
    const figH = y1 >= y0 ? y1 - y0 + 1 : 0, figW = x1 >= x0 ? x1 - x0 + 1 : 0;
    add('figure-height', figH >= VALIDATION_LIMITS.minPoseFigureHeight ? 'pass' : 'warn', `opaque figure ${figW}×${figH} px (target ≥ ${VALIDATION_LIMITS.minPoseFigureHeight} px tall to avoid soft close-ups)`);
    // Consistency with approved poses of the same character: figure aspect (width/height) within the reference range.
    const poseRefs = referenceItems.filter(r => r.ref.includes(':pose-') && r.width && r.height);
    if (poseRefs.length && figH) {
      const ratios = poseRefs.map(r => r.width / r.height), lo = Math.min(...ratios) * 0.75, hi = Math.max(...ratios) * 1.25, ratio = figW / figH;
      add('pose-proportions', ratio >= lo && ratio <= hi ? 'pass' : 'warn', `figure width/height ${ratio.toFixed(2)} vs approved poses ${Math.min(...ratios).toFixed(2)}–${Math.max(...ratios).toFixed(2)} (±25%)`);
    } else add('pose-proportions', 'warn', 'no approved pose references to compare with');
  } else if (assetType === 'environment') {
    add('opacity', tFrac === 0 && partial === 0 ? 'pass' : 'fail', `${(tFrac * 100).toFixed(1)}% transparent (an environment plate must be fully opaque)`);
    const aspect = W / H, want = VALIDATION_LIMITS.environmentAspect;
    add('aspect-ratio', Math.abs(aspect - want) / want <= 0.06 ? 'pass' : 'warn', `${aspect.toFixed(3)} (9:16 is ${want.toFixed(3)})`);
    const envRef = referenceItems.find(r => r.ref === `env:${assetKey}`);
    add('environment-reference', envRef ? 'pass' : 'warn', envRef ? `compares to registered ${envRef.ref} (${envRef.width}×${envRef.height})` : 'no registered environment with this ID to compare with (new environment)');
  }
  add('human-approval', 'warn', 'validation never approves; a person must review the candidate');
  return finish(checks);
}
function finish(checks) {
  const status = checks.some(c => c.status === 'fail') ? 'fail' : checks.some(c => c.status === 'warn') ? 'warn' : 'pass';
  return {status, checks};
}
