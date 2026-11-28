// Measures an approved master and builds a matching code-body preset; cuts its head out. The master is only READ.
// Returns {head: canvas, preset: CAST entry, m: measurements (source pixels)}.
export function analyseMaster(im, opts = {}) {
  const W = im.width, H = im.height, cv = document.createElement('canvas'); cv.width = W; cv.height = H; const x = cv.getContext('2d'); x.drawImage(im, 0, 0);
  const d = x.getImageData(0, 0, W, H), px = d.data;
  const lum = (q) => (px[q] * 0.3 + px[q + 1] * 0.59 + px[q + 2] * 0.11), white = (k) => px[k] > 236 && px[k + 1] > 236 && px[k + 2] > 236;
  const seen = new Uint8Array(W * H), st = []; const push = (i, j) => { if (i < 0 || j < 0 || i >= W || j >= H) return; const q = j * W + i; if (seen[q] || !white(q * 4)) return; seen[q] = 1; st.push(q); };
  for (let i = 0; i < W; i++) { push(i, 0); push(i, H - 1); } for (let j = 0; j < H; j++) { push(0, j); push(W - 1, j); }
  while (st.length) { const q = st.pop(), i = q % W, j = (q / W) | 0; px[q * 4 + 3] = 0; push(i + 1, j); push(i - 1, j); push(i, j + 1); push(i, j - 1); }
  const dark = (i, j) => px[(j * W + i) * 4 + 3] > 0 && lum((j * W + i) * 4) < 100;
  const opaque = (i, j) => px[(j * W + i) * 4 + 3] > 0;
  const light = (i, j) => opaque(i, j) && lum((j * W + i) * 4) > 205;
  // figure rows = rows containing dark pixels (the grey contact shadow is not dark)
  let top = -1, sole = -1; const rowDark = new Array(H).fill(0), rowOpq = new Array(H).fill(0);
  for (let j = 0; j < H; j++) { let n = 0, o = 0; for (let i = 0; i < W; i++) { if (dark(i, j)) n++; if (opaque(i, j)) o++; } rowDark[j] = n; rowOpq[j] = o; if (n > 2) { if (top < 0) top = j; sole = j; } }
  let maxW = 0, maxJ = top; for (let j = top; j < H * 0.6; j++) if (rowOpq[j] > maxW) { maxW = rowOpq[j]; maxJ = j; }
  let neck = maxJ; for (let j = maxJ; j < H * 0.7; j++) { if (rowOpq[j] < maxW * 0.22) { neck = j; break; } }
  // torso rows: rows below the neck that still contain enclosed light (white) pixels; the last one is the hip
  const limit = Math.round(top + 0.66 * (sole - top)); let hip = neck, pillW = 0; for (let j = neck; j < limit; j++) { let n = 0; for (let i = 0; i < W; i++) if (light(i, j)) n++; if (n > 6) { hip = j; pillW = Math.max(pillW, n); } }
  const darkRuns = (j) => { const r = []; let s0 = -1; for (let i = 0; i <= W; i++) { const dk = i < W && dark(i, j); if (dk && s0 < 0) s0 = i; if (!dk && s0 >= 0) { r.push([s0, i - s0]); s0 = -1; } } return r; };
  const med = (a) => (a.length ? a.slice().sort((p, q) => p - q)[Math.floor(a.length / 2)] : 0);
  const legRows = []; for (let j = Math.round(hip + 0.15 * (sole - hip)); j < Math.round(sole - 0.25 * (sole - hip)); j += 4) darkRuns(j).forEach(([, w]) => legRows.push(w));
  const legW = med(legRows) || 14;
  // arms: dark runs in the torso rows that lie OUTSIDE the white pill; hands: the widest dark runs near the hip
  let cxp = 0, cn = 0; for (let j = neck + 10; j < hip; j += 6) for (let i = 0; i < W; i++) if (light(i, j)) { cxp += i; cn++; } cxp = cn ? cxp / cn : W / 2;
  const armRows = []; for (let j = Math.round(neck + 0.2 * (hip - neck)); j < Math.round(neck + 0.7 * (hip - neck)); j += 4) darkRuns(j).forEach(([st0, w]) => { if (w < legW * 2.2 && Math.abs(st0 + w / 2 - cxp) > pillW * 0.45) armRows.push(w); });
  const armW = med(armRows) || legW;
  let handW = 0, handL = 0; for (let j = Math.round(hip - 0.25 * (hip - neck)); j < Math.round(hip + 0.35 * (sole - hip)); j++) { let mw = 0; darkRuns(j).forEach(([st0, w]) => { if (Math.abs(st0 + w / 2 - cxp) > pillW * 0.4 && w > mw) mw = w; }); if (mw > armW * 1.5) { handL++; handW = Math.max(handW, mw); } }
  // head crop
  const hh = neck - top + Math.round(maxW * 0.02); let l = W, r = 0; for (let j = top; j < neck; j++) for (let i = 0; i < W; i++) if (opaque(i, j)) { if (i < l) l = i; if (i > r) r = i; }
  x.putImageData(d, 0, 0); const head = document.createElement('canvas'); head.width = r - l + 1; head.height = hh; head.getContext('2d').drawImage(cv, l, top, r - l + 1, hh, 0, 0, r - l + 1, hh);
  // ---- preset: design card is 600x1000, soles at 975; the head top sits at y=30
  const total = sole - top, sc = (975 - 30) / total, hD = (neck - top) * sc, wD = head.width * sc, headW = opts.headW || 1.25;
  const R = wD / (2 * headW), neckY = 30 + hD, torsoTop = neckY + 22 - 0.02 * R, hipD = 30 + (hip - top) * sc;
  const preset = { armStyle: 'master', legStyle: 'master', kneeOut: 0, headW, headDrop: 1.02, body: { R: +R.toFixed(1), hip: +hipD.toFixed(1), torso: +(hipD - torsoTop).toFixed(1), limb: +(legW * sc / 16.2).toFixed(2), armK: +((armW * sc / 15.3) / Math.max(0.2, (legW * sc / 16.2))).toFixed(2), torsoW: +((pillW / 2 * sc) / 42).toFixed(2), hand: +Math.max(0.8, Math.min(1.8, (handW * sc * 0.7) / (0.25 * R))).toFixed(2), foot: 1.0 } };
  return { head, preset, m: { top, neck, hip, sole, total, pillW, legW, armW, handW, handL, headW: head.width, headH: hh } };
}
