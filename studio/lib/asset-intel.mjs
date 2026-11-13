// Story asset intelligence, reference packs and candidate validation (AP-84B2). Read-only towards the repository:
// registries, stories and artwork are only read and hashed, never written.
//
//  requirementsFor(storyFile)  which characters / poses / environments a story needs, and whether each is
//                              available | missing | unapproved | unresolved (with the reason)
//  buildReferencePack(...)     immutable snapshot of reference files (source, SHA-256, dimensions, approval, version,
//                              measured silhouette / feet / palette); only approved, verified references are included
//  verifyPack(pack)            re-hash every item now: detects missing files and hash mismatches
//  validateCandidate(...)      measurable checks on a quarantined candidate (never approves anything)
//  publicPackItem / publicRequirements   API views without filesystem paths (sources stay internal)
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

// ---------- 2. image measurement (shared by references and candidates; read-only)
// Colour bins: 4 bits per channel for pose palettes (4096 bins), 3 bits per channel for environment histograms (512 bins).
const BIN4 = (r, g, b) => ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4);
const BIN3 = (r, g, b) => ((r >> 5) << 6) | ((g >> 5) << 3) | (b >> 5);
const SOLID = 128;                                                    // alpha above this counts as part of the figure

// Measures what can honestly be measured from pixels: transparency, the figure's silhouette (bounding box of
// solid pixels), the feet anchor (centre of the lowest band of the silhouette), clipping at canvas edges, edge
// quality (isolated specks, near-white fringe pixels on the outline), a palette (cut-outs) or a colour histogram
// (opaque plates), and flat borders (letterboxing) on opaque plates.
// Loads from the file path: @napi-rs/canvas fails to decode some valid PNGs (e.g. the lookdev plates) from a Buffer
// ("Invalid SVG image") but decodes them from a path. withCounts adds the full colour-bin counts (not stored in packs).
export async function measureImage(file, {withCounts = false} = {}) {
  const img = await canvas.loadImage(file);
  const W = img.width, H = img.height, N = W * H;
  const c = canvas.createCanvas(W, H), ctx = c.getContext('2d'); ctx.drawImage(img, 0, 0);
  const px = ctx.getImageData(0, 0, W, H).data;
  const solid = new Uint8Array(N), pal = new Map(), hist = new Float64Array(512);
  let transparent = 0, partial = 0, opaque = 0, x0 = W, x1 = -1, y0 = H, y1 = -1;
  for (let i = 0; i < N; i++) {
    const o = i * 4, a = px[o + 3];
    if (a === 0) transparent++; else if (a < 255) partial++;
    if (a <= SOLID) continue;
    solid[i] = 1; opaque++;
    const x = i % W, y = (i / W) | 0;
    if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
    const k = BIN4(px[o], px[o + 1], px[o + 2]); pal.set(k, (pal.get(k) || 0) + 1);
    hist[BIN3(px[o], px[o + 1], px[o + 2])]++;
  }
  const out = {width: W, height: H, transparentFraction: +(transparent / N).toFixed(4), partialFraction: +(partial / N).toFixed(4),
    cutout: transparent / N >= 0.2, silhouette: null, feet: null, feetRelX: null, clipped: [], edge: null, palette: null, histogram: null, flatBorders: []};
  if (withCounts) out.counts = pal;
  if (opaque) {
    const sw = x1 - x0 + 1, shh = y1 - y0 + 1;
    out.silhouette = {x: x0, y: y0, width: sw, height: shh};
    if (out.cutout) {
      out.clipped = [x0 === 0 && 'left', y0 === 0 && 'top', x1 === W - 1 && 'right', y1 === H - 1 && 'bottom'].filter(Boolean);
      // Feet anchor: centre of the solid pixels in the lowest 3% of the silhouette (at least 2 rows).
      const band = Math.max(2, Math.round(shh * 0.03));
      let fx0 = W, fx1 = -1;
      for (let y = y1 - band + 1; y <= y1; y++) for (let x = x0; x <= x1; x++) if (solid[y * W + x]) { if (x < fx0) fx0 = x; if (x > fx1) fx1 = x; }
      if (fx1 >= fx0) { const fx = Math.round((fx0 + fx1) / 2); out.feet = {x: fx, y: y1}; out.feetRelX = +((fx - x0) / sw).toFixed(4); }
      // Edge quality: outline pixels (solid with a non-solid 4-neighbour), isolated specks, near-white fringe.
      let boundary = 0, specks = 0, white = 0;
      for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
        const i = y * W + x;
        if (!solid[i]) continue;
        const n = (x > 0 && solid[i - 1]) + (x < W - 1 && solid[i + 1]) + (y > 0 && solid[i - W]) + (y < H - 1 && solid[i + W]);
        if (n === 0) specks++;
        if (n < 4) { boundary++; const o = i * 4; if (Math.min(px[o], px[o + 1], px[o + 2]) > 230) white++; }
      }
      out.edge = {boundary, speckFraction: +(specks / opaque).toFixed(5), haloFraction: boundary ? +(white / boundary).toFixed(4) : 0};
      // Palette: most frequent bins covering 95% of the figure's pixels (at most 256 bins).
      const bins = [...pal.entries()].sort((a, b) => b[1] - a[1]);
      const keep = []; let acc = 0;
      for (const [k, n] of bins) { keep.push(k); acc += n; if (acc / opaque >= 0.95 || keep.length >= 256) break; }
      out.palette = keep;
    } else {
      out.histogram = Array.from(hist, v => +(v / opaque).toFixed(5));
      // Flat borders: a 2 px strip along a side with (almost) no luminance variation suggests letterboxing or padding.
      const strip = (xa, ya, xb, yb) => {
        let n = 0, s = 0, s2 = 0;
        for (let y = ya; y < yb; y++) for (let x = xa; x < xb; x++) { const o = (y * W + x) * 4, l = 0.299 * px[o] + 0.587 * px[o + 1] + 0.114 * px[o + 2]; n++; s += l; s2 += l * l; }
        return n ? Math.sqrt(Math.max(0, s2 / n - (s / n) ** 2)) : 0;
      };
      out.flatBorders = [['top', strip(0, 0, W, 2)], ['bottom', strip(0, H - 2, W, H)], ['left', strip(0, 0, 2, H)], ['right', strip(W - 2, 0, W, H)]]
        .filter(([, sd]) => sd < 1.5).map(([side]) => side);
    }
  }
  return out;
}

// Validation configuration (expected canvas sizes). Null means "not defined": the check reports n/a instead of guessing.
function validationConfig(src) {
  try { return readJson(src.canonFile).validation || {}; } catch { return {}; }
}

// ---------- 3. reference packs (snapshots; persisted immutably by generation.mjs)
// subject: {kind: 'character', id: 'character-01'} or {kind: 'story', id: '<file>.story.json'}
// Internally each item keeps its repository-relative source so it can be re-verified; publicPackItem() removes it.
export async function buildReferencePack(subject, sources) {
  const src = {...DEFAULT_SOURCES, ...sources};
  const items = [], extraProblems = [];
  const push = async (it) => {
    const abs = repoFile(it.file), st = fileState(it.file, it.expected);
    let features = null;
    if (st.state === 'ok') { try { features = await measureImage(abs); } catch {} }
    items.push({ref: it.ref, role: it.role, source: it.file, sha256: st.sha256 || it.expected || null, expectedSha256: it.expected || null,
      width: features?.width ?? null, height: features?.height ?? null, approval: it.approval || null, approved: it.approved !== false, version: it.version || 1,
      ...(it.feet ? {feet: it.feet} : {}), ...(it.figureHeight ? {figureHeight: it.figureHeight} : {}),
      state: st.state, ...(st.reason ? {reason: st.reason} : {}), features});
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
      await push({ref: `${id}:pose-${pose}`, role: `pose ${pose} (${r.name || ''})`.trim(), file: r.file, expected: r.sha256, approval: r.approval,
        version: Number(r.version) || 1, feet: r.feet, figureHeight: r.figureHeight});
    }
  };
  if (subject?.kind === 'character') {
    if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(subject.id || '')) throw Object.assign(new Error('character id must be a lowercase identifier'), {status: 400});
    await characterItems(subject.id);
  } else if (subject?.kind === 'story') {
    const req = requirementsFor(subject.id, src);
    if (!req.valid) throw Object.assign(new Error(`story cannot be analysed: ${req.error}`), {status: 422});
    for (const c of req.characters) {
      if (c.registryFound) await characterItems(c.character);
      // A story's pack is only complete when everything the story needs is available.
      for (const p of c.poses) if (p.status !== 'available') extraProblems.push(`${c.character}:pose-${p.pose ?? '?'}: ${p.status} (${p.reason})`);
    }
    for (const e of req.environments) {
      // Only approved, verified environments become references; anything else is named as a problem, never included silently.
      if (e.status === 'available') await push({ref: `env:${e.id}`, role: 'environment plate', file: e.file, expected: e.sha256, approval: e.approval, version: e.version});
      else extraProblems.push(`env:${e.id ?? 'direct-file'}: ${e.status} (${e.reason}); not used as a reference`);
    }
  } else throw Object.assign(new Error('subject must be {kind: "character"|"story", id}'), {status: 400});
  const canonical = items.map(i => ({ref: i.ref, source: i.source, sha256: i.sha256, version: i.version})).sort((a, b) => a.ref.localeCompare(b.ref));
  const problems = [...items.filter(i => i.state !== 'ok').map(i => `${i.ref}: ${i.reason}`), ...extraProblems];
  return {subject, items, packSha256: crypto.createHash('sha256').update(JSON.stringify(canonical)).digest('hex'), complete: problems.length === 0, problems};
}

// Packs recorded before measurements existed: measure items whose file still matches the recorded hash.
export async function ensureFeatures(items) {
  for (const i of items) {
    if (i.features || i.state !== 'ok') continue;
    const abs = repoFile(i.source);
    if (abs && fs.existsSync(abs) && sha(abs) === i.sha256) { try { i.features = await measureImage(abs); } catch {} }
  }
  return items;
}

// References a candidate is compared with. Poses: the character's approved references. Environments: the registered
// environment with the same ID (flagged if unapproved) plus every approved environment plate as a style family.
export async function referencesForAsset(assetType, assetKey, sources) {
  const src = {...DEFAULT_SOURCES, ...sources};
  if (assetType === 'character-pose') {
    try { return (await buildReferencePack({kind: 'character', id: String(assetKey).split('/')[0]}, src)).items; } catch { return []; }
  }
  let reg = {environments: {}};
  try { reg = readJson(src.environmentsFile); } catch {}
  const items = [];
  for (const [id, e] of Object.entries(reg.environments || {})) {
    const approved = approvedEnv(e.status);
    if (!approved && id !== assetKey) continue;
    const st = fileState(e.file, e.sha256);
    let features = null;
    if (st.state === 'ok') { try { features = await measureImage(repoFile(e.file)); } catch {} }
    items.push({ref: `env:${id}`, role: 'environment plate', source: e.file, sha256: st.sha256 || e.sha256 || null, width: features?.width ?? null, height: features?.height ?? null,
      approval: e.status || null, approved, version: Number(e.version) || 1, state: st.state, features});
  }
  return items;
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

// ---------- public views: no filesystem paths leave the studio (identifiers, roles, hashes, sizes, approvals only)
export function publicPackItem(i) {
  const f = i.features;
  return {ref: i.ref, role: i.role, sha256: i.sha256, expectedSha256: i.expectedSha256 ?? null, width: i.width, height: i.height,
    approval: i.approval, approved: i.approved !== false, version: i.version, state: i.state, ...(i.reason ? {reason: i.reason} : {}),
    registeredFeet: i.feet ?? null, measured: f ? {silhouette: f.silhouette, transparentFraction: f.transparentFraction, cutout: f.cutout, feet: f.feet} : null};
}
export function publicRequirements(r) {
  const strip = ({file, registry, legacyFile, ...rest}) => ({...rest, ...(legacyFile !== undefined ? {directFile: !!legacyFile} : {})});
  return {...r, characters: r.characters.map(c => ({...strip(c), poses: c.poses.map(strip)})), environments: r.environments.map(strip)};
}

// ---------- 4. candidate validation (measurable checks only; never approval)
// Statuses: pass | warn | fail | n/a. "n/a" means the check cannot be measured honestly with the data available.
export const VALIDATION_LIMITS = Object.freeze({maxBytes: 20 * 1024 * 1024, minSide: 256, maxSide: 4096, minPoseFigureHeight: 1000, environmentAspect: 9 / 16,
  proportionTolerance: 0.25, feetRelTolerance: 0.15, palettePass: 0.75, paletteFail: 0.4, envPalettePass: 0.6, envPaletteFail: 0.25, haloMargin: 0.15});
const L = VALIDATION_LIMITS;
const range = xs => [Math.min(...xs), Math.max(...xs)];
const f2 = v => v.toFixed(2);

// Fraction of the candidate's figure pixels whose colour bin is in (or next to) the approved poses' palettes.
function paletteCoverage(counts, refPalettes) {
  const allowed = new Set();
  for (const pal of refPalettes) for (const k of pal) {
    const r = k >> 8, g = (k >> 4) & 15, b = k & 15;
    for (let dr = -1; dr <= 1; dr++) for (let dg = -1; dg <= 1; dg++) for (let db = -1; db <= 1; db++) {
      const R = r + dr, G = g + dg, B = b + db;
      if (R >= 0 && R < 16 && G >= 0 && G < 16 && B >= 0 && B < 16) allowed.add((R << 8) | (G << 4) | B);
    }
  }
  let inside = 0, total = 0;
  for (const [k, n] of counts) { total += n; if (allowed.has(k)) inside += n; }
  return total ? inside / total : 0;
}
const intersect = (a, b) => a.reduce((s, v, i) => s + Math.min(v, b[i] || 0), 0);

export async function validateCandidate({file, bytes, assetType, assetKey, referenceItems = [], sources}) {
  const src = {...DEFAULT_SOURCES, ...sources};
  const expectedCanvas = validationConfig(src).expectedCanvas || {};
  const checks = [];
  const add = (id, status, detail) => checks.push({id, status, detail});
  add('file-size', bytes > 0 && bytes <= L.maxBytes ? 'pass' : 'fail', `${bytes} bytes (limit ${L.maxBytes})`);
  let m;
  try { m = await measureImage(file, {withCounts: true}); add('image-integrity', 'pass', 'PNG decodes'); }
  catch (e) { add('image-integrity', 'fail', `does not decode as an image: ${e.message}`); return finish(checks); }
  const {width: W, height: H} = m;
  add('dimensions', Math.min(W, H) >= L.minSide && Math.max(W, H) <= L.maxSide ? 'pass' : 'fail', `${W}×${H} (allowed sides ${L.minSide}–${L.maxSide})`);
  const exp = expectedCanvas[assetType];

  if (assetType === 'character-pose') {
    const refs = referenceItems.filter(r => r.ref.includes(':pose-') && r.approved !== false && r.features?.silhouette);
    if (exp) add('canvas-dimensions', W === exp.width && H === exp.height ? 'pass' : 'warn', `${W}×${H} (expected ${exp.width}×${exp.height})`);
    else add('canvas-dimensions', 'n/a', 'no expected canvas size is configured for character poses (approved poses are tight crops of different sizes)');
    add('transparency', m.cutout ? 'pass' : 'fail', `${(m.transparentFraction * 100).toFixed(1)}% fully transparent pixels (a character cut-out needs a transparent background)`);
    const sil = m.silhouette;
    if (!sil || !m.cutout) {
      for (const id of ['figure-height', 'pose-proportions', 'feet-anchor', 'palette-consistency', 'edge-integrity'])
        add(id, 'fail', sil ? 'no separable figure: the image has no transparent background' : 'no figure found: the image has no solid pixels');
    } else {
      add('figure-height', sil.height >= L.minPoseFigureHeight ? 'pass' : 'warn', `measured figure ${sil.width}×${sil.height} px (target ≥ ${L.minPoseFigureHeight} px tall to avoid soft close-ups)`);
      // Proportions: measured silhouette width/height compared with the measured silhouettes of the approved poses.
      if (refs.length) {
        const [lo, hi] = range(refs.map(r => r.features.silhouette.width / r.features.silhouette.height)), ratio = sil.width / sil.height;
        add('pose-proportions', ratio >= lo * (1 - L.proportionTolerance) && ratio <= hi * (1 + L.proportionTolerance) ? 'pass' : 'warn',
          `silhouette width/height ${f2(ratio)} vs approved poses ${f2(lo)}–${f2(hi)} (±${L.proportionTolerance * 100}%)`);
      } else add('pose-proportions', 'n/a', 'no measured approved pose silhouettes to compare with');
      // Feet anchor: detectable, not cut off, and placed within the figure like the registered anchors of approved poses.
      const anchored = refs.filter(r => r.feet && Number.isFinite(r.feet.x));
      if (!m.feet) add('feet-anchor', 'fail', 'no feet anchor could be measured');
      else if (m.clipped.includes('bottom')) add('feet-anchor', 'fail', `figure touches the bottom edge: feet may be cut off (measured anchor ${m.feet.x},${m.feet.y})`);
      else if (!anchored.length) add('feet-anchor', 'warn', `measured anchor ${m.feet.x},${m.feet.y}; no registered feet anchors on approved poses to compare with`);
      else {
        const [lo, hi] = range(anchored.map(r => (r.feet.x - r.features.silhouette.x) / r.features.silhouette.width));
        const ok = m.feetRelX >= lo - L.feetRelTolerance && m.feetRelX <= hi + L.feetRelTolerance;
        add('feet-anchor', ok ? 'pass' : 'warn', `measured anchor ${m.feet.x},${m.feet.y} at ${f2(m.feetRelX)} of the figure width; registered anchors of ${anchored.length} approved poses span ${f2(lo)}–${f2(hi)} (±${L.feetRelTolerance})`);
      }
      // Palette: share of figure pixels in colours used by the approved poses.
      const palRefs = refs.filter(r => r.features.palette?.length);
      if (palRefs.length) {
        const cov = paletteCoverage(m.counts, palRefs.map(r => r.features.palette));
        add('palette-consistency', cov >= L.palettePass ? 'pass' : cov >= L.paletteFail ? 'warn' : 'fail',
          `${(cov * 100).toFixed(1)}% of figure pixels use colours of the approved poses (pass ≥ ${L.palettePass * 100}%, fail < ${L.paletteFail * 100}%)`);
      } else add('palette-consistency', 'n/a', 'no measured approved pose palettes to compare with');
      // Edges: cut off at the canvas edge, stray specks, near-white fringe from background removal (relative to approved poses).
      const edgeRefs = refs.filter(r => r.features.edge);
      const issues = [];
      if (m.clipped.length) issues.push(['fail', `figure is cut off at the ${m.clipped.join(', ')} edge`]);
      const maxSpeck = edgeRefs.length ? Math.max(...edgeRefs.map(r => r.features.edge.speckFraction)) : 0;
      const maxHalo = edgeRefs.length ? Math.max(...edgeRefs.map(r => r.features.edge.haloFraction)) : 0;
      if (m.edge.speckFraction > maxSpeck * 2 + 0.001) issues.push(['warn', `${(m.edge.speckFraction * 100).toFixed(2)}% isolated specks (approved poses ≤ ${(maxSpeck * 100).toFixed(2)}%)`]);
      if (m.edge.haloFraction > maxHalo + L.haloMargin) issues.push(['warn', `${(m.edge.haloFraction * 100).toFixed(1)}% near-white outline pixels, a possible halo (approved poses ≤ ${(maxHalo * 100).toFixed(1)}%)`]);
      add('edge-integrity', issues.some(i => i[0] === 'fail') ? 'fail' : issues.length ? 'warn' : 'pass',
        issues.length ? issues.map(i => i[1]).join('; ') : `not cut off; specks ${(m.edge.speckFraction * 100).toFixed(2)}%, near-white outline ${(m.edge.haloFraction * 100).toFixed(1)}%${edgeRefs.length ? ' (within the approved poses\' range)' : ''}`);
    }
  } else if (assetType === 'environment') {
    const same = referenceItems.find(r => r.ref === `env:${assetKey}`);
    const family = referenceItems.filter(r => r.ref.startsWith('env:') && r.approved !== false && r.features?.histogram);
    add('opacity', m.transparentFraction === 0 && m.partialFraction === 0 ? 'pass' : 'fail', `${(m.transparentFraction * 100).toFixed(1)}% transparent (an environment plate must be fully opaque)`);
    const aspect = W / H;
    add('aspect-ratio', Math.abs(aspect - L.environmentAspect) / L.environmentAspect <= 0.06 ? 'pass' : 'warn', `${aspect.toFixed(3)} (9:16 is ${L.environmentAspect.toFixed(3)})`);
    // Expected canvas: configured, or the size shared by every approved plate; otherwise not measurable.
    const sizes = [...new Set(family.map(r => `${r.width}×${r.height}`))];
    if (exp) add('canvas-dimensions', W === exp.width && H === exp.height ? 'pass' : 'warn', `${W}×${H} (expected ${exp.width}×${exp.height})`);
    else if (sizes.length === 1) add('canvas-dimensions', `${W}×${H}` === sizes[0] ? 'pass' : 'warn', `${W}×${H} (every approved plate is ${sizes[0]})`);
    else add('canvas-dimensions', 'n/a', sizes.length ? `approved plates differ in size (${sizes.join(', ')}); no single expected canvas` : 'no approved plates or configured size to compare with');
    if (same && same.approved !== false) add('environment-reference', 'pass', `compares with registered ${same.ref} (${same.approval})`);
    else if (same) add('environment-reference', 'warn', `${same.ref} is registered but not approved (${same.approval}); it is not used as a reference`);
    else add('environment-reference', 'warn', family.length ? `new environment: compared with ${family.length} approved plate(s) as a style family` : 'new environment: no approved plates to compare with');
    const sameOk = same && same.approved !== false && same.width;
    add('environment-reference-dimensions', sameOk ? (same.width === W && same.height === H ? 'pass' : 'warn') : 'n/a',
      sameOk ? `${W}×${H} vs registered ${same.width}×${same.height}` : 'no approved environment with this ID to compare dimensions with');
    if (m.histogram && family.length) {
      const targets = sameOk && same.features?.histogram ? [same] : family;
      const best = Math.max(...targets.map(r => intersect(m.histogram, r.features.histogram)));
      add('environment-palette', best >= L.envPalettePass ? 'pass' : best >= L.envPaletteFail ? 'warn' : 'fail',
        `colour histogram overlap ${(best * 100).toFixed(1)}% with ${targets.length === 1 && targets[0] === same ? same.ref : 'the closest approved plate'} (pass ≥ ${L.envPalettePass * 100}%, fail < ${L.envPaletteFail * 100}%)`);
    } else add('environment-palette', 'n/a', m.histogram ? 'no approved plates to compare colours with' : 'the image is not an opaque plate');
    add('edge-integrity', m.flatBorders.length ? 'warn' : 'pass', m.flatBorders.length ? `flat border on the ${m.flatBorders.join(', ')} side(s): possible letterboxing or padding` : 'no flat borders (no letterboxing or padding detected)');
  }
  add('human-approval', 'warn', 'validation never approves; a person must review the candidate');
  return finish(checks);
}
function finish(checks) {
  const st = checks.filter(c => c.status !== 'n/a');
  const status = st.some(c => c.status === 'fail') ? 'fail' : st.some(c => c.status === 'warn') ? 'warn' : 'pass';
  return {status, checks};
}
