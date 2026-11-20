import {test} from 'node:test';
import assert from 'node:assert/strict';
import {joinWithPrevious, splitScene} from './audioScenes.ts';

const scenes = [{id: 's1', heading: 'Desk', lines: [{line_id: 'l1'}, {line_id: 'l2'}, {line_id: 'l3'}]}, {id: 's2', heading: 'Later', lines: [{line_id: 'l4'}]}];
const order = (s: any[]) => s.flatMap(x => x.lines.map((l: any) => l.line_id));

test('a split moves a cut between two lines and keeps every line in order', () => {
  const out = splitScene(scenes, 0, 2);
  assert.deepEqual(out.map(s => s.lines.length), [2, 1, 1]);
  assert.deepEqual(order(out), ['l1', 'l2', 'l3', 'l4']);
  assert.deepEqual(out.map(s => s.id), ['s1', 's2', 's3']);
  assert.equal(splitScene(scenes, 0, 0), scenes, 'no empty scene');
  assert.equal(splitScene(scenes, 0, 3), scenes);
});

test('a join removes a cut and keeps every line in order', () => {
  const out = joinWithPrevious(scenes, 1);
  assert.deepEqual(out.map(s => s.heading), ['Desk']);
  assert.deepEqual(order(out), ['l1', 'l2', 'l3', 'l4']);
  assert.equal(joinWithPrevious(scenes, 0), scenes);
});
