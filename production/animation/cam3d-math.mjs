// 3D camera (Gate 1): the pure maths of the native 3D characters. No three.js, no canvas; tested with node --test.
//
// World units: one unit = spec.px_per_unit px of the approved picture the spec was measured from. y up, z towards the
// camera of the front view, x to the viewer's right in that view; the floor is y = 0, the origin is under the hips.
import {ik3} from './rig3d-pose.mjs';

export const deg = Math.PI / 180;

// The camera's position for a view of `target` from `dist` away, turned `yaw` degrees around the vertical axis
// (0 = straight in front, + = towards the viewer's right, i.e. the character's left) and raised `pitch` degrees.
export function orbit(target, dist, yaw, pitch = 0) {
  const a = yaw * deg, p = pitch * deg;
  return {x: target.x + dist * Math.cos(p) * Math.sin(a), y: target.y + dist * Math.sin(p), z: target.z + dist * Math.cos(p) * Math.cos(a)};
}

// The distance at which a vertical span `h` fills `fill` of a perspective camera's height (vertical fov in degrees).
export const fitDistance = (h, fovDeg, fill = 0.8) => h / fill / (2 * Math.tan(fovDeg * deg / 2));

// A picture laid flat over the front of a shape (planar projection, the way a drawing on paper is pressed onto a ball):
// the texture coordinates of a point (x, y) for a picture covering the box [x0, x1] x [y0, y1] (y up). The picture's
// row 0 is its top, so v runs down from the top edge.
export function planarUV(x, y, box) {
  return {u: (x - box.x0) / (box.x1 - box.x0), v: (box.y1 - y) / (box.y1 - box.y0)};
}

// The ink outline of a box: a slightly bigger box drawn inside-out behind it. Its scale per axis, for an outline of
// thickness t on every side.
export const shellScale = (size, t) => size.map(s => (s + 2 * t) / s);

// The seated body: the joints of one character on a seat, in world units. The thighs run forward level from the hips,
// the shins hang straight down and the soles rest on the floor, so the hips sit at shin + shoe height; the knees spread
// `apart` degrees. The hands rest on the lap (as far as the arms reach: a target out of reach straightens the arm).
export function seated(spec, apart = 8) {
  const U = 1 / spec.px_per_unit, thigh = spec.leg / 2 * U, shin = spec.leg / 2 * U, drop = spec.shoe.drop * U;
  const hipY = shin + drop, hx = spec.hips.x * U;
  const torsoH = (spec.torso.bottom - spec.torso.top) * U, hipToBottom = (spec.torso.bottom - spec.hips.y) * U;
  const torsoBottom = hipY - hipToBottom, torsoTop = torsoBottom + torsoH;
  const legs = [-1, 1].map(s => {
    const hip = {x: s * hx, y: hipY, z: 0};
    const a = apart * deg, knee = {x: hip.x + s * thigh * Math.sin(a), y: hipY, z: thigh * Math.cos(a)};
    const ankle = {x: knee.x, y: hipY - shin, z: knee.z};
    return {hip, knee, ankle, sole: {x: ankle.x, y: ankle.y - drop, z: ankle.z}};
  });
  const upper = spec.arm / 2 * U, fore = spec.arm / 2 * U;
  const arms = [-1, 1].map((s, i) => {
    // the arms hang at the torso's sides (as in the approved art) and the hands rest on the seat beside the hips
    const shoulder = {x: s * (spec.torso.width / 2 + spec.line * 0.3) * U, y: torsoTop - spec.shoulders.below_top * U, z: 0};
    const rest = {x: s * (spec.torso.width / 2 + spec.hand.r * 1.2) * U, y: hipY + spec.hand.r * 0.6 * U, z: legs[i].knee.z * 0.3};
    const {joint, end} = ik3(shoulder, rest, upper, fore, {x: s, y: 0, z: -1});
    return {shoulder, elbow: joint, hand: end};
  });
  const headR = spec.head.r * U, neck = {x: 0, y: torsoTop, z: 0};
  const head = {x: 0, y: torsoTop + spec.head.neck_to_centre * U, z: 0};
  return {U, hipY, torsoBottom, torsoTop, legs, arms, neck, head, headR, thigh, shin, upper, fore};
}

// Mouth shapes for Rhubarb's visemes (the same set the 2D renderer uses), as fractions of the face's mouth width:
// a closed line (keeping the expression's bend) or a filled ink oval. X is the rest mouth.
const OVALS = {B: [0.8, 0.14], C: [0.6, 0.32], D: [0.72, 0.55], E: [0.5, 0.36], F: [0.3, 0.32], H: [0.55, 0.3]};
export const VISEMES = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'X'];
export function mouthShape(viseme = 'X') {
  if (viseme === 'X') return {kind: 'line', w: 1, dy: 0};
  if (viseme === 'A') return {kind: 'line', w: 0.9, dy: 0};          // M B P: closed
  if (viseme === 'G') return {kind: 'line', w: 0.8, dy: 0.04};       // F V: closed, lower lip tucked
  const [w, h] = OVALS[viseme] || OVALS.C;
  return {kind: 'oval', w, h};
}

// Brow and eye settings per expression (Gate 1: neutral only; later expressions add rows here, not new drawings).
export const EXPRESSIONS = {
  neutral: {brow: {dy: 0, tilt: 0, arch: 1}, lid: 0, pupil: {x: 0, y: 0}, bend: 0},
};
export const expression = name => EXPRESSIONS[name] || EXPRESSIONS.neutral;
