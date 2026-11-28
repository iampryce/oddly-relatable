// "What if every lie made you smaller?" Narrated short, 8 scenes, 30 fps. Cast: Sam (hero), Kit (niece), Dev (boss), Mo (uncle).
// Staged in the study world of main.js (desk set + family row). Timings are PLACEHOLDERS from word counts (3.7 words/s) until the
// narration is made; retime SC[] from the voice's word timings (tools/timing.py) when it exists.
import { M, clamp, lerp, ramp, camFromKeys, q } from './motion.js';
export const FPS = 30;
export const FAMX = [-1.6, -0.9, -0.2, 0.5, 1.2, 1.9], FAMZ = 2.9;
// scene starts (frames) and the end
export const SC = [0, 90, 144, 252, 348, 450, 588, 648];
export const TOTAL = 726;
const S = 0.6, U = 2.25 * S / 1000;                       // card scale: 1000 design units = 1.35 m at scale S
const SEAT = 0.13, DTOP = 0.78, DESKZ = -0.9;
const worldY = (y0, Y) => y0 + (975 - Y) * U;
const HIP = 0.474;                                              // chair-seat height (hips of a seated card at scale S)
const seatY = (sc) => HIP - 255 * U * sc;                         // y0 that keeps the hips on the seat for a card scaled by sc

// ---------- shots ----------
export const SHOTS = [
  { id: 'desk', a: 0, b: 143 }, { id: 'row3', a: 144, b: 251 }, { id: 'row4', a: 252, b: 347 }, { id: 'row5', a: 348, b: 449 },
  { id: 'top', a: 450, b: 647 }, { id: 'wide', a: 648, b: 725 },
];
export const shotAt = (f) => SHOTS.find((s) => f >= s.a && f <= s.b) || SHOTS[SHOTS.length - 1];
const HEADY = 293;
const rowHead = (x) => [x, worldY(SEAT, HEADY), FAMZ - 0.03];
const CAMS = {
  desk: [{ f: 0, pos: [0.0, 1.27, 2.3], look: [0, 1.18, -1.45], fov: 28 }, { f: 143, pos: [0.02, 1.25, 1.85], look: [0, 1.17, -1.45], fov: 24 }],
  row3: [{ f: 144, pos: [0.1, 1.08, 1.3], look: [0.12, 0.98, 2.87], fov: 36 }, { f: 251, pos: [0.14, 1.08, 1.4], look: [0.14, 0.98, 2.87], fov: 34 }],
  row4: [{ f: 252, pos: [0.1, 1.08, 1.3], look: [0.12, 0.98, 2.87], fov: 36 }, { f: 347, pos: [0.14, 1.08, 1.4], look: [0.14, 0.98, 2.87], fov: 34 }],
  row5: [{ f: 348, pos: [0.1, 1.08, 1.3], look: [0.12, 0.98, 2.87], fov: 36 }, { f: 449, pos: [0.14, 1.08, 1.4], look: [0.14, 0.98, 2.87], fov: 34 }],
  top: [{ f: 450, pos: [0.3, 1.12, 0.1], look: [0.05, 0.9, -0.7], fov: 34 }, { f: 647, pos: [0.15, 0.98, -0.08], look: [0.05, 0.86, -0.7], fov: 27 }],
  wide: [{ f: 648, pos: [0.4, 1.08, 0.2], look: [0.3, 0.88, -0.8], fov: 36 }, { f: 725, pos: [0.38, 1.0, 0.0], look: [0.3, 0.85, -0.8], fov: 30 }],
};
export const camAt = (f) => camFromKeys(CAMS[shotAt(f).id], f, { creep: 0.0004 });
export const dofAt = (f) => { const Sh = shotAt(f), C = camAt(f), l = C.look; const d = Math.hypot(C.pos[0] - l[0], C.pos[1] - l[1], C.pos[2] - l[2]); return { focus: d, cinf: Sh.id === 'top' ? 9 : 6, near: 1 }; };
const STUDY = { az: 120, el: 42, sky: '#fff8ea', ground: '#d6b48a', hemi: 1.75, sun: '#fff0d6', sunI: 1.3, sat: 1.08, gain: '#fffaf2', vig: 0.18, shadowExt: 3.5, ink: 2.2 };
export const lightFor = (Sh) => ({ ...STUDY, shadowExt: Sh.id.startsWith('row') || Sh.id === 'wide' ? 2.6 : 3.5 });

// ---------- helpers ----------
const keyOf = (who, o) => who + JSON.stringify(o, (k, v) => (typeof v === 'number' ? q(v, 3) : v));
const blinkAt = (f, seed) => { const per = 70 + (seed * 17) % 41, ph = (f + seed * 23) % per; return ph < 2 ? 0.5 : ph < 4 ? 1 : ph < 6 ? 0.4 : 0; };
const idle = (f, seed) => ({ bob: 0.004 * Math.sin((f + seed * 11) * 0.07), roll: 1.0 * Math.sin((f + seed * 5) * 0.03 + seed) });
const mk = (who, o, x, y, z, s) => ({ key: keyOf(who, o), draw: (p) => window.__T.stickFront(p, who, o), x, y, z, s });

// Sam's size: each lie shrinks him a step ("Poof" lands ~ 2.4 s into each lie scene)
const samScale = (f) => {
  const step = (f0, a, b) => M.back(ramp(f, f0, f0 + 7), 1.4) * (b - a) + a;
  if (f < SC[2] + 70) return 1;
  if (f < SC[3] + 62) return step(SC[2] + 70, 1, 0.88);
  if (f < SC[4] + 70) return step(SC[3] + 62, 0.88, 0.76);
  if (f < SC[5]) return step(SC[4] + 70, 0.76, 0.52);
  return 0.085;
};
const poofAt = (f) => { for (const f0 of [SC[2] + 70, SC[3] + 62, SC[4] + 70]) { const k = (f - f0) / 14; if (k >= 0 && k <= 1) return k; } return -1; };

function sam(f) {
  const t = f / FPS, i = idle(f, 1), sc = samScale(f);
  const o = { blink: blinkAt(f, 1), headRoll: i.roll, bodyLean: 0.4 * Math.sin(t * 0.8) };
  const inRow = f >= SC[2] && f < SC[5];
  if (f < SC[2]) {                                       // at the desk: hook, then "found out on a Tuesday"
    Object.assign(o, { seated: true, pose: 'lap', expr: 'neutral', look: [0, 0.1], pitch: 0.1 });
    if (f >= SC[1]) { const k = M.smooth(ramp(f, SC[1] + 6, SC[1] + 30)); o.exprB = 'worried'; o.exprT = k; o.look = [lerp(0, 0.6, k), lerp(0.1, 0.6, k)]; o.pitch = 0.4 * k; }
    const hookNod = Math.sin(Math.max(0, f - 6) * 0.2) * Math.exp(-(f - 6) * 0.03); o.headDY = f < 40 ? 5 * hookNod : 0;
  } else if (inRow) {                                    // telling a small lie, then the poof
    const sIdx = f < SC[3] ? 2 : f < SC[4] ? 3 : 4, t0 = SC[sIdx], poof = (f - (t0 + 70));
    Object.assign(o, { seated: true, pose: 'lap', expr: 'smirk', look: [0.75, 0.15], facing: 0.35, pitch: 0.05 });
    if (poof > -2) { const k = M.smooth(ramp(f, t0 + 70, t0 + 84)); o.exprB = 'shocked'; o.exprT = k; o.look = [lerp(0.75, 0, k), lerp(0.15, 0.2, k)]; o.pose = 'lap'; o.poseB = 'recoil'; o.poseT = k; o.headDY = -14 * Math.sin(Math.PI * clamp(ramp(f, t0 + 70, t0 + 84))); }
  } else if (f < SC[7]) {                                // salt-shaker Sam beside the giant mug, then looking around
    Object.assign(o, { expr: 'worried', pose: 'hang', look: [0.2, 0] });
    if (f >= SC[6]) { const lk = Math.sin((f - SC[6]) * 0.09); o.look = [0.9 * lk, 0.1]; o.facing = 0.35 * lk; o.headRoll = 3 * lk; }
    if (f >= SC[5] + 90 && f < SC[6]) o.expr = 'shocked';
  } else {                                               // the wide: he notices nobody else notices
    Object.assign(o, { pose: 'hang', expr: 'worried', look: [0.5, 0.2] });
    if (f > 690) { o.expr = 'neutral'; o.exprB = 'smirk'; o.exprT = M.smooth(ramp(f, 700, 718)); }
  }
  // placement
  if (f < SC[2]) return mk('samN', o, 0, 0.42 + i.bob, -1.45, S * sc);
  if (inRow) return mk('samN', o, FAMX[2], seatY(sc) + i.bob, FAMZ - 0.03, S * sc);
  if (f < SC[7]) return mk('samN', o, 0.0, DTOP, DESKZ + 0.05, S * sc);
  return mk('samN', o, 0.02, DTOP, DESKZ + 0.05, S * sc);
}

// the person Sam is lying to: Kit (niece), Dev (boss), Mo (uncle). They react, then wobble when he shrinks.
function target(f) {
  const idx = f >= SC[4] ? 4 : f >= SC[3] ? 3 : 2, t0 = SC[idx], who = ['kitN', 'devN', 'moN'][idx - 2], seed = idx;
  const i = idle(f, seed), k = M.smooth(ramp(f, t0 + 70, t0 + 90));
  const o = { seated: true, pose: 'lap', blink: blinkAt(f, seed), headRoll: i.roll, look: [-0.5, 0.05], facing: -0.25 };
  if (who === 'kitN') { o.expr = 'neutral'; o.exprB = 'smug'; o.exprT = 0.6; }
  if (who === 'devN') { o.expr = 'stern'; o.exprB = 'skeptical'; o.exprT = M.smooth(ramp(f, t0 + 20, t0 + 50)); }
  if (who === 'moN') { o.expr = 'smug'; o.exprB = 'neutral'; o.exprT = 0.2; o.pose = 'hang'; }
  if (k > 0 && k < 1) { o.exprB = 'shocked'; o.exprT = k; }
  if (k >= 1 && who !== 'moN') { o.expr = 'shocked'; o.exprB = undefined; }
  return mk(who, o, FAMX[3], SEAT + i.bob, FAMZ - 0.03, S);
}

// scene 8: the others pop in, tiny, on the table next to Sam ("Poof" at ~ f 668 / 678 / 688)
function others(f) {
  const out = [];
  [['kitN', 0.24, 668], ['devN', 0.42, 678], ['moN', 0.6, 688]].forEach(([who, x, f0], n) => {
    const k = M.back(ramp(f, f0, f0 + 8), 1.3); if (k <= 0.001) return;
    const o = { pose: 'hang', blink: blinkAt(f, n + 7), headRoll: idle(f, n + 3).roll, look: [0.5 - 0.5 * n, 0.1], facing: 0.25, expr: who === 'devN' ? 'stern' : 'smug' };
    out.push(mk(who, o, x, DTOP, DESKZ + 0.05, S * 0.085 * k));
    const pk = (f - f0) / 14; if (pk >= 0 && pk <= 1) out.push({ key: 'poofw' + n + q(pk, 1), draw: (p) => window.__T.fxDust(p, pk), x, y: DTOP + 0.05, z: DESKZ - 0.02, s: S * 0.12, order: 3, shadow: false });
  });
  return out;
}

// a mug the size of a swimming pool: a drawn prop card (design units, soles at y=975)
const mugDraw = (p) => {
  const body = [[160, 975], [450, 975], [470, 560], [140, 560]];
  p.poly(body, '#ecebf0', 12);
  p.ell(305, 560, 165, 40, '#9a5a2a', 12);                       // tea surface
  p.ell(305, 560, 165, 40, null, 12);
  p.stroke([[470, 640], [560, 650], [570, 800], [470, 860]], 36, '#121212'); p.stroke([[470, 640], [560, 650], [570, 800], [470, 860]], 24, '#ecebf0');
  p.stroke([[190, 640], [185, 900]], 10, 'rgba(255,255,255,.7)');
};

export const actorsAt = (f, T) => {
  window.__T = T;
  const out = [];
  const Sh = shotAt(f).id;
  if (Sh === 'desk') out.push(sam(f));
  else if (Sh.startsWith('row')) { out.push(sam(f)); out.push(target(f)); }
  else if (Sh === 'top') { out.push({ key: 'mug', draw: mugDraw, x: 0.38, y: DTOP, z: DESKZ + 0.02, s: S * 0.55 }); out.push(sam(f)); }
  else { out.push(sam(f)); out.push(...others(f)); }
  const pk = poofAt(f);
  if (pk >= 0 && Sh.startsWith('row')) { const s0 = sam(f); out.push({ key: 'poof' + q(pk, 1), draw: (p) => window.__T.fxDust(p, pk), x: s0.x, y: s0.y + 0.15, z: s0.z - 0.05, s: S * 0.5, order: 3, shadow: false }); }
  return out;
};
