// AP-67: controlled corrections of Production Candidate 04 (concept code).
// READS production-candidate-04 (never modified) and WRITES ONLY NEW FILES into production-candidates/corrected/.
//   1) skin-only colour correction (soft colour-ratio mask, per-channel gain toward the canon's skin colour)
//   2) both hands replaced by native-resolution vector mitts (palm + three rounded finger bumps), matching the canon's mitt.
// Sweater, shoes, face drawing, proportions and outlines are NOT touched (verified by a pixel-diff outside the masks).
const path = require('path'), fs = require('fs'), crypto = require('crypto');
const sharp = require('module').createRequire(path.resolve(__dirname, '../../../skills/directing-stickman-videos/package.json'))('sharp');
const D = path.resolve(__dirname, '../lookdev-richenv') + '/', P = D + 'production-candidates/', O = P + 'corrected/';
fs.mkdirSync(O, { recursive: true });
const SRC = P + 'production-candidate-04-character-master.png';
const sha = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));

// ---- skin model (measured): candidate skin (253,232,205); canon skin (252,222,180)
const CAND_SKIN = [253, 232, 205], CANON_SKIN = [252, 222, 180];
const GAIN = CANON_SKIN.map((v, i) => v / CAND_SKIN[i]);            // ~ (0.996, 0.957, 0.878)
const GR0 = 232 / 253, BR0 = (253 - 205) / 253;                       // skin colour ratios g/r and (r-b)/r, preserved by blends with black
function skinWeight(r, g, b, y) {
  if (y > 570 || r < 70) return 0;                                     // head only; dark outline pixels excluded
  const gr = g / r, br = (r - b) / r;
  // plateau (full weight) over the skin's own noise, soft fall-off only where it blends into outline, eye white or background
  return clamp(2 - Math.abs(gr - GR0) / 0.025) * clamp(2 - Math.abs(br - BR0) / 0.05);
}

// ---- vector mitt (canon design): round palm + three rounded finger bumps fanned to one side, solid black
const ARM = { L: { cx: 348, y0: 868 }, R: { cx: 674, y0: 868 } };       // measured arm centre lines at the wrist cut
const PALM = { rx: 31, ry: 33, dy: 31 };                                // palm centre = (arm x, y0 + dy)
const FINGER_W = 24;                                                    // canon: thick finger bumps
const FINGERS = [{ a: -28, len: 52 }, { a: 4, len: 62 }, { a: 36, len: 50 }];
const ROT = 80;                                                         // rotate canon frame so fingers hang down (90 = straight down)
function mittSvgGroup(side) {
  const { cx, y0 } = ARM[side], px = cx, py = y0 + PALM.dy, m = side === 'R' ? -1 : 1;
  let g = `<ellipse cx="${px}" cy="${py}" rx="${PALM.rx}" ry="${PALM.ry}" fill="#000"/>`;
  for (const f of FINGERS) {
    const deg = ROT + f.a, rad = deg * Math.PI / 180;
    const dx = Math.cos(rad) * m, dy = Math.sin(rad);                   // mirrored for the right hand
    const bx = px + dx * 14, by = py + dy * 14, tx = px + dx * f.len, ty = py + dy * f.len;
    g += `<line x1="${bx.toFixed(1)}" y1="${by.toFixed(1)}" x2="${tx.toFixed(1)}" y2="${ty.toFixed(1)}" stroke="#000" stroke-width="${FINGER_W}" stroke-linecap="round"/>`;
  }
  return g;
}
const W = 1024, H = 1536;
const handsSvg = (scale) => `<svg xmlns="http://www.w3.org/2000/svg" width="${W * scale}" height="${H * scale}" viewBox="0 0 ${W} ${H}">${mittSvgGroup('L')}${mittSvgGroup('R')}</svg>`;
// old-hook removal windows (hook pixels only; sweater hem outline and arms above the wrist are outside)
const inLeftWin = (x, y) => y >= 868 && y <= 962 && x >= 296 && x <= (y < 880 ? 381 : 388);
const inRightWin = (x, y) => y >= 868 && y <= 962 && x <= 716 && x >= (y < 890 ? 642 : 628);

(async () => {
  const before = sha(SRC);
  const { data: src } = await sharp(SRC).removeAlpha().raw().toBuffer({ resolveWithObject: true });
  const skinOnly = Buffer.from(src), maskSkin = Buffer.alloc(W * H);
  let sumB = [0, 0, 0], sumA = [0, 0, 0], nS = 0;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const o = (y * W + x) * 3, w = skinWeight(src[o], src[o + 1], src[o + 2], y);
    if (w <= 0) continue;
    maskSkin[y * W + x] = Math.round(w * 255);
    skinOnly[o + 1] = Math.round(src[o + 1] * (1 + w * (GAIN[1] - 1)));
    skinOnly[o + 2] = Math.round(src[o + 2] * (1 + w * (GAIN[2] - 1)));
    skinOnly[o] = Math.round(src[o] * (1 + w * (GAIN[0] - 1)));
    if (w > 0.95) { nS++; for (let c = 0; c < 3; c++) { sumB[c] += src[o + c]; sumA[c] += skinOnly[o + c]; } }
  }
  const mean = (s) => s.map(v => Math.round(v / nS));
  // ---- hands: erase old hooks with the local background colour, then composite the vector mitts (4x supersampled, then downscaled)
  const ring = []; for (let y = 880; y <= 940; y += 4) for (const x of [292, 294, 720, 722]) { const o = (y * W + x) * 3; ring.push([src[o], src[o + 1], src[o + 2]]); }
  const bg = [0, 1, 2].map(c => Math.round(ring.map(p => p[c]).sort((a, b) => a - b)[Math.floor(ring.length / 2)]));
  const handsOnly = Buffer.from(src), both = Buffer.from(skinOnly), winMask = Buffer.alloc(W * H);
  for (let y = 860; y < 970; y++) for (let x = 280; x < 730; x++) {
    if (!(inLeftWin(x, y) || inRightWin(x, y))) continue;
    const o = (y * W + x) * 3; winMask[y * W + x] = 255;
    for (let c = 0; c < 3; c++) { handsOnly[o + c] = bg[c]; both[o + c] = bg[c]; }
  }
  const mitt = await sharp(Buffer.from(handsSvg(4))).resize(W, H, { kernel: 'lanczos3' }).ensureAlpha().raw().toBuffer(); // premult-free RGBA, black with AA alpha
  for (let i = 0; i < W * H; i++) {
    const a = mitt[i * 4 + 3] / 255; if (a <= 0) continue;
    for (let c = 0; c < 3; c++) { handsOnly[i * 3 + c] = Math.round(handsOnly[i * 3 + c] * (1 - a)); both[i * 3 + c] = Math.round(both[i * 3 + c] * (1 - a)); }
  }
  const savePng = (buf, name, ch = 3) => sharp(buf, { raw: { width: W, height: H, channels: ch } }).png().toFile(O + name);
  await savePng(skinOnly, 'candidate-04_corrected-skin-only.png');
  await savePng(handsOnly, 'candidate-04_corrected-hands-only.png');
  await savePng(both, 'candidate-04_corrected-v2.png');
  await savePng(maskSkin, 'mask-skin-weight.png', 1);
  await savePng(winMask, 'mask-old-hand-windows.png', 1);
  fs.writeFileSync(O + 'hands-vector.svg', handsSvg(1));
  // ---- verification: nothing outside the masks may change
  let outside = 0, maxOutside = 0, changedSkin = 0, changedWin = 0;
  for (let i = 0; i < W * H; i++) {
    const inSkin = maskSkin[i] > 0, inWin = winMask[i] > 0, inMitt = mitt[i * 4 + 3] > 0;
    let d = 0; for (let c = 0; c < 3; c++) d = Math.max(d, Math.abs(both[i * 3 + c] - src[i * 3 + c]));
    if (d > 0) { if (!inSkin && !inWin && !inMitt) { outside++; maxOutside = Math.max(maxOutside, d); } else if (inSkin) changedSkin++; else changedWin++; }
  }
  // amplified diff image
  const diff = Buffer.alloc(W * H * 3);
  for (let i = 0; i < W * H * 3; i++) diff[i] = clamp(Math.abs(both[i] - src[i]) * 4, 0, 255);
  await savePng(diff, 'diff-original-vs-v2-x4.png');
  // measure corrected skin vs canon
  const skinMeanBefore = mean(sumB), skinMeanAfter = mean(sumA);
  const report = {
    source_sha256_before: before, source_sha256_after: sha(SRC), source_unchanged: before === sha(SRC),
    gain: GAIN.map(v => +v.toFixed(4)), backgroundFill: bg,
    skin_interior_mean: { before: skinMeanBefore, after: skinMeanAfter, canon: CANON_SKIN, skinPixelsUsed: nS },
    changed_pixels_outside_masks: outside, max_delta_outside: maxOutside, changed_in_skin_mask: changedSkin, changed_in_hand_zone: changedWin,
    outputs: Object.fromEntries(['candidate-04_corrected-skin-only.png', 'candidate-04_corrected-hands-only.png', 'candidate-04_corrected-v2.png'].map(f => [f, sha(O + f)])),
  };
  fs.writeFileSync(O + 'correction-report.json', JSON.stringify(report, null, 1));
  console.log(JSON.stringify(report, null, 1));
})();
