// Persistent production job runner. Each run executes the EXISTING production engine
// (`node production/cli.mjs produce <story> <out>`) as a child process with an argument array (no shell),
// writing stdout/stderr straight into a log file so logs survive server restarts. One run at a time
// (renders are CPU-heavy) and never two active runs for the same episode.
//
// Restart recovery: runs left "running" are checked: if the process is still alive it is watched until it exits;
// otherwise the run's own production-run.json decides the outcome, and a run that never finished is marked
// "interrupted" (never assumed successful). Queued runs are resumed.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {REPO_ROOT} from '../../production/lib/runtime.mjs';
import {now, logEvent, runRow} from './db.mjs';
import {storyPath} from './stories.mjs';

export const ACTIVE = ['queued', 'running'];
export const TERMINAL = ['produced', 'qa-failed', 'failed', 'awaiting-approval', 'interrupted', 'cancelled'];
const FROM_RUN_FILE = {produced: 'produced', 'qa-failed': 'qa-failed', 'awaiting-approval': 'awaiting-approval', failed: 'failed', built: 'produced'};

const sha = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
export const newRunId = () => {
  const d = new Date(), p = n => String(n).padStart(2, '0');
  return `r-${d.getUTCFullYear()}${p(d.getUTCMonth() + 1)}${p(d.getUTCDate())}-${p(d.getUTCHours())}${p(d.getUTCMinutes())}${p(d.getUTCSeconds())}-${crypto.randomBytes(3).toString('hex')}`;
};
export function isAlive(pid) {
  if (!pid) return false;
  try { process.kill(pid, 0); return true; } catch (e) { return e.code === 'EPERM'; }
}

// Stop a run and the renderer/ffmpeg processes it started. On Windows a plain kill would leave grandchildren running.
export function killTree(pid) {
  if (process.platform === 'win32') spawn('taskkill', ['/pid', String(pid), '/T', '/F'], {stdio: 'ignore', windowsHide: true});
  else try { process.kill(pid); } catch {}
}

export class JobRunner {
  // command(storyAbsPath, outDir) -> [executable, args[]]; injectable for tests.
  constructor({db, storage, command, pollMs = 1000, concurrency = 1}) {
    this.db = db; this.storage = storage; this.pollMs = pollMs; this.concurrency = concurrency;
    this.command = command || ((story, out) => [process.execPath, [path.join(REPO_ROOT, 'production', 'cli.mjs'), 'produce', story, out]]);
    this.children = new Map(); this.watchers = new Map(); this.stopped = false;
  }

  get(id) { return runRow(this.db.prepare('SELECT * FROM runs WHERE id = ?').get(id)); }
  #update(id, fields) {
    const cols = Object.keys(fields);
    this.db.prepare(`UPDATE runs SET ${cols.map(c => `${c} = ?`).join(', ')} WHERE id = ?`).run(...cols.map(c => fields[c]), id);
  }

  // Create a queued run; refuses while the episode already has an active run.
  create(episodeId) {
    const ep = this.db.prepare('SELECT * FROM episodes WHERE id = ?').get(episodeId);
    if (!ep) throw Object.assign(new Error(`episode not found: ${episodeId}`), {status: 404});
    const active = this.db.prepare(`SELECT id FROM runs WHERE episode_id = ? AND status IN ('queued','running')`).get(episodeId);
    if (active) throw Object.assign(new Error(`episode ${episodeId} already has an active run (${active.id})`), {status: 409, runId: active.id});
    const story = storyPath(ep.story_file), id = newRunId();
    this.db.prepare('INSERT INTO runs (id, episode_id, status, story_file, story_sha256, created_at) VALUES (?, ?, ?, ?, ?, ?)')
      .run(id, episodeId, 'queued', ep.story_file, sha(story), now());
    logEvent(this.db, 'run-queued', `Production run ${id} queued`, {episodeId, runId: id});
    queueMicrotask(() => this.kick());
    return this.get(id);
  }

  // Start queued runs while capacity allows.
  kick() {
    if (this.stopped) return;
    const running = this.db.prepare(`SELECT COUNT(*) AS n FROM runs WHERE status = 'running'`).get().n;
    for (let free = this.concurrency - running; free > 0; free--) {
      const next = this.db.prepare(`SELECT * FROM runs WHERE status = 'queued' ORDER BY created_at, id LIMIT 1`).get();
      if (!next) return;
      this.#start(next);
    }
  }

  #start(run) {
    const out = this.storage.runOutputDir(run.id), log = this.storage.logFile(run.id);
    if (fs.existsSync(out)) { this.#finish(run.id, null, 'output folder already exists; refusing to overwrite'); return; }
    let exe, args;
    try { [exe, args] = this.command(storyPath(run.story_file), out); }
    catch (e) { this.#finish(run.id, null, e.message); return; }
    const fd = fs.openSync(log, 'a');
    fs.writeSync(fd, `[studio ${now()}] starting: produce ${run.story_file} (run ${run.id})\n`);
    const child = spawn(exe, args, {cwd: REPO_ROOT, env: process.env, stdio: ['ignore', fd, fd], windowsHide: true, shell: false});
    fs.closeSync(fd);
    this.#update(run.id, {status: 'running', pid: child.pid ?? null, started_at: now()});
    logEvent(this.db, 'run-started', `Production run ${run.id} started`, {episodeId: run.episode_id, runId: run.id});
    this.children.set(run.id, child);
    child.on('error', e => { this.children.delete(run.id); this.#finish(run.id, null, `could not start the production engine: ${e.message}`); });
    child.on('exit', code => { this.children.delete(run.id); this.#finish(run.id, code); });
    this.#watch(run.id);
  }

  // Poll the run's production-run.json for stage progress (and for exit when the child is not ours).
  #watch(id, pid = null) {
    if (this.watchers.has(id)) return;
    const timer = setInterval(() => {
      const runFile = this.storage.readJson(id, 'production-run.json');
      if (runFile?.stages) this.#update(id, {stages_json: JSON.stringify(runFile.stages)});
      if (pid && !isAlive(pid)) this.#finish(id, null);            // recovered run: process ended without us
    }, this.pollMs);
    timer.unref?.();
    this.watchers.set(id, timer);
  }

  #finish(id, code, error = null) {
    if (this.stopped) return;
    const timer = this.watchers.get(id); if (timer) { clearInterval(timer); this.watchers.delete(id); }
    const run = this.get(id);
    if (!run || TERMINAL.includes(run.status)) { this.kick(); return; }
    const runFile = this.storage.readJson(id, 'production-run.json');
    let status;
    if (run.status === 'running' && this.cancelling?.has(id)) status = 'cancelled';
    else if (error) status = 'failed';
    else if (runFile && FROM_RUN_FILE[runFile.status]) status = FROM_RUN_FILE[runFile.status];
    else if (code === null || code === undefined) status = 'interrupted';
    else status = code === 0 ? 'produced' : 'failed';
    const err = error || runFile?.error?.message || (status === 'interrupted' ? 'the production process stopped before finishing (server restart or crash)' : null)
      || (status === 'failed' ? `production engine exited with code ${code}` : null);
    const summary = runFile ? {render: runFile.render || null, audio: runFile.audio || null, qa: runFile.qa || null, layout: runFile.layout || null, awaiting: runFile.awaiting || null, seconds: runFile.seconds ?? null} : null;
    this.#update(id, {status, exit_code: code ?? null, error: err, finished_at: now(), stages_json: JSON.stringify(runFile?.stages || run.stages || []), summary_json: summary ? JSON.stringify(summary) : null});
    this.cancelling?.delete(id);
    logEvent(this.db, `run-${status}`, `Production run ${id} ${status}${err ? `: ${err}` : ''}`, {episodeId: run.episodeId, runId: id});
    this.kick();
  }

  cancel(id) {
    const run = this.get(id);
    if (!run) throw Object.assign(new Error('run not found'), {status: 404});
    if (run.status === 'queued') { this.#update(id, {status: 'cancelled', finished_at: now()}); logEvent(this.db, 'run-cancelled', `Production run ${id} cancelled before starting`, {episodeId: run.episodeId, runId: id}); return this.get(id); }
    if (run.status !== 'running') throw Object.assign(new Error(`run is ${run.status}; only queued or running runs can be cancelled`), {status: 409});
    (this.cancelling ??= new Set()).add(id);
    const pid = this.children.get(id)?.pid ?? this.db.prepare('SELECT pid FROM runs WHERE id = ?').get(id)?.pid;
    if (isAlive(pid)) killTree(pid);
    return this.get(id);
  }

  // Called once at startup.
  recover() {
    const report = {watching: [], adopted: [], interrupted: [], queued: 0};
    for (const r of this.db.prepare(`SELECT * FROM runs WHERE status = 'running'`).all()) {
      if (isAlive(r.pid)) { report.watching.push(r.id); this.#watch(r.id, r.pid); continue; }
      this.#finish(r.id, null);
      (this.get(r.id).status === 'interrupted' ? report.interrupted : report.adopted).push(r.id);
    }
    report.queued = this.db.prepare(`SELECT COUNT(*) AS n FROM runs WHERE status = 'queued'`).get().n;
    this.kick();
    return report;
  }

  // Stop supervising: the production processes keep running and are reconciled by recover() on the next start.
  stop() {
    this.stopped = true;
    for (const t of this.watchers.values()) clearInterval(t);
    this.watchers.clear();
    for (const c of this.children.values()) c.removeAllListeners('exit');
    this.children.clear();
  }
}
