// AP-86 S4 (approved by the owner; implemented 2026-11-16): framing profiles, composed camera windows, camera moves
// and continuity reporting for face-to-face scenes in a set.
//
// OPT-IN. Only a story@2 story that declares `profile` takes this path. Every other story (Short 001, the accepted AP-85
// scenes, S1 to S3 fixtures) compiles exactly as before.
//
// A shot is a WINDOW on the set plate (world units): left L, top T, width W; zoom z = plane width / W and the window's
// height is H = W × plane height / plane width. The plate is cover-fitted to the profile's plane (sets.mjs), so a
// square superframe plate gives a portrait frame extra width to pan across and a landscape frame extra height:
// "portrait shows extra floor and ceiling, landscape shows extra wall" (bible MULTI_PLATFORM_ARCHITECTURE §4). Windows
// always lie inside the plate, so the background always covers the frame.
//
// Rules (Track A rules kept, given more room):
//   wide (z = 1): every member of the scene fully in frame (horizontal edge margin), the cast centred.
//   medium / close: the focus member fully in frame; every other member fully in or fully out (never cut by the left or
//     right edge); when others are in frame, the focus member is clearly the most central; `single` hides the others.
//   vertical: the window keeps `headroom` (fraction of its height) above the tallest framed head, so bubbles have room.
// Moves (push-in, pull-back, pan): the window's left, top and width are interpolated with the same ease between two
// rule-satisfying windows; the plate-coverage constraints are convex, so every in-between frame is covered too.
// While the camera moves, members may cross the frame edge (that is what a pan does); the rules apply again from the
// move's last frame.
//
// PROVISIONAL VALUES (owner-approved 2026-11-16 as provisional): platform UI-safe margins and caption zones are not
// verified platform figures (bible §5); they are conservative and configurable per scene (`layout.safe`).

export const PROFILES = Object.freeze({
  'P-916': Object.freeze({id: 'P-916', width: 1080, height: 1920, safe: {top: 0.06, bottom: 0.18, left: 0.04, right: 0.04},
    bubbleY: 300, headroom: 0.2, bubbles: {}}),
  // Landscape: the frame is short, so figures fill about three quarters of its height. Bubbles use a smaller type (36
  // design units = 54 px at 1080p) and a wider line, so one line fits above the heads within the headroom.
  'P-169': Object.freeze({id: 'P-169', width: 1920, height: 1080, safe: {top: 0.03, bottom: 0.16, left: 0.04, right: 0.04},
    bubbleY: 28, headroom: 0.24, bubbles: {fontSize: 36, padX: 28, padY: 18, maxWidth: 1000}}),
});

export const MOVE_DEFAULTS = Object.freeze({pushDuration: 1.0, pullDuration: 1.2, panDuration: 1.0, maxPanSpeed: 1.6});
const EPS = 1e-9;
const r2 = v => Math.round(v * 100) / 100;
const smooth = x => { x = Math.max(0, Math.min(1, x)); return x * x * (3 - 2 * x); };

export function profileFor(id) {
  const p = PROFILES[id];
  if (!p) throw new Error(`unknown framing profile "${id}" (known: ${Object.keys(PROFILES).join(', ')})`);
  return p;
}

// Camera (the existing {z, pivot, ox, oy} form used by applyCamera and parallaxCamera) that shows exactly `win`.
// Pivot = window centre, so parallax layers scale about the middle of what is on screen.
export function windowCamera(win, plane, t = 0) {
  const z = plane.width / win.W, cx = win.L + win.W / 2, cy = win.T + win.W * plane.height / plane.width / 2;
  return {t, z, pivot: {x: cx, y: cy}, ox: plane.width / 2 - cx, oy: plane.height / 2 - cy};
}

// Union of a member's pose rectangles over [from, to): x0, x1, top (head) and bottom (feet).
export function extent(m, from, to, poseRect) {
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const seg of m.segments) {
    if (seg.end <= from + EPS || seg.start >= to - EPS) continue;
    const info = m.infos.get(seg.pose), r = poseRect(info, m.placement), k = r.k;
    x0 = Math.min(x0, r.x); x1 = Math.max(x1, r.x + r.w);
    y0 = Math.min(y0, m.placement.feetY - m.placement.figureHeight); y1 = Math.max(y1, r.y + info.height * k);
  }
  return Number.isFinite(x0) ? {x0, x1, y0, y1} : null;
}

const intersect = (A, B) => A.flatMap(([a0, a1]) => B.map(([b0, b1]) => [Math.max(a0, b0), Math.min(a1, b1)])).filter(([lo, hi]) => lo <= hi + EPS).sort((p, q) => p[0] - q[0]);
function nearest(set, x) {
  let best = null;
  for (const [lo, hi] of set) { const c = Math.min(Math.max(x, lo), hi); if (best === null || Math.abs(c - x) < Math.abs(best - x) - EPS) best = c; }
  return best;
}
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

// Compose one shot's window. ctx: {cast, byId, plane, plate (world rect), fr: {edgeMargin, subjectMargin}, profile, poseRect}
export function composeWindow(s, ctx, {from = s.start, to = s.end} = {}) {
  const {cast, byId, plane, plate, fr, profile, poseRect} = ctx;
  const where = `line ${s.line} (${s.note}${s.focus ? ` on ${s.focus}` : ''})`;
  const z = s.zoom, W = plane.width / z, H = W * plane.height / plane.width, m = fr.edgeMargin;
  if (W > plate.w + EPS || H > plate.h + EPS) throw new Error(`${where}: the set plate is smaller than a ${z}x window in profile ${profile.id}`);
  const xs = [plate.x, plate.x + plate.w - W], ys = [plate.y, plate.y + plate.h - H];
  const ext = new Map(cast.map(c => [c.id, extent(c, from, to, poseRect)]));
  let L, visible, hidden = [], framedTop;
  if (!(z > 1 + EPS)) {
    // Wide: everyone in frame, centred.
    const all = cast.map(c => ext.get(c.id)).filter(Boolean);
    const u0 = Math.min(...all.map(e => e.x0)), u1 = Math.max(...all.map(e => e.x1));
    const set = intersect([xs], [[u1 + m - W, u0 - m]]);
    if (!set.length) throw new Error(`${where}: the cast is spread wider than a wide ${profile.id} frame. Restage the members closer together, or use a medium shot`);
    L = nearest(set, (u0 + u1) / 2 - W / 2);
    visible = cast.map(c => c.id);
    framedTop = Math.min(...all.map(e => e.y0));
  } else {
    // Medium / close: the Track A rules, panning anywhere on the plate.
    const focus = byId.get(s.focus), f = ext.get(focus.id);
    let set = intersect([xs], [[f.x1 + m - W, f.x0 - m]]);
    if (!set.length) throw new Error(`${where}: "${focus.id}" does not fit inside this frame with a ${m}-unit margin. Use a wider shot`);
    const others = cast.filter(c => c.id !== focus.id);
    hidden = s.single ? others.map(c => c.id) : [];
    for (const o of s.single ? [] : others) {
      const e = ext.get(o.id);
      if (!e) continue;
      const allowed = intersect(set, [[-Infinity, e.x0 - m - W], [e.x1 + m - W, e.x0 - m], [e.x1 + m, Infinity]]);
      if (!allowed.length) throw new Error(`${where}: every framing that keeps "${focus.id}" in frame would cut "${o.id}" at the frame edge. Restage, or make this a single`);
      set = allowed;
    }
    const fc = (f.x0 + f.x1) / 2;
    L = nearest(set, fc - W / 2);
    const centre = L + W / 2;
    visible = [focus.id];
    for (const o of s.single ? [] : others) {
      const e = ext.get(o.id);
      if (!e || e.x1 <= L + EPS || e.x0 >= L + W - EPS) continue;
      visible.push(o.id);
      if (Math.abs(fc - centre) + fr.subjectMargin * W > Math.abs((e.x0 + e.x1) / 2 - centre)) {
        throw new Error(`${where}: "${focus.id}" would not be the clear subject ("${o.id}" is about as central). Restage, or make this a single`);
      }
    }
    framedTop = f.y0;
  }
  // Vertical: headroom above the tallest framed head (room for bubbles), inside the plate.
  const T = clamp(framedTop - profile.headroom * H, ys[0], ys[1]);
  // Members not framed in this window (out of frame left/right) are "out"; members hidden by `single` are off camera.
  return {...s, window: {L, T, W, H, z}, visible, hidden, out: cast.map(c => c.id).filter(id => !visible.includes(id) && !hidden.includes(id))};
}

// Move timing: [start, start + duration) of the shot, eased; the window holds after it.
export function moveSpan(shot, opts = MOVE_DEFAULTS) {
  const beat = shot.end - shot.start, mv = shot.move;
  const base = mv.kind === 'push' ? opts.pushDuration : mv.kind === 'pull' ? opts.pullDuration : opts.panDuration;
  return {start: shot.start, end: shot.start + (mv.slow ? beat : Math.min(base, beat))};
}

export function windowAt(shots, t) {
  const i = shots.findIndex(s => t >= s.start - EPS && t < s.end - EPS);
  const s = shots[i === -1 ? shots.length - 1 : i];
  if (!s.move || !s.from) return s.window;
  const span = s.span, u = span.end > span.start ? smooth((t - span.start) / (span.end - span.start)) : 1;
  const a = s.from, b = s.window, k = t >= span.end ? 1 : u;
  const W = a.W + (b.W - a.W) * k;
  return {L: a.L + (b.L - a.L) * k, T: a.T + (b.T - a.T) * k, W, H: a.H + (b.H - a.H) * k, z: undefined};
}

// Continuity across cuts (REPORT ONLY, owner decision 2026-11-16): between consecutive shots, a member that appears on
// the other half of the frame, or two members whose left-right order flips, is listed; the build never fails on it.
export function continuityReport(shots, cast, plane, screenX) {
  const notes = [];
  for (let i = 1; i < shots.length; i++) {
    const a = shots[i - 1], b = shots[i];
    if (b.move) continue;                               // a move is continuous by construction
    const both = cast.map(c => c.id).filter(id => a.visible.includes(id) && b.visible.includes(id));
    for (const id of both) {
      const sa = screenX(a, id) < plane.width / 2 ? 'left' : 'right', sb = screenX(b, id) < plane.width / 2 ? 'left' : 'right';
      if (sa !== sb) notes.push({t: r2(b.start), line: b.line, kind: 'screen-side switch', member: id, from: sa, to: sb});
    }
    for (let p = 0; p < both.length; p++) for (let q = p + 1; q < both.length; q++) {
      const [x, y] = [both[p], both[q]];
      if (Math.sign(screenX(a, x) - screenX(a, y)) !== Math.sign(screenX(b, x) - screenX(b, y))) notes.push({t: r2(b.start), line: b.line, kind: 'left-right order flip', members: [x, y]});
    }
  }
  return notes;
}
