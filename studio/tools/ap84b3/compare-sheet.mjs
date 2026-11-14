#!/usr/bin/env node
// AP-84B3 comparison sheet (D1-6, item I5).
//
// Draws the reference, the approved pose and the candidates side by side for the owner's review. Every image is
// drawn at ONE scale factor (so relative sizes are honest), on the same grey ground, with its label, pixel
// size and SHA-256 underneath. The inputs are only read. The sheet is review evidence, not artwork, and is
// written outside the repository.
//
//   node studio/tools/ap84b3/compare-sheet.mjs --out <sheet.png> --item "label=path" [--item "label=path" ...]
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {canvas, ensureFonts, FONT} from '../../../production/lib/runtime.mjs';
import {loadLock, sha256Buffer, isInside, REPO_ROOT} from '../../lib/experiment-spec.mjs';

const PAD = 40, GAP = 40, CAPTION = 96, MAX_CELL_H = 1536, GROUND = '#cbcbcb';

// Pure layout: one scale for every item, chosen so the tallest image fits MAX_CELL_H (never enlarged above 1).
export function layout(items) {
  if (!items.length) throw new Error('at least one item is required');
  const scale = Math.min(1, MAX_CELL_H / Math.max(...items.map(i => i.height)));
  let x = PAD;
  const cellH = Math.round(Math.max(...items.map(i => i.height)) * scale);
  const cells = items.map(i => {
    const w = Math.round(i.width * scale), h = Math.round(i.height * scale);
    const cell = {label: i.label, sha256: i.sha256, sourceWidth: i.width, sourceHeight: i.height, x, y: PAD + (cellH - h), width: w, height: h, scale};
    x += Math.max(w, 300) + GAP;
    return cell;
  });
  return {scale, cells, width: x - GAP + PAD, height: PAD + cellH + CAPTION + PAD};
}

// items: [{label, file}]. Returns {buffer, sheet} where sheet records the layout and every input hash.
export async function buildSheet(items) {
  ensureFonts();
  const loaded = [];
  for (const it of items) {
    if (!it.label || /[\r\n]/.test(it.label) || it.label.length > 60) throw new Error('each item needs a short, single-line label');
    const bytes = fs.readFileSync(it.file);
    const img = await canvas.loadImage(it.file);                 // loaded from its path (Buffers are not decoded reliably)
    loaded.push({label: it.label, sha256: sha256Buffer(bytes), width: img.width, height: img.height, img});
  }
  const L = layout(loaded);
  const c = canvas.createCanvas(L.width, L.height), ctx = c.getContext('2d');
  ctx.fillStyle = GROUND; ctx.fillRect(0, 0, L.width, L.height);
  ctx.textBaseline = 'top';
  L.cells.forEach((cell, i) => {
    ctx.drawImage(loaded[i].img, cell.x, cell.y, cell.width, cell.height);
    const ty = L.height - PAD - CAPTION + 12;
    ctx.fillStyle = '#000000';
    ctx.font = `700 26px "${FONT.sans}"`; ctx.fillText(cell.label, cell.x, ty);
    ctx.font = `400 18px "${FONT.sans}"`;
    ctx.fillText(`${cell.sourceWidth}×${cell.sourceHeight} px, drawn at ${(L.scale * 100).toFixed(1)}%`, cell.x, ty + 34);
    ctx.fillText(`sha256 ${cell.sha256.slice(0, 16)}…`, cell.x, ty + 58);
  });
  return {buffer: c.toBuffer('image/png'), sheet: {schema: 'ap84b3-compare-sheet/1', scale: L.scale, width: L.width, height: L.height, items: L.cells}};
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  (async () => {
    const out = process.argv[process.argv.indexOf('--out') + 1], items = [];
    process.argv.forEach((a, i) => { if (a === '--item') { const v = process.argv[i + 1] || '', k = v.indexOf('='); if (k < 1) throw new Error('--item must be "label=path"'); items.push({label: v.slice(0, k), file: v.slice(k + 1)}); } });
    if (!process.argv.includes('--out') || !out || !items.length) throw new Error('usage: compare-sheet.mjs --out <sheet.png> --item "label=path" [--item ...]');
    loadLock();                                                   // refuses unless the lock is owner-approved
    const target = path.resolve(out);
    if (isInside(path.dirname(target), REPO_ROOT)) throw new Error('the sheet must be written outside the repository');
    const {buffer, sheet} = await buildSheet(items);
    fs.writeFileSync(target, buffer, {flag: 'wx'});
    fs.writeFileSync(target.replace(/\.png$/i, '') + '.json', JSON.stringify({...sheet, sha256: sha256Buffer(buffer)}, null, 1), {flag: 'wx'});
    console.log(JSON.stringify({out: target, sha256: sha256Buffer(buffer), scale: sheet.scale, items: sheet.items.length}, null, 1));
  })().catch(e => { console.error(`compare-sheet: ${e.message}`); process.exit(1); });
}
