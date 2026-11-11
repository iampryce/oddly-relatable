// AP-63 upscaling feasibility tests (concept code).
// Reads the two production candidates (never modifies them) and writes ONLY new files into
// production-candidates/upscale-tests/. Local deterministic resamplers in the installed `sharp` (libvips)
// plus a small shock-filter edge sharpener written here. No installs, no AI model, no generation.
//
// Findings baked into this script:
//  * sharp resize({kernel}) treats cubic/mitchell/lanczos2/lanczos3/mks* identically when ENLARGING (bicubic).
//  * affine() needs a 0.25 px input offset for a 2x enlarge to stay pixel-aligned (0 gives a 1/2 px shift).
const path = require('path'), fs = require('fs');
const sharp = require('module').createRequire(path.resolve(__dirname, '../../../skills/directing-stickman-videos/package.json'))('sharp');
const D = path.resolve(__dirname, '../lookdev-richenv') + '/', P = D + 'production-candidates/', O = P + 'upscale-tests/';
fs.mkdirSync(O, { recursive: true });
const C4 = P + 'production-candidate-04-character-master.png', C5 = P + 'production-candidate-05-environment-master.png';

// ---- enlargers: take PNG buffer, return {data(raw RGB), w, h}
async function enlarge(buf, f, method) {
  const m = await sharp(buf).metadata();
  const w = Math.round(m.width * f), h = Math.round(m.height * f);
  let p;
  if (method === 'nearest') p = sharp(buf).resize(w, h, { kernel: 'nearest' });
  else if (method === 'linear') p = sharp(buf).resize(w, h, { kernel: 'linear' });
  else if (method === 'cubic' || method === 'cubic+unsharp') p = sharp(buf).resize(w, h, { kernel: 'lanczos3' });
  else if (method === 'nohalo' || method === 'lbb') {
    // integer factors only; offset keeps pixel centres aligned
    p = sharp(buf).affine([f, 0, 0, f], { interpolator: method, idx: 0.25 * (f === 2 ? 1 : 0.5), idy: 0.25 * (f === 2 ? 1 : 0.5) });
  } else p = sharp(buf).resize(w, h, { kernel: 'lanczos3' }); // base for shock
  if (method === 'cubic+unsharp') p = p.sharpen({ sigma: 0.8, m1: 0, m2: 2.5 });
  const { data, info } = await p.removeAlpha().raw().toBuffer({ resolveWithObject: true });
  return { data, w: info.width, h: info.height };
}

// ---- shock filter (Osher-Rudin style) on RGB, driven by luminance; pushes blurred edges toward the nearer side.
function shock(img, iters, grad) {
  let { data, w, h } = img;
  const L = new Float32Array(w * h);
  for (let it = 0; it < iters; it++) {
    for (let i = 0; i < w * h; i++) L[i] = 0.299 * data[i * 3] + 0.587 * data[i * 3 + 1] + 0.114 * data[i * 3 + 2];
    const out = Buffer.from(data);
    for (let y = 1; y < h - 1; y++) for (let x = 1; x < w - 1; x++) {
      const i = y * w + x, c = L[i];
      const gx = (L[i + 1] - L[i - 1]) * 0.5, gy = (L[i + w] - L[i - w]) * 0.5;
      if (Math.abs(gx) + Math.abs(gy) < grad) continue; // leave flat areas and texture untouched
      const lap = L[i - 1] + L[i + 1] + L[i - w] + L[i + w] - 4 * c;
      // find min / max luminance neighbour in 3x3
      let mn = i, mx = i;
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) { const j = i + dy * w + dx; if (L[j] < L[mn]) mn = j; if (L[j] > L[mx]) mx = j; }
      const src = lap > 0 ? mn : mx; // concave (lap>0) -> take the darker neighbour; convex -> the lighter one
      const o = i * 3, s = src * 3;
      out[o] = data[s]; out[o + 1] = data[s + 1]; out[o + 2] = data[s + 2];
    }
    data = out;
  }
  return { data, w, h };
}

function edgeMAE(orig, rec, w, h) {
  let s = 0, k = 0;
  for (let y = 1; y < h - 1; y++) for (let x = 1; x < w - 1; x++) {
    const o = (y * w + x) * 3;
    const g = Math.abs(orig[o] - orig[o + 3]) + Math.abs(orig[o] - orig[o + w * 3]);
    if (g > 60) { for (let c = 0; c < 3; c++) s += Math.abs(orig[o + c] - rec[o + c]); k += 3; }
  }
  return +(s / k).toFixed(2);
}
function mae(a, b) { let s = 0; for (let i = 0; i < a.length; i++) s += Math.abs(a[i] - b[i]); return +(s / a.length).toFixed(2); }
function psnr(a, b) { let s = 0; for (let i = 0; i < a.length; i++) { const d = a[i] - b[i]; s += d * d; } return +(10 * Math.log10(255 * 255 / (s / a.length))).toFixed(2); }

(async () => {
  const report = { groundTruth: {}, timing2x: {}, tiling: {} };
  // 1) Ground truth: halve each candidate, enlarge back x2 with each method, compare with the original.
  for (const [label, file, shockGrad] of [['char04', C4, 40], ['room05', C5, 90]]) {
    const m = await sharp(file).metadata();
    const W = Math.floor(m.width / 2) * 2, H = Math.floor(m.height / 2) * 2;
    const orig = await sharp(file).removeAlpha().extract({ left: 0, top: 0, width: W, height: H }).raw().toBuffer();
    const half = await sharp(file).removeAlpha().extract({ left: 0, top: 0, width: W, height: H }).resize(W / 2, H / 2, { kernel: 'lanczos3' }).png().toBuffer();
    report.groundTruth[label] = {};
    for (const method of ['nearest', 'linear', 'cubic', 'nohalo', 'lbb', 'cubic+unsharp', 'cubic+shock1', 'cubic+shock2']) {
      const t = Date.now();
      let rec;
      if (method.startsWith('cubic+shock')) rec = shock(await enlarge(half, 2, 'cubic'), +method.slice(-1), shockGrad);
      else rec = await enlarge(half, 2, method);
      report.groundTruth[label][method] = { MAE: mae(orig, rec.data), PSNR: psnr(orig, rec.data), edgeMAE: edgeMAE(orig, rec.data, W, H), ms: Date.now() - t };
    }
  }

  // 2) Real 2x enlargements on COPIES (new files only)
  const c4 = await sharp(C4).removeAlpha().png().toBuffer();
  const c5 = await sharp(C5).removeAlpha().png().toBuffer();
  const save = async (img, name) => { await sharp(img.data, { raw: { width: img.w, height: img.h, channels: 3 } }).png().toFile(O + name); return `${img.w}x${img.h}`; };
  let t = Date.now();
  const c4cubic = await enlarge(c4, 2, 'cubic'); report.timing2x.char04_cubic_ms = Date.now() - t;
  report.sizes = { char04_2x_cubic: await save(c4cubic, 'char04_2x_cubic.png') };
  t = Date.now();
  const c4shock = shock(c4cubic, 1, 40); report.timing2x.char04_shock1_ms = Date.now() - t;
  report.sizes.char04_2x_cubic_shock1 = await save(c4shock, 'char04_2x_cubic_shock1.png');
  t = Date.now();
  const c5nh = await enlarge(c5, 2, 'nohalo'); report.timing2x.room05_nohalo_ms = Date.now() - t;
  report.sizes.room05_2x_nohalo = await save(c5nh, 'room05_2x_nohalo.png');
  const c5cubic = await enlarge(c5, 2, 'cubic');
  report.sizes.room05_2x_cubic = await save(c5cubic, 'room05_2x_cubic.png');

  // 3) Tiled processing seam test on the plate: 2x3 tiles with overlap, shock filter per tile, feather-blended.
  //    (Local deterministic filters should give ~0 seam error; an AI model per tile would not, see README.)
  {
    const W2 = c5cubic.w, H2 = c5cubic.h, OV = 64;
    const whole = shock(c5cubic, 1, 90);
    const acc = new Float32Array(W2 * H2 * 3), wt = new Float32Array(W2 * H2);
    const cols = 2, rows = 3, tw = Math.ceil(W2 / cols), th = Math.ceil(H2 / rows);
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
      const x0 = Math.max(0, c * tw - OV), y0 = Math.max(0, r * th - OV), x1 = Math.min(W2, (c + 1) * tw + OV), y1 = Math.min(H2, (r + 1) * th + OV);
      const w = x1 - x0, h = y1 - y0, tile = Buffer.alloc(w * h * 3);
      for (let y = 0; y < h; y++) c5cubic.data.copy(tile, y * w * 3, ((y0 + y) * W2 + x0) * 3, ((y0 + y) * W2 + x1) * 3);
      const res = shock({ data: tile, w, h }, 1, 90);
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
        const fx = Math.min(1, Math.min(x, w - 1 - x) / OV + (x0 === 0 && x < OV ? 1 : 0) + (x1 === W2 && w - 1 - x < OV ? 1 : 0));
        const fy = Math.min(1, Math.min(y, h - 1 - y) / OV + (y0 === 0 && y < OV ? 1 : 0) + (y1 === H2 && h - 1 - y < OV ? 1 : 0));
        const k = Math.max(0.001, Math.min(1, fx) * Math.min(1, fy)), gi = (y0 + y) * W2 + x0 + x;
        for (let ch = 0; ch < 3; ch++) acc[gi * 3 + ch] += res.data[(y * w + x) * 3 + ch] * k;
        wt[gi] += k;
      }
    }
    const tiled = Buffer.alloc(W2 * H2 * 3);
    for (let i = 0; i < W2 * H2; i++) for (let ch = 0; ch < 3; ch++) tiled[i * 3 + ch] = Math.round(acc[i * 3 + ch] / wt[i]);
    report.tiling = { tilesGrid: `${cols}x${rows}`, overlapPx: OV, meanAbsDiffTiledVsWhole: mae(whole.data, tiled), maxAbsDiff: (() => { let m = 0; for (let i = 0; i < tiled.length; i++) m = Math.max(m, Math.abs(tiled[i] - whole.data[i])); return m; })() };
  }
  fs.writeFileSync(O + 'upscale-test-results.json', JSON.stringify(report, null, 1));
  console.log(JSON.stringify(report, null, 1));
})();
