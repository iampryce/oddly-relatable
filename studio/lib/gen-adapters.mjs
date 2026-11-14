// Generation worker adapters (AP-84B1). Interface:
//   status()                 -> {available: boolean, reason}
//   generate(request, ctx)   -> [{name, buffer, width, height, synthetic, provenance}]
// "none" is the default and never produces anything. "fake" draws a deterministic, clearly labelled synthetic test
// card (not artwork) so the queue, quarantine and review flow can be exercised without any model, GPU or service.
// "import" (AP-84B3 D1-6) reads one finished, transfer-verified candidate from a local run folder; it never
// generates anything and never talks to a GPU or a service. Live RunPod/ComfyUI adapters are not implemented.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import {canvas, ensureFonts, FONT} from '../../production/lib/runtime.mjs';
import {loadLock, validateRunSheet, buildProvenance, parseStrictJson, pngSize, sha256Buffer, isInside, REPO_ROOT,
  TRANSFER_SCHEMA, CANDIDATE_IDS, OUTPUT_NAME_RE, SHA256_RE} from './experiment-spec.mjs';
import {crossCheckRun} from './experiment-ledger.mjs';

export class NoWorkerError extends Error {
  constructor() { super('No generation worker is configured (adapter "none"). Nothing was generated.'); this.code = 'NO_WORKER'; this.retryable = false; }
}

export const noneAdapter = {
  id: 'none',
  status: () => ({available: false, reason: 'No generation worker is configured. Generation jobs can be queued and reviewed, but nothing is generated.'}),
  async generate() { throw new NoWorkerError(); },
};

// Deterministic seed from the request (and attempt), so identical requests give byte-identical fixtures.
export const requestSeed = (request, attempt) => crypto.createHash('sha256').update(JSON.stringify({assetType: request.assetType, assetKey: request.assetKey, description: request.description, attempt})).digest('hex');

export const fakeAdapter = {
  id: 'fake',
  status: () => ({available: true, reason: 'Local fake adapter: produces labelled synthetic test fixtures only (never artwork).'}),
  async generate(request, {attempt = 1} = {}) {
    ensureFonts();
    const seed = requestSeed(request, attempt), W = 512, H = 768;
    const c = canvas.createCanvas(W, H), ctx = c.getContext('2d');
    // Diagonal test-card stripes in grey and magenta: unmistakably not production artwork.
    ctx.fillStyle = '#9a9a9a'; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = '#d13ad1';
    for (let x = -H; x < W + H; x += 64) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x + 32, 0); ctx.lineTo(x + 32 + H, H); ctx.lineTo(x + H, H); ctx.closePath(); ctx.fill(); }
    ctx.fillStyle = '#ffffff'; ctx.fillRect(24, 250, W - 48, 268);
    ctx.fillStyle = '#000000'; ctx.textBaseline = 'top';
    ctx.font = `700 34px "${FONT.sans}"`; ctx.fillText('SYNTHETIC TEST FIXTURE', 40, 266);
    ctx.font = `600 22px "${FONT.sans}"`; ctx.fillText('NOT ARTWORK · NOT FOR PRODUCTION', 40, 314);
    ctx.font = `400 18px "${FONT.sans}"`;
    ctx.fillText(`type: ${request.assetType}`, 40, 360);
    ctx.fillText(`key: ${String(request.assetKey).slice(0, 36)}`, 40, 388);
    ctx.fillText(`attempt: ${attempt}`, 40, 416);
    ctx.fillText(`seed: ${seed.slice(0, 24)}`, 40, 444);
    ctx.fillText('adapter: fake (AP-84B1)', 40, 472);
    const buffer = c.toBuffer('image/png');
    return [{name: `synthetic-test-fixture-${seed.slice(0, 12)}.png`, buffer, width: W, height: H, synthetic: true,
      provenance: {adapter: 'fake', synthetic: true, seed, attempt, generator: 'studio/lib/gen-adapters.mjs fakeAdapter', note: 'Synthetic test fixture for pipeline testing; contains no artwork.'}}];
  },
};

// ---------------------------------------------------------------------------------------------------
// Import adapter (AP-84B3 D1-6, item I1).
// Run folder layout (outside the repository, never committed):
//   run-sheet.json                     the run record (schema ap84b3-run-sheet/1)
//   transfers/<A|B|C>/                 raw outputs + MANIFEST, moved here by verify-transfer.mjs
//   transfers/<A|B|C>.verified.json    verification record, written last and only on success
//   cutouts/<name>.png                 local cut-out of the raw output: this is the candidate that is imported
//   imported/<A|B|C>.json              marker written after a successful import (an import is never repeated)
//   ledger.json, ledger.head           the session ledger (sessions and workflow freezes); checked against the run sheet
//   frozen-q.json, frozen-s.json       the frozen workflow graphs recorded in the ledger
// The job description must start with "AP-84B3 candidate A" (or B, C): one job per candidate.
export class ImportRefused extends Error {
  constructor(message) { super(`Import refused: ${message}. Nothing was imported.`); this.code = 'IMPORT_REFUSED'; this.retryable = false; }
}
const MAX_IMPORT_BYTES = 20 * 1024 * 1024;
const CANDIDATE_REQUEST = /^AP-84B3 candidate ([ABC])(?![A-Za-z0-9])/;

// Read a regular file strictly inside `root` (no symlinks anywhere on the way, no traversal, size-capped).
function readInside(root, parts, what) {
  let cur = root;
  for (const part of parts) {
    if (typeof part !== 'string' || !part || part === '.' || part === '..' || /[\\/]/.test(part)) throw new ImportRefused(`${what}: unsafe path`);
    cur = path.join(cur, part);
    let st; try { st = fs.lstatSync(cur); } catch { throw new ImportRefused(`${what} is missing`); }
    if (st.isSymbolicLink()) throw new ImportRefused(`${what}: symbolic links are not allowed`);
  }
  const st = fs.lstatSync(cur);
  if (!st.isFile()) throw new ImportRefused(`${what} is not a regular file`);
  if (st.size < 1 || st.size > MAX_IMPORT_BYTES) throw new ImportRefused(`${what}: size must be 1 byte to ${MAX_IMPORT_BYTES} bytes`);
  return fs.readFileSync(cur);
}

// dir: the run folder. lockFile / decisionsFile are overridden only by tests (fixture lock and decision record).
export function createImportAdapter({dir, lockFile, decisionsFile} = {}) {
  const configured = () => (typeof dir === 'function' ? dir() : dir) || null;
  return {
    id: 'import',
    status: () => configured()
      ? {available: true, reason: 'Import adapter: imports transfer-verified AP-84B3 candidates from the configured run folder. It generates nothing.'}
      : {available: false, reason: 'Import adapter: no run folder is configured (STUDIO_GEN_IMPORT_DIR). Nothing can be imported.'},
    async generate(request) {
      const runDir = configured();
      if (!runDir) throw new ImportRefused('no run folder is configured');
      const root = path.resolve(runDir);
      if (!fs.existsSync(root) || fs.lstatSync(root).isSymbolicLink() || !fs.statSync(root).isDirectory()) throw new ImportRefused('the run folder does not exist');
      if (isInside(root, REPO_ROOT)) throw new ImportRefused('the run folder must be outside the repository');
      // 1. The experiment lock must be owner-approved (hash recorded in DECISIONS.md).
      let lock, lockSha256;
      try { ({lock, sha256: lockSha256} = loadLock({...(lockFile ? {lockFile} : {}), ...(decisionsFile ? {decisionsFile} : {})})); }
      catch (e) { throw new ImportRefused(e.message); }
      // 2. The job must be for the approved target and must name one candidate.
      if (request?.assetType !== lock.target.assetType || request?.assetKey !== lock.target.assetKey) throw new ImportRefused(`the job must be for ${lock.target.assetType} ${lock.target.assetKey}`);
      const m = CANDIDATE_REQUEST.exec(request?.description || '');
      if (!m || !CANDIDATE_IDS.includes(m[1])) throw new ImportRefused('the job description must start with "AP-84B3 candidate A", "B" or "C"');
      const id = m[1];
      if (fs.existsSync(path.join(root, 'imported', `${id}.json`))) throw new ImportRefused(`candidate ${id} has already been imported`);
      // 3. The run sheet must be valid and match the lock.
      let sheet;
      try { sheet = parseStrictJson(readInside(root, ['run-sheet.json'], 'run sheet')); }
      catch (e) { if (e instanceof ImportRefused) throw e; throw new ImportRefused(`run sheet is not valid: ${e.message}`); }
      const problems = validateRunSheet(sheet, lock, lockSha256);
      if (problems.length) throw new ImportRefused(`run sheet does not match the approved experiment: ${problems.join('; ')}`);
      const c = sheet.candidates[id];
      if (c.status !== 'retained') throw new ImportRefused(`candidate ${id} is recorded as ${c.status}`);
      const smokeHashes = new Set(sheet.smoke.map(s => s.sha256));
      if (smokeHashes.has(c.raw.sha256) || smokeHashes.has(c.cutout.sha256) || /smoke/.test(c.raw.name) || /smoke/.test(c.cutout.name)) throw new ImportRefused('smoke images are never candidates');
      // 4. The transfer must have been verified, and the files must still match (re-hashed here, not trusted).
      let record;
      try { record = parseStrictJson(readInside(root, ['transfers', `${id}.verified.json`], 'transfer verification record')); }
      catch (e) { if (e instanceof ImportRefused) throw e; throw new ImportRefused(`transfer verification record is not valid: ${e.message}`); }
      if (record.schema !== TRANSFER_SCHEMA || record.status !== 'verified' || record.candidate !== id || !SHA256_RE.test(record.manifestSha256 || '') || !Array.isArray(record.files)) throw new ImportRefused('the transfer has not been verified');
      const listed = record.files.find(f => f?.name === c.raw.name);
      if (!listed || listed.sha256 !== c.raw.sha256) throw new ImportRefused('the raw output is not in the verified transfer');
      if (sha256Buffer(readInside(root, ['transfers', id, 'MANIFEST'], 'transfer manifest')) !== record.manifestSha256) throw new ImportRefused('the transfer manifest changed after verification');
      const raw = readInside(root, ['transfers', id, c.raw.name], 'raw output');
      if (raw.length !== c.raw.bytes || sha256Buffer(raw) !== c.raw.sha256) throw new ImportRefused('the raw output does not match its recorded SHA-256');
      if (!pngSize(raw)) throw new ImportRefused('the raw output is not a PNG');
      // 5. The cut-out is the candidate. Its hash must be the one recorded in the run sheet.
      if (!OUTPUT_NAME_RE.test(c.cutout.name)) throw new ImportRefused('unsafe cut-out file name');
      const cut = readInside(root, ['cutouts', c.cutout.name], 'cut-out');
      if (cut.length !== c.cutout.bytes || sha256Buffer(cut) !== c.cutout.sha256) throw new ImportRefused('the cut-out does not match its recorded SHA-256');
      const size = pngSize(cut);
      if (!size) throw new ImportRefused('the cut-out is not a PNG');
      // 6. The run sheet, the session ledger, the frozen graph and the lock must all agree before anything is imported.
      const cross = crossCheckRun({runDir: root, lock, lockSha256, sheet, workflow: lock.candidates[id].workflow});
      if (cross.length) throw new ImportRefused(`the run record is inconsistent: ${cross.join('; ')}`);
      const provenance = buildProvenance({lock, lockSha256, sheet, candidate: id, transfer: record});
      // 7. Mark the candidate as imported (write-once), so the same candidate can never be imported twice.
      fs.mkdirSync(path.join(root, 'imported'), {recursive: true});
      try { fs.writeFileSync(path.join(root, 'imported', `${id}.json`), JSON.stringify({candidate: id, cutoutSha256: c.cutout.sha256, importedAt: new Date().toISOString()}, null, 1), {flag: 'wx'}); }
      catch { throw new ImportRefused(`candidate ${id} has already been imported`); }
      return [{name: `ap84b3-candidate-${id.toLowerCase()}-cutout.png`, buffer: cut, width: size.width, height: size.height, synthetic: false, provenance}];
    },
  };
}
// The configured adapter reads its run folder from server configuration (never from an API client).
export const importAdapter = createImportAdapter({dir: () => process.env.STUDIO_GEN_IMPORT_DIR});

export const ADAPTERS = Object.freeze({none: noneAdapter, fake: fakeAdapter, import: importAdapter});
export function adapterFor(id) {
  // Tests may pass an adapter object (e.g. an import adapter bound to a fixture lock). The server only ever passes an id.
  if (id && typeof id === 'object' && typeof id.id === 'string' && typeof id.generate === 'function' && typeof id.status === 'function') return id;
  const a = ADAPTERS[id];
  if (!a) throw new Error(`Unknown generation adapter "${id}" (available: ${Object.keys(ADAPTERS).join(', ')})`);
  return a;
}
