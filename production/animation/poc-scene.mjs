// Animation proof of concept: Leo, Ben and Maya in the approved living-room set, real Piper voices + Rhubarb lip sync.
//   node poc-scene.mjs <work dir>   (work dir holds rigs/<name>/, audio/<line>.wav|json, and receives poc.mp4)
// Beats: Leo talks with gestures; Ben reacts (head scratch, shrug); Leo's exaggerated "You did WHAT?" jump; Leo walks
// to the armchair and drops into it (facepalm); Maya walks in (planted footsteps); Maya explains with gestures; Leo
// celebrates from the chair; Ben gives a thumbs-up. Full bodies stay in frame throughout.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {loadRig, drawCharacter, renderVideo, readWav, mixWav, loadImage, envelope, ease, clamp, lerp, hipHeight} from './animator.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../..');
const WORK = path.resolve(process.argv[2]);
const FPS = 30;

// ---------------------------------------------------------------- set (world = plate pixels)
const PLATE = path.join(ROOT, 'bible/concepts/lookdev-richenv/lookdev-room-empty-03.png');
const FLOOR = 1335;                       // standing feet line on the rug
const SEAT = {x: 300, y: 1112};           // armchair cushion (hip when seated)
const SEAT_FEET_Y = 1252;                 // floor just in front of the armchair

// ---------------------------------------------------------------- dialogue (real Piper audio, Rhubarb visemes)
const LINES = [
  {id: 'l1-leo', who: 'leo', at: 0.8, text: 'Okay. Nobody panic. The party is in the other room, and he does not suspect a thing.'},
  {id: 'l2-ben', who: 'ben', at: 7.15, text: 'Uh... about that. I may have sent him the invite.'},
  {id: 'l3-leo', who: 'leo', at: 9.95, text: 'You did WHAT?'},
  {id: 'l4-maya', who: 'maya', at: 15.0, text: 'Relax. I sent him a fake one. He thinks he is going to the dentist.'},
  {id: 'l5-leo', who: 'leo', at: 21.75, text: 'Maya. You are a genius.'},
];
for (const l of LINES) {
  l.wav = readWav(path.join(WORK, 'audio', `${l.id}.wav`));
  l.end = l.at + l.wav.seconds;
  l.cues = JSON.parse(fs.readFileSync(path.join(WORK, 'audio', `${l.id}.json`), 'utf8')).mouthCues;
}
const DURATION = LINES.at(-1).end + 1.1;

function viseme(who, t) {
  for (const l of LINES) if (l.who === who && t >= l.at && t < l.end) {
    const u = t - l.at, c = l.cues.find(c => u >= c.start && u < c.end);
    return c ? c.value : 'X';
  }
  return 'X';
}
const speaking = (who, t) => LINES.some(l => l.who === who && t >= l.at + 0.05 && t < l.end - 0.05);
const speakerAt = t => (LINES.find(l => t >= l.at && t < l.end + 0.4) || {}).who;

// ---------------------------------------------------------------- characters
const C = {
  leo: await loadRig(path.join(WORK, 'rigs/leo'), 560, {name: 'leo'}),
  ben: await loadRig(path.join(WORK, 'rigs/ben'), 575, {name: 'ben'}),
  maya: await loadRig(path.join(WORK, 'rigs/maya'), 545, {name: 'maya', lips: true}),
};

// Hand targets relative to the shoulder (source px, body frame); L = screen-left arm, R = screen-right arm.
// Each gesture is a function of (character, local time u in seconds) so it can move while held.
const G = {
  rest: (c, side) => side < 0 ? {x: c.handL.x - c.shoulderL.x, y: c.handL.y - c.shoulderL.y}
                             : {x: c.handR.x - c.shoulderR.x, y: c.handR.y - c.shoulderR.y},
  openPalms: (c, side, u) => ({x: side * c.armLen * 0.62, y: c.armLen * 0.38 + Math.sin(u * 7) * 6}),
  pointSide: (c, side) => ({x: side * c.armLen * 0.95, y: -c.armLen * 0.12}),
  pointAt: dir => (c, side) => ({x: dir * c.armLen * 0.93, y: -c.armLen * 0.18}),
  shrug: (c, side) => ({x: side * c.armLen * 0.62, y: -c.armLen * 0.12}),
  armsUp: (c, side, u) => ({x: side * c.armLen * 0.38, y: -c.armLen * 0.92 + Math.sin(u * 16) * 10}),
  headScratch: (c, side, u) => ({x: -side * c.armLen * 0.02 + (side < 0 ? -1 : 1) * 40, y: -c.armLen * 0.86 + Math.sin(u * 22) * 14}),
  hip: (c, side) => ({x: side * c.armLen * 0.46, y: c.armLen * 0.62}),
  chest: (c, side) => ({x: -side * c.armLen * 0.45, y: c.armLen * 0.32}),
  face: (c, side) => ({x: -side * c.armLen * 0.5, y: -c.armLen * 0.55}),
  thumbsUp: (c, side) => ({x: side * c.armLen * 0.35, y: c.armLen * 0.05}),
  beat: (c, side, u) => ({x: side * c.armLen * 0.25 - side * 30, y: c.armLen * 0.48 - Math.sin(u * 9) * 18}),
  knees: (c, side) => ({x: side * c.armLen * 0.25, y: c.armLen * 0.72}),
};

// Choreography: per character, timed arm gestures [arm, gesture, t0, t1, handKind?] and body actions.
const ACT = {
  leo: {
    arms: [
      ['both', 'openPalms', 1.0, 2.6], ['R', 'pointAt', 3.7, 5.0, 'point', -1], ['L', 'beat', 5.4, 6.6],
      ['both', 'armsUp', 9.85, 11.1], ['R', 'face', 13.0, 16.3], ['L', 'knees', 12.4, 21.6],
      ['both', 'armsUp', 21.8, 23.9],
    ],
  },
  ben: {
    arms: [['R', 'headScratch', 5.3, 7.4], ['both', 'shrug', 8.05, 9.6], ['L', 'beat', 7.3, 8.0],
           ['R', 'pointAt', 16.4, 17.4, 'point', 1], ['R', 'thumbsUp', 22.3, 24.4, 'thumb']],
  },
  maya: {
    arms: [['both', 'hip', 15.1, 16.9], ['L', 'chest', 17.2, 18.4], ['R', 'openPalms', 18.6, 19.9],
           ['both', 'shrug', 20.1, 21.3]],
  },
};

// ---------------------------------------------------------------- locomotion
// Walk with planted feet: n steps from x0 to x1 over [t0, t1]; returns hip x, bob and world foot positions.
function walk(c, x0, x1, t0, t1, t, floorY) {
  const dir = Math.sign(x1 - x0), steps = Math.max(2, Math.round(Math.abs(x1 - x0) / (c.legLen * c.S * 0.55)));
  const stride = (x1 - x0) / steps;
  const u = clamp((t - t0) / (t1 - t0)) * steps, k = Math.min(steps - 1, Math.floor(u)), f = u - k;
  const hipOff = {L: c.hipL.x * c.S, R: c.hipR.x * c.S};
  const mover = (k % 2 === 0) === (dir > 0) ? 'R' : 'L';
  // simple model: before step k, each foot has advanced to the last stride index it reached
  let posL = 0, posR = 0;
  for (let i = 0; i < k; i++) { if ((i % 2 === 0) === (dir > 0)) posR = i + 1; else posL = i + 1; }
  const swingFrom = mover === 'R' ? posR : posL, swingTo = k + 1;
  const sf = ease.inOut(f);
  const cur = lerp(swingFrom, swingTo, sf);
  if (mover === 'R') posR = cur; else posL = cur;
  if (t >= t1) { posL = posR = steps; }
  const lift = Math.sin(Math.PI * f) * c.legLen * c.S * 0.14 * (t < t1 ? 1 : 0);
  const bodyU = (posL + posR) / 2;
  return {
    hipX: x0 + stride * bodyU, bob: -Math.abs(Math.sin(Math.PI * f)) * 9 * (t < t1 && t > t0 ? 1 : 0),
    footL: {x: x0 + stride * posL + hipOff.L * 0.6, y: floorY - (mover === 'L' ? lift : 0)},
    footR: {x: x0 + stride * posR + hipOff.R * 0.6, y: floorY - (mover === 'R' ? lift : 0)},
    swing: Math.sin(Math.PI * u) * dir, moving: t > t0 && t < t1, dir,
  };
}

// ---------------------------------------------------------------- blinks (deterministic)
function blinkAmount(name, t) {
  let seed = [...name].reduce((a, ch) => a * 31 + ch.charCodeAt(0), 7) % 997, tt = 0.7 + (seed % 10) / 10;
  while (tt < t + 1) {
    const d = t - tt;
    if (d >= 0 && d < 0.17) return d < 0.06 ? d / 0.06 : d < 0.09 ? 1 : 1 - (d - 0.09) / 0.08;
    seed = (seed * 73 + 41) % 997; tt += 2.4 + (seed % 20) / 10;
  }
  return 0;
}

// ---------------------------------------------------------------- per-character pose
const POS = {leo: 395, ben: 625, maya: 800};
const lastLook = {leo: {x: 0, y: 0}, ben: {x: 0, y: 0}, maya: {x: 0, y: 0}};

function armTargets(name, c, t, p) {
  for (const side of [-1, 1]) {
    const key = side < 0 ? 'L' : 'R';
    let target = G.rest(c, side), kind = 'mitten';
    // idle: arms hang with a slight sway; while speaking, small automatic beat motions
    target = {x: target.x + Math.sin(t * 1.7 + side) * 5, y: target.y};
    for (const [arm, g, t0, t1, k, arg] of ACT[name].arms) {
      if (!(arm === 'both' || arm === key)) continue;
      const e = envelope(t, t0, t1, 0.26, 0.3, true);
      if (e <= 0) continue;
      const fn = g === 'pointAt' ? G.pointAt(arg) : G[g];
      const gt = fn(c, side, t - t0);
      target = {x: lerp(target.x, gt.x, e), y: lerp(target.y, gt.y, e)};
      if (e > 0.5 && k) kind = k;
    }
    p[`hand${key}`] = target; p[`handKind${key}`] = kind;
  }
}

function poseFor(name, t) {
  const c = C[name], p = {lean: 0, breath: Math.sin(t * 2.1 + name.length) * 0.008, squash: 1, headTilt: 0, headNod: 0};
  let x = POS[name], floor = FLOOR, hipY = FLOOR - hipHeight(c), feet = null, kneeDir = null, seated = 0;

  if (name === 'maya') {
    // enters from the right (off screen), planted footsteps, settles with a small overshoot
    const w = walk(c, 1010, POS.maya, 11.9, 14.6, t, FLOOR);
    x = w.hipX; hipY += w.bob; feet = {L: w.footL, R: w.footR};
    if (w.moving) { p.lean = -0.06; p.headTilt = Math.sin(t * 9) * 0.03; }
    if (t > 14.6 && t < 15.0) p.squash = 1 - Math.sin((t - 14.6) / 0.4 * Math.PI) * 0.04;
  }
  if (name === 'leo') {
    // "You did WHAT?": anticipation dip, jump with stretch, squash on landing
    if (t > 9.7 && t < 10.9) {
      const u = (t - 9.7) / 1.2;
      const lift = u < 0.12 ? -u / 0.12 * 22 : u < 0.62 ? Math.sin((u - 0.12) / 0.5 * Math.PI) * 95 : 0;
      hipY -= lift;
      p.squash = u < 0.12 ? 1 - u / 0.12 * 0.08 : u < 0.35 ? 1.07 : u > 0.62 && u < 0.8 ? 1 - Math.sin((u - 0.62) / 0.18 * Math.PI) * 0.09 : 1;
      p.headStretch = u > 0.12 && u < 0.6 ? 1.12 : 1;
      p.pupilScale = 0.6;
      if (lift > 0) feet = {L: {x: x + c.hipL.x * c.S * 0.75, y: FLOOR - lift * 0.85}, R: {x: x + c.hipR.x * c.S * 0.75, y: FLOOR - lift * 0.85}};
    }
    // walk to the armchair, turn, drop into it
    if (t >= 11.2 && t < 12.3) {
      const w = walk(c, POS.leo, SEAT.x + 40, 11.2, 12.3, t, FLOOR);
      x = w.hipX; hipY += w.bob; feet = {L: w.footL, R: w.footR}; p.lean = 0.05; p.headTilt = -0.06;
    }
    if (t >= 12.3) {
      const u = clamp((t - 12.3) / 0.55), down = ease.back(u);
      const standHip = {x: SEAT.x + 40, y: FLOOR - hipHeight(c)};
      x = lerp(standHip.x, SEAT.x, ease.inOut(u));
      hipY = lerp(standHip.y, SEAT.y, down);
      feet = {L: {x: SEAT.x - 40, y: lerp(FLOOR, SEAT_FEET_Y, ease.inOut(u))}, R: {x: SEAT.x + 40, y: lerp(FLOOR, SEAT_FEET_Y, ease.inOut(u))}};
      kneeDir = {x: 0, y: -1};
      seated = 1;
      if (u < 1) p.lean = Math.sin(u * Math.PI) * 0.18;
      if (t > 12.85 && t < 13.2) p.squash = 1 - Math.sin((t - 12.85) / 0.35 * Math.PI) * 0.07;
      // slump with the facepalm, perk up when Maya explains, bounce when celebrating
      const slump = envelope(t, 12.9, 16.4, 0.4, 0.5, false);
      p.lean += slump * 0.12; p.headNod = slump * 18; p.headTilt = slump * 0.12;
      if (t > 21.8 && t < 23.9) { hipY -= Math.abs(Math.sin((t - 21.8) * 7)) * 14; p.squash = 1 + Math.sin((t - 21.8) * 14) * 0.03; }
    }
  }
  if (name === 'ben') {
    // leans back from Leo's outburst, reaction tilts
    p.lean += envelope(t, 9.9, 11.0, 0.12, 0.5, true) * 0.16;
    p.headTilt += envelope(t, 5.3, 7.4, 0.3, 0.3, false) * -0.12 + envelope(t, 8.05, 9.6) * 0.14;
    p.shoulderLift = envelope(t, 8.05, 9.6) * 26;
  }
  if (name === 'maya') p.headTilt += envelope(t, 20.1, 21.3) * -0.13;

  // talking: head bobs with the openness of the mouth, gentle sway
  if (speaking(name, t)) {
    const v = viseme(name, t), open = {X: 0, A: 0, B: 0.3, C: 0.6, D: 1, E: 0.6, F: 0.4, G: 0.25, H: 0.5}[v] || 0;
    p.headNod += -open * 6; p.headTilt += Math.sin(t * 3.1) * 0.05;
  }
  p.viseme = viseme(name, t);
  p.blink = Math.max(blinkAmount(name, t), name === 'leo' && t > 9.7 && t < 9.78 ? 1 : 0);

  // eyes: look at whoever is speaking (or at the walker), quick saccade-like settling
  const target = name === 'ben' && t > 11.8 && t < 15.0 ? 'maya' : speakerAt(t) && speakerAt(t) !== name ? speakerAt(t) : null;
  let look = {x: 0, y: 0.1};
  if (target) look = {x: clamp((POS[target] - x) / 160, -1, 1), y: 0.05};
  if (name === 'ben' && t > 5.3 && t < 7.2) look = {x: -0.9, y: -0.7};          // guilty: looks away and up
  if (name === 'leo' && t > 12.9 && t < 16.0) look = {x: 0, y: 0.8};             // despair: looks down
  if (name === 'maya' && t >= 11.9 && t < 14.6) look = {x: -0.7, y: 0};          // walking in: looks ahead
  const L = lastLook[name];
  L.x += (look.x - L.x) * 0.35; L.y += (look.y - L.y) * 0.35;
  p.look = {x: L.x, y: L.y};

  armTargets(name, c, t, p);
  if (!feet) feet = {L: {x: x + c.hipL.x * c.S * 0.75, y: floor}, R: {x: x + c.hipR.x * c.S * 0.75, y: floor}};
  // planted ankles: the ankle sits above the sole
  const ankleUp = (c.footDrop - c.ankleL.y) * c.S;
  p.footL = {x: feet.L.x, y: feet.L.y - ankleUp}; p.footR = {x: feet.R.x, y: feet.R.y - ankleUp};
  p.kneeDir = kneeDir; p.hip = {x, y: hipY}; p.seated = seated;
  return p;
}

// ---------------------------------------------------------------- camera (always fits full bodies)
// keys: time -> world box to fit [x0, x1, yTop, yBottom]; frame aspect 9:16
const CAM = [
  [0, [230, 790, 660, 1400]], [6.5, [230, 790, 660, 1400]], [9.6, [250, 770, 640, 1400]],
  [11.0, [150, 941, 600, 1420]], [15.5, [150, 941, 600, 1420]], [20.8, [150, 941, 600, 1420]], [23.6, [170, 930, 620, 1410]],
];
function camera(t, W, H) {
  let i = CAM.findIndex(k => k[0] > t); if (i < 0) i = CAM.length; const a = CAM[Math.max(0, i - 1)], b = CAM[Math.min(CAM.length - 1, i)];
  const u = a === b ? 0 : ease.inOut(clamp((t - a[0]) / (b[0] - a[0])));
  const box = a[1].map((v, k) => lerp(v, b[1][k], u));
  let w = box[1] - box[0], h = box[3] - box[2];
  if (w / h > W / H) h = w * H / W; else w = h * W / H;
  w = Math.min(w, 941); h = w * H / W;
  const cx = (box[0] + box[1]) / 2, x0 = clamp(cx - w / 2, 0, 941 - w), y0 = clamp(box[3] - h + 40, 0, 1672 - h);
  return {x0, y0, k: W / w};
}

// ---------------------------------------------------------------- frame
const plate = await loadImage(PLATE);
function drawFrame(ctx, t, {width: W, height: H}) {
  const cam = camera(t, W, H);
  ctx.setTransform(cam.k, 0, 0, cam.k, -cam.x0 * cam.k, -cam.y0 * cam.k);
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(plate, 0, 0);
  // soft contact shadows, then characters back to front
  const order = ['ben', 'leo', 'maya'];
  const poses = Object.fromEntries(order.map(n => [n, poseFor(n, t)]));
  for (const n of order) {
    const p = poses[n], fy = p.seated ? SEAT_FEET_Y : FLOOR;
    ctx.fillStyle = 'rgba(40,20,10,0.22)'; ctx.beginPath(); ctx.ellipse(p.hip.x, fy, 95, 14, 0, 0, Math.PI * 2); ctx.fill();
  }
  for (const n of order) drawCharacter(ctx, C[n], poses[n]);
  // subtitles (screen space)
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  const line = LINES.find(l => t >= l.at && t < l.end + 0.3);
  if (line) {
    ctx.font = '700 52px Sub'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.lineJoin = 'round';
    const words = line.text.split(' '), rows = []; let cur = '';
    for (const w of words) { const nx = cur ? cur + ' ' + w : w; if (ctx.measureText(nx).width > 900 && cur) { rows.push(cur); cur = w; } else cur = nx; }
    rows.push(cur);
    rows.forEach((r, i) => { const y = 190 + i * 64; ctx.lineWidth = 10; ctx.strokeStyle = '#111'; ctx.strokeText(r, W / 2, y); ctx.fillStyle = '#fff'; ctx.fillText(r, W / 2, y); });
  }
}

// ---------------------------------------------------------------- run
if (process.argv[3] === '--stills') {
  // review frames only (eyes are smoothed frame to frame, so warm the state up to each time)
  const {createCanvas, GlobalFontsRegister} = await import('./animator.mjs');
  const {createRequire} = await import('node:module');
  const req = createRequire(path.join(ROOT, 'skills/directing-stickman-videos/package.json'));
  req('@napi-rs/canvas').GlobalFonts.registerFromPath(path.join(ROOT, 'skills/directing-stickman-videos/assets/fonts/NotoSans.ttf'), 'Sub');
  const cv = createCanvas(1080, 1920), cx = cv.getContext('2d');
  for (const t of process.argv.slice(4).map(Number)) {
    for (let w = Math.max(0, t - 0.5); w < t; w += 1 / FPS) poseFor('leo', w), poseFor('ben', w), poseFor('maya', w);
    cx.setTransform(1, 0, 0, 1, 0, 0); drawFrame(cx, t, {width: 1080, height: 1920});
    fs.writeFileSync(path.join(WORK, `still-${t}.png`), cv.toBuffer('image/png'));
  }
  process.exit(0);
}
const audioOut = path.join(WORK, 'poc-voice.wav');
mixWav(LINES.map(l => ({wav: l.wav, start: l.at})), DURATION, audioOut);
const out = path.join(WORK, 'poc.mp4');
const started = Date.now();
await renderVideo({seconds: DURATION, fps: FPS, drawFrame, audio: audioOut, out, ffmpeg: process.env.FFMPEG || 'ffmpeg',
  font: path.join(ROOT, 'skills/directing-stickman-videos/assets/fonts/NotoSans.ttf')});
console.log(JSON.stringify({out, seconds: +DURATION.toFixed(2), render_seconds: (Date.now() - started) / 1000}));
