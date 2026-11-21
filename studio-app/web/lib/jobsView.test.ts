// node --test: Recent jobs collapses to the latest 10, and Show more reveals up to 40.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {recentRows} from './jobsView.ts';

test('recent jobs: latest 10, show more up to 40', () => {
  const jobs = Array.from({length: 55}, (_, i) => ({id: 55 - i}));
  assert.deepEqual(recentRows(jobs, false).map(j => j.id), Array.from({length: 10}, (_, i) => 55 - i));
  assert.equal(recentRows(jobs, true).length, 40);
  assert.equal(recentRows(jobs.slice(0, 4), false).length, 4);
});
