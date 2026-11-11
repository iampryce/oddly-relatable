// Text helpers: renderability checks and measured word wrapping.

// The bundled font (Noto Sans) has no emoji glyphs; an emoji would render as an empty box,
// so we reject it early with a clear message instead of producing a broken bubble.
const EMOJI = /\p{Extended_Pictographic}/u;

export function assertRenderable(text, where) {
  if (typeof text !== 'string' || !text.trim()) throw new Error(`${where}: text is required`);
  if (EMOJI.test(text)) throw new Error(`${where}: emoji are not supported by the bundled font ("${text}"); use the header "icon" option for a heart`);
  if (/[\t\r]/.test(text)) throw new Error(`${where}: tabs and carriage returns are not allowed`);
  return text;
}

// Wrap text to a maximum width using the canvas's real glyph measurements.
// Explicit "\n" starts a new paragraph. A single word wider than the limit is split by characters.
export function wrapText(ctx, text, maxWidth) {
  const lines = [];
  for (const paragraph of text.split('\n')) {
    const words = paragraph.trim().split(/\s+/).filter(Boolean);
    let line = '';
    for (const word of words) {
      const candidate = line ? `${line} ${word}` : word;
      if (ctx.measureText(candidate).width <= maxWidth) { line = candidate; continue; }
      if (line) lines.push(line);
      if (ctx.measureText(word).width <= maxWidth) { line = word; continue; }
      // Character-level split for an over-long token (e.g. a URL or "AAAAAAAA").
      let chunk = '';
      for (const ch of [...word]) {
        if (ctx.measureText(chunk + ch).width > maxWidth && chunk) { lines.push(chunk); chunk = ch; } else chunk += ch;
      }
      line = chunk;
    }
    lines.push(line);
  }
  return lines;
}
