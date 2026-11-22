// node --test: room titles, reuse labels, picker groups (own first, kept second) and the set notes cost line.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {pickerGroups, reuseLabel, roomTitle, setNotesCost} from './setView.ts';

test('rooms are named from the set notes', () => {
  assert.equal(roomTitle({room: 'office'}, 0), 'Room 1: office');
  assert.equal(roomTitle({room: null}, 0), 'The set');
});

test('the picker shows this episode\'s sets first and kept sets as explicit reuse', () => {
  const opts = [{id: 'mine', own: true, kept: false, source: 'studio'}, {id: 'lib', own: false, kept: true, source: 'studio'},
    {id: 'plate', own: false, kept: true, source: 'repository'}, {id: 'old', own: false, kept: false, source: 'studio'}];
  const g = pickerGroups(opts);
  assert.deepEqual(g.own.map(o => o.id), ['mine', 'old'], 'a set the episode already uses stays with its own sets');
  assert.deepEqual(g.kept.map(o => o.id), ['lib', 'plate']);
  assert.equal(reuseLabel(opts[0]), 'made for this episode');
  assert.equal(reuseLabel({...opts[0], kept: true}), 'made for this episode · kept for future episodes');
  assert.equal(reuseLabel(opts[1]), 'kept for reuse');
  assert.equal(reuseLabel(opts[2]), 'studio plate (kept for reuse)');
});

test('the set notes cost is shown before an upload', () => {
  assert.equal(setNotesCost({set_notes: {usd: 0.0032, frames: 6, rooms_assumed: 2}}), 'includes set notes: about $0.003 (6 frames, 2 rooms assumed)');
  assert.equal(setNotesCost({}), '');
});
