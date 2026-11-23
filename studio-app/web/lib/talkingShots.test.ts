// node --test: the Talking shots total shown before Run.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {clampCrop, lineEstimate, talkingTotal} from './talkingShots.ts';

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

test('a crop the owner moves stays 9:16 and inside the plate (no bars)', () => {
  assert.deepEqual(clampCrop({x: 900, y: 0, w: 540}, 1024, 1536), {w: 540, x: 484, y: 0});
  assert.deepEqual(clampCrop({x: 0, y: 0, w: 2000}, 1024, 1536), {w: 864, x: 0, y: 0}, 'never wider than a 9:16 crop of the plate');
  const c = clampCrop({x: 10, y: 1000, w: 540}, 1024, 1536);
  assert.equal(c.y + c.w * 16 / 9 <= 1536, true);
});
