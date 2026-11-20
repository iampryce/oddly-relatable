// POV banner text layout: pure (only ctx.font and ctx.measureText), so it is unit-tested without a canvas package.
// Owner rules (2026-11-20): an emoji never sits alone on a line (it stays attached to the word before it), and when a
// long hook is cut with "…", its closing emoji is kept after the ellipsis.

export const BANNER = Object.freeze({margin: 34, top: 96, pad: 26, maxSize: 86, minSize: 52, maxRows: 2, angle: -2 * Math.PI / 180,
  family: 'Banner', emoji: 'Noto Color Emoji'});

export const fontAt = size => `${size}px ${BANNER.family}, "${BANNER.emoji}"`;

// A token made only of emoji (and their joiners / variation selectors / skin tones), no letters or digits.
const EMOJI_ONLY = /^(?:\p{Extended_Pictographic}|\p{Emoji_Modifier}|\p{Regional_Indicator}|‍|️|⃣)+$/u;
export const isEmojiToken = t => EMOJI_ONLY.test(t);

// Words to wrap, with every emoji-only token glued to the word before it ("met 😂🍆" is one unit; a leading emoji
// joins the first word), so line breaks never leave an emoji on its own.
export function hookUnits(text) {
  const units = [];
  let lead = '';
  for (const tok of String(text || '').split(/\s+/).filter(Boolean)) {
    if (isEmojiToken(tok)) {
      if (units.length) units[units.length - 1] += ' ' + tok; else lead = lead ? lead + ' ' + tok : tok;
    } else {
      units.push(lead ? lead + ' ' + tok : tok);
      lead = '';
    }
  }
  if (lead) units.push(lead);      // a hook made only of emoji
  return units;
}

// The emoji the hook ends with ("" when it ends on a word).
export function trailingEmoji(text) {
  const toks = String(text || '').trim().split(/\s+/).filter(Boolean);
  const tail = [];
  while (toks.length && isEmojiToken(toks[toks.length - 1])) tail.unshift(toks.pop());
  return toks.length ? tail.join(' ') : '';
}

export function wrapUnits(ctx, units, maxW) {
  const rows = []; let cur = '';
  for (const u of units) {
    const nx = cur ? cur + ' ' + u : u;
    if (ctx.measureText(nx).width > maxW && cur) { rows.push(cur); cur = u; } else cur = nx;
  }
  if (cur) rows.push(cur);
  return rows;
}

// Cut the last row so that row + "…" (+ " " + the hook's closing emoji) fits; characters are removed whole
// (never half an emoji), the cut backs up to the last whole word, and a trailing space or comma is dropped.
export function cutWithEllipsis(ctx, row, inner, emoji = '') {
  const tail = '…' + (emoji ? ' ' + emoji : '');
  let chars = Array.from(row);
  if (emoji && row.endsWith(emoji)) chars = Array.from(row.slice(0, -emoji.length).trimEnd());   // never twice
  const orig = chars.slice();
  while (chars.length > 1 && ctx.measureText(chars.join('') + tail).width > inner) chars.pop();
  // a cut inside a word backs up to the last whole word (when that keeps most of the row): "it a…" -> "it…"
  const sp = chars.lastIndexOf(' '), insideWord = chars.length < orig.length && orig[chars.length] !== ' ';
  if (insideWord && sp > chars.length / 2) chars = chars.slice(0, sp);
  return chars.join('').replace(/[\s,;:]+$/u, '') + tail;
}

// Largest font size (maxSize down to minSize) at which the hook fits in maxRows; the box spans the frame's width.
export function layoutBanner(ctx, text, W) {
  const boxW = W - 2 * BANNER.margin, inner = boxW - 2 * BANNER.pad;
  const units = hookUnits(text);
  let size = BANNER.maxSize, rows;
  for (; size >= BANNER.minSize; size -= 4) {
    ctx.font = fontAt(size);
    rows = wrapUnits(ctx, units, inner);
    if (rows.length <= BANNER.maxRows) break;
  }
  if (rows.length > BANNER.maxRows) {                      // still too long at the smallest size: cut with an ellipsis
    ctx.font = fontAt(size = BANNER.minSize);
    rows = wrapUnits(ctx, units, inner).slice(0, BANNER.maxRows);
    rows[rows.length - 1] = cutWithEllipsis(ctx, rows[rows.length - 1], inner, trailingEmoji(text));
  }
  const lh = Math.round(size * 1.12), boxH = rows.length * lh + 2 * BANNER.pad - Math.round(size * 0.12);
  const box = {x: BANNER.margin, y: BANNER.top, w: boxW, h: boxH};
  // the lowest screen point of the rotated box (bubbles stay below it)
  const bottom = Math.ceil(box.y + box.h + Math.abs(Math.sin(BANNER.angle)) * box.w / 2 + 6);
  return {rows, size, lh, box, bottom};
}
