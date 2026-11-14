#!/usr/bin/env node
// AP-84B3 atomic transfer verifier (D1-6, addition A2, required by owner decision D1-5).
//
// Files pulled from the Pod land in a staging folder that the import adapter cannot read. This tool checks the
// staging folder against the Pod-side MANIFEST (written by collect-outputs.sh):
//   - the exact file set: nothing missing, nothing extra;
//   - every file's size and SHA-256;
//   - a PNG signature on every .png.
// Only if everything matches is the staging folder renamed into place (one step) and the verification record
// written LAST (write to a temporary file, then rename). On any failure or interruption the staging folder is
// moved to rejected/ with a failure record, and no success record exists. An output is "safely retained" only
// once this record exists; anything else is not retained.
//
//   node studio/tools/ap84b3/verify-transfer.mjs --run <run folder> --candidate A|B|C|smoke --staging <staging folder>
//
// Smoke outputs use --candidate smoke and land in transfers/smoke/. The import adapter only ever reads the
// folders of candidates A, B and C, so a smoke output cannot be imported.
//
// The run folder and the staging folder must be on the same volume (so the rename is atomic) and outside the
// repository. This tool never contacts the Pod and never extends a time limit.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {loadLock, sha256Buffer, pngSize, isInside, REPO_ROOT, MANIFEST_HEADER, TRANSFER_SCHEMA, TRANSFER_IDS, OUTPUT_NAME_RE, SHA256_RE} from '../../lib/experiment-spec.mjs';

const MAX_BYTES = 20 * 1024 * 1024;
export class TransferRejected extends Error {
  constructor(problems) { super(`transfer rejected: ${problems.join('; ')}`); this.problems = problems; this.code = 'TRANSFER_REJECTED'; }
}

export function parseManifest(text) {
  const lines = text.replace(/\r\n/g, '\n').split('\n').filter(l => l.length);
  if (lines[0] !== MANIFEST_HEADER) throw new Error(`manifest must start with "${MANIFEST_HEADER}"`);
  const entries = lines.slice(1).map(l => {
    const m = /^([0-9a-f]{64})  (\d+)  ([^\s]+)$/.exec(l);
    if (!m || !OUTPUT_NAME_RE.test(m[3])) throw new Error(`manifest line is not valid: ${JSON.stringify(l.slice(0, 120))}`);
    return {sha256: m[1], bytes: Number(m[2]), name: m[3]};
  });
  if (!entries.length) throw new Error('manifest lists no files');
  if (new Set(entries.map(e => e.name)).size !== entries.length) throw new Error('manifest lists a file twice');
  return entries;
}

// Check a staging folder against its manifest. Returns {entries, manifestSha256, problems}.
export function checkStaging(stagingDir) {
  const problems = [];
  let entries = [], manifestSha256 = null;
  const dirents = fs.readdirSync(stagingDir, {withFileTypes: true});
  const manifestFile = path.join(stagingDir, 'MANIFEST');
  if (!fs.existsSync(manifestFile) || fs.lstatSync(manifestFile).isSymbolicLink()) return {entries, manifestSha256, problems: ['MANIFEST is missing from the staging folder']};
  const manifestBytes = fs.readFileSync(manifestFile);
  manifestSha256 = sha256Buffer(manifestBytes);
  try { entries = parseManifest(manifestBytes.toString('utf8')); } catch (e) { return {entries, manifestSha256, problems: [e.message]}; }
  const expected = new Set(entries.map(e => e.name));
  for (const d of dirents) {
    if (d.name === 'MANIFEST') continue;
    if (!d.isFile() || d.isSymbolicLink()) problems.push(`${d.name}: not a regular file`);
    else if (!expected.has(d.name)) problems.push(`${d.name}: not listed in the manifest (extra file)`);
  }
  for (const e of entries) {
    const f = path.join(stagingDir, e.name);
    let st; try { st = fs.lstatSync(f); } catch { problems.push(`${e.name}: missing`); continue; }
    if (!st.isFile() || st.isSymbolicLink()) continue;                         // already reported above
    if (st.size > MAX_BYTES) { problems.push(`${e.name}: larger than ${MAX_BYTES} bytes`); continue; }
    if (st.size !== e.bytes) { problems.push(`${e.name}: size ${st.size} does not match the manifest (${e.bytes}); incomplete or changed`); continue; }
    const buf = fs.readFileSync(f);
    if (sha256Buffer(buf) !== e.sha256) problems.push(`${e.name}: SHA-256 does not match the manifest`);
    else if (e.name.endsWith('.png') && !pngSize(buf)) problems.push(`${e.name}: not a PNG`);
  }
  return {entries, manifestSha256, problems};
}

const stamp = () => new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z');

// Verify and, only on success, move the staging folder into place and write the verification record last.
// beforeRecord is a test hook that simulates an interruption between the move and the record.
export function verifyTransfer({runDir, candidate, stagingDir, beforeRecord = null}) {
  // 'smoke' is a transfer folder of its own: smoke outputs are verified like any other file but are never a candidate.
  if (!TRANSFER_IDS.includes(candidate)) throw new Error('candidate must be A, B, C or smoke');
  const run = path.resolve(runDir), staging = path.resolve(stagingDir);
  for (const [p, what] of [[run, 'run folder'], [staging, 'staging folder']]) {
    if (!fs.existsSync(p) || fs.lstatSync(p).isSymbolicLink() || !fs.statSync(p).isDirectory()) throw new Error(`the ${what} does not exist`);
    if (isInside(p, REPO_ROOT)) throw new Error(`the ${what} must be outside the repository`);
  }
  const target = path.join(run, 'transfers', candidate), record = path.join(run, 'transfers', `${candidate}.verified.json`);
  if (fs.existsSync(target) || fs.existsSync(record)) throw new Error(`candidate ${candidate} already has a transfer in this run folder`);
  // Move a folder to rejected/ with a failure record. Never leaves a success record behind.
  const reject = (from, problems) => {
    const rejected = path.join(run, 'rejected', `${candidate}-${stamp()}-${process.pid}`);
    fs.mkdirSync(path.dirname(rejected), {recursive: true});
    fs.renameSync(from, rejected);
    fs.writeFileSync(path.join(run, 'rejected', `${path.basename(rejected)}.failed.json`),
      JSON.stringify({schema: 'ap84b3-transfer-rejected/1', status: 'rejected', candidate, problems, rejectedAt: new Date().toISOString()}, null, 1), {flag: 'wx'});
  };
  const {entries, manifestSha256, problems} = checkStaging(staging);
  if (problems.length) { reject(staging, problems); throw new TransferRejected(problems); }
  fs.mkdirSync(path.dirname(target), {recursive: true});
  fs.renameSync(staging, target);                                              // one step: all files or none
  const tmp = `${record}.tmp-${process.pid}`;
  try {
    if (beforeRecord) beforeRecord();
    const again = checkStaging(target);                                        // re-check in place before recording success
    if (again.problems.length || again.manifestSha256 !== manifestSha256) throw new TransferRejected(again.problems.length ? again.problems : ['the manifest changed during verification']);
    const body = {schema: TRANSFER_SCHEMA, status: 'verified', candidate, manifestSha256,
      files: entries.map(e => ({name: e.name, bytes: e.bytes, sha256: e.sha256})), verifiedAt: new Date().toISOString()};
    const fd = fs.openSync(tmp, 'wx');
    try { fs.writeSync(fd, JSON.stringify(body, null, 1)); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    fs.renameSync(tmp, record);                                                // the success record appears last, complete
    return body;
  } catch (e) {
    // Anything that goes wrong after the move: no success record, and the files leave the place the adapter reads.
    try { fs.rmSync(tmp, {force: true}); } catch {}
    if (!fs.existsSync(record) && fs.existsSync(target)) { try { reject(target, e.problems || [`verification interrupted: ${e.message}`]); } catch {} }
    throw e;
  }
}

// Has this candidate's transfer been verified? True only if the success record exists and names verified files.
export function isRetained(runDir, candidate) {
  try {
    const r = JSON.parse(fs.readFileSync(path.join(path.resolve(runDir), 'transfers', `${candidate}.verified.json`), 'utf8'));
    return r.schema === TRANSFER_SCHEMA && r.status === 'verified' && r.candidate === candidate && SHA256_RE.test(r.manifestSha256) && Array.isArray(r.files) && r.files.length > 0;
  } catch { return false; }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const arg = n => { const i = process.argv.indexOf(n); return i >= 0 ? process.argv[i + 1] : undefined; };
    const runDir = arg('--run'), candidate = arg('--candidate'), stagingDir = arg('--staging');
    if (!runDir || !candidate || !stagingDir) throw new Error('usage: verify-transfer.mjs --run <run folder> --candidate A|B|C|smoke --staging <staging folder>');
    loadLock();                                                                // refuses unless the lock is owner-approved
    console.log(JSON.stringify(verifyTransfer({runDir, candidate, stagingDir}), null, 1));
  } catch (e) { console.error(`verify-transfer: ${e.message}`); process.exit(1); }
}
