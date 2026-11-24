// node --test: Recent jobs collapses to the latest 10, and Show more reveals up to 40.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {isOldFailure, quietJobs, recentRows} from './jobsView.ts';

test('recent jobs: latest 10, show more up to 40', () => {
  const jobs = Array.from({length: 55}, (_, i) => ({id: 55 - i}));
  assert.deepEqual(recentRows(jobs, false).map(j => j.id), Array.from({length: 10}, (_, i) => 55 - i));
  assert.equal(recentRows(jobs, true).length, 40);
  assert.equal(recentRows(jobs.slice(0, 4), false).length, 4);
});

test('quiet by default: old failures behind a count, routine successes not listed, nothing a live episode needs hidden', () => {
  const now = Date.parse('2026-11-23T12:00:00Z');
  const j = (id: number, kind: string, status: string, at: string, keep: string | null = null) =>
    ({id, kind, status, finished_at: at, keep_reason: keep});
  const jobs = [
    j(1, 'render_episode', 'failed', '2026-11-23T10:00:00Z'),                 // 2 h ago: shown
    j(2, 'scene_voice', 'failed', '2026-11-21T10:00:00Z'),                    // 2 days ago: hidden
    j(3, 'render_segment', 'failed', '2026-11-20T10:00:00Z', 'episode 14 still needs it'),   // kept: shown
    j(4, 'shot_key', 'succeeded', '2026-11-23T11:00:00Z'),                    // routine: not listed
    j(5, 'shot_prepare', 'succeeded', '2026-11-23T11:00:00Z'),
    j(6, 'shot_key', 'failed', '2026-11-23T11:30:00Z'),                       // a failed key is not routine: shown
    j(7, 'render_episode', 'succeeded', '2026-11-23T11:40:00Z'),
  ];
  const q = quietJobs(jobs, false, now);
  assert.deepEqual(q.failed.map(x => x.id), [1, 3, 6]);
  assert.equal(q.hiddenFailed, 1);
  assert.deepEqual(q.recent.map(x => x.id), [1, 3, 6, 7]);
  assert.equal(q.hiddenRoutine, 2);
  const all = quietJobs(jobs, true, now);
  assert.deepEqual(all.failed.map(x => x.id), [1, 2, 3, 6], 'Show them: every failure');
  assert.equal(all.hiddenFailed, 0);
  assert.equal(isOldFailure(j(9, 'x', 'failed', 'not a date'), now), false, 'no date: shown');
});
