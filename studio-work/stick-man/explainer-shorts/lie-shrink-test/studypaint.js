// Painted textures for the Episode 15 study, in the kit's paint.js style (flat colour, dark seams, deterministic).
import { rng } from './paint.js';
const cv = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return [c, c.getContext('2d')]; };
const hsl = (h, s, l, a = 1) => `hsla(${h},${s}%,${l}%,${a})`;
const mottle = (g, w, h, r, n, h0, s0, l0, dl, a = 0.25) => { for (let i = 0; i < n; i++) { g.fillStyle = hsl(h0 + r() * 6 - 3, s0, l0 + (r() - 0.5) * dl, a); g.beginPath(); g.ellipse(r() * w, r() * h, 10 + r() * 40, 6 + r() * 24, r() * 3, 0, 7); g.fill(); } };
const grain = (g, x, y, w, h, r, base, n = 40, vertical = true) => {
  for (let k = 0; k < n; k++) { g.strokeStyle = hsl(base[0] - 3, base[1], base[2] - 6 - r() * 8, 0.4); g.lineWidth = 1 + r() * 2; g.beginPath();
    if (vertical) { const xx = x + r() * w; g.moveTo(xx, y); g.bezierCurveTo(xx + 6, y + h / 3, xx - 6, y + 2 * h / 3, xx + r() * 6 - 3, y + h); }
    else { const yy = y + r() * h; g.moveTo(x, yy); g.bezierCurveTo(x + w / 3, yy + 5, x + 2 * w / 3, yy - 5, x + w, yy + r() * 4 - 2); }
    g.stroke(); }
};
/** raised panel moulding: light top/left, dark bottom/right */
const panel = (g, x, y, w, h, lt, dk, lw = 6) => {
  g.lineWidth = lw; g.strokeStyle = dk; g.strokeRect(x, y, w, h);
  g.strokeStyle = lt; g.beginPath(); g.moveTo(x + lw, y + h - lw); g.lineTo(x + lw, y + lw); g.lineTo(x + w - lw, y + lw); g.stroke();
  g.strokeStyle = dk; g.beginPath(); g.moveTo(x + lw * 2, y + h - lw * 2); g.lineTo(x + w - lw * 2, y + h - lw * 2); g.lineTo(x + w - lw * 2, y + lw * 2); g.stroke();
};
/** green painted wall with one tall moulded panel per tile */
export function greenWall(seed = 1) {
  const [c, g] = cv(512, 1024), r = rng(seed);
  g.fillStyle = '#2d5a3a'; g.fillRect(0, 0, 512, 1024);
  mottle(g, 512, 1024, r, 120, 140, 34, 26, 8, 0.25);
  panel(g, 56, 70, 400, 890, '#4d7f58', '#173523', 9);
  g.strokeStyle = 'rgba(15,35,22,.55)'; g.lineWidth = 3; g.strokeRect(76, 90, 360, 850);
  return c;
}
/** dark wood wainscot / cabinet doors: panels with bevels */
export function woodPanel(seed = 2, base = [24, 42, 24], cols = 1) {
  const [c, g] = cv(512, 512), r = rng(seed);
  g.fillStyle = hsl(...base); g.fillRect(0, 0, 512, 512);
  grain(g, 0, 0, 512, 512, r, base, 60);
  const w = 512 / cols;
  for (let i = 0; i < cols; i++) { panel(g, i * w + 34, 40, w - 68, 432, hsl(base[0], base[1], base[2] + 12), hsl(base[0], base[1], base[2] - 12), 8); }
  return c;
}
export function woodGrain(seed = 3, base = [24, 40, 26]) { const [c, g] = cv(256, 512), r = rng(seed); g.fillStyle = hsl(...base); g.fillRect(0, 0, 256, 512); grain(g, 0, 0, 256, 512, r, base, 50); return c; }
/** desk front: two drawers per pedestal with brass bail handles */
export function drawers(seed = 4, rows = 3) {
  const base = [22, 44, 26], [c, g] = cv(512, 768), r = rng(seed);
  g.fillStyle = hsl(...base); g.fillRect(0, 0, 512, 768); grain(g, 0, 0, 512, 768, r, base, 40, false);
  const h = 768 / rows;
  for (let i = 0; i < rows; i++) {
    const y = i * h; g.fillStyle = 'rgba(20,10,4,.9)'; g.fillRect(0, y, 512, 6);
    panel(g, 28, y + 22, 456, h - 44, hsl(base[0], base[1], base[2] + 12), hsl(base[0], base[1], base[2] - 13), 7);
    const cx = 256, cy = y + h / 2; g.strokeStyle = '#2a1a0a'; g.lineWidth = 12; g.beginPath(); g.arc(cx, cy - 6, 44, 0.15, Math.PI - 0.15); g.stroke();
    g.strokeStyle = '#d9a845'; g.lineWidth = 7; g.beginPath(); g.arc(cx, cy - 6, 44, 0.15, Math.PI - 0.15); g.stroke();
    for (const s of [-1, 1]) { g.fillStyle = '#2a1a0a'; g.beginPath(); g.arc(cx + s * 44, cy - 2, 11, 0, 7); g.fill(); g.fillStyle = '#d9a845'; g.beginPath(); g.arc(cx + s * 44, cy - 2, 7.5, 0, 7); g.fill(); }
  }
  return c;
}
/** green tufted leather: diamond seams, buttons, soft highlights */
export function leather(seed = 5) {
  const [c, g] = cv(512, 512), r = rng(seed);
  g.fillStyle = '#2f6a3b'; g.fillRect(0, 0, 512, 512);
  const s = 128;
  for (let y = -1; y < 5; y++) for (let x = -1; x < 5; x++) {
    const cx = x * s + (y % 2 ? s / 2 : 0), cy = y * s * 0.5 * 1.2;
    const gr = g.createRadialGradient(cx - 14, cy - 18, 4, cx, cy, s * 0.55); gr.addColorStop(0, '#5fa86a'); gr.addColorStop(0.45, '#3a7d47'); gr.addColorStop(1, '#245832');
    g.fillStyle = gr; g.beginPath(); g.moveTo(cx, cy - s * 0.36); g.lineTo(cx + s / 2, cy); g.lineTo(cx, cy + s * 0.36); g.lineTo(cx - s / 2, cy); g.closePath(); g.fill();
  }
  g.strokeStyle = '#143a1e'; g.lineWidth = 4;
  for (let k = -6; k < 12; k++) { g.beginPath(); g.moveTo(k * s / 2, 0); g.lineTo(k * s / 2 + 512 * 1.39, 512); g.stroke(); g.beginPath(); g.moveTo(k * s / 2, 512); g.lineTo(k * s / 2 + 512 * 1.39, 0); g.stroke(); }
  for (let y = 0; y < 8; y++) for (let x = 0; x < 9; x++) { const px = x * s / 2 + (y % 2 ? s / 4 : 0), py = y * s * 0.36 * 0.5 * 2.0; g.fillStyle = '#0f2a15'; g.beginPath(); g.arc(px, py, 7, 0, 7); g.fill(); g.fillStyle = '#4f9a5c'; g.beginPath(); g.arc(px - 2, py - 2, 3, 0, 7); g.fill(); }
  return c;
}
export function plainLeather() { const [c, g] = cv(256, 256), r = rng(6); g.fillStyle = '#2f6a3b'; g.fillRect(0, 0, 256, 256); for (let i = 0; i < 30; i++) { g.fillStyle = `rgba(110,190,120,${0.1 + r() * 0.15})`; g.beginPath(); g.ellipse(r() * 256, r() * 256, 20 + r() * 40, 8 + r() * 14, r() * 3, 0, 7); g.fill(); } return c; }
/** burgundy rug with a gold border and a centre medallion */
export function rug() {
  const [c, g] = cv(1024, 768), r = rng(7);
  g.fillStyle = '#6e1a2a'; g.fillRect(0, 0, 1024, 768);
  mottle(g, 1024, 768, r, 160, 350, 50, 24, 8, 0.25);
  g.strokeStyle = '#c89a52'; g.lineWidth = 10; g.strokeRect(30, 30, 964, 708); g.lineWidth = 4; g.strokeRect(70, 70, 884, 628);
  g.fillStyle = '#5a1222'; g.fillRect(36, 36, 952, 28); g.fillRect(36, 704, 952, 28); g.fillRect(36, 36, 28, 696); g.fillRect(960, 36, 28, 696);
  g.strokeStyle = '#c89a52'; g.lineWidth = 3;
  for (let i = 0; i < 24; i++) { const x = 90 + i * 37; g.beginPath(); g.arc(x, 50, 10, 0, Math.PI); g.stroke(); g.beginPath(); g.arc(x, 718, 10, Math.PI, 0); g.stroke(); }
  // medallion
  g.save(); g.translate(512, 384); g.fillStyle = '#8a2a38'; g.beginPath(); g.moveTo(0, -170); g.lineTo(260, 0); g.lineTo(0, 170); g.lineTo(-260, 0); g.closePath(); g.fill();
  g.strokeStyle = '#c89a52'; g.lineWidth = 6; g.stroke();
  g.lineWidth = 4; for (let k = 0; k < 8; k++) { g.rotate(Math.PI / 4); g.beginPath(); g.moveTo(30, 0); g.bezierCurveTo(70, -40, 110, 30, 150, -10); g.stroke(); }
  g.fillStyle = '#c89a52'; g.beginPath(); g.arc(0, 0, 22, 0, 7); g.fill(); g.restore();
  for (const [x, y] of [[180, 160], [844, 160], [180, 608], [844, 608]]) { g.save(); g.translate(x, y); g.strokeStyle = '#c89a52'; g.lineWidth = 4; for (let k = 0; k < 4; k++) { g.rotate(Math.PI / 2); g.beginPath(); g.moveTo(8, 0); g.bezierCurveTo(30, -30, 60, 20, 80, -6); g.stroke(); } g.restore(); }
  return c;
}
/** the portrait: an invented bearded old gentleman, painted (not a stick figure) */
export function portrait() {
  const [c, g] = cv(512, 640);
  const bg = g.createRadialGradient(256, 260, 30, 256, 300, 420); bg.addColorStop(0, '#6b5236'); bg.addColorStop(1, '#2a1c12'); g.fillStyle = bg; g.fillRect(0, 0, 512, 640);
  // dark coat + shirt + cravat
  g.fillStyle = '#1f2622'; g.beginPath(); g.moveTo(40, 640); g.bezierCurveTo(60, 470, 150, 430, 256, 425); g.bezierCurveTo(362, 430, 452, 470, 472, 640); g.fill();
  g.fillStyle = '#efe9da'; g.beginPath(); g.moveTo(200, 440); g.lineTo(256, 560); g.lineTo(312, 440); g.fill();
  g.fillStyle = '#5a1e22'; g.beginPath(); g.moveTo(240, 470); g.lineTo(272, 470); g.lineTo(262, 560); g.lineTo(250, 560); g.fill();
  // head
  g.fillStyle = '#e8c2a0'; g.beginPath(); g.ellipse(256, 250, 92, 112, 0, 0, 7); g.fill();
  g.fillStyle = '#d4a684'; g.beginPath(); g.ellipse(226, 270, 50, 80, 0.2, 0, 7); g.fill();
  // white hair sides + bald top shine
  g.fillStyle = '#eeeeea'; for (const s of [-1, 1]) { g.beginPath(); g.ellipse(256 + s * 92, 220, 34, 60, s * 0.3, 0, 7); g.fill(); }
  g.fillStyle = 'rgba(255,240,220,.5)'; g.beginPath(); g.ellipse(276, 175, 30, 16, -0.3, 0, 7); g.fill();
  // big white beard + moustache
  g.fillStyle = '#f2f0ea'; g.beginPath(); g.moveTo(170, 270); g.bezierCurveTo(165, 400, 220, 470, 256, 490); g.bezierCurveTo(292, 470, 347, 400, 342, 270); g.bezierCurveTo(310, 330, 200, 330, 170, 270); g.fill();
  g.strokeStyle = '#c9c6be'; g.lineWidth = 2.5; for (let i = -4; i <= 4; i++) { g.beginPath(); g.moveTo(256 + i * 18, 330); g.quadraticCurveTo(256 + i * 16, 400, 256 + i * 9, 470); g.stroke(); }
  g.fillStyle = '#f7f5f0'; g.beginPath(); g.ellipse(232, 312, 34, 13, 0.25, 0, 7); g.ellipse(280, 312, 34, 13, -0.25, 0, 7); g.fill();
  // eyes, brows, nose
  g.fillStyle = '#2a1e18'; for (const s of [-1, 1]) { g.beginPath(); g.ellipse(256 + s * 36, 240, 7, 5, 0, 0, 7); g.fill(); }
  g.strokeStyle = '#eeeeea'; g.lineWidth = 9; g.lineCap = 'round'; for (const s of [-1, 1]) { g.beginPath(); g.moveTo(256 + s * 18, 220); g.lineTo(256 + s * 56, 214); g.stroke(); }
  g.strokeStyle = '#b58866'; g.lineWidth = 4; g.beginPath(); g.moveTo(256, 245); g.quadraticCurveTo(268, 280, 252, 292); g.stroke();
  // varnish
  const v = g.createLinearGradient(0, 0, 512, 640); v.addColorStop(0, 'rgba(255,230,170,.10)'); v.addColorStop(1, 'rgba(0,0,0,.25)'); g.fillStyle = v; g.fillRect(0, 0, 512, 640);
  return c;
}
/** gilded frame moulding */
export function gilt() { const [c, g] = cv(128, 512), r = rng(9); g.fillStyle = '#c8962e'; g.fillRect(0, 0, 128, 512); for (let y = 0; y < 512; y += 32) { g.fillStyle = '#e8c45c'; g.beginPath(); g.ellipse(64, y + 16, 26, 12, 0, 0, 7); g.fill(); g.strokeStyle = '#7a5410'; g.lineWidth = 3; g.stroke(); } g.fillStyle = '#7a5410'; g.fillRect(0, 0, 10, 512); g.fillRect(118, 0, 10, 512); return c; }
/** curtain folds */
export function curtain() { const [c, g] = cv(256, 512); for (let i = 0; i < 8; i++) { const gr = g.createLinearGradient(i * 32, 0, i * 32 + 32, 0); gr.addColorStop(0, '#1d4f2c'); gr.addColorStop(0.5, '#3f8550'); gr.addColorStop(1, '#1d4f2c'); g.fillStyle = gr; g.fillRect(i * 32, 0, 32, 512); } return c; }
export function brick() { const [c, g] = cv(256, 256), r = rng(11); g.fillStyle = '#1b1512'; g.fillRect(0, 0, 256, 256); for (let y = 0; y < 8; y++) for (let x = -1; x < 5; x++) { g.fillStyle = hsl(10, 25, 18 + r() * 8); g.fillRect(x * 64 + (y % 2) * 32 + 3, y * 32 + 3, 58, 26); } return c; }
export function paperStack() { const [c, g] = cv(256, 256), r = rng(12); g.fillStyle = '#f2ecdb'; g.fillRect(0, 0, 256, 256); g.strokeStyle = '#b9b2a0'; g.lineWidth = 4; for (let i = 0; i < 9; i++) { g.beginPath(); g.moveTo(30, 40 + i * 22); g.lineTo(150 + r() * 70, 40 + i * 22); g.stroke(); } return c; }
