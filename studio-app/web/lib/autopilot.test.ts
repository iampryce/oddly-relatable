// node --test: the autopilot panel's words, the budget parsing and bar, the buttons per status, the provider badges,
// the final cut's shot list and the quality check's lines.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {apStatus, budgetPercent, budgetText, checkSummary, controls, issueText, lengthText, parseBudget, providerBadge,
  sourceText, startConfirmText} from './autopilot.ts';

test('status words and buttons', () => {
  assert.equal(apStatus({status: 'waiting'}).text, 'Waiting for you');
  assert.equal(apStatus({status: 'nonsense'}).text, 'Not started');
  assert.deepEqual(controls({status: 'off'}), {start: true, pause: false, resume: false, stop: false});
  assert.deepEqual(controls({status: 'running'}), {start: false, pause: true, resume: false, stop: true});
  assert.deepEqual(controls({status: 'waiting'}), {start: false, pause: true, resume: false, stop: true});
  assert.deepEqual(controls({status: 'paused'}), {start: false, pause: false, resume: true, stop: true});
  assert.deepEqual(controls({status: 'finished'}), {start: true, pause: false, resume: false, stop: false});
});

test('budget text, bar and parsing', () => {
  assert.equal(budgetText({budget_usd: 10, spent_usd: 1.2, remaining_usd: 8.8}), '$1.20 of $10.00 used · $8.80 left');
  assert.equal(budgetText({}), 'No budget set yet');
  assert.equal(budgetPercent({budget_usd: 10, spent_usd: 2.5}), 25);
  assert.equal(budgetPercent({budget_usd: 10, spent_usd: 12}), 100);
  assert.equal(parseBudget('$12.50'), 12.5);
  assert.equal(parseBudget('0'), null);
  assert.equal(parseBudget('501'), null);
  assert.equal(parseBudget('1.234'), null);
  assert.equal(parseBudget('abc'), null);
  assert.ok(startConfirmText(10).includes('$10.00'));
  assert.ok(startConfirmText(10).includes('never approves'));
});

test('providers, shot list and quality lines', () => {
  assert.deepEqual(providerBadge({ready: true}), {text: 'Ready', tone: 'good'});
  assert.deepEqual(providerBadge({ready: false, essential: true}), {text: 'Needed: not ready', tone: 'bad'});
  assert.deepEqual(providerBadge({ready: false, essential: false}), {text: 'Skipped', tone: 'warn'});
  assert.equal(sourceText({label: 'still, not animated'}), 'Still, not animated');
  assert.equal(lengthText({frames: 60}), '2.40 s');
  assert.equal(lengthText({seconds: 1.5}), '1.50 s');
  assert.equal(issueText({t: 1.24, severity: 'clear', kind: 'style', what: 'A nose appears.'}), '1.2 s · clear · style: A nose appears.');
  assert.deepEqual(checkSummary({}), {text: 'Not checked', tone: ''});
  assert.deepEqual(checkSummary({check: {issues: []}}), {text: 'No problems found', tone: 'good'});
  assert.deepEqual(checkSummary({check: {issues: [{severity: 'clear'}, {severity: 'possible'}]}}), {text: '2 problem(s), 1 clear', tone: 'bad'});
});
