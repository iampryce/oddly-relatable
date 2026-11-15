// Conversation graphics, drawn as PNGs because the B1 renderer only composites image/text layers.
// All sizes are in renderer design units (the 1280-wide plane). `ppu` = output pixels per design unit,
// so a PNG drawn at ppu = outputWidth / 1280 is composited at ~1:1 and stays crisp.
import {canvas, ensureFonts, FONT} from './runtime.mjs';
import {BUBBLE_STYLES, PALETTE} from './palette.mjs';
import {assertRenderable, wrapText} from './text.mjs';

const {createCanvas} = canvas;

export const BUBBLE_DEFAULTS = Object.freeze({
  fontSize: 46, lineHeight: 1.24, padX: 34, padY: 24,
  maxWidth: 860, minWidth: 140, radius: 34, outline: 5, tail: 16, drop: 7,
});

function surface(width, height, ppu) {
  const c = createCanvas(Math.max(1, Math.ceil(width * ppu)), Math.max(1, Math.ceil(height * ppu)));
  const ctx = c.getContext('2d');
  ctx.scale(ppu, ppu);
  return {c, ctx};
}
// Report the drawn size in design units from the actual pixel size, so aspect ratio is exact.
function result(c, ppu, extra = {}) {
  return {png: c.toBuffer('image/png'), width: c.width / ppu, height: c.height / ppu, ...extra};
}
function styleFor(name) {
  const s = typeof name === 'object' ? name : BUBBLE_STYLES[name];
  if (!s) throw new Error(`Unknown bubble style: ${name}`);
  return s;
}

// Measure a message bubble without drawing it (used by layout and tests).
export function measureBubble(text, opts = {}) {
  ensureFonts();
  const o = {...BUBBLE_DEFAULTS, ...opts};
  assertRenderable(text, 'message');
  const {ctx} = surface(4, 4, 1);
  ctx.font = `500 ${o.fontSize}px "${FONT.sans}"`;
  const maxText = o.maxWidth - 2 * o.padX;
  const lines = wrapText(ctx, text, maxText);
  const textWidth = Math.max(...lines.map(l => ctx.measureText(l).width));
  const bodyWidth = Math.max(o.minWidth, Math.ceil(textWidth + 2 * o.padX));
  const bodyHeight = Math.ceil(lines.length * o.fontSize * o.lineHeight + 2 * o.padY);
  return {lines, textWidth, bodyWidth, bodyHeight, width: bodyWidth + o.outline * 2, height: bodyHeight + o.tail + o.drop + o.outline * 2, opts: o};
}

// Shared bubble body: drop shadow, rounded body, small rounded tail on the speaker's side.
// Draw order (stroke tail, stroke body, fill tail, fill body) hides the inner seam between them.
function drawShell(ctx, {bodyWidth, bodyHeight, side, style, o}) {
  const x = o.outline, y = o.outline, w = bodyWidth, h = bodyHeight;
  const left = side === 'left';
  const tx = left ? x + o.radius * 0.7 : x + w - o.radius * 0.7;
  const tail = new Path2DLike();
  tail.moveTo(tx - 16, y + h - 4);
  tail.lineTo(left ? tx - 22 : tx + 22, y + h + o.tail);
  tail.lineTo(tx + 16, y + h - 4);
  // drop shadow
  ctx.fillStyle = PALETTE.shadow;
  ctx.beginPath(); ctx.roundRect(x + 2, y + o.drop, w, h, o.radius); ctx.fill();
  ctx.lineWidth = o.outline; ctx.strokeStyle = style.outline; ctx.lineJoin = 'round'; ctx.fillStyle = style.fill;
  tail.apply(ctx); ctx.stroke();
  ctx.beginPath(); ctx.roundRect(x, y, w, h, o.radius); ctx.stroke();
  tail.apply(ctx); ctx.fill();
  ctx.beginPath(); ctx.roundRect(x, y, w, h, o.radius); ctx.fill();
}
// Minimal replayable path (keeps the tail geometry in one place).
class Path2DLike {
  constructor() { this.ops = []; }
  moveTo(x, y) { this.ops.push(['moveTo', x, y]); }
  lineTo(x, y) { this.ops.push(['lineTo', x, y]); }
  apply(ctx) { ctx.beginPath(); for (const [op, x, y] of this.ops) ctx[op](x, y); ctx.closePath(); }
}

// A message bubble PNG. side: which way the tail points ('left' or 'right'). style: required, from the speaker's
// configuration (AP-85 P1); it is never derived from the side.
export function renderBubble({text, side = 'left', style, ppu = 1, ...opts}) {
  if (!['left', 'right'].includes(side)) throw new Error(`Bubble side must be left or right, got ${side}`);
  if (style === undefined) throw new Error('Bubble style is required (it comes from the speaker\'s configuration, never from the side)');
  const m = measureBubble(text, opts), o = m.opts, s = styleFor(style);
  const {c, ctx} = surface(m.width, m.height, ppu);
  drawShell(ctx, {bodyWidth: m.bodyWidth, bodyHeight: m.bodyHeight, side, style: s, o});
  ctx.fillStyle = s.text; ctx.textBaseline = 'top';
  ctx.font = `500 ${o.fontSize}px "${FONT.sans}"`;
  // Text is left-aligned inside the bubble; lines are vertically centred in the line box.
  const lead = (o.fontSize * o.lineHeight - o.fontSize) / 2;
  m.lines.forEach((line, i) => ctx.fillText(line, o.outline + o.padX, o.outline + o.padY + lead + i * o.fontSize * o.lineHeight));
  return result(c, ppu, {lines: m.lines, side});
}

// Typing indicator shell (an empty bubble sized for three dots) and the dot itself.
export const TYPING_DEFAULTS = Object.freeze({dot: 20, gap: 16, padX: 32, padY: 28});
export function typingGeometry(opts = {}) {
  const t = {...TYPING_DEFAULTS, ...opts}, o = {...BUBBLE_DEFAULTS, ...opts};
  const bodyWidth = t.padX * 2 + t.dot * 3 + t.gap * 2, bodyHeight = t.padY * 2 + t.dot;
  const dots = [0, 1, 2].map(i => ({x: o.outline + t.padX + i * (t.dot + t.gap), y: o.outline + t.padY}));
  return {bodyWidth, bodyHeight, width: bodyWidth + o.outline * 2, height: bodyHeight + o.tail + o.drop + o.outline * 2, dots, dot: t.dot, o};
}
export function renderTypingShell({side = 'left', style, ppu = 1, ...opts}) {
  if (style === undefined) throw new Error('Typing indicator style is required (it comes from the speaker\'s configuration, never from the side)');
  const g = typingGeometry(opts), s = styleFor(style);
  const {c, ctx} = surface(g.width, g.height, ppu);
  drawShell(ctx, {bodyWidth: g.bodyWidth, bodyHeight: g.bodyHeight, side, style: s, o: g.o});
  return result(c, ppu, {dots: g.dots, dot: g.dot});
}
export function renderDot({diameter = TYPING_DEFAULTS.dot, color = PALETTE.muted, ppu = 1}) {
  const {c, ctx} = surface(diameter, diameter, ppu);
  ctx.fillStyle = color; ctx.beginPath(); ctx.arc(diameter / 2, diameter / 2, diameter / 2, 0, Math.PI * 2); ctx.fill();
  return result(c, ppu);
}

// Simple vector heart (the font has no emoji), used by the contact header.
function drawHeart(ctx, cx, cy, size, color) {
  const s = size / 2;
  ctx.fillStyle = color; ctx.beginPath();
  ctx.moveTo(cx, cy + s * 0.9);
  ctx.bezierCurveTo(cx - s * 1.6, cy - s * 0.1, cx - s * 0.7, cy - s * 1.35, cx, cy - s * 0.45);
  ctx.bezierCurveTo(cx + s * 0.7, cy - s * 1.35, cx + s * 1.6, cy - s * 0.1, cx, cy + s * 0.9);
  ctx.fill();
}

// Contact / conversation header: a pill with the contact label and an optional heart icon.
export function renderHeader({label, icon = null, fontSize = 40, padX = 34, padY = 16, ppu = 1, fill = PALETTE.card, color = PALETTE.cardInk, iconColor = PALETTE.rust}) {
  ensureFonts();
  assertRenderable(label, 'header label');
  if (icon && icon !== 'heart') throw new Error(`Unsupported header icon: ${icon}`);
  const {ctx: m} = surface(4, 4, 1); m.font = `700 ${fontSize}px "${FONT.sans}"`;
  const textW = m.measureText(label).width, iconW = icon ? fontSize * 0.95 + 14 : 0;
  const w = Math.ceil(textW + iconW + padX * 2), h = Math.ceil(fontSize * 1.3 + padY * 2);
  const {c, ctx} = surface(w, h, ppu);
  ctx.fillStyle = fill; ctx.beginPath(); ctx.roundRect(0, 0, w, h, h / 2); ctx.fill();
  ctx.fillStyle = color; ctx.font = `700 ${fontSize}px "${FONT.sans}"`; ctx.textBaseline = 'middle';
  ctx.fillText(label, padX, h / 2 + 1);
  if (icon) drawHeart(ctx, padX + textW + 14 + fontSize * 0.45, h / 2 + 2, fontSize * 0.8, iconColor);
  return result(c, ppu);
}

// Generic title card used for the opening hook and the end card.
// lines: [{text, size, weight, color, font: 'sans'|'hand'}]; background: none | panel | solid | dim.
// footer: optional light band at the bottom ({height, color}) so the renderer's B1 caption (dark text) stays readable on a dark card.
export function renderTitleCard({lines, width, height = null, padding = 40, gap = 14, align = 'center', background = {type: 'panel'}, footer = null, ppu = 1}) {
  ensureFonts();
  if (!Array.isArray(lines) || !lines.length) throw new Error('Title card needs at least one line');
  const {ctx: m} = surface(4, 4, 1);
  const laid = [];
  for (const [i, line] of lines.entries()) {
    assertRenderable(line.text, `title line ${i + 1}`);
    const size = line.size || 64, weight = line.weight || 700, family = FONT[line.font || 'sans'];
    m.font = `${weight} ${size}px "${family}"`;
    const wrapped = wrapText(m, line.text, width - padding * 2);
    for (const text of wrapped) laid.push({text, size, weight, family, color: line.color || PALETTE.cardInk, w: m.measureText(text).width});
  }
  const contentH = laid.reduce((a, l) => a + l.size * 1.2, 0) + gap * (laid.length - 1);
  const h = Math.ceil(height ?? contentH + padding * 2);
  const {c, ctx} = surface(width, h, ppu);
  const bg = background || {type: 'none'};
  if (bg.type === 'panel') {
    ctx.fillStyle = bg.color || PALETTE.card; ctx.beginPath(); ctx.roundRect(0, 0, width, h, bg.radius ?? 30); ctx.fill();
    if (bg.outline) { ctx.lineWidth = bg.outline; ctx.strokeStyle = PALETTE.outline; ctx.stroke(); }
  } else if (bg.type === 'solid') { ctx.fillStyle = bg.color || PALETTE.card; ctx.fillRect(0, 0, width, h); }
  else if (bg.type === 'dim') { ctx.fillStyle = bg.color || 'rgba(22,19,15,0.72)'; ctx.fillRect(0, 0, width, h); }
  else if (bg.type !== 'none') throw new Error(`Unknown title background: ${bg.type}`);
  if (footer) { ctx.fillStyle = footer.color || PALETTE.cream; ctx.fillRect(0, h - footer.height, width, footer.height); }
  let y = (h - (footer?.height || 0) - contentH) / 2;
  ctx.textBaseline = 'top';
  for (const l of laid) {
    ctx.font = `${l.weight} ${l.size}px "${l.family}"`; ctx.fillStyle = l.color;
    const x = align === 'left' ? padding : align === 'right' ? width - padding - l.w : (width - l.w) / 2;
    ctx.fillText(l.text, x, y + l.size * 0.1);
    y += l.size * 1.2 + gap;
  }
  return result(c, ppu, {lines: laid.map(l => l.text)});
}

// Soft contact shadow under the character's feet.
export function renderShadow({width = 220, height = 46, ppu = 1, opacity = 0.32}) {
  const {c, ctx} = surface(width, height, ppu);
  const g = ctx.createRadialGradient(width / 2, height / 2, 2, width / 2, height / 2, width / 2);
  g.addColorStop(0, `rgba(22,19,15,${opacity})`); g.addColorStop(1, 'rgba(22,19,15,0)');
  ctx.save(); ctx.translate(width / 2, height / 2); ctx.scale(1, height / width); ctx.translate(-width / 2, -height / 2);
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(width / 2, height / 2, width / 2, 0, Math.PI * 2); ctx.fill(); ctx.restore();
  return result(c, ppu);
}
