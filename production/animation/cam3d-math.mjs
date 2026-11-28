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

// The width in output pixels of something `size` world units across, `dist` away, for a camera `heightPx` tall.
export const pixelsAcross = (size, dist, fovDeg, heightPx) => size * (heightPx / 2) / Math.tan(fovDeg * deg / 2) / dist;

// A picture laid flat over the front of a shape (planar projection, the way a drawing on paper is pressed onto a ball):
// the texture coordinates of a point (x, y) for a picture covering the box [x0, x1] x [y0, y1] (y up). The picture's
// row 0 is its top, so v runs down from the top edge.
export function planarUV(x, y, box) {
  return {u: (x - box.x0) / (box.x1 - box.x0), v: (box.y1 - y) / (box.y1 - box.y0)};
}

// The face plate: a gently curved shell (radius `plateR` head radii) just in front of the head's face, so the features
// foreshorten like a nearly flat face when the head turns instead of wrapping round the ball. Its depth at (x, y).
export function plateZ(x, y, depth, plateR, gap = 0.012) {
  return depth + gap - plateR + Math.sqrt(Math.max(0, plateR * plateR - x * x - y * y));
}

// ---------------------------------------------------------------- measured proportions
// The approved art's proportions, from outside edge to outside edge of the ink (spec.measured), and the 3D model's,
// seen from the front (its shapes are traced along the centre of the ink line, and the renderer draws one line of the
// art's width centred on every edge, so each outside width is the shape's width plus one line). Limbs and hands are
// ink themselves: their thickness is the tube's.
export function ratios(m) {
  return {head_vest: m.head_width / m.vest_width, head_shoulders: m.head_width / m.shoulder_span,
          arm_head: m.arm / m.head_width, leg_head: m.leg / m.head_width, line_head: m.line / m.head_width};
}
export function modelMeasures(spec) {
  const vest = Math.max(...spec.torso.profile.map(p => p[0])) * 2;
  return {head_width: 2 * spec.head.r + spec.line, vest_width: vest + spec.line,
          shoulder_span: 2 * (spec.shoulders.x + spec.arm.thickness / 2), arm: spec.arm.thickness, leg: spec.leg.thickness,
          line: spec.line};
}

// ---------------------------------------------------------------- the seated body
// The joints of one character on a seat, in world units. The thighs run forward level from the hips, the shins hang
// straight down and the soles rest on the floor, so the hips sit at shin + ankle-to-sole height; the knees spread
// `apart` degrees. The arms hang at the torso's sides (as in the approved art), reaching forward a little so the hands
// rest on the seat beside the thighs; the elbows bend slightly outwards.
export function seated(spec, apart = 6, seatGap = 0.004) {
  const U = 1 / spec.px_per_unit, thigh = spec.leg.length / 2 * U, shin = spec.leg.length / 2 * U, drop = spec.shoe.drop * U;
  const hipY = shin + drop, hx = spec.hips.x * U;
  const Y = yArt => hipY + (spec.hips.y - yArt) * U;              // a height in the art -> world height, seated
  const X = xArt => (xArt - spec.centre_x) * U;
  const legs = [-1, 1].map(s => {
    const hip = {x: s * hx, y: hipY, z: 0};
    const a = apart * deg, knee = {x: hip.x + s * thigh * Math.sin(a), y: hipY, z: thigh * Math.cos(a)};
    const ankle = {x: knee.x, y: hipY - shin, z: knee.z};
    return {hip, knee, ankle, sole: {x: ankle.x, y: ankle.y - drop, z: ankle.z}};
  });
  const seatTop = hipY - spec.leg.thickness / 2 * U;
  const L = spec.arm.length * U, handH = (Math.max(...spec.hand.outline.map(p => p[1])) - spec.arm.wrist[1]) * U;
  const arms = [-1, 1].map(s => {
    const shoulder = {x: s * spec.shoulders.x * U, y: Y(spec.shoulders.y), z: 0};
    const wx = s * Math.abs(X(spec.arm.wrist[0])), wy = seatTop + handH + seatGap;
    const dx = wx - shoulder.x, dy = wy - shoulder.y, reach = 0.97 * L;
    const wz = Math.sqrt(Math.max(0, reach * reach - dx * dx - dy * dy));
    const {joint, end} = ik3(shoulder, {x: wx, y: wy, z: wz}, L / 2, L / 2, {x: s, y: 0, z: -0.3});
    return {shoulder, elbow: joint, wrist: end};
  });
  return {U, X, Y, hipY, seatTop, legs, arms, thigh, shin, torsoBottom: hipY, torsoTop: Y(Math.min(...spec.torso.profile.map(p => p[1]))),
          head: {x: X(spec.head.cx), y: Y(spec.head.cy), z: 0}, headR: spec.head.r * U, handH};
}

// ---------------------------------------------------------------- the ink line
// Exact squared Euclidean distance transform (Felzenszwalb & Huttenlocher) of a w x h grid: f holds 0 at the seed
// pixels and a large number elsewhere; it is replaced in place by each pixel's squared distance to the nearest seed.
const BIG = 1e20;
function edt1d(f, n, d, v, z) {
  let k = 0; v[0] = 0; z[0] = -BIG; z[1] = BIG;
  for (let q = 1; q < n; q++) {
    let s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]);
    while (s <= z[k]) { k--; s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]); }
    k++; v[k] = q; z[k] = s; z[k + 1] = BIG;
  }
  k = 0;
  for (let q = 0; q < n; q++) { while (z[k + 1] < q) k++; d[q] = (q - v[k]) * (q - v[k]) + f[v[k]]; }
}
export function edt(f, w, h) {
  const n = Math.max(w, h), g = new Float64Array(n), d = new Float64Array(n), v = new Int32Array(n), z = new Float64Array(n + 1);
  for (let x = 0; x < w; x++) {
    for (let y = 0; y < h; y++) g[y] = f[y * w + x];
    edt1d(g, h, d, v, z);
    for (let y = 0; y < h; y++) f[y * w + x] = d[y];
  }
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) g[x] = f[y * w + x];
    edt1d(g, w, d, v, z);
    for (let x = 0; x < w; x++) f[y * w + x] = d[x];
  }
  return f;
}

// The outline: every edge between two different parts (a part id per pixel; 0 = the room) gets one ink line `width`
// pixels wide, centred on the edge. Parts with id `inkId` (limbs, hands: ink already) make no edges. Returns a mask
// (1 = ink) the size of the grid; only the box around the edges is worked on.
export function inkMask(ids, w, h, width, inkId) {
  const mask = new Uint8Array(w * h), half = width / 2;
  let x0 = w, y0 = h, x1 = -1, y1 = -1;
  const seed = new Uint8Array(w * h);
  const edge = (p, q, x, y, qx, qy) => {
    const b = ids[q];
    if (b === inkId || b === ids[p]) return;
    seed[p] = 1; seed[q] = 1;
    if (x < x0) x0 = x; if (y < y0) y0 = y; if (qx > x1) x1 = qx; if (qy > y1) y1 = qy;
  };
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const p = y * w + x;
    if (ids[p] === inkId) continue;
    if (x + 1 < w) edge(p, p + 1, x, y, x + 1, y);
    if (y + 1 < h) edge(p, p + w, x, y, x, y + 1);
  }
  if (x1 < 0) return mask;
  const pad = Math.ceil(half) + 2;
  x0 = Math.max(0, x0 - pad); y0 = Math.max(0, y0 - pad); x1 = Math.min(w - 1, x1 + pad); y1 = Math.min(h - 1, y1 + pad);
  const bw = x1 - x0 + 1, bh = y1 - y0 + 1, f = new Float64Array(bw * bh).fill(BIG);
  for (let y = 0; y < bh; y++) for (let x = 0; x < bw; x++) if (seed[(y + y0) * w + x + x0]) f[y * bw + x] = 0;
  edt(f, bw, bh);
  // the seeds sit on both sides of the edge (a line one pixel wide already): the rest of the width is spread evenly
  const r2 = Math.max(0, half - 0.5) ** 2;
  for (let y = 0; y < bh; y++) for (let x = 0; x < bw; x++) if (f[y * bw + x] <= r2) mask[(y + y0) * w + x + x0] = 1;
  return mask;
}

// A k x k box filter: the supersampled picture (RGBA, rows bottom-up as GL reads them) averaged down to w x h, rows
// top-down. `ink` (optional mask) paints those pixels in `inkRGB` first.
export function boxDown(src, W, H, k, ink = null, inkRGB = [0, 0, 0]) {
  const w = Math.floor(W / k), h = Math.floor(H / k), out = new Uint8ClampedArray(w * h * 4), n = k * k;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let r = 0, g = 0, b = 0;
    for (let j = 0; j < k; j++) for (let i = 0; i < k; i++) {
      const p = (y * k + j) * W + x * k + i;
      if (ink && ink[p]) { r += inkRGB[0]; g += inkRGB[1]; b += inkRGB[2]; } else { r += src[p * 4]; g += src[p * 4 + 1]; b += src[p * 4 + 2]; }
    }
    const o = ((h - 1 - y) * w + x) * 4;
    out[o] = Math.round(r / n); out[o + 1] = Math.round(g / n); out[o + 2] = Math.round(b / n); out[o + 3] = 255;
  }
  return out;
}

// ---------------------------------------------------------------- the face
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

// The control point of a quadratic curve from a to b that passes through `peak` halfway (a brow through its top).
export const throughPeak = (a, peak, b) => [2 * peak[0] - (a[0] + b[0]) / 2, 2 * peak[1] - (a[1] + b[1]) / 2];

// Brow and eye settings per expression (Gate 1: neutral only; later expressions add rows here, not new drawings).
export const EXPRESSIONS = {
  neutral: {brow: {dy: 0, tilt: 0}, lid: 0, pupil: {x: 0, y: 0}, bend: 0},
};
export const expression = name => EXPRESSIONS[name] || EXPRESSIONS.neutral;
