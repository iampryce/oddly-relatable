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
export const ENVIRONMENT_FILE = path.join(REPO_ROOT, 'studio', 'config', 'ap84b3-environment.json');
export const ENVIRONMENT_SCHEMA = 'ap84b3-environment/1';
export const LOCK_SCHEMA = 'ap84b3-experiment-lock/1';
export const RUN_SHEET_SCHEMA = 'ap84b3-run-sheet/1';
export const TRANSFER_SCHEMA = 'ap84b3-transfer-verified/1';
export const MANIFEST_HEADER = '# ap84b3-manifest/1';
export const RESOURCES_HEADER = '# ap84b3-resources/1';
export const CANDIDATE_IDS = Object.freeze(['A', 'B', 'C']);
export const TRANSFER_IDS = Object.freeze(['A', 'B', 'C', 'smoke']);     // smoke outputs travel separately and are never candidates
export const SMOKE_NAME_RE = /^smoke-([qs])\.png$/;
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
  // Smoke run: fixed settings and a seed that no candidate uses.
  const sm = lock.smoke;
  need(sm && sm.maxPerWorkflow === 1 && sm.neverACandidate === true && [sm.width, sm.height, sm.steps].every(v => Number.isInteger(v) && v > 0), 'smoke needs width, height, steps, maxPerWorkflow 1 and neverACandidate');
  need(Number.isSafeInteger(sm.seed) && sm.seed >= 0, 'smoke.seed must be a non-negative integer');
  need(!Object.values(lock.candidates).some(c => c.seed === sm.seed), 'the smoke seed must differ from every candidate seed');
  // Pinned sampling and node settings (lock amendment).
  for (const k of ['Q', 'S']) need(/^\d+\.\d+$/.test(lock.workflows[k].denoise || '') && isStr(lock.workflows[k].latentNode), `workflows.${k}: denoise and latentNode are required`);
  const WQ = lock.workflows.Q, WS = lock.workflows.S;
  need(WQ.inputScaling === 'none' && WQ.shift === 'recorded-at-export', 'workflows.Q: inputScaling must be "none" and shift "recorded-at-export"');
  need(/^compatibility-gate: unverified/.test(WQ.latentNodeStatus || ''), 'workflows.Q.latentNodeStatus must record the latent node as an unverified compatibility gate');
  need(WS.promptEncoder === 'CLIPTextEncode' && isStr(WS.ipAdapter?.loader) && isStr(WS.ipAdapter.imageEncoderLoader) && isStr(WS.ipAdapter.combineEmbeds) && isStr(WS.ipAdapter.embedsScaling), 'workflows.S: prompt encoder, loaders and IP-Adapter options are required');
  need(WS.ipAdapter.imageNegative === 'none' && WS.ipAdapter.attnMask === 'none' && WS.rawOutputRetained === true, 'workflows.S: no negative image, no attention mask, raw output retained');
  const R = WS.reference;
  need(R && R.source === lock.inputs.editInput.id && R.preparedLocally === true && R.placement === 'centred' && Number.isInteger(R.canvasWidth) && Number.isInteger(R.canvasHeight) && SHA256_RE.test(R.sha256 || ''), 'workflows.S.reference is incomplete');
  need(Array.isArray(R.padColourRGB) && R.padColourRGB.length === 3 && R.padColourRGB.every(v => Number.isInteger(v) && v >= 0 && v <= 255), 'workflows.S.reference.padColourRGB must be three integers from 0 to 255');
  for (const k of ['Q', 'S']) validateGraphConstraints(lock, k);
  const P = lock.provider, L = lock.limits;
  need(isStr(P?.name) && isStr(P.cloud) && isStr(P.gpuPrimary) && isStr(P.gpuFallback) && Number.isInteger(P.containerDiskGB), 'provider is incomplete');
  need(L && [L.depositUSD, L.consumptionCeilingUSD, L.watchdogEstimateStopUSD, L.containerDiskUSDPerGBMonth, L.reconciliationToleranceUSD].every(v => { usdToMicro(v); return true; }), 'limits: dollar values must be decimal strings');
  for (const g of [P.gpuPrimary, P.gpuFallback]) usdToMicro(L.gpuRateCapUSDPerHour?.[g]);
  need(usdToMicro(L.watchdogEstimateStopUSD) < usdToMicro(L.consumptionCeilingUSD) && usdToMicro(L.consumptionCeilingUSD) <= usdToMicro(L.depositUSD), 'limits: stop threshold < ceiling <= deposit');
  const M = L.milestoneSeconds;
  need(M && M.noNewGeneration < M.transfersComplete && M.transfersComplete < M.timerAlert && M.timerAlert < M.watchdogStop && M.watchdogStop < M.manualStop && M.manualStop < M.absoluteLimit, 'limits: milestones must be strictly increasing');
  need(M.absoluteLimit === L.maxRuntimeSeconds, 'limits: the absolute milestone must equal maxRuntimeSeconds');
  need(Number.isInteger(L.hoursPerMonthAssumption) && Number.isInteger(L.consoleCheckpointSeconds), 'limits: hoursPerMonthAssumption and consoleCheckpointSeconds are required');
  need(L.cumulativeAcrossSessions === true, 'limits: the ceiling, runtime and deposit must be cumulative across sessions');
  return lock;
}

// ---------------------------------------------------------------------------------------------------
// Workflow graph constraints (Layer 1). The lock lists one entry per node (role, type, literal settings) and the
// connections between roles. Literal settings are not duplicated: each points at the lock field that holds the
// approved value. This is NOT the API export graph; that is inspected and frozen during authorised execution.
export function lockValue(lock, dotPath) {
  let v = lock;
  for (const k of dotPath.split('.')) { if (v === null || typeof v !== 'object' || !(k in v)) throw new LockError(`experiment lock: no value at ${dotPath}`, 'LOCK_VALUE'); v = v[k]; }
  return v;
}
// What a literal setting must be. ctx: {seed, smoke}. Returns {kind: 'value', value, optional} | {kind: 'record', name} | {kind: 'free'}.
export function resolveLiteral(lock, workflow, s, ctx = {}) {
  if (!s || typeof s !== 'object' || Array.isArray(s)) throw new LockError('graph constraint: a literal setting must be an object', 'LOCK_VALUE');
  if (isStr(s.free)) return {kind: 'free', reason: s.free};
  if (isStr(s.record)) return {kind: 'record', name: s.record};
  if (s.seed === true) return {kind: 'value', value: ctx.seed, optional: false};
  if (isStr(s.model)) {
    const m = lock.models.find(x => x.workflow === workflow && x.role === s.model);
    if (!m) throw new LockError(`graph constraint: no model with role ${s.model} in workflow ${workflow}`, 'LOCK_VALUE');
    return {kind: 'value', value: m.saveAs.split('/').pop(), optional: false};
  }
  if (isStr(s.ref)) {
    const raw = lockValue(lock, ctx.smoke && isStr(s.smoke) ? s.smoke : s.ref);
    let value;
    if (s.type === 'string') { if (typeof raw !== 'string') throw new LockError(`graph constraint: ${s.ref} is not a string`, 'LOCK_VALUE'); value = raw; }
    else if (s.type === 'integer') { if (!Number.isSafeInteger(raw)) throw new LockError(`graph constraint: ${s.ref} is not an integer`, 'LOCK_VALUE'); value = raw; }
    else if (s.type === 'number') { if (typeof raw !== 'string' || !/^\d+(\.\d+)?$/.test(raw)) throw new LockError(`graph constraint: ${s.ref} is not a decimal string`, 'LOCK_VALUE'); value = Number(raw); }
    else if (s.type === 'boolean') { if (raw !== 'true' && raw !== 'false') throw new LockError(`graph constraint: ${s.ref} is not "true" or "false"`, 'LOCK_VALUE'); value = raw === 'true'; }
    else throw new LockError(`graph constraint: unknown type for ${s.ref}`, 'LOCK_VALUE');
    return {kind: 'value', value, optional: s.optional === true};
  }
  throw new LockError('graph constraint: unrecognised literal setting', 'LOCK_VALUE');
}
export function validateGraphConstraints(lock, workflow) {
  const G = lock.workflows[workflow].graphConstraints, where = `workflows.${workflow}.graphConstraints`;
  need(G && G.closedWorld === true && Array.isArray(G.nodes) && G.nodes.length > 0 && Array.isArray(G.connections), `${where} needs closedWorld, nodes and connections`);
  const roles = new Map();
  for (const n of G.nodes) {
    need(isStr(n.role) && isStr(n.type) && n.literals && typeof n.literals === 'object' && !roles.has(n.role), `${where}: every node needs a unique role, a type and literals`);
    roles.set(n.role, n);
    for (const s of Object.values(n.literals)) for (const smoke of [false, true]) resolveLiteral(lock, workflow, s, {seed: 0, smoke});
  }
  const targets = new Set();
  for (const c of G.connections) {
    need(roles.has(c.from) && roles.has(c.to) && isStr(c.input), `${where}: a connection names an unknown role`);
    need(!targets.has(`${c.to}.${c.input}`) && !(c.input in roles.get(c.to).literals), `${where}: input ${c.to}.${c.input} is defined twice`);
    targets.add(`${c.to}.${c.input}`);
  }
  need(G.nodes.filter(n => n.type === lock.workflows[workflow].latentNode).length === 1, `${where}: exactly one latent node of the pinned type`);
  need(G.nodes.filter(n => n.type === 'KSampler').length === 1, `${where}: exactly one sampler`);
  need(!G.nodes.some(n => /lora|controlnet|FluxKontextImageScale|VAEEncode|UnifiedLoader|PrepImageForClipVision/i.test(n.type)), `${where}: a forbidden node type is listed`);
  return G;
}

// Limits that remain after earlier Pod sessions. The ceiling, the runtime and the deposit are cumulative across
// the whole experiment: a failed session does not reset them, and no further funding is authorised.
// priorSessions: [{startedAt, endedAt, consumedUSD}]. consumedUSD is the higher of the balance and usage methods.
export function remainingLimits(lock, priorSessions = []) {
  const L = lock.limits, M = L.milestoneSeconds;
  let seconds = 0, consumed = 0;
  for (const p of priorSessions) {
    const a = Date.parse(p?.startedAt), b = Date.parse(p?.endedAt);
    if (Number.isNaN(a) || Number.isNaN(b) || b < a) throw new LockError('prior session needs valid startedAt and endedAt', 'LOCK_VALUE');
    seconds += Math.ceil((b - a) / 1000);
    consumed += usdToMicro(p.consumedUSD);
  }
  const out = {
    priorRuntimeSeconds: seconds, priorConsumedUSD: microToUsd(consumed),
    remainingRuntimeSeconds: M.absoluteLimit - seconds,
    watchdogStopSeconds: M.watchdogStop - seconds,
    noNewGenerationSeconds: M.noNewGeneration - seconds,
    estimateStopMicro: usdToMicro(L.watchdogEstimateStopUSD) - consumed,
    remainingCeilingMicro: usdToMicro(L.consumptionCeilingUSD) - consumed,
    additionalFunding: 'none',
  };
  // A new session needs room for at least one generation before the cut-off and a positive estimate margin.
  out.sessionAllowed = out.noNewGenerationSeconds > 0 && out.watchdogStopSeconds > out.noNewGenerationSeconds && out.estimateStopMicro > 0;
  out.estimateStopUSD = out.estimateStopMicro > 0 ? microToUsd(out.estimateStopMicro) : '0.000000';
  return out;
}

// Local pre-session check: would these watchdog settings silently reset the cumulative limits?
// The watchdog's own defaults are the FULL approved limits. After an earlier session those defaults are too
// generous, so every limit must be set explicitly and must not exceed what remains. `env` is the set of WD_*
// settings the operator intends to start the watchdog with. This check runs on the local machine before a
// session; it cannot force the watchdog on the Pod to use the values (see the open proposal in NEXT_STEPS.md).
export function checkSessionSettings(lock, priorSessions = [], env = {}) {
  const r = remainingLimits(lock, priorSessions), problems = [];
  const required = {WD_STOP_SECONDS: String(Math.max(r.watchdogStopSeconds, 0)), WD_NO_NEW_GENERATION_SECONDS: String(Math.max(r.noNewGenerationSeconds, 0)), WD_ESTIMATE_STOP_USD: r.estimateStopUSD};
  if (!r.sessionAllowed) problems.push('no further session is allowed: the cumulative runtime or the estimate margin is used up. Return to the owner');
  if (env.WD_TEST_MODE !== undefined && env.WD_TEST_MODE !== '') problems.push('WD_TEST_MODE must not be set for a real session');
  const M = lock.limits.milestoneSeconds;
  const given = {
    WD_STOP_SECONDS: [env.WD_STOP_SECONDS, M.watchdogStop, r.watchdogStopSeconds, v => /^\d+$/.test(v) ? Number(v) : null],
    WD_NO_NEW_GENERATION_SECONDS: [env.WD_NO_NEW_GENERATION_SECONDS, M.noNewGeneration, r.noNewGenerationSeconds, v => /^\d+$/.test(v) ? Number(v) : null],
    WD_ESTIMATE_STOP_USD: [env.WD_ESTIMATE_STOP_USD, usdToMicro(lock.limits.watchdogEstimateStopUSD), r.estimateStopMicro, v => { try { return usdToMicro(v); } catch { return null; } }],
  };
  for (const [name, [value, fullLimit, remaining, parse]] of Object.entries(given)) {
    if (value === undefined || value === '') {
      // Not set: the watchdog would use the full approved limit. That is only right when nothing has been used yet.
      if (priorSessions.length > 0 || fullLimit > remaining) problems.push(`${name} is not set, so the watchdog would use the full limit and the earlier sessions would not count. Set it to ${required[name]}`);
      continue;
    }
    const n = parse(String(value));
    if (n === null) problems.push(`${name} is not a valid value`);
    else if (n > remaining) problems.push(`${name} is ${value}, above what remains after the earlier sessions (${required[name]})`);
  }
  return {ok: problems.length === 0, problems, required, remaining: r};
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
  // Cumulative limits: every Pod session of the experiment counts, including failed ones.
  const micro = v => { try { return usdToMicro(v); } catch { return null; } };
  let runtimeMs = 0, consumed = 0, sessionsOk = !p.some(x => x.startsWith('pod.startedAt') || x.startsWith('pod.endedAt'));
  if (sessionsOk) { runtimeMs = Date.parse(pod.endedAt) - Date.parse(pod.startedAt); if (runtimeMs < 0) { bad('pod.endedAt is before pod.startedAt'); sessionsOk = false; } }
  if (micro(pod.consumedUSD) === null) { bad('pod.consumedUSD must be a decimal string (the higher of the balance and usage methods)'); sessionsOk = false; } else consumed += micro(pod.consumedUSD);
  if (!Array.isArray(sheet.priorSessions)) { bad('priorSessions must be a list (empty if this was the only Pod session)'); sessionsOk = false; }
  else for (const s of sheet.priorSessions) {
    const a = Date.parse(s?.startedAt), b = Date.parse(s?.endedAt);
    if (Number.isNaN(a) || Number.isNaN(b) || b < a || micro(s?.consumedUSD) === null || !isStr(s?.reason)) { bad('each prior session needs startedAt, endedAt, consumedUSD and reason'); sessionsOk = false; continue; }
    if (![lock.provider.gpuPrimary, lock.provider.gpuFallback].includes(s.gpu)) bad('a prior session used a GPU that is not approved');
    runtimeMs += b - a; consumed += micro(s.consumedUSD);
  }
  if (sessionsOk && runtimeMs > lock.limits.maxRuntimeSeconds * 1000) bad('total Pod runtime across all sessions exceeds the approved limit');
  if (sessionsOk && consumed > usdToMicro(lock.limits.consumptionCeilingUSD)) bad('total consumption across all sessions exceeds the approved ceiling');
  if (sheet.software?.comfyuiCommit !== lock.software.comfyui.commit) bad('software.comfyuiCommit does not match the pin');
  if (sheet.software?.ipadapterCommit !== lock.software.ipadapterPlus.commit) bad('software.ipadapterCommit does not match the pin');
  const cands = sheet.candidates || {};
  // A workflow that produced a retained candidate must have been frozen: its export hash and frozen graph hash are recorded.
  for (const w of ['Q', 'S']) {
    const used = CANDIDATE_IDS.some(id => lock.candidates[id].workflow === w && cands[id]?.status === 'retained');
    for (const k of ['apiSha256', 'graphSha256']) {
      const v = sheet.workflows?.[w]?.[k];
      if (used ? !SHA256_RE.test(v || '') : (v !== undefined && !SHA256_RE.test(v || ''))) bad(`workflows.${w}.${k} must be recorded before any candidate`);
    }
  }
  if (!SHA256_RE.test(sheet.ledgerHead || '')) bad('ledgerHead must be the hash of the newest session-ledger entry');
  if (Object.keys(cands).sort().join() !== CANDIDATE_IDS.join()) bad('candidates must be exactly A, B and C');
  for (const id of CANDIDATE_IDS) {
    const c = cands[id]; if (!c) continue;
    const L = lock.candidates[id];
    if (c.workflow !== L.workflow || c.seed !== L.seed) bad(`candidate ${id}: workflow or seed differs from the lock`);
    if (!['retained', 'lost', 'not-generated'].includes(c.status)) bad(`candidate ${id}: status must be retained, lost or not-generated`);
    if (c.status === 'retained') for (const f of ['raw', 'cutout']) {
      const x = c[f] || {};
      if (!OUTPUT_NAME_RE.test(x.name || '') || !x.name.endsWith('.png') || !SHA256_RE.test(x.sha256 || '') || !Number.isInteger(x.bytes) || x.bytes < 1) bad(`candidate ${id}: ${f} needs a safe .png name, sha256 and bytes`);
      else if (/smoke/.test(x.name)) bad(`candidate ${id}: ${f} is named as a smoke image; smoke images are never candidates`);
    }
  }
  // Smoke runs: fixed seed, size and steps from the lock; at most one per workflow; never a candidate.
  if (!Array.isArray(sheet.smoke)) bad('smoke must be a list (empty if no smoke run was made)');
  else {
    const S = lock.smoke;
    for (const s of sheet.smoke) {
      const m = SMOKE_NAME_RE.exec(s?.name || '');
      if (!['Q', 'S'].includes(s?.workflow) || !SHA256_RE.test(s?.sha256 || '') || !m || m[1] !== String(s.workflow).toLowerCase()) { bad('each smoke entry needs workflow, sha256 and the name smoke-q.png or smoke-s.png'); continue; }
      if (s.seed !== S.seed) bad(`smoke ${s.workflow}: seed differs from the lock's smoke seed`);
      if (s.width !== S.width || s.height !== S.height || s.steps !== S.steps) bad(`smoke ${s.workflow}: size or steps differ from the lock`);
      for (const id of CANDIDATE_IDS) for (const f of ['raw', 'cutout']) if (cands[id]?.[f]?.sha256 === s.sha256) bad(`candidate ${id}: ${f} is a smoke image; smoke images are never candidates`);
    }
    for (const w of ['Q', 'S']) if (sheet.smoke.filter(s => s?.workflow === w).length > S.maxPerWorkflow) bad(`more than ${S.maxPerWorkflow} smoke run for workflow ${w}`);
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

// ---------------------------------------------------------------------------------------------------
// Environment lock (owner decision A5: Option A, two tiers). A separate file from the experiment lock, so the
// approved experiment lock hash is not affected. Approved only when its canonical SHA-256 is recorded in
// DECISIONS.md as  AP-84B3-ENVIRONMENT-APPROVED-SHA256=<hex>  after the owner's review.
const ENV_APPROVED_RE = /AP-84B3-ENVIRONMENT-APPROVED-SHA256=([0-9a-f]{64})/g;
const ENV_REVOKED_RE = /AP-84B3-ENVIRONMENT-REVOKED-SHA256=([0-9a-f]{64})/g;
export function validateEnvironmentShape(env, lock) {
  const n = (c, m) => { if (!c) throw new LockError(`environment lock: ${m}`, 'ENV_INVALID'); };
  n(env && env.schema === ENVIRONMENT_SCHEMA, `schema must be ${ENVIRONMENT_SCHEMA}`);
  const I = env.image || {};
  n(/^[a-z0-9]+(\/[a-z0-9._-]+)+:[A-Za-z0-9._-]+$/.test(I.reference || ''), 'image.reference must be a tagged image name');
  n(/^sha256:[0-9a-f]{64}$/.test(I.digest || '') && /^sha256:[0-9a-f]{64}$/.test(I.configDigest || ''), 'image.digest and image.configDigest must be sha256 digests');
  n(I.deployAs === `${I.reference.split(':')[0]}@${I.digest}`, 'image.deployAs must be the repository pinned by digest');
  n(I.platform === 'linux/amd64' && I.fingerprint && isStr(I.fingerprint.CUDA_VERSION) && isStr(I.fingerprint.NV_CUDNN_VERSION), 'image.platform and image.fingerprint are required');
  const T = env.tier1 || {};
  n(/^3\.\d+$/.test(T.python || ''), 'tier1.python must look like 3.12');
  for (const k of ['torch', 'torchvision', 'torchaudio']) n(/^\d+\.\d+\.\d+\+cu\d+$/.test(T[k] || ''), `tier1.${k} must be an exact version with its CUDA build, e.g. 2.13.0+cu130`);
  n(/^\d+\.\d+$/.test(T.torchCuda || ''), 'tier1.torchCuda must look like 13.0');
  n(SHA256_RE.test(T.comfyuiRequirementsSha256 || ''), 'tier1.comfyuiRequirementsSha256 must be a SHA-256');
  n(Array.isArray(env.installConstraints) && ['torch', 'torchvision', 'torchaudio'].every(k => env.installConstraints.includes(`${k}==${T[k]}`)), 'installConstraints must pin torch, torchvision and torchaudio to the tier 1 versions');
  n(env.installConstraints.every(c => /^[a-z0-9_-]+==[A-Za-z0-9.+_-]+$/.test(c)), 'installConstraints must be exact pins');
  n(Array.isArray(env.tier2?.launchOptions) && env.tier2.launchOptions.every(o => typeof o === 'string' && !/[\s;&|$`]/.test(o)), 'tier2.launchOptions must be plain arguments');
  const G = env.gpu || {};
  n(G.allowed && typeof G.allowed === 'object' && Number.isSafeInteger(G.minTotalMemoryBytes) && G.minTotalMemoryBytes > 0, 'gpu.allowed and gpu.minTotalMemoryBytes are required');
  const lockGpus = [lock.provider.gpuPrimary, lock.provider.gpuFallback].sort();
  n(JSON.stringify(Object.values(G.allowed).map(g => g.lockName).sort()) === JSON.stringify(lockGpus), 'gpu.allowed must name exactly the approved primary and fallback GPUs');
  for (const g of Object.values(G.allowed)) n(/^\d+\.\d+$/.test(g.computeCapability || ''), 'each GPU needs its compute capability');
  n(Number.isInteger(env.disk?.marginGB) && env.disk.marginGB >= 1, 'disk.marginGB is required');
  return env;
}
export function loadEnvironment({environmentFile = ENVIRONMENT_FILE, decisionsFile = DECISIONS_FILE, lock, requireApproved = true} = {}) {
  const text = fs.readFileSync(environmentFile);
  const env = validateEnvironmentShape(parseStrictJson(text), lock);
  const sha256 = canonicalHash(text);
  const d = fs.existsSync(decisionsFile) ? fs.readFileSync(decisionsFile, 'utf8') : '';
  const approved = new Set([...d.matchAll(ENV_APPROVED_RE)].map(m => m[1])), revoked = new Set([...d.matchAll(ENV_REVOKED_RE)].map(m => m[1]));
  const ok = approved.has(sha256) && !revoked.has(sha256);
  if (requireApproved && !ok) {
    throw new LockError(`environment lock ${sha256} is not recorded as owner-approved in ${path.basename(decisionsFile)} `
      + '(expected a line AP-84B3-ENVIRONMENT-APPROVED-SHA256=<hash>, written only after the owner\'s explicit review). Nothing was built.', 'ENV_NOT_APPROVED');
  }
  return {env, sha256, approved: ok};
}
