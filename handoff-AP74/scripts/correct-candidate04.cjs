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
// v3: smaller palm; three rounded fingers that CURVE and sweep to one side (canon mitt), no points
const PALM = { rx: 25, ry: 28, dy: 26 };                                // palm centre = (arm x, y0 + dy)
const FINGER_W = 19;                                                    // finger thickness (canon: about 0.35 to 0.4 of the palm width)
// canon frame: +x = sweep direction; a = fan angle (deg), len = tip-centre distance from the palm centre, curl = sideways curl of the tip (+ = clockwise)
const FINGERS = [{ a: -26, len: 40, curl: 9 }, { a: 2, len: 50, curl: 11 }, { a: 30, len: 39, curl: 8 }];
const ROT = 55;                                                         // rotate the canon frame so the fingers sweep inward and downward
function mittSvgGroup(side) {
  const { cx, y0 } = ARM[side], px = cx, py = y0 + PALM.dy, m = side === 'R' ? -1 : 1;
  const T = (u, v) => { const r = ROT * Math.PI / 180, x = u * Math.cos(r) - v * Math.sin(r), y = u * Math.sin(r) + v * Math.cos(r); return [px + m * x, py + y]; }; // canon-frame (u,v) -> image
  let g = `<ellipse cx="${px}" cy="${py}" rx="${PALM.rx}" ry="${PALM.ry}" fill="#000"/>`;
  for (const f of FINGERS) {
    const a = f.a * Math.PI / 180, d = [Math.cos(a), Math.sin(a)], n = [-Math.sin(a), Math.cos(a)];
    const p0 = T(d[0] * 10, d[1] * 10);
    const pc = T(d[0] * f.len * 0.55 - n[0] * 3, d[1] * f.len * 0.55 - n[1] * 3);
    const p1 = T(d[0] * f.len + n[0] * f.curl, d[1] * f.len + n[1] * f.curl);
    g += `<path d="M${p0[0].toFixed(1)} ${p0[1].toFixed(1)} Q${pc[0].toFixed(1)} ${pc[1].toFixed(1)} ${p1[0].toFixed(1)} ${p1[1].toFixed(1)}" fill="none" stroke="#000" stroke-width="${FINGER_W}" stroke-linecap="round" stroke-linejoin="round"/>`;
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
  await savePng(both, 'candidate-04_corrected-v3.png');
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
  await savePng(diff, 'diff-original-vs-v3-x4.png');
  // measure corrected skin vs canon
  const skinMeanBefore = mean(sumB), skinMeanAfter = mean(sumA);
  const report = {
    source_sha256_before: before, source_sha256_after: sha(SRC), source_unchanged: before === sha(SRC),
    gain: GAIN.map(v => +v.toFixed(4)), backgroundFill: bg,
    skin_interior_mean: { before: skinMeanBefore, after: skinMeanAfter, canon: CANON_SKIN, skinPixelsUsed: nS },
    changed_pixels_outside_masks: outside, max_delta_outside: maxOutside, changed_in_skin_mask: changedSkin, changed_in_hand_zone: changedWin,
    outputs: Object.fromEntries(['candidate-04_corrected-skin-only.png', 'candidate-04_corrected-hands-only.png', 'candidate-04_corrected-v3.png'].map(f => [f, sha(O + f)])),
  };
  fs.writeFileSync(O + 'correction-report.json', JSON.stringify(report, null, 1));
  console.log(JSON.stringify(report, null, 1));
})();
