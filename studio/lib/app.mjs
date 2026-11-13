// Studio HTTP application: JSON API, safe media serving, static dashboard. Built on node:http (no framework).
// Security: loopback only, Host-header check (blocks DNS rebinding), same-origin check and JSON content type on
// writes, bounded bodies, validated IDs and inputs, whitelisted media keys, no environment or paths exposed.
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {fileURLToPath} from 'node:url';
import {openDb, now, logEvent, runRow} from './db.mjs';
import {LocalStorage, RUN_ID} from './storage.mjs';
import {JobRunner, TERMINAL} from './jobs.mjs';
import {listStories, storyInfo} from './stories.mjs';
import {createGeneration} from './generation.mjs';
import {requirementsFor, publicRequirements} from './asset-intel.mjs';
import {createPromotion} from './promotion.mjs';

const PUBLIC = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'public');
const STATIC = {'/': 'index.html', '/index.html': 'index.html', '/app.js': 'app.js', '/styles.css': 'styles.css'};
const STATIC_TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8'};
const EPISODE_ID = /^[a-z0-9][a-z0-9-]{1,63}$/;
export const DECISIONS = ['approved-next-step', 'changes-requested', 'rejected'];
const REVIEWABLE = ['produced', 'qa-failed', 'awaiting-approval'];
const MAX_BODY = 16 * 1024;

const fail = (status, message, extra = {}) => Object.assign(new Error(message), {status, ...extra});
const cleanText = (v, name, min, max) => {
  if (typeof v !== 'string') throw fail(400, `${name} must be text`);
  const t = v.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '').trim();
  if (t.length < min || t.length > max) throw fail(400, `${name} must be ${min}–${max} characters`);
  return t;
};

export function createStudio({workspace, port = 4317, command, pollMs = 1000, seed = true, genAdapter = 'none', genTimeoutMs, assetSources, promotionLibrary} = {}) {
  const storage = new LocalStorage(workspace);
  const db = openDb(path.join(storage.root, 'studio.db'));
  const jobs = new JobRunner({db, storage, command, pollMs});
  // Generation (AP-84B1): separate jobs, quarantine and reviews; the adapter is server configuration, never chosen by clients.
  const gen = createGeneration({db, workspace: storage.root, adapter: genAdapter, sources: assetSources, ...(genTimeoutMs ? {timeoutMs: genTimeoutMs} : {})});
  // Registry promotion: owner-approved new versions only, never "current" (see lib/promotion.mjs).
  // assetSources / promotionLibrary are overridden only by tests (temporary registries and library).
  const promo = createPromotion({db, quarantine: gen.quarantine, workspace: storage.root, sources: assetSources, ...(promotionLibrary ? {libraryRoot: promotionLibrary} : {})});
  const allowedHosts = new Set([`127.0.0.1:${port}`, `localhost:${port}`, `[::1]:${port}`]);

  // ---------- data helpers
  const episodeRow = e => {
    if (!e) return null;
    const latest = db.prepare('SELECT * FROM runs WHERE episode_id = ? ORDER BY created_at DESC, id DESC LIMIT 1').get(e.id);
    const runs = db.prepare('SELECT COUNT(*) AS n FROM runs WHERE episode_id = ?').get(e.id).n;
    let story; try { story = storyInfo(e.story_file); } catch (err) { story = {valid: false, error: err.message}; }
    return {id: e.id, title: e.title, storyFile: e.story_file, storySha256: e.story_sha256, storyChanged: story.sha256 ? story.sha256 !== e.story_sha256 : null,
      note: e.note, createdAt: e.created_at, duration: story.duration ?? null, story, runs, latestRun: latest ? {...runRow(latest), review: reviewState(latest.id, latest.status)} : null};
  };
  const reviewsFor = runId => db.prepare('SELECT * FROM reviews WHERE run_id = ? ORDER BY id').all(runId)
    .map(r => ({id: r.id, runId: r.run_id, episodeId: r.episode_id, decision: r.decision, note: r.note, reviewer: r.reviewer, createdAt: r.created_at}));
  function reviewState(runId, status) {
    if (!REVIEWABLE.includes(status)) return {state: TERMINAL.includes(status) ? 'not-reviewable' : 'pending-run'};
    const last = db.prepare('SELECT decision, created_at FROM reviews WHERE run_id = ? ORDER BY id DESC LIMIT 1').get(runId);
    return last ? {state: last.decision, at: last.created_at} : {state: 'awaiting-review'};
  }
  const runDetail = id => {
    const run = jobs.get(id);
    if (!run) return null;
    const qa = storage.readJson(id, 'reports/qa-report.json');
    return {...run, review: reviewState(id, run.status), reviews: reviewsFor(id), artifacts: storage.listArtifacts(id),
      qa: qa ? {status: qa.status, failed: qa.failed, warnings: qa.warnings, checks: qa.checks, note: qa.note} : null};
  };

  // First start: register an episode for each valid story so the library is not empty (records only).
  if (seed && !db.prepare('SELECT COUNT(*) AS n FROM episodes').get().n) {
    for (const s of listStories().filter(s => s.valid)) {
      const id = String(s.id).toLowerCase().replace(/[^a-z0-9-]/g, '-').slice(0, 64);
      db.prepare('INSERT OR IGNORE INTO episodes (id, title, story_file, story_sha256, note, created_at) VALUES (?, ?, ?, ?, ?, ?)').run(id, s.title, s.file, s.sha256, 'registered automatically on first start', now());
      logEvent(db, 'episode-created', `Episode ${id} registered from ${s.file}`, {episodeId: id});
    }
  }

  // ---------- routes
  const routes = [
    ['GET', /^\/api\/health$/, () => ({ok: true, storage: storage.describe(), ffmpegConfigured: Boolean(process.env.FFMPEG && process.env.FFPROBE), time: now()})],
    ['GET', /^\/api\/overview$/, () => {
      const count = sql => db.prepare(sql).get().n;
      return {
        episodes: count('SELECT COUNT(*) AS n FROM episodes'), runs: count('SELECT COUNT(*) AS n FROM runs'),
        produced: count(`SELECT COUNT(*) AS n FROM runs WHERE status = 'produced'`),
        failed: count(`SELECT COUNT(*) AS n FROM runs WHERE status IN ('failed','qa-failed','interrupted')`),
        active: count(`SELECT COUNT(*) AS n FROM runs WHERE status IN ('queued','running')`),
        awaitingReview: db.prepare(`SELECT id, status FROM runs WHERE status IN ('produced','qa-failed','awaiting-approval')`).all().filter(r => reviewState(r.id, r.status).state === 'awaiting-review').length,
        events: db.prepare('SELECT * FROM events ORDER BY id DESC LIMIT 25').all().map(e => ({at: e.at, kind: e.kind, episodeId: e.episode_id, runId: e.run_id, message: e.message})),
        recentRuns: db.prepare('SELECT * FROM runs ORDER BY created_at DESC, id DESC LIMIT 8').all().map(r => ({...runRow(r), review: reviewState(r.id, r.status)})),
      };
    }],
    ['GET', /^\/api\/stories$/, () => listStories()],
    ['GET', /^\/api\/episodes$/, () => db.prepare('SELECT * FROM episodes ORDER BY created_at, id').all().map(episodeRow)],
    ['POST', /^\/api\/episodes$/, (m, body) => {
      const info = storyInfo(cleanText(body.storyFile, 'storyFile', 1, 120));
      if (!info.valid) throw fail(422, `story cannot be produced: ${info.error}`);
      const id = body.id === undefined ? String(info.id).toLowerCase() : cleanText(body.id, 'id', 2, 64);
      if (!EPISODE_ID.test(id)) throw fail(400, 'id must be lowercase letters, digits and hyphens (2–64)');
      if (db.prepare('SELECT 1 FROM episodes WHERE id = ?').get(id)) throw fail(409, `episode ${id} already exists`);
      const title = body.title === undefined ? info.title : cleanText(body.title, 'title', 1, 120);
      const note = body.note === undefined ? null : cleanText(body.note, 'note', 0, 500);
      db.prepare('INSERT INTO episodes (id, title, story_file, story_sha256, note, created_at) VALUES (?, ?, ?, ?, ?, ?)').run(id, title, info.file, info.sha256, note, now());
      logEvent(db, 'episode-created', `Episode ${id} created from ${info.file}`, {episodeId: id});
      return {status: 201, body: episodeRow(db.prepare('SELECT * FROM episodes WHERE id = ?').get(id))};
    }],
    ['GET', /^\/api\/episodes\/([a-z0-9-]+)$/, m => {
      const e = episodeRow(db.prepare('SELECT * FROM episodes WHERE id = ?').get(m[1]));
      if (!e) throw fail(404, 'episode not found');
      e.history = db.prepare('SELECT * FROM runs WHERE episode_id = ? ORDER BY created_at DESC, id DESC').all(m[1]).map(r => ({...runRow(r), review: reviewState(r.id, r.status)}));
      e.reviews = db.prepare('SELECT * FROM reviews WHERE episode_id = ? ORDER BY id DESC').all(m[1]).map(r => ({id: r.id, runId: r.run_id, decision: r.decision, note: r.note, reviewer: r.reviewer, createdAt: r.created_at}));
      return e;
    }],
    ['POST', /^\/api\/episodes\/([a-z0-9-]+)\/runs$/, m => ({status: 202, body: jobs.create(m[1])})],
    ['GET', /^\/api\/runs$/, () => db.prepare('SELECT * FROM runs ORDER BY created_at DESC, id DESC LIMIT 200').all().map(r => ({...runRow(r), review: reviewState(r.id, r.status)}))],
    ['GET', /^\/api\/runs\/(r-[0-9a-f-]+)$/, m => { if (!RUN_ID.test(m[1])) throw fail(400, 'invalid run id'); const r = runDetail(m[1]); if (!r) throw fail(404, 'run not found'); return r; }],
    ['GET', /^\/api\/runs\/(r-[0-9a-f-]+)\/log$/, (m, body, url) => {
      if (!RUN_ID.test(m[1]) || !jobs.get(m[1])) throw fail(404, 'run not found');
      const offset = Number(url.searchParams.get('offset') || 0);
      if (!Number.isInteger(offset) || offset < 0) throw fail(400, 'offset must be a non-negative integer');
      return storage.readLog(m[1], offset);
    }],
    ['POST', /^\/api\/runs\/(r-[0-9a-f-]+)\/cancel$/, m => { if (!RUN_ID.test(m[1])) throw fail(400, 'invalid run id'); return jobs.cancel(m[1]); }],
    // ---------- generation (AP-84B1)
    ['GET', /^\/api\/generation$/, () => {
      const count = st => db.prepare('SELECT COUNT(*) AS n FROM gen_jobs WHERE status = ?').get(st).n;
      return {...gen.config(), counts: Object.fromEntries(['queued', 'running', 'candidate_ready', 'failed', 'cancelled', 'approved', 'rejected'].map(st => [st, count(st)]))};
    }],
    ['GET', /^\/api\/generation\/jobs$/, () => gen.list()],
    ['POST', /^\/api\/generation\/jobs$/, (m, body) => ({status: 202, body: gen.create({episodeId: body.episodeId ?? null, assetType: body.assetType, assetKey: body.assetKey, description: body.description, initiatedBy: body.initiatedBy ?? 'owner', referencePackId: body.referencePackId ?? null})})],
    // ---------- asset intelligence (AP-84B2): read-only analysis, immutable reference packs, advisory validation
    ['GET', /^\/api\/generation\/requirements$/, (m, body, url) => {
      const story = url.searchParams.get('story');
      // Public view: no registry or artwork paths in responses (AP-84B2 correction).
      if (story) return publicRequirements(requirementsFor(story, assetSources));
      return listStories().map(st => publicRequirements(requirementsFor(st.file, assetSources)));
    }],
    ['GET', /^\/api\/generation\/reference-packs$/, () => gen.listPacks()],
    ['POST', /^\/api\/generation\/reference-packs$/, async (m, body) => ({status: 201, body: await gen.createPack({kind: body.kind, id: body.id, note: body.note ?? null, createdBy: body.createdBy ?? 'owner'})})],
    ['GET', /^\/api\/generation\/reference-packs\/(\d{1,9})$/, m => { const p = gen.packDetail(m[1]); if (!p) throw fail(404, 'reference pack not found'); return p; }],
    ['POST', /^\/api\/generation\/jobs\/(g-[0-9a-f-]+)\/validate$/, async m => { if (!gen.isJobId(m[1])) throw fail(400, 'invalid generation job id'); return {status: 201, body: await gen.validateJob(m[1], 'manual')}; }],
    ['GET', /^\/api\/generation\/jobs\/(g-[0-9a-f-]+)$/, m => { if (!gen.isJobId(m[1])) throw fail(400, 'invalid generation job id'); const d = gen.detail(m[1]); if (!d) throw fail(404, 'generation job not found'); return {...d, promotions: promo.forJob(m[1])}; }],
    // ---------- registry promotion: checks (read-only), owner promotion with a note, history
    ['GET', /^\/api\/generation\/proposals\/(\d{1,9})\/promotion-check$/, async m => promo.check(m[1])],
    ['POST', /^\/api\/generation\/proposals\/(\d{1,9})\/promote$/, async (m, body) => ({status: 201, body: await promo.promote(m[1], {note: body.note, promotedBy: body.promotedBy ?? 'owner',
      approval: body.approval, feet: body.feet, figureHeight: body.figureHeight, confirm: body.confirm})})],
    ['GET', /^\/api\/generation\/promotions$/, () => promo.list()],
    ['POST', /^\/api\/generation\/jobs\/(g-[0-9a-f-]+)\/cancel$/, m => { if (!gen.isJobId(m[1])) throw fail(400, 'invalid generation job id'); return gen.cancel(m[1]); }],
    ['POST', /^\/api\/generation\/jobs\/(g-[0-9a-f-]+)\/reviews$/, (m, body) => { if (!gen.isJobId(m[1])) throw fail(400, 'invalid generation job id'); return {status: 201, body: gen.review(m[1], {decision: body.decision, candidateId: body.candidateId, note: body.note, reviewer: body.reviewer ?? 'owner'})}; }],
    ['POST', /^\/api\/runs\/(r-[0-9a-f-]+)\/reviews$/, (m, body) => {
      if (!RUN_ID.test(m[1])) throw fail(400, 'invalid run id');
      const run = jobs.get(m[1]);
      if (!run) throw fail(404, 'run not found');
      if (!REVIEWABLE.includes(run.status)) throw fail(409, `a ${run.status} run cannot be reviewed; review a produced, QA-failed or awaiting-approval run`);
      if (!DECISIONS.includes(body.decision)) throw fail(400, `decision must be one of: ${DECISIONS.join(', ')}`);
      const note = cleanText(body.note, 'note', 3, 2000);
      const reviewer = body.reviewer === undefined ? 'owner' : cleanText(body.reviewer, 'reviewer', 1, 60);
      // Recording a decision never approves anything in the renderer and never publishes.
      db.prepare('INSERT INTO reviews (run_id, episode_id, decision, note, reviewer, created_at) VALUES (?, ?, ?, ?, ?, ?)').run(run.id, run.episodeId, body.decision, note, reviewer, now());
      logEvent(db, `review-${body.decision}`, `Review of ${run.id}: ${body.decision} by ${reviewer}`, {episodeId: run.episodeId, runId: run.id});
      return {status: 201, body: runDetail(run.id)};
    }],
  ];

  // ---------- media (Range support so the MP4 plays and seeks in the browser)
  function serveMedia(req, res, runId, key) {
    if (!RUN_ID.test(runId)) return send(res, 400, {error: 'invalid run id'});
    const st = storage.stat(runId, key);
    if (!st) return send(res, 404, {error: 'not found'});
    const headers = {'Content-Type': st.type, 'Accept-Ranges': 'bytes', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'};
    const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || '');
    if (m && (m[1] || m[2])) {
      let start = m[1] ? Number(m[1]) : st.size - Number(m[2]), end = m[1] && m[2] ? Number(m[2]) : st.size - 1;
      if (!m[1]) end = st.size - 1;
      if (start < 0 || start >= st.size || end < start) { res.writeHead(416, {'Content-Range': `bytes */${st.size}`}); return res.end(); }
      end = Math.min(end, st.size - 1);
      res.writeHead(206, {...headers, 'Content-Range': `bytes ${start}-${end}/${st.size}`, 'Content-Length': end - start + 1});
      return storage.open(runId, key, {start, end}).pipe(res);
    }
    res.writeHead(200, {...headers, 'Content-Length': st.size});
    storage.open(runId, key).pipe(res);
  }

  // Quarantined candidates: whitelisted names only, served as data (never executed), never cached.
  function serveCandidate(res, jobId, name) {
    if (!gen.isJobId(jobId)) return send(res, 400, {error: 'invalid generation job id'});
    const st = gen.quarantine.stat(jobId, name);
    if (!st) return send(res, 404, {error: 'not found'});
    res.writeHead(200, {'Content-Type': st.type, 'Content-Length': st.size, 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Content-Disposition': 'inline'});
    gen.quarantine.open(jobId, name).pipe(res);
  }

  function send(res, status, body) {
    const data = JSON.stringify(body);
    res.writeHead(status, {'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Content-Length': Buffer.byteLength(data)});
    res.end(data);
  }
  const readBody = req => new Promise((resolve, reject) => {
    // Over the limit: keep draining (discarding) so the client still receives a clean 413 response.
    let size = 0, tooBig = false; const chunks = [];
    req.on('data', c => { size += c.length; if (size > MAX_BODY) { tooBig = true; chunks.length = 0; } else if (!tooBig) chunks.push(c); });
    req.on('end', () => { if (tooBig) return reject(fail(413, 'request body too large')); if (!chunks.length) return resolve({}); try { const v = JSON.parse(Buffer.concat(chunks).toString('utf8')); resolve(v && typeof v === 'object' && !Array.isArray(v) ? v : {}); } catch { reject(fail(400, 'body must be a JSON object')); } });
    req.on('error', reject);
  });

  const server = http.createServer(async (req, res) => {
    try {
      if (!allowedHosts.has(String(req.headers.host || '').toLowerCase())) return send(res, 421, {error: 'unexpected Host header'});
      const url = new URL(req.url, `http://${req.headers.host}`);
      const p = decodeURIComponent(url.pathname);
      if (p.includes('\0')) return send(res, 400, {error: 'bad path'});
      if (req.method === 'GET' && STATIC[url.pathname]) {
        const f = path.join(PUBLIC, STATIC[url.pathname]);
        res.writeHead(200, {'Content-Type': STATIC_TYPES[path.extname(f)], 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
          'Content-Security-Policy': "default-src 'self'; img-src 'self'; media-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"});
        return fs.createReadStream(f).pipe(res);
      }
      const media = /^\/media\/runs\/([^/]+)\/(.+)$/.exec(url.pathname);
      if (req.method === 'GET' && media) return serveMedia(req, res, media[1], media[2]);
      const genMedia = /^\/media\/generation\/([^/]+)\/([^/]+)$/.exec(url.pathname);
      if (req.method === 'GET' && genMedia) return serveCandidate(res, genMedia[1], genMedia[2]);
      if (!url.pathname.startsWith('/api/')) return send(res, 404, {error: 'not found'});
      let body = {};
      if (req.method === 'POST') {
        const origin = req.headers.origin;
        if (origin && !allowedHosts.has(origin.replace(/^https?:\/\//, '').toLowerCase())) return send(res, 403, {error: 'cross-origin request refused'});
        if (!/^application\/json\b/i.test(req.headers['content-type'] || '')) return send(res, 415, {error: 'content-type must be application/json'});
        body = await readBody(req);
      } else if (req.method !== 'GET') return send(res, 405, {error: 'method not allowed'});
      for (const [method, re, handler] of routes) {
        const m = re.exec(url.pathname);
        if (!m || method !== req.method) continue;
        const out = await handler(m, body, url);
        return out && out.status && out.body !== undefined ? send(res, out.status, out.body) : send(res, 200, out);
      }
      return send(res, 404, {error: 'not found'});
    } catch (e) {
      const status = e.status || 500;
      send(res, status, {error: status === 500 ? 'internal error' : e.message, ...(e.runId ? {runId: e.runId} : {}), ...(e.details && status !== 500 ? {details: e.details} : {})});
      if (status === 500) console.error(e);
    }
  });

  return {
    server, db, jobs, storage, gen,
    async listen(host = '127.0.0.1') {
      if (!['127.0.0.1', '::1', 'localhost'].includes(host)) throw new Error('The studio only binds to a loopback address');
      const recovered = jobs.recover();
      recovered.generation = gen.recover();
      await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, host, resolve); });
      return recovered;
    },
    async close() { jobs.stop(); gen.stop(); await new Promise(r => server.close(() => r())); server.closeAllConnections?.(); db.close(); },
  };
}
