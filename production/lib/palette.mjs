// Colour tokens for conversation graphics.
// CANON values are measured from the locked canonical reference (bible/concepts/lookdev-richenv/lookdev-scene-01.png):
// skin (252,222,180), rust sweater (188,76,21), shoe (132,86,59); outline is the canon's near-black line colour.
// The remaining tokens are derived neutrals chosen to sit with that warm palette (not measured).
export const CANON = Object.freeze({
  skin: '#FCDEB4',
  rust: '#BC4C15',
  shoe: '#84563B',
  outline: '#16130F',
});

export const PALETTE = Object.freeze({
  ...CANON,
  cream: '#FFF6E6',
  ink: '#1F1A15',
  muted: '#7A6B5D',
  card: '#2A1D16',
  cardInk: '#FFF1DC',
  shadow: 'rgba(22,19,15,0.22)',
});

// Message bubble styles. Deliberately not modelled on any real messaging app:
// heavy cartoon outline, warm cream / canon rust fills, a small rounded tail.
export const BUBBLE_STYLES = Object.freeze({
  her: {fill: PALETTE.cream, text: PALETTE.ink, outline: PALETTE.outline},
  him: {fill: PALETTE.rust, text: PALETTE.cream, outline: PALETTE.outline},
  neutral: {fill: '#FFFFFF', text: PALETTE.ink, outline: PALETTE.outline},
});

// WCAG relative luminance and contrast ratio, used by tests to keep text readable.
export function luminance(hex) {
  const n = hex.replace('#', '');
  const [r, g, b] = [0, 2, 4].map(i => parseInt(n.slice(i, i + 2), 16) / 255)
    .map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
export function contrast(a, b) {
  const [l1, l2] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
}
