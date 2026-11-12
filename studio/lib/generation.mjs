// Generation jobs, candidates, reviews and registry proposals (AP-84B1). Separate from production runs.
//
// Job status: queued -> running -> candidate_ready | failed | cancelled ; candidate_ready -> approved | rejected (human only).
// Approval is always an explicit human review with a note. It creates an append-only review record and a versioned
// REGISTRY PROPOSAL; it never writes to production/characters or production/environments (promotion is future work).
// Proposals for synthetic fixtures are recorded as not promotable.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import {PRODUCTION_ROOT} from '../../production/lib/runtime.mjs';
import {now, logEvent} from './db.mjs';
import {Quarantine, GEN_JOB_ID} from './quarantine.mjs';
import {adapterFor} from './gen-adapters.mjs';

export const GEN_STATUSES = ['queued', 'running', 'candidate_ready', 'failed', 'cancelled', 'approved', 'rejected'];
export const ASSET_TYPES = ['character-pose', 'environment'];
export const GEN_DECISIONS = ['approve', 'reject', 'regenerate'];
const SLUG = /^[a-z0-9][a-z0-9-]{0,63}$/;
const fail = (status, message) => Object.assign(new Error(message), {status});

const SCHEMA = `
CREATE TABLE IF NOT EXISTS gen_jobs (
  id TEXT PRIMARY KEY,
  episode_id TEXT REFERENCES episodes(id),
  asset_type TEXT NOT NULL,
  asset_key TEXT NOT NULL,             -- e.g. character-01/pose-07 or living-room-night
  description TEXT NOT NULL,
  status TEXT NOT NULL,
  adapter TEXT NOT NULL,
  initiated_by TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 1,
  parent_job_id TEXT REFERENCES gen_jobs(id),
  progress INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  retryable INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);
CREATE TABLE IF NOT EXISTS gen_candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES gen_jobs(id),
  name TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  media_type TEXT,
  width INTEGER, height INTEGER,
  synthetic INTEGER NOT NULL,
  provenance_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(job_id, name)
);
CREATE TABLE IF NOT EXISTS gen_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES gen_jobs(id),
  candidate_id INTEGER REFERENCES gen_candidates(id),
  decision TEXT NOT NULL,              -- approve | reject | regenerate
  note TEXT NOT NULL,
  reviewer TEXT NOT NULL,
  regenerated_job_id TEXT,
  proposal_id INTEGER,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gen_registry_proposals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES gen_jobs(id),
  candidate_id INTEGER NOT NULL REFERENCES gen_candidates(id),
  registry TEXT NOT NULL,              -- characters/character-01 or environments
  entry_key TEXT NOT NULL,             -- pose-07, living-room-night, ...
  version INTEGER NOT NULL,            -- next version for this entry; never reuses or replaces an existing one
  candidate_sha256 TEXT NOT NULL,
  promotable INTEGER NOT NULL,
  status TEXT NOT NULL,                -- proposed (promotion into the registry files is future work)
  reason TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(registry, entry_key, version)
);
CREATE INDEX IF NOT EXISTS gen_jobs_status ON gen_jobs(status, created_at);
`;
// Append-only guarantees at the database level.
const TRIGGERS = `
CREATE TRIGGER IF NOT EXISTS gen_reviews_no_update BEFORE UPDATE ON gen_reviews BEGIN SELECT RAISE(ABORT, 'gen_reviews is append-only'); END;
CREATE TRIGGER IF NOT EXISTS gen_reviews_no_delete BEFORE DELETE ON gen_reviews BEGIN SELECT RAISE(ABORT, 'gen_reviews is append-only'); END;
CREATE TRIGGER IF NOT EXISTS gen_proposals_no_delete BEFORE DELETE ON gen_registry_proposals BEGIN SELECT RAISE(ABORT, 'registry proposals are append-only'); END;
CREATE TRIGGER IF NOT EXISTS gen_candidates_no_update BEFORE UPDATE ON gen_candidates BEGIN SELECT RAISE(ABORT, 'candidates are immutable'); END;
`;

export const newGenJobId = () => {
  const d = new Date(), p = n => String(n).padStart(2, '0');
  return `g-${d.getUTCFullYear()}${p(d.getUTCMonth() + 1)}${p(d.getUTCDate())}-${p(d.getUTCHours())}${p(d.getUTCMinutes())}${p(d.getUTCSeconds())}-${crypto.randomBytes(3).toString('hex')}`;
};
const text = (v, name, min, max) => {
  if (typeof v !== 'string') throw fail(400, `${name} must be text`);
  const t = v.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '').trim();
  if (t.length < min || t.length > max) throw fail(400, `${name} must be ${min}–${max} characters`);
  return t;
};

// Validate the requested asset against the existing registries (read-only).
function parseAssetKey(assetType, assetKey) {
  if (assetType === 'character-pose') {
    const m = /^([a-z0-9][a-z0-9-]{0,63})\/([a-z0-9][a-z0-9-]{0,63})$/.exec(assetKey || '');
    if (!m) throw fail(400, 'assetKey for character-pose must be "<character-id>/<pose-key>", e.g. character-01/pose-07');
    if (!fs.existsSync(path.join(PRODUCTION_ROOT, 'characters', `${m[1]}.json`))) throw fail(422, `no registry for character "${m[1]}"`);
    return {registry: `characters/${m[1]}`, entryKey: m[2]};
  }
  if (assetType === 'environment') {
    if (!SLUG.test(assetKey || '')) throw fail(400, 'assetKey for environment must be a lowercase environment id');
    return {registry: 'environments', entryKey: assetKey};
  }
  throw fail(400, `assetType must be one of: ${ASSET_TYPES.join(', ')}`);
}

export function createGeneration({db, workspace, adapter = 'none', timeoutMs = 120000}) {
  db.exec(SCHEMA); db.exec(TRIGGERS);
  const quarantine = new Quarantine(workspace);
  const worker = adapterFor(adapter);
  let busy = false, stopped = false;

  const get = id => db.prepare('SELECT * FROM gen_jobs WHERE id = ?').get(id);
  const update = (id, fields) => {
    const cols = Object.keys(fields);
    db.prepare(`UPDATE gen_jobs SET ${cols.map(c => `${c} = ?`).join(', ')}, updated_at = ? WHERE id = ?`).run(...cols.map(c => fields[c]), now(), id);
  };
  const jobView = r => r && ({id: r.id, episodeId: r.episode_id, assetType: r.asset_type, assetKey: r.asset_key, description: r.description, status: r.status,
    adapter: r.adapter, initiatedBy: r.initiated_by, attempt: r.attempt, parentJobId: r.parent_job_id, progress: r.progress, error: r.error, retryable: !!r.retryable,
    createdAt: r.created_at, updatedAt: r.updated_at, startedAt: r.started_at, finishedAt: r.finished_at});
  const candidates = id => db.prepare('SELECT * FROM gen_candidates WHERE job_id = ? ORDER BY id').all(id).map(c => ({id: c.id, name: c.name, sha256: c.sha256, bytes: c.bytes,
    mediaType: c.media_type, width: c.width, height: c.height, synthetic: !!c.synthetic, provenance: JSON.parse(c.provenance_json), createdAt: c.created_at}));
  const reviews = id => db.prepare('SELECT * FROM gen_reviews WHERE job_id = ? ORDER BY id').all(id).map(r => ({id: r.id, candidateId: r.candidate_id, decision: r.decision,
    note: r.note, reviewer: r.reviewer, regeneratedJobId: r.regenerated_job_id, proposalId: r.proposal_id, createdAt: r.created_at}));
  const proposals = id => db.prepare('SELECT * FROM gen_registry_proposals WHERE job_id = ? ORDER BY id').all(id).map(p => ({id: p.id, candidateId: p.candidate_id, registry: p.registry,
    entryKey: p.entry_key, version: p.version, candidateSha256: p.candidate_sha256, promotable: !!p.promotable, status: p.status, reason: p.reason, createdAt: p.created_at}));
  const detail = id => { const j = jobView(get(id)); return j && {...j, candidates: candidates(id), reviews: reviews(id), proposals: proposals(id)}; };

  function create({episodeId = null, assetType, assetKey, description, initiatedBy = 'owner'}, {parent = null} = {}) {
    if (!ASSET_TYPES.includes(assetType)) throw fail(400, `assetType must be one of: ${ASSET_TYPES.join(', ')}`);
    parseAssetKey(assetType, assetKey);
    const desc = text(description, 'description', 3, 1000), who = text(initiatedBy, 'initiatedBy', 1, 60);
    if (episodeId !== null && episodeId !== undefined) {
      if (typeof episodeId !== 'string' || !db.prepare('SELECT 1 FROM episodes WHERE id = ?').get(episodeId)) throw fail(404, `episode not found: ${episodeId}`);
    }
    const id = newGenJobId(), t = now();
    db.prepare(`INSERT INTO gen_jobs (id, episode_id, asset_type, asset_key, description, status, adapter, initiated_by, attempt, parent_job_id, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)`).run(id, episodeId || null, assetType, assetKey, desc, worker.id, who, parent ? parent.attempt + 1 : 1, parent?.id ?? null, t, t);
    logEvent(db, 'gen-queued', `Generation job ${id} queued (${assetType} ${assetKey}, adapter ${worker.id})`, {episodeId: episodeId || null});
    queueMicrotask(() => kick());
    return detail(id);
  }

  async function kick() {
    if (busy || stopped) return;
    const next = db.prepare(`SELECT * FROM gen_jobs WHERE status = 'queued' ORDER BY created_at, id LIMIT 1`).get();
    if (!next) return;
    busy = true;
    try { await runJob(next); } finally { busy = false; }
    if (!stopped) queueMicrotask(() => kick());
  }

  async function runJob(job) {
    update(job.id, {status: 'running', started_at: now(), progress: 10});
    try {
      const outputs = await Promise.race([
        worker.generate({assetType: job.asset_type, assetKey: job.asset_key, description: job.description}, {attempt: job.attempt}),
        new Promise((_, reject) => setTimeout(() => reject(Object.assign(new Error(`generation timed out after ${timeoutMs} ms`), {retryable: true})), timeoutMs).unref?.()),
      ]);
      if (stopped || get(job.id).status !== 'running') return;          // cancelled or shutting down meanwhile
      if (!Array.isArray(outputs) || !outputs.length) throw new Error('worker returned no candidates');
      for (const o of outputs) {
        const w = quarantine.write(job.id, o.name, o.buffer);
        const provenance = {...o.provenance, jobId: job.id, adapter: worker.id, request: {assetType: job.asset_type, assetKey: job.asset_key, description: job.description}, sha256: w.sha256, createdAt: now()};
        db.prepare(`INSERT INTO gen_candidates (job_id, name, sha256, bytes, media_type, width, height, synthetic, provenance_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
          .run(job.id, w.name, w.sha256, w.bytes, w.mediaType, o.width ?? null, o.height ?? null, o.synthetic ? 1 : 0, JSON.stringify(provenance), now());
      }
      update(job.id, {status: 'candidate_ready', progress: 100, finished_at: now()});
      logEvent(db, 'gen-candidate-ready', `Generation job ${job.id}: ${outputs.length} candidate(s) ready for review`);
    } catch (e) {
      if (stopped && get(job.id).status === 'running') return;          // leave for restart recovery
      update(job.id, {status: 'failed', error: e.message, retryable: e.retryable ? 1 : 0, finished_at: now()});
      logEvent(db, 'gen-failed', `Generation job ${job.id} failed: ${e.message}`);
    }
  }

  function cancel(id) {
    const j = get(id);
    if (!j) throw fail(404, 'generation job not found');
    if (!['queued', 'running'].includes(j.status)) throw fail(409, `a ${j.status} job cannot be cancelled`);
    update(id, {status: 'cancelled', finished_at: now(), error: 'cancelled by the user'});
    logEvent(db, 'gen-cancelled', `Generation job ${id} cancelled`);
    return detail(id);
  }

  // Human review. approve -> approved + registry proposal (never a registry write); reject -> rejected;
  // regenerate -> rejected + a new queued job (attempt + 1). All decisions are append-only records.
  function review(id, {decision, candidateId, note, reviewer = 'owner'}) {
    const j = get(id);
    if (!j) throw fail(404, 'generation job not found');
    if (!GEN_DECISIONS.includes(decision)) throw fail(400, `decision must be one of: ${GEN_DECISIONS.join(', ')}`);
    if (j.status !== 'candidate_ready') throw fail(409, `only jobs with candidates ready can be reviewed (this job is ${j.status})`);
    const n = text(note, 'note', 3, 2000), who = text(reviewer, 'reviewer', 1, 60);
    let candidate = null, proposalId = null, regenerated = null;
    if (decision === 'approve') {
      candidate = db.prepare('SELECT * FROM gen_candidates WHERE id = ? AND job_id = ?').get(Number(candidateId), id);
      if (!candidate) throw fail(400, 'approve requires the candidateId of one of this job\'s candidates');
      if (quarantine.sha256(id, candidate.name) !== candidate.sha256) throw fail(409, 'candidate file is missing or changed since it was recorded; it cannot be approved');
      const {registry, entryKey} = parseAssetKey(j.asset_type, j.asset_key);
      const last = db.prepare('SELECT MAX(version) AS v FROM gen_registry_proposals WHERE registry = ? AND entry_key = ?').get(registry, entryKey).v;
      const version = Math.max(registryVersion(registry, entryKey), last || 0) + 1;      // always a NEW version
      const synthetic = !!candidate.synthetic;
      proposalId = Number(db.prepare(`INSERT INTO gen_registry_proposals (job_id, candidate_id, registry, entry_key, version, candidate_sha256, promotable, status, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?)`).run(id, candidate.id, registry, entryKey, version, candidate.sha256, synthetic ? 0 : 1,
        synthetic ? 'synthetic test fixture: must never be promoted into a registry' : 'awaiting promotion into the registry (future milestone)', now()).lastInsertRowid);
      update(id, {status: 'approved'});
    } else if (decision === 'reject') {
      update(id, {status: 'rejected'});
    } else {
      update(id, {status: 'rejected'});
      regenerated = create({episodeId: j.episode_id, assetType: j.asset_type, assetKey: j.asset_key, description: j.description, initiatedBy: who}, {parent: j}).id;
    }
    db.prepare(`INSERT INTO gen_reviews (job_id, candidate_id, decision, note, reviewer, regenerated_job_id, proposal_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`)
      .run(id, candidate?.id ?? null, decision, n, who, regenerated, proposalId, now());
    logEvent(db, `gen-review-${decision}`, `Generation job ${id}: ${decision} by ${who}${regenerated ? ` (new job ${regenerated})` : ''}`);
    return {...detail(id), regeneratedJobId: regenerated};
  }

  // Version already present in the real registry (read-only): an existing entry counts as version 1, or its "version".
  function registryVersion(registry, entryKey) {
    try {
      if (registry.startsWith('characters/')) {
        const reg = JSON.parse(fs.readFileSync(path.join(PRODUCTION_ROOT, `${registry}.json`), 'utf8'));
        const e = reg.poses?.[entryKey]; return e ? (Number(e.version) || 1) : 0;
      }
      const reg = JSON.parse(fs.readFileSync(path.join(PRODUCTION_ROOT, 'environments', 'environments.json'), 'utf8'));
      const e = reg.environments?.[entryKey]; return e ? (Number(e.version) || 1) : 0;
    } catch { return 0; }
  }

  // Restart: queued jobs resume; jobs left running were interrupted (in-process work cannot survive a restart).
  function recover() {
    const interrupted = db.prepare(`SELECT id FROM gen_jobs WHERE status = 'running'`).all().map(r => r.id);
    for (const id of interrupted) {
      update(id, {status: 'failed', error: 'interrupted: the studio stopped while this job was running', retryable: 1, finished_at: now()});
      logEvent(db, 'gen-interrupted', `Generation job ${id} interrupted by a restart`);
    }
    const queued = db.prepare(`SELECT COUNT(*) AS n FROM gen_jobs WHERE status = 'queued'`).get().n;
    queueMicrotask(() => kick());
    return {interrupted, queued};
  }

  const list = () => db.prepare('SELECT * FROM gen_jobs ORDER BY created_at DESC, id DESC LIMIT 200').all().map(jobView);
  const config = () => ({adapter: worker.id, ...worker.status(), assetTypes: ASSET_TYPES, decisions: GEN_DECISIONS,
    note: 'Approval creates a versioned registry proposal only; registries are never modified by the studio in AP-84B1.'});

  return {create, cancel, review, recover, list, detail, config, quarantine, kick, stop() { stopped = true; }, isJobId: id => GEN_JOB_ID.test(id)};
}
