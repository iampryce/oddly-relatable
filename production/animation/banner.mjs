// The POV banner (owner decision 2026-11-20): a full-width white box across the top, rotated about -2 degrees, with
// the hook in a heavy condensed font (Anton, OFL) in normal case and colour emoji (Noto Color Emoji, OFL) drawn inline.
// Pure drawing: the caller registers the fonts (registerBannerFonts) and draws the layout on every frame.
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {BANNER, fontAt} from './banner-layout.mjs';

// the renderer's own canvas package, resolved like animator.mjs does
const HERE = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(HERE, '../../skills/directing-stickman-videos/package.json'));
const {GlobalFonts} = require('@napi-rs/canvas');

export {BANNER, layoutBanner} from './banner-layout.mjs';

export function registerBannerFonts(bannerFont, emojiFont) {
  const ok = {};
  if (bannerFont) ok.banner = !!GlobalFonts.registerFromPath(bannerFont, BANNER.family);
  if (emojiFont) ok.emoji = !!GlobalFonts.registerFromPath(emojiFont, BANNER.emoji);
  return ok;
}

// opts.flat (the band layout, 2026-11-24): drawn level, like a headline above the picture
export function drawBanner(ctx, L, opts) {
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  const cx = L.box.x + L.box.w / 2, cy = L.box.y + L.box.h / 2;
  ctx.translate(cx, cy); if (!opts?.flat) ctx.rotate(BANNER.angle);
  ctx.shadowColor = 'rgba(0,0,0,0.28)'; ctx.shadowBlur = 14; ctx.shadowOffsetY = 5;
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(-L.box.w / 2, -L.box.h / 2, L.box.w, L.box.h);
  ctx.shadowColor = 'transparent';
  ctx.fillStyle = '#111111'; ctx.font = fontAt(L.size); ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  const first = -((L.rows.length - 1) * L.lh) / 2;
  L.rows.forEach((r, i) => ctx.fillText(r, 0, first + i * L.lh + Math.round(L.size * 0.04)));
  ctx.restore();
}
