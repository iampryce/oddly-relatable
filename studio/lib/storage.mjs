// Storage interface (local implementation). The API and UI only ever see run IDs and artifact KEYS
// (e.g. "render/short-001-v2.mp4"), never filesystem paths, so a future S3/Garage backend can implement the same
// methods. Keys are whitelisted by pattern and resolved strictly inside the run folder (no traversal, no symlinks).
import fs from 'node:fs';
import path from 'node:path';

const KEY = /^(render\/[a-z0-9][a-z0-9-]{0,80}\.mp4|audio\/[a-z0-9][a-z0-9-]{0,80}\.wav|storyboard\/storyboard-sheet\.png|storyboard\/frames\/\d{2}-t\d{1,4}\.\d{2}\.png|reports\/(qa|layout)-report\.json|production-(manifest|run)\.json)$/;
const TYPES = {'.mp4': 'video/mp4', '.wav': 'audio/wav', '.png': 'image/png', '.json': 'application/json'};
export const RUN_ID = /^r-\d{8}-\d{6}-[0-9a-f]{6}$/;

export class LocalStorage {
  constructor(root) {
    this.root = path.resolve(root);
    this.runsDir = path.join(this.root, 'runs');
    this.logsDir = path.join(this.root, 'logs');
    fs.mkdirSync(this.runsDir, {recursive: true});
    fs.mkdirSync(this.logsDir, {recursive: true});
  }
  describe() { return {kind: 'local'}; }   // never reveal the absolute root to clients

  // Internal: where the production engine writes a run (must not exist yet; produce refuses non-empty folders).
  runOutputDir(runId) { this.#checkRun(runId); return path.join(this.runsDir, runId); }
  logFile(runId) { this.#checkRun(runId); return path.join(this.logsDir, `${runId}.log`); }

  #checkRun(runId) { if (!RUN_ID.test(runId)) throw Object.assign(new Error('invalid run id'), {status: 400}); }

  // Resolve a whitelisted key to a real file strictly inside the run folder, or null.
  resolve(runId, key) {
    this.#checkRun(runId);
    if (typeof key !== 'string' || !KEY.test(key)) return null;
    const base = path.join(this.runsDir, runId), file = path.resolve(base, ...key.split('/'));
    const rel = path.relative(base, file);
    if (rel.startsWith('..') || path.isAbsolute(rel)) return null;
    try {
      // Reject symlinks anywhere along the path.
      let p = base;
      for (const part of rel.split(path.sep)) { p = path.join(p, part); if (fs.lstatSync(p).isSymbolicLink()) return null; }
      return fs.statSync(file).isFile() ? file : null;
    } catch { return null; }
  }

  stat(runId, key) {
    const f = this.resolve(runId, key);
    if (!f) return null;
    return {size: fs.statSync(f).size, type: TYPES[path.extname(f)] || 'application/octet-stream', file: f};
  }
  open(runId, key, range) {
    const s = this.stat(runId, key);
    return s ? fs.createReadStream(s.file, range) : null;
  }
  readJson(runId, key) {
    const f = this.resolve(runId, key);
    if (!f) return null;
    try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch { return null; }
  }

  // All artifacts of a run, as keys with sizes (only whitelisted kinds).
  listArtifacts(runId) {
    this.#checkRun(runId);
    const base = path.join(this.runsDir, runId), out = [];
    if (!fs.existsSync(base)) return out;
    const walk = (dir, prefix) => {
      for (const e of fs.readdirSync(dir, {withFileTypes: true})) {
        const key = prefix ? `${prefix}/${e.name}` : e.name;
        if (e.isDirectory() && ['render', 'audio', 'storyboard', 'frames', 'reports'].includes(e.name)) walk(path.join(dir, e.name), key);
        else if (e.isFile() && KEY.test(key)) out.push({key, bytes: fs.statSync(path.join(dir, e.name)).size, type: TYPES[path.extname(e.name)]});
      }
    };
    walk(base, '');
    return out.sort((a, b) => a.key.localeCompare(b.key));
  }

  // Log text from a byte offset (bounded), so the UI can tail it.
  readLog(runId, offset = 0, limit = 64 * 1024) {
    const f = this.logFile(runId);
    if (!fs.existsSync(f)) return {text: '', size: 0, nextOffset: 0};
    const size = fs.statSync(f).size, start = Math.max(0, Math.min(offset, size)), len = Math.min(limit, size - start);
    const buf = Buffer.alloc(len), fd = fs.openSync(f, 'r');
    try { fs.readSync(fd, buf, 0, len, start); } finally { fs.closeSync(fd); }
    return {text: buf.toString('utf8'), size, nextOffset: start + len};
  }
}
