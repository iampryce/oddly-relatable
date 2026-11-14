#!/usr/bin/env node
// AP-84B3 parameterised cut-out (D1-6, item I2).
//
// The AP-72 method (bible/concepts/src/ap72-cutout.cjs, validated on master v3) with the input and output paths
// as arguments. The algorithm and its thresholds are unchanged: a flat-grey background is removed by border flood
// fill (plus small enclosed pockets), then an edge "unmix" turns black-to-grey anti-aliasing into black with partial
// alpha. Eye whites are protected. Pixels are only made transparent; nothing is redrawn. The input is never modified.
//
//   node studio/tools/ap84b3/cutout.cjs --in <raw.png> --out <cutout.png> [--mode full|crop] [--meta <file.json>]
//
// mode full (default): keeps the whole canvas, so a 1024x1536 input gives a 1024x1536 transparent PNG (what the
//                      studio validator expects for a generated pose).
// mode crop:           trims to the figure with a 10 px pad, exactly as AP-72 did (used by the regression test).
// The output is write-once and must be outside the repository. The command-line tool refuses to run unless the
// experiment lock is owner-approved; the exported function is used directly by the tests.
const path = require('path'), fs = require('fs'), crypto = require('crypto');
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const sharp = require('module').createRequire(path.join(REPO_ROOT, 'skills', 'directing-stickman-videos', 'package.json'))('sharp');
const sha = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const inside = (child, parent) => { const rel = path.relative(parent, child); return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel)); };
const real = p => { try { return fs.realpathSync(p); } catch { return path.resolve(p); } };

async function cutout({input, output, mode = 'full', metaFile = null, allowInsideRepo = false}) {
  if (!['full', 'crop'].includes(mode)) throw new Error('mode must be "full" or "crop"');
  const SRC = path.resolve(input), OUT = path.resolve(output);
  if (!fs.existsSync(SRC) || !fs.statSync(SRC).isFile()) throw new Error('input file not found');
  if (!allowInsideRepo && inside(real(path.dirname(OUT)), real(REPO_ROOT))) throw new Error('the output must be outside the repository');
  if (fs.existsSync(OUT)) throw new Error('the output already exists (cut-outs are write-once)');
  if (metaFile && fs.existsSync(metaFile)) throw new Error('the metadata file already exists');
  const before = sha(SRC);
  const {data, info} = await sharp(SRC).removeAlpha().raw().toBuffer({resolveWithObject: true});
  const W = info.width, H = info.height, N = W * H;
  if (W < 64 || H < 64 || W > 4096 || H > 4096) throw new Error('input size must be between 64 and 4096 px per side');
  const lum = i => 0.299 * data[i * 3] + 0.587 * data[i * 3 + 1] + 0.114 * data[i * 3 + 2];
  const sat = i => Math.max(data[i * 3], data[i * 3 + 1], data[i * 3 + 2]) - Math.min(data[i * 3], data[i * 3 + 1], data[i * 3 + 2]);
  // background estimate: median luminance of the border rows
  const bl = []; for (let x = 0; x < W; x++) for (const y of [0, 4, H - 1, H - 5]) bl.push(lum(y * W + x)); bl.sort((a, b) => a - b);
  const BG = bl[bl.length >> 1], lo = bl[Math.floor(bl.length * 0.01)], hi = bl[Math.floor(bl.length * 0.99)];
  const isBg = i => sat(i) <= 14 && lum(i) >= BG - 28 && lum(i) <= BG + 22;   // grey, near the bg level, below eye-white brightness
  const isTight = i => sat(i) <= 8 && Math.abs(lum(i) - BG) <= 7;             // pockets: only true background grey
  const rm = new Uint8Array(N), q = [];
  const push = i => { if (!rm[i] && isBg(i)) { rm[i] = 1; q.push(i); } };
  for (let x = 0; x < W; x++) { push(x); push((H - 1) * W + x); } for (let y = 0; y < H; y++) { push(y * W); push(y * W + W - 1); }
  while (q.length) { const i = q.pop(), x = i % W, y = (i / W) | 0; if (x > 0) push(i - 1); if (x < W - 1) push(i + 1); if (y > 0) push(i - W); if (y < H - 1) push(i + W); }
  // enclosed bg-like pockets (e.g. between arm and torso), area 60..4000 and not bright
  const seen = new Uint8Array(N); let pockets = 0;
  for (let s = 0; s < N; s++) {
    if (rm[s] || seen[s] || !isTight(s)) continue;
    const comp = [s]; seen[s] = 1;
    for (let k = 0; k < comp.length; k++) { const i = comp[k], x = i % W, y = (i / W) | 0; for (const j of [x > 0 ? i - 1 : -1, x < W - 1 ? i + 1 : -1, y > 0 ? i - W : -1, y < H - 1 ? i + W : -1]) if (j >= 0 && !seen[j] && !rm[j] && isTight(j)) { seen[j] = 1; comp.push(j); } }
    if (comp.length >= 60 && comp.length <= 4000) { pockets++; for (const i of comp) rm[i] = 1; }
  }
  // alpha: removed = 0; edge band (within 3 px of removed, low saturation, darker than bg) -> black with alpha = 1 - lum/BG
  const dist = new Uint8Array(N).fill(9);
  for (let i = 0; i < N; i++) if (rm[i]) dist[i] = 0;
  for (let pass = 1; pass <= 3; pass++) for (let y = 1; y < H - 1; y++) for (let x = 1; x < W - 1; x++) { const i = y * W + x; if (dist[i] <= pass) continue; if (dist[i - 1] < pass || dist[i + 1] < pass || dist[i - W] < pass || dist[i + W] < pass) dist[i] = pass; }
  const out = Buffer.alloc(N * 4);
  let removed = 0;
  for (let i = 0; i < N; i++) {
    let r = data[i * 3], g = data[i * 3 + 1], b = data[i * 3 + 2], a = 255;
    if (rm[i]) { a = 0; removed++; }
    else if (dist[i] <= 3 && sat(i) <= 40) { const L = lum(i); a = Math.max(0, Math.min(255, Math.round((1 - L / BG) * 255 * 1.0))); if (a > 0) { r = g = b = 0; } }   // black-over-grey unmix
    out[i * 4] = r; out[i * 4 + 1] = g; out[i * 4 + 2] = b; out[i * 4 + 3] = a;
  }
  // bounding box (+10 px pad)
  let x0 = W, x1 = 0, y0 = H, y1 = 0;
  for (let i = 0; i < N; i++) if (out[i * 4 + 3] > 8) { const x = i % W, y = (i / W) | 0; x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
  if (x1 < x0 || y1 < y0) throw new Error('nothing but background was found: no cut-out was written');
  const figure = {x0, y0, width: x1 - x0 + 1, height: y1 - y0 + 1};
  const pad = 10; x0 = Math.max(0, x0 - pad); y0 = Math.max(0, y0 - pad); x1 = Math.min(W - 1, x1 + pad); y1 = Math.min(H - 1, y1 + pad);
  const full = await sharp(out, {raw: {width: W, height: H, channels: 4}}).png().toBuffer();
  const bytes = mode === 'crop' ? await sharp(full).extract({left: x0, top: y0, width: x1 - x0 + 1, height: y1 - y0 + 1}).png().toBuffer() : full;
  fs.writeFileSync(OUT, bytes, {flag: 'wx'});
  const after = sha(SRC);
  if (after !== before) throw new Error('the input changed while it was being read');
  const meta = {tool: 'studio/tools/ap84b3/cutout.cjs', mode, source_sha256: before, source_unchanged: true, source_size: {width: W, height: H},
    output_sha256: crypto.createHash('sha256').update(bytes).digest('hex'), output_bytes: bytes.length,
    output_size: mode === 'crop' ? {width: x1 - x0 + 1, height: y1 - y0 + 1} : {width: W, height: H},
    crop: {x0, y0, w: x1 - x0 + 1, h: y1 - y0 + 1}, figure, bg_lum: BG, bg_lum_p1: lo, bg_lum_p99: hi,
    background_fraction_removed: +(removed / N).toFixed(4), enclosed_pockets_removed: pockets,
    thresholds: {bg_saturation_max: 14, bg_lum_below: 28, bg_lum_above: 22, pocket_saturation_max: 8, pocket_lum_tolerance: 7, pocket_area: [60, 4000], edge_band_px: 3, edge_saturation_max: 40},
    method: 'border flood fill + enclosed pocket removal + black-over-grey edge unmix; no redrawing (AP-72 method, thresholds unchanged)'};
  if (metaFile) fs.writeFileSync(metaFile, JSON.stringify(meta, null, 1), {flag: 'wx'});
  return meta;
}

module.exports = {cutout};

if (require.main === module) {
  (async () => {
    const args = process.argv.slice(2), opt = {};
    for (let i = 0; i < args.length; i += 2) {
      if (!['--in', '--out', '--mode', '--meta'].includes(args[i]) || args[i + 1] === undefined) throw new Error('usage: cutout.cjs --in <raw.png> --out <cutout.png> [--mode full|crop] [--meta <file.json>]');
      opt[args[i].slice(2)] = args[i + 1];
    }
    if (!opt.in || !opt.out) throw new Error('usage: cutout.cjs --in <raw.png> --out <cutout.png> [--mode full|crop] [--meta <file.json>]');
    const {loadLock} = await import(require('url').pathToFileURL(path.join(REPO_ROOT, 'studio', 'lib', 'experiment-spec.mjs')).href);
    loadLock();                                                   // refuses unless the lock is owner-approved
    console.log(JSON.stringify(await cutout({input: opt.in, output: opt.out, mode: opt.mode || 'full', metaFile: opt.meta || null}), null, 1));
  })().catch(e => { console.error(`cutout: ${e.message}`); process.exit(1); });
}
