// node --test: the keyed copy's check in the shot comparison cell.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {checkFrames, keyQuality} from './keyQuality.ts';

const q = (over: any = {}) => ({quality: {ok: true, reasons: [], bg_dev_max: 0, pink_max: 8, key_first: [250, 34, 230],
  key_last: [240, 57, 210], limits: {bg_dev: 6, pink: 150}, ...over}});

test('a clean key says Keyed, with the measurements', () => {
  const r = keyQuality(q());
  assert.equal(r.ok, true);
  assert.equal(r.line, 'Check over grey: background up to 0 off grey (limit 6), 8 pink pixels left at most (limit 150); key colour (250,34,230) at the start, (240,57,210) at the end');
});

test('a key over the limits needs attention and says why', () => {
  const r = keyQuality(q({ok: false, bg_dev_max: 27, reasons: ['over grey the background is up to 27 levels off grey at 4.7 s (limit 6): a tint of the key colour is left']}));
  assert.equal(r.ok, false);
  assert.match(r.reasons[0], /27 levels off grey at 4\.7 s/);
});

test('a key from before the check is shown as keyed, with nothing measured', () => {
  assert.deepEqual(keyQuality({status: 'done'}), {ok: true, reasons: [], line: ''});
});

test('check frames: one per second', () => {
  assert.equal(checkFrames([0, 1, 2, 3, 4, 5, 6]), 'one per second (7 frames, 0–6 s)');
  assert.equal(checkFrames([0.6, 3.1, 5.6]), '0.6 s, 3.1 s, 5.6 s');
  assert.equal(checkFrames([]), 'open');
});
