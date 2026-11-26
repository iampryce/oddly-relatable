// node --test: the stick pipeline's costs (images per image, video PER SECOND) and labels.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {usd4, animateAllShots, chatEstimateText, chatUsageText, chosenClip, clipStatus, confirmText, imageCost, usd, videoCost} from './stickPipeline.ts';

test('money', () => {
  assert.equal(usd(0.04), '$0.04');
  assert.equal(usd(0.3), '$0.30');
  assert.equal(usd(0.0042), '$0.0042');
  assert.equal(usd(null), 'cost unknown');
  assert.equal(usd4(0.0108), '$0.0108');
  assert.equal(usd4(2.5), '$2.50');
});

test('images are priced per image', () => {
  assert.deepEqual(imageCost(2, 0.04), {usd: 0.08, label: '2 images x $0.04 = $0.08'});
  assert.equal(imageCost(1, 0.04).label, '1 image x $0.04 = $0.04');
});

test('video is priced per second of video', () => {
  assert.deepEqual(videoCost(5, 0.06), {usd: 0.3, label: '5 s x $0.06/s = $0.30'});
  assert.equal(videoCost(8, 0.06).usd, 0.48);
  const all = videoCost(5, 0.06, 3);
  assert.equal(all.usd, 0.9);
  assert.equal(all.label, '3 clips x 5 s x $0.06/s = $0.30 = $0.90');
  assert.match(confirmText('Animate shot 2', videoCost(5, 0.06)), /\$0\.30\. Start now\?/);
  assert.match(confirmText('x', null), /cannot start/);
});

test('animate all and clips', () => {
  const shots = [{index: 1, approved: true, chosen: 5}, {index: 2, approved: false, chosen: 6},
    {index: 3, approved: true, chosen: 7, clips: [{asset_id: 9}]}, {index: 4, approved: true, chosen: null}];
  assert.deepEqual(animateAllShots(shots), [1]);
  assert.deepEqual(clipStatus({clips: []}), {tone: '', text: 'no clip'});
  assert.equal(clipStatus({clips: [{asset_id: 1}], clip_approved: true}).text, 'clip approved');
  assert.equal(chosenClip({clips: [{asset_id: 1}, {asset_id: 2}], clip_chosen: 2}).asset_id, 2);
});

test('chat cost texts', () => {
  assert.equal(chatEstimateText({label: 'Claude', usd_typical: 0.0042, usd_max: 0.082, input_tokens: 900}),
    'Claude: about $0.0042 (at most $0.0820), ~900 tokens in');
  assert.equal(chatUsageText({usage: {input_tokens: 1200, output_tokens: 300}, usd: 0.0108}), '1,200 in / 300 out tokens · $0.0108');
  assert.equal(chatUsageText({}), '');
});
