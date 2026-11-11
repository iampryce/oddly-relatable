import test from 'node:test';
import assert from 'node:assert/strict';
import {stackLayout, checkLayout, dotKeys, interpolate, bubbleX, LAYOUT_DEFAULTS} from '../lib/layout.mjs';

const plane = {width: 1280, height: 2275.56};
const item = (id, start, height = 100, end = Infinity, order = 0) => ({id, start, end, height, width: 400, x: 64, order});
const strictlyIncreasing = keys => keys.every((k, i) => i === 0 || k.t > keys[i - 1].t);

test('newest bubble sits at the bottom; earlier bubbles slide up by height + gap', () => {
  const o = {...LAYOUT_DEFAULTS, zoneTop: 400, zoneBottom: 1000, gap: 20};
  const {layers, snapshots} = stackLayout([item('a', 0), item('b', 2)], o);
  const at2 = snapshots.find(s => s.t === 2).rects;
  assert.equal(at2.find(r => r.id === 'b').y, 900);
  assert.equal(at2.find(r => r.id === 'a').y, 780);
  const a = layers.find(l => l.id === 'a');
  assert.equal(interpolate(a.keys, 'y', 1.5), 900);          // settled before b arrives
  assert.equal(interpolate(a.keys, 'y', 2 + o.slide), 780);  // slid up after b arrives
  for (const l of layers) assert.ok(strictlyIncreasing(l.keys));
});

test('a new bubble fades and rises in', () => {
  const {layers} = stackLayout([item('a', 1)]);
  const a = layers[0];
  assert.equal(interpolate(a.keys, 'alpha', 1), 0);
  assert.equal(interpolate(a.keys, 'alpha', 1 + LAYOUT_DEFAULTS.enter), 1);
  assert.ok(interpolate(a.keys, 'y', 1) > interpolate(a.keys, 'y', 1 + LAYOUT_DEFAULTS.enter));
});

test('bubbles pushed above the zone fade out instead of overlapping the header', () => {
  const o = {...LAYOUT_DEFAULTS, zoneTop: 700, zoneBottom: 1000, gap: 20};
  const {layers, snapshots} = stackLayout([item('a', 0), item('b', 1), item('c', 2), item('d', 3)], o);
  const last = snapshots.at(-1).rects.map(r => r.id);
  assert.ok(!last.includes('a'), 'oldest bubble is no longer visible');
  assert.equal(interpolate(layers.find(l => l.id === 'a').keys, 'alpha', 10), 0);
});

test('typing indicator takes a slot, then the stack slides back when it disappears', () => {
  const o = {...LAYOUT_DEFAULTS, zoneTop: 300, zoneBottom: 1000, gap: 20};
  const {layers} = stackLayout([item('m', 0), item('t', 2, 80, 4)], o);
  const m = layers.find(l => l.id === 'm');
  assert.equal(interpolate(m.keys, 'y', 3), 1000 - 80 - 20 - 100); // pushed up above the typing slot (800)
  assert.equal(interpolate(m.keys, 'y', 5), 900);            // back down after typing ends
  const t = layers.find(l => l.id === 't');
  assert.equal(t.to, 4);
  assert.equal(interpolate(t.keys, 'alpha', 3.999), 0);
});

test('typing replaced by the reply: the reply takes over the bottom slot', () => {
  const o = {...LAYOUT_DEFAULTS, zoneTop: 300, zoneBottom: 1000, gap: 20};
  const {snapshots} = stackLayout([item('m', 0), item('t', 2, 80, 4), item('r', 4, 100)], o);
  const at4 = snapshots.find(s => s.t === 4).rects;
  assert.deepEqual(at4.map(r => [r.id, r.y]).sort(), [['m', 780], ['r', 900]]);
});

test('typing dots follow their bubble and pulse in turn', () => {
  const {layers} = stackLayout([item('t', 1, 80, 3)]);
  const bubble = layers[0].keys, d0 = dotKeys(bubble, 30, 1, 3, 0), d1 = dotKeys(bubble, 30, 1, 3, 0.18);
  assert.ok(strictlyIncreasing(d0));
  for (const t of [1.5, 2.2]) assert.ok(Math.abs(interpolate(d0, 'y', t) - (interpolate(bubble, 'y', t) + 30)) < 2);
  const alphas = d0.filter(k => k.t > 1.3 && k.t < 2.9).map(k => k.alpha);
  assert.ok(Math.max(...alphas) - Math.min(...alphas) > 0.4, 'dot opacity pulses');
  assert.notDeepEqual(d0.map(k => k.alpha), d1.map(k => k.alpha), 'dots are out of phase');
});

test('layout checks catch face overlap, hook overlap and safe-zone violations', () => {
  const snap = [{t: 1, rects: [{id: 'm1', x: 64, y: 900, w: 400, h: 100}]}];
  assert.ok(checkLayout({snapshots: snap, plane}).ok);
  const face = checkLayout({snapshots: snap, plane, faceBoxes: [{x: 100, y: 950, w: 300, h: 300, from: 0, to: 5, pose: '02'}]});
  assert.match(face.issues[0].problem, /face/);
  const hook = checkLayout({snapshots: snap, plane, hook: {x: 0, y: 880, w: 1280, h: 60, from: 0, to: 3}});
  assert.match(hook.issues[0].problem, /hook/);
  const edge = checkLayout({snapshots: [{t: 0, rects: [{id: 'm', x: 0, y: 900, w: 400, h: 100}]}], plane});
  assert.match(edge.issues[0].problem, /safe zone/);
});

test('bubble x aligns left speakers to the left margin and right speakers to the right margin', () => {
  assert.equal(bubbleX('left', 300, plane), LAYOUT_DEFAULTS.marginX);
  assert.equal(bubbleX('right', 300, plane), plane.width - LAYOUT_DEFAULTS.marginX - 300);
});
