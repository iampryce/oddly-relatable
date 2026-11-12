import test from 'node:test';
import assert from 'node:assert/strict';
import {planPoseLayers, scaleAt, alphaAt, poseRect, castLayers, TRANSITION_DEFAULTS} from '../lib/timeline.mjs';

const segs = transition => [{pose: 'a', start: 0, end: 2, transition: 'cut'}, {pose: 'b', start: 2, end: 4, transition}];
const info = {id: 'a', width: 274, height: 596, feet: {x: 139, y: 585}, figureHeight: 575};
const placement = {feetX: 640, feetY: 2070, figureHeight: 880};

test('hard cut: segments meet exactly at the pose change, fully opaque, no scaling', () => {
  const [a, b] = planPoseLayers(segs('cut'));
  assert.deepEqual([a.from, a.to, b.from, b.to], [0, 2, 2, 4]);
  for (const t of [0, 1.99]) assert.equal(alphaAt(a, t), 1);
  for (const t of [2, 3]) { assert.equal(alphaAt(b, t), 1); assert.equal(scaleAt(b, t), 1); }
});

test('pop: brief bounce that starts and ends at exact size, anchored at the feet', () => {
  const [, b] = planPoseLayers(segs('pop'));
  const d = TRANSITION_DEFAULTS.popDuration;
  assert.equal(scaleAt(b, 2), 1);
  assert.ok(scaleAt(b, 2 + d / 2) > 1.05);
  assert.equal(scaleAt(b, 2 + d), 1);
  for (const s of [1, scaleAt(b, 2 + d / 2)]) {
    const r = poseRect(info, placement, s);
    assert.ok(Math.abs(r.x + info.feet.x * r.k - 640) < 1e-9 && Math.abs(r.y + info.feet.y * r.k - 2070) < 1e-9, 'feet stay put');
    assert.ok(Math.abs(r.w / (info.height * r.k) - info.width / info.height) < 1e-12, 'proportions preserved');
  }
});

test('crossfade: incoming pose dissolves over the outgoing one, centred on the change', () => {
  const [a, b] = planPoseLayers(segs('crossfade'));
  const half = TRANSITION_DEFAULTS.crossfade / 2;
  assert.ok(Math.abs(b.from - (2 - half)) < 1e-9 && Math.abs(a.to - (2 + half)) < 1e-9);
  assert.equal(alphaAt(b, 2 - half), 0);
  assert.ok(Math.abs(alphaAt(b, 2) - 0.5) < 1e-9);
  assert.equal(alphaAt(b, 2 + half), 1);
  assert.equal(alphaAt(a, 2), 1, 'outgoing stays opaque underneath (no see-through)');
});

test('crossfade overlap is limited by short neighbouring segments', () => {
  const [a, b] = planPoseLayers([{pose: 'a', start: 0, end: 0.04, transition: 'cut'}, {pose: 'b', start: 0.04, end: 3, transition: 'crossfade'}]);
  assert.ok(b.from >= 0 && a.to <= 0.04 + 0.02 + 1e-9);
});

test('unknown transition is rejected', () => {
  assert.throws(() => planPoseLayers(segs('wipe')), /Unknown transition/);
});

test('cast layers: one layer per pose, frame-exact keys, alpha keys present', () => {
  const plans = planPoseLayers(segs('pop'));
  const identity = () => ({z: 1, ox: 0, oy: 0, pivot: {x: 0, y: 0}});
  const layers = castLayers({plans, infos: new Map([['a', info], ['b', {...info, id: 'b'}]]), placement, cameraFor: identity, fps: 30, assetPathFor: i => `p-${i.id}.png`});
  assert.equal(layers.length, 2);
  assert.equal(layers[0].keys.length, 2, 'a held pose needs only two keys');
  assert.ok(layers[1].keys.length > 4, 'the pop is sampled per frame');
  assert.ok(layers.every(l => l.keys.every(k => k.alpha !== undefined)));
});
