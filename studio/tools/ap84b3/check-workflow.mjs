#!/usr/bin/env node
// AP-84B3 workflow graph checker (D1-6 addition A4, amended under owner decision L12).
//
// The owner's D1-2 caveat: the exact node graph and shift value must be exported, hashed and recorded before any
// candidate, with no silent workflow changes. This tool validates a workflow exported from ComfyUI in API format
// (Workflow > Export (API)): an object of  "<node id>": {"class_type": "...", "inputs": {...}}  where a
// connection is ["<node id>", <output index>].
//
// TWO LAYERS
//   Layer 1 (fixed now, in the experiment lock): for each workflow, one entry per node (its type and literal
//     settings) and the connections between them. These come from the approved specification and the pinned
//     sources. The world is closed: any node, literal setting or connection that is not listed is not accepted.
//   Layer 2 (frozen during authorised execution): the details of the real export that Layer 1 cannot know in
//     advance, i.e. output slot numbers, the recorded shift value and the "free" values (file names). The first
//     export that passes Layer 1 is frozen; every later export must equal it except for the values allowed to
//     differ (the seed; for a smoke run also the latent size and the step count).
//
// The real API export has NOT been seen (ComfyUI is not installed locally), and no expected export graph is
// invented or pre-approved here. So the checker is deliberately strict:
//   - a wrong, missing or extra node, a changed setting or a rewired connection FAILS;
//   - a literal setting that Layer 1 does not list is not judged harmless by this tool or by the operator: the
//     result is STOP, and the export goes to the owner for review. Nothing may be generated.
// Node numbering is ignored: nodes are matched to their roles by type, settings and connections.
//
//   node studio/tools/ap84b3/check-workflow.mjs --run <run folder> --workflow Q|S (--candidate A|B|C | --smoke) --file <export.json>
//
// THE FREEZE IS MANDATORY AND FAILS CLOSED. The frozen graph lives in the run folder as frozen-q.json or
// frozen-s.json; there is no option to skip it or to point at another file. The session ledger is the authority:
// it records each freeze with the frozen file's SHA-256. A frozen graph that is deleted, replaced or altered, or
// a frozen file the ledger does not know about, stops the workflow. It is never re-created automatically: the
// only way back is the owner-controlled recovery procedure (an approval line naming the exact ledger state).
//   - Only the first candidate of each workflow may create it: candidate A for workflow Q, candidate C for
//     workflow S, and only when no frozen graph exists yet. It is written once and never overwritten.
//   - Every other export (candidate B, every smoke run, and any later export of A or C) must be compared with
//     it. If the frozen graph is missing, unreadable, altered or made under a different lock, the check fails.
//   - A smoke export can never create a frozen graph.
//   - Apart from the seed (and, for a smoke run, the latent size and the steps), everything frozen must be
//     identical: the shift, output slot numbers, connections, node settings and file names.
//
// Sources for Layer 1: ComfyUI at the pinned commit (node input names), the pinned IP-Adapter node source, and
// comfyui-workflow-templates==0.11.107, templates/image_qwen_image_edit_2511.json
// (SHA-256 fd2d7ebc17c80ab1e55f8320babd13a568de94c26b67807dbdf2a74cea18b65b), whose shift value is 3.1.
// The Qwen latent node (EmptySD3LatentImage) is an UNVERIFIED compatibility gate: it is tested in the smoke run
// during authorised execution, and if it is incompatible the run stops. No other node is substituted.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {loadLock, resolveLiteral, isInside, REPO_ROOT, CANDIDATE_IDS} from '../../lib/experiment-spec.mjs';
import {readLedger, freezeStatus, registerFreeze, frozenFileName as ledgerFrozenFileName} from '../../lib/experiment-ledger.mjs';

export const FROZEN_SCHEMA = 'ap84b3-frozen-graph/1';
const isLink = v => Array.isArray(v) && v.length === 2 && (typeof v[0] === 'string' || Number.isInteger(v[0])) && Number.isInteger(v[1]);
const base = p => String(p).split(/[\\/]/).pop();
// Deterministic JSON with sorted keys (the graph contains decimals, so the lock's integer-only form is not used).
const stable = v => Array.isArray(v) ? '[' + v.map(stable).join(',') + ']'
  : v && typeof v === 'object' ? '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + stable(v[k])).join(',') + '}' : JSON.stringify(v);
export const graphHash = normalForm => crypto.createHash('sha256').update(stable(normalForm)).digest('hex');
const permutations = a => a.length <= 1 ? [a] : a.flatMap((x, i) => permutations([...a.slice(0, i), ...a.slice(i + 1)]).map(p => [x, ...p]));

// The expected settings for one export. mode: {candidate: 'A'} or {smoke: true}.
function expectation(lock, workflow, mode) {
  const G = lock.workflows[workflow].graphConstraints;
  const ctx = mode.smoke ? {seed: lock.smoke.seed, smoke: true} : {seed: lock.candidates[mode.candidate].seed, smoke: false};
  return {G, ctx, nodes: G.nodes.map(n => ({role: n.role, type: n.type, literals: Object.fromEntries(Object.entries(n.literals).map(([k, s]) => [k, resolveLiteral(lock, workflow, s, ctx)]))}))};
}

// Check one assignment of export nodes to roles. Returns {problems, unlisted, recorded, free, normalForm}.
function evaluate(exp, assign, graph) {
  const problems = [], unlisted = [], recorded = {}, free = {}, normalForm = {};
  const roleOf = new Map([...assign].map(([role, id]) => [String(id), role]));
  const wanted = new Map(exp.G.connections.map(c => [`${c.to}.${c.input}`, c.from]));
  for (const n of exp.nodes) {
    const node = graph[assign.get(n.role)], inputs = node.inputs || {}, norm = {};
    for (const [name, want] of Object.entries(n.literals)) {
      const has = name in inputs, v = inputs[name];
      if (!has) { if (!(want.kind === 'value' && want.optional)) problems.push(`${n.role} (${n.type}): setting "${name}" is missing`); continue; }
      if (isLink(v)) { problems.push(`${n.role} (${n.type}): "${name}" must be a literal setting, but it is connected to another node`); continue; }
      norm[name] = v;
      if (want.kind === 'free') { free[`${n.role}.${name}`] = v; continue; }
      if (want.kind === 'record') { if (typeof v !== 'number') problems.push(`${n.role} (${n.type}): "${name}" must be a number`); else recorded[want.name] = v; continue; }
      const got = typeof want.value === 'string' && /\.(safetensors|bin)$/.test(want.value) ? base(v) : v;
      if (got !== want.value) problems.push(`${n.role} (${n.type}): "${name}" is ${JSON.stringify(v)}, approved ${JSON.stringify(want.value)}`);
    }
    for (const [name, v] of Object.entries(inputs)) {
      if (name in n.literals) continue;
      const key = `${n.role}.${name}`;
      if (isLink(v)) {
        const from = roleOf.get(String(v[0]));
        norm[name] = ['@' + (from ?? '?'), v[1]];
        if (!wanted.has(key)) problems.push(`${n.role} (${n.type}): unexpected connection on "${name}"`);
        else if (from !== wanted.get(key)) problems.push(`${n.role} (${n.type}): "${name}" is connected to ${from ?? 'an unknown node'}, expected ${wanted.get(key)}`);
      } else {
        norm[name] = v;
        if (wanted.has(key)) problems.push(`${n.role} (${n.type}): "${name}" must be connected to ${wanted.get(key)}, but it is a literal value`);
        else unlisted.push(`${n.role} (${n.type}): setting "${name}" = ${JSON.stringify(v)} is not listed in the approved constraints`);
      }
    }
    for (const c of exp.G.connections) if (c.to === n.role && !(c.input in inputs)) problems.push(`${n.role} (${n.type}): required connection "${c.input}" from ${c.from} is missing`);
    normalForm[n.role] = {class_type: n.type, inputs: norm};
  }
  return {problems, unlisted, recorded, free, normalForm};
}

// Validate an export against Layer 1. Returns {ok, stop, problems, unlisted, recorded, free, normalForm, graphSha256}.
//   ok   : every constraint holds and nothing is unlisted.
//   stop : true when the only obstacle is unlisted settings, which need the owner's review.
export function checkWorkflow({graph, workflow, lock, candidate = null, smoke = false}) {
  const fail = problems => ({ok: false, stop: false, problems, unlisted: [], recorded: {}, free: {}, normalForm: null, graphSha256: null});
  if (!['Q', 'S'].includes(workflow)) return fail(['workflow must be Q or S']);
  if (smoke ? candidate !== null : !CANDIDATE_IDS.includes(candidate)) return fail(['name either a candidate (A, B or C) or a smoke run, not both']);
  if (!smoke && lock.candidates[candidate].workflow !== workflow) return fail([`candidate ${candidate} does not use workflow ${workflow}`]);
  if (!graph || typeof graph !== 'object' || Array.isArray(graph) || 'nodes' in graph || 'links' in graph) return fail(['this is not an API-format export (use Workflow > Export (API) in ComfyUI)']);
  const ids = Object.keys(graph);
  if (!ids.length || ids.some(id => !graph[id] || typeof graph[id].class_type !== 'string' || (graph[id].inputs !== undefined && (typeof graph[id].inputs !== 'object' || Array.isArray(graph[id].inputs))))) return fail(['every node needs a class_type and an inputs object']);
  const exp = expectation(lock, workflow, smoke ? {smoke: true} : {candidate});

  // Closed world: node types and counts must equal the constraint list exactly.
  const count = list => list.reduce((m, t) => m.set(t, (m.get(t) || 0) + 1), new Map());
  const want = count(exp.nodes.map(n => n.type)), got = count(ids.map(id => graph[id].class_type)), problems = [];
  for (const [t, n] of want) if ((got.get(t) || 0) !== n) problems.push(`expected ${n} node(s) of type ${t}, found ${got.get(t) || 0}`);
  for (const [t, n] of got) if (!want.has(t)) problems.push(`node type ${t} is not part of the approved workflow (${n} found)`);
  if (problems.length) return fail(problems);

  // Match nodes to roles. Nodes of the same type are tried in every order; the best assignment is reported.
  const types = [...want.keys()];
  const options = types.map(t => { const roles = exp.nodes.filter(n => n.type === t).map(n => n.role); return permutations(ids.filter(id => graph[id].class_type === t)).map(p => roles.map((r, i) => [r, p[i]])); });
  let best = null;
  const walk = (i, acc) => {
    if (i === options.length) {
      const r = evaluate(exp, new Map(acc), graph);
      if (!best || r.problems.length < best.problems.length || (r.problems.length === best.problems.length && r.unlisted.length < best.unlisted.length)) best = r;
      return;
    }
    for (const o of options[i]) walk(i + 1, acc.concat(o));
  };
  walk(0, []);
  // The smoke seed belongs to smoke runs only (the lock already guarantees it differs from every candidate seed).
  const ok = best.problems.length === 0 && best.unlisted.length === 0;
  return {ok, stop: best.problems.length === 0 && best.unlisted.length > 0, problems: best.problems, unlisted: best.unlisted, recorded: best.recorded, free: best.free,
    normalForm: best.problems.length === 0 ? best.normalForm : null, graphSha256: ok ? graphHash(best.normalForm) : null};
}

// Layer 2. The frozen record of the first export that passed Layer 1.
// The candidate whose export creates each workflow's frozen graph: the first candidate that uses the workflow.
export const FREEZING_CANDIDATE = Object.freeze({Q: 'A', S: 'C'});
export const frozenFileName = ledgerFrozenFileName;

export function freeze({result, workflow, candidate, lockSha256, apiSha256}) {
  if (!result.ok) throw new Error('only an export that passes every constraint, with nothing unlisted, can be frozen');
  if (FREEZING_CANDIDATE[workflow] !== candidate) throw new Error(`only candidate ${FREEZING_CANDIDATE[workflow]} may freeze workflow ${workflow}`);
  return {schema: FROZEN_SCHEMA, workflow, frozenFrom: `candidate ${candidate}`, lockSha256, apiSha256, graphSha256: result.graphSha256, recorded: result.recorded, free: result.free, normalForm: result.normalForm, frozenAt: new Date().toISOString()};
}
// Compare a later export with the frozen graph. Only the listed values may differ: the seed, and for a smoke run
// also the latent size and the steps. Everything else, including slot numbers, shift and file names, must be identical.
export function compareToFrozen({frozen, result, lock, workflow, smoke = false}) {
  if (!frozen || frozen.schema !== FROZEN_SCHEMA || frozen.workflow !== workflow || !frozen.normalForm) return ['the frozen graph is missing or is for a different workflow'];
  if (!result.ok || !result.normalForm) return ['the export did not pass the constraints, so it cannot be compared with the frozen graph'];
  const G = lock.workflows[workflow].graphConstraints, mayDiffer = new Set();
  for (const n of G.nodes) for (const [k, s] of Object.entries(n.literals)) if (s.seed === true || (smoke && typeof s.smoke === 'string')) mayDiffer.add(`${n.role}.${k}`);
  const mask = nf => Object.fromEntries(Object.entries(nf).map(([role, n]) => [role, {class_type: n.class_type, inputs: Object.fromEntries(Object.entries(n.inputs).map(([k, v]) => [k, mayDiffer.has(`${role}.${k}`) ? '<may differ>' : v]))}]));
  const a = mask(frozen.normalForm), b = mask(result.normalForm), diffs = [];
  for (const role of new Set([...Object.keys(a), ...Object.keys(b)])) {
    if (!a[role] || !b[role]) { diffs.push(`${role}: present in only one of the two graphs`); continue; }
    if (a[role].class_type !== b[role].class_type) diffs.push(`${role}: node type ${b[role].class_type} differs from the frozen ${a[role].class_type}`);
    for (const k of new Set([...Object.keys(a[role].inputs), ...Object.keys(b[role].inputs)])) if (stable(a[role].inputs[k]) !== stable(b[role].inputs[k])) diffs.push(`${role}.${k}: ${stable(b[role].inputs[k])} differs from the frozen ${stable(a[role].inputs[k])}`);
  }
  return diffs;
}

// Is a frozen record usable? It must be complete, self-consistent (its hash matches its content), made from the
// workflow's freezing candidate, and made under the same experiment lock. Returns a list of problems.
export function frozenProblems({frozen, workflow, lockSha256}) {
  if (!frozen || typeof frozen !== 'object' || frozen.schema !== FROZEN_SCHEMA) return ['the frozen graph is not a valid frozen record'];
  const p = [];
  if (frozen.workflow !== workflow) p.push(`the frozen graph is for workflow ${frozen.workflow}, not ${workflow}`);
  if (frozen.frozenFrom !== `candidate ${FREEZING_CANDIDATE[workflow]}`) p.push(`the frozen graph was not made from candidate ${FREEZING_CANDIDATE[workflow]}`);
  if (frozen.lockSha256 !== lockSha256) p.push('the frozen graph was made under a different experiment lock');
  if (!frozen.normalForm || typeof frozen.normalForm !== 'object' || graphHash(frozen.normalForm) !== frozen.graphSha256) p.push('the frozen graph has been altered (its hash does not match its content)');
  return p;
}

// The complete, fail-closed decision for one export. `frozen` is the workflow's frozen record, or null if none exists.
//   - No frozen record: only the freezing candidate's export may pass, and it becomes the frozen record (toFreeze).
//     Any other export, and every smoke export, FAILS: there is nothing to compare it with.
//   - A frozen record exists: the export must equal it apart from the permitted differences.
// Returns the Layer 1 result plus {ok, frozenRequired, toFreeze, differencesFromFrozen}.
export function validateExport({graph, workflow, lock, lockSha256, candidate = null, smoke = false, frozen = null, apiSha256 = null}) {
  const result = checkWorkflow({graph, workflow, lock, candidate, smoke});
  const out = {...result, toFreeze: null, differencesFromFrozen: null, frozenRequired: true};
  if (!result.ok) return out;                                     // Layer 1 failed or stopped: nothing else is considered
  if (frozen === null) {
    if (!smoke && candidate === FREEZING_CANDIDATE[workflow]) return {...out, frozenRequired: false, toFreeze: freeze({result, workflow, candidate, lockSha256, apiSha256})};
    return {...out, ok: false, graphSha256: null, problems: [smoke
      ? `no frozen graph exists for workflow ${workflow}. A smoke export cannot create one: freeze candidate ${FREEZING_CANDIDATE[workflow]}'s export first`
      : `no frozen graph exists for workflow ${workflow}. Only candidate ${FREEZING_CANDIDATE[workflow]}'s export may create it; this export cannot be accepted without one`]};
  }
  const bad = frozenProblems({frozen, workflow, lockSha256});
  if (bad.length) return {...out, ok: false, graphSha256: null, problems: bad};
  const diffs = compareToFrozen({frozen, result, lock, workflow, smoke});
  return {...out, ok: diffs.length === 0, graphSha256: diffs.length ? null : result.graphSha256, differencesFromFrozen: diffs, problems: diffs.length ? ['the export differs from the frozen graph'] : []};
}

// The same decision against a run folder: reads frozen-q.json / frozen-s.json, and writes it (once) when the
// freezing candidate's first export passes. There is no way to name another file or to skip the comparison.
export function checkExportInRun({runDir, graph, workflow, lock, lockSha256, candidate = null, smoke = false, apiSha256 = null}) {
  const run = path.resolve(runDir);
  if (!fs.existsSync(run) || fs.lstatSync(run).isSymbolicLink() || !fs.statSync(run).isDirectory()) throw new Error('the run folder does not exist');
  if (isInside(run, REPO_ROOT)) throw new Error('the run folder must be outside the repository');
  if (!['Q', 'S'].includes(workflow)) throw new Error('workflow must be Q or S');
  const closed = problems => ({ok: false, stop: false, problems, unlisted: [], recorded: {}, free: {}, normalForm: null, graphSha256: null, toFreeze: null, differencesFromFrozen: null, frozenRequired: true});
  // The ledger must be valid, for this lock, with a session in progress: exports are only checked on the Pod.
  let led;
  try { led = readLedger(run, lock); } catch (e) { return closed([e.message]); }
  if (led.state.lockSha256 !== lockSha256) return closed(['the session ledger belongs to a different experiment lock']);
  if (!led.state.sessions.some(x => x.status === 'prepared')) return closed(['no session is in progress in the session ledger']);
  const st = freezeStatus({ledger: led, workflow});
  if (st.status === 'broken') return closed(st.problems);
  let frozen = null;
  if (st.status === 'frozen') {
    try { frozen = JSON.parse(fs.readFileSync(st.file, 'utf8')); } catch { frozen = {}; }
    if (frozen === null || typeof frozen !== 'object' || frozen.graphSha256 !== st.record.graphSha256) return closed([`the frozen graph for workflow ${workflow} does not contain the graph recorded in the session ledger`]);
  }
  const out = validateExport({graph, workflow, lock, lockSha256, candidate, smoke, frozen, apiSha256});
  if (out.ok && out.toFreeze) {
    // First freeze of this workflow: written once, made read-only, and recorded in the ledger with its file hash.
    fs.writeFileSync(st.file, JSON.stringify(out.toFreeze, null, 1), {flag: 'wx'});
    try { fs.chmodSync(st.file, 0o444); } catch {}
    registerFreeze({runDir: run, lock, workflow, graphSha256: out.toFreeze.graphSha256, apiSha256: out.toFreeze.apiSha256});
    out.frozenWritten = st.file;
  }
  return out;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const arg = n => { const i = process.argv.indexOf(n); return i >= 0 ? process.argv[i + 1] : undefined; };
    const runDir = arg('--run'), workflow = arg('--workflow'), candidate = arg('--candidate') ?? null, smoke = process.argv.includes('--smoke'), file = arg('--file');
    if (process.argv.includes('--frozen') || process.argv.includes('--write-frozen')) throw new Error('--frozen and --write-frozen are not accepted: the frozen graph is always the one in the run folder');
    if (!runDir || !workflow || !file || (smoke ? candidate !== null : !candidate)) throw new Error('usage: check-workflow.mjs --run <run folder> --workflow Q|S (--candidate A|B|C | --smoke) --file <export.json>');
    const {lock, sha256: lockSha256} = loadLock();                              // refuses unless the lock is owner-approved
    const bytes = fs.readFileSync(file), apiSha256 = crypto.createHash('sha256').update(bytes).digest('hex');
    const r = checkExportInRun({runDir, graph: JSON.parse(bytes.toString('utf8')), workflow, lock, lockSha256, candidate, smoke, apiSha256});
    console.log(JSON.stringify({workflow, candidate, smoke, lockSha256, apiSha256, ok: r.ok, stop: r.stop, problems: r.problems, unlisted: r.unlisted, recorded: r.recorded, free: r.free,
      graphSha256: r.graphSha256, differencesFromFrozen: r.differencesFromFrozen, frozenWritten: r.frozenWritten ?? null}, null, 1));
    if (r.stop) console.error('check-workflow: STOP. The export contains settings that are not in the approved constraints. Do not generate anything; send this report to the owner for review.');
    if (!r.ok) process.exit(r.stop ? 3 : 1);
  } catch (e) { console.error(`check-workflow: ${e.message}`); process.exit(1); }
}
