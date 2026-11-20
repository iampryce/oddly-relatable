// Characters drawn from a spec (prototype, owner decision 2026-11-20: "B: drawn from spec"). No image model: a small
// JSON spec (proportions, line weight, hair or headwear shape, garment, face parameters per expression) is drawn into
// the same rig format rig_extract.py produces (rig.json + head/mouth/torso/feet images), so the real acting renderer
// (render-acting.mjs, animator.mjs) animates it unchanged: limbs, blob hands, overlay lip sync and blinks are drawn live.
// Everything is drawn at high resolution (figure 1600 px), so close-ups stay sharp.
//
//   node production/animation/spec_rig.mjs <spec.json> <out_dir>
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(HERE, '../../skills/directing-stickman-videos/package.json'));
const {createCanvas} = require('@napi-rs/canvas');

const FIG = 1600;                    // source figure height (px), feet to top of head
const INK = '#121212';

// ---------------------------------------------------------------- expressions (house defaults; a spec may override)
// brow: angle in degrees (positive = inner ends down: cross), raise (fraction of head height, + = up), tilt (one brow up)
// eyes: open (height scale), size (scale), squint (flatten top), look (x offset, fraction of eye spacing)
// mouth: type line|o|d, curve (+ smile, - frown), width (scale), offset (x, fraction of head width)
export const EXPRESSIONS = {
  neutral:  {brow: {angle: 4, raise: 0}, eyes: {open: 1}, mouth: {type: 'line', curve: 0, width: 1}},
  deadpan:  {brow: {angle: 0, raise: -0.012}, eyes: {open: 0.62, squint: 0.35}, mouth: {type: 'line', curve: -0.02, width: 0.85, offset: 0.03}},
  annoyed:  {brow: {angle: 24, raise: -0.02}, eyes: {open: 0.8, squint: 0.25}, mouth: {type: 'line', curve: -0.16, width: 0.95}},
  shocked:  {brow: {angle: -18, raise: 0.05}, eyes: {open: 1.25, size: 1.12}, mouth: {type: 'o', width: 0.62, height: 0.55}},
  laughing: {brow: {angle: -10, raise: 0.035}, eyes: {open: 0.35, squint: 0.7, smile: true}, mouth: {type: 'd', width: 1.25, height: 0.62}},
  worried:  {brow: {angle: -26, raise: 0.02}, eyes: {open: 0.95, look: -0.12}, mouth: {type: 'line', curve: -0.1, width: 0.8, wobble: true}},
};

// ---------------------------------------------------------------- geometry from the spec
export function layout(spec) {
  const p = {head: 0.30, head_aspect: 1.06, torso: 0.30, shoulder: 0.15, hip: 0.105, ...(spec.proportions || {})};
  const lw = Math.round((spec.line?.weight ?? 0.0125) * FIG);
  const W = 1100, top = 120, cx = W / 2;
  const headH = p.head * FIG, headW = headH / p.head_aspect;
  const head = {cx, cy: top + headH / 2, rx: headW / 2, ry: headH / 2};
  const neckY = top + headH + 0.012 * FIG;                  // where the head image is cut and swapped
  const torsoTop = top + headH + 0.03 * FIG, torsoH = p.torso * FIG, hipY = torsoTop + torsoH;
  const bottom = top + FIG, ankleY = bottom - 0.02 * FIG;
  const sh = p.shoulder * FIG, hp = p.hip * FIG;
  const shoulderY = torsoTop + 0.035 * FIG;
  return {spec, p, lw, W, H: bottom + 80, top, bottom, cx, head, headH, headW, neckY, torsoTop, torsoH, hipY, ankleY, sh, hp,
    shoulderL: [cx - sh + lw * 0.6, shoulderY], shoulderR: [cx + sh - lw * 0.6, shoulderY],
    handL: [cx - sh - 0.02 * FIG, hipY + 0.12 * FIG], handR: [cx + sh + 0.02 * FIG, hipY + 0.12 * FIG],
    hipL: [cx - hp * 0.55, hipY], hipR: [cx + hp * 0.55, hipY],
    ankleL: [cx - hp * 0.7, ankleY], ankleR: [cx + hp * 0.7, ankleY]};
}

function rounded(ctx, pts, r) {
  ctx.beginPath();
  for (let i = 0; i < pts.length; i++) {
    const [x0, y0] = pts[(i - 1 + pts.length) % pts.length], [x1, y1] = pts[i], [x2, y2] = pts[(i + 1) % pts.length];
    const a = Math.hypot(x1 - x0, y1 - y0), b = Math.hypot(x2 - x1, y2 - y1), k = Math.min(r, a / 2, b / 2);
    const s = [x1 - (x1 - x0) / a * k, y1 - (y1 - y0) / a * k], e = [x1 + (x2 - x1) / b * k, y1 + (y2 - y1) / b * k];
    if (i === 0) ctx.moveTo(...s); else ctx.lineTo(...s);
    ctx.quadraticCurveTo(x1, y1, ...e);
  }
  ctx.closePath();
}

// ---------------------------------------------------------------- hair and headwear (shape library)
// Each shape draws behind and/or in front of the head; colours from the spec. Shapes stay above the eyes.
const HAIR = {
  short_crop(ctx, h, col, lw, front) {        // a short crop: a cap following the hairline, one swept tuft
    if (!front) return;
    const a = [h.cx - h.rx * 1.02, h.cy - h.ry * 0.28], c = [h.cx, h.cy - h.ry * 0.56], b = [h.cx + h.rx * 1.02, h.cy - h.ry * 0.34];
    ctx.save(); ctx.beginPath(); ctx.ellipse(h.cx, h.cy, h.rx, h.ry, 0, 0, Math.PI * 2); ctx.clip();
    ctx.beginPath(); ctx.moveTo(...a); ctx.quadraticCurveTo(...c, ...b); ctx.lineTo(h.cx + h.rx * 1.2, h.cy - h.ry * 1.2);
    ctx.lineTo(h.cx - h.rx * 1.2, h.cy - h.ry * 1.2); ctx.closePath(); ctx.fillStyle = col; ctx.fill(); ctx.restore();
    ctx.beginPath(); ctx.moveTo(...a); ctx.quadraticCurveTo(...c, ...b); ctx.lineWidth = lw * 0.8; ctx.strokeStyle = INK; ctx.stroke();
    // swept tuft above the crown
    ctx.beginPath(); ctx.moveTo(h.cx - h.rx * 0.25, h.cy - h.ry * 0.97);
    ctx.quadraticCurveTo(h.cx + h.rx * 0.05, h.cy - h.ry * 1.22, h.cx + h.rx * 0.32, h.cy - h.ry * 1.12);
    ctx.quadraticCurveTo(h.cx + h.rx * 0.1, h.cy - h.ry * 1.06, h.cx + h.rx * 0.12, h.cy - h.ry * 0.96);
    ctx.closePath(); ctx.fillStyle = col; ctx.fill(); ctx.lineWidth = lw * 0.7; ctx.stroke();
  },
  high_bun(ctx, h, col, lw, front) {          // smooth hair cap with a side part and a high bun
    if (!front) {
      ctx.beginPath(); ctx.ellipse(h.cx + h.rx * 0.12, h.cy - h.ry * 1.18, h.rx * 0.36, h.ry * 0.26, 0.15, 0, Math.PI * 2);
      ctx.fillStyle = col; ctx.fill(); ctx.lineWidth = lw; ctx.strokeStyle = INK; ctx.stroke();
      return;
    }
    ctx.save(); ctx.beginPath(); ctx.ellipse(h.cx, h.cy, h.rx, h.ry, 0, 0, Math.PI * 2); ctx.clip();
    ctx.beginPath(); ctx.moveTo(h.cx - h.rx * 1.1, h.cy - h.ry * 0.2); ctx.lineTo(h.cx - h.rx * 1.1, h.cy - h.ry * 1.1);
    ctx.lineTo(h.cx + h.rx * 1.1, h.cy - h.ry * 1.1); ctx.lineTo(h.cx + h.rx * 1.1, h.cy - h.ry * 0.1);
    ctx.quadraticCurveTo(h.cx + h.rx * 0.35, h.cy - h.ry * 0.62, h.cx - h.rx * 0.18, h.cy - h.ry * 0.52);
    ctx.quadraticCurveTo(h.cx - h.rx * 0.75, h.cy - h.ry * 0.46, h.cx - h.rx * 1.1, h.cy - h.ry * 0.2);
    ctx.fillStyle = col; ctx.fill(); ctx.restore();
    ctx.beginPath(); ctx.moveTo(h.cx - h.rx * 0.97, h.cy - h.ry * 0.24); ctx.quadraticCurveTo(h.cx - h.rx * 0.6, h.cy - h.ry * 0.5, h.cx - h.rx * 0.18, h.cy - h.ry * 0.52);
    ctx.quadraticCurveTo(h.cx + h.rx * 0.35, h.cy - h.ry * 0.62, h.cx + h.rx * 0.99, h.cy - h.ry * 0.12);
    ctx.lineWidth = lw * 0.8; ctx.strokeStyle = INK; ctx.stroke();
    ctx.beginPath(); ctx.moveTo(h.cx - h.rx * 0.18, h.cy - h.ry * 0.53); ctx.lineTo(h.cx - h.rx * 0.08, h.cy - h.ry * 0.98); ctx.lineWidth = lw * 0.5; ctx.stroke();
  },
  bald_tufts(ctx, h, col, lw, front) {        // bald crown, two side tufts
    if (!front) return;
    for (const s of [-1, 1]) {
      ctx.beginPath();
      const x = h.cx + s * h.rx * 0.97, y = h.cy - h.ry * 0.08;
      ctx.moveTo(x, y - h.ry * 0.3);
      ctx.quadraticCurveTo(x + s * h.rx * 0.2, y - h.ry * 0.12, x + s * h.rx * 0.08, y + h.ry * 0.08);
      ctx.quadraticCurveTo(x + s * h.rx * 0.18, y + h.ry * 0.12, x - s * h.rx * 0.02, y + h.ry * 0.2);
      ctx.quadraticCurveTo(x - s * h.rx * 0.1, y - h.ry * 0.05, x, y - h.ry * 0.3);
      ctx.fillStyle = col; ctx.fill(); ctx.lineWidth = lw * 0.8; ctx.strokeStyle = INK; ctx.stroke();
    }
  },
};

// ---------------------------------------------------------------- face parts
function faceGeom(L) {
  const f = {eye_w: 0.095, eye_h: 0.2, spacing: 0.36, eye_y: 0.53, brow_w: 0.21, brow_y: 0.4, brow_weight: 2.1,
             mouth_w: 0.2, mouth_y: 0.76, ...(L.spec.face || {})};
  const h = L.head, hw = L.headW, hh = L.headH;
  return {f, h, hw, hh,
    eyeL: {x: h.cx - f.spacing * hw / 2, y: h.cy - hh / 2 + f.eye_y * hh}, eyeR: {x: h.cx + f.spacing * hw / 2, y: h.cy - hh / 2 + f.eye_y * hh},
    browY: h.cy - hh / 2 + f.brow_y * hh, mouth: {x: h.cx, y: h.cy - hh / 2 + f.mouth_y * hh, w: f.mouth_w * hw}};
}

function expr(spec, name) {
  const base = EXPRESSIONS[name] || EXPRESSIONS.neutral, own = (spec.expressions || {})[name] || {};
  return {brow: {...base.brow, ...(own.brow || {})}, eyes: {...base.eyes, ...(own.eyes || {})}, mouth: {...base.mouth, ...(own.mouth || {})}};
}

function drawEyes(ctx, G, e, lw) {
  const w = G.f.eye_w * G.hw * (e.size || 1), h = G.f.eye_h * G.hh * (e.size || 1);
  const out = [];
  for (const c of [G.eyeL, G.eyeR]) {
    const x = c.x + (e.look || 0) * G.f.spacing * G.hw, eh = h * (e.open ?? 1);
    if (e.smile) {                              // laughing: closed, upturned arcs
      ctx.beginPath(); ctx.moveTo(x - w * 0.75, c.y + eh * 0.2); ctx.quadraticCurveTo(x, c.y - h * 0.45, x + w * 0.75, c.y + eh * 0.2);
      ctx.lineWidth = lw * 0.9; ctx.lineCap = 'round'; ctx.strokeStyle = INK; ctx.stroke();
    } else {
      ctx.save(); ctx.beginPath(); ctx.ellipse(x, c.y, w / 2, eh / 2, 0, 0, Math.PI * 2); ctx.clip();
      // a heavy lid flattens the top of the eye: fill only below the lid line
      ctx.fillStyle = INK; ctx.fillRect(x - w, c.y - eh / 2 + eh * (e.squint || 0), 2 * w, eh * 2); ctx.restore();
    }
    out.push({cx: x, cy: c.y, w, h: Math.max(eh, lw)});
  }
  return out;
}

function drawBrows(ctx, G, b, lw) {
  const len = G.f.brow_w * G.hw, thick = lw * G.f.brow_weight, y = G.browY - (b.raise || 0) * G.hh;
  for (const [c, s] of [[G.eyeL, -1], [G.eyeR, 1]]) {
    const ang = (b.angle || 0) * Math.PI / 180 * -s + ((b.tilt && s === 1) ? -0.25 : 0);
    ctx.save(); ctx.translate(c.x, y + ((b.tilt && s === 1) ? -0.03 * G.hh : 0)); ctx.rotate(ang);
    // a heavy wedge: thicker at the outer end
    ctx.beginPath(); ctx.moveTo(-len / 2, -thick * (s < 0 ? 0.62 : 0.4)); ctx.lineTo(len / 2, -thick * (s < 0 ? 0.4 : 0.62));
    ctx.lineTo(len / 2, thick * (s < 0 ? 0.4 : 0.62)); ctx.lineTo(-len / 2, thick * (s < 0 ? 0.62 : 0.4)); ctx.closePath();
    ctx.fillStyle = INK; ctx.fill(); ctx.restore();
  }
}

// The resting mouth for an expression, drawn on its own (it becomes mouth-<name>.png; the head image has no mouth).
function drawMouth(ctx, G, m, lw, ox, oy) {
  const w = G.mouth.w * (m.width || 1), x = G.mouth.x + (m.offset || 0) * G.hw - ox, y = G.mouth.y - oy;
  ctx.fillStyle = INK; ctx.strokeStyle = INK; ctx.lineCap = 'round';
  if (m.type === 'o') { ctx.beginPath(); ctx.ellipse(x, y, w / 2, w * (m.height || 0.55) / 2 * 1.4, 0, 0, Math.PI * 2); ctx.fill(); return; }
  if (m.type === 'd') { ctx.beginPath(); ctx.moveTo(x - w / 2, y - w * 0.08); ctx.quadraticCurveTo(x, y - w * 0.02, x + w / 2, y - w * 0.08);
    ctx.quadraticCurveTo(x + w * 0.2, y + w * (m.height || 0.6), x, y + w * (m.height || 0.6)); ctx.quadraticCurveTo(x - w * 0.2, y + w * (m.height || 0.6), x - w / 2, y - w * 0.08); ctx.fill(); return; }
  ctx.beginPath(); ctx.moveTo(x - w / 2, y);
  if (m.wobble) { ctx.bezierCurveTo(x - w / 6, y - w * 0.12, x + w / 6, y + w * 0.12 - (m.curve || 0) * w, x + w / 2, y); }
  else ctx.quadraticCurveTo(x, y - 2 * (m.curve || 0) * w * -1, x + w / 2, y);
  ctx.lineWidth = lw * 0.62; ctx.stroke();
}

function headCanvas(L, name) {
  const pad = 40, h = L.head, G = faceGeom(L), e = expr(L.spec, name);
  const x0 = Math.floor(h.cx - h.rx * 1.45 - pad), y0 = Math.floor(h.cy - h.ry * 1.55 - pad);
  const w = Math.ceil(h.rx * 2.9 + 2 * pad), hgt = Math.ceil(L.neckY - y0 + 4);
  const cv = createCanvas(w, hgt), ctx = cv.getContext('2d');
  ctx.translate(-x0, -y0);
  const hair = HAIR[L.spec.hair?.shape] || (() => {});
  hair(ctx, h, L.spec.hair?.color || '#2a2a2a', L.lw, false);       // back layer (bun)
  ctx.beginPath(); ctx.ellipse(h.cx, h.cy, h.rx, h.ry, 0, 0, Math.PI * 2);
  ctx.fillStyle = L.spec.skin || '#ffffff'; ctx.fill(); ctx.lineWidth = L.lw; ctx.strokeStyle = INK; ctx.stroke();
  hair(ctx, h, L.spec.hair?.color || '#2a2a2a', L.lw, true);        // front layer
  const eyes = drawEyes(ctx, G, e.eyes, L.lw);
  drawBrows(ctx, G, e.brow, L.lw);
  // the mouth on its own image
  const m = e.mouth, mw = G.mouth.w * (m.width || 1), mx0 = Math.floor(G.mouth.x + (m.offset || 0) * G.hw - mw / 2 - 20), my0 = Math.floor(G.mouth.y - mw * 0.5 - 20);
  const mcv = createCanvas(Math.ceil(mw + 40), Math.ceil(mw * 1.3 + 40)), mctx = mcv.getContext('2d');
  drawMouth(mctx, G, m, L.lw, mx0, my0);
  const curve = m.type === 'line' ? Math.max(-0.3, Math.min(0.3, (m.curve || 0))) : 0;
  const skin = hexRgb(L.spec.skin || '#ffffff');
  return {cv, mcv, origin: [x0, y0], mouth_origin: [mx0, my0],
    face: {eyes: eyes.map(q => ({cx: q.cx, cy: q.cy, w: q.w, h: q.h, pupil: {cx: q.cx, cy: q.cy, r: Math.max(q.w, q.h) / 2}})),
      mouth: {x0: G.mouth.x - mw / 2, x1: G.mouth.x + mw / 2, y0: G.mouth.y - L.lw, y1: G.mouth.y + L.lw, cx: G.mouth.x + (m.offset || 0) * G.hw,
              cy: G.mouth.y, w: Math.max(mw, 60), h: L.lw * 2, color: [18, 18, 18], curve},
      skin, style: 'v2'}};
}

function hexRgb(h) { const n = parseInt(h.replace('#', ''), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }

// ---------------------------------------------------------------- torso (with an optional plain adult garment)
const GARMENT = {
  none() {},
  polo(ctx, pts, L, col) {
    rounded(ctx, pts, 30); ctx.fillStyle = col; ctx.fill();
    const c = L.cx, t = L.torsoTop;
    for (const s of [-1, 1]) { ctx.beginPath(); ctx.moveTo(c, t + 8); ctx.lineTo(c + s * 70, t + 6); ctx.lineTo(c + s * 52, t + 70); ctx.closePath();
      ctx.fillStyle = col; ctx.fill(); ctx.lineWidth = L.lw * 0.7; ctx.strokeStyle = INK; ctx.stroke(); }
    ctx.beginPath(); ctx.moveTo(c, t + 10); ctx.lineTo(c, t + 120); ctx.lineWidth = L.lw * 0.5; ctx.stroke();
  },
  blazer(ctx, pts, L, col) {
    const c = L.cx, t = L.torsoTop, b = L.hipY;
    ctx.save(); rounded(ctx, pts, 30); ctx.clip();
    ctx.fillStyle = col; ctx.fillRect(L.cx - L.sh - 20, t - 10, 2 * L.sh + 40, L.torsoH + 40);
    ctx.fillStyle = '#ffffff'; ctx.beginPath(); ctx.moveTo(c - 46, t - 5); ctx.lineTo(c + 46, t - 5); ctx.lineTo(c + 8, b - 30); ctx.lineTo(c - 8, b - 30); ctx.closePath(); ctx.fill();
    ctx.restore();
    for (const s of [-1, 1]) { ctx.beginPath(); ctx.moveTo(c + s * 46, t); ctx.lineTo(c + s * 8, b - 30); ctx.lineWidth = L.lw * 0.7; ctx.strokeStyle = INK; ctx.stroke(); }
  },
  cardigan(ctx, pts, L, col) {
    const c = L.cx, t = L.torsoTop, b = L.hipY;
    ctx.save(); rounded(ctx, pts, 30); ctx.clip();
    ctx.fillStyle = col; ctx.fillRect(L.cx - L.sh - 20, t - 10, 2 * L.sh + 40, L.torsoH + 40);
    ctx.fillStyle = '#ffffff'; ctx.beginPath(); ctx.moveTo(c - 34, t - 5); ctx.lineTo(c + 34, t - 5); ctx.lineTo(c, t + 140); ctx.closePath(); ctx.fill();
    ctx.restore();
    ctx.beginPath(); ctx.moveTo(c - 34, t); ctx.lineTo(c, t + 140); ctx.lineTo(c + 34, t); ctx.moveTo(c, t + 140); ctx.lineTo(c, b - 6);
    ctx.lineWidth = L.lw * 0.6; ctx.strokeStyle = INK; ctx.stroke();
    for (let k = 0; k < 3; k++) { ctx.beginPath(); ctx.arc(c + 16, t + 190 + k * 80, 7, 0, Math.PI * 2); ctx.fillStyle = INK; ctx.fill(); }
  },
};

function torsoCanvas(L) {
  const x0 = Math.floor(L.cx - L.sh - 40), y0 = Math.floor(L.neckY - 6), w = Math.ceil(2 * L.sh + 80), h = Math.ceil(L.hipY + 30 - y0);
  const cv = createCanvas(w, h), ctx = cv.getContext('2d');
  ctx.translate(-x0, -y0);
  ctx.beginPath(); ctx.moveTo(L.cx, L.neckY - 4); ctx.lineTo(L.cx, L.torsoTop + 10); ctx.lineWidth = L.lw; ctx.strokeStyle = INK; ctx.stroke();   // neck
  const pts = [[L.cx - L.sh, L.torsoTop], [L.cx + L.sh, L.torsoTop], [L.cx + L.hp, L.hipY], [L.cx - L.hp, L.hipY]];
  rounded(ctx, pts, 30); ctx.fillStyle = (L.spec.torso?.fill) || L.spec.skin || '#ffffff'; ctx.fill();
  const g = L.spec.torso?.garment;
  if (g && GARMENT[g.type]) GARMENT[g.type](ctx, pts, L, g.color || '#555');
  rounded(ctx, pts, 30); ctx.lineWidth = L.lw; ctx.strokeStyle = INK; ctx.stroke();
  return {cv, origin: [x0, y0]};
}

function footCanvas(L, side) {
  const fw = 0.085 * FIG, fh = 0.026 * FIG, cv = createCanvas(Math.ceil(fw + 20), Math.ceil(fh + 20)), ctx = cv.getContext('2d');
  ctx.beginPath(); ctx.ellipse(10 + fw / 2, 10 + fh / 2, fw / 2, fh / 2, 0, 0, Math.PI * 2); ctx.fillStyle = INK; ctx.fill();
  const a = side === 'l' ? L.ankleL : L.ankleR;
  // the foot points outwards a little; the ankle sits on its inner half
  const ox = side === 'l' ? a[0] - fw * 0.62 - 10 : a[0] - fw * 0.38 - 10;
  return {cv, origin: [Math.round(ox), Math.round(a[1] - 10 - fh * 0.35)]};
}

// ---------------------------------------------------------------- rig
export function buildRig(spec, out) {
  fs.mkdirSync(out, {recursive: true});
  const L = layout(spec);
  const png = (cv, name) => fs.writeFileSync(path.join(out, name), cv.toBuffer('image/png'));
  const faces = {};
  for (const name of Object.keys({...EXPRESSIONS, ...(spec.expressions || {})})) {
    const hc = headCanvas(L, name);
    png(hc.cv, `head-${name}.png`); png(hc.mcv, `mouth-${name}.png`);
    faces[name] = {...hc.face, file: `head-${name}.png`, origin: hc.origin, size: [hc.cv.width, hc.cv.height],
                   mouth_file: `mouth-${name}.png`, mouth_origin: hc.mouth_origin, neck: [L.cx, L.neckY], static_eyes: true};
  }
  const t = torsoCanvas(L); png(t.cv, 'torso.png');
  const fl = footCanvas(L, 'l'), fr = footCanvas(L, 'r'); png(fl.cv, 'shoe-l.png'); png(fr.cv, 'shoe-r.png');
  const body = {top: L.top, bottom: L.bottom, height: L.bottom - L.top, neck: [L.cx, L.neckY], arm_split_y: Math.round(L.torsoTop + 40),
    line_width: L.lw, shoulder_l: L.shoulderL, shoulder_r: L.shoulderR, hand_l: L.handL, hand_r: L.handR, hip_y: L.hipY,
    hip_l: L.hipL, hip_r: L.hipR, ankle_l: L.ankleL, ankle_r: L.ankleR};
  const rig = {source: `spec:${spec.id}`, style: 'v2', image_size: [L.W, L.H], body,
    parts: {torso: {file: 'torso.png', origin: t.origin, size: [t.cv.width, t.cv.height]},
            shoe_l: {file: 'shoe-l.png', origin: fl.origin, size: [fl.cv.width, fl.cv.height]},
            shoe_r: {file: 'shoe-r.png', origin: fr.origin, size: [fr.cv.width, fr.cv.height]}},
    faces};
  fs.writeFileSync(path.join(out, 'rig.json'), JSON.stringify(rig, null, 1));
  return rig;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const [specFile, out] = process.argv.slice(2);
  const rig = buildRig(JSON.parse(fs.readFileSync(specFile, 'utf8')), out);
  console.log(JSON.stringify({source: rig.source, faces: Object.keys(rig.faces), line_width: rig.body.line_width, height: rig.body.height}));
}
