// node --test: the reaction sheet's and shot list's editing helpers.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {beatForServer, beatTime, newBeat, newShot, sceneSpan, shotsProblem, wordLabel, wordsOf} from './reactionSheet.ts';

const tr = [{id: 'l2', words: [{word: 'To', start: 7.32, end: 7.32}, {word: ' ', start: 7.4, end: 7.4}, {word: 'Ralph', start: 8.24, end: 8.76}]}];

test('words come from the transcript line, and a beat defaults to its word start', () => {
  const w = wordsOf(tr, 'l2');
  assert.equal(w.length, 2, 'blank words are left out');
  assert.equal(wordLabel(w[1], 1), '2. Ralph (8.24 s)');
  assert.equal(beatTime({word: 1, expression: 'neutral', move: 'lift', strength: 'medium', reason: ''}, w), 8.24);
  assert.equal(beatTime({word: 1, t: 8.5, expression: 'neutral', move: 'lift', strength: 'medium', reason: ''}, w), 8.5);
  assert.deepEqual(wordsOf(tr, 'l9'), []);
  assert.equal(newBeat(w).word, 0);
  assert.equal(newBeat(w, {word: 1, expression: 'x', move: 'none', strength: 'light', reason: ''}).word, 1, 'never past the last word');
});

test('only a hand-set time is sent', () => {
  assert.equal('t' in beatForServer({word: 0, expression: 'neutral', move: 'none', strength: 'light', reason: ''}), false);
  const b = beatForServer({word: 3, t: 17.65, estimated: true, word_text: 'yacht', expression: 'worried', move: 'dip', strength: 'medium', reason: 'r'});
  assert.deepEqual(b, {word: 3, t: 17.65, estimated: true, expression: 'worried', move: 'dip', strength: 'medium', reason: 'r'});
});

test('shots: the same first problem the API refuses', () => {
  const a = newShot(undefined, 6.22, ['uncle-mortimer']);
  assert.deepEqual([a.start, a.end, a.on_screen], [6.22, 7.22, ['uncle-mortimer']]);
  const b = newShot(a, 6.22, ['ralph']);
  assert.equal(b.start, 7.22, 'a new shot starts where the last one ends');
  assert.equal(shotsProblem([a, b]), '');
  assert.match(shotsProblem([a, {...b, start: 7.0}]), /before shot 1 ends/);
  assert.match(shotsProblem([{...a, type: 'ots'}]), /whose shoulder/);
  assert.match(shotsProblem([{...a, on_screen: []}]), /who is on screen/);
  assert.match(shotsProblem([{...a, end: 6.0}]), /end after it starts/);
});

test('the scene span matches the API', () => {
  const scenes = [{lines: [{start: 0, end: 6.22}]}, {lines: [{start: 7.32, end: 17.98}]}, {lines: [{start: 19.62, end: 21.4}]}];
  assert.deepEqual(sceneSpan(scenes, 1), [6.22, 19.62]);
  assert.deepEqual(sceneSpan(scenes, 2, 60), [17.98, 60]);
});
