// Registry promotion (implements docs/oddly-relatable/REGISTRY-PROMOTION-DESIGN.md with the owner decisions of 2026-11-13).
//
// An approved, promotable proposal becomes a NEW VERSION in the registry file, recorded under a top-level
// "promotions" map. It never becomes "current" here:
//   - the production engine reads only registry.poses / registry.environments, so stories cannot pick a promoted
//     version up by accident, and the engine's registry validation (every pose needs file, feet, figureHeight)
//     is unaffected;
//   - making a version current needs a successful preview render AND a separate owner approval (decision 4),
//     which is a later milestone.
//
// Safety: human decision with a note; promotable proposals only (never synthetic fixtures); candidate hash,
// validation (no "fail"), reference pack and version freedom are re-checked; the asset is copied write-once into
// the generated library; the registry is written via temp file + rename after verifying that every byte before
// the promotions block is unchanged; a backup of the previous registry is kept in the studio workspace; the
// registry's hash must not have changed since the checks (concurrency). Append-only audit (gen_promotions).
// Character poses only for now: the owner decisions cover generated poses, not environments.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {REPO_ROOT, PRODUCTION_ROOT} from '../../production/lib/runtime.mjs';
import {loadRegistry} from '../../production/lib/character.mjs';
import {now, logEvent} from './db.mjs';
import {measureImage, verifyPack} from './asset-intel.mjs';

export const PROMOTION_APPROVAL = 'APPROVED_WORKING_TEST_ASSET';        // owner decision 2 (2026-11-13)
export const DEFAULT_LIBRARY = path.join(REPO_ROOT, 'bible', 'concepts', 'lookdev-richenv', 'generated');   // owner decision 3
const fail = (status, message, extra = {}) => Object.assign(new Error(message), {status, ...extra});
const sha = buf => crypto.createHash('sha256').update(buf).digest('hex');
const rel = abs => path.relative(REPO_ROOT, abs).split(path.sep).join('/');
const inside = (child, parent) => { const r = path.relative(parent, child); return r && !r.startsWith('..') && !path.isAbsolute(r); };

const SCHEMA = `
CREATE TABLE IF NOT EXISTS gen_promotions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  proposal_id INTEGER NOT NULL UNIQUE REFERENCES gen_registry_proposals(id),
  job_id TEXT NOT NULL REFERENCES gen_jobs(id),
  candidate_id INTEGER NOT NULL REFERENCES gen_candidates(id),
  registry TEXT NOT NULL,              -- characters/character-01
  entry_key TEXT NOT NULL,             -- 07
  version INTEGER NOT NULL,
  asset_file TEXT NOT NULL,            -- repository-relative (internal; not returned by the API)
  asset_sha256 TEXT NOT NULL,
  registry_sha256_before TEXT NOT NULL,
  registry_sha256_after TEXT NOT NULL,
  backup_file TEXT NOT NULL,           -- workspace-relative backup of the previous registry
  approval TEXT NOT NULL,
  feet_json TEXT NOT NULL,
  figure_height INTEGER NOT NULL,
  validation_id INTEGER NOT NULL,
  review_id INTEGER NOT NULL,
  note TEXT NOT NULL,
  promoted_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(registry, entry_key, version)
);
CREATE TRIGGER IF NOT EXISTS gen_promotions_no_update BEFORE UPDATE ON gen_promotions BEGIN SELECT RAISE(ABORT, 'promotions are append-only'); END;
CREATE TRIGGER IF NOT EXISTS gen_promotions_no_delete BEFORE DELETE ON gen_promotions BEGIN SELECT RAISE(ABORT, 'promotions are append-only'); END;
`;

// Insert or replace the trailing top-level "promotions" block as text, so every existing byte of the registry is kept.
export function writePromotionsBlock(text, promotions) {
  const before = JSON.parse(text);
  const keys = Object.keys(before);
  if (keys.includes('promotions') && keys[keys.length - 1] !== 'promotions') throw fail(409, 'registry has a "promotions" key that is not last; refusing to edit it');
  const block = JSON.stringify(promotions, null, 2).split('\n').join('\n  ');
  let prefix;
  if (keys.includes('promotions')) {
    const i = text.lastIndexOf('\n  "promotions":');
    if (i < 0) throw fail(409, 'cannot locate the "promotions" block in the registry text');
    prefix = text.slice(0, i);                                     // ends with the "," after the previous key
    if (!prefix.trimEnd().endsWith(',')) throw fail(409, 'unexpected registry layout before "promotions"');
    prefix = prefix.trimEnd();
  } else {
    const close = text.lastIndexOf('}');
    prefix = text.slice(0, close).trimEnd() + ',';
  }
  const out = `${prefix}\n  "promotions": ${block}\n}\n`;
  // Verification: identical bytes up to the promotions block, identical values for every other key.
  const after = JSON.parse(out);
  const keep = keys.includes('promotions') ? prefix : text.slice(0, text.lastIndexOf('}')).trimEnd();
  if (!out.startsWith(keep)) throw fail(500, 'registry edit would change existing bytes; aborted');
  for (const k of keys) if (k !== 'promotions' && JSON.stringify(after[k]) !== JSON.stringify(before[k])) throw fail(500, `registry edit would change "${k}"; aborted`);
  if (JSON.stringify(after.promotions) !== JSON.stringify(promotions)) throw fail(500, 'promotions block did not round-trip; aborted');
  return out;
}

export function createPromotion({db, quarantine, workspace, sources = {}, libraryRoot = DEFAULT_LIBRARY}) {
  const charactersDir = sources.charactersDir || path.join(PRODUCTION_ROOT, 'characters');
  const library = path.resolve(libraryRoot);
  // The library must be inside the repository and never inside the renderer or the production engine.
  if (!inside(library, REPO_ROOT)) throw new Error('promotion library must be inside the repository');
  for (const p of ['skills', 'production'].map(d => path.join(REPO_ROOT, d))) if (library === p || inside(library, p)) throw new Error('promotion library must not be inside skills/ or production/');
  const backups = path.join(path.resolve(workspace), 'registry-backups');
  db.exec(SCHEMA);

  const proposalRow = id => db.prepare('SELECT * FROM gen_registry_proposals WHERE id = ?').get(Number(id));
  const view = r => r && ({id: r.id, proposalId: r.proposal_id, jobId: r.job_id, candidateId: r.candidate_id, registry: r.registry, entryKey: r.entry_key, version: r.version,
    asset: path.basename(r.asset_file), assetSha256: r.asset_sha256, registrySha256Before: r.registry_sha256_before, registrySha256After: r.registry_sha256_after,
    approval: r.approval, feet: JSON.parse(r.feet_json), figureHeight: r.figure_height, validationId: r.validation_id, reviewId: r.review_id, current: false,
    note: r.note, promotedBy: r.promoted_by, createdAt: r.created_at});

  // Pre-promotion checks (read-only). Returns every check, the plan, and measured defaults for feet and figure height.
  async function check(proposalId) {
    const checks = [], add = (id, status, detail) => checks.push({id, status, detail});
    const p = proposalRow(proposalId);
    if (!p) throw fail(404, 'registry proposal not found');
    const plan = {proposalId: p.id, registry: p.registry, entryKey: p.entry_key, version: p.version};
    add('proposal', p.status === 'proposed' ? 'pass' : 'fail', `proposal status is "${p.status}"`);
    add('promotable', p.promotable ? 'pass' : 'fail', p.promotable ? 'proposal is promotable' : `not promotable: ${p.reason}`);
    const done = db.prepare('SELECT id FROM gen_promotions WHERE proposal_id = ?').get(p.id);
    add('not-promoted-yet', done ? 'fail' : 'pass', done ? `already promoted (promotion ${done.id})` : 'no earlier promotion of this proposal');
    const isPose = p.registry.startsWith('characters/');
    add('asset-type', isPose ? 'pass' : 'fail', isPose ? 'character pose' : 'only generated character poses can be promoted (owner decisions of 2026-11-13 cover poses)');
    const job = db.prepare('SELECT * FROM gen_jobs WHERE id = ?').get(p.job_id);
    const review = db.prepare(`SELECT * FROM gen_reviews WHERE job_id = ? AND decision = 'approve' AND candidate_id = ? ORDER BY id DESC`).get(p.job_id, p.candidate_id);
    add('human-approval', job?.status === 'approved' && review ? 'pass' : 'fail', review ? `candidate approved by ${review.reviewer}: "${review.note}"` : 'no human approval of this candidate');
    const cand = db.prepare('SELECT * FROM gen_candidates WHERE id = ?').get(p.candidate_id);
    const qsha = cand ? quarantine.sha256(p.job_id, cand.name) : null;
    add('candidate-file', qsha && qsha === p.candidate_sha256 ? 'pass' : 'fail', qsha ? (qsha === p.candidate_sha256 ? 'quarantined file matches the approved hash' : 'quarantined file changed since approval') : 'quarantined file is missing');
    add('synthetic', cand && !cand.synthetic ? 'pass' : 'fail', cand?.synthetic ? 'synthetic test fixture: never promotable' : 'not a synthetic fixture');
    const v = db.prepare('SELECT * FROM gen_validations WHERE candidate_id = ? ORDER BY id DESC').get(p.candidate_id);
    add('validation', v && v.candidate_sha256 === p.candidate_sha256 && v.status !== 'fail' ? 'pass' : 'fail',
      v ? `latest validation ${v.id} is "${v.status}"${v.candidate_sha256 !== p.candidate_sha256 ? ' (for a different file)' : ''}` : 'candidate has never been validated');
    if (job?.reference_pack_id) {
      const pk = db.prepare('SELECT items_json FROM gen_reference_packs WHERE id = ?').get(job.reference_pack_id);
      const ver = verifyPack(JSON.parse(pk.items_json));
      add('reference-pack', ver.ok ? 'pass' : 'fail', ver.ok ? `reference pack ${job.reference_pack_id} still verifies` : `reference pack ${job.reference_pack_id} has drifted: ${ver.results.filter(r => r.state !== 'ok').map(r => `${r.ref} ${r.state}`).join(', ')}`);
    } else add('reference-pack', 'pass', 'job used the current registry (no recorded pack)');
    let regText = null, reg = null, regFile = null;
    if (isPose) {
      regFile = path.join(charactersDir, `${p.registry.slice('characters/'.length)}.json`);
      try { regText = fs.readFileSync(regFile, 'utf8'); reg = JSON.parse(regText); } catch {}
    }
    add('registry', reg ? 'pass' : 'fail', reg ? `registry ${p.registry} readable` : `registry ${p.registry} not found or invalid`);
    if (reg) {
      const existing = reg.poses?.[p.entry_key], taken = new Set(Object.keys(reg.promotions?.[p.entry_key] || {}).map(Number));
      if (existing) taken.add(Number(existing.version) || 1);
      add('version-free', taken.has(p.version) ? 'fail' : 'pass', taken.has(p.version) ? `version ${p.version} of ${p.entry_key} already exists` : `version ${p.version} of ${p.entry_key} is free`);
      plan.registrySha256 = sha(Buffer.from(regText));
    }
    let dest = null;
    if (isPose) {
      const name = `${p.entry_key.startsWith('pose-') ? p.entry_key : `pose-${p.entry_key}`}_v${p.version}.png`;
      dest = path.join(library, p.registry.slice('characters/'.length), name);
      plan.asset = name;
      add('destination', fs.existsSync(dest) ? 'fail' : 'pass', fs.existsSync(dest) ? `${name} already exists in the generated library (write-once)` : `${name} will be created in the generated library`);
    }
    let measured = null;
    if (cand && qsha) {
      try { const m = await measureImage(quarantine.stat(p.job_id, cand.name).file); measured = m.feet && m.silhouette ? {feet: m.feet, figureHeight: m.silhouette.height, width: m.width, height: m.height} : null; } catch {}
    }
    add('measurements', measured ? 'pass' : 'fail', measured ? `measured feet ${measured.feet.x},${measured.feet.y}; figure height ${measured.figureHeight} px` : 'feet anchor and figure height could not be measured');
    return {ok: checks.every(c => c.status === 'pass'), checks, plan, measured, approval: PROMOTION_APPROVAL, current: false,
      notice: 'Promotion adds a new version to the registry; it does not become current. Making it current needs a successful preview render and a separate owner approval.',
      _internal: {regFile, dest, cand, review, validation: v}};
  }
  const publicCheck = ({_internal, ...rest}) => rest;

  async function promote(proposalId, {note, promotedBy = 'owner', approval = PROMOTION_APPROVAL, feet, figureHeight, confirm} = {}) {
    if (confirm !== true) throw fail(400, 'promotion requires confirm: true (an explicit owner decision)');
    if (approval !== PROMOTION_APPROVAL) throw fail(400, `generated poses start as ${PROMOTION_APPROVAL} (owner decision of 2026-11-13)`);
    const n = typeof note === 'string' ? note.trim() : '';
    if (n.length < 3 || n.length > 2000) throw fail(400, 'note must be 3–2000 characters');
    const who = typeof promotedBy === 'string' && promotedBy.trim() ? promotedBy.trim().slice(0, 60) : 'owner';
    const c = await check(proposalId);
    if (!c.ok) throw fail(409, 'pre-promotion checks failed', {details: publicCheck(c)});
    const {regFile, dest, cand, review, validation} = c._internal, p = proposalRow(proposalId);
    const f = feet ?? c.measured.feet, fh = figureHeight ?? c.measured.figureHeight;
    if (!f || !Number.isInteger(f.x) || !Number.isInteger(f.y) || f.x < 0 || f.y < 0 || f.x >= c.measured.width || f.y >= c.measured.height) throw fail(400, 'feet must be integer pixel coordinates inside the image');
    if (!Number.isInteger(fh) || fh <= 0 || fh > c.measured.height) throw fail(400, 'figureHeight must be a positive integer no larger than the image height');

    // 1. Copy the candidate write-once into the generated library, verifying its hash.
    const bytes = fs.readFileSync(quarantine.stat(p.job_id, cand.name).file);
    if (sha(bytes) !== p.candidate_sha256) throw fail(409, 'candidate changed during promotion');
    fs.mkdirSync(path.dirname(dest), {recursive: true});
    fs.writeFileSync(dest, bytes, {flag: 'wx'});
    let replaced = false;                                            // true once the registry file has been swapped
    try {
      // 2. Registry: concurrency check, text-preserving edit, temp file + verify + backup + rename.
      const text = fs.readFileSync(regFile, 'utf8');
      if (sha(Buffer.from(text)) !== c.plan.registrySha256) throw fail(409, 'registry changed since the checks; nothing was promoted');
      const reg = JSON.parse(text);
      const promotions = structuredClone(reg.promotions || {});
      promotions[p.entry_key] = {...(promotions[p.entry_key] || {}), [String(p.version)]: {
        file: rel(dest), sha256: p.candidate_sha256, width: c.measured.width, height: c.measured.height, feet: {x: f.x, y: f.y}, figureHeight: fh,
        approval: PROMOTION_APPROVAL, status: 'PROMOTED, NOT CURRENT (needs a successful preview render and owner approval to become current)',
        source: {jobId: p.job_id, candidateId: p.candidate_id, candidateSha256: p.candidate_sha256, proposalId: p.id, reviewId: review.id, validationId: validation.id,
          referencePack: db.prepare('SELECT reference_pack_id FROM gen_jobs WHERE id = ?').get(p.job_id).reference_pack_id ?? null},
        promotedBy: who, promotedAt: now(), note: n}};
      const out = writePromotionsBlock(text, promotions);
      const tmp = `${regFile}.promote-tmp`;
      fs.writeFileSync(tmp, out, {flag: 'wx'});
      try { loadRegistry(tmp); }                                    // the production engine still accepts the registry
      catch (e) { fs.rmSync(tmp, {force: true}); throw fail(500, `promoted registry would not load in the production engine: ${e.message}`); }
      fs.mkdirSync(backups, {recursive: true});
      const backup = path.join(backups, `${Date.now()}-${path.basename(regFile)}`);
      fs.writeFileSync(backup, text, {flag: 'wx'});
      fs.renameSync(tmp, regFile);
      replaced = true;
      // 3. Verify what was written.
      const after = fs.readFileSync(regFile, 'utf8');
      if (after !== out || sha(fs.readFileSync(dest)) !== p.candidate_sha256) throw fail(500, 'post-promotion verification failed; restore from the backup');
      const id = Number(db.prepare(`INSERT INTO gen_promotions (proposal_id, job_id, candidate_id, registry, entry_key, version, asset_file, asset_sha256, registry_sha256_before, registry_sha256_after,
        backup_file, approval, feet_json, figure_height, validation_id, review_id, note, promoted_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
        .run(p.id, p.job_id, p.candidate_id, p.registry, p.entry_key, p.version, rel(dest), p.candidate_sha256, c.plan.registrySha256, sha(Buffer.from(after)),
          path.relative(path.resolve(workspace), backup).split(path.sep).join('/'), PROMOTION_APPROVAL, JSON.stringify({x: f.x, y: f.y}), fh, validation.id, review.id, n, who, now()).lastInsertRowid);
      db.prepare(`UPDATE gen_registry_proposals SET status = 'promoted' WHERE id = ?`).run(p.id);
      logEvent(db, 'gen-promoted', `Proposal ${p.id} promoted by ${who}: ${p.registry} ${p.entry_key} v${p.version} (${PROMOTION_APPROVAL}, not current)`);
      return {...view(db.prepare('SELECT * FROM gen_promotions WHERE id = ?').get(id)),
        nextSteps: ['Update the asset register (ASSET_REGISTER.md) and the project records, then commit after review.',
          'To make this version current: a successful preview render with it, then a separate owner approval (not built yet).']};
    } catch (e) {
      // Before the registry swap nothing was promoted: remove the asset this call created (it did not exist before).
      // After the swap the registry already points at the asset, so it is kept and the error says to restore the backup.
      if (!replaced) fs.rmSync(dest, {force: true});
      else e.message = `${e.message} (the registry was already replaced; its previous version is in the studio workspace registry-backups)`;
      throw e;
    }
  }

  const list = () => db.prepare('SELECT * FROM gen_promotions ORDER BY id DESC LIMIT 200').all().map(view);
  const forJob = jobId => db.prepare('SELECT * FROM gen_promotions WHERE job_id = ? ORDER BY id').all(jobId).map(view);
  return {check: async id => publicCheck(await check(id)), promote, list, forJob};
}
