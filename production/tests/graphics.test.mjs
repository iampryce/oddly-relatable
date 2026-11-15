import test from 'node:test';
import assert from 'node:assert/strict';
import {canvas} from '../lib/runtime.mjs';
import {measureBubble, renderBubble, renderTypingShell, typingGeometry, renderHeader, renderTitleCard, renderDot, BUBBLE_DEFAULTS} from '../lib/graphics.mjs';
import {BUBBLE_STYLES, PALETTE, contrast} from '../lib/palette.mjs';

// Read one RGBA pixel (design-unit coordinates) from a rendered PNG.
async function pixel(png, x, y, ppu = 1) {
  const img = await canvas.loadImage(png), c = canvas.createCanvas(img.width, img.height), ctx = c.getContext('2d');
  ctx.drawImage(img, 0, 0);
  return [...ctx.getImageData(Math.round(x * ppu), Math.round(y * ppu), 1, 1).data];
}
const hex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
const near = (a, b, tol = 6) => a.slice(0, 3).every((v, i) => Math.abs(v - b[i]) <= tol);

test('short message is one line; long message wraps and never exceeds the max width', () => {
  assert.equal(measureBubble('Tonight.').lines.length, 1);
  const long = measureBubble('Is this about the dishwasher? I can explain the dishwasher. I really can, honestly, it was an accident.');
  assert.ok(long.lines.length >= 3, `expected wrapping, got ${long.lines.length} line(s)`);
  assert.ok(long.width <= BUBBLE_DEFAULTS.maxWidth + 2 * BUBBLE_DEFAULTS.outline + 1);
  const token = measureBubble('A'.repeat(80));
  assert.ok(token.lines.length > 1, 'an over-long single token is split rather than overflowing');
});

test('left (HER) and right (HIM) bubbles use their distinct canon-palette fills', async () => {
  const her = renderBubble({text: 'We need to talk.', side: 'left', style: 'her'}), him = renderBubble({text: 'Is everything ok?', side: 'right', style: 'him'});
  // sample inside the body, away from the text (top-right inner corner region)
  assert.ok(near(await pixel(her.png, her.width - 30, 14), hex(BUBBLE_STYLES.her.fill)));
  assert.ok(near(await pixel(him.png, him.width - 30, 14), hex(BUBBLE_STYLES.him.fill)));
  assert.equal(her.side, 'left'); assert.equal(him.side, 'right');
  assert.throws(() => renderBubble({text: 'x', side: 'up'}), /left or right/);
});

test('bubble text keeps WCAG AA contrast against its fill', () => {
  for (const s of Object.values(BUBBLE_STYLES)) assert.ok(contrast(s.text, s.fill) >= 4.5, `${s.text} on ${s.fill}`);
  assert.ok(contrast(PALETTE.cardInk, PALETTE.card) >= 4.5);
});

test('ppu scales pixels but not design-unit size', () => {
  const a = renderBubble({text: 'Define March.', style: 'her', ppu: 1}), b = renderBubble({text: 'Define March.', style: 'her', ppu: 0.84375});
  assert.ok(Math.abs(a.width - b.width) < 2 && Math.abs(a.height - b.height) < 2);
});

test('typing indicator: three dots inside the shell', () => {
  const g = typingGeometry(), shell = renderTypingShell({side: 'left', style: 'her'});
  assert.equal(shell.dots.length, 3);
  for (const d of shell.dots) assert.ok(d.x > 0 && d.x + g.dot < shell.width && d.y + g.dot < shell.height);
  const dot = renderDot({diameter: 20});
  assert.equal(Math.round(dot.width), 20);
});

test('header draws a vector heart instead of an emoji glyph', async () => {
  const h = renderHeader({label: 'Wife', icon: 'heart'}), plain = renderHeader({label: 'Wife'});
  assert.ok(h.width > plain.width);
  assert.throws(() => renderHeader({label: 'Wife ❤️'}), /emoji/);
  assert.throws(() => renderHeader({label: 'Wife', icon: 'star'}), /Unsupported header icon/);
});

test('title card: hook panel and full-frame end card with a light caption footer', async () => {
  const hook = renderTitleCard({lines: [{text: 'Four words. No warning.', size: 64}], width: 1000});
  assert.equal(Math.round(hook.width), 1000);
  const end = renderTitleCard({lines: [{text: 'Title', size: 90}], width: 1280, height: 2275.56, background: {type: 'solid', color: PALETTE.card}, footer: {height: 150, color: PALETTE.cream}});
  assert.ok(near(await pixel(end.png, 20, 20), hex(PALETTE.card)));
  assert.ok(near(await pixel(end.png, 20, 2275.56 - 40), hex(PALETTE.cream)));
  assert.throws(() => renderTitleCard({lines: [], width: 100}), /at least one line/);
  assert.throws(() => renderTitleCard({lines: [{text: 'x'}], width: 300, background: {type: 'glitter'}}), /Unknown title background/);
});
