// node --test: the suggested-speakers review table (nothing saved until accepted; edits and character keys win).
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {acceptBody, confidenceText, confirmAmount, defaultValue, initialPicks, videoPrice, type SuggestRow} from './speakerSuggest.ts';

const row = (id: string, label: string, extra: Partial<SuggestRow> = {}): SuggestRow => ({line_id: id, start: 0, end: 1, text: 't',
  current: '', label, confidence: 0.8, level: 'high', character_key: null, character_name: null, ...extra});

test('the accepted value: the edit, else the character key, else the label', () => {
  const rows = [row('l1', 'Doctor'), row('l2', 'ann', {character_key: 'ann', character_name: 'Ann'}), row('l3', ''), row('l4', 'Nurse')];
  assert.equal(defaultValue(rows[1]), 'ann');
  const picked = new Set(['l1', 'l2', 'l3']);
  assert.deepEqual(acceptBody(rows, {l1: ' Surgeon '}, picked), [{line_id: 'l1', speaker: 'Surgeon'}, {line_id: 'l2', speaker: 'ann'}]);
  assert.deepEqual(acceptBody(rows, {}, new Set(), true).map(r => r.line_id), ['l1', 'l2', 'l4'], 'accept all skips empty rows');
});

test('rows picked at first: suggested and no speaker yet', () => {
  const picks = initialPicks([row('l1', 'Doctor'), row('l2', 'Nurse', {current: 'bob'}), row('l3', '')]);
  assert.deepEqual([...picks], ['l1']);
});

test('confidence and price texts', () => {
  assert.equal(confidenceText(row('l1', 'Doctor'), 'video'), 'high (80%)');
  assert.equal(confidenceText(row('l1', 'Doctor', {confidence: 0.4, level: 'low'}), 'text'), 'low (40%), text only');
  assert.equal(confidenceText(row('l1', ''), 'video'), 'no suggestion');
  const est = {usd_typical: 0.03, usd_max: 0.21};
  assert.equal(videoPrice(est, true, false), 'about $0.03, at most $0.21');
  assert.equal(videoPrice(est, false, true), 'free tier, $0.00');
  assert.equal(videoPrice(est, false, false), 'tick a tier first');
  assert.equal(confirmAmount(est, true), 0.21);
  assert.equal(confirmAmount(est, false), 0);
});
