// node --test: the Talking shots total shown before Run.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {lineEstimate, talkingTotal} from './talkingShots.ts';

test('each line: audio rounded up, 3 s minimum, $0.015/s', () => {
  assert.equal(lineEstimate(6.22), 0.105, 'Episode 14 line 1');
  assert.equal(lineEstimate(1.44), 0.045, 'the 3 s minimum');
  assert.equal(lineEstimate(3.0), 0.045);
  assert.equal(lineEstimate(10.5), 0.165);
});

test('the total of the ticked lines (a keyed line is not run again)', () => {
  const rows = [6.22, 1.44, 5.92, 10.5].map(s => ({estimate_usd: lineEstimate(s), status: 'not run'}));
  assert.equal(talkingTotal(rows), 0.405);
  assert.equal(talkingTotal([...rows, {estimate_usd: 0.105, status: 'keyed'}]), talkingTotal(rows));
});
