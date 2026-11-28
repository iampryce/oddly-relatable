// "The Perfectionist and the Builder": a block-stacking race, 30 fps, ~24 s, workshop set. Cast = the approved masters (art heads, measured code bodies):
// Mortimer (perfectionist: measures every block, places 3) vs Winifred (just keeps stacking: finishes 8 first and wins). Timings are placeholders (no narration yet).
import { M, clamp, lerp, ramp, camFromKeys, q } from './motion.js';
export const FPS = 30;
export const FAMX = [-1.6, -0.9, -0.2, 0.5, 1.2, 1.9], FAMZ = 2.9;            // (main.js import; unused)
export const ART = { hybMort: 'ref/mortimer-master.png', hybWin: 'ref/winifred-master.png' };
const PERF = 'hybMort', BUILD = 'hybWin';
export const SC = [0, 90, 190, 290, 390, 480, 570, 650];
export const TOTAL = 720;
const S = 0.6, U = 2.25 * S / 1000, WZ = 0.2;
const BLOCKS = 8, BH = 70, BW = 130;                                            // tower blocks (design units)

// ---------- shots ----------
export const SHOTS = [
  { id: 'wide', a: 0, b: 189 }, { id: 'perf', a: 190, b: 289 }, { id: 'build', a: 290, b: 389 }, { id: 'wide2', a: 390, b: 479 },
  { id: 'win', a: 480, b: 569 }, { id: 'perf2', a: 570, b: 649 }, { id: 'end', a: 650, b: 719 },
];
export const shotAt = (f) => SHOTS.find((s) => f >= s.a && f <= s.b) || SHOTS[SHOTS.length - 1];
const PX = -1.0, BX = 1.1, PTX = -0.66, BTX = 0.88;                              // characters and towers (world x)
const CAMS = {
  wide: [{ f: 0, pos: [0.05, 1.1, 3.0], look: [0.05, 0.78, 0.2], fov: 44 }, { f: 189, pos: [0.05, 1.08, 2.7], look: [0.05, 0.78, 0.2], fov: 41 }],
  perf: [{ f: 190, pos: [-0.75, 1.0, 2.1], look: [-0.78, 0.85, 0.2], fov: 32 }, { f: 289, pos: [-0.78, 1.0, 1.8], look: [-0.78, 0.85, 0.2], fov: 29 }],
  build: [{ f: 290, pos: [1.0, 1.0, 2.1], look: [1.0, 0.85, 0.2], fov: 32 }, { f: 389, pos: [1.0, 1.0, 1.8], look: [1.0, 0.85, 0.2], fov: 29 }],
  wide2: [{ f: 390, pos: [0.05, 1.1, 2.9], look: [0.05, 0.78, 0.2], fov: 44 }, { f: 479, pos: [0.1, 1.05, 2.6], look: [0.1, 0.8, 0.2], fov: 40 }],
  win: [{ f: 480, pos: [0.95, 1.05, 2.5], look: [1.0, 0.95, 0.2], fov: 38 }, { f: 569, pos: [0.95, 1.1, 2.2], look: [1.0, 1.0, 0.2], fov: 34 }],
  perf2: [{ f: 570, pos: [-0.75, 1.0, 2.0], look: [-0.78, 0.85, 0.2], fov: 31 }, { f: 649, pos: [-0.78, 1.0, 1.7], look: [-0.78, 0.88, 0.2], fov: 28 }],
  end: [{ f: 650, pos: [0.05, 1.12, 2.8], look: [0.05, 0.82, 0.2], fov: 42 }, { f: 719, pos: [0.05, 1.18, 3.3], look: [0.05, 0.82, 0.2], fov: 47 }],
};
export const camAt = (f) => camFromKeys(CAMS[shotAt(f).id], f, { creep: 0.0004 });
export const dofAt = (f) => { const C = camAt(f), l = C.look; const d = Math.hypot(C.pos[0] - l[0], C.pos[1] - l[1], C.pos[2] - l[2]); return { focus: d, cinf: 5, near: 1 }; };
const DAY = { az: 120, el: 44, sky: '#fff8ea', ground: '#d6b48a', hemi: 1.75, sun: '#fff0d6', sunI: 1.3, sat: 1.08, gain: '#fffaf2', vig: 0.18, shadowExt: 4.5, ink: 2.2 };
export const lightFor = () => DAY;

// ---------- helpers ----------
const keyOf = (who, o) => who + JSON.stringify(o, (k, v) => (typeof v === 'number' ? q(v, 3) : v));
const blinkAt = (f, seed) => { const per = 70 + (seed * 17) % 41, ph = (f + seed * 23) % per; return ph < 2 ? 0.5 : ph < 4 ? 1 : ph < 6 ? 0.4 : 0; };
const mk = (who, o, x, y, z, s) => ({ key: keyOf(who, o), draw: (p) => window.__T.stickFront(p, who, o), x, y, z, s });
const cyc = (f, period, f0 = 0) => (((f - f0) % period) + period) % period / period;
// where a shoulder is in the card (design units) for a measured master body
const shoulder = (who, sd) => { const B = window.__T.CAST[who].body; return [300 + sd * 26, B.hip - B.torso + 14]; };
// hand offset (from that shoulder) to reach a point given in world x and a tower top (design y)
const reach = (who, sd, worldDx, topY) => { const sh = shoulder(who, sd); return { hx: 300 + worldDx / U - sh[0], hy: topY - sh[1] }; };

// ---------- block towers ----------
const COLS = ['#e0463a', '#2f6fb5', '#f2b632', '#4f9a4a', '#8e4fb0', '#2f9aa0', '#e8803a', '#d94f8f'];
const towerDraw = (n, wob, done) => (pen) => {
  for (let k = 0; k < n; k++) {
    const cx = 300 + wob * Math.sin(k * 2.3 + 1) * 9, yb = 975 - k * BH;
    pen.poly([[cx - BW / 2, yb], [cx + BW / 2, yb], [cx + BW / 2, yb - BH], [cx - BW / 2, yb - BH]], COLS[k % COLS.length], 6);
    pen.stroke([[cx - BW * 0.35, yb - BH * 0.72], [cx + BW * 0.05, yb - BH * 0.72]], 3, 'rgba(255,255,255,.5)');
  }
  if (done) { const yt = 975 - n * BH; pen.stroke([[300, yt], [300, yt - 120]], 6, '#6b4a2e'); pen.poly([[300, yt - 120], [372, yt - 98], [300, yt - 76]], '#f2c14e', 5); }
};
const pileDraw = (n) => (pen) => { for (let k = 0; k < n; k++) { const col = k % 2, row = (k / 2) | 0, cx = 270 + col * 110, yb = 975 - row * BH; pen.poly([[cx - 52, yb], [cx + 52, yb], [cx + 52, yb - BH * 0.9], [cx - 52, yb - BH * 0.9]], COLS[(k + 3) % COLS.length], 6); } };

// block counts over time
const BT = Array.from({ length: BLOCKS }, (_, k) => 110 + 46 * k);              // Winifred places block k+1 at BT[k] (last at 432)
const PT = [210, 380, 560];                                                      // Mortimer places 3 blocks in the whole film
const countW = (f) => BT.filter((t) => f >= t + 10).length;
const countP = (f) => PT.filter((t) => f >= t + 10).length;

// ---------- actors ----------
function perfectionist(f) {
  const t = f / FPS, sh = shotAt(f).id, seed = 3, n = countP(f);
  const o = { blink: blinkAt(f, seed), headRoll: 1.0 * Math.sin(t * 1.3), bodyLean: 0.4 * Math.sin(t * 0.9), facing: 0.2 * Math.sin(t * 0.7), shadow: true };
  // measure the block on top of his tower: tape stretches out, holds, snaps back; before each placement he nudges it
  const per = 80, u = cyc(f, per), stretch = u < 0.3 ? M.smooth(u / 0.3) : u < 0.62 ? 1 : 1 - M.easeOut((u - 0.62) / 0.38);
  const Lm = lerp(40, 150, clamp(stretch)), topY = 975 - (n + 1) * BH;
  const sh0 = shoulder(PERF, -1), shR = shoulder(PERF, 1), cx0 = shR[0] + 85;
  o.arms = { R: { hx: 85, hy: topY - shR[1] + 10, prop: 'tape', a: Math.PI, len: Lm }, L: { hx: cx0 - Lm - 40 - sh0[0] - 22, hy: topY - sh0[1] + 10 } };
  // placing: right hand brings a block from his pile to the tower
  const nearPlace = PT.some((t0) => f >= t0 - 28 && f <= t0 + 12);
  if (nearPlace) { const t0 = PT.find((x) => f >= x - 28 && f <= x + 12), k = M.smooth(ramp(f, t0 - 28, t0)), rel = M.smooth(ramp(f, t0, t0 + 12));
    const from = reach(PERF, 1, -0.2, 975 - 60), to = reach(PERF, 1, PTX - PX, 975 - (n + (f < t0 + 10 ? 1 : 0)) * BH - BH * 0.5);
    o.arms = { L: o.arms.L, R: { hx: lerp(from.hx, to.hx, k), hy: lerp(from.hy, to.hy, k) - 40 * Math.sin(Math.PI * k), prop: f < t0 + 10 ? 'block' : undefined, a: 0, color: COLS[(n + 3) % COLS.length], size: 0.3 } }; }
  if (f >= SC[6]) o.headRoll = 3 * Math.sin(t * 2.5);
  const flip = sh === 'win' || sh === 'perf2';
  return mk(PERF, o, PX, 0, WZ, S);
}

function builder(f) {
  const t = f / FPS, sh = shotAt(f).id, seed = 5, n = countW(f);
  const o = { blink: blinkAt(f, seed), headRoll: 1.2 * Math.sin(t * 1.9), shadow: true, bodyLean: 0.6 * Math.sin(t * 2.1) };
  const per = 46, u = cyc(f, per, 110 - 46 * 0);                                   // one block per cycle, aligned to BT
  const done = f >= BT[BLOCKS - 1] + 10;
  if (f < 110) { o.arms = { L: { hx: -60, hy: 130 }, R: { hx: 60, hy: 130 } }; o.headRoll += 2 * Math.sin(t * 5); }
  else if (!done) {
    const topY = 975 - (n + 1) * BH + BH * 0.5, pile = reach(BUILD, 1, 0.3, 975 - 70), tower = reach(BUILD, 1, BTX - BX, topY);
    const up = u < 0.3 ? M.smooth(u / 0.3) : u < 0.78 ? 1 : 1;                       // 0 -> at the pile, then carrying to the tower
    const grab = u < 0.18 ? 0 : 1;                                                   // block appears once picked up
    const carry = M.smooth(ramp(u, 0.2, 0.78)), back = M.smooth(ramp(u, 0.78, 1.0));
    const hx = lerp(lerp(pile.hx, tower.hx, carry), pile.hx, back), hy = lerp(lerp(pile.hy, tower.hy, carry), pile.hy, back) - 45 * Math.sin(Math.PI * carry);
    o.arms = { L: { hx: -50, hy: 125 }, R: { hx, hy, prop: back > 0.1 ? undefined : grab ? 'block' : undefined, a: 0, color: COLS[n % COLS.length], size: 0.3 } };
    o.headDY = 4 * Math.sin(Math.PI * carry); o.facing = 0.2;
  } else {
    const k = M.smooth(ramp(f, BT[BLOCKS - 1] + 10, BT[BLOCKS - 1] + 40));
    o.arms = { L: { hx: lerp(-50, -150, k), hy: lerp(125, -210, k) }, R: { hx: lerp(60, 150, k), hy: lerp(125, -210, k) } };   // both arms up: she won
    o.headDY = -6 * Math.abs(Math.sin(t * 6)); o.headRoll = 4 * Math.sin(t * 5);
  }
  return mk(BUILD, o, BX, 0, WZ, S);
}

const tower = (who, f) => {
  const isB = who === 'b', n = isB ? countW(f) : countP(f), done = isB && f >= BT[BLOCKS - 1] + 10;
  return { key: who + 'T' + n + (done ? 'd' : ''), draw: towerDraw(n, isB ? 1 : 0, done), x: isB ? BTX : PTX, y: 0, z: WZ - 0.02, s: S };
};
const pile = (who, f) => { const left = who === 'b' ? Math.max(0, BLOCKS - countW(f)) : Math.max(0, 6 - countP(f)); return { key: who + 'P' + left, draw: pileDraw(Math.min(left, 8)), x: who === 'b' ? BX + 0.34 : PX - 0.32, y: 0, z: WZ + 0.05, s: S * 0.8 }; };
const confetti = (f) => {
  const k = f - 440; if (k < 0 || k > 170) return null; const fr = Math.floor(k / 2);
  return { key: 'cf' + fr, draw: (pen) => { for (let i = 0; i < 46; i++) { const x = (i * 97) % 560 + 20, y0 = -60 + ((i * 53) % 200), y = y0 + fr * (6 + (i % 5)) * 1.6, c = COLS[i % COLS.length]; if (y > 0 && y < 980) pen.poly([[x, y], [x + 22, y + 6], [x + 18, y + 24], [x - 4, y + 18]], c, 3); } }, x: 1.0, y: 0.2, z: WZ + 0.3, s: S * 1.5, shadow: false, order: 4 };
};
const banner = (f) => {
  if (f < 470 || f >= 650) return null; const k = M.back(ramp(f, 470, 490), 1.6);
  return { key: 'bn' + q(k, 2), draw: (pen) => { const g = pen.g; pen.poly([[40, 40], [560, 40], [560, 190], [40, 190]], '#f2c14e', 8); g.save(); g.fillStyle = '#7a2f14'; g.font = '800 86px Helvetica, Arial'; g.textAlign = 'center'; g.fillText('WINNER!', 300, 150); g.restore(); }, x: 1.0, y: 1.25, z: WZ - 0.3, s: S * 0.8 * k, shadow: false, order: 4 };
};

export const actorsAt = (f, T) => {
  window.__T = T;
  const out = [tower('p', f), tower('b', f), pile('p', f), pile('b', f), perfectionist(f), builder(f)];
  const cf = confetti(f); if (cf) out.push(cf);
  const bn = banner(f); if (bn) out.push(bn);
  return out;
};
