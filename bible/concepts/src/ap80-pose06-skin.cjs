// AP-80: skin-only correction of the EXISTING extracted Pose 06 (deadpan, arms crossed). Reads the source (never modified) and writes NEW files only
// into lookdev-richenv/ap80-pose06-test/. Same method as v3 (AP-67): colour-ratio skin mask with plateau weighting + per-channel gain,
// gain computed from SAMPLED source and target values. Alpha channel is copied unchanged; hands, mouth, eyes, outline, sweater, shoes are not touched.
const path = require('path'), fs = require('fs'), crypto = require('crypto');
const sharp = require('module').createRequire(path.resolve(__dirname, '../../../skills/directing-stickman-videos/package.json'))('sharp');
const D = path.resolve(__dirname, '../lookdev-richenv') + '/', O = D + 'ap80-pose06-test/';
const SRC = D + 'extracted/canonical-character-01_06-deadpan-arms-crossed.png';
const V3 = D + 'production-candidates/corrected/candidate-04_corrected-v3.png';
const CANON = D + 'lookdev-scene-01.png';
const sha = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
// skin colour ratios of the SOURCE (g/r, (r-b)/r) are measured from the source itself below; plateau weighting as in v3
function weightFn(gr0, br0) {
  return (r, g, b) => (r < 70) ? 0 : clamp(2 - Math.abs(g / r - gr0) / 0.025) * clamp(2 - Math.abs((r - b) / r - br0) / 0.05);
}
async function meanSkin(file, box, gr0, br0, rMin) {
  // sample actual interior skin pixels (full weight window) in an optional region
  let img = sharp(file).removeAlpha(); if (box) img = img.extract(box);
  const { data, info } = await img.raw().toBuffer({ resolveWithObject: true });
  const w = weightFn(gr0, br0); let s = [0, 0, 0], n = 0;
  for (let i = 0; i < info.width * info.height; i++) { const r = data[i * 3], g = data[i * 3 + 1], b = data[i * 3 + 2]; if (r < rMin) continue; if (w(r, g, b) >= 0.999) { s[0] += r; s[1] += g; s[2] += b; n++; } }
  return { mean: s.map(v => v / n), n };
}
(async () => {
  fs.mkdirSync(O, { recursive: true });
  const before = { src: sha(SRC), v3: sha(V3), canon: sha(CANON) };
  const { data: src, info } = await sharp(SRC).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  const W = info.width, H = info.height, N = W * H;
  // 1) source skin ratios: robust seed = the head's modal skin colour (pixels with r>=240, g/r in 0.88..0.95, not white/pink)
  const hist = new Map();
  for (let i = 0; i < N; i++) { if (src[i * 4 + 3] < 255 || ((i / W) | 0) > H * 0.40) continue; const r = src[i * 4], g = src[i * 4 + 1], b = src[i * 4 + 2]; if (r < 240 || g / r < 0.88 || g / r > 0.95 || b > 225) continue; const k = r + ',' + g + ',' + b; hist.set(k, (hist.get(k) || 0) + 1); }
  const seed = [...hist.entries()].sort((a, b) => b[1] - a[1])[0][0].split(',').map(Number);
  const GR0 = seed[1] / seed[0], BR0 = (seed[0] - seed[2]) / seed[0];
  const wf = weightFn(GR0, BR0);
  // 2) mask = skin weight on head region only, alpha > 0
  const maskW = Buffer.alloc(N); let sMean = [0, 0, 0], nS = 0;
  for (let i = 0; i < N; i++) {
    if (src[i * 4 + 3] === 0 || ((i / W) | 0) > H * 0.40) continue;
    const w = wf(src[i * 4], src[i * 4 + 1], src[i * 4 + 2]); if (w <= 0) continue;
    maskW[i] = Math.round(w * 255); if (w >= 0.999 && src[i * 4 + 3] === 255 && src[i * 4] >= 235) { nS++; for (let c = 0; c < 3; c++) sMean[c] += src[i * 4 + c]; }
  }
  sMean = sMean.map(v => v / nS);
  // 3) targets sampled from the actual files: v3 head (same method) and the canon (character head region of the scene)
  const CGR = 222 / 252, CBR = (252 - 180) / 252; // canon/v3 skin ratios (their own, from the recorded canon skin), used only to FIND their skin pixels
  const v3s = await meanSkin(V3, { left: 300, top: 120, width: 420, height: 420 }, CGR, CBR, 235);
  const canS = await meanSkin(CANON, { left: 470, top: 790, width: 190, height: 170 }, CGR, CBR, 235);
  // the canon is the authority: use its sampled mean when the sample is large and plausible, else the recorded value (252,222,180)
  const recorded = [252, 222, 180];
  const plausible = canS.n > 2000 && canS.mean.every((v, i) => Math.abs(v - recorded[i]) < 6);
  const TARGET = plausible ? canS.mean : recorded;
  const GAIN = TARGET.map((v, i) => v / sMean[i]);
  // 4) apply: RGB gain weighted by mask, clamped to 0..255 (a gain above 1 must not wrap); alpha copied unchanged
  const out = Buffer.from(src);
  for (let i = 0; i < N; i++) { const m = maskW[i] / 255; if (m <= 0) continue; for (let c = 0; c < 3; c++) out[i * 4 + c] = Math.min(255, Math.max(0, Math.round(src[i * 4 + c] * (1 + m * (GAIN[c] - 1))))); }
  const outFile = O + 'character-01_pose-06-deadpan_skin-only_test.png';
  await sharp(out, { raw: { width: W, height: H, channels: 4 } }).png().toFile(outFile);
  await sharp(maskW, { raw: { width: W, height: H, channels: 1 } }).png().toFile(O + 'mask-skin-weight.png');
  // 5) verification: re-read the written PNG and compare with the source pixel by pixel (RGBA)
  const { data: re } = await sharp(outFile).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  let inside = 0, outside = 0, maxOut = 0, alphaDiff = 0, maskCount = 0;
  for (let i = 0; i < N; i++) {
    if (maskW[i] > 0) maskCount++;
    let d = 0; for (let c = 0; c < 4; c++) d = Math.max(d, Math.abs(re[i * 4 + c] - src[i * 4 + c]));
    if (re[i * 4 + 3] !== src[i * 4 + 3]) alphaDiff++;
    if (d > 0) { if (maskW[i] > 0) inside++; else { outside++; maxOut = Math.max(maxOut, d); } }
  }
  // extra check: pink mouth pixels (g/r < 0.75, r > 150, head region) must be unchanged
  let pinkTotal = 0, pinkChanged = 0;
  for (let i = 0; i < N; i++) { const r = src[i * 4], g = src[i * 4 + 1]; if (src[i * 4 + 3] > 0 && r > 150 && g / r < 0.75 && ((i / W) | 0) < H * 0.40 && (src[i*4+2] / r) > 0.45) { pinkTotal++; if (re[i * 4] !== src[i * 4] || re[i * 4 + 1] !== src[i * 4 + 1] || re[i * 4 + 2] !== src[i * 4 + 2]) pinkChanged++; } }
  // extra checks: near-white pixels (eye whites) and grey pixels (r~g~b, mid brightness, e.g. outline blends) must be unchanged
  let whiteChanged = 0, greyChanged = 0, whiteTotal = 0, greyTotal = 0;
  for (let i = 0; i < N; i++) { if (src[i*4+3] < 255) continue; const r = src[i*4], g = src[i*4+1], b = src[i*4+2], mx = Math.max(r,g,b), mn = Math.min(r,g,b); const ch = re[i*4]!==r || re[i*4+1]!==g || re[i*4+2]!==b; if (mn > 238) { whiteTotal++; if (ch) whiteChanged++; } else if (mx - mn < 22 && mx > 40 && mx < 200) { greyTotal++; if (ch) greyChanged++; } }
  let rowMin = 1e9, rowMax = -1, blackBelow = 0, blackBelowChanged = 0;
  for (let i = 0; i < N; i++) { const y = (i / W) | 0; const ch = re[i*4]!==src[i*4] || re[i*4+1]!==src[i*4+1] || re[i*4+2]!==src[i*4+2] || re[i*4+3]!==src[i*4+3]; if (ch) { rowMin = Math.min(rowMin, y); rowMax = Math.max(rowMax, y); } if (src[i*4+3] === 255 && y > H * 0.40 && Math.max(src[i*4], src[i*4+1], src[i*4+2]) < 60) { blackBelow++; if (ch) blackBelowChanged++; } }
  const prot = {near_black: [0, 0], sweater: [0, 0], shoes: [0, 0], warm_grey_changed: 0, cool_grey_changed: 0};
  for (let i = 0; i < N; i++) { if (!src[i*4+3]) continue; const r = src[i*4], g = src[i*4+1], b = src[i*4+2], mx = Math.max(r,g,b), mn = Math.min(r,g,b); const ch = r!==re[i*4] || g!==re[i*4+1] || b!==re[i*4+2] || src[i*4+3]!==re[i*4+3];
    if (mx < 40) { prot.near_black[0]++; if (ch) prot.near_black[1]++; }
    if (r > 150 && g > 50 && g < 120 && b < 60 && r - b > 110) { prot.sweater[0]++; if (ch) prot.sweater[1]++; }
    if (r > 110 && r < 190 && g > 70 && g < 115 && b > 40 && b < 85 && r - b > 45) { prot.shoes[0]++; if (ch) prot.shoes[1]++; }
    if (ch && mx - mn < 22) { if (r > b) prot.warm_grey_changed++; else prot.cool_grey_changed++; } }
  let rMean = [0, 0, 0], nR = 0;
  for (let i = 0; i < N; i++) if (maskW[i] === 255 && src[i * 4 + 3] === 255 && src[i * 4] >= 235) { nR++; for (let c = 0; c < 3; c++) rMean[c] += re[i * 4 + c]; }
  rMean = rMean.map(v => v / nR);
  const r1 = a => a.map(v => +v.toFixed(1));
  const report = {
    task: 'AP-80 pose 06 skin-only correction', method: 'v3 method: colour-ratio plateau mask + per-channel gain from sampled values; alpha unchanged',
    source: path.relative(D, SRC), output: path.relative(D, outFile), size: [W, H],
    sha256_before: before, sha256_after: { src: sha(SRC), v3: sha(V3), canon: sha(CANON) },
    sources_unchanged: before.src === sha(SRC) && before.v3 === sha(V3) && before.canon === sha(CANON),
    output_sha256: sha(outFile), source_seed_rgb: seed, ratios: { gr0: +GR0.toFixed(4), br0: +BR0.toFixed(4) },
    skin_mean_rgb: { original: r1(sMean), corrected: r1(rMean), canonical_sampled: r1(canS.mean), canonical_sampled_pixels: canS.n, canonical_recorded: recorded, target_used: r1(TARGET), approved_v3_sampled: r1(v3s.mean), v3_pixels: v3s.n, interior_pixels_used: nS },
    gain: GAIN.map(v => +v.toFixed(4)),
    skin_mask_pixel_count: maskCount, changed_pixels_inside_mask: inside, changed_pixels_outside_mask: outside, max_delta_outside_mask: maxOut, alpha_pixels_changed: alphaDiff, near_white_pixels_checked: whiteTotal, near_white_pixels_changed: whiteChanged, grey_pixels_checked: greyTotal, grey_pixels_changed: greyChanged, protected_checks: {near_black_checked: prot.near_black[0], near_black_changed: prot.near_black[1], sweater_checked: prot.sweater[0], sweater_changed: prot.sweater[1], shoes_checked: prot.shoes[0], shoes_changed: prot.shoes[1], grey_class_changed_warm_skin_blends: prot.warm_grey_changed, grey_class_changed_cool: prot.cool_grey_changed}, changed_row_range: [rowMin, rowMax], black_pixels_below_head: blackBelow, black_pixels_below_head_changed: blackBelowChanged, pink_mouth_pixels_checked: pinkTotal, pink_mouth_pixels_changed: pinkChanged,
  };
  fs.writeFileSync(O + 'correction-report.json', JSON.stringify(report, null, 1)); console.log(JSON.stringify(report, null, 1));
})();
