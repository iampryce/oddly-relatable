// 3D camera (Gate 1): stills of one native 3D character seated on a chair, seen from the front and from a
// three-quarter view, and a comparison picture beside a reference picture (optional; read only, never copied).
//
//   xvfb-run -a node production/animation/cam3d-still.mjs --spec production/animation/cast3d/uncle-mortimer.json \
//     --out <folder> [--ref <approved pose png>] [--yaw 38] [--ss 2] [--bench 10] [--font <ttf>]
//
// Writes front.png, three-quarter.png and (with --ref) comparison.png in <folder>, and prints the timings as JSON.
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
const specFile = arg('spec'), outDir = arg('out'), ref = arg('ref'), yaw = Number(arg('yaw', 38)), ss = Number(arg('ss', 2));
const bench = Number(arg('bench', 0)), font = arg('font', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf');
if (!specFile || !outDir) { console.error('usage: cam3d-still.mjs --spec <json> --out <folder> [--ref <png>] [--yaw 38] [--ss 2] [--bench N]'); process.exit(2); }
const spec = JSON.parse(fs.readFileSync(specFile, 'utf8'));
fs.mkdirSync(outDir, {recursive: true});
const W = 1080, H = 608, FOV = 30;

const t0 = performance.now();
const R = await createCam3D({width: W, height: H, ss});
const ch = buildCharacter(R, spec);
R.scene.add(ch.group, buildChair(R, ch.joints));
const t1 = performance.now();

// framing: the seated figure, floor to the top of the hair, fills most of the height
const J = ch.joints, top = J.head.y + J.headR * 1.45, target = {x: 0, y: top * 0.47, z: 0.02};
const dist = fitDistance(top, FOV, 0.8);
const view = y => ({fov: FOV, target, position: orbit(target, dist, y, 9)});
const views = [['front', 0], ['three-quarter', yaw]];
const files = {}, times = {};
for (const [name, y] of views) {
  const s = performance.now(), cv = R.render(view(y));
  times[name] = performance.now() - s;
  const buf = cv.toBuffer('image/png'); files[name] = buf;
  fs.writeFileSync(path.join(outDir, `${name}.png`), buf);
}
// steady-state timing: the same frames again (the first frame compiles the shaders and uploads the textures)
const per = [];
for (let i = 0; i < bench; i++) { const s = performance.now(); R.render(view(i % 2 ? yaw : 0)); per.push(performance.now() - s); }
const again = R.render(view(0)).toBuffer('image/png');
const sha = b => crypto.createHash('sha256').update(b).digest('hex').slice(0, 16);

if (ref) {
  if (fs.existsSync(font)) GlobalFonts.registerFromPath(font, 'Label');
  const bar = 56, cv = createCanvas(W * 3, H + bar), x = cv.getContext('2d');
  x.fillStyle = '#ffffff'; x.fillRect(0, 0, cv.width, cv.height);
  const refImg = await loadImage(ref), k = Math.min((W - 40) / refImg.width, (H - 30) / refImg.height);
  x.fillStyle = '#f6f3ec'; x.fillRect(0, bar, W, H);
  x.drawImage(refImg, (W - refImg.width * k) / 2, bar + (H - refImg.height * k) / 2, refImg.width * k, refImg.height * k);
  for (const [i, [name]] of views.entries()) x.drawImage(await loadImage(files[name]), W * (i + 1), bar);
  const labels = [`${spec.name}: approved 2D art (reference only)`, `New 3D ${spec.name}: front`, `New 3D ${spec.name}: three-quarter (${yaw}°)`];
  x.font = '26px Label'; x.fillStyle = '#1b1b1b'; x.textBaseline = 'middle';
  labels.forEach((l, i) => { x.textAlign = 'center'; x.fillText(l, W * i + W / 2, bar / 2); });
  x.fillStyle = '#1b1b1b'; for (const i of [1, 2]) x.fillRect(W * i - 1, 0, 2, cv.height);
  fs.writeFileSync(path.join(outDir, 'comparison.png'), cv.toBuffer('image/png'));
}

const mean = a => a.length ? a.reduce((s, v) => s + v, 0) / a.length : null;
console.log(JSON.stringify({
  size: `${W}x${H}`, supersampling: ss, setup_ms: Math.round(t1 - t0),
  first_frame_ms: Object.fromEntries(Object.entries(times).map(([k2, v]) => [k2, Math.round(v)])),
  steady_frame_ms: per.length ? Math.round(mean(per)) : null, steady_frames: per.length,
  deterministic: sha(files.front) === sha(again), front_sha: sha(files.front),
  peak_rss_mb: Math.round(process.resourceUsage().maxRSS / 1024),
}));
process.exit(0);
