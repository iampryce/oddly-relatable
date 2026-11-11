'use strict';
// AP-58: extract the six existing poses of Canonical Character 01 from the approved consistency-test sheet.
// LOCAL IMAGE PROCESSING ONLY: no generation, no redrawing, no recolouring. The source image is only READ.
// Method: the sheet's background is a flat grey (measured 209,209,209, std 0.7). Pixels within a small colour distance
// of it become transparent; only the thin anti-aliased edge band is converted to a clean dark fringe with partial alpha
// (the outline is black, so an edge pixel is a black/grey blend). Interior pixels (eye whites, skin, sweater, phone) are untouched.
// Uses the already-installed `sharp`. Usage: node bible/concepts/src/extract-poses.cjs
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const {createRequire} = require('module');
const ROOT = path.resolve(__dirname, '..', '..', '..');
const sharp = createRequire(path.join(ROOT, 'skills/directing-stickman-videos/package.json'))('sharp');
const DIR = path.join(ROOT, 'bible/concepts/lookdev-richenv');
const SRC = path.join(DIR, 'lookdev-character-test-02.png');
const OUT = path.join(DIR, 'extracted');
const NAMES = ['01-neutral', '02-worried-phone', '03-shocked-frozen', '04-laughing', '05-pleading', '06-deadpan-arms-crossed'];
const BG = [209, 209, 209], BG_T = 12, EDGE_PX = 4, MIN_AREA = 400, FRINGE = [24, 24, 26], BLACK = 24;

(async () => {
  if (fs.existsSync(OUT) && fs.readdirSync(OUT).some(n => !n.startsWith('_v'))) throw new Error('extracted/ already has outputs; not overwriting'); // the _vN-*-defect folders hold earlier, defective attempts (kept)
  const sha = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
  const srcHash = sha(SRC);
  const {data, info} = await sharp(SRC).removeAlpha().raw().toBuffer({resolveWithObject: true});
  const W = info.width, H = info.height, N = W * H;
  const dist = new Float32Array(N);
  for (let i = 0; i < N; i++) { const o = i * 3; dist[i] = Math.hypot(data[o] - BG[0], data[o + 1] - BG[1], data[o + 2] - BG[2]); }
  // 1. OUTSIDE background: flood fill from the image border through background-like pixels only. Pale pixels inside the
  //    figure (eye whites, highlights) are never reached, so they can never be removed (v2 of this script wrongly removed some).
  const bg = new Uint8Array(N), q = new Int32Array(N); let qs = 0;
  const push = i => { if (!bg[i] && dist[i] <= BG_T) { bg[i] = 1; q[qs++] = i; } };
  for (let x = 0; x < W; x++) { push(x); push((H - 1) * W + x); } for (let y = 0; y < H; y++) { push(y * W); push(y * W + W - 1); }
  while (qs) { const i = q[--qs], x = i % W, y = (i / W) | 0; if (x > 0) push(i - 1); if (x < W - 1) push(i + 1); if (y > 0) push(i - W); if (y < H - 1) push(i + W); }
  // 2. ENCLOSED pockets of (almost exactly) the background grey, e.g. the gap between crossed arms and the torso: large, uniform, tight threshold
  const seenP = new Uint8Array(N), EXACT_T = 5, POCKET_MIN = 120; let pockets = 0;
  for (let s = 0; s < N; s++) {
    if (bg[s] || seenP[s] || dist[s] > EXACT_T) continue;
    const comp = []; let sp = 0; q[sp++] = s; seenP[s] = 1;
    while (sp) { const i = q[--sp]; comp.push(i); const x = i % W, y = (i / W) | 0; for (const j of [x > 0 ? i - 1 : -1, x < W - 1 ? i + 1 : -1, y > 0 ? i - W : -1, y < H - 1 ? i + W : -1]) if (j >= 0 && !bg[j] && !seenP[j] && dist[j] <= EXACT_T) { seenP[j] = 1; q[sp++] = j; } }
    if (comp.length >= POCKET_MIN) { for (const i of comp) bg[i] = 1; pockets++; }
  }
  // 3. SMALL enclosed grey/white slivers (between a limb and the torso, between fingers): greyish pixels forming a SMALL enclosed
  //    component. Eye whites are far larger (thousands of px), so they are never matched, and pale shading pixels inside an eye belong to
  //    the large eye component, not to a sliver.
  const seenS = new Uint8Array(N), SLIVER_MAX = 800; let slivers = 0;
  const greyish = i => { const o = i * 3, r = data[o], g = data[o + 1], b = data[o + 2], mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (r + g + b) / 3; return mx - mn <= 14 && l >= 195 && l <= 232; };
  for (let s = 0; s < N; s++) {
    if (bg[s] || seenS[s] || !greyish(s)) continue;
    const comp = []; let sp = 0; q[sp++] = s; seenS[s] = 1; let tooBig = false;
    while (sp) { const i = q[--sp]; comp.push(i); if (comp.length > SLIVER_MAX) tooBig = true; const x = i % W, y = (i / W) | 0; for (const j of [x > 0 ? i - 1 : -1, x < W - 1 ? i + 1 : -1, y > 0 ? i - W : -1, y < H - 1 ? i + W : -1]) if (j >= 0 && !bg[j] && !seenS[j] && greyish(j)) { seenS[j] = 1; q[sp++] = j; } }
    if (!tooBig) {
      // ring test: grey shading INSIDE an eye is bordered by eye-white pixels; a background sliver between a limb and the torso is not
      const inC = new Set(comp); let ring = 0, whites = 0;
      for (const i of comp) { const x = i % W, y = (i / W) | 0; for (const j of [x > 0 ? i - 1 : -1, x < W - 1 ? i + 1 : -1, y > 0 ? i - W : -1, y < H - 1 ? i + W : -1]) { if (j < 0 || inC.has(j)) continue; ring++; const o = j * 3, r = data[o], g = data[o + 1], b = data[o + 2]; if ((r + g + b) / 3 >= 236 && Math.max(r, g, b) - Math.min(r, g, b) <= 16) whites++; } }
      if (ring === 0 || whites / ring < 0.15) { for (const i of comp) bg[i] = 1; slivers++; }
    }
  }
  console.log('enclosed background pockets removed:', pockets, '| small grey slivers removed:', slivers);
  // edge band = pixels within EDGE_PX of the background
  let near = bg.slice();
  for (let it = 0; it < EDGE_PX; it++) { const nx = near.slice(); for (let y = 1; y < H - 1; y++) for (let x = 1; x < W - 1; x++) { const i = y * W + x; if (near[i]) continue; if (near[i - 1] || near[i + 1] || near[i - W] || near[i + W] || near[i - W - 1] || near[i - W + 1] || near[i + W - 1] || near[i + W + 1]) nx[i] = 1; } near = nx; }
  const rgba = Buffer.alloc(N * 4);
  const bgLuma = (BG[0] + BG[1] + BG[2]) / 3;
  for (let i = 0; i < N; i++) {
    const o = i * 3, p = i * 4; let a = 255, r = data[o], g = data[o + 1], b = data[o + 2];
    if (bg[i]) a = 0;
    else if (near[i]) {
      const mx = Math.max(r, g, b), mn = Math.min(r, g, b), luma = (r + g + b) / 3;
      if (mx - mn <= 14) {
        if (luma >= bgLuma - 12) a = 0; // bright anti-aliasing 'ringing' just outside the outline: becomes transparent (v1 kept it as a white halo)
        else { a = Math.round(255 * Math.max(0, Math.min(1, (bgLuma - luma) / (bgLuma - BLACK)))); [r, g, b] = FRINGE; } // grey/black blend on the outline edge; true black stays fully opaque
      }
    }
    rgba[p] = r; rgba[p + 1] = g; rgba[p + 2] = b; rgba[p + 3] = a;
  }
  // connected components (8-neighbour) on alpha > 50 to drop specks and group pieces per cell
  const lab = new Int32Array(N); let nl = 0; const comps = [];
  const stack = new Int32Array(N);
  for (let s = 0; s < N; s++) {
    if (lab[s] || rgba[s * 4 + 3] <= 50) continue;
    nl++; let sp = 0, area = 0, sx = 0, sy = 0, x0 = W, y0 = H, x1 = 0, y1 = 0; stack[sp++] = s; lab[s] = nl;
    while (sp) { const i = stack[--sp]; const x = i % W, y = (i / W) | 0; area++; sx += x; sy += y; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) { if (!dx && !dy) continue; const nx = x + dx, ny = y + dy; if (nx < 0 || ny < 0 || nx >= W || ny >= H) continue; const j = ny * W + nx; if (!lab[j] && rgba[j * 4 + 3] > 50) { lab[j] = nl; stack[sp++] = j; } } }
    comps.push({id: nl, area, cx: sx / area, cy: sy / area, x0, y0, x1, y1});
  }
  const kept = comps.filter(c => c.area >= MIN_AREA), dropped = comps.length - kept.length;
  const cells = Array.from({length: 6}, () => []);
  for (const c of kept) { const col = Math.min(2, Math.floor(c.cx / (W / 3))), row = Math.min(1, Math.floor(c.cy / (H / 2))); cells[row * 3 + col].push(c); }
  fs.mkdirSync(OUT, {recursive: true});
  const manifest = {schema: 'canonical-character-01-poses-v1', source: 'lookdev-character-test-02.png', source_sha256: srcHash, method: 'local flat-background removal (distance threshold + edge fringe); no generation, no redrawing', background_rgb: BG, threshold: BG_T, components_dropped_as_specks: dropped, poses: []};
  const PAD = 10;
  for (let k = 0; k < 6; k++) {
    const cs = cells[k]; if (!cs.length) throw new Error('no component found for cell ' + k);
    const ids = new Set(cs.map(c => c.id));
    const x0 = Math.max(0, Math.min(...cs.map(c => c.x0)) - PAD), y0 = Math.max(0, Math.min(...cs.map(c => c.y0)) - PAD), x1 = Math.min(W - 1, Math.max(...cs.map(c => c.x1)) + PAD), y1 = Math.min(H - 1, Math.max(...cs.map(c => c.y1)) + PAD);
    const w = x1 - x0 + 1, h = y1 - y0 + 1, out = Buffer.alloc(w * h * 4);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const si = (y0 + y) * W + (x0 + x), di = (y * w + x) * 4, sp4 = si * 4;
      // keep only pixels that belong to this pose's components, plus the partial-alpha fringe directly adjacent to them
      const belongs = ids.has(lab[si]) || (rgba[sp4 + 3] > 0 && rgba[sp4 + 3] <= 50 && [-1, 1, -W, W].some(d => ids.has(lab[si + d])));
      if (belongs) { out[di] = rgba[sp4]; out[di + 1] = rgba[sp4 + 1]; out[di + 2] = rgba[sp4 + 2]; out[di + 3] = rgba[sp4 + 3]; } }
    // opaque bounding box and feet anchor (centre x of the lowest 14 px of the figure)
    let ox0 = w, oy0 = h, ox1 = 0, oy1 = 0; for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (out[(y * w + x) * 4 + 3] > 50) { if (x < ox0) ox0 = x; if (x > ox1) ox1 = x; if (y < oy0) oy0 = y; if (y > oy1) oy1 = y; }
    let fx = 0, fn = 0; for (let y = oy1 - 13; y <= oy1; y++) for (let x = 0; x < w; x++) if (out[(y * w + x) * 4 + 3] > 50) { fx += x; fn++; }
    const file = `canonical-character-01_${NAMES[k]}.png`;
    await sharp(out, {raw: {width: w, height: h, channels: 4}}).png().toFile(path.join(OUT, file));
    manifest.poses.push({index: k + 1, name: NAMES[k], file, sha256: sha(path.join(OUT, file)), width: w, height: h, crop_in_sheet: {x: x0, y: y0}, figure_bbox_in_file: {x: ox0, y: oy0, w: ox1 - ox0 + 1, h: oy1 - oy0 + 1}, feet_anchor_in_file: {x: Math.round(fx / fn), y: oy1}});
  }
  fs.writeFileSync(path.join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
  console.log('extracted', manifest.poses.length, 'poses; specks dropped:', dropped);
  for (const p of manifest.poses) console.log(p.file, p.width + 'x' + p.height, 'feet', JSON.stringify(p.feet_anchor_in_file));
  // verification contact sheet: each pose over a checkerboard, a warm brown and a dark teal (halos/fringes show against contrasting grounds)
  const CELLW = 300, CELLH = 330, GRIDS = [['checker', null], ['warm', {r: 122, g: 75, b: 42}], ['dark', {r: 22, g: 52, b: 59}]];
  const comp = [];
  const checker = (w, h) => { const b = Buffer.alloc(w * h * 3); for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const v = ((x >> 3) + (y >> 3)) & 1 ? 235 : 190; const o = (y * w + x) * 3; b[o] = b[o + 1] = b[o + 2] = v; } return b; };
  const SW = CELLW * 6, SH = CELLH * 3 + 40;
  const base = Buffer.alloc(SW * SH * 3, 255);
  const baseImg = sharp(base, {raw: {width: SW, height: SH, channels: 3}});
  for (let r = 0; r < 3; r++) for (let k = 0; k < 6; k++) {
    const p = manifest.poses[k]; const tile = r === 0 ? sharp(checker(CELLW, CELLH), {raw: {width: CELLW, height: CELLH, channels: 3}}) : sharp({create: {width: CELLW, height: CELLH, channels: 3, background: GRIDS[r][1]}});
    const fig = await sharp(path.join(OUT, p.file)).resize({height: CELLH - 20, width: CELLW - 20, fit: 'inside'}).png().toBuffer();
    const fm = await sharp(fig).metadata();
    const t = await tile.composite([{input: fig, left: Math.round((CELLW - fm.width) / 2), top: CELLH - 10 - fm.height}]).png().toBuffer();
    comp.push({input: t, left: k * CELLW, top: 40 + r * CELLH});
  }
  const title = Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${SW}" height="40"><rect width="100%" height="100%" fill="#fff"/><text x="12" y="27" font-family="Arial" font-size="22" font-weight="700" fill="#222">Canonical Character 01: six extracted poses (rows: checkerboard / warm brown / dark teal; 01 neutral, 02 worried-phone, 03 shocked, 04 laughing, 05 pleading, 06 deadpan)</text></svg>`);
  comp.unshift({input: title, left: 0, top: 0});
  await baseImg.composite(comp).png().toFile(path.join(OUT, 'contact-sheet-extracted-poses.png'));
  console.log('contact sheet written');
})().catch(e => { console.error(e); process.exit(1); });
