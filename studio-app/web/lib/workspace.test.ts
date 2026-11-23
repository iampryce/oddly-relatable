// node --test: the workspace's banner, open sections, seat line and costs.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {bannerText, candidateCost, isOpen, jobLine, seatsLine, showLastError, TONE, workingText} from './workspace.ts';

test('a banner only for what truly blocks; work in progress is one quiet line; otherwise nothing', () => {
  assert.deepEqual(bannerText({blocker: {section: 'plan', title: 'Reference plan', message: 'Accept it.'}, running: ['Set']}),
    {tone: 'warn', text: 'Blocked at Reference plan: Accept it.'});
  assert.equal(bannerText({blocker: null, running: ['Set']}), null);
  assert.equal(bannerText({blocker: null, running: []}), null);
  assert.equal(workingText({blocker: null, running: ['Set', 'Production']}), 'Working: Set, Production.');
  assert.equal(workingText({running: []}), '');
});

test('the episode\'s last error only while it is in a failed stage', () => {
  assert.equal(showLastError({stage: 'production_failed', last_error: 'render: out of memory'}), true);
  assert.equal(showLastError({stage: 'video_review', last_error: 'render: out of memory'}), false, 'retried and fine since');
  assert.equal(showLastError({stage: 'production_failed', last_error: ''}), false);
});

test('finished sections start collapsed; the owner\'s toggle wins', () => {
  const s: any = {key: 'lines', open: false};
  assert.equal(isOpen(s, {}), false);
  assert.equal(isOpen(s, {lines: true}), true);
  assert.equal(isOpen({...s, open: true}, {lines: false}), false);
  assert.equal(TONE.failed, 'bad');
});

test('jobs and seats in words', () => {
  assert.equal(jobLine({id: 7, kind: 'set_candidate', status: 'failed', error: '401'}), 'set candidate #7 failed: 401');
  assert.equal(jobLine({id: 8, kind: 'audio_video_notes', status: 'running'}), 'audio video notes #8 running…');
  assert.deepEqual(seatsLine(4, 5), {text: '4 seats for 5 people: 1 seated person(s) will stand', short: true});
  assert.deepEqual(seatsLine(5, 5), {text: '5 seats for 5 people', short: false});
  assert.equal(seatsLine(1, 0).text, '1 seat');
  assert.equal(candidateCost({estimated_usd: 0.17}), 'image about $0.17');
  assert.equal(candidateCost({estimated_usd: 0.17, suggested: {estimated_usd: 0.0021}}), 'image about $0.17 · seat suggestion about $0.002');
});
