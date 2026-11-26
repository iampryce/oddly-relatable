// node --test: the guided steps (order, all available), the help panel's next/back and the cost text.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {costText, currentStep, moveHelp, statusOf, STEPS} from './guide.ts';

test('eleven steps in order, all in the dashboard (10 quality check, 11 assembly)', () => {
  assert.deepEqual(STEPS.map(s => s.key), ['upload', 'acting', 'prompts', 'masters', 'sets', 'closeups', 'faces', 'movement', 'talking', 'quality', 'assembly']);
  assert.deepEqual(STEPS.filter(s => !s.available).map(s => s.key), []);
  assert.ok(STEPS.find(s => s.key === 'faces')!.help.join(' ').includes('screen-left'));
  assert.ok(STEPS.find(s => s.key === 'movement')!.help.join(' ').includes('living holds'));
  assert.ok(STEPS.find(s => s.key === 'sets')!.help.join(' ').includes('rotate'));
  assert.ok(STEPS.find(s => s.key === 'talking')!.help.join(' ').includes('Wan 2.2 Speech-to-Video'));
  for (const s of STEPS) assert.ok(s.what && s.why && s.before && s.help.length > 0, s.key);
});

test('current step is the first available one not done', () => {
  assert.equal(currentStep({steps: {}}), 0);
  assert.equal(currentStep({steps: {upload: {status: 'done'}, acting: {status: 'needs_approval'}}}), 1);
  const all = Object.fromEntries(STEPS.map(s => [s.key, {status: 'done'}]));
  assert.equal(currentStep({steps: all}), STEPS.length - 1);
  assert.equal(statusOf({steps: {x: {status: 'weird'}}}, 'x'), 'not_started');
});

test('help moves one instruction at a time across steps', () => {
  const n0 = STEPS[0].help.length;
  assert.deepEqual(moveHelp([0, 0], 1), [0, 1]);
  assert.deepEqual(moveHelp([0, n0 - 1], 1), [1, 0]);
  assert.deepEqual(moveHelp([1, 0], -1), [0, n0 - 1]);
  assert.deepEqual(moveHelp([0, 0], -1), [0, 0]);
  const last = STEPS.length - 1;
  assert.deepEqual(moveHelp([last, STEPS[last].help.length - 1], 1), [last, STEPS[last].help.length - 1]);
});

test('cost text', () => {
  assert.equal(costText({usd_typical: 0.21, usd_max: 1.1}), 'about $0.21, at most $1.10');
  assert.equal(costText({usd_typical: 0.0042, usd_max: 0.1224}), 'about $0.0042, at most $0.12');
  assert.equal(costText({usd: 0.08, label: '2 images x $0.04 = $0.08'}), '2 images x $0.04 = $0.08');
  assert.equal(costText(null), '');
});
