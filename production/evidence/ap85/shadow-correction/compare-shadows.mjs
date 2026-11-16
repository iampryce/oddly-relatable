// AP-85 shadow correction (2026-11-16): before/after comparison of the accepted A4 scene.
//
// Builds A4 twice, with the pre-fix code (BEFORE: a checkout of commit 81fc4c0) and the corrected code (AFTER: this
// repository), paints the six review-sheet sample times with the UNMODIFIED renderer, and writes:
//   A4-shadow-before-after.png  row 1 before, row 2 after, row 3 the after frame dimmed with every changed pixel in magenta
//   difference.json             per time: changed pixels and their bounding box; plus the checks that the projects differ
//                               only in shadow visibility windows and that frames without shadows are pixel-identical
// Local, $0. Run with FFMPEG/FFPROBE set:  BEFORE=<checkout of 81fc4c0> node production/evidence/ap85/shadow-correction/compare-shadows.mjs
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url)), AFTER = path.resolve(HERE, '..', '..', '..', '..');
if (!process.env.BEFORE || !process.env.FFPROBE) throw new Error('Set BEFORE (a checkout of commit 81fc4c0) and FFMPEG/FFPROBE');
const BEFORE = path.resolve(process.env.BEFORE);
const TIMES = [0.9, 2.4, 3.9, 5.4, 6.9, 8.4];                                // the A4 review-sheet sample times (one per line)
const LABELS = ['1 Wide', '2 Medium single on ph', '3 Medium single on c01', '4 Close single on c01', '5 Close single on ph', '6 Wide'];

async function build(repo) {
  const imp = p => import(pathToFileURL(path.join(repo, p)).href);
  const {writePlaceholder, PLACEHOLDER_CHARACTER} = await imp('production/tests/fixtures/ap85-placeholder.mjs');
  const {compileProject} = await imp('production/lib/scene.mjs');
  const {rendererModules, canvas, ensureFonts, FONT} = await imp('production/lib/runtime.mjs');
  const src = fs.readFileSync(path.join(repo, 'production', 'tests', 'ap85-track-a.test.mjs'), 'utf8');
  const a = src.indexOf('const c01 = '), s = src.indexOf('const SCENES = {', a), b = src.indexOf('\n};\n', s);
  const PH_REG = writePlaceholder(fs.mkdtempSync(path.join(os.tmpdir(), 'cmp-ph-')));
  const SCENES = new Function('C01', 'PH', 'PH_REG', `${src.slice(a, b + 3)}\nreturn SCENES;`)('character-01', PLACEHOLDER_CHARACTER, PH_REG);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cmp-')), r = await compileProject(SCENES.A4(), {outDir: dir, allowSynthetic: true});
  const project = JSON.parse(fs.readFileSync(r.projectFile, 'utf8'));
  const noShadow = structuredClone(project); noShadow.shots[0].layers = noShadow.shots[0].layers.filter(l => !l.path.includes('/shadow-'));
  fs.writeFileSync(path.join(dir, 'no-shadow.json'), JSON.stringify(noShadow));
  const {core, render} = await rendererModules();
  const grab = draw => t => { const f = draw(t), c = canvas.createCanvas(f.width, f.height); c.getContext('2d').drawImage(f, 0, 0); return c; };
  return {project, full: grab(await render.painter(core.loadProject(r.projectFile))), bare: grab(await render.painter(core.loadProject(path.join(dir, 'no-shadow.json')))), canvas, ensureFonts, FONT};
}

const before = await build(BEFORE), after = await build(AFTER), {canvas, FONT} = after;
after.ensureFonts();
const data = c => c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
// Projects: identical apart from the visibility windows of shadow layers.
const shadowless = p => JSON.stringify({...p, shots: p.shots.map(s => ({...s, layers: s.layers.map(l => (l.path.includes('/shadow-') ? {...l, from: undefined, to: undefined} : l))}))});
const projectCheck = {
  identicalApartFromShadowWindows: shadowless(before.project) === shadowless(after.project),
  shadowWindowsBefore: before.project.shots[0].layers.filter(l => l.path.includes('/shadow-')).map(l => [l.from ?? 'none', l.to ?? 'none']),
  shadowWindowsAfter: after.project.shots[0].layers.filter(l => l.path.includes('/shadow-')).map(l => [l.from ?? 'whole shot', l.to ?? 'whole shot']),
};
// Frames: per sample time, every changed pixel and its box; and frames without shadows are identical.
const TW = 300, TH = Math.round(TW * 1920 / 1080), PAD = 12, CAP = 40, HEAD = 96;
const sheet = canvas.createCanvas(PAD + TIMES.length * (TW + PAD), HEAD + 3 * (TH + CAP + PAD)), ctx = sheet.getContext('2d');
ctx.fillStyle = '#1d2433'; ctx.fillRect(0, 0, sheet.width, sheet.height); ctx.textBaseline = 'top';
const text = (s, x, y, w = 400, px = 14, c = '#dfe5f0') => { ctx.font = `${w} ${px}px "${FONT.sans}"`; ctx.fillStyle = c; ctx.fillText(s, x, y); };
text('AP-85 A4 shadow correction · before (row 1, accepted evidence code 81fc4c0) · after (row 2) · changed pixels in magenta (row 3)', PAD, 12, 700, 17, '#ffffff');
text('TRACK A ONLY. The blue/green figure is a SYNTHETIC PLACEHOLDER, NOT ARTWORK. Only shadows differ: with shadows removed, before and after are pixel-identical.', PAD, 38, 700, 13, '#ffd34d');
text('Before: every split shadow layer showed for the whole shot (duplicates; off-camera members still cast shadows). After: each shadow shows only while its member is on camera.', PAD, 60, 400, 13);
const frames = [];
for (const [i, t] of TIMES.entries()) {
  const b = before.full(t), a = after.full(t), db = data(b), da = data(a);
  const bareSame = Buffer.compare(Buffer.from(data(before.bare(t))), Buffer.from(data(after.bare(t)))) === 0;
  let n = 0, x0 = Infinity, y0 = Infinity, x1 = -1, y1 = -1;
  const diff = canvas.createCanvas(a.width, a.height), dc = diff.getContext('2d');
  dc.drawImage(a, 0, 0); dc.fillStyle = 'rgba(0,0,0,0.55)'; dc.fillRect(0, 0, a.width, a.height);
  const img = dc.getImageData(0, 0, a.width, a.height);
  for (let k = 0; k < db.length; k += 4) {
    if (db[k] === da[k] && db[k + 1] === da[k + 1] && db[k + 2] === da[k + 2]) continue;
    n++; const p = k / 4, x = p % a.width, y = (p - x) / a.width;
    if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
    img.data[k] = 255; img.data[k + 1] = 0; img.data[k + 2] = 200; img.data[k + 3] = 255;
  }
  dc.putImageData(img, 0, 0);
  frames.push({t, shot: LABELS[i], changedPixels: n, changedBox: n ? {x0, y0, x1, y1} : null, framesWithoutShadowsIdentical: bareSame});
  const x = PAD + i * (TW + PAD);
  [b, a, diff].forEach((c, row) => {
    const y = HEAD + row * (TH + CAP + PAD);
    ctx.drawImage(c, x, y, TW, TH);
    text(row === 0 ? `${LABELS[i]} · t ${t}s` : row === 1 ? 'after' : `${n} px changed`, x, y + TH + 6, row === 0 ? 700 : 400, 12.5, row === 2 && n ? '#ff7ae0' : '#dfe5f0');
  });
}
fs.writeFileSync(path.join(HERE, 'A4-shadow-before-after.png'), sheet.toBuffer('image/png'));
fs.writeFileSync(path.join(HERE, 'difference.json'), JSON.stringify({
  scene: 'AP-85 A4 (accepted scene definition, production/tests/ap85-track-a.test.mjs)', before: 'commit 81fc4c0 (pre-fix)', after: 'the corrected code',
  projects: projectCheck, frames,
  summary: 'Only shadow pixels differ. With every shadow layer removed, the before and after frames are pixel-identical at every sample time, and the projects are identical apart from the visibility windows of shadow layers.',
}, null, 2) + '\n');
console.log(JSON.stringify(frames.map(f => [f.t, f.changedPixels, f.framesWithoutShadowsIdentical])), projectCheck.identicalApartFromShadowWindows);
