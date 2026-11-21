// node --test: batch selection keys and the result grid cells (rig / model clip / failed with retry).
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {clipCell, lineKey, toggleAll} from './shotBatch.ts';

test('all lines / none', () => {
  const lines = [{scene_id: 1, line: 0}, {scene_id: 1, line: 1}, {scene_id: 2, line: 0}];
  assert.deepEqual([...toggleAll(lines, true)], ['1:0', '1:1', '2:0']);
  assert.equal(toggleAll(lines, false).size, 0);
  assert.equal(lineKey({scene_id: 3, line: 4}), '3:4');
});

test('grid cells: rig, done clip, running, failed with its reason, not run', () => {
  const plan = {status: 'ready', rig_url: '/r.mp4', rig_check: {length_ok: true, video_seconds: 3, audio_seconds: 3},
    requests: [{model: 'a', estimate: {usd: 0.17}}, {model: 'b', estimate: {usd: 0.35}}],
    results: {a: {status: 'done', url: '/a.mp4', actual_usd: 0.1686, per_second_usd: 0.0562, check: {length_ok: true, video_seconds: 3, audio_seconds: 3}},
      b: {status: 'failed', error: 'fal.ai: generation failed'}, c: {status: 'running'}}};
  assert.equal(clipCell(plan, 'rig').cost, 'free');
  assert.equal(clipCell(plan, 'a').cost, '$0.169 · $0.056/s');
  assert.equal(clipCell(plan, 'a').lengthOk, true);
  assert.equal(clipCell({...plan, results: {...plan.results, a: {...plan.results.a, asset_id: 7}}}, 'a').assetId, 7, 'a done clip can be deleted to the Bin');
  const binned = clipCell({...plan, results: {...plan.results, a: {...plan.results.a, url: undefined, binned: true}}}, 'a');
  assert.equal(binned.binned, true);
  assert.equal(binned.url, undefined, 'a clip in the Bin is not playable here');
  assert.deepEqual(clipCell(plan, 'b'), {failed: 'fal.ai: generation failed', estimate: 0.35});
  assert.equal(clipCell(plan, 'c').state, 'running…');
  assert.match(clipCell({...plan, results: {}}, 'a').state!, /not run \(estimate \$0\.170\)/);
});
