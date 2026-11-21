// Acting renderer: performs a script's structured acting instructions with the procedural animator.
//   node render-acting.mjs <acting.json> <out.mp4>
// acting.json (built by the studio, oddstudio/acting.py):
//   {width, height, fps, duration, captions: bool,
//    set: {plate, width, height, floor_y, stand_min_x, stand_max_x, seat?: {x, hip_y, feet_y},
//          seats?: [{x, hip_y, feet_y}], table_front?: {x0, y0, x1, y1}},
//    cast: {key: {rig, height, lips, start: "on" | "off" | "seat:N"}},
//    scenes?: [{t0, set: {...as set}, starts: {key: "on" | "off" | "seat:N"}}]   (later scenes: at t0 the set changes
//      and everyone is placed as the scene starts; without it, one set for the whole render, as before)
//    (seats: several seats; the older single `seat` is seat 0. table_front: the part of the plate in front of the
//     seated characters (a table top), drawn again after them so they sit behind it.)
//    lines: [{speaker, text, start, end, expression, gesture?, move?: {type, to?}, look_at?, reactions?: [...],
//             cues: [{start, end, value}]}]}
// Video only (the studio muxes the voice mix). Deterministic: the same input renders the same frames.
import fs from 'node:fs';
import path from 'node:path';
import {loadRig, drawCharacter, renderVideo, loadImage, createCanvas, envelope, ease, clamp, lerp, hipHeight} from './animator.mjs';
import {registerBannerFonts, layoutBanner, drawBanner} from './banner.mjs';

const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const OUT = process.argv[3];
const {width: W, height: H, fps: FPS, duration: DUR} = spec;
let SET = spec.set;
const KEYS = Object.keys(spec.cast);
const seatsOf = s => s.seats?.length ? s.seats : s.seat ? [s.seat] : [];
let SEATS = seatsOf(SET);
// scene 0 is spec.set with the cast's starts; later scenes switch set at their t0
const SCENES = [{t0: -Infinity, set: spec.set}, ...(spec.scenes || []).slice().sort((a, b) => a.t0 - b.t0)];
const useScene = i => { SET = SCENES[i].set; SEATS = seatsOf(SET); home = homes[i]; };
const sceneAt = t => { let i = 0; while (i + 1 < SCENES.length && SCENES[i + 1].t0 <= t) i++; return i; };
const startSeat = k => { const m = /^seat:(\d+)$/.exec(spec.cast[k].start || ''); return m && SEATS[+m[1]] ? +m[1] : null; };

// ---------------------------------------------------------------- cast and blocking
const C = {};
for (const k of KEYS) C[k] = await loadRig(spec.cast[k].rig, spec.cast[k].height, {name: k, lips: spec.cast[k].lips});
// footprint: the widest of head and arms-at-rest, so neighbours never overlap
const halfW = k => { const c = C[k]; return Math.max(c.faces.neutral.head.width / 2, Math.abs(c.handL.x) + c.lw * 2) * c.S + 6; };

// Standing marks for the characters on stage at the start (left to right in cast order), spaced by footprint.
function marks(keys) {
  const total = keys.reduce((a, k) => a + 2 * halfW(k), 0);
  const span = SET.stand_max_x - SET.stand_min_x;
  const gap = Math.max(0, (span - total) / (keys.length + 1));
  let x = SET.stand_min_x + gap, out = {};
  for (const k of keys) { out[k] = x + halfW(k); x += 2 * halfW(k) + gap; }
  return out;
}

// ---------------------------------------------------------------- choreography from the script
// Per character: a list of locomotion segments {t0, t1, from, to, kind: walk|sit|stand|jump} and a timeline of states.
const onStart = KEYS.filter(k => spec.cast[k].start !== 'off');
// every cast member gets a reserved mark (characters who enter later walk to theirs, so nobody overlaps)
const homes = SCENES.map(sc => { const keep = SET; SET = sc.set; const h = marks(KEYS); SET = keep; return h; });
let home = homes[0];
const state = {};                       // per character: x, seated, seat (index while seated)
for (const k of KEYS) {
  const si = startSeat(k);
  state[k] = si !== null ? {x: SEATS[si].x, seated: true, seat: si, on: true}
    : {x: spec.cast[k].start === 'off' ? SET.width + 160 : home[k], seated: false, seat: null, on: spec.cast[k].start !== 'off'};
}
const seatTaken = i => KEYS.some(o => state[o].seated && state[o].seat === i);
const warnings = [];   // reported with the result (the studio logs them on the job)
// the seat a move asks for ("seat:N"), else the nearest free one
function pickSeat(k, to) {
  const m = /^seat:(\d+)$/.exec(to || '');
  if (m && SEATS[+m[1]] && !seatTaken(+m[1])) return +m[1];   // a taken seat: the nearest free one instead
  const free = SEATS.map((s, i) => i).filter(i => !seatTaken(i));
  return free.sort((a, b) => Math.abs(SEATS[a].x - state[k].x) - Math.abs(SEATS[b].x - state[k].x))[0] ?? null;
}
const moves = Object.fromEntries(KEYS.map(k => [k, []]));
const WALK_SPEED = 230;                 // world px per second
const arms = Object.fromEntries(KEYS.map(k => [k, []]));      // [arm, gesture, t0, t1, kind, arg]
const exprs = Object.fromEntries(KEYS.map(k => [k, []]));     // [t0, expression]

const GEST = {   // script gesture -> [arm, animator gesture, hand kind]
  open_palms: ['both', 'openPalms'], point: ['R', 'pointAt', 'point'], shrug: ['both', 'shrug'], arms_up: ['both', 'armsUp'],
  head_scratch: ['R', 'headScratch'], hands_on_hips: ['both', 'hip'], hand_on_chest: ['L', 'chest'], facepalm: ['R', 'face'],
  thumbs_up: ['R', 'thumbsUp', 'thumb'], wave: ['R', 'wave'], beat: ['L', 'beat'], cross_arms: ['both', 'cross'], hands_on_head: ['both', 'onHead'],
};
const nearestOther = (k, x) => KEYS.filter(o => o !== k && state[o].on).sort((a, b) => Math.abs(state[a].x - x) - Math.abs(state[b].x - x))[0];

let sceneNow = 0;
for (const ln of spec.lines) {
  const k = ln.speaker, t = ln.start, len = ln.end - ln.start;
  // a cut to the next scene: its set, and everyone placed as that scene starts (cuts reset staging)
  while (sceneNow + 1 < SCENES.length && SCENES[sceneNow + 1].t0 <= t) {
    sceneNow++;
    const sc = SCENES[sceneNow];
    useScene(sceneNow);
    for (const c of KEYS) {
      for (const m of moves[c]) if (m.t1 > sc.t0) m.t1 = Math.max(m.t0, sc.t0 - 0.001);
      const v = (sc.starts || {})[c] || 'off', mm = /^seat:(\d+)$/.exec(v), si = mm && SEATS[+mm[1]] ? +mm[1] : null;
      state[c] = si !== null ? {x: SEATS[si].x, seated: true, seat: si, on: true}
        : {x: v === 'on' ? home[c] : SET.width + 160, seated: false, seat: null, on: v === 'on'};
      moves[c].push({t0: sc.t0, t1: sc.t0, kind: 'place', x: state[c].x, seated: state[c].seated, seat: state[c].seat});
    }
  }
  exprs[k].push([t, ln.expression || 'neutral']);
  exprs[k].push([ln.end + 0.5, 'neutral']);
  // movement first: it starts with the line (characters talk while they move)
  const mv = ln.move;
  if (mv) {
    const s = state[k];
    let target = null, kind = 'walk', si = null;
    if (mv.type === 'enter') { s.on = true; s.x = (mv.to === 'left' ? -160 : SET.width + 160); target = home[k]; }
    else if (mv.type === 'exit') target = (s.x < SET.width / 2 ? -200 : SET.width + 200);
    else if (mv.type === 'sit' && !s.seated && (si = pickSeat(k, mv.to)) !== null) target = SEATS[si].x + 40, kind = 'walk-sit';
    else if (mv.type === 'sit' && !s.seated) warnings.push(`${k} at ${t.toFixed(1)} s: asked to sit, but ${SEATS.length ? 'every seat is taken' : 'the set has no seat'}: stays standing`);
    else if (mv.type === 'stand') kind = 'stand';
    else if (mv.type === 'jump') kind = 'jump';
    else if (mv.type === 'walk_to') {
      if (/^seat(:\d+)?$/.test(mv.to || '') && (si = pickSeat(k, mv.to)) !== null) target = SEATS[si].x + 40;
      else if (/^seat(:\d+)?$/.test(mv.to || '')) warnings.push(`${k} at ${t.toFixed(1)} s: asked to walk to a seat, but ${SEATS.length ? 'every seat is taken' : 'the set has no seat'}: stays in place`);
      else if (KEYS.includes(mv.to)) { const o = state[mv.to]; target = o.x + (o.x > s.x ? -1 : 1) * (halfW(k) + halfW(mv.to)); }
      else if (mv.to === 'left') target = SET.stand_min_x + halfW(k); else if (mv.to === 'right') target = SET.stand_max_x - halfW(k);
      else target = (SET.stand_min_x + SET.stand_max_x) / 2;
    }
    if (kind === 'stand' && s.seated) { moves[k].push({t0: t, t1: t + 0.6, kind: 'stand', seat: s.seat, from: s.x, to: SEATS[s.seat].x + 40}); s.seated = false; s.x = SEATS[s.seat].x + 40; s.seat = null; }
    else if (kind === 'jump') moves[k].push({t0: t, t1: t + 1.1, kind: 'jump', from: s.x, to: s.x});
    else if (target !== null) {
      if (s.seated) { moves[k].push({t0: t, t1: t + 0.6, kind: 'stand', seat: s.seat, from: s.x, to: SEATS[s.seat].x + 40}); s.seated = false; s.x = SEATS[s.seat].x + 40; s.seat = null; }
      const t0 = moves[k].at(-1)?.t1 > t ? moves[k].at(-1).t1 : t;
      const dur = Math.max(0.8, Math.abs(target - s.x) / WALK_SPEED);
      moves[k].push({t0, t1: t0 + dur, kind: 'walk', from: s.x, to: target});
      s.x = target;
      if (kind === 'walk-sit') { moves[k].push({t0: t0 + dur, t1: t0 + dur + 0.6, kind: 'sit', seat: si, from: s.x, to: SEATS[si].x}); s.seated = true; s.seat = si; s.x = SEATS[si].x; }
      if (mv.type === 'exit') s.on = false;
    }
  }
  // the speaker's gesture (held for most of the line); without one, small beat gestures on longer lines
  const g = GEST[ln.gesture];
  if (g) {
    const dir = ln.look_at && state[ln.look_at] ? Math.sign(state[ln.look_at].x - state[k].x) : Math.sign((state[nearestOther(k, state[k].x)]?.x ?? state[k].x) - state[k].x) || 1;
    arms[k].push([g[0], g[1], t + 0.05, t + Math.max(1.2, Math.min(len, 3.2)), g[2], dir]);
  } else if (len > 2.2 && !state[k].seated) {
    for (let b = t + 0.3, i = 0; b < ln.end - 0.8; b += 1.7, i++) arms[k].push([i % 2 ? 'R' : 'L', 'beat', b, b + 1.1]);
  }
  for (const r of ln.reactions || []) {
    if (!state[r.character]) continue;
    if (r.expression) { exprs[r.character].push([t + 0.25, r.expression]); exprs[r.character].push([t + Math.max(1.6, Math.min(len, 3.0)), 'neutral']); }
    const rg = GEST[r.gesture];
    if (rg) arms[r.character].push([rg[0], rg[1], t + 0.3, t + Math.max(1.3, Math.min(len, 2.6)), rg[2], Math.sign(state[k].x - state[r.character].x) || 1]);
  }
}

// ---------------------------------------------------------------- gesture targets (relative to the shoulder, source px)
const G = {
  rest: (c, side) => side < 0 ? {x: c.handL.x - c.shoulderL.x, y: c.handL.y - c.shoulderL.y} : {x: c.handR.x - c.shoulderR.x, y: c.handR.y - c.shoulderR.y},
  openPalms: (c, side, u) => ({x: side * c.armLen * 0.62, y: c.armLen * 0.38 + Math.sin(u * 7) * 6}),
  pointAt: (c, side, u, dir) => ({x: dir * c.armLen * 0.93, y: -c.armLen * 0.18}),
  shrug: (c, side) => ({x: side * c.armLen * 0.62, y: -c.armLen * 0.12}),
  armsUp: (c, side, u) => ({x: side * c.armLen * 0.38, y: -c.armLen * 0.92 + Math.sin(u * 16) * 10}),
  headScratch: (c, side, u) => ({x: side * 40, y: -c.armLen * 0.86 + Math.sin(u * 22) * 14}),
  hip: (c, side) => ({x: side * c.armLen * 0.46, y: c.armLen * 0.62}),
  chest: (c, side) => ({x: -side * c.armLen * 0.45, y: c.armLen * 0.32}),
  face: (c, side) => ({x: -side * c.armLen * 0.5, y: -c.armLen * 0.55}),
  thumbsUp: (c, side) => ({x: side * c.armLen * 0.35, y: c.armLen * 0.05}),
  wave: (c, side, u) => ({x: side * c.armLen * 0.55, y: -c.armLen * 0.75, swing: Math.sin(u * 12)}),
  beat: (c, side, u) => ({x: side * c.armLen * 0.25 - side * 30, y: c.armLen * 0.48 - Math.sin(u * 9) * 18}),
  cross: (c, side) => ({x: -side * c.armLen * 0.38, y: c.armLen * 0.4}),
  onHead: (c, side) => ({x: side * c.armLen * 0.12, y: -c.armLen * 1.25}),   // hands on top of the head, clear of the face
};

// ---------------------------------------------------------------- per-frame pose
function speakingLine(k, t) { return spec.lines.find(l => l.speaker === k && t >= l.start && t < l.end); }
function viseme(k, t) { const l = speakingLine(k, t); if (!l) return 'X'; const u = t - l.start; const c = (l.cues || []).find(c => u >= c.start && u < c.end); return c ? c.value : 'X'; }
function expressionAt(k, t) { let e = 'neutral', best = -1; for (const [t0, x] of exprs[k]) if (t0 <= t && t0 >= best) { e = x; best = t0; } return C[k].faces[e] ? e : 'neutral'; }
function blink(k, t) {
  let seed = [...k].reduce((a, ch) => a * 31 + ch.charCodeAt(0), 7) % 997, tt = 0.6 + (seed % 10) / 10;
  while (tt < t + 1) { const d = t - tt; if (d >= 0 && d < 0.17) return d < 0.06 ? d / 0.06 : d < 0.09 ? 1 : 1 - (d - 0.09) / 0.08; seed = (seed * 73 + 41) % 997; tt += 2.4 + (seed % 20) / 10; }
  return 0;
}

// Where a character is at time t: replays its locomotion segments.
function locomotion(k, t) {
  const c = C[k], stand = FLOOR() - hipHeight(c);
  const s0 = startSeat(k);
  let x = s0 !== null ? SEATS[s0].x : spec.cast[k].start === 'off' ? SET.width + 160 : homes[0][k], seated = s0 !== null, seat = s0, out = null;
  for (const m of moves[k]) {
    if (t < m.t0) break;
    if (m.kind === 'place') { x = m.x; seated = m.seated; seat = m.seat; continue; }
    const u = clamp((t - m.t0) / (m.t1 - m.t0));
    if (m.kind === 'walk') {
      if (t <= m.t1) out = walkPose(c, m, t); else x = m.to;
    } else if (m.kind === 'sit') { if (t <= m.t1) out = sitPose(c, m, u, false); else { seated = true; seat = m.seat; x = SEATS[m.seat].x; } }
    else if (m.kind === 'stand') { if (t <= m.t1) out = sitPose(c, m, 1 - u, true); else { seated = false; seat = null; x = m.to; } }
    else if (m.kind === 'jump' && t <= m.t1) out = {jump: (t - m.t0) / (m.t1 - m.t0), x, hipY: stand};
    if (out) return {...out, x: out.x ?? x};
  }
  if (seated) return sitPose(c, {seat, from: SEATS[seat].x + 40, to: SEATS[seat].x}, 1, false);
  return {x, hipY: stand};
}
const FLOOR = () => SET.floor_y;

function walkPose(c, m, t) {
  const dist = m.to - m.from, dir = Math.sign(dist) || 1;
  const steps = Math.max(2, Math.round(Math.abs(dist) / (c.legLen * c.S * 0.5)));
  const stride = dist / steps, u = clamp((t - m.t0) / (m.t1 - m.t0)) * steps, k = Math.min(steps - 1, Math.floor(u)), f = u - k;
  let posL = 0, posR = 0;
  for (let i = 0; i < k; i++) { if ((i % 2 === 0) === (dir > 0)) posR = i + 1; else posL = i + 1; }
  const moverR = (k % 2 === 0) === (dir > 0), sf = ease.inOut(f);
  if (moverR) posR = lerp(posR, k + 1, sf); else posL = lerp(posL, k + 1, sf);
  const lift = Math.sin(Math.PI * f) * c.legLen * c.S * 0.16;
  const stance = 0.12;   // turned body: feet close together under it, so the legs read as walking sideways
  return {walking: true, dir, x: m.from + stride * (posL + posR) / 2, hipY: FLOOR() - hipHeight(c) - Math.abs(Math.sin(Math.PI * f)) * 9,
    feet: {L: {x: m.from + stride * posL + c.hipL.x * c.S * stance, y: FLOOR() - (moverR ? 0 : lift)},
           R: {x: m.from + stride * posR + c.hipR.x * c.S * stance, y: FLOOR() - (moverR ? lift : 0)}}};
}

function sitPose(c, m, u, rising) {
  const S = SEATS[m.seat ?? 0];
  const down = rising ? ease.inOut(u) : ease.back(u);
  const standHip = FLOOR() - hipHeight(c);
  const fy = lerp(FLOOR(), S.feet_y, ease.inOut(u));
  return {seated: u > 0.5, sitting: u, x: lerp(m.from ?? S.x + 40, S.x, ease.inOut(u)), hipY: lerp(standHip, S.hip_y, down),
    feet: {L: {x: S.x - 34, y: fy}, R: {x: S.x + 34, y: fy}}, seatedFeetY: S.feet_y};
}

const looks = Object.fromEntries(KEYS.map(k => [k, {x: 0, y: 0.1}]));
function pose(k, t) {
  const c = C[k], L = locomotion(k, t);
  const p = {lean: 0, breath: Math.sin(t * 2.1 + k.length) * 0.008, squash: 1, headTilt: 0, headNod: 0, expression: expressionAt(k, t)};
  let x = L.x, hipY = L.hipY, feet = L.feet, kneeDir = null;
  if (L.walking) { p.turn = 1; p.turnDir = L.dir; p.lean = 0.05 * L.dir; p.headTilt = Math.sin(t * 9) * 0.025; }
  if (L.sitting !== undefined) {
    // seated: knees forward and slightly apart, shins down to the floor in front of the seat
    kneeDir = {x: 0, y: -0.15};
    if (L.sitting < 1) p.lean = Math.sin(L.sitting * Math.PI) * 0.16;
  }
  if (L.jump !== undefined) {
    const u = L.jump, lift = u < 0.12 ? -u / 0.12 * 22 : u < 0.62 ? Math.sin((u - 0.12) / 0.5 * Math.PI) * 95 : 0;
    hipY -= lift; p.squash = u < 0.12 ? 0.93 : u < 0.35 ? 1.07 : u > 0.62 && u < 0.8 ? 0.92 : 1;
    p.headStretch = u > 0.12 && u < 0.6 ? 1.12 : 1; p.pupilScale = 0.6;
    if (lift > 0) feet = {L: {x: x + c.hipL.x * c.S * 0.75, y: FLOOR() - lift * 0.85}, R: {x: x + c.hipR.x * c.S * 0.75, y: FLOOR() - lift * 0.85}};
  }
  // talking: head bobs with the mouth, gentle sway; reactions tilt the head
  if (speakingLine(k, t)) {
    const open = {B: 0.3, C: 0.6, D: 1, E: 0.6, F: 0.4, G: 0.25, H: 0.5}[viseme(k, t)] || 0;
    p.headNod += -open * 6; p.headTilt += Math.sin(t * 3.1) * 0.05;
  }
  p.viseme = viseme(k, t);
  p.blink = blink(k, t);
  // eyes: the speaker looks at look_at / the nearest character; listeners look at the speaker
  const cur = spec.lines.find(l => t >= l.start && t < l.end + 0.4);
  let target = null;
  if (cur) target = cur.speaker === k ? (cur.look_at || nearestOtherAt(k, t)) : cur.speaker;
  let look = {x: 0, y: 0.1};
  if (L.walking) look = {x: 0.8 * L.dir, y: 0};
  // a target outside this render's cast (the spec builder adds everyone a line references; this guards older specs)
  else if (target && target !== k && C[target]) look = {x: clamp((locomotion(target, t).x - x) / 160, -1, 1), y: 0.05};
  const lk = looks[k]; lk.x += (look.x - lk.x) * 0.35; lk.y += (look.y - lk.y) * 0.35; p.look = {...lk};
  // arms
  for (const side of [-1, 1]) {
    const key = side < 0 ? 'L' : 'R';
    let tgt = G.rest(c, side), kind = 'mitten';
    tgt = {x: tgt.x + Math.sin(t * 1.7 + side) * 5, y: tgt.y};
    if (L.walking) tgt = {x: tgt.x * 0.6 - L.dir * Math.sin(t * 7.5 + (side > 0 ? Math.PI : 0)) * c.armLen * 0.18, y: tgt.y};
    if (L.seated && !L.walking) tgt = {x: side * c.armLen * 0.22, y: c.armLen * 0.7};
    for (const [arm, g, t0, t1, hk, dir] of arms[k]) {
      if (!(arm === 'both' || arm === key)) continue;
      const e = envelope(t, t0, t1, 0.26, 0.3, true);
      if (e <= 0) continue;
      const gt = G[g](c, side, t - t0, dir || 1);
      tgt = {x: lerp(tgt.x, gt.x, e), y: lerp(tgt.y, gt.y, e)};
      if (e > 0.5 && hk) kind = hk;
    }
    p[`hand${key}`] = tgt; p[`handKind${key}`] = kind;
  }
  if (!feet) feet = {L: {x: x + c.hipL.x * c.S * 0.75, y: FLOOR()}, R: {x: x + c.hipR.x * c.S * 0.75, y: FLOOR()}};
  const ankleUp = (c.footDrop - c.ankleL.y) * c.S;
  p.footL = {x: feet.L.x, y: feet.L.y - ankleUp}; p.footR = {x: feet.R.x, y: feet.R.y - ankleUp};
  p.kneeDir = kneeDir; p.hip = {x, y: hipY}; p.seated = !!L.seated; p.seatedFeetY = L.seatedFeetY; p.onStage = x > -150 && x < SET.width + 150;
  return p;
}
function nearestOtherAt(k, t) {
  const x = locomotion(k, t).x;
  return KEYS.filter(o => o !== k).map(o => [o, Math.abs(locomotion(o, t).x - x)]).filter(([o]) => { const ox = locomotion(o, t).x; return ox > -100 && ox < SET.width + 100; })
    .sort((a, b) => a[1] - b[1])[0]?.[0] || null;
}

// ---------------------------------------------------------------- camera: fit the full bodies of everyone on stage
let cam = null, camShot = null;
const headTop = (k, p) => p.hip.y - (C[k].footDrop * 1.75) * C[k].S;
function shotBox(kind, keys, poses) {
  // world box around the given characters: medium = down to the knees, close = head and torso
  let x0 = Infinity, x1 = -Infinity, top = Infinity, bottom = -Infinity;
  for (const k of keys) {
    const p = poses[k], c = C[k];
    x0 = Math.min(x0, p.hip.x - halfW(k)); x1 = Math.max(x1, p.hip.x + halfW(k)); top = Math.min(top, headTop(k, p));
    bottom = Math.max(bottom, kind === 'close' ? p.hip.y + 10 : p.hip.y + c.legLen * c.S * 0.55);
  }
  const pad = kind === 'close' ? 30 : 50;
  let w = Math.max(x1 - x0 + 2 * pad, (bottom - top + 2 * pad) * W / H, kind === 'close' ? (x1 - x0) * 2.1 : 380), h = w * H / W;
  w = Math.min(w, SET.width); h = w * H / W;
  // a close-up keeps the speaker off-centre (towards the side of the set they stand on) so the bubble has room
  const cx = (x0 + x1) / 2 + (kind === 'close' ? ((x0 + x1) / 2 < SET.width / 2 ? 0.2 : -0.2) * w : 0);
  return {x0: clamp(cx - w / 2, 0, SET.width - w), y0: clamp(top - pad - (h - (bottom - top + 2 * pad)) * 0.35, 0, SET.height - h), w};
}
function camera(poses, t) {
  // the line being spoken (or the one just finished) decides the shot; a new shot is a hard cut
  const li = spec.lines.findIndex(l => t >= l.start - 0.05 && t < l.end + 0.15);
  const line = li >= 0 ? spec.lines[li] : null;
  const moving = KEYS.some(k => { const L = locomotion(k, t); return L.walking || L.jump !== undefined || (L.sitting !== undefined && L.sitting < 1); })
    || (line && line.move);
  let kind = (!line || moving) ? 'wide' : (line.shot || 'wide');
  if (kind !== 'wide') {
    const keys = kind === 'close' ? [line.speaker] : [line.speaker, line.look_at || nearestOtherAt(line.speaker, t)].filter(k => k && poses[k] && poses[k].onStage);
    if (keys.length && keys.every(k => poses[k].onStage)) {
      const target = shotBox(kind, keys, poses), id = `${li}:${kind}`;
      if (camShot !== id) { cam = {...target}; camShot = id; }          // cut
      else for (const k of ['x0', 'y0', 'w']) cam[k] += (target[k] - cam[k]) * 0.08;
      return cam;
    }
  }
  if (camShot && camShot !== 'wide') { cam = null; }                     // cut back to the wide shot
  camShot = 'wide';
  const on = KEYS.filter(k => poses[k].onStage);
  let x0 = Infinity, x1 = -Infinity, top = Infinity;
  for (const k of on) { const p = poses[k], c = C[k]; x0 = Math.min(x0, p.hip.x - halfW(k)); x1 = Math.max(x1, p.hip.x + halfW(k)); top = Math.min(top, p.hip.y - (c.footDrop * 1.75) * c.S); }
  if (!on.length) { x0 = SET.stand_min_x; x1 = SET.stand_max_x; top = FLOOR() - 700; }
  const bottom = FLOOR() + 70;
  let w = Math.max(x1 - x0 + 60, (bottom - top + 40) * W / H, 420), h = w * H / W;
  w = Math.min(w, SET.width); h = w * H / W;
  const target = {x0: clamp((x0 + x1) / 2 - w / 2, 0, SET.width - w), y0: clamp(bottom - h, 0, SET.height - h), w};
  // smooth, critically damped follow (no jitter, no sudden zooms)
  if (!cam) cam = {...target};
  for (const k of ['x0', 'y0', 'w']) cam[k] += (target[k] - cam[k]) * 0.06;
  return cam;
}

// ---------------------------------------------------------------- frame
const plates = await Promise.all(SCENES.map(sc => loadImage(sc.set.plate)));
let plate = plates[0];
function wrapText(ctx, text, maxW) {
  const rows = []; let cur = '';
  for (const w of text.split(/\s+/)) { const nx = cur ? cur + ' ' + w : w; if (ctx.measureText(nx).width > maxW && cur) { rows.push(cur); cur = w; } else cur = nx; }
  if (cur) rows.push(cur);
  return rows;
}

// The POV banner (spec.hook): laid out once, drawn on every frame. Without banner fonts in the spec, the older yellow
// hook box below is used (specs written before 2026-11-20).
const BANNER_FONTS = spec.hook && spec.banner_font ? registerBannerFonts(spec.banner_font, spec.emoji_font) : null;
const BANNER_LAYOUT = BANNER_FONTS && BANNER_FONTS.banner ? layoutBanner(createCanvas(W, 400).getContext('2d'), spec.hook, W) : null;
const HOOK_BOTTOM = BANNER_LAYOUT ? BANNER_LAYOUT.bottom : 220;

function drawHook(ctx) {
  if (BANNER_LAYOUT) { drawBanner(ctx, BANNER_LAYOUT); return; }
  // permanent top banner (the episode's hook): black bold capitals on a yellow box with a black border
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.font = '800 50px Sub'; ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
  const rows = wrapText(ctx, spec.hook.toUpperCase(), W * 0.82).slice(0, 2);
  const tw = Math.max(...rows.map(r => ctx.measureText(r).width)), bh = 34 + rows.length * 60, x = 46, y = 70;
  ctx.fillStyle = '#ffe11a'; ctx.strokeStyle = '#111'; ctx.lineWidth = 7;
  ctx.beginPath(); ctx.roundRect(x, y, tw + 56, bh, 10); ctx.fill(); ctx.stroke();
  ctx.fillStyle = '#111';
  rows.forEach((r, i) => ctx.fillText(r, x + 28, y + 17 + 30 + i * 60));
}

function drawBubble(ctx, t, poses, v, s) {
  // comic speech bubble by the speaker's head: above it when there is room, otherwise beside it (the side with more
  // space); the tail points at the face; never covers the head; always fully inside the frame
  const line = spec.lines.find(l => t >= l.start && t < l.end + 0.1);
  if (!line || !poses[line.speaker] || !poses[line.speaker].onStage) return;
  const k = line.speaker, p = poses[k], c = C[k];
  const hx = (p.hip.x - v.x0) * s, top = (headTop(k, p) - v.y0) * s;
  const headH = (p.hip.y + c.neck.y * c.S - headTop(k, p)) * s, faceY = top + headH * 0.6, headHalf = halfW(k) * s * 0.75;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  let size = 44, rows;
  for (; size >= 30; size -= 4) {   // long lines get a smaller font rather than being cut off
    ctx.font = `800 ${size}px Sub`;
    rows = wrapText(ctx, line.text.toUpperCase(), W * 0.52);
    if (rows.length <= 4) break;
  }
  const lh = size * 1.18, bw = Math.max(...rows.map(r => ctx.measureText(r).width)) + 64, bh = rows.length * lh + 40;
  const minY = (spec.hook ? HOOK_BOTTOM : 40) + 10;
  // every visible head (screen rectangles): a bubble must not cover any of them
  const heads = KEYS.filter(o => poses[o].onStage).map(o => {
    const q = poses[o], cq = C[o], tp = (headTop(o, q) - v.y0) * s, hh = (q.hip.y + cq.neck.y * cq.S - headTop(o, q)) * s;
    const cx = (q.hip.x - v.x0) * s, half = halfW(o) * s * 0.8;
    return [cx - half, tp - 10, cx + half, tp + hh + 10];
  });
  const overlap = (x, y) => heads.reduce((a, [l, tp, r, b]) => a + Math.max(0, Math.min(x + bw, r) - Math.max(x, l)) * Math.max(0, Math.min(y + bh, b) - Math.max(y, tp)), 0);
  const fit = (x, y) => [clamp(x, 24, W - bw - 24), clamp(y, minY, H - bh - 40)];
  const cands = [
    ['above', ...fit(hx + (hx < W / 2 ? 50 : -50) - bw / 2, top - bh - 50)],
    ['right', ...fit(hx + headHalf + 30, faceY - bh / 2 - 40)],
    ['left', ...fit(hx - headHalf - 30 - bw, faceY - bh / 2 - 40)],
    ['banner', ...fit(hx - bw / 2, minY)],
    ['banner', ...fit(24, minY)], ['banner', ...fit(W - bw - 24, minY)],
  ].map(([side, x, y]) => ({side, x, y, cost: overlap(x, y) + Math.hypot(x + bw / 2 - hx, y + bh / 2 - faceY) * 0.5}));
  cands.sort((a, b) => a.cost - b.cost);
  let {side, x: bx, y: by} = cands[0];
  let tip, base;
  if (side === 'left' || side === 'right') {
    const ty = clamp(faceY, by + 30, by + bh - 30), ex = side === 'right' ? bx + 3 : bx + bw - 3;
    base = [[ex, ty - 18], [ex, ty + 18]]; tip = [side === 'right' ? hx + headHalf * 0.85 : hx - headHalf * 0.85, faceY];
  } else {
    const tx = clamp(hx, bx + 34, bx + bw - 34);
    base = [[tx - 20, by + bh - 3], [tx + 20, by + bh - 3]]; tip = [clamp(hx, 30, W - 30), Math.max(by + bh + 20, top - 8)];
  }
  ctx.fillStyle = '#fff'; ctx.strokeStyle = '#111'; ctx.lineWidth = 6; ctx.lineJoin = 'round';
  ctx.beginPath(); ctx.roundRect(bx, by, bw, bh, Math.min(bh / 2.2, 60)); ctx.fill(); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(...base[0]); ctx.lineTo(...tip); ctx.lineTo(...base[1]); ctx.fill(); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(base[0][0], base[0][1]); ctx.lineTo(base[1][0], base[1][1]);   // hide the seam
  ctx.lineWidth = 8; ctx.strokeStyle = '#fff'; ctx.stroke();
  ctx.fillStyle = '#111';
  rows.forEach((r, i) => ctx.fillText(r, bx + bw / 2, by + 20 + lh / 2 + i * lh));
}

function drawEndCard(ctx, u) {
  // the show's end card: the set softly darkened, the show title in the caption style, fading in
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = `rgba(20,12,8,${0.72 * Math.min(1, u * 3)})`; ctx.fillRect(0, 0, W, H);
  ctx.globalAlpha = Math.min(1, u * 3);
  ctx.font = '700 96px Sub'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.lineJoin = 'round';
  ctx.lineWidth = 14; ctx.strokeStyle = '#111'; ctx.strokeText(spec.end_card.text, W / 2, H * 0.45);
  ctx.fillStyle = '#fff'; ctx.fillText(spec.end_card.text, W / 2, H * 0.45);
  ctx.globalAlpha = 1;
}

function drawFrame(ctx, t) {
  const cardFrom = spec.end_card ? DUR - spec.end_card.seconds : Infinity;
  if (t >= cardFrom) { drawScene(ctx, cardFrom - 0.001); drawEndCard(ctx, (t - cardFrom) / spec.end_card.seconds); return; }
  drawScene(ctx, t);
}

function drawScene(ctx, t) {
  const si = sceneAt(t);
  useScene(si); plate = plates[si];
  const poses = Object.fromEntries(KEYS.map(k => [k, pose(k, t)]));
  const v = camera(poses, t), s = W / v.w;
  if (![v.x0, v.y0, v.w].every(Number.isFinite)) throw new Error(`invalid camera at t=${t.toFixed(2)}`);
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H);
  ctx.setTransform(s, 0, 0, s, -v.x0 * s, -v.y0 * s);
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(plate, 0, 0);
  const order = [...KEYS].sort((a, b) => (poses[a].seated ? -1 : 0) - (poses[b].seated ? -1 : 0));
  for (const k of order) { const p = poses[k]; if (!p.onStage) continue; const fy = p.seated ? (p.seatedFeetY ?? FLOOR()) : FLOOR(); ctx.fillStyle = 'rgba(40,20,10,0.22)'; ctx.beginPath(); ctx.ellipse(p.hip.x, fy, halfW(k) * 0.7, 13, 0, 0, Math.PI * 2); ctx.fill(); }
  // seated characters, then the table front (that part of the plate again, so they sit behind the table), then
  // everyone standing (in front of it)
  for (const k of order) if (poses[k].onStage && poses[k].seated) drawCharacter(ctx, C[k], poses[k]);
  const tf = SET.table_front;
  if (tf && tf.x1 > tf.x0 && tf.y1 > tf.y0) ctx.drawImage(plate, tf.x0, tf.y0, tf.x1 - tf.x0, tf.y1 - tf.y0, tf.x0, tf.y0, tf.x1 - tf.x0, tf.y1 - tf.y0);
  for (const k of order) if (poses[k].onStage && !poses[k].seated) drawCharacter(ctx, C[k], poses[k]);
  if (spec.bubbles) drawBubble(ctx, t, poses, v, s);
  if (spec.hook) drawHook(ctx);
  if (spec.captions) {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    const line = spec.lines.find(l => t >= l.start && t < l.end + 0.25);
    if (line) {
      ctx.font = '700 52px Sub'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.lineJoin = 'round';
      const rows = []; let cur = '';
      for (const w of line.text.split(' ')) { const nx = cur ? cur + ' ' + w : w; if (ctx.measureText(nx).width > W * 0.84 && cur) { rows.push(cur); cur = w; } else cur = nx; }
      rows.push(cur);
      // captions sit in the lower third, clear of the POV banner at the top and of the platform's buttons at the bottom
      rows.forEach((r, i) => { const y = H * 0.70 + i * 64; ctx.lineWidth = 10; ctx.strokeStyle = '#111'; ctx.strokeText(r, W / 2, y); ctx.fillStyle = '#fff'; ctx.fillText(r, W / 2, y); });
    }
  }
}

const t0 = Date.now();
await renderVideo({width: W, height: H, fps: FPS, seconds: DUR, drawFrame: (ctx, t) => drawFrame(ctx, t), out: OUT,
  ffmpeg: process.env.FFMPEG || 'ffmpeg', font: spec.font});
console.log(JSON.stringify({out: OUT, seconds: DUR, frames: Math.round(DUR * FPS), render_seconds: (Date.now() - t0) / 1000, warnings}));
