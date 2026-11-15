// AP-85 review: frame-level fingerprint of Track A scenes (render plan, generated assets, renderer frames every 0.1 s).
// Used to show that scenes the owner-review corrections must not change (A1, A3a, A3b, A5, A6) are byte-identical
// before and after. Run at each commit with FFMPEG/FFPROBE set:  OUT=<file> node production/evidence/ap85/review/fingerprint-frames.mjs
// (IDS=A1,A3a,... selects scenes; REPO defaults to this repository).
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path'; import crypto from 'node:crypto'; import {fileURLToPath, pathToFileURL} from 'node:url';
const repo = process.env.REPO || path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..'), out = process.env.OUT, ids = (process.env.IDS || 'A1,A3a,A3b,A5,A6').split(',');
const imp = p => import(pathToFileURL(path.join(repo, p)).href);
const {writePlaceholder, PLACEHOLDER_CHARACTER} = await imp('production/tests/fixtures/ap85-placeholder.mjs');
const {compileProject} = await imp('production/lib/scene.mjs');
const {rendererModules} = await imp('production/lib/runtime.mjs');
const src = fs.readFileSync(path.join(repo, 'production/tests/ap85-track-a.test.mjs'), 'utf8');
const a = src.indexOf('const c01 = '), s = src.indexOf('const SCENES = {', a), b = src.indexOf('\n};\n', s);
const PH_REG = writePlaceholder(fs.mkdtempSync(path.join(os.tmpdir(), 'fp-ph-')));
const SCENES = new Function('C01', 'PH', 'PH_REG', `${src.slice(a, b + 3)}\nreturn SCENES;`)('character-01', PLACEHOLDER_CHARACTER, PH_REG);
const sha = x => crypto.createHash('sha256').update(x).digest('hex');
const {core, render} = await rendererModules();
const res = {};
for (const id of ids) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), `fp-${id}-`)), r = await compileProject(SCENES[id](), {outDir: dir, allowSynthetic: true});
  const p = core.loadProject(r.projectFile), draw = await render.painter(p);
  const assets = {}; for (const sub of ['assets/gen', 'assets/src']) for (const f of fs.readdirSync(path.join(dir, sub))) assets[`${sub}/${f}`] = sha(fs.readFileSync(path.join(dir, sub, f)));
  const frames = {}; for (let t = 0; t < p.duration - 1e-6; t = +(t + 0.1).toFixed(2)) { const f = draw(t); frames[t.toFixed(2)] = sha(f.getContext('2d').getImageData(0, 0, f.width, f.height).data); }
  res[id] = {project: sha(fs.readFileSync(r.projectFile)), assets: sha(JSON.stringify(assets)), frames, frameCount: Object.keys(frames).length};
  console.log(id, res[id].project.slice(0, 12), res[id].frameCount, 'frames');
}
fs.writeFileSync(out, JSON.stringify(res, null, 1));
