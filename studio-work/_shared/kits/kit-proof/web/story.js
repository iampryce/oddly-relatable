// Episode 15, shots 13 and 19, 25 fps. One timeline: frames 0-49 = shot 13 (33.9-35.9 s), frames 50-399 = shot 19 (51.8-65.8 s).
import { M, clamp, lerp, ramp, camFromKeys, q } from './motion.js';
import { LIPSYNC } from './lipsync.js';
export const FPS = 25, TOTAL = 400;
export const FAMX = [-1.6, -0.9, -0.2, 0.5, 1.2, 1.9], FAMZ = 2.9;
export const SHOTS = [{ id: 's13', a: 0, b: 49, t0: 33.9 }, { id: 's19', a: 50, b: 399, t0: 51.8 }];
export const shotAt = (f) => SHOTS.find((s) => f >= s.a && f <= s.b) || SHOTS[SHOTS.length - 1];

// card scale: design unit (1/1000 of the card) in metres
const S = 0.6, U = 2.25 * S / 1000;
const HEADY = 293; // head centre in design units (seated)
const worldY = (y0, Y) => y0 + (975 - Y) * U;

// ---------- light ----------
const STUDY = { az: 118, el: 38, sky: '#fff0d8', ground: '#5a3c26', hemi: 1.55, sun: '#ffe6c4', sunI: 1.25, sat: 1.06, gain: '#fff8ee', vig: 0.28, shadowExt: 3.5, ink: 2.2 };
export const lightFor = (Sh) => ({ ...STUDY, shadowExt: Sh.id === 's13' ? 2.5 : 3.5 });

// ---------- positions ----------
const MORT = { x: 0, y0: 0.42, z: -1.45 };
const SID = { x: FAMX[4], y0: 0.13, z: FAMZ - 0.03 };
const MHEAD = [MORT.x, worldY(MORT.y0, HEADY), MORT.z], SHEAD = [SID.x, worldY(SID.y0, HEADY), SID.z];

// ---------- cameras ----------
const CAMS = {
  s13: [
    { f: 0, pos: [0.36, 1.12, 1.42], look: [SHEAD[0] + 0.03, SHEAD[1] - 0.1, SHEAD[2]], fov: 31 },
    { f: 49, pos: [0.4, 1.12, 1.5], look: [SHEAD[0] + 0.03, SHEAD[1] - 0.09, SHEAD[2]], fov: 30 },
  ],
  s19: [
    { f: 50, pos: [0.0, 1.27, 2.1], look: [0, 1.18, -1.45], fov: 25 },
    { f: 399, pos: [0.03, 1.27, 1.85], look: [0.0, 1.19, -1.45], fov: 24.4 },
  ],
};
export const camAt = (f) => { const Sh = shotAt(f); return camFromKeys(CAMS[Sh.id], f, { creep: 0.0004, kicks: Sh.id === 's13' ? [{ f: 10, a: 0.0025 }] : [] }); };
export const dofAt = (f) => {
  const Sh = shotAt(f), C = camAt(f), tgt = Sh.id === 's13' ? SHEAD : MHEAD;
  const d = Math.hypot(C.pos[0] - tgt[0], C.pos[1] - tgt[1], C.pos[2] - tgt[2]);
  return Sh.id === 's13' ? { focus: d, cinf: 11, near: 1 } : { focus: d, cinf: 5, near: 1 };
};

// ---------- acting helpers ----------
const bump = (t, w = 0.28) => (t < 0 || t > w ? 0 : Math.sin(Math.PI * t / w));             // one smooth dip
const blinkAt = (t, list) => { for (const b of list) { const k = (t - b) * FPS; if (k >= 0 && k < 5) return [0.5, 1, 1, 0.6, 0.2][Math.floor(k)]; } return 0; };
const updown = (t, a, b, c, d, ea = M.smooth, ed = M.smooth) => (t < c ? ea(ramp(t, a, b)) : 1 - ed(ramp(t, c, d)));

// Smoothed lip-sync for a calm reading voice: the per-frame shapes are blended over +-2 frames, the opening is scaled down and the
// width barely changes, so the mouth size no longer jumps between small / wide every 2-4 frames.
const mouthSmooth = (T, key, i0, open = 0.7, wide = 0.35) => {
  const L = LIPSYNC[key], n = L.mouth.length; let w0 = 0, w1 = 0, w2 = 0, ws = 0;
  for (let k = -2; k <= 2; k++) {
    const i = Math.min(n - 1, Math.max(0, i0 + k)), w = 1 - Math.abs(k) / 3, nm = L.mouth[i] || 'closed', M = T.MOUTHS[nm] || T.MOUTHS.closed, am = nm === 'closed' ? 0 : (L.amp[i] || 1);
    w0 += w * M[0]; w1 += w * M[1] * am; w2 += w * M[2]; ws += w;
  }
  return [1 + wide * (w0 / ws - 1), (w1 / ws) * open, w2 / ws];
};
const keyOf = (who, o) => who + JSON.stringify(o, (k, v) => (typeof v === 'number' ? q(v, 3) : v));

// stressed syllables (shot-19 seconds) for head bobs
const STRESS19 = [1.45, 1.92, 3.05, 8.56, 9.0, 11.92, 13.45];

function mortimer(f) {
  const t = (f - 50) / FPS;
  const peer = updown(t, 2.4, 2.9, 5.75, 6.25, (x) => M.back(x, 1.2));                  // "when she survived": paper down, over the glasses
  const glance = updown(t, 11.0, 11.5, 12.95, 13.35, (x) => M.back(x, 1.0));             // "her uncle Sidney still owes me": knowing glance right
  const lift = updown(t, 9.62, 9.95, 10.45, 10.8);                                       // eyes flick up through the second laugh
  let E = 'reading';
  const o = {};
  o.expr = 'reading';
  // expression mix: reading -> stern (peer) ; reading -> smirk (glance) ; stern finality at the end
  const fin = M.smooth(ramp(t, 13.1, 13.5));
  if (peer > 0.001) { o.exprB = 'stern'; o.exprT = clamp(peer); }
  else if (glance > 0.001) { o.exprB = 'smirk'; o.exprT = clamp(glance); }
  else if (fin > 0) { o.exprB = 'stern'; o.exprT = fin * 0.55; }
  const shakeT = t - 13.0, shake = shakeT > 0 && shakeT < 0.75 ? Math.sin(shakeT * Math.PI * 2 / 0.34) * Math.exp(-shakeT * 3.2) : 0;
  let stress = 0; for (const s of STRESS19) stress += bump(t - s + 0.04, 0.3);
  const idleT = Math.sin(t * 2 * Math.PI / 3.6);
  o.look = [lerp(lerp(0.0, 0.0, peer), 0.85, glance) + shake * 0.1, lerp(lerp(0.85 - lift * 0.9, -0.85, peer), -0.15, glance)];
  o.pitch = lerp(lerp(0.55, 0.95, peer), 0.25, glance) + stress * 0.12 + Math.max(0, fin - glance) * 0.15;
  o.facing = 0.32 * glance + shake * 0.13 + 0.03 * Math.sin(t * 0.9);
  o.headRoll = 1.2 * Math.sin(t * 0.7 + 1) + peer * -2.5 + glance * 3.5 + shake * 4;
  o.headDY = stress * 5 + peer * 6; o.glassesDrop = 0.06 * peer;
  o.bodyLean = 0.6 * idleT + peer * -0.8;
  o.pose = 'read'; o.paperY = 0.5 * peer + 0.03 * Math.sin(t * 1.3); o.paperTilt = 1.2 * Math.sin(t * 0.8) - peer * 3;
  o.blink = blinkAt(t, [0.9, 3.45, 6.0, 7.75, 10.2, 11.02, 12.35]);
  o.mouthM = mouthSmooth(window.__T, 's19', f - 50); o.talkAmp = 1;
  o.seated = true; o.squash = 0.012 * (1 + idleT);
  return { key: keyOf('mortimer', o), draw: (p) => window.__T.stickFront(p, 'mortimer', o), x: MORT.x, y: MORT.y0 + 0.004 * idleT, z: MORT.z, s: S };
}

function sidney(f) {
  const t = f / FPS, o = { seated: true };
  // 0-0.3 skeptical | 0.3-0.4 anticipation | 0.4-0.7 snap into shock (overshoot) | 0.7-1.2 hold, tremble, blink | 1.2-1.6 turn into the glare | huff at 1.7
  const ant = bump(t - 0.28, 0.14);
  const snap = M.back(ramp(t, 0.38, 0.6), 2.2);
  const settle = M.spring(Math.max(0, t - 0.6), 3.2, 6);
  const toGlare = M.smooth(ramp(t, 1.18, 1.6));
  const shockAmt = clamp(snap) * (1 - toGlare);
  o.expr = 'skeptical';
  if (t >= 0.36) { o.expr = 'shocked'; if (toGlare > 0) { o.exprB = 'indignant'; o.exprT = toGlare; } }
  else if (ant > 0) { o.exprB = 'indignant'; o.exprT = ant * 0.5; }               // squint on the wind-up
  const recoil = (t < 0.38 ? 0 : snap) * (1 - toGlare * 0.75);
  const trem = (t > 0.62 && t < 1.3) ? Math.sin(t * 95) * (1 - toGlare) : 0;
  const huff = bump(t - 1.66, 0.22);
  o.headDY = 9 * ant - 26 * recoil + 6 * huff + (1 - settle) * 0;
  o.headDX = 1.8 * trem - 4 * recoil;
  o.squash = 0.1 * ant - 0.04 * recoil + 0.06 * huff;
  o.bodyLean = -3.5 * recoil + 1.5 * toGlare;
  o.headRoll = 2 * Math.sin(t * 1.4) - 5 * recoil + trem * 0.8 - 4 * toGlare;
  o.look = [lerp(t < 0.36 ? -0.55 : 0, -0.85, toGlare), lerp(0.05, 0.02, toGlare)];
  o.facing = lerp(-0.18 * (1 - recoil), -0.22, toGlare);
  o.pitch = -0.25 * recoil + 0.15 * huff + 0.08 * toGlare;
  o.pose = 'lap'; if (t >= 0.38) { o.poseB = toGlare > 0 ? 'cross' : 'recoil'; o.poseT = toGlare > 0 ? toGlare : clamp(snap); if (toGlare > 0) o.pose = 'recoil'; }
  o.blink = blinkAt(t, [1.0]);
  o.mouth = huff > 0.3 ? 'small' : 'closed'; o.talkAmp = 0.7;
  return { key: keyOf('sidney', o), draw: (p) => window.__T.stickFront(p, 'sidney', o), x: SID.x, y: SID.y0, z: SID.z, s: S };
}

const standIn = (who, x, f, seed, look) => {
  const t = f / FPS, o = { seated: true, expr: who === 'ronald' ? 'neutral' : 'reading', look, pose: 'lap', blink: blinkAt(t, [0.5 + seed * 0.4]), headRoll: 1.5 * Math.sin(t * 1.1 + seed), facing: -0.15 };
  if (who === 'winifred') { o.expr = 'shocked'; o.exprB = 'neutral'; o.exprT = 0.6; }
  return { key: keyOf(who, o), draw: (p) => window.__T.stickFront(p, who, o), x, y: SID.y0 + 0.004 * Math.sin(t * 1.7 + seed), z: FAMZ - 0.03, s: S };
};

export const actorsAt = (f, T) => {
  window.__T = T;
  const Sh = shotAt(f);
  if (Sh.id === 's13') return [sidney(f), standIn('winifred', FAMX[3], f, 1, [-0.6, 0]), standIn('ronald', FAMX[5], f, 2, [-0.8, 0])];
  return [mortimer(f)];
};
