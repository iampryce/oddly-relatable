// AP-84B3 session ledger: the durable, chained record of the experiment's Pod sessions and workflow freezes.
//
// Why it exists. The owner's limits are cumulative across the whole experiment: $5.00 consumption, 3 hours of Pod
// runtime, one $10 deposit, no additional funding. A new Pod starts with an empty disk, so nothing on the Pod can
// know about earlier sessions unless it is told. The ledger is that memory. Each session is prepared from the
// ledger (which gives it only the allowance that remains), and closed into the ledger with its reported usage.
// The ledger also records each workflow's frozen graph, so a deleted or replaced frozen graph cannot be quietly
// re-created.
//
// Integrity. Every entry carries the hash of the entry before it, so an edited, reordered or removed entry in the
// middle breaks the chain. A sidecar file (ledger.head) holds the newest entry's number and hash, so a ledger cut
// short at the end is detected too. The chain is verified locally every time the ledger is read. The Pod receives
// only the sealed session file (session.env) derived from it, covered by the bundle checksums.
//
// LIMITS OF THIS CONTROL (stated plainly):
//   - It is a local record. Someone with access to the run folder who deliberately rewrites the ledger AND its
//     sidecar consistently is not stopped by the chain. The independent checks are the provider's own balance,
//     read by the operator in the console before each session (prepareSession refuses if the balance does not
//     match the ledger), and the single $10 deposit with auto-pay off.
//   - Consumption figures are entered by a person from the provider's console. No account API key is used, so this
//     tool cannot read billing itself and cannot guarantee a hard billing cap. Only the provider can.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {usdToMicro, microToUsd, isInside, REPO_ROOT, SHA256_RE, RUN_ID_RE} from './experiment-spec.mjs';

export const LEDGER_SCHEMA = 'ap84b3-ledger/1';
export const LEDGER_FILE = 'ledger.json';
export const LEDGER_HEAD_FILE = 'ledger.head';
export const SESSION_ENV_FILE = 'session.env';
export const frozenFileName = workflow => `frozen-${String(workflow).toLowerCase()}.json`;
const WORKFLOWS = ['Q', 'S'];
const sha = s => crypto.createHash('sha256').update(s).digest('hex');
const shaFile = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');

export class LedgerError extends Error {
  constructor(message, code = 'LEDGER_INVALID') { super(`session ledger: ${message}`); this.code = code; }
}

// The hash of one entry. Deliberately simple (no JSON canonicalisation), so the Pod-side check in
// verify-ledger.py computes exactly the same thing: sha256("seq|type|at|prevHash|sha256(dataJson)").
export const entryHash = e => sha(`${e.seq}|${e.type}|${e.at}|${e.prevHash}|${sha(e.dataJson)}`);
// The first entry is chained to the experiment lock, so a ledger cannot be moved to a different lock.
export const genesisHash = lockSha256 => sha(`ap84b3-ledger-genesis|${lockSha256}`);

function runFolder(runDir) {
  const run = path.resolve(runDir);
  if (!fs.existsSync(run) || fs.lstatSync(run).isSymbolicLink() || !fs.statSync(run).isDirectory()) throw new LedgerError('the run folder does not exist', 'RUN_FOLDER');
  if (isInside(run, REPO_ROOT)) throw new LedgerError('the run folder must be outside the repository', 'RUN_FOLDER');
  return run;
}
const secondsBetween = (a, b) => Math.ceil((Date.parse(b) - Date.parse(a)) / 1000);

// Replay the entries into the experiment's state, enforcing the allowed order of events.
function replay(entries, lock) {
  const st = {lockSha256: null, runId: null, funded: null, sessions: [], freezes: {Q: null, S: null}, revokedFreezes: [], overLimit: false};
  const fail = (e, m) => { throw new LedgerError(`entry ${e.seq} (${e.type}): ${m}`, 'LEDGER_ORDER'); };
  const open = () => st.sessions.find(s => s.status === 'prepared') || null;
  for (const e of entries) {
    const d = e.data;
    if (e.seq === 1 && e.type !== 'init') fail(e, 'the first entry must be "init"');
    switch (e.type) {
      case 'init':
        if (e.seq !== 1) fail(e, 'only the first entry may be "init"');
        if (!SHA256_RE.test(d.lockSha256 || '') || !RUN_ID_RE.test(d.runId || '')) fail(e, 'needs lockSha256 and runId');
        st.lockSha256 = d.lockSha256; st.runId = d.runId;
        break;
      case 'funded':
        if (st.funded) fail(e, 'funding is recorded only once: no additional deposit is authorised');
        if (usdToMicro(d.balanceAfterUSD) - usdToMicro(d.balanceBeforeUSD) !== usdToMicro(lock.limits.depositUSD)) fail(e, `the deposit must be exactly $${lock.limits.depositUSD}`);
        st.funded = {balanceBeforeUSD: d.balanceBeforeUSD, balanceAfterUSD: d.balanceAfterUSD, seq: e.seq};
        break;
      case 'session-prepared':
        if (!st.funded) fail(e, 'a session cannot be prepared before the deposit is recorded');
        if (open()) fail(e, 'the previous session has not been closed');
        if (d.session !== st.sessions.length + 1) fail(e, 'session numbers must be consecutive');
        st.sessions.push({number: d.session, status: 'prepared', prepared: d, preparedSeq: e.seq, preparedHash: e.hash, closed: null});
        break;
      case 'session-closed': {
        const s = open();
        if (!s || d.session !== s.number) fail(e, 'there is no prepared session with this number to close');
        if (!Number.isInteger(d.runtimeSeconds) || d.runtimeSeconds < 0) fail(e, 'runtimeSeconds must be a non-negative integer');
        usdToMicro(d.consumedUSD);
        s.status = 'closed'; s.closed = d; s.closedSeq = e.seq;
        break;
      }
      case 'freeze':
        if (!WORKFLOWS.includes(d.workflow)) fail(e, 'unknown workflow');
        if (st.freezes[d.workflow]) fail(e, `workflow ${d.workflow} is already frozen; a freeze is never replaced`);
        if (!open()) fail(e, 'a freeze can only be recorded during a prepared session');
        for (const k of ['graphSha256', 'apiSha256', 'fileSha256']) if (!SHA256_RE.test(d[k] || '')) fail(e, `needs ${k}`);
        st.freezes[d.workflow] = {...d, seq: e.seq, hash: e.hash};
        break;
      case 'freeze-recovery':
        if (!WORKFLOWS.includes(d.workflow) || typeof d.reason !== 'string' || d.reason.length < 3 || !SHA256_RE.test(d.approvedAgainstHead || '')) fail(e, 'needs workflow, reason and the ledger head the owner approved against');
        st.revokedFreezes.push({workflow: d.workflow, previous: st.freezes[d.workflow], seq: e.seq});
        st.freezes[d.workflow] = null;
        break;
      default: fail(e, 'unknown entry type');
    }
  }
  return st;
}

// Read and fully verify the ledger. Throws LedgerError on anything wrong; never returns a partly valid ledger.
export function readLedger(runDir, lock) {
  const run = runFolder(runDir), file = path.join(run, LEDGER_FILE), headFile = path.join(run, LEDGER_HEAD_FILE);
  if (!fs.existsSync(file)) throw new LedgerError('the ledger is missing from the run folder', 'LEDGER_MISSING');
  if (fs.lstatSync(file).isSymbolicLink()) throw new LedgerError('the ledger must not be a symbolic link');
  let doc;
  try { doc = JSON.parse(fs.readFileSync(file, 'utf8')); } catch { throw new LedgerError('the ledger is not readable JSON'); }
  if (!doc || doc.schema !== LEDGER_SCHEMA || !Array.isArray(doc.entries) || doc.entries.length === 0) throw new LedgerError('the ledger has no valid entries');
  let prev = null;
  const entries = doc.entries.map((e, i) => {
    if (!e || e.seq !== i + 1 || typeof e.type !== 'string' || typeof e.at !== 'string' || typeof e.dataJson !== 'string') throw new LedgerError(`entry ${i + 1} is malformed or out of order`, 'LEDGER_CHAIN');
    let data; try { data = JSON.parse(e.dataJson); } catch { throw new LedgerError(`entry ${e.seq} has unreadable data`, 'LEDGER_CHAIN'); }
    if (!data || typeof data !== 'object') throw new LedgerError(`entry ${e.seq} has unreadable data`, 'LEDGER_CHAIN');
    const expectPrev = i === 0 ? genesisHash(data.lockSha256) : prev;
    if (e.prevHash !== expectPrev) throw new LedgerError(`entry ${e.seq} does not follow the entry before it (a record was changed, removed or inserted)`, 'LEDGER_CHAIN');
    if (e.hash !== entryHash(e)) throw new LedgerError(`entry ${e.seq} has been altered (its hash does not match its content)`, 'LEDGER_CHAIN');
    prev = e.hash;
    return {...e, data};
  });
  const head = entries[entries.length - 1];
  let sidecar = null; try { sidecar = fs.readFileSync(headFile, 'utf8').trim(); } catch {}
  if (sidecar !== `${head.seq} ${head.hash}`) throw new LedgerError('the ledger does not end where its head record says (records are missing from the end, or the ledger was replaced)', 'LEDGER_HEAD');
  const state = replay(entries, lock);
  return {run, entries, head: {seq: head.seq, hash: head.hash}, state};
}

function write(run, entries) {
  const file = path.join(run, LEDGER_FILE), headFile = path.join(run, LEDGER_HEAD_FILE), head = entries[entries.length - 1];
  const body = JSON.stringify({schema: LEDGER_SCHEMA, entries: entries.map(({seq, type, at, dataJson, prevHash, hash}) => ({seq, type, at, dataJson, prevHash, hash}))}, null, 1) + '\n';
  for (const [target, text] of [[file, body], [headFile, `${head.seq} ${head.hash}\n`]]) {
    const tmp = `${target}.tmp-${process.pid}`;
    const fd = fs.openSync(tmp, 'w');
    try { fs.writeSync(fd, text); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    fs.renameSync(tmp, target);
  }
}
function append(runDir, lock, type, data, now = new Date()) {
  const led = readLedger(runDir, lock);
  const e = {seq: led.head.seq + 1, type, at: now.toISOString(), dataJson: JSON.stringify(data), prevHash: led.head.hash};
  e.hash = entryHash(e);
  const entries = [...led.entries, {...e, data}];
  replay(entries, lock);                                           // refuse an event that is out of order before writing it
  write(led.run, entries);
  return readLedger(runDir, lock);
}

// Start a ledger in a new run folder. Refuses a folder that already holds a ledger or any run output.
export function initLedger({runDir, lock, lockSha256, runId, now = new Date()}) {
  const run = runFolder(runDir);
  if (!SHA256_RE.test(lockSha256 || '') || !RUN_ID_RE.test(runId || '')) throw new LedgerError('needs the lock hash and a run id like r-YYYYMMDD-HHMMSS');
  for (const n of [LEDGER_FILE, LEDGER_HEAD_FILE, 'transfers', 'imported', 'run-sheet.json', ...WORKFLOWS.map(frozenFileName)]) {
    if (fs.existsSync(path.join(run, n))) throw new LedgerError(`the run folder already contains ${n}; a ledger is started only in a new run folder`, 'LEDGER_EXISTS');
  }
  const data = {lockSha256, runId};
  const e = {seq: 1, type: 'init', at: now.toISOString(), dataJson: JSON.stringify(data), prevHash: genesisHash(lockSha256)};
  e.hash = entryHash(e);
  replay([{...e, data}], lock);
  write(run, [e]);
  return readLedger(runDir, lock);
}

// Record the single deposit: the balance immediately before and immediately after it.
export function recordFunding({runDir, lock, balanceBeforeUSD, balanceAfterUSD, now}) {
  return append(runDir, lock, 'funded', {balanceBeforeUSD, balanceAfterUSD}, now);
}

// Runtime and consumption already used by closed sessions.
export function totals(state) {
  let runtimeSeconds = 0, consumedMicro = 0;
  for (const s of state.sessions) if (s.status === 'closed') { runtimeSeconds += s.closed.runtimeSeconds; consumedMicro += usdToMicro(s.closed.consumedUSD); }
  return {runtimeSeconds, consumedMicro, consumedUSD: microToUsd(consumedMicro)};
}
// What the next session may use: only what remains. Never a fresh full allowance.
export function allowance(lock, state) {
  const L = lock.limits, M = L.milestoneSeconds, t = totals(state);
  const a = {
    priorRuntimeSeconds: t.runtimeSeconds, priorConsumedMicro: t.consumedMicro, priorConsumedUSD: t.consumedUSD,
    remainingRuntimeSeconds: M.absoluteLimit - t.runtimeSeconds,
    watchdogStopSecondsRemaining: M.watchdogStop - t.runtimeSeconds,
    noNewGenerationSecondsRemaining: M.noNewGeneration - t.runtimeSeconds,
    estimateStopMicroRemaining: usdToMicro(L.watchdogEstimateStopUSD) - t.consumedMicro,
    ceilingMicroRemaining: usdToMicro(L.consumptionCeilingUSD) - t.consumedMicro,
  };
  a.reasons = [];
  if (a.noNewGenerationSecondsRemaining <= 0) a.reasons.push('the cumulative runtime is past the point where a generation may start');
  if (a.estimateStopMicroRemaining <= 0) a.reasons.push('the cumulative consumption has reached the estimated stop threshold');
  if (a.ceilingMicroRemaining <= 0) a.reasons.push('the cumulative consumption has reached the ceiling');
  if (state.sessions.some(s => s.status === 'prepared')) a.reasons.push('the previous session has not been closed');
  if (!state.funded) a.reasons.push('the deposit has not been recorded');
  a.allowed = a.reasons.length === 0;
  return a;
}

// Prepare the next session. Refuses if the ledger is invalid, a session is still open, a limit has been reached,
// or the provider's balance (read by the operator in the console) does not match what the ledger says was spent.
export function prepareSession({runDir, lock, currentBalanceUSD, now}) {
  const led = readLedger(runDir, lock), a = allowance(lock, led.state);
  if (!a.allowed) throw new LedgerError(`no session may be prepared: ${a.reasons.join('; ')}`, 'SESSION_REFUSED');
  const current = usdToMicro(currentBalanceUSD), baseline = usdToMicro(led.state.funded.balanceAfterUSD), tol = usdToMicro(lock.limits.reconciliationToleranceUSD);
  const spentByBalance = baseline - current;
  if (current > baseline) throw new LedgerError('the balance is higher than it was after the deposit: additional funding is not authorised', 'SESSION_REFUSED');
  if (Math.abs(spentByBalance - a.priorConsumedMicro) > tol) {
    throw new LedgerError(`the balance shows $${microToUsd(spentByBalance)} spent since the deposit, but the ledger records $${a.priorConsumedUSD}. `
      + 'They differ by more than the tolerance, so a session or a charge is unaccounted for. Return to the owner', 'SESSION_REFUSED');
  }
  const session = led.state.sessions.length + 1;
  // The larger of the two figures is carried forward, so the estimate never starts below the provider's own balance.
  const priorConsumedMicro = Math.max(a.priorConsumedMicro, spentByBalance);
  const data = {session, priorRuntimeSeconds: a.priorRuntimeSeconds, priorConsumedUSD: microToUsd(priorConsumedMicro), balanceUSD: currentBalanceUSD,
    watchdogStopSecondsRemaining: a.watchdogStopSecondsRemaining, noNewGenerationSecondsRemaining: a.noNewGenerationSecondsRemaining};
  const after = append(runDir, lock, 'session-prepared', data, now);
  return {ledger: after, session: data, sessionEnv: sessionEnvText(data, after.head.hash)};
}
// The sealed session file the Pod watchdog reads. It holds no credential.
export function sessionEnvText(d, ledgerHead) {
  return ['# AP-84B3 session allowance, generated from the session ledger. Do not edit: the watchdog checks this file against BUNDLE.SHA256SUMS.',
    `WD_SESSION_NUMBER=${d.session}`, `WD_PRIOR_RUNTIME_SECONDS=${d.priorRuntimeSeconds}`, `WD_PRIOR_CONSUMED_USD=${d.priorConsumedUSD}`, `WD_LEDGER_HEAD=${ledgerHead}`].join('\n') + '\n';
}

// Close the prepared session with its reported usage. consumedUSD is the higher of the balance and usage methods.
// A session that was prepared but never started is closed with notStarted: true (zero runtime, zero consumption).
export function closeSession({runDir, lock, gpu, gpuRateUSDPerHour, startedAt, endedAt, consumedUSD, reason, notStarted = false, now}) {
  const led = readLedger(runDir, lock), s = led.state.sessions.find(x => x.status === 'prepared');
  if (!s) throw new LedgerError('there is no prepared session to close', 'SESSION_REFUSED');
  if (typeof reason !== 'string' || reason.trim().length < 3) throw new LedgerError('a reason is required when closing a session');
  let data;
  if (notStarted) {
    data = {session: s.number, notStarted: true, runtimeSeconds: 0, consumedUSD: '0.00', reason};
  } else {
    if (![lock.provider.gpuPrimary, lock.provider.gpuFallback].includes(gpu)) throw new LedgerError('the GPU is not one of the approved GPUs');
    if (usdToMicro(gpuRateUSDPerHour) > usdToMicro(lock.limits.gpuRateCapUSDPerHour[gpu])) throw new LedgerError('the GPU rate is above the approved cap');
    if (Number.isNaN(Date.parse(startedAt)) || Number.isNaN(Date.parse(endedAt)) || Date.parse(endedAt) < Date.parse(startedAt)) throw new LedgerError('startedAt and endedAt must be valid times, in order');
    usdToMicro(consumedUSD);
    data = {session: s.number, gpu, gpuRateUSDPerHour, startedAt: new Date(startedAt).toISOString(), endedAt: new Date(endedAt).toISOString(), runtimeSeconds: secondsBetween(startedAt, endedAt), consumedUSD, reason};
  }
  const after = append(runDir, lock, 'session-closed', data, now);
  const t = totals(after.state), L = lock.limits;
  return {ledger: after, session: data, totals: t,
    overLimit: t.runtimeSeconds > L.maxRuntimeSeconds || t.consumedMicro > usdToMicro(L.consumptionCeilingUSD)};
}

// ---------------------------------------------------------------------------------------------------
// Workflow freezes. The ledger is the authority on whether a workflow has been frozen and with which graph.
// Result: {status, problems}. status is one of:
//   'none'    not frozen and no frozen file: the freezing candidate may establish the freeze
//   'frozen'  frozen, and the file on disk is exactly the one recorded
//   'broken'  anything else: deleted, replaced, altered, or a file with no ledger record. The workflow stops.
export function freezeStatus({ledger, workflow}) {
  const file = path.join(ledger.run, frozenFileName(workflow)), rec = ledger.state.freezes[workflow], exists = fs.existsSync(file);
  if (!rec) {
    if (exists) return {status: 'broken', file, problems: [`${frozenFileName(workflow)} exists but the ledger has no freeze record for workflow ${workflow} (missing freeze metadata). Owner recovery is required`]};
    return {status: 'none', file, problems: []};
  }
  if (!exists) return {status: 'broken', file, record: rec, problems: [`the frozen graph for workflow ${workflow} has been deleted: the ledger records a freeze but ${frozenFileName(workflow)} is missing. It is never re-created automatically; owner recovery is required`]};
  if (fs.lstatSync(file).isSymbolicLink() || !fs.statSync(file).isFile()) return {status: 'broken', file, record: rec, problems: [`${frozenFileName(workflow)} is not a regular file`]};
  if (shaFile(file) !== rec.fileSha256) return {status: 'broken', file, record: rec, problems: [`the frozen graph for workflow ${workflow} has been replaced or altered: it no longer matches the freeze recorded in the ledger. Owner recovery is required`]};
  return {status: 'frozen', file, record: rec, problems: []};
}
// Record a freeze. The frozen file must already be on disk; it is hashed here, never trusted from the caller.
export function registerFreeze({runDir, lock, workflow, graphSha256, apiSha256, now}) {
  const run = runFolder(runDir), file = path.join(run, frozenFileName(workflow));
  if (!fs.existsSync(file)) throw new LedgerError('the frozen graph file is missing');
  return append(runDir, lock, 'freeze', {workflow, graphSha256, apiSha256, fileSha256: shaFile(file)}, now);
}

// Owner-controlled recovery. A broken or unwanted freeze can only be cleared when DECISIONS.md carries a line
//     AP-84B3-FREEZE-RECOVERY-APPROVED=<Q|S>:<current ledger head hash>
// written after the owner's explicit decision. The approval names the exact ledger state, so it cannot be reused.
// The old frozen file (if any) is kept under a revoked name, never deleted. Outputs made under the old freeze no
// longer match the active freeze and cannot be imported.
export function recoverFreeze({runDir, lock, workflow, reason, decisionsFile, now}) {
  if (!WORKFLOWS.includes(workflow)) throw new LedgerError('workflow must be Q or S');
  const led = readLedger(runDir, lock);
  const text = fs.existsSync(decisionsFile) ? fs.readFileSync(decisionsFile, 'utf8') : '';
  if (!text.includes(`AP-84B3-FREEZE-RECOVERY-APPROVED=${workflow}:${led.head.hash}`)) {
    throw new LedgerError(`freeze recovery for workflow ${workflow} is not approved. It needs the owner's explicit decision, recorded in ${path.basename(decisionsFile)} as `
      + `AP-84B3-FREEZE-RECOVERY-APPROVED=${workflow}:${led.head.hash}`, 'RECOVERY_NOT_APPROVED');
  }
  const st = freezeStatus({ledger: led, workflow});
  if (st.status === 'none') throw new LedgerError(`workflow ${workflow} has no freeze to recover`);
  const after = append(runDir, lock, 'freeze-recovery', {workflow, reason, approvedAgainstHead: led.head.hash, previousGraphSha256: st.record?.graphSha256 ?? null}, now);
  if (fs.existsSync(st.file)) { try { fs.chmodSync(st.file, 0o644); } catch {} fs.renameSync(st.file, path.join(led.run, `frozen-${workflow.toLowerCase()}.revoked-${after.head.seq}.json`)); }
  return after;
}

// ---------------------------------------------------------------------------------------------------
// Independent cross-check used before anything is imported: the run sheet, the ledger, the frozen graph and the
// lock must all agree. Returns a list of problems (empty = consistent).
export function crossCheckRun({runDir, lock, lockSha256, sheet, workflow}) {
  let led;
  try { led = readLedger(runDir, lock); } catch (e) { return [e.message]; }
  const p = [], st = led.state;
  if (st.lockSha256 !== lockSha256) p.push('the ledger belongs to a different experiment lock');
  if (st.runId !== sheet.runId) p.push('the ledger belongs to a different run');
  if (sheet.ledgerHead !== led.head.hash) p.push('the run sheet was not completed against the current ledger (ledgerHead differs)');
  if (st.sessions.some(s => s.status === 'prepared')) p.push('a session is still open in the ledger');
  // Sessions: every session that ran must be in the run sheet with the same times and consumption, and no others.
  const ran = st.sessions.filter(s => s.status === 'closed' && !s.closed.notStarted).map(s => `${s.closed.startedAt}|${s.closed.endedAt}|${usdToMicro(s.closed.consumedUSD)}|${s.closed.gpu}`);
  const iso = v => (Number.isNaN(Date.parse(v)) ? String(v) : new Date(v).toISOString());
  const micro = v => { try { return usdToMicro(v); } catch { return 'invalid'; } };
  const listed = [...(Array.isArray(sheet.priorSessions) ? sheet.priorSessions : []), sheet.pod || {}].map(s => `${iso(s.startedAt)}|${iso(s.endedAt)}|${micro(s.consumedUSD)}|${s.gpu}`);
  if (ran.length !== listed.length || ran.some((x, i) => x !== listed[i])) p.push('the sessions in the run sheet do not match the sessions recorded in the ledger (a session is missing, added or changed)');
  const t = totals(st), L = lock.limits;
  if (t.runtimeSeconds > L.maxRuntimeSeconds) p.push('the ledger records more total Pod runtime than the approved limit');
  if (t.consumedMicro > usdToMicro(L.consumptionCeilingUSD)) p.push('the ledger records more total consumption than the approved ceiling');
  // Frozen graph: ledger, file, run sheet and lock must agree.
  const fz = freezeStatus({ledger: led, workflow});
  if (fz.status !== 'frozen') p.push(...(fz.problems.length ? fz.problems : [`workflow ${workflow} was never frozen`]));
  else {
    let frozen = null; try { frozen = JSON.parse(fs.readFileSync(fz.file, 'utf8')); } catch {}
    if (!frozen || frozen.graphSha256 !== fz.record.graphSha256) p.push('the frozen graph file does not contain the graph recorded in the ledger');
    else if (frozen.lockSha256 !== lockSha256) p.push('the frozen graph was made under a different experiment lock');
    if (sheet.workflows?.[workflow]?.graphSha256 !== fz.record.graphSha256) p.push(`the run sheet's frozen graph hash for workflow ${workflow} does not match the ledger`);
    if (sheet.workflows?.[workflow]?.apiSha256 !== fz.record.apiSha256) p.push(`the run sheet's export hash for workflow ${workflow} does not match the ledger`);
  }
  return p;
}

