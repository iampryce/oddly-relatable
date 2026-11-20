import {test} from 'node:test';
import assert from 'node:assert/strict';
import {windowError, windowFrom} from './trimWindow.ts';

test('a window of at most 60 s inside the recording is accepted', () => {
  assert.equal(windowError(10, 70, 95, 60), null);
  assert.equal(windowError(0, 42, 42, 60), null);
});

test('a window that is too long, reversed or outside the recording is refused', () => {
  assert.match(windowError(0, 61, 95, 60)!, /at most 60 s/);
  assert.match(windowError(30, 20, 95, 60)!, /end after it starts/);
  assert.match(windowError(50, 100, 95, 60)!, /after the recording/);
  assert.match(windowError(-1, 10, 95, 60)!, /before the recording/);
  assert.match(windowError(NaN, 10, 95, 60)!, /Enter a start/);
});

test('windowFrom gives the longest window from a start, kept inside the recording', () => {
  assert.deepEqual(windowFrom(12, 95, 60), {start: 12, end: 72});
  assert.deepEqual(windowFrom(80, 95, 60), {start: 35, end: 95});      // moved back so it still runs 60 s
  assert.deepEqual(windowFrom(0, 40, 60), {start: 0, end: 40});        // a short recording: all of it
});
