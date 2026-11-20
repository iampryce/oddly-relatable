// node --test (Node strips the types): "Set speaker for selected" never labels rows the owner did not select.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {applyEdit, type Line, type LinesState} from './audioLines.ts';

const line = (id: string, start: number, words: string[], speaker = ''): Line => ({
  id, start, end: start + words.length * 0.5, text: words.join(' '), speaker,
  words: words.map((word, k) => ({start: start + k * 0.5, end: start + k * 0.5 + 0.4, word})),
});
const sample = (): Line[] => [line('l1', 0, ['to', 'my', 'niece']), line('l2', 2, ['I', 'leave', 'nothing']), line('l3', 4, ['thank', 'you'])];
const speakers = (s: LinesState) => s.lines.map(l => `${l.id}:${l.speaker}`);

test('bulk speaker labels exactly the selected rows', () => {
  const s = applyEdit({lines: sample(), selected: new Set([1, 2])}, {kind: 'speaker', speaker: 'ralph'});
  assert.deepEqual(speakers(s), ['l1:', 'l2:ralph', 'l3:ralph']);
  assert.equal(s.selected.size, 0);
});

test('a split clears the selection, so the old indices cannot label the shifted rows', () => {
  // select l2 and l3 (rows 1, 2), then split l1: l2 and l3 move down to rows 2, 3
  let s = applyEdit({lines: sample(), selected: new Set([1, 2])}, {kind: 'split', index: 0, word: 2});
  assert.deepEqual(s.lines.map(l => l.id), ['l1', 'l1b', 'l2', 'l3']);
  assert.equal(s.selected.size, 0);
  s = applyEdit(s, {kind: 'speaker', speaker: 'ralph'});
  assert.deepEqual(speakers(s), ['l1:', 'l1b:', 'l2:', 'l3:'], 'no row is labelled: the owner must select again');
});

test('a merge clears the selection', () => {
  let s = applyEdit({lines: sample(), selected: new Set([2])}, {kind: 'merge', index: 0});
  assert.deepEqual(s.lines.map(l => l.text), ['to my niece I leave nothing', 'thank you']);
  assert.equal(s.selected.size, 0);
  s = applyEdit(s, {kind: 'speaker', speaker: 'ralph'});
  assert.deepEqual(speakers(s), ['l1:', 'l3:']);
});

test('an invalid split or merge changes nothing', () => {
  const st = {lines: sample(), selected: new Set([1])};
  assert.equal(applyEdit(st, {kind: 'split', index: 0, word: 0}), st);
  assert.equal(applyEdit(st, {kind: 'merge', index: 2}), st);
});
