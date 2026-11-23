// node --test production/animation/ : the 3D rig animator's pose maths (no three.js, no canvas needed).
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {deg, dims, headView, ik3, legFrom, pose3d, seatedThighPitch, KNEES_APART} from './rig3d-pose.mjs';

// Uncle Mortimer's rig (Episode 14) as loadRig builds it (source px, y down, relative to the hip centre)
const mortimer = {legLen: 353, armLen: 303.3, footDrop: 443, ankleL: {x: -12, y: 353}, hipL: {x: -62.25, y: 0}, hipR: {x: 62.25, y: 0},
  shoulderL: {x: -113.75, y: -338}, shoulderR: {x: 114.75, y: -338}, neck: {x: 0.25, y: -415}};
const S = 407 / 1400;
const near = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg}: ${a} vs ${b}`);
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);

test('seated: the soles reach the set\'s feet line, whatever the seat height (within the legs\' reach)', () => {
  const d = dims(mortimer);
  for (const [hipY, feetY] of [[968, 1082], [968, 1060], [930, 1040]]) {
    const pitch = seatedThighPitch(d, hipY, feetY, S);
    const leg = legFrom(d, 1, pitch, pitch, KNEES_APART);
    near(hipY - leg.sole.y * S, feetY, 1.5, `seat ${hipY}/${feetY}: the sole on the feet line`);
    near(leg.ankle.x, leg.knee.x, 1e-9, 'the shin hangs straight down');
    near(leg.ankle.z, leg.knee.z, 1e-9, 'the shin hangs straight down');
  }
  // a seat too high for these legs: the thighs never steeper than 25 degrees, the feet hang (no stretching)
  assert.equal(seatedThighPitch(d, 900, 1400, S), 25);
  // a seat too low: the thighs stay level
  assert.equal(seatedThighPitch(d, 968, 990, S), 90);
});

test('the limbs keep their lengths in every pose (nothing is lost or stretched)', () => {
  const d = dims(mortimer);
  const poses = [
    {hip: {x: 300, y: 968}, seated: true, sitting: 1, seatHipY: 968, seatFeetY: 1082, look: {x: 0, y: 0}},
    {hip: {x: 300, y: 900}, sitting: 0.4, seatHipY: 968, seatFeetY: 1082, look: {x: 0, y: 0}},
    {hip: {x: 300, y: 880}, walk: {step: 1.3, dir: 1}, turn: 1, turnDir: 1, look: {x: 0, y: 0}},
    {hip: {x: 300, y: 880}, handL: {x: -200, y: -150}, handR: {x: 40, y: 280}, look: {x: 0, y: 0}},
  ];
  for (const p of poses) {
    const q = pose3d(mortimer, p, S);
    for (const g of q.legs) {
      near(dist(g.hip, g.knee), d.thigh, 1e-6, 'thigh'); near(dist(g.knee, g.ankle), d.shin, 1e-6, 'shin');
      for (const v of [g.hip, g.knee, g.ankle, g.sole]) assert.ok([v.x, v.y, v.z].every(Number.isFinite));
    }
    for (const a of q.arms) {
      near(dist(a.shoulder, a.elbow), d.upper, 1e-6, 'upper arm'); assert.ok(dist(a.elbow, a.hand) <= d.fore + 1e-6, 'forearm');
    }
  }
});

test('seated hands rest on the thighs with straight arms; walking legs alternate; a turn shows the profile', () => {
  const q = pose3d(mortimer, {hip: {x: 0, y: 968}, seated: true, sitting: 1, seatHipY: 968, seatFeetY: 1082, look: {x: 0, y: 0}}, S);
  for (const a of q.arms) {
    const off = Math.hypot(...['x', 'y', 'z'].map(k => (a.elbow[k] - a.shoulder[k]) / 1 - (a.hand[k] - a.shoulder[k]) / 2));
    assert.ok(off < 1, `the arm is straight (elbow on the line): ${off}`);
    assert.ok(a.hand.z > 0, 'the hand is forward, on the thigh');
  }
  const w = pose3d(mortimer, {hip: {x: 0, y: 880}, walk: {step: 0.5, dir: 1}, turn: 1, turnDir: 1, look: {x: 0, y: 0}}, S);
  assert.ok(w.legs[0].knee.z > 0 && w.legs[1].knee.z < 0, 'one leg forward, the other back');
  assert.equal(w.yaw, 90, 'walking right: the body turned to its profile');
});

test('the head view follows the body and head turn; left is the right drawing mirrored', () => {
  assert.deepEqual(headView(0).view, 'front');
  assert.deepEqual(headView(40), {view: 'three-quarter', flip: false, angle: 40});
  assert.deepEqual(headView(-90), {view: 'side', flip: true, angle: -90});
  assert.equal(headView(90, 90).view, 'back');
  assert.equal(headView(180).flip, false, 'the back is never mirrored');
  assert.equal(headView(-90, 90).view, 'front', 'a body turned left, the head turned back to the camera');
});

test('3D IK: out of reach straightens along the line; within reach bends towards the pole', () => {
  const s = ik3({x: 0, y: 0, z: 0}, {x: 0, y: -500, z: 0}, 100, 100, {x: 1, y: 0, z: 0});
  near(s.end.y, -200, 1e-3, "pulled in to the limb length"); near(s.joint.x, 0, 0.05, "straight");
  const b = ik3({x: 0, y: 0, z: 0}, {x: 0, y: -150, z: 0}, 100, 100, {x: 1, y: 0, z: 0});
  assert.ok(b.joint.x > 0, 'bends towards the pole');
  assert.equal(deg, Math.PI / 180);
});

test('seated facing: the speaker\'s seat faces the camera, the audience the speaker, unless the set says otherwise', async () => {
  const {seatYaw, seatFacing, FACE_ANGLE} = await import('./rig3d-pose.mjs');
  // Episode 14's set: the speaker behind the desk on the left, three audience seats to the right
  const seats = [{x: 180, n: 0}, {x: 530, n: 1, facing: 'speaker'}, {x: 737, n: 2, facing: 'seat:1'}, {x: 940, n: 3, facing: 'away'}];
  assert.equal(seatFacing(seats, 0), '', 'no choice on the seat: decided by the scene');
  assert.equal(seatYaw(seats, 1), -FACE_ANGLE, 'towards the speaker, on the left');
  assert.equal(seatYaw(seats, 2), -FACE_ANGLE, 'towards seat 2, on the left');
  assert.equal(seatYaw(seats, 3), 180, 'away from the camera');
  // a reversed side of the room (shot / reverse shot): the seats keep their numbers, the speaker is now on the right
  const rev = seats.slice().reverse().map(s => ({...s, x: 1024 - s.x}));
  assert.equal(seatYaw(rev, rev.findIndex(s => s.n === 1)), FACE_ANGLE);
  assert.equal(seatYaw([{x: 300, n: 0, facing: 'camera'}, {x: 300, n: 1, facing: 'speaker'}], 1), 0, 'right in front of the speaker: the camera');
});

test('by the scene: the speaker turns to the person addressed, listeners as the plan says, else to the speaker', async () => {
  const {facingTarget, turnTowards, SPEAKER_TURN, LISTENER_TURN} = await import('./rig3d-pose.mjs');
  const at = {'uncle-mortimer': 180, ralph: 530, sidney: 737, winifred: 940};
  const line = {speaker: 'uncle-mortimer', look_at: 'sidney'};
  const m = facingTarget({key: 'uncle-mortimer', x: 180}, line, 'uncle-mortimer', at, 'right');
  assert.deepEqual(m, {x: 737}, 'the person the line addresses comes first');
  assert.equal(turnTowards(m, 180, SPEAKER_TURN), 65, 'turned right, a profile');
  assert.deepEqual(facingTarget({key: 'uncle-mortimer', x: 180}, {speaker: 'uncle-mortimer'}, null, at, 'right'), {dir: 1}, 'else the plan');
  assert.deepEqual(facingTarget({key: 'ralph', x: 530}, line, 'uncle-mortimer', at, 'left'), {dir: -1});
  assert.deepEqual(facingTarget({key: 'sidney', x: 737}, line, 'uncle-mortimer', at, 'ralph'), {x: 530}, 'facing another person in the plan');
  const w = facingTarget({key: 'winifred', x: 940}, line, 'uncle-mortimer', at, undefined);
  assert.equal(turnTowards(w, 940, LISTENER_TURN), -45, 'no note: towards the speaker, 45 degrees');
  assert.deepEqual(facingTarget({key: 'winifred', x: 940}, null, 'uncle-mortimer', at, undefined), {x: 180}, 'between lines: the last speaker');
  assert.equal(turnTowards(null, 0, 45), 0);
});

test('listeners: the speaker, the person the plan names, down on a sad reaction, a short glance now and then', async () => {
  const {listenerGaze, GLANCE_EVERY} = await import('./rig3d-pose.mjs');
  const line = {speaker: 'uncle-mortimer', start: 0, end: 20, reactions: [{character: 'sidney', expression: 'worried'}]};
  assert.deepEqual(listenerGaze('sidney', 3, line, ['ralph', 'winifred'], undefined), {target: null, down: true}, 'worried: looks down');
  assert.deepEqual(listenerGaze('ralph', 3, line, ['sidney'], 'sidney'), {target: 'sidney', down: false}, 'the plan says Ralph faces Sidney');
  // over a long line a listener mostly watches the speaker and glances away briefly, the same way every render
  const ts = Array.from({length: 200}, (_, i) => 1.05 + i * 0.1);
  const at = ts.map(t => listenerGaze('winifred', t, line, ['ralph'], undefined).target);
  const away = at.filter(x => x === 'ralph').length / at.length;
  assert.ok(away > 0.05 && away < 0.3, `glances are short: ${away}`);
  assert.deepEqual(at, ts.map(t => listenerGaze('winifred', t, line, ['ralph'], undefined).target), 'deterministic');
  assert.equal(listenerGaze('winifred', 0.5, line, ['ralph'], undefined).target, 'uncle-mortimer', 'no glance in the first second');
  assert.equal(listenerGaze('winifred', 3, line, [], undefined).target, 'uncle-mortimer', 'nobody else: the speaker');
  assert.ok(GLANCE_EVERY > 4);
});
