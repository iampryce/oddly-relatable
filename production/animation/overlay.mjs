// Overlay pictures for the assembled episode (studio-app/api/oddstudio/assembly.py): the POV banner and one picture
// per dialogue line (a caption in the lower third, or a speech bubble near the top), each a transparent PNG of the
// whole frame. FFmpeg lays them over the video at each line's time. Same fonts and banner layout as the episode
// renderer (render-acting.mjs / banner.mjs); bubbles cannot point at a head here (the clips are pictures), so they sit
// under the banner with the tail pointing down.
//
// Usage: node overlay.mjs spec.json
//   spec: {width, height, hook, band, mode: "captions" | "bubbles" | "none", banner_font, emoji_font, font,
//          lines: [{text}], out: folder}
// Prints one JSON line: {banner: path | null, lines: [path, ...]}
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {registerBannerFonts, layoutBanner, drawBanner} from './banner.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(HERE, '../../skills/directing-stickman-videos/package.json'));
const {createCanvas, GlobalFonts} = require('@napi-rs/canvas');

const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const W = spec.width, H = spec.height, OUT = spec.out;
fs.mkdirSync(OUT, {recursive: true});
if (spec.font) GlobalFonts.registerFromPath(spec.font, 'Sub');
const BAND = !!spec.band && H > W;
const VH = BAND ? Math.round(W * 9 / 16) : H, OY = BAND ? Math.round((H - VH) / 2) : 0;
const K = Math.max(W, H) / 1920;                 // the renderer's sizes are for a 1920-pixel long side

function wrap(ctx, text, maxW) {
  const rows = []; let cur = '';
  for (const w of String(text).split(/\s+/).filter(Boolean)) {
    const nx = cur ? cur + ' ' + w : w;
    if (ctx.measureText(nx).width > maxW && cur) { rows.push(cur); cur = w; } else cur = nx;
  }
  if (cur) rows.push(cur);
  return rows;
}

function save(canvas, name) {
  const f = path.join(OUT, name);
  fs.writeFileSync(f, canvas.toBuffer('image/png'));
  return f;
}

let bannerBottom = Math.round(40 * K);
let banner = null;
if (spec.hook) {
  const ok = registerBannerFonts(spec.banner_font, spec.emoji_font);
  if (ok.banner) {
    const c = createCanvas(W, H), ctx = c.getContext('2d');
    const L = layoutBanner(createCanvas(W, 400).getContext('2d'), spec.hook, W);
    drawBanner(ctx, L, BAND ? {flat: true} : undefined);
    bannerBottom = L.bottom;
    banner = save(c, 'banner.png');
  }
}

function caption(text) {
  const c = createCanvas(W, H), ctx = c.getContext('2d');
  const size = Math.round(52 * K * (H > W ? 1 : 1.25));
  ctx.font = `700 ${size}px Sub`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.lineJoin = 'round';
  const rows = wrap(ctx, text, W * 0.84);
  const lh = Math.round(size * 1.23);
  // the lower third, clear of the banner at the top and of the platform's buttons at the bottom; in the band, under it
  const y0 = BAND ? OY + VH + Math.round(80 * K) : Math.min(H * 0.70, H - Math.round(60 * K) - rows.length * lh);
  rows.forEach((r, i) => {
    const y = y0 + i * lh;
    ctx.lineWidth = Math.max(4, Math.round(10 * K)); ctx.strokeStyle = '#111'; ctx.strokeText(r, W / 2, y);
    ctx.fillStyle = '#fff'; ctx.fillText(r, W / 2, y);
  });
  return c;
}

function bubble(text) {
  const c = createCanvas(W, H), ctx = c.getContext('2d');
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  let size = Math.round(44 * K * 1.3), rows;
  for (; size >= Math.round(26 * K); size -= 2) {
    ctx.font = `800 ${size}px Sub`;
    rows = wrap(ctx, text.toUpperCase(), W * 0.6);
    if (rows.length <= 4) break;
  }
  const lh = size * 1.18, bw = Math.max(...rows.map(r => ctx.measureText(r).width)) + 64 * K, bh = rows.length * lh + 40 * K;
  const bx = (W - bw) / 2, by = (BAND ? OY : bannerBottom) + 14 * K;
  const tx = W / 2;
  ctx.fillStyle = '#fff'; ctx.strokeStyle = '#111'; ctx.lineWidth = Math.max(3, 6 * K); ctx.lineJoin = 'round';
  ctx.beginPath(); ctx.roundRect(bx, by, bw, bh, Math.min(bh / 2.2, 60 * K)); ctx.fill(); ctx.stroke();
  const base = [[tx - 20 * K, by + bh - 3], [tx + 20 * K, by + bh - 3]], tip = [tx + 10 * K, by + bh + 34 * K];
  ctx.beginPath(); ctx.moveTo(...base[0]); ctx.lineTo(...tip); ctx.lineTo(...base[1]); ctx.fill(); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(...base[0]); ctx.lineTo(...base[1]); ctx.lineWidth = Math.max(4, 8 * K); ctx.strokeStyle = '#fff'; ctx.stroke();
  ctx.fillStyle = '#111';
  rows.forEach((r, i) => ctx.fillText(r, W / 2, by + 20 * K + lh / 2 + i * lh));
  return c;
}

const lines = [];
if (spec.mode === 'captions' || spec.mode === 'bubbles') {
  (spec.lines || []).forEach((ln, i) => {
    const c = spec.mode === 'captions' ? caption(ln.text) : bubble(ln.text);
    lines.push(save(c, `line-${String(i).padStart(4, '0')}.png`));
  });
}
console.log(JSON.stringify({banner, lines}));
