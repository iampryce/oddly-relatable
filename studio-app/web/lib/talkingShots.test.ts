// node --test: the Talking shots total shown before Run.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {clampCrop, lineEstimate, rowMedia, talkingTotal} from './talkingShots.ts';

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

test('a row\'s clip and keying, as in its shot comparison cell', () => {
  const urls = {keyed: '/k.webm', over_set: '/s.mp4', over_grey: '/g.mp4', check: '/c.png'};
  const done = {clip_url: '/clip.mp4', can_key_again: true, key: {status: 'done', colour: '#FF00FF', check_at: [0, 1, 2], urls, quality: {ok: true, reasons: []}}};
  assert.deepEqual(rowMedia(done), {state: 'keyed', tone: '', reasons: [], keyAgain: true, clip: '/clip.mp4', overSet: '/s.mp4',
    overGrey: '/g.mp4', check: '/c.png', keyed: '/k.webm', checkFrames: 3});
  const attention = rowMedia({...done, key: {...done.key, quality: {ok: false, reasons: ['over grey the background is up to 27 levels off grey at 4.7 s (limit 6)']}}});
  assert.equal(attention.state, 'key needs attention');
  assert.equal(attention.tone, 'warn');
  assert.match(attention.reasons[0], /27 levels off grey/);
  assert.equal(attention.keyAgain, true, 'Key again is offered to fix it (free)');
  const failed = rowMedia({clip_url: '/clip.mp4', can_key_again: true, key: {status: 'failed', error: 'the keying job 352 stopped: PendingRollbackError'}});
  assert.deepEqual([failed.state, failed.tone, failed.keyAgain], ['keying failed: the keying job 352 stopped: PendingRollbackError', 'bad', true]);
  const running = rowMedia({clip_url: '/clip.mp4', can_key_again: false, key: {status: 'running', colour: '#FF00FF'}});
  assert.deepEqual([running.state, running.keyAgain], ['keying #FF00FF out… (free)', false]);
  assert.deepEqual([rowMedia({clip_url: '/clip.mp4'}).state, rowMedia({}).state], ['clip, not keyed yet', '']);
  assert.deepEqual([rowMedia({clip_binned: true, can_key_again: true}).state, rowMedia({clip_binned: true, can_key_again: true}).keyAgain], ['clip in the Bin', false]);
});
