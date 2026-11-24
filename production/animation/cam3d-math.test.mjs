// node --test production/animation/ : the 3D camera's maths (no three.js, no canvas needed).
import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {expression, fitDistance, mouthShape, orbit, planarUV, seated, shellScale, VISEMES} from './cam3d-math.mjs';

const spec = JSON.parse(fs.readFileSync(new URL('./cast3d/uncle-mortimer.json', import.meta.url), 'utf8'));
const near = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg}: ${a} vs ${b}`);
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);

test('orbit: front, three-quarter and raised views keep their distance from the target', () => {
  const t = {x: 0, y: 0.5, z: 0};
  const f = orbit(t, 3, 0);
  near(f.x, 0, 1e-12, 'front: straight ahead'); near(f.z, 3, 1e-12, 'front: in front');
  const q = orbit(t, 3, 38, 9);
  near(dist(q, t), 3, 1e-9, 'three-quarter: same distance');
  assert.ok(q.x > 0 && q.y > t.y, 'turned to the viewer\'s right and raised');
  near(Math.atan2(q.x, q.z) * 180 / Math.PI, 38, 1e-9, 'the turn');
});

test('fitDistance: the span fills the asked share of the picture height', () => {
  const d = fitDistance(1.2, 30, 0.8);
  near(1.2 / (2 * d * Math.tan(15 * Math.PI / 180)), 0.8, 1e-12, 'fill');
});

test('planarUV: the picture\'s corners and centre; v runs down from the top row', () => {
  const box = {x0: -1, x1: 1, y0: -1, y1: 1};
  assert.deepEqual(planarUV(-1, 1, box), {u: 0, v: 0});
  assert.deepEqual(planarUV(1, -1, box), {u: 1, v: 1});
  assert.deepEqual(planarUV(0, 0, box), {u: 0.5, v: 0.5});
});

test('shellScale: an outline of the same thickness on every side', () => {
  const s = shellScale([0.4, 0.02, 0.3], 0.005);
  near(0.4 * s[0] - 0.4, 0.01, 1e-12, 'x'); near(0.02 * s[1] - 0.02, 0.01, 1e-12, 'y'); near(0.3 * s[2] - 0.3, 0.01, 1e-12, 'z');
});

test('seated: soles on the floor, limbs at their lengths, the head on the torso', () => {
  const J = seated(spec);
  for (const L of J.legs) {
    near(L.sole.y, 0, 1e-12, 'the sole on the floor');
    near(dist(L.hip, L.knee), J.thigh, 1e-12, 'thigh length');
    near(dist(L.knee, L.ankle), J.shin, 1e-12, 'shin length');
    near(L.knee.y, J.hipY, 1e-12, 'level thigh');
    assert.ok(L.knee.z > 0, 'knees forward');
  }
  for (const A of J.arms) {
    near(dist(A.shoulder, A.elbow), J.upper, 1e-9, 'upper arm length');
    near(dist(A.elbow, A.hand), J.fore, 1e-9, 'forearm length');
    assert.ok(A.hand.y > J.hipY - 0.001, 'the hands stay above the seat');
  }
  near(J.head.y - J.headR, J.torsoTop, 0.01, 'the head sits on the torso');
  near(J.arms[0].shoulder.x, -J.arms[1].shoulder.x, 1e-12, 'symmetric');
});

test('mouth shapes: every Rhubarb viseme has one; closed ones are lines, X is the rest mouth', () => {
  for (const v of VISEMES) {
    const m = mouthShape(v);
    assert.ok(m.kind === 'line' || m.kind === 'oval', v);
    assert.ok(m.w > 0 && m.w <= 1, `${v} width`);
    if (m.kind === 'oval') assert.ok(m.h > 0 && m.h <= 0.6, `${v} height`);
  }
  assert.deepEqual(mouthShape('X'), {kind: 'line', w: 1, dy: 0});
  for (const v of ['A', 'G']) assert.equal(mouthShape(v).kind, 'line');
  assert.ok(mouthShape('D').h > mouthShape('B').h, 'AA opens wider than a consonant');
});

test('expressions: an unknown name falls back to neutral', () => {
  assert.equal(expression('furious'), expression('neutral'));
  assert.equal(expression('neutral').lid, 0);
});
