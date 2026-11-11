// Scene preview: exact still frames from the UNMODIFIED renderer (its exported loadProject + painter),
// assembled into a labelled storyboard sheet. Nothing is encoded and the renderer's output/ folder is not touched.
import fs from 'node:fs';
import path from 'node:path';
import {canvas, ensureFonts, FONT, rendererModules} from './runtime.mjs';

export async function renderStills(projectFile, times) {
  const {core, render} = await rendererModules();
  const p = core.loadProject(projectFile);
  const draw = await render.painter(p);
  return times.map(({t, label}) => {
    const tt = Math.max(0, Math.min(t, p.duration - 1 / p.fps));
    const frame = draw(tt);                     // the renderer reuses one canvas: copy the pixels immediately
    return {t: tt, label, png: frame.toBuffer('image/png'), width: frame.width, height: frame.height};
  });
}

export async function storyboardSheet(projectFile, times, {outFile, columns = 6, thumbWidth = 270, framesDir = null} = {}) {
  ensureFonts();
  const stills = await renderStills(projectFile, times);
  if (framesDir) {
    fs.mkdirSync(framesDir, {recursive: true});
    stills.forEach((s, i) => fs.writeFileSync(path.join(framesDir, `${String(i + 1).padStart(2, '0')}-t${s.t.toFixed(2)}.png`), s.png));
  }
  const th = Math.round(thumbWidth * stills[0].height / stills[0].width), labelH = 44, pad = 10;
  const rows = Math.ceil(stills.length / columns);
  const sheet = canvas.createCanvas(columns * (thumbWidth + pad) + pad, rows * (th + labelH + pad) + pad);
  const ctx = sheet.getContext('2d');
  ctx.fillStyle = '#1d2433'; ctx.fillRect(0, 0, sheet.width, sheet.height);
  for (const [i, s] of stills.entries()) {
    const x = pad + (i % columns) * (thumbWidth + pad), y = pad + Math.floor(i / columns) * (th + labelH + pad);
    ctx.drawImage(await canvas.loadImage(s.png), x, y + labelH, thumbWidth, th);
    ctx.fillStyle = '#ffffff'; ctx.font = `600 15px "${FONT.sans}"`; ctx.textBaseline = 'top';
    ctx.fillText(`${String(i + 1).padStart(2, '0')}  t=${s.t.toFixed(2)}s`, x, y + 4);
    ctx.fillStyle = '#c9d1e0'; ctx.font = `400 13px "${FONT.sans}"`;
    ctx.fillText(s.label.slice(0, 34), x, y + 24);
  }
  if (outFile) { fs.mkdirSync(path.dirname(outFile), {recursive: true}); fs.writeFileSync(outFile, sheet.toBuffer('image/png')); }
  return {sheet, stills};
}
