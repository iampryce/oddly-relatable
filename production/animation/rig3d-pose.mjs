// Studio 3D rig animator (feat/3d-rig PR 2): from the acting renderer's 2D pose to the 3D stickman's joints. Pure
// functions (no three.js, no canvas), tested with node --test.
//
// Units: the character's SOURCE pixels (the approved pose's pixels), body-local: x to the character's right as seen
// from the front, y UP, z towards the camera when the character faces it; the origin is the centre of the hips.
// The renderer scales by c.S (source -> set pixels) and turns the body by `yaw` (0 faces the camera, +90 faces screen
// right).

export const deg = Math.PI / 180;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const add = (a, b) => ({x: a.x + b.x, y: a.y + b.y, z: a.z + b.z});
const sub = (a, b) => ({x: a.x - b.x, y: a.y - b.y, z: a.z - b.z});
const mul = (a, k) => ({x: a.x * k, y: a.y * k, z: a.z * k});
const len = a => Math.hypot(a.x, a.y, a.z);
const norm = a => { const l = len(a) || 1; return mul(a, 1 / l); };
const cross = (a, b) => ({x: a.y * b.z - a.z * b.y, y: a.z * b.x - a.x * b.z, z: a.x * b.y - a.y * b.x});
const dot = (a, b) => a.x * b.x + a.y * b.y + a.z * b.z;

// A character's proportions in source px, from the 2D rig (animator.loadRig).
export function dims(c) {
  const shoe = c.footDrop - c.ankleL.y;                               // ankle to sole
  return {legLen: c.legLen, thigh: c.legLen / 2, shin: c.legLen / 2, shoe, armLen: c.armLen, upper: c.armLen / 2, fore: c.armLen / 2,
          hipHalf: (c.hipR.x - c.hipL.x) / 2, hipX: [c.hipL.x, c.hipR.x],
          shoulders: [{x: c.shoulderL.x, y: -c.shoulderL.y, z: 0}, {x: c.shoulderR.x, y: -c.shoulderR.y, z: 0}],
          neck: {x: c.neck.x, y: -c.neck.y, z: 0}};
}

// Seated thighs: the angle from straight down (90 = horizontal, pointing forward) at which the knee, with the shin
// hanging straight down and the shoe below it, puts the sole on the set's feet line. A seat marked too high for the
// character's legs sits them on its front edge (thighs sloping down, never steeper than 25 degrees); a seat too low
// keeps the thighs level.
export const KNEES_APART = 30;                                       // seated thighs spread outwards (deg): reads as seated
export function seatedThighPitch(d, hipY, feetY, S, apart = KNEES_APART) {
  const A = (feetY - hipY) / S;                                       // hip to the feet line, source px (y down on screen)
  const c = (A - d.shin - d.shoe) / (d.thigh * Math.cos(apart * deg)); // cos(pitch) needed
  return clamp(Math.acos(clamp(c, 0, 1)) / deg, 25, 90);
}

// Two-bone IK in 3D: the joint for root a, target t, bone lengths l1, l2; the joint bends towards `pole`. A target out of
// reach straightens the limb along the line to it (the limb never stretches or bows).
export function ik3(a, t, l1, l2, pole) {
  let d = sub(t, a), dist = len(d);
  const max = l1 + l2 - 1e-6;
  if (dist > max) { d = mul(norm(d), max); t = add(a, d); dist = max; }
  dist = Math.max(dist, Math.abs(l1 - l2) + 1e-6);
  const dir = norm(d);
  const along = (l1 * l1 - l2 * l2 + dist * dist) / (2 * dist), h = Math.sqrt(Math.max(0, l1 * l1 - along * along));
  // the bend direction: the pole made perpendicular to the limb
  let p = sub(pole, mul(dir, dot(pole, dir)));
  if (len(p) < 1e-9) p = Math.abs(dir.y) < 0.9 ? cross(dir, {x: 0, y: 1, z: 0}) : cross(dir, {x: 1, y: 0, z: 0});
  p = norm(p);
  return {joint: add(add(a, mul(dir, along)), mul(p, h)), end: t};
}

// A leg from its thigh pitch (deg from straight down, forward positive), knee bend (deg, the shin swinging back) and
// the thigh's outward spread (deg; seated knees apart).
export function legFrom(d, side, pitch, knee, apart = 0) {
  const hip = {x: d.hipX[side < 0 ? 0 : 1], y: 0, z: 0};
  const ca = Math.cos(apart * deg);
  const th = {x: side * Math.sin(apart * deg), y: -Math.cos(pitch * deg) * ca, z: Math.sin(pitch * deg) * ca};
  const kneeP = add(hip, mul(th, d.thigh));
  const sa = (pitch - knee) * deg;                                    // the shin's angle from straight down
  const ankle = add(kneeP, mul({x: 0, y: -Math.cos(sa), z: Math.sin(sa)}, d.shin));
  return {hip, knee: kneeP, ankle, sole: add(ankle, {x: 0, y: -d.shoe, z: 0})};
}

// The 3D pose of one character for one frame, from the acting renderer's 2D pose p (render-acting.mjs pose()).
//   seat (when seated or sitting): {hip_y, feet_y} of the seat, set px; S: source -> set px.
export function pose3d(c, p, S) {
  const d = dims(c);
  const walking = !!p.walk;
  const yaw = p.yaw3d ?? ((p.turn || 0) * 90 * (p.turnDir || 1));
  // legs
  let legs;
  if (p.sitting !== undefined && p.sitting > 0 && p.seatFeetY !== undefined) {
    const target = seatedThighPitch(d, p.seatHipY ?? p.hip.y, p.seatFeetY, S);
    const u = clamp(p.sitting, 0, 1), pitch = target * u;
    legs = [-1, 1].map(s => legFrom(d, s, pitch, pitch, KNEES_APART * u));   // knees apart, the shin straight down
  } else if (walking) {
    const w = Math.sin(Math.PI * p.walk.step);                       // one swing per step
    const swing = 24 * w, lift = 34 * Math.max(0, Math.sin(Math.PI * (p.walk.step % 1)));
    legs = [legFrom(d, -1, swing, Math.max(0, swing > 0 ? lift : 0)), legFrom(d, 1, -swing, Math.max(0, swing < 0 ? lift : 0))];
  } else {
    legs = [-1, 1].map(s => legFrom(d, s, 0, 0));
  }
  // arms: to the 2D hand target (in the frontal plane), or swinging while walking, or resting on the thighs seated
  const arms = [-1, 1].map((side, i) => {
    const sh = {...d.shoulders[i], y: d.shoulders[i].y + (p.shoulderLift || 0)};
    let target;
    if (p.seated && !walking && p.sitting >= 1) {
      // the hand on the thigh, the arm straight at its full length towards it
      const k = legs[i].knee, h = legs[i].hip;
      const onThigh = add(h, mul(sub(k, h), 0.8));
      target = add(sh, mul(norm(sub(onThigh, sh)), d.upper + d.fore));
    } else if (walking && !p.gesturing) {
      const a = -22 * Math.sin(Math.PI * p.walk.step) * (side < 0 ? 1 : -1) * deg;
      target = add(sh, {x: side * d.armLen * 0.08, y: -Math.cos(a) * d.armLen * 0.98, z: Math.sin(a) * d.armLen * 0.98});
    } else {
      const h = p[side < 0 ? 'handL' : 'handR'] || {x: side * d.armLen * 0.2, y: d.armLen * 0.95};
      target = add(sh, {x: h.x, y: -h.y, z: 0});
    }
    const {joint, end} = ik3(sh, target, d.upper, d.fore, {x: side, y: -0.35, z: -0.25});
    return {shoulder: sh, elbow: joint, hand: end};
  });
  return {yaw, roll: -(p.lean || 0), squash: p.squash || 1, legs, arms, neck: d.neck, dims: d};
}

// The head's view: which drawing faces the camera, from where the body and head point (deg; 0 = the camera).
export function headView(yaw, headYaw = 0) {
  const a = ((yaw + headYaw) % 360 + 540) % 360 - 180, A = Math.abs(a);
  const view = A > 125 ? 'back' : A > 62 ? 'side' : A > 22 ? 'three-quarter' : 'front';
  // the drawings face the viewer's right; a head turned to the left is the same drawing mirrored
  return {view, flip: view !== 'back' && view !== 'front' && a < 0, angle: a};
}

// Where a seated character faces (feat/3d-rig PR 3): the owner's choice on the seat (the set's staging) when there is
// one:  camera | away | speaker | seat:N   (N: the seat's number in the set's staging, 0 = the first = the speaker's)
// else nothing here: the renderer turns them by the scene (facingTarget below).
export const FACE_ANGLE = 55;                                        // a seated body turned towards a seat (deg)
export function seatFacing(seats, i) {
  return (seats[i] || {}).facing || '';
}
export function seatYaw(seats, i) {
  const f = seatFacing(seats, i), here = seats[i];
  if (!here || f === 'camera') return 0;
  if (f === 'away') return 180;
  const n = f === 'speaker' ? 0 : Number(String(f).split(':')[1]);
  const target = seats.find((s, j) => (s.n ?? j) === n);
  if (!target || target === here || Math.abs(target.x - here.x) < 1) return 0;
  return Math.sign(target.x - here.x) * FACE_ANGLE;
}

// Which way a character turns, by the scene (owner correction 2026-11-23): the speaker turns towards the person the
// line addresses (look_at), else the reference plan's direction for them, else the others; everyone else turns as the
// plan says (a direction or a person), else towards the current speaker. "camera" in the plan is read as towards the
// speaker (a listener in a close shot still faces the speaker). Returns {x} (a point to face) or {dir} (-1 left, 1 right)
// or null (face the camera).
//   me: {key, x}; line: the current line or null; lastSpeaker: the key who spoke last; at: key -> x of those on stage;
//   note: the plan's facing for this character now ('left' | 'right' | a character key | undefined).
export function facingTarget(me, line, lastSpeaker, at, note) {
  const speaking = line && line.speaker === me.key;
  if (speaking && line.look_at && line.look_at !== me.key && at[line.look_at] !== undefined) return {x: at[line.look_at]};
  if (note === 'left') return {dir: -1};
  if (note === 'right') return {dir: 1};
  if (note && note !== me.key && at[note] !== undefined) return {x: at[note]};
  if (speaking) {
    const others = Object.entries(at).filter(([k]) => k !== me.key).map(([, x]) => x);
    return others.length ? {x: others.reduce((a, b) => a + b, 0) / others.length} : null;
  }
  const s = line?.speaker && line.speaker !== me.key ? line.speaker : lastSpeaker;
  return s && s !== me.key && at[s] !== undefined ? {x: at[s]} : null;
}
export const SPEAKER_TURN = 65, LISTENER_TURN = 45, STANDING_TURN = 30;
// The body's yaw for a target: towards its side at the given angle (a target right in front: the camera).
export function turnTowards(target, x, angle) {
  if (!target) return 0;
  const d = target.dir ?? (Math.abs(target.x - x) < 30 ? 0 : Math.sign(target.x - x));
  return d * angle;
}
