// 3D camera (Gate 1): stills of one native 3D character seated on a wooden chair, seen from the front and from a
// three-quarter view, with the face as vector shapes (B) and, given the approved art, as a picture (A) for comparison,
// and a sheet: the approved art (reference only) | front | three-quarter, one row per face. The approved art is only
// read, never copied.
//
//   xvfb-run -a node production/animation/cam3d-still.mjs --spec production/animation/cast3d/uncle-mortimer.json \
//     --out <folder> [--ref <approved pose png>] [--yaw 38] [--ss 4] [--bench 4] [--font <ttf>]
//
// Writes <key>-face-shapes-front.png, <key>-face-shapes-three-quarter.png (and -face-picture- with --ref) and
// <key>-sheet.png in <folder>, and prints the timings as JSON.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {buildChair, buildCharacter, createCam3D} from './cam3d.mjs';
import {fitDistance, orbit} from './cam3d-math.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(HERE, '../../skills/directing-stickman-videos/package.json'));
const {createCanvas, loadImage, GlobalFonts} = require('@napi-rs/canvas');

const arg = (name, dflt) => { const i = process.argv.indexOf(`--${name}`); return i > 0 ? process.argv[i + 1] : dflt; };
const specFile = arg('spec'), outDir = arg('out'), ref = arg('ref'), yaw = Number(arg('yaw', 38)), ss = Number(arg('ss', 4));
const bench = Number(arg('bench', 0)), font = arg('font', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf');
if (!specFile || !outDir) { console.error('usage: cam3d-still.mjs --spec <json> --out <folder> [--ref <png>] [--yaw 38] [--ss 4] [--bench N]'); process.exit(2); }
const spec = JSON.parse(fs.readFileSync(specFile, 'utf8'));
fs.mkdirSync(outDir, {recursive: true});
const W = 1080, H = 608, FOV = 30, line = spec.line / spec.px_per_unit;
const refImg = ref ? await loadImage(ref) : null;
const sha = b => crypto.createHash('sha256').update(b).digest('hex').slice(0, 16);

const t0 = performance.now();
const R = await createCam3D({width: W, height: H, ss});
const faces = [['shapes', 'Face B: vector shapes'], ...(refImg ? [['picture', 'Face A: picture']] : [])];
const chars = Object.fromEntries(faces.map(([f]) => [f, buildCharacter(R, spec, {face: f, faceImage: refImg})]));
const J = chars.shapes.joints;
R.scene.add(buildChair(R, J));
const setup = performance.now() - t0;

// framing: the seated figure, floor to the top of the hair, fills most of the height
const top = J.head.y + J.headR * 1.42, target = {x: 0, y: top * 0.47, z: 0.05};
const dist = fitDistance(top, FOV, 0.78);
const view = y => ({fov: FOV, target, position: orbit(target, dist, y, 6)});
const views = [['front', 0], ['three-quarter', yaw]];
const files = {}, times = [];
for (const [f] of faces) {
  for (const [k, c] of Object.entries(chars)) R.scene.remove(c.group);
  R.scene.add(chars[f].group);
  for (const [name, y] of views) {
    const s = performance.now(), buf = R.render(view(y), line).toBuffer('image/png');
    times.push(performance.now() - s);
    files[`${f}-${name}`] = buf;
    fs.writeFileSync(path.join(outDir, `${spec.key}-face-${f}-${name}.png`), buf);
  }
}
const per = [];
for (let i = 0; i < bench; i++) { const s = performance.now(); R.render(view(i % 2 ? yaw : 0), line); per.push(performance.now() - s); }
const last = faces[faces.length - 1][0];
const again = R.render(view(yaw), line).toBuffer('image/png');

// the sheet: one row per face
if (fs.existsSync(font)) GlobalFonts.registerFromPath(font, 'Label');
const bar = 56, sheet = createCanvas(W * 3, (H + bar) * faces.length), x = sheet.getContext('2d');
x.fillStyle = '#ffffff'; x.fillRect(0, 0, sheet.width, sheet.height);
x.font = '26px Label'; x.textBaseline = 'middle'; x.textAlign = 'center';
for (const [row, [f, label]] of faces.entries()) {
  const y0 = row * (H + bar);
  x.fillStyle = '#f6f3ec'; x.fillRect(0, y0 + bar, W, H);
  if (refImg) {
    const k = Math.min((W - 40) / refImg.width, (H - 30) / refImg.height);
    x.drawImage(refImg, (W - refImg.width * k) / 2, y0 + bar + (H - refImg.height * k) / 2, refImg.width * k, refImg.height * k);
  }
  for (const [i, [name]] of views.entries()) x.drawImage(await loadImage(files[`${f}-${name}`]), W * (i + 1), y0 + bar);
  const labels = [refImg ? `${spec.name}: approved 2D art (reference only)` : '', `${label}: front`, `${label}: three-quarter (${yaw}°)`];
  x.fillStyle = '#1b1b1b';
  labels.forEach((l, i) => x.fillText(l, W * i + W / 2, y0 + bar / 2));
  x.fillRect(0, y0 - 1, sheet.width, row ? 2 : 0);
}
x.fillStyle = '#1b1b1b'; for (const i of [1, 2]) x.fillRect(W * i - 1, 0, 2, sheet.height);
fs.writeFileSync(path.join(outDir, `${spec.key}-sheet.png`), sheet.toBuffer('image/png'));

const mean = a => a.length ? Math.round(a.reduce((s, v) => s + v, 0) / a.length) : null;
console.log(JSON.stringify({
  size: `${W}x${H}`, supersampling: ss, setup_ms: Math.round(setup), frame_ms: times.map(Math.round), steady_frame_ms: mean(per),
  deterministic: sha(files[`${last}-three-quarter`]) === sha(again), peak_rss_mb: Math.round(process.resourceUsage().maxRSS / 1024),
}));
process.exit(0);
