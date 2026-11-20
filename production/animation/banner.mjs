// The POV banner (owner decision 2026-11-20): a full-width white box across the top, rotated about -2 degrees, with
// the hook in a heavy condensed font (Anton, OFL) in normal case and colour emoji (Noto Color Emoji, OFL) drawn inline.
// Pure drawing: the caller registers the fonts (registerBannerFonts) and draws the layout on every frame.
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';

// the renderer's own canvas package, resolved like animator.mjs does
const HERE = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(HERE, '../../skills/directing-stickman-videos/package.json'));
const {GlobalFonts} = require('@napi-rs/canvas');

export const BANNER = Object.freeze({margin: 34, top: 96, pad: 26, maxSize: 86, minSize: 52, maxRows: 2, angle: -2 * Math.PI / 180,
  family: 'Banner', emoji: 'Noto Color Emoji'});

export function registerBannerFonts(bannerFont, emojiFont) {
  const ok = {};
  if (bannerFont) ok.banner = !!GlobalFonts.registerFromPath(bannerFont, BANNER.family);
  if (emojiFont) ok.emoji = !!GlobalFonts.registerFromPath(emojiFont, BANNER.emoji);
  return ok;
}

const fontAt = size => `${size}px ${BANNER.family}, "${BANNER.emoji}"`;

function wrap(ctx, text, maxW) {
  const rows = []; let cur = '';
  for (const w of text.split(/\s+/).filter(Boolean)) {
    const nx = cur ? cur + ' ' + w : w;
    if (ctx.measureText(nx).width > maxW && cur) { rows.push(cur); cur = w; } else cur = nx;
  }
  if (cur) rows.push(cur);
  return rows;
}

// Largest font size (maxSize down to minSize) at which the hook fits in maxRows; the box spans the frame's width.
export function layoutBanner(ctx, text, W) {
  const boxW = W - 2 * BANNER.margin, inner = boxW - 2 * BANNER.pad;
  let size = BANNER.maxSize, rows;
  for (; size >= BANNER.minSize; size -= 4) {
    ctx.font = fontAt(size);
    rows = wrap(ctx, text, inner);
    if (rows.length <= BANNER.maxRows) break;
  }
  if (rows.length > BANNER.maxRows) {                      // still too long at the smallest size: cut with an ellipsis
    rows = rows.slice(0, BANNER.maxRows);
    ctx.font = fontAt(size = BANNER.minSize);
    while (rows[rows.length - 1].length > 1 && ctx.measureText(rows[rows.length - 1] + '…').width > inner) rows[rows.length - 1] = rows[rows.length - 1].slice(0, -1);
    rows[rows.length - 1] += '…';
  }
  const lh = Math.round(size * 1.12), boxH = rows.length * lh + 2 * BANNER.pad - Math.round(size * 0.12);
  const box = {x: BANNER.margin, y: BANNER.top, w: boxW, h: boxH};
  // the lowest screen point of the rotated box (bubbles stay below it)
  const bottom = Math.ceil(box.y + box.h + Math.abs(Math.sin(BANNER.angle)) * box.w / 2 + 6);
  return {rows, size, lh, box, bottom};
}

export function drawBanner(ctx, L) {
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  const cx = L.box.x + L.box.w / 2, cy = L.box.y + L.box.h / 2;
  ctx.translate(cx, cy); ctx.rotate(BANNER.angle);
  ctx.shadowColor = 'rgba(0,0,0,0.28)'; ctx.shadowBlur = 14; ctx.shadowOffsetY = 5;
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(-L.box.w / 2, -L.box.h / 2, L.box.w, L.box.h);
  ctx.shadowColor = 'transparent';
  ctx.fillStyle = '#111111'; ctx.font = fontAt(L.size); ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  const first = -((L.rows.length - 1) * L.lh) / 2;
  L.rows.forEach((r, i) => ctx.fillText(r, 0, first + i * L.lh + Math.round(L.size * 0.04)));
  ctx.restore();
}
