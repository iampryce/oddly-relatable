import test from 'node:test';
import assert from 'node:assert/strict';
import {parseCameraNote, buildCameraTrack, zoomAt, cameraAt, applyCamera, offsetAt} from '../lib/camera.mjs';
import {sampleKeys} from '../lib/timeline.mjs';

const plane = {width: 1280, height: 2275.56};

test('script camera notes map to framing, moves, holds, shake and drift', () => {
  assert.deepEqual(parseCameraNote('Wide, still').framing, {zoom: 1});
  assert.equal(parseCameraNote('Wide, still').hold, true);
  assert.deepEqual(parseCameraNote('Slow push-in to 1.2×').move, {zoom: 1.2, duration: 'beat'});
  assert.deepEqual(parseCameraNote('Hard cut, medium 1.5×').framing, {zoom: 1.5});
  assert.equal(parseCameraNote('Hard cut, medium 1.5×').cut, true);
  assert.deepEqual(parseCameraNote('Medium 1.3×').framing, {zoom: 1.3});
  assert.equal(parseCameraNote('Pull back to wide, hold').move.zoom, 1.0);
  assert.equal(parseCameraNote('Hold').hold, true);
  assert.equal(parseCameraNote('Medium 1.3×, small shake').shake, true);
  assert.equal(parseCameraNote('Medium 1.3×, drift').drift, true);
});

test('zoom limit is enforced and unknown wording is rejected instead of guessed', () => {
  assert.throws(() => parseCameraNote('Medium 1.6×'), /outside the allowed 1–1.5× range/);
  assert.throws(() => parseCameraNote('Dutch angle orbit'), /not recognised/);
  assert.equal(parseCameraNote('Close').framing.zoom, 1.5);
});

test('track: framing changes are cuts, push/pull are eased moves, holds change nothing', () => {
  const tr = buildCameraTrack([
    {note: 'Wide, still', start: 0, end: 3}, {note: 'Slow push-in to 1.2×', start: 3, end: 6}, {note: 'Hold', start: 6, end: 9},
    {note: 'Hard cut, medium 1.5×', start: 9, end: 11}, {note: 'Pull back to wide, hold', start: 11, end: 14},
  ]);
  assert.deepEqual(tr.moves.map(m => [m.start, m.end, m.from, m.to]), [[3, 6, 1, 1.2], [11, 12.2, 1.5, 1]]);
  assert.deepEqual(tr.cuts.map(c => [c.t, c.to]), [[9, 1.5]]);
  assert.equal(zoomAt(tr, 2.9), 1); assert.equal(zoomAt(tr, 4.5), 1.1); assert.equal(zoomAt(tr, 7), 1.2);
  assert.equal(zoomAt(tr, 8.999), 1.2); assert.equal(zoomAt(tr, 9), 1.5); assert.equal(zoomAt(tr, 13), 1);
  for (let t = 0; t < 14; t += 0.01) assert.ok(zoomAt(tr, t) <= 1.5 + 1e-9);
});

test('camera evaluation is deterministic', () => {
  const tr = buildCameraTrack([{note: 'Medium 1.3×, small shake', start: 0, end: 2}, {note: 'Medium 1.3×, drift', start: 2, end: 4}]);
  const a = [0.3, 1.1, 2.5, 3.7].map(t => cameraAt(tr, t, {pivot: {x: 640, y: 1190}, plane}));
  const b = [0.3, 1.1, 2.5, 3.7].map(t => cameraAt(tr, t, {pivot: {x: 640, y: 1190}, plane}));
  assert.deepEqual(a, b);
  assert.notEqual(offsetAt(tr, 0.3).ox, 0, 'shake moves the frame');
  assert.equal(offsetAt(tr, 1.99).ox.toFixed(3) === offsetAt(tr, 0.3).ox.toFixed(3), false);
});

test('the pivot stays fixed on screen and the same transform applies to every world layer', () => {
  const tr = buildCameraTrack([{note: 'Medium 1.5×', start: 0, end: 1}]);
  const cam = cameraAt(tr, 0.5, {pivot: {x: 640, y: 1190}, plane});
  const p = applyCamera(cam, {x: 640, y: 1190, w: 10});
  assert.equal(p.x, 640); assert.equal(p.y, 1190); assert.equal(p.w, 15);
  const bg = applyCamera(cam, {x: 0, y: 0, w: 1280}), ch = applyCamera(cam, {x: 500, y: 1000, w: 300});
  assert.ok(Math.abs((ch.x - bg.x) - 500 * 1.5) < 1e-9 && Math.abs((ch.y - bg.y) - 1000 * 1.5) < 1e-9);
});

test('shake and drift are clamped so the background always covers the frame', () => {
  const tr = buildCameraTrack([{note: 'Wide, small shake', start: 0, end: 2}]);
  const cover = {x: 0, y: 0, w: 1280, h: 2275.56};
  for (let t = 0; t < 2; t += 1 / 30) {
    const cam = cameraAt(tr, t, {pivot: {x: 640, y: 1190}, plane, coverRect: cover});
    const r = applyCamera(cam, cover);
    assert.ok(r.x <= 1e-9 && r.y <= 1e-9 && r.x + r.w >= 1280 - 1e-9 && r.y + cover.h * cam.z >= plane.height - 1e-9);
  }
});

test('keyframes land on the frame grid, strictly ordered, compressed on holds', () => {
  const keys = sampleKeys(t => ({x: t < 1 ? 0 : t < 2 ? (t - 1) * 30 : 30, y: 0, w: 1, alpha: 1}), 0, 3, 30);
  assert.ok(keys.every((k, i) => i === 0 || k.t > keys[i - 1].t));
  assert.ok(keys.every(k => Math.abs(k.t * 30 - Math.round(k.t * 30)) < 0.005), "keys sit on frame times (4-decimal rounding)");
  assert.ok(keys.length < 40, `holds are compressed (got ${keys.length})`);
  assert.equal(keys[0].t, 0); assert.ok(Math.abs(keys.at(-1).t - 89 / 30) < 1e-3);
});
