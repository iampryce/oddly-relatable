// Procedural character animator (prototype, owner request 2026-11-17).
//
// Every frame is DRAWN, not composited from fixed poses: the approved head, clothing and shoes (cut from the approved
// artwork by rig_extract.py) are reused exactly, while limbs, mouths, pupils and eyelids are drawn live:
//   - limbs: two-bone inverse kinematics, drawn as one smooth curve through the elbow/knee (bendy stick limbs)
//   - feet: planted in world space while walking (no sliding); knees bend to keep them there
//   - mouth: Rhubarb viseme cues (A-H, X) from the real Piper audio; X shows the character's own painted mouth
//   - eyes: pupils drawn live (glances, tracking the speaker), eyelid blinks
//   - body: breathing, lean, squash/stretch, anticipation and overshoot (easeOutBack) on big moves
// Separate from the production engine (production/lib): nothing there changes until this is approved.
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(HERE, '../../skills/directing-stickman-videos/package.json'));
const {createCanvas, loadImage, GlobalFonts} = require('@napi-rs/canvas');

// ---------------------------------------------------------------- maths
export const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
export const lerp = (a, b, u) => a + (b - a) * u;
const lerpP = (a, b, u) => ({x: lerp(a.x, b.x, u), y: lerp(a.y, b.y, u)});
export const ease = {
  linear: u => u,
  inOut: u => u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2,
  out: u => 1 - Math.pow(1 - u, 3),
  in: u => u * u * u,
  back: u => { const c1 = 1.9, c3 = c1 + 1; return 1 + c3 * Math.pow(u - 1, 3) + c1 * Math.pow(u - 1, 2); },   // overshoot
};
const rot = (p, a) => ({x: p.x * Math.cos(a) - p.y * Math.sin(a), y: p.x * Math.sin(a) + p.y * Math.cos(a)});
const add = (a, b) => ({x: a.x + b.x, y: a.y + b.y});
const sub = (a, b) => ({x: a.x - b.x, y: a.y - b.y});

// Envelope of an action active on [t0, t1]: eases in (overshooting when `pop`) and out.
export function envelope(t, t0, t1, inDur = 0.28, outDur = 0.32, pop = true) {
  if (t <= t0 || t >= t1) return 0;
  const i = clamp((t - t0) / inDur), o = clamp((t1 - t) / outDur);
  return Math.min(pop ? ease.back(i) : ease.inOut(i), ease.inOut(o));
}

// Two-bone IK: joint position for root a, target t, bone lengths l1/l2; `prefer` picks the bend side (a direction the
// joint should point towards). Targets out of reach are pulled in (the limb straightens).
function ik(a, t, l1, l2, prefer) {
  let d = sub(t, a), dist = Math.hypot(d.x, d.y);
  const max = l1 + l2 - 0.01, min = Math.abs(l1 - l2) + 0.01;
  if (dist > max) { t = add(a, {x: d.x / dist * max, y: d.y / dist * max}); d = sub(t, a); dist = max; }
  if (dist < min) dist = min;
  const A = Math.acos(clamp((l1 * l1 + dist * dist - l2 * l2) / (2 * l1 * dist), -1, 1));
  const base = Math.atan2(d.y, d.x);
  const j1 = add(a, {x: l1 * Math.cos(base + A), y: l1 * Math.sin(base + A)});
  const j2 = add(a, {x: l1 * Math.cos(base - A), y: l1 * Math.sin(base - A)});
  const score = j => (j.x - a.x) * prefer.x + (j.y - a.y) * prefer.y;
  return {joint: score(j1) >= score(j2) ? j1 : j2, end: t};
}

// ---------------------------------------------------------------- rigs
const VISEME_OPEN = {X: 0, A: 0, B: 0.25, C: 0.55, D: 0.85, E: 0.5, F: 0.35, G: 0.2, H: 0.5};

export async function loadRig(dir, figureHeight, opts = {}) {
  const rig = JSON.parse(fs.readFileSync(path.join(dir, 'rig.json'), 'utf8'));
  const b = rig.body, f = rig.faces.neutral;
  const img = async name => loadImage(path.join(dir, name));
  const H0 = {x: (b.hip_l[0] + b.hip_r[0]) / 2, y: b.hip_y};
  const P = v => ({x: v[0] - H0.x, y: v[1] - H0.y});
  const legLen = Math.hypot(b.ankle_l[0] - b.hip_l[0], b.ankle_l[1] - b.hip_l[1]);
  const armLen = Math.hypot(b.hand_l[0] - b.shoulder_l[0], b.hand_l[1] - b.shoulder_l[1]);
  const c = {
    name: opts.name, rig, S: figureHeight / b.height, lw: b.line_width,
    head: await img(f.file), mouthRest: await img(f.mouth_file), torso: await img(rig.parts.torso.file),
    shoeL: await img(rig.parts.shoe_l.file), shoeR: await img(rig.parts.shoe_r.file),
    neck: P(b.neck), shoulderL: P(b.shoulder_l), shoulderR: P(b.shoulder_r), hipL: P(b.hip_l), hipR: P(b.hip_r),
    ankleL: P(b.ankle_l), ankleR: P(b.ankle_r), handL: P(b.hand_l), handR: P(b.hand_r),
    footDrop: b.bottom - H0.y,                       // hip to sole, source px
    thigh: legLen / 2 * 1.004, shin: legLen / 2 * 1.004, upper: armLen / 2 * 1.04, fore: armLen / 2 * 1.04, armLen, legLen,
    faces: {},
    lips: opts.lips ? `rgb(${f.mouth.color.join(',')})` : '#111',
    torsoOff: {x: rig.parts.torso.origin[0] - H0.x, y: rig.parts.torso.origin[1] - H0.y},
    shoeLOff: {x: rig.parts.shoe_l.origin[0] - b.ankle_l[0], y: rig.parts.shoe_l.origin[1] - b.ankle_l[1]},
    shoeROff: {x: rig.parts.shoe_r.origin[0] - b.ankle_r[0], y: rig.parts.shoe_r.origin[1] - b.ankle_r[1]},
    state: {look: {x: 0, y: 0}},
  };
  // One head per approved expression (rig_extract --head-only), each positioned from its own neck point so it
  // swaps onto the body's neck. Lips colour, when the character has coloured lips, comes from each face.
  for (const [name, fc] of Object.entries(rig.faces)) {
    const n = fc.neck;
    c.faces[name] = {
      head: await img(fc.file), mouthRest: await img(fc.mouth_file),
      headOff: {x: fc.origin[0] - n[0], y: fc.origin[1] - n[1]},
      mouthRestOff: {x: fc.mouth_origin[0] - n[0], y: fc.mouth_origin[1] - n[1]},
      mouth: {x: fc.mouth.cx - n[0], y: fc.mouth.cy - n[1], w: fc.mouth.w, h: fc.mouth.h},
      eyes: fc.eyes.map(e => ({x: e.cx - n[0], y: e.cy - n[1], w: e.w, h: e.h, px: e.pupil.cx - n[0], py: e.pupil.cy - n[1], r: e.pupil.r})),
      skin: `rgb(${fc.skin.join(',')})`,
      lips: opts.lips ? `rgb(${fc.mouth.color.join(',')})` : '#111',
      static_eyes: !!fc.static_eyes,   // expression faces keep their drawn eyes (the expression lives in them)
      style: fc.style || rig.style || 'v1',   // v2: solid black eyes, thin-line mouth (house style v2)
      curve: (fc.mouth && fc.mouth.curve) || 0,   // v2: the expression's mouth bend, kept while speaking
    };
  }
  Object.assign(c, c.faces.neutral);   // the neutral face is the default
  return c;
}

// Standing hip height above the floor, in world px.
export const hipHeight = c => c.footDrop * c.S;

// ---------------------------------------------------------------- drawing
function limb(ctx, a, j, e, lw) {
  // one smooth curve through the joint: control point so the quadratic passes through j at its middle
  const ctl = {x: 2 * j.x - (a.x + e.x) / 2, y: 2 * j.y - (a.y + e.y) / 2};
  ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.quadraticCurveTo(ctl.x, ctl.y, e.x, e.y);
  ctx.lineWidth = lw; ctx.strokeStyle = '#121212'; ctx.lineCap = 'round'; ctx.stroke();
}

function hand(ctx, j, e, lw, kind) {
  const ang = Math.atan2(e.y - j.y, e.x - j.x);
  ctx.save(); ctx.translate(e.x, e.y); ctx.rotate(ang);
  ctx.fillStyle = '#121212';
  if (kind === 'point') {
    ctx.beginPath(); ctx.ellipse(lw * 0.6, 0, lw * 1.15, lw * 0.95, 0, 0, Math.PI * 2); ctx.fill();
    ctx.beginPath(); ctx.moveTo(lw * 1.2, 0); ctx.lineTo(lw * 3.1, 0); ctx.lineWidth = lw * 0.62; ctx.lineCap = 'round'; ctx.strokeStyle = '#121212'; ctx.stroke();
  } else if (kind === 'thumb') {
    ctx.beginPath(); ctx.ellipse(lw * 0.6, 0, lw * 1.25, lw * 1.05, 0, 0, Math.PI * 2); ctx.fill();
    ctx.rotate(-ang); ctx.beginPath(); ctx.moveTo(0, -lw * 0.6); ctx.lineTo(0, -lw * 2.2); ctx.lineWidth = lw * 0.7; ctx.lineCap = 'round'; ctx.strokeStyle = '#121212'; ctx.stroke();
  } else {
    ctx.beginPath(); ctx.ellipse(lw * 0.75, 0, lw * 1.45, lw * 1.2, 0, 0, Math.PI * 2); ctx.fill();
  }
  ctx.restore();
}

// House style v2 (overlay lip sync, owner decision 2026-11-20): Rhubarb shapes drawn as solid black ink in the line
// style, sized to the face's own mouth; closed shapes keep the expression's bend (smile or frown); no teeth or tongue.
function mouthShapeV2(ctx, c, v, lw) {
  const m = c.mouth, mw = Math.max(m.w, 40);
  if (v === 'X') { ctx.drawImage(c.mouthRest, c.mouthRestOff.x, c.mouthRestOff.y); return; }
  const ink = '#121212', bend = clamp(c.curve || 0, -0.3, 0.3);
  ctx.save(); ctx.translate(m.x, m.y);
  const line = (w, wid, dy = 0) => { ctx.beginPath(); ctx.moveTo(-w / 2, dy); ctx.quadraticCurveTo(0, dy + 2 * bend * w, w / 2, dy); ctx.lineWidth = wid; ctx.lineCap = 'round'; ctx.strokeStyle = ink; ctx.stroke(); };
  const oval = (w, h) => { ctx.beginPath(); ctx.ellipse(0, h / 2 - lw * 0.3, w / 2, h / 2, 0, 0, Math.PI * 2); ctx.fillStyle = ink; ctx.fill(); };
  switch (v) {
    case 'A': line(mw * 0.9, lw * 0.7); break;                        // M B P: closed
    case 'G': line(mw * 0.8, lw * 0.7, lw * 0.25); break;             // F V: closed, lower lip tucked
    case 'B': oval(mw * 0.8, Math.max(lw * 0.9, mw * 0.14)); break;   // most consonants: a narrow slit
    case 'C': oval(mw * 0.6, mw * 0.32); break;                       // EH: small open
    case 'E': oval(mw * 0.5, mw * 0.36); break;                       // AO ER: rounded
    case 'H': oval(mw * 0.55, mw * 0.3); break;                       // L
    case 'D': oval(mw * 0.72, mw * 0.55); break;                      // AA: wide open
    case 'F': oval(mw * 0.3, mw * 0.32); break;                       // OO W: small round O
    default: oval(mw * 0.6, mw * 0.32);
  }
  ctx.restore();
}

function mouthShape(ctx, c, v, lw) {
  if (c.style === 'v2') return mouthShapeV2(ctx, c, v, lw);
  const m = c.mouth, mw = Math.max(m.w, 70);
  if (v === 'X') { ctx.drawImage(c.mouthRest, c.mouthRestOff.x, c.mouthRestOff.y); return; }
  ctx.save(); ctx.translate(m.x, m.y + (VISEME_OPEN[v] || 0) * mw * 0.12);
  const line = (w, wid = lw * 0.62) => { ctx.beginPath(); ctx.moveTo(-w / 2, 0); ctx.quadraticCurveTo(0, w * 0.08, w / 2, 0); ctx.lineWidth = wid; ctx.lineCap = 'round'; ctx.strokeStyle = c.lips; ctx.stroke(); };
  const sizes = {B: [0.62, 0.2], C: [0.62, 0.42], D: [0.7, 0.62], E: [0.46, 0.46], F: [0.3, 0.32], G: [0.56, 0.17], H: [0.56, 0.4]};
  if (v === 'A') { line(mw * 0.55, lw * 0.75); ctx.restore(); return; }
  const [sw, sh] = sizes[v] || sizes.C;
  const w = mw * sw, h = mw * sh;
  ctx.beginPath(); ctx.ellipse(0, 0, w / 2, h / 2, 0, 0, Math.PI * 2);
  ctx.fillStyle = '#4b1518'; ctx.fill();
  ctx.save(); ctx.clip();
  if (['B', 'C', 'D', 'G'].includes(v)) { ctx.fillStyle = '#fbf8f2'; ctx.fillRect(-w / 2, -h / 2, w, h * (v === 'D' ? 0.24 : 0.36)); }
  if (['C', 'D', 'H'].includes(v)) { ctx.fillStyle = '#e06c78'; ctx.beginPath(); ctx.ellipse(0, h * (v === 'H' ? 0.05 : 0.38), w * 0.3, h * 0.32, 0, 0, Math.PI * 2); ctx.fill(); }
  ctx.restore();
  ctx.lineWidth = c.lips === '#111' ? lw * 0.55 : lw * 0.85; ctx.strokeStyle = c.lips; ctx.stroke();
  ctx.restore();
}

function drawHead(ctx, c0, p) {
  const c = {...c0, ...(c0.faces[p.expression] || c0.faces.neutral)};
  ctx.drawImage(c.head, c.headOff.x, c.headOff.y);
  const lw = c.lw;
  if (c.style === 'v2' && p.blink > 0.5) {
    // v2 blink: the solid black eye closes to a short heavy line
    for (const e of c.eyes) {
      ctx.fillStyle = c.skin; ctx.beginPath(); ctx.ellipse(e.x, e.y, e.w / 2 + 3, e.h / 2 + 3, 0, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.moveTo(e.x - e.w * 0.75, e.y + e.h * 0.1); ctx.lineTo(e.x + e.w * 0.75, e.y + e.h * 0.1);
      ctx.lineWidth = lw * 0.6; ctx.lineCap = 'round'; ctx.strokeStyle = '#121212'; ctx.stroke();
    }
  }
  for (const e of c.static_eyes ? [] : c.eyes) {
    // pupil: live, constrained inside the eye white
    const maxX = e.w / 2 - e.r - 8, maxY = e.h / 2 - e.r - 8;
    const px = e.x + clamp(p.look.x, -1, 1) * maxX, py = e.y + clamp(p.look.y, -1, 1) * maxY + (e.py - e.y) * 0.3;
    ctx.fillStyle = '#121212'; ctx.beginPath(); ctx.arc(px, py, e.r * (p.pupilScale || 1), 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = 'rgba(255,255,255,0.9)'; ctx.beginPath(); ctx.arc(px - e.r * 0.3, py - e.r * 0.35, e.r * 0.28, 0, Math.PI * 2); ctx.fill();
    if (p.blink > 0.02) {
      // eyelid: skin closes from the top; its edge is a dark line
      ctx.save(); ctx.beginPath(); ctx.ellipse(e.x, e.y, e.w / 2 - 2, e.h / 2 - 2, 0, 0, Math.PI * 2); ctx.clip();
      const edge = e.y - e.h / 2 + e.h * p.blink;
      ctx.fillStyle = c.skin; ctx.fillRect(e.x - e.w / 2, e.y - e.h / 2 - 4, e.w, e.h * p.blink + 4);
      ctx.beginPath(); ctx.moveTo(e.x - e.w / 2, edge); ctx.quadraticCurveTo(e.x, edge + e.h * 0.12 * (p.blink > 0.9 ? 1 : 0), e.x + e.w / 2, edge);
      ctx.lineWidth = lw * 0.55; ctx.strokeStyle = '#121212'; ctx.stroke(); ctx.restore();
    }
  }
  mouthShape(ctx, c, p.viseme || 'X', lw);
}

// Draw one character. Pose (world px unless noted):
//   hip {x,y}; lean (rad); squash (y scale, x = 1/sqrt); breath; headTilt; headNod (src px); headScale;
//   look {x,y} -1..1; blink 0..1; viseme; shoulderLift (src px);
//   handL/handR: target relative to the shoulder (src px, body frame); handKindL/R: 'mitten'|'point'|'thumb';
//   footL/footR: WORLD targets of the ankles; kneeDir {x,y} preferred knee direction.
export function drawCharacter(ctx, c, p) {
  const S = c.S, sq = p.squash || 1, sx = 1 / Math.sqrt(sq);
  ctx.save();
  ctx.translate(p.hip.x, p.hip.y); ctx.scale(S * sx, S * sq);
  const lw = c.lw;
  // legs (world foot targets -> local)
  const toLocal = w => ({x: (w.x - p.hip.x) / (S * sx), y: (w.y - p.hip.y) / (S * sq)});
  const legs = [[c.hipL, p.footL, c.shoeL, c.shoeLOff, -1], [c.hipR, p.footR, c.shoeR, c.shoeROff, 1]];
  for (const [hip, footW, shoe, off, side] of legs) {
    const t = toLocal(footW);
    const pref = p.kneeDir || {x: side * 0.8, y: -0.2};
    const {joint, end} = ik(hip, t, c.thigh, c.shin, pref);
    limb(ctx, hip, joint, end, lw);
    ctx.drawImage(shoe, end.x + off.x, end.y + off.y);
  }
  // torso (lean about the hip, breathing)
  const lean = p.lean || 0, br = 1 + (p.breath || 0);
  // turn (0..1): the body narrows as it turns towards walking direction p.turnDir, so a frontal design reads as
  // walking sideways; the head leads slightly in that direction
  const tz = 1 - 0.2 * (p.turn || 0), td = (p.turnDir || 0) * (p.turn || 0);
  const body = q => rot({x: q.x * tz, y: q.y * br}, lean);
  ctx.save(); ctx.rotate(lean); ctx.scale(tz, br); ctx.drawImage(c.torso, c.torsoOff.x, c.torsoOff.y); ctx.restore();
  // head
  const neck = body(c.neck);
  ctx.save(); ctx.translate(neck.x + td * 22, neck.y + (p.headNod || 0)); ctx.rotate(lean + (p.headTilt || 0));
  const hs = p.headScale || 1; ctx.scale(hs * (1 - 0.1 * (p.turn || 0)) / Math.sqrt(p.headStretch || 1), hs * (p.headStretch || 1));
  drawHead(ctx, c, p);
  ctx.restore();
  // arms (on top: gestures cross the body and reach the face)
  const arms = [[c.shoulderL, p.handL, p.handKindL, -1], [c.shoulderR, p.handR, p.handKindR, 1]];
  for (const [sh0, target, kind, side] of arms) {
    const sh = body({x: sh0.x, y: sh0.y - (p.shoulderLift || 0)});
    const tgt = add(sh, rot(target, lean));
    // elbows point outward and slightly down
    const {joint, end} = ik(sh, tgt, c.upper, c.fore, {x: side, y: 0.35});
    limb(ctx, sh, joint, end, lw);
    hand(ctx, joint, end, lw, kind);
  }
  ctx.restore();
}

// ---------------------------------------------------------------- audio
export function readWav(file) {
  const b = fs.readFileSync(file);
  let o = 12, fmt, data;
  while (o < b.length) {
    const id = b.toString('ascii', o, o + 4), size = b.readUInt32LE(o + 4);
    if (id === 'fmt ') fmt = {channels: b.readUInt16LE(o + 10), rate: b.readUInt32LE(o + 12), bits: b.readUInt16LE(o + 22)};
    if (id === 'data') data = b.subarray(o + 8, o + 8 + size);
    o += 8 + size + (size % 2);
  }
  if (!fmt || fmt.bits !== 16 || fmt.channels !== 1) throw new Error(`${file}: expected 16-bit mono WAV`);
  const s = new Float32Array(data.length / 2);
  for (let i = 0; i < s.length; i++) s[i] = data.readInt16LE(i * 2) / 32768;
  return {rate: fmt.rate, samples: s, seconds: s.length / fmt.rate};
}

export function mixWav(clips, seconds, out) {
  const rate = clips[0].wav.rate, n = Math.ceil(seconds * rate), mix = new Float32Array(n);
  for (const {wav, start} of clips) {
    if (wav.rate !== rate) throw new Error('all clips must share one sample rate');
    const o = Math.round(start * rate);
    for (let i = 0; i < wav.samples.length && o + i < n; i++) mix[o + i] += wav.samples[i];
  }
  const buf = Buffer.alloc(44 + n * 2);
  buf.write('RIFF', 0); buf.writeUInt32LE(36 + n * 2, 4); buf.write('WAVEfmt ', 8); buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22); buf.writeUInt32LE(rate, 24); buf.writeUInt32LE(rate * 2, 28);
  buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34); buf.write('data', 36); buf.writeUInt32LE(n * 2, 40);
  for (let i = 0; i < n; i++) buf.writeInt16LE(Math.round(clamp(mix[i], -1, 1) * 32767), 44 + i * 2);
  fs.writeFileSync(out, buf);
}

// ---------------------------------------------------------------- render loop
export async function renderVideo({width = 1080, height = 1920, fps = 30, seconds, drawFrame, audio, out, ffmpeg = 'ffmpeg', font,
  stills = null}) {
  if (font) GlobalFonts.registerFromPath(font, 'Sub');
  const canvas = createCanvas(width, height), ctx = canvas.getContext('2d');
  if (stills) {
    // stills mode (storyboard): the frames are drawn in order exactly as for the video (the renderer keeps state from
    // frame to frame: camera, scene, actions), up to the last still; only the frames at the given times are saved as
    // PNG files in `out` (a folder). No video is encoded and no audio is used.
    fs.mkdirSync(out, {recursive: true});
    const want = stills.map(t => Math.max(0, Math.min(Math.round(seconds * fps) - 1, Math.round(t * fps))));
    const last = Math.max(...want), files = [];
    for (let i = 0; i <= last; i++) {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      drawFrame(ctx, i / fps, {width, height});
      want.forEach((f, k) => {
        if (f === i) {
          const file = path.join(out, `still-${String(k + 1).padStart(2, '0')}.png`);
          fs.writeFileSync(file, canvas.toBuffer('image/png'));
          files[k] = {file, t: Math.round(i / fps * 1000) / 1000};
        }
      });
    }
    return {frames: last + 1, stills: files};
  }
  const args = ['-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', `${width}x${height}`, '-r', String(fps), '-i', '-',
    ...(audio ? ['-i', audio] : []), '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
    ...(audio ? ['-c:a', 'aac', '-b:a', '192k', '-shortest'] : []), '-movflags', '+faststart', out];
  const ff = spawn(ffmpeg, args, {stdio: ['pipe', 'inherit', 'inherit']});
  const done = new Promise((res, rej) => ff.on('close', code => code === 0 ? res() : rej(new Error(`ffmpeg exited ${code}`))));
  const frames = Math.round(seconds * fps), times = [];
  for (let i = 0; i < frames; i++) {
    const t = i / fps;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    drawFrame(ctx, t, {width, height});
    const px = ctx.getImageData(0, 0, width, height).data;
    if (!ff.stdin.write(Buffer.from(px.buffer, px.byteOffset, px.byteLength))) await new Promise(r => ff.stdin.once('drain', r));
    times.push(t);
  }
  ff.stdin.end();
  await done;
  return {frames};
}

export {createCanvas, loadImage, lerpP};
