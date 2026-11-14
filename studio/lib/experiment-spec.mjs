// AP-84B3 experiment lock, canonical hashing, run-sheet and provenance schema (D1-6, items I3).
//
// The lock file (studio/config/ap84b3-experiment.json) holds every owner-approved experiment value once.
// Nothing here decides what is approved: a lock is "approved" only when its canonical SHA-256 appears in
// DECISIONS.md as  AP-84B3-LOCK-APPROVED-SHA256=<hex>  (and is not listed as revoked). That line is written
// by a documentation commit after the owner's explicit review. Tests never contain an approved hash, so a
// passing test cannot authorise a change to a prompt, model hash, software pin, seed or workflow setting.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(HERE, '..', '..');
export const LOCK_FILE = path.join(REPO_ROOT, 'studio', 'config', 'ap84b3-experiment.json');
export const DECISIONS_FILE = path.join(REPO_ROOT, 'DECISIONS.md');
export const LOCK_SCHEMA = 'ap84b3-experiment-lock/1';
export const RUN_SHEET_SCHEMA = 'ap84b3-run-sheet/1';
export const TRANSFER_SCHEMA = 'ap84b3-transfer-verified/1';
export const MANIFEST_HEADER = '# ap84b3-manifest/1';
export const RESOURCES_HEADER = '# ap84b3-resources/1';
export const CANDIDATE_IDS = Object.freeze(['A', 'B', 'C']);
export const SHA256_RE = /^[0-9a-f]{64}$/;
export const COMMIT_RE = /^[0-9a-f]{40}$/;
export const OUTPUT_NAME_RE = /^[a-z0-9][a-z0-9-]{0,80}\.(png|json)$/;
export const RUN_ID_RE = /^r-\d{8}-\d{6}$/;

export class LockError extends Error {
  constructor(message, code = 'LOCK_INVALID') { super(message); this.code = code; }
}

// ---------------------------------------------------------------------------------------------------
// Strict JSON: like JSON.parse, but duplicate keys and non-integer numbers are errors. Decimals must be
// stored as strings so that number formatting can never change the canonical form.
export function parseStrictJson(input) {
  let s = Buffer.isBuffer(input) ? input.toString('utf8') : String(input);
  if (s.charCodeAt(0) === 0xfeff) s = s.slice(1);                       // byte-order mark
  let i = 0;
  const err = m => new LockError(`strict JSON: ${m} at offset ${i}`, 'LOCK_JSON');
  const ws = () => { while (i < s.length && ' \t\r\n'.includes(s[i])) i++; };
  function value() {
    ws();
    const c = s[i];
    if (c === '{') return object();
    if (c === '[') return array();
    if (c === '"') return string();
    if (c === '-' || (c >= '0' && c <= '9')) return number();
    for (const [lit, v] of [['true', true], ['false', false], ['null', null]]) if (s.startsWith(lit, i)) { i += lit.length; return v; }
    throw err('unexpected token');
  }
  function object() {
    i++; const o = Object.create(null), seen = new Set();
    ws();
    if (s[i] === '}') { i++; return {...o}; }
    for (;;) {
      ws();
      if (s[i] !== '"') throw err('object key must be a string');
      const k = string();
      if (seen.has(k)) throw err(`duplicate key ${JSON.stringify(k)}`);
      seen.add(k);
      ws();
      if (s[i] !== ':') throw err('expected ":"');
      i++;
      o[k] = value();
      ws();
      if (s[i] === ',') { i++; continue; }
      if (s[i] === '}') { i++; return {...o}; }
      throw err('expected "," or "}"');
    }
  }
  function array() {
    i++; const a = [];
    ws();
    if (s[i] === ']') { i++; return a; }
    for (;;) {
      a.push(value());
      ws();
      if (s[i] === ',') { i++; continue; }
      if (s[i] === ']') { i++; return a; }
      throw err('expected "," or "]"');
    }
  }
  function string() {
    const start = i; i++;
    while (i < s.length && s[i] !== '"') { if (s[i] === '\\') i++; i++; }
    if (i >= s.length) throw err('unterminated string');
    i++;
    try { return JSON.parse(s.slice(start, i)); } catch { throw err('invalid string'); }
  }
  function number() {
    const m = /^-?(0|[1-9]\d*)/.exec(s.slice(i, i + 40));
    if (!m) throw err('invalid number');
    const after = s[i + m[0].length];
    if (after === '.' || after === 'e' || after === 'E') throw err('non-integer numbers are not allowed (store decimals as strings)');
    const n = Number(m[0]);
    if (!Number.isSafeInteger(n) || Object.is(n, -0)) throw err('integer out of range');
    i += m[0].length;
    return n;
  }
  const v = value();
  ws();
  if (i !== s.length) throw err('trailing content');
  return v;
}

// Compare two strings by Unicode code point (JavaScript's default sort compares UTF-16 code units).
function byCodePoint(a, b) {
  const x = Array.from(a), y = Array.from(b);
  for (let k = 0; k < Math.min(x.length, y.length); k++) {
    const d = x[k].codePointAt(0) - y[k].codePointAt(0);
    if (d) return d;
  }
  return x.length - y.length;
}

// Canonical form: keys sorted by code point, arrays in order, no whitespace, strings as stored.
export function canonicalize(v) {
  if (v === null || typeof v === 'boolean') return String(v);
  if (typeof v === 'number') {
    if (!Number.isSafeInteger(v)) throw new LockError('canonical JSON: only integers are allowed as numbers', 'LOCK_JSON');
    return String(v);
  }
  if (typeof v === 'string') return JSON.stringify(v);
  if (Array.isArray(v)) return '[' + v.map(canonicalize).join(',') + ']';
  if (typeof v === 'object') return '{' + Object.keys(v).sort(byCodePoint).map(k => JSON.stringify(k) + ':' + canonicalize(v[k])).join(',') + '}';
  throw new LockError('canonical JSON: unsupported value', 'LOCK_JSON');
}

// Canonical SHA-256 of JSON text: parse strictly, re-serialise canonically, hash the UTF-8 bytes.
export function canonicalHash(input) {
  return crypto.createHash('sha256').update(Buffer.from(canonicalize(parseStrictJson(input)), 'utf8')).digest('hex');
}

// ---------------------------------------------------------------------------------------------------
// Approval record in DECISIONS.md.
const APPROVED_RE = /AP-84B3-LOCK-APPROVED-SHA256=([0-9a-f]{64})/g;
const REVOKED_RE = /AP-84B3-LOCK-REVOKED-SHA256=([0-9a-f]{64})/g;
export function readApprovals(decisionsText) {
  const approved = new Set([...decisionsText.matchAll(APPROVED_RE)].map(m => m[1]));
  const revoked = new Set([...decisionsText.matchAll(REVOKED_RE)].map(m => m[1]));
  return {approved, revoked, isApproved: h => approved.has(h) && !revoked.has(h)};
}

// ---------------------------------------------------------------------------------------------------
// Money and rates. Everything is integer micro-dollars; rates are per hour. Conversions round up.
export function usdToMicro(str) {
  if (typeof str !== 'string' || !/^\d+(\.\d{1,6})?$/.test(str)) throw new LockError(`not a decimal dollar amount: ${JSON.stringify(str)}`, 'LOCK_VALUE');
  const [w, f = ''] = str.split('.');
  return Number(w) * 1_000_000 + Number((f + '000000').slice(0, 6));
}
export const microToUsd = m => `${Math.floor(m / 1_000_000)}.${String(m % 1_000_000).padStart(6, '0')}`;
const ceilDiv = (a, b) => Math.floor((a + b - 1) / b);
export const BILLING_PERIODS = Object.freeze(['hour', 'second', 'day', 'month', 'gb-month', 'one-off']);

// Normalise a published rate to micro-dollars per hour. hoursPerMonth is the documented billing-period
// assumption (672 = a 28-day month, the shortest, so monthly prices err high). A one-off charge has no
// hourly rate: it is returned as {hourlyMicro: 0, oneOffMicro}.
export function normaliseHourly({rate, period, quantity = 1, hoursPerMonth = 672}) {
  const r = usdToMicro(rate);
  if (!Number.isInteger(quantity) || quantity < 1) throw new LockError('quantity must be a positive integer', 'LOCK_VALUE');
  if (!Number.isInteger(hoursPerMonth) || hoursPerMonth < 1) throw new LockError('hoursPerMonth must be a positive integer', 'LOCK_VALUE');
  switch (period) {
    case 'hour': return {hourlyMicro: r * quantity, oneOffMicro: 0, conversion: 'published hourly rate × quantity'};
    case 'second': return {hourlyMicro: r * quantity * 3600, oneOffMicro: 0, conversion: 'per-second rate × 3600 × quantity'};
    case 'day': return {hourlyMicro: ceilDiv(r * quantity, 24), oneOffMicro: 0, conversion: 'per-day rate × quantity ÷ 24'};
    case 'month': return {hourlyMicro: ceilDiv(r * quantity, hoursPerMonth), oneOffMicro: 0, conversion: `per-month rate × quantity ÷ ${hoursPerMonth}`};
    case 'gb-month': return {hourlyMicro: ceilDiv(r * quantity, hoursPerMonth), oneOffMicro: 0, conversion: `per-GB-month rate × GB ÷ ${hoursPerMonth}`};
    case 'one-off': return {hourlyMicro: 0, oneOffMicro: r * quantity, conversion: 'one-off charge, added in full at the start'};
    default: throw new LockError(`unknown billing period: ${JSON.stringify(period)}`, 'LOCK_VALUE');
  }
}

// Estimated consumption (micro-dollars) after elapsedSeconds. Never GPU compute alone: GPU at the higher of
// the recorded rate and the cap, plus the container disk, plus every extra resource (all hourly), plus one-offs.
export function estimateConsumptionMicro({lock, gpu, recordedGpuRate, elapsedSeconds, extraResources = []}) {
  const L = lock.limits, cap = usdToMicro(L.gpuRateCapUSDPerHour[gpu] ?? (() => { throw new LockError(`no rate cap for GPU ${JSON.stringify(gpu)}`, 'LOCK_VALUE'); })());
  const recorded = usdToMicro(recordedGpuRate);
  if (recorded > cap) throw new LockError(`recorded GPU rate ${recordedGpuRate} exceeds the approved cap ${L.gpuRateCapUSDPerHour[gpu]}`, 'RATE_CAP');
  const disk = normaliseHourly({rate: L.containerDiskUSDPerGBMonth, period: 'gb-month', quantity: lock.provider.containerDiskGB, hoursPerMonth: L.hoursPerMonthAssumption});
  let hourly = Math.max(recorded, cap) + disk.hourlyMicro, oneOff = 0;
  for (const r of extraResources) { const n = normaliseHourly({...r, hoursPerMonth: L.hoursPerMonthAssumption}); hourly += n.hourlyMicro; oneOff += n.oneOffMicro; }
  return {hourlyMicro: hourly, oneOffMicro: oneOff, estimateMicro: ceilDiv(elapsedSeconds * hourly, 3600) + oneOff};
}

// ---------------------------------------------------------------------------------------------------
// Lock shape. This checks structure and internal consistency only; it never judges whether values are approved.
const need = (cond, msg) => { if (!cond) throw new LockError(`experiment lock: ${msg}`); };
const isStr = v => typeof v === 'string' && v.length > 0;
export function validateLockShape(lock) {
  need(lock && typeof lock === 'object' && lock.schema === LOCK_SCHEMA, `schema must be ${LOCK_SCHEMA}`);
  need(lock.target?.assetType === 'character-pose' && /^[a-z0-9-]+\/[a-z0-9-]+$/.test(lock.target.assetKey || ''), 'target must name a character pose');
  for (const k of ['editInput', 'control']) need(isStr(lock.inputs?.[k]?.file) && SHA256_RE.test(lock.inputs[k].sha256), `inputs.${k} needs file and sha256`);
  need(Array.isArray(lock.models) && lock.models.length > 0, 'models must be a non-empty list');
  const saved = new Set();
  for (const m of lock.models) {
    need(['Q', 'S'].includes(m.workflow) && isStr(m.role) && /^[\w.-]+\/[\w.-]+$/.test(m.repo || ''), `model ${m.file}: workflow, role and repo are required`);
    need(COMMIT_RE.test(m.revision) && SHA256_RE.test(m.sha256), `model ${m.file}: revision and sha256 must be full hashes`);
    need(isStr(m.file) && !m.file.includes('..') && /^models\/[a-z_]+\/[\w.-]+$/.test(m.saveAs || ''), `model ${m.file}: file and saveAs must be safe relative paths`);
    need(!saved.has(m.saveAs), `model ${m.file}: duplicate saveAs`); saved.add(m.saveAs);
    need(isStr(m.licence) && /^\d+\.\d{2}$/.test(m.sizeGB || ''), `model ${m.file}: licence and sizeGB are required`);
  }
  for (const k of ['comfyui', 'ipadapterPlus']) need(/^https:\/\/github\.com\/[\w.-]+\/[\w.-]+$/.test(lock.software?.[k]?.repo || '') && COMMIT_RE.test(lock.software[k].commit), `software.${k} needs an https repo and a full commit`);
  for (const k of ['Q', 'S']) {
    const w = lock.workflows?.[k];
    need(w && Number.isInteger(w.width) && Number.isInteger(w.height) && Number.isInteger(w.steps) && isStr(w.cfg) && isStr(w.sampler) && isStr(w.scheduler), `workflows.${k}: size, steps, cfg, sampler and scheduler are required`);
    need(isStr(w.prompt) && typeof w.negativePrompt === 'string' && w.batchSize === 1, `workflows.${k}: prompt, negativePrompt and batchSize 1 are required`);
  }
  for (const id of CANDIDATE_IDS) need(['Q', 'S'].includes(lock.candidates?.[id]?.workflow) && Number.isSafeInteger(lock.candidates[id].seed), `candidates.${id} needs workflow and seed`);
  need(Object.keys(lock.candidates).length === CANDIDATE_IDS.length, 'exactly three candidates (A, B, C)');
  const P = lock.provider, L = lock.limits;
  need(isStr(P?.name) && isStr(P.cloud) && isStr(P.gpuPrimary) && isStr(P.gpuFallback) && Number.isInteger(P.containerDiskGB), 'provider is incomplete');
  need(L && [L.depositUSD, L.consumptionCeilingUSD, L.watchdogEstimateStopUSD, L.containerDiskUSDPerGBMonth, L.reconciliationToleranceUSD].every(v => { usdToMicro(v); return true; }), 'limits: dollar values must be decimal strings');
  for (const g of [P.gpuPrimary, P.gpuFallback]) usdToMicro(L.gpuRateCapUSDPerHour?.[g]);
  need(usdToMicro(L.watchdogEstimateStopUSD) < usdToMicro(L.consumptionCeilingUSD) && usdToMicro(L.consumptionCeilingUSD) <= usdToMicro(L.depositUSD), 'limits: stop threshold < ceiling <= deposit');
  const M = L.milestoneSeconds;
  need(M && M.noNewGeneration < M.transfersComplete && M.transfersComplete < M.timerAlert && M.timerAlert < M.watchdogStop && M.watchdogStop < M.manualStop && M.manualStop < M.absoluteLimit, 'limits: milestones must be strictly increasing');
  need(M.absoluteLimit === L.maxRuntimeSeconds, 'limits: the absolute milestone must equal maxRuntimeSeconds');
  need(Number.isInteger(L.hoursPerMonthAssumption) && Number.isInteger(L.consoleCheckpointSeconds), 'limits: hoursPerMonthAssumption and consoleCheckpointSeconds are required');
  return lock;
}

// Load the lock. With requireApproved (the default for every tool) an unapproved lock is refused.
// lockFile and decisionsFile are overridden only by tests (fixture lock and fixture decision record).
export function loadLock({lockFile = LOCK_FILE, decisionsFile = DECISIONS_FILE, requireApproved = true} = {}) {
  const text = fs.readFileSync(lockFile);
  const lock = validateLockShape(parseStrictJson(text));
  const sha256 = canonicalHash(text);
  const approvals = readApprovals(fs.existsSync(decisionsFile) ? fs.readFileSync(decisionsFile, 'utf8') : '');
  const approved = approvals.isApproved(sha256);
  if (requireApproved && !approved) {
    throw new LockError(`experiment lock ${sha256} is not recorded as owner-approved in ${path.basename(decisionsFile)} `
      + '(expected a line AP-84B3-LOCK-APPROVED-SHA256=<hash>, written only after the owner\'s explicit review). Nothing was run.', 'LOCK_NOT_APPROVED');
  }
  return {lock, sha256, approved, revoked: approvals.revoked.has(sha256)};
}

export const modelDownloadUrl = m => `https://huggingface.co/${m.repo}/resolve/${m.revision}/${m.file}`;
export const gpuCap = (lock, gpu) => lock.limits.gpuRateCapUSDPerHour[gpu];

// ---------------------------------------------------------------------------------------------------
// Run sheet: one record per run, filled in during execution. validateRunSheet returns a list of problems
// (empty = valid) and checks every frozen value against the lock.
export function validateRunSheet(sheet, lock, lockSha256) {
  const p = [];
  const bad = m => p.push(m);
  if (!sheet || typeof sheet !== 'object') return ['run sheet is not an object'];
  if (sheet.schema !== RUN_SHEET_SCHEMA) bad(`schema must be ${RUN_SHEET_SCHEMA}`);
  if (!RUN_ID_RE.test(sheet.runId || '')) bad('runId must look like r-YYYYMMDD-HHMMSS');
  if (sheet.lockSha256 !== lockSha256) bad('lockSha256 does not match the approved experiment lock');
  const pod = sheet.pod || {};
  if (pod.provider !== lock.provider.name || pod.cloud !== lock.provider.cloud) bad('pod.provider and pod.cloud must match the approved provider');
  if (![lock.provider.gpuPrimary, lock.provider.gpuFallback].includes(pod.gpu)) bad('pod.gpu must be the approved primary or fallback GPU');
  else {
    try { if (usdToMicro(pod.gpuRateUSDPerHour) > usdToMicro(gpuCap(lock, pod.gpu))) bad('pod.gpuRateUSDPerHour exceeds the approved rate cap'); }
    catch { bad('pod.gpuRateUSDPerHour must be a decimal string'); }
  }
  for (const k of ['startedAt', 'endedAt']) if (!isStr(pod[k]) || Number.isNaN(Date.parse(pod[k]))) bad(`pod.${k} must be a timestamp`);
  if (!p.some(x => x.startsWith('pod.startedAt') || x.startsWith('pod.endedAt')) && Date.parse(pod.endedAt) - Date.parse(pod.startedAt) > lock.limits.maxRuntimeSeconds * 1000) bad('pod runtime exceeds the approved limit');
  if (sheet.software?.comfyuiCommit !== lock.software.comfyui.commit) bad('software.comfyuiCommit does not match the pin');
  if (sheet.software?.ipadapterCommit !== lock.software.ipadapterPlus.commit) bad('software.ipadapterCommit does not match the pin');
  for (const w of ['Q', 'S']) if (!SHA256_RE.test(sheet.workflows?.[w]?.apiSha256 || '')) bad(`workflows.${w}.apiSha256 must be recorded before any candidate`);
  const cands = sheet.candidates || {};
  if (Object.keys(cands).sort().join() !== CANDIDATE_IDS.join()) bad('candidates must be exactly A, B and C');
  for (const id of CANDIDATE_IDS) {
    const c = cands[id]; if (!c) continue;
    const L = lock.candidates[id];
    if (c.workflow !== L.workflow || c.seed !== L.seed) bad(`candidate ${id}: workflow or seed differs from the lock`);
    if (!['retained', 'lost', 'not-generated'].includes(c.status)) bad(`candidate ${id}: status must be retained, lost or not-generated`);
    if (c.status === 'retained') for (const f of ['raw', 'cutout']) {
      const x = c[f] || {};
      if (!OUTPUT_NAME_RE.test(x.name || '') || !x.name.endsWith('.png') || !SHA256_RE.test(x.sha256 || '') || !Number.isInteger(x.bytes) || x.bytes < 1) bad(`candidate ${id}: ${f} needs a safe .png name, sha256 and bytes`);
    }
  }
  if (!Array.isArray(sheet.smoke)) bad('smoke must be a list (empty if no smoke run was made)');
  else {
    for (const s of sheet.smoke) if (!['Q', 'S'].includes(s?.workflow) || !SHA256_RE.test(s?.sha256 || '')) bad('each smoke entry needs workflow and sha256');
    for (const w of ['Q', 'S']) if (sheet.smoke.filter(s => s?.workflow === w).length > lock.smoke.maxPerWorkflow) bad(`more than ${lock.smoke.maxPerWorkflow} smoke run for workflow ${w}`);
  }
  return p;
}

// Provenance stored with an imported candidate (specification §6.6). Everything comes from the lock and the run sheet.
export function buildProvenance({lock, lockSha256, sheet, candidate, transfer}) {
  const L = lock.candidates[candidate], c = sheet.candidates[candidate], w = lock.workflows[L.workflow];
  return {
    adapter: 'import', synthetic: false, experiment: lock.experiment, candidate, runId: sheet.runId, lockSha256,
    workflow: {id: L.workflow, name: w.name, apiSha256: sheet.workflows[L.workflow].apiSha256,
      settings: Object.fromEntries(Object.entries(w).filter(([k]) => !['prompt', 'negativePrompt', 'name'].includes(k)))},
    prompt: w.prompt, negativePrompt: w.negativePrompt, seed: L.seed,
    models: lock.models.filter(m => m.workflow === L.workflow).map(m => ({role: m.role, repo: m.repo, revision: m.revision, file: m.file, sizeGB: m.sizeGB, sha256: m.sha256, licence: m.licence})),
    software: {comfyui: lock.software.comfyui.commit, ipadapterPlus: lock.software.ipadapterPlus.commit},
    input: {id: lock.inputs.editInput.id, sha256: lock.inputs.editInput.sha256},
    pod: {provider: sheet.pod.provider, cloud: sheet.pod.cloud, gpu: sheet.pod.gpu, region: sheet.pod.region ?? null, startedAt: sheet.pod.startedAt, endedAt: sheet.pod.endedAt, gpuRateUSDPerHour: sheet.pod.gpuRateUSDPerHour},
    raw: {name: c.raw.name, sha256: c.raw.sha256, bytes: c.raw.bytes},
    cutout: {name: c.cutout.name, sha256: c.cutout.sha256, bytes: c.cutout.bytes},
    transfer: {manifestSha256: transfer.manifestSha256, verifiedAt: transfer.verifiedAt},
  };
}

export const sha256File = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
export const sha256Buffer = b => crypto.createHash('sha256').update(b).digest('hex');
const PNG_SIG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
// Width and height from the PNG header, or null if the bytes are not a PNG.
export function pngSize(buf) {
  if (!Buffer.isBuffer(buf) || buf.length < 33 || !buf.subarray(0, 8).equals(PNG_SIG) || buf.toString('latin1', 12, 16) !== 'IHDR') return null;
  return {width: buf.readUInt32BE(16), height: buf.readUInt32BE(20)};
}
// True if `child` is the same as, or inside, `parent` (after resolving symlinks where the paths exist).
export function isInside(child, parent) {
  const real = p => { try { return fs.realpathSync(p); } catch { return path.resolve(p); } };
  const c = real(child), r = real(parent);
  const rel = path.relative(r, c);
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}
