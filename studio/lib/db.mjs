// Studio database: a local SQLite file (Node's built-in node:sqlite, no dependency).
// Tables: episodes (records that point at approved story files), runs (production jobs), reviews (human decisions,
// append-only audit trail), events (recent activity). Story files themselves are never stored or modified here.
import {DatabaseSync} from 'node:sqlite';

const SCHEMA = `
CREATE TABLE IF NOT EXISTS episodes (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  story_file TEXT NOT NULL,          -- file name inside production/stories/
  story_sha256 TEXT NOT NULL,        -- story file hash when the record was created
  note TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  episode_id TEXT NOT NULL REFERENCES episodes(id),
  status TEXT NOT NULL,              -- queued | running | produced | qa-failed | failed | awaiting-approval | interrupted | cancelled
  story_file TEXT NOT NULL,
  story_sha256 TEXT NOT NULL,        -- story hash used for this run
  pid INTEGER,
  exit_code INTEGER,
  error TEXT,
  stages_json TEXT,                  -- last known stage list from the production run file
  summary_json TEXT,                 -- render / audio / qa summary when finished
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS runs_episode ON runs(episode_id, created_at);
CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(id),
  episode_id TEXT NOT NULL REFERENCES episodes(id),
  decision TEXT NOT NULL,            -- approved-next-step | changes-requested | rejected
  note TEXT NOT NULL,
  reviewer TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  kind TEXT NOT NULL,
  episode_id TEXT,
  run_id TEXT,
  message TEXT NOT NULL
);
`;

export function openDb(file) {
  const db = new DatabaseSync(file);
  db.exec('PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON;');
  db.exec(SCHEMA);
  return db;
}

export const now = () => new Date().toISOString();

export function logEvent(db, kind, message, {episodeId = null, runId = null} = {}) {
  db.prepare('INSERT INTO events (at, kind, episode_id, run_id, message) VALUES (?, ?, ?, ?, ?)').run(now(), kind, episodeId, runId, message);
}

// Row helpers: parse JSON columns into objects for the API.
export function runRow(r) {
  if (!r) return null;
  return {id: r.id, episodeId: r.episode_id, status: r.status, storyFile: r.story_file, storySha256: r.story_sha256, exitCode: r.exit_code, error: r.error,
    stages: r.stages_json ? JSON.parse(r.stages_json) : [], summary: r.summary_json ? JSON.parse(r.summary_json) : null,
    createdAt: r.created_at, startedAt: r.started_at, finishedAt: r.finished_at};
}
