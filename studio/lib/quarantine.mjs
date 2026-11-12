// Quarantine storage for generation candidates (AP-84B1).
// Candidates live ONLY under <workspace>/quarantine/<job-id>/ and are never written into production/ or bible/.
// File names are whitelisted, files are write-once (never overwritten), sizes are capped and every file is hashed.
// The API exposes job IDs and candidate names only, never filesystem paths.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {REPO_ROOT} from '../../production/lib/runtime.mjs';

export const GEN_JOB_ID = /^g-\d{8}-\d{6}-[0-9a-f]{6}$/;
export const CANDIDATE_NAME = /^[a-z0-9][a-z0-9-]{0,80}\.(png|json)$/;
export const MAX_CANDIDATE_BYTES = 20 * 1024 * 1024;
const TYPES = {'.png': 'image/png', '.json': 'application/json'};
const PROTECTED = ['production', 'bible', 'skills'].map(d => path.join(REPO_ROOT, d));
const err = (status, message) => Object.assign(new Error(message), {status});

export class Quarantine {
  constructor(workspaceRoot) {
    this.root = path.join(path.resolve(workspaceRoot), 'quarantine');
    for (const p of PROTECTED) if (this.root === p || this.root.startsWith(p + path.sep)) throw new Error('quarantine must not live inside production, bible or skills');
    fs.mkdirSync(this.root, {recursive: true});
  }

  #jobDir(jobId) {
    if (!GEN_JOB_ID.test(jobId)) throw err(400, 'invalid generation job id');
    return path.join(this.root, jobId);
  }

  // Strictly resolve <job>/<name> inside the quarantine root (no traversal, no symlinks); null if invalid.
  resolve(jobId, name) {
    if (typeof name !== 'string' || !CANDIDATE_NAME.test(name)) return null;
    const dir = this.#jobDir(jobId), file = path.join(dir, name);
    if (path.dirname(file) !== dir) return null;
    try {
      if (fs.lstatSync(dir).isSymbolicLink() || fs.lstatSync(file).isSymbolicLink()) return null;
      return fs.statSync(file).isFile() ? file : null;
    } catch { return null; }
  }

  // Write a new candidate file. Refuses invalid names, oversize content and existing files (write-once).
  write(jobId, name, buffer) {
    if (typeof name !== 'string' || !CANDIDATE_NAME.test(name)) throw err(400, `invalid candidate file name: ${JSON.stringify(String(name).slice(0, 100))}`);
    if (!Buffer.isBuffer(buffer)) throw err(400, 'candidate content must be bytes');
    if (buffer.length === 0 || buffer.length > MAX_CANDIDATE_BYTES) throw err(413, `candidate size must be 1 byte to ${MAX_CANDIDATE_BYTES} bytes`);
    const dir = this.#jobDir(jobId);
    fs.mkdirSync(dir, {recursive: true});
    const file = path.join(dir, name);
    if (path.dirname(file) !== dir) throw err(400, 'invalid candidate path');
    fs.writeFileSync(file, buffer, {flag: 'wx'});               // 'wx' fails if the file already exists
    return {name, bytes: buffer.length, sha256: crypto.createHash('sha256').update(buffer).digest('hex'), mediaType: TYPES[path.extname(name)]};
  }

  stat(jobId, name) {
    const f = this.resolve(jobId, name);
    return f ? {file: f, size: fs.statSync(f).size, type: TYPES[path.extname(f)] || 'application/octet-stream'} : null;
  }
  sha256(jobId, name) {
    const f = this.resolve(jobId, name);
    return f ? crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex') : null;
  }
  open(jobId, name, range) { const s = this.stat(jobId, name); return s ? fs.createReadStream(s.file, range) : null; }
}
