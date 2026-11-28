
// ---------------- Oddly Relatable stick cast (Episode 15), drawn on the Pen API above ----------------
// Same approach as roman.js: one function draws a whole character on the 600x1000 design canvas (soles at y=975).
// House style (approved masters): round white head, bold black outline, big white eyes + black pupils,
// simple brows, small mouth, NO nose, slim white body, thin black stick limbs, small solid black mitten hands.
const BLK = "#121212", PAPER = "#f6f1e2", SHADE = "#d5d8e0", SHADE2 = "#e6e8ee", MOUTHC = "#4a1a1f", TONG = "#d9707a";
const lerpN = (a, b, t) => a + (b - a) * t;
const lerpP = (a, b, t) => [lerpN(a[0], b[0], t), lerpN(a[1], b[1], t)];
// filled shape with a black outline
const fo = (p, pts, fill, w) => { const g = p.g; p.path(pts, true); if (fill) { g.fillStyle = fill; g.fill(); } if (w) { g.lineWidth = w; g.strokeStyle = BLK; g.lineJoin = "round"; g.stroke(); } };
const ln = (p, pts, w, col = BLK) => p.stroke(pts, w, col);
// thick coloured stroke with a black rim (white brows, wires)
const rimLine = (p, pts, fill, w, rim) => { p.stroke(pts, w + 2 * rim, BLK); p.stroke(pts, w, fill); };
// tapered stroke (brows, moustache halves)
const taperPts = (pts, w0, w1) => {
  const L = [], Rr = [], n = pts.length;
  for (let i = 0; i < n; i++) {
    const a = pts[Math.max(0, i - 1)], b = pts[Math.min(n - 1, i + 1)], dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1;
    const w = lerpN(w0, w1, i / (n - 1)) / 2, nx = -dy / l * w, ny = dx / l * w;
    L.push([pts[i][0] + nx, pts[i][1] + ny]); Rr.push([pts[i][0] - nx, pts[i][1] - ny]);
  }
  return [...L, ...Rr.reverse()];
};
const qbez = (a, c, b, n = 16) => { const o = []; for (let i = 0; i <= n; i++) { const t = i / n, u = 1 - t; o.push([u * u * a[0] + 2 * u * t * c[0] + t * t * b[0], u * u * a[1] + 2 * u * t * c[1] + t * t * b[1]]); } return o; };

// ---------- expressions: numeric parameter sets (blendable) ----------
// browY: + raises (R units) | browAng: + = inner ends down (cross) | browArc: arch | browAsym: + raises the screen-right brow
// lid: upper lid 0..1 | lidAng: + = lid line slopes down toward the nose (angry) | lidBot: lower-lid squint
// eyeS/pupS: eye and pupil scale | curve: mouth corners up(+)/down(-) | skew: + lifts the screen-right corner
// mw: mouth width | jaw: forced opening (shock) | teeth: show upper teeth when open
export const EXPR = {
  neutral:   { browY: 0.00, browAng: 0, browArc: 0.5, browAsym: 0, lid: 0.12, lidAng: 0, lidBot: 0, eyeS: 1.0, pupS: 1.0, curve: 0.10, skew: 0, mw: 0.30, jaw: 0, teeth: 0 },
  reading:   { browY: -0.02, browAng: 0.05, browArc: 0.45, browAsym: 0, lid: 0.30, lidAng: 0, lidBot: 0, eyeS: 1.0, pupS: 1.0, curve: -0.05, skew: 0, mw: 0.22, jaw: 0, teeth: 0 },
  stern:     { browY: -0.04, browAng: 0.55, browArc: 0.25, browAsym: 0, lid: 0.16, lidAng: 0.35, lidBot: 0.06, eyeS: 0.97, pupS: 1.0, curve: -0.55, skew: 0, mw: 0.32, jaw: 0, teeth: 0 },
  smirk:     { browY: 0.00, browAng: 0.15, browArc: 0.4, browAsym: 0.14, lid: 0.38, lidAng: 0.1, lidBot: 0.08, eyeS: 1.0, pupS: 1.0, curve: 0.45, skew: 0.75, mw: 0.42, jaw: 0, teeth: 0 },
  smug:      { browY: 0.00, browAng: 0.45, browArc: 0.3, browAsym: 0.10, lid: 0.36, lidAng: 0.1, lidBot: 0.05, eyeS: 1.0, pupS: 1.0, curve: 0.40, skew: 0.65, mw: 0.40, jaw: 0, teeth: 0 },
  skeptical: { browY: 0.00, browAng: 0.25, browArc: 0.3, browAsym: 0.20, lid: 0.42, lidAng: 0.12, lidBot: 0.10, eyeS: 1.0, pupS: 1.0, curve: -0.20, skew: -0.45, mw: 0.28, jaw: 0, teeth: 0 },
  shocked:   { browY: 0.17, browAng: -0.55, browArc: 0.65, browAsym: 0, lid: 0.0, lidAng: 0, lidBot: 0, eyeS: 1.3, pupS: 0.55, curve: -0.9, skew: 0, mw: 0.25, jaw: 1.0, teeth: 1 },
  worried:   { browY: 0.10, browAng: -0.45, browArc: 0.55, browAsym: 0, lid: 0.0, lidAng: 0, lidBot: 0, eyeS: 1.12, pupS: 0.8, curve: -0.45, skew: 0.1, mw: 0.26, jaw: 0, teeth: 0 },
  indignant: { browY: -0.08, browAng: 0.75, browArc: 0.15, browAsym: -0.04, lid: 0.42, lidAng: 0.45, lidBot: 0.14, eyeS: 1.0, pupS: 0.95, curve: -0.75, skew: -0.15, mw: 0.34, jaw: 0, teeth: 0 },
};
export const blendExpr = (a, b, t) => { const A = typeof a === "string" ? EXPR[a] : a, B = typeof b === "string" ? EXPR[b] : b, o = {}; for (const k in A) o[k] = lerpN(A[k], B[k] ?? A[k], t); return o; };

// talking mouth shapes: [width scale, opening (R units), roundness 0..1]
export const MOUTHS = { closed: [1, 0, 0], small: [0.85, 0.07, 0.1], mid: [0.95, 0.14, 0.1], round: [0.55, 0.15, 1], wide: [1.1, 0.22, 0], rest: [1, 0, 0] };

// ---------- characters ----------
export const CAST = {
  mortimer: { tufts: true, glasses: true, browStyle: "white", baseFacing: 0 },
  sidney: { combover: true, moustache: true, browStyle: "dark", heavyLid: 0.06, lidShade: true },
  winifred: { bun: "#a84a2a", browStyle: "dark" },
  ronald: { cap: "#7a6a4e", rosy: true, browStyle: "dark" },
  // narrator of the narrated shorts (draft, awaiting owner approval): plain stick man, teal cap, dark brows
  narrator: { cap: "#2f7f86", browStyle: "dark" },
  // narrator design options (drafts): same body and face system, different head details
  optA: { cap: "#2f7f86", browStyle: "dark" },                                    // A: teal cap
  optB: { spiky: "#1b1816", rosy: true, browStyle: "dark" },                      // B: spiky black hair, rosy cheeks
  optC: { beanie: "#e8892b", cuff: "#c96d17", browStyle: "dark" },                // C: orange beanie with a pom
  optD: { hairCap: "#4a3322", glasses: true, browStyle: "dark" },                 // D: brown hair and round glasses
  optE: { bun: "#7a3fa0", rosy: true, browStyle: "dark" },                        // E: purple top bun, rosy cheeks
  // arm / leg style options on Sam (drafts)
  samLine: { hairCap: "#5a3b26", tie: "#c23b3b", browStyle: "dark", body: { R: 172, hip: 688, torso: 228, limb: 1.1, torsoW: 1.3, hand: 1.1, foot: 1.05 } },
  samThick: { hairCap: "#5a3b26", tie: "#c23b3b", browStyle: "dark", limbStyle: "thick", body: { R: 172, hip: 688, torso: 228, limb: 1.1, torsoW: 1.3, hand: 1.1, foot: 1.05 } },
  samPipeArms: { hairCap: "#5a3b26", tie: "#c23b3b", browStyle: "dark", armStyle: "pipe", body: { R: 172, hip: 688, torso: 228, limb: 1.1, torsoW: 1.3, hand: 1.1, foot: 1.05 } },
  samPipeAll: { hairCap: "#5a3b26", tie: "#c23b3b", browStyle: "dark", limbStyle: "pipe", body: { R: 172, hip: 688, torso: 228, limb: 1.1, torsoW: 1.3, hand: 1.1, foot: 1.05 } },
  // body options (drafts), all on the beanie head
  bodyA: { beanie: "#e8892b", cuff: "#c96d17", browStyle: "dark" },
  bodyB: { beanie: "#e8892b", cuff: "#c96d17", browStyle: "dark", body: { R: 180, hip: 700, torso: 205, limb: 1.25, torsoW: 1.35, hand: 1.15, foot: 1.1 } },
  bodyC: { beanie: "#e8892b", cuff: "#c96d17", browStyle: "dark", body: { R: 172, hip: 690, torso: 225, limb: 1.1, torsoW: 1.65, hand: 1.1, foot: 1.05 } },
  bodyD: { beanie: "#e8892b", cuff: "#c96d17", browStyle: "dark", body: { R: 150, hip: 640, torso: 270, limb: 0.9, torsoW: 0.85 } },
  bodyE: { beanie: "#e8892b", cuff: "#c96d17", browStyle: "dark", body: { R: 205, hip: 722, torso: 170, limb: 1.2, torsoW: 1.1, hand: 1.2, foot: 1.15 } },
  bodyF: { beanie: "#e8892b", cuff: "#c96d17", browStyle: "dark", body: { R: 168, hip: 665, torso: 250, limb: 1.35, torsoW: 1.15, hand: 1.3, foot: 1.1 } },
  // new characters for the narrated shorts (drafts): an everyman who tells small lies
  samN: { hairCap: "#5a3b26", tie: "#c23b3b", browStyle: "dark", body: { R: 172, hip: 688, torso: 228, limb: 1.1, torsoW: 1.3, hand: 1.1, foot: 1.05 } },
  devN: { spiky: "#1b1816", glasses: true, tie: "#2f5fb0", browStyle: "dark", body: { R: 180, hip: 700, torso: 205, limb: 1.25, torsoW: 1.35, hand: 1.15, foot: 1.1 } },
  moN: { beanie: "#e8892b", cuff: "#c96d17", rosy: true, browStyle: "dark", body: { R: 172, hip: 690, torso: 225, limb: 1.1, torsoW: 1.65, hand: 1.1, foot: 1.05 } },
  kitN: { bun: "#7a3fa0", rosy: true, tie: "#e0b030", browStyle: "dark", body: { R: 160, hip: 650, torso: 262, limb: 0.95, torsoW: 0.95, hand: 1.05 } },
  optF: { headband: "#d23a3a", spiky: "#2b211c", browStyle: "dark", heavyLid: 0.04 }, // F: red headband, short dark hair, relaxed lids
};

// ---------- head parts ----------
const eyeDraw = (p, ex, ey, rx, ry, E, look, lidK, side, C, R) => {
  const ow = 0.038 * R, pts = ellPts(ex, ey, rx, ry, 0, 360, 0, 40);
  fo(p, pts, "#ffffff", 0);
  p.clip(pts, () => {
    p.ell(ex - 0.45 * rx, ey + 0.55 * ry, rx * 0.9, ry * 0.65, SHADE2, 0);
    // pupil
    const pr = 0.4 * Math.min(rx, ry) * E.pupS, mx = rx - pr * 0.95, my = ry - pr * 0.95;
    const px = ex + look[0] * mx * 0.85, py = ey + look[1] * my * 0.8;
    p.dot(px, py, pr, BLK);
    p.dot(px - pr * 0.38, py - pr * 0.4, pr * 0.3, "#ffffff");
    // upper lid (white skin + line), slope toward the nose for anger
    const lid = Math.min(1, lidK);
    if (lid > 0.01) {
      const yl = ey - ry + 2 * ry * lid, sl = E.lidAng * ry * 0.5 * side; // side=-1 left eye: inner corner is +x
      const a = [ex - rx * 1.2, yl - sl * 1.2], b = [ex + rx * 1.2, yl + sl * 1.2];
      fo(p, [[ex - rx * 1.3, ey - ry * 1.4], [ex + rx * 1.3, ey - ry * 1.4], b, a], "#ffffff", 0);
      if (lid < 0.97) { p.stroke([a, b], 0.05 * ry, SHADE); p.stroke([[a[0], a[1] + ry * 0.07], [b[0], b[1] + ry * 0.07]], ry * 0.12, "rgba(170,175,190,.35)"); }
      if (C.lidShade) fo(p, [[ex - rx * 1.3, ey - ry * 1.4], [ex + rx * 1.3, ey - ry * 1.4], [b[0], b[1] - ry * 0.02], [a[0], a[1] - ry * 0.02]], "rgba(190,194,206,.55)", 0);
      ln(p, [a, b], ow * 0.95);
    }
    if (E.lidBot > 0.01 && lid < 0.97) {
      const yb = ey + ry - 2 * ry * E.lidBot;
      fo(p, [[ex - rx * 1.3, ey + ry * 1.4], [ex + rx * 1.3, ey + ry * 1.4], [ex + rx * 1.2, yb], [ex - rx * 1.2, yb]], "#ffffff", 0);
      ln(p, [[ex - rx * 1.1, yb + ry * 0.05], [ex, yb - ry * 0.03], [ex + rx * 1.1, yb + ry * 0.05]], ow * 0.7);
    }
  });
  fo(p, pts, null, ow);
  if (lidK >= 0.97) ln(p, qbez([ex - rx, ey + ry * 0.1], [ex, ey + ry * 0.45], [ex + rx, ey + ry * 0.1]), ow * 1.1); // closed: lash line
};

const browDraw = (p, bx, by, w, E, side, C, R) => {
  // side: -1 = screen-left brow, +1 = screen-right brow. inner end is toward the face centre.
  const inner = -side, ang = E.browAng * 0.22 * R, asym = E.browAsym * R * (side > 0 ? 1 : -0.4);
  const yIn = by + ang - asym, yOut = by - ang * 0.25 - asym;
  const xIn = bx + inner * w * 0.5, xOut = bx - inner * w * 0.5;
  const mid = [(xIn + xOut) / 2, (yIn + yOut) / 2 - E.browArc * 0.16 * R];
  const pts = qbez([xOut, yOut], mid, [xIn, yIn], 14);
  if (C.browStyle === "white") { // Mortimer: bushy white brows with a black rim
    const sh = taperPts(pts, 0.06 * R, 0.1 * R);
    fo(p, sh, "#ffffff", 0.035 * R);
    ln(p, qbez([xOut + inner * w * 0.15, yOut + 0.01 * R], [mid[0], mid[1] + 0.035 * R], [xIn - inner * w * 0.12, yIn + 0.02 * R], 10), 0.012 * R, "#b9bcc6");
  } else {
    fo(p, taperPts(pts, 0.055 * R, 0.1 * R), "#221d1a", 0);
  }
};

// mouth: base line through (mx,my), width W, corners curve c, skew s, opening H, roundness rd
const mouthDraw = (p, mx, my, W, c, s, H, rd, teeth, R, C) => {
  const n = 22, base = (t) => [mx + t * W / 2, my - c * 0.11 * R * t * t + c * 0.03 * R - s * 0.07 * R * t];
  if (H < 0.012 * R) {
    const pts = []; for (let i = 0; i <= n; i++) pts.push(base(-1 + 2 * i / n));
    ln(p, pts, 0.042 * R);
    // little cheek tick on the lifted corner (master smile)
    if (c > 0.3) { const sd = s >= 0 ? 1 : -1, q = base(sd); ln(p, [[q[0] - sd * 0.02 * R, q[1] - 0.05 * R], [q[0] + sd * 0.05 * R, q[1] + 0.03 * R]], 0.026 * R); }
    if (c < -0.5) { for (const sd of [-1, 1]) { const q = base(sd); ln(p, [[q[0] + sd * 0.01 * R, q[1] - 0.01 * R], [q[0] + sd * 0.05 * R, q[1] + 0.05 * R]], 0.024 * R); } }
    return;
  }
  const up = [], lo = [];
  for (let i = 0; i <= n; i++) {
    const t = -1 + 2 * i / n, [x, y] = base(t), k = Math.pow(Math.max(0, 1 - t * t), rd > 0.5 ? 0.5 : 0.75);
    up.push([x, y - H * 0.28 * k]); lo.push([x, y + H * 0.72 * k]);
  }
  const shape = [...up, ...lo.reverse()];
  fo(p, shape, MOUTHC, 0);
  p.clip(shape, () => {
    if (H > 0.09 * R) p.ell(mx + s * 0.03 * R, my + H * 0.62, W * 0.32, H * 0.38, TONG, 0);
    if (teeth && H > 0.1 * R) { const tp = up.map(([x, y]) => [x, y + 0.045 * R]); fo(p, [...up, ...tp.reverse()], "#ffffff", 0); }
  });
  fo(p, shape, null, 0.04 * R);
};

/** a whole head. Returns nothing; draws at (hx,hy) radius R. o: E (expr params), mouth, look, blink, facing, pitch */
export const stickHead = (p, C, hx, hy, R, o) => {
  const E = o.E, f = o.facing || 0, pitch = o.pitch || 0;
  const ow = 0.048 * R;
  if (!o.faceOnly) {
  // hair behind the head
  if (C.bun) { fo(p, ellPts(hx + 0.05 * R, hy - 1.0 * R, 0.42 * R, 0.34 * R), C.bun, ow * 0.9); }
  // Mortimer tufts (behind the head outline so the head rim overlaps them)
  const tuft = (sd) => {
    const x0 = hx + sd * 0.86 * R, y0 = hy - 0.28 * R, pts = [];
    const lobes = [[0.0, -0.46], [0.22, -0.44], [0.3, -0.3], [0.44, -0.24], [0.32, -0.1], [0.46, -0.02], [0.3, 0.06], [0.36, 0.2], [0.16, 0.16], [0.12, 0.3], [0.0, 0.26]];
    for (const [dx, dy] of lobes) pts.push([x0 + sd * dx * R, y0 + dy * R]);
    pts.push([x0 - sd * 0.12 * R, y0 + 0.1 * R], [x0 - sd * 0.12 * R, y0 - 0.25 * R]);
    fo(p, pts, "#f2f3f6", ow * 0.8);
    p.clip(pts, () => { p.ell(x0 + sd * 0.05 * R, y0 + 0.06 * R, 0.16 * R, 0.12 * R, "#d4d7de", 0); });
    ln(p, [[x0 + sd * 0.1 * R, y0 - 0.12 * R], [x0 + sd * 0.22 * R, y0 - 0.04 * R]], 0.018 * R, "#9aa0ab");
    ln(p, [[x0 + sd * 0.08 * R, y0 + 0.04 * R], [x0 + sd * 0.2 * R, y0 + 0.12 * R]], 0.018 * R, "#9aa0ab");
  };
  if (C.tufts) { tuft(-1); tuft(1); }
  // head: white with a soft grey crescent on the lower-left (light from upper right)
  const hp = ellPts(hx, hy, R, R, 0, 360, 0, 72);
  fo(p, hp, "#ffffff", 0);
  p.clip(hp, () => {
    const g = p.g, [gx, gy] = p.P(hx + 0.24 * R, hy - 0.2 * R), gr = g.createRadialGradient(gx, gy, 0, gx, gy, 1.2 * R);
    gr.addColorStop(0, "#ffffff"); gr.addColorStop(0.74, "#ffffff"); gr.addColorStop(0.86, "#e4e6ec"); gr.addColorStop(1, "#c3c7d2");
    p.path(hp, true); g.fillStyle = gr; g.fill();
    if (C.rosy) for (const sd of [-1, 1]) p.ell(hx + f * 0.3 * R + sd * 0.42 * R, hy + 0.25 * R, 0.13 * R, 0.08 * R, "rgba(232,120,120,.45)", 0);
  });
  fo(p, hp, null, ow);
  }
  // features
  const fx = hx + f * 0.3 * R, fy = hy + pitch * 0.14 * R;
  const eyeY = fy - 0.09 * R - Math.max(0, E.eyeS - 1) * 0.12 * R, sep = 0.35 * R * Math.max(1, 0.25 + 0.8 * E.eyeS);
  const rx = 0.28 * R * E.eyeS, ry = 0.31 * R * E.eyeS;
  const lidK = Math.max(E.lid + (C.heavyLid || 0) * (1 - Math.min(1, E.jaw)), o.blink || 0);
  const look = o.look || [0, 0];
  const exs = [fx - sep * (1 - f * 0.12), fx + sep * (1 + f * 0.12)];
  const sc = [1 - Math.max(0, f) * 0.14, 1 + Math.min(0, f) * 0.14]; // far eye slightly narrower
  exs.forEach((ex, i) => eyeDraw(p, ex, eyeY, rx * sc[i], ry, E, look, lidK, i ? 1 : -1, C, R));
  const browBase = eyeY - ry - 0.1 * R + E.browY * R;
  exs.forEach((ex, i) => browDraw(p, ex + (i ? 0.02 : -0.02) * R, browBase, 0.34 * R * sc[i], E, i ? 1 : -1, C, R));
  if (!o.faceOnly) {
  // comb-over strands across the top
  if (C.combover) {
    const strands = [[-0.62, -0.62, 0.0, -1.2, 0.72, -0.84], [-0.48, -0.8, 0.1, -1.26, 0.56, -0.98], [-0.72, -0.46, -0.1, -1.06, 0.66, -0.68], [-0.3, -0.92, 0.18, -1.18, 0.4, -1.04]];
    strands.forEach(([a, b, c, d, e2, f2], i) => ln(p, qbez([hx + a * R, hy + b * R], [hx + c * R, hy + d * R], [hx + e2 * R, hy + f2 * R]), (i === 3 ? 0.02 : 0.028) * R, "#2a2420"));
  }
  if (C.hairCap) { // short hair: a dome hugging the top of the head, with a side-swept edge
    const hc = [...ellPts(hx, hy - 0.08 * R, 1.0 * R, 0.98 * R, 195, 345, 0, 30), [hx + 0.62 * R, hy - 0.5 * R], [hx + 0.1 * R, hy - 0.66 * R], [hx - 0.55 * R, hy - 0.58 * R]];
    fo(p, hc, C.hairCap, ow * 0.9);
    ln(p, qbez([hx - 0.7 * R, hy - 0.62 * R], [hx - 0.1 * R, hy - 0.98 * R], [hx + 0.62 * R, hy - 0.52 * R], 12), 0.022 * R, "rgba(255,255,255,.28)");
  }
  if (C.spiky) { // five spikes on the crown
    const sp = [];
    const n = 5;
    for (let i = 0; i < n; i++) { const a0 = Math.PI * (1.12 + 0.76 * i / n), a1 = Math.PI * (1.12 + 0.76 * (i + 0.5) / n), a2 = Math.PI * (1.12 + 0.76 * (i + 1) / n), h = (i % 2 ? 1.28 : 1.42) * R;
      sp.push([hx + Math.cos(a0) * 0.98 * R, hy + Math.sin(a0) * 0.98 * R], [hx + Math.cos(a1) * h, hy + Math.sin(a1) * h], [hx + Math.cos(a2) * 0.98 * R, hy + Math.sin(a2) * 0.98 * R]); }
    fo(p, sp, C.spiky, ow * 0.9);
  }
  if (C.beanie) { // knitted beanie: dome, folded cuff, pom
    const dome = [...ellPts(hx, hy - 0.3 * R, 1.0 * R, 0.95 * R, 180, 360, 0, 36)];
    fo(p, dome, C.beanie, ow * 0.9);
    for (let i = -3; i <= 3; i++) ln(p, [[hx + i * 0.26 * R, hy - 0.4 * R], [hx + i * 0.2 * R, hy - 1.18 * R]], 0.014 * R, "rgba(0,0,0,.18)");
    const cuff = rrect(hx - 1.02 * R, hy - 0.52 * R, hx + 1.02 * R, hy - 0.2 * R, 0.07 * R);
    fo(p, cuff, C.cuff, ow * 0.9);
    p.dot(hx, hy - 1.3 * R, 0.17 * R, C.cuff); p.path(ellPts(hx, hy - 1.3 * R, 0.17 * R, 0.17 * R), true); p.g.lineWidth = ow * 0.8; p.g.strokeStyle = BLK; p.g.stroke();
  }
  if (C.headband) ln(p, qbez([hx - 0.99 * R, hy - 0.3 * R], [hx, hy - 0.5 * R], [hx + 0.99 * R, hy - 0.3 * R], 20), 0.15 * R, C.headband), ln(p, qbez([hx - 0.99 * R, hy - 0.3 * R], [hx, hy - 0.5 * R], [hx + 0.99 * R, hy - 0.3 * R], 20), 0.012 * R, BLK);
  if (C.cap) {
    const cp = [...ellPts(hx, hy - 0.5 * R, 0.98 * R, 0.55 * R, 180, 360, 0, 30), [hx + 1.25 * R, hy - 0.42 * R], [hx + 0.9 * R, hy - 0.36 * R]];
    fo(p, cp, C.cap, ow * 0.9);
    ln(p, [[hx - 0.9 * R, hy - 0.48 * R], [hx + 0.9 * R, hy - 0.44 * R]], 0.03 * R);
  }
  }
  // mouth
  const M = o.mouthM || MOUTHS[o.mouth || "closed"] || MOUTHS.closed;   // mouthM: [width scale, opening, roundness] already blended by the caller
  const talkOpen = M[1] * R * (o.talkAmp ?? 1);
  const jawOpen = E.jaw * 0.46 * R;
  const H = Math.max(talkOpen, jawOpen);
  const rd = jawOpen > talkOpen ? 0.6 : M[2];
  const W = E.mw * R * 2 * (jawOpen > talkOpen ? 0.95 : M[0]);
  const mx = fx + 0.02 * R, my = fy + 0.43 * R;
  const curve = H > 0.05 * R ? (jawOpen > talkOpen ? E.curve : E.curve * 0.5) : E.curve;
  mouthDraw(p, mx, my, W, curve, E.skew, H, rd, E.teeth, R, C);
  if (C.moustache) { // pencil moustache: two thin tapered halves, lifted with the upper lip
    const yy = my - 0.12 * R - H * 0.22 - E.skew * 0.02 * R;
    for (const sd of [-1, 1]) {
      const sk = sd * E.skew * 0.035 * R;
      const pts = qbez([mx + sd * 0.03 * R, yy - sk * 0.3], [mx + sd * 0.17 * R, yy - 0.05 * R - sk], [mx + sd * 0.3 * R, yy + 0.02 * R - sk * 1.4], 10);
      fo(p, taperPts(pts, 0.07 * R, 0.03 * R), "#57504a", 0.012 * R);
      for (let k = 1; k < 4; k++) { const q = pts[k * 2 + 1]; ln(p, [[q[0], q[1] - 0.015 * R], [q[0] + sd * 0.01 * R, q[1] + 0.02 * R]], 0.008 * R, "#3a3430"); }
    }
  }
  // Mortimer's small round wire glasses, sitting low on the eyes
  if (C.glasses) {
    const gy = eyeY + 0.24 * R + (o.glassesDrop || 0) * R, gr = 0.155 * R;
    const gxs = [exs[0] + 0.06 * R, exs[1] - 0.06 * R];
    gxs.forEach((gx) => {
      const rp = ellPts(gx, gy, gr, gr * 0.95, 0, 360, 0, 32);
      const g = p.g; g.save(); g.globalAlpha = 0.35; fo(p, rp, "#cfe2ee", 0); g.restore();
      p.clip(rp, () => ln(p, [[gx - gr * 0.5, gy + gr * 0.1], [gx + gr * 0.1, gy - gr * 0.55]], 0.03 * R, "rgba(255,255,255,.9)"));
      fo(p, rp, null, 0.026 * R);
    });
    ln(p, qbez([gxs[0] + gr, gy - 0.02 * R], [(gxs[0] + gxs[1]) / 2, gy - 0.09 * R], [gxs[1] - gr, gy - 0.02 * R], 8), 0.022 * R);
    // temple wires out to the sides of the head
    const yT = gy - 0.06 * R;
    ln(p, [[gxs[0] - gr, gy - 0.02 * R], [hx - Math.sqrt(Math.max(0, R * R - (yT - hy) ** 2)) * 0.99, yT - 0.06 * R]], 0.02 * R);
    ln(p, [[gxs[1] + gr, gy - 0.02 * R], [hx + Math.sqrt(Math.max(0, R * R - (yT - hy) ** 2)) * 0.99, yT - 0.06 * R]], 0.02 * R);
  }
};

// mitten hand: solid black oval with a thumb, pointing along `dir` (radians)
const hand = (p, x, y, dir, R, thumbSide = 1) => {
  // (x, y) is the wrist: the mitten starts there and extends along `dir`, so the arm line ends inside its base
  const ca = Math.cos(dir), sa = Math.sin(dir), L = 0.2 * R, W = 0.125 * R;
  const cx = x + ca * L * 0.72, cy = y + sa * L * 0.72, deg = dir * 180 / Math.PI - 90;
  // thumb first (behind), then the palm over its root, so the two read as one mitten
  const tx = cx + Math.cos(dir + thumbSide * 1.35) * W * 0.95 - ca * L * 0.15, ty = cy + Math.sin(dir + thumbSide * 1.35) * W * 0.95 - sa * L * 0.15;
  fo(p, ellPts(tx, ty, 0.055 * R, 0.1 * R, 0, 360, (dir + thumbSide * 0.8) * 180 / Math.PI - 90, 14), BLK, 0);
  fo(p, ellPts(cx, cy, W, L, 0, 360, deg, 28), BLK, 0);
  // wrist: a short black collar so the line flows into the hand
  ln(p, [[x - ca * 0.05 * R, y - sa * 0.05 * R], [cx, cy]], 0.11 * R, BLK);
};

/** stickFront(p, who, opts)
 * opts: expr (name | params) | exprB + exprT (blend), mouth, talkAmp, look [x,y], blink, facing, pitch, headRoll (deg), bodyLean (deg),
 *       pose: "hang" | "read" | "lap" | "recoil" | "cross" (or poseB + poseT blend), paperY 0 (reading) .. 1 (lowered), paperTilt,
 *       seated (bool), headDX/headDY (design units, head recoil), squash (0..), glassesDrop */
export const stickFront = (p, who, opts = {}) => {
  const C = CAST[who] || {};
  let E = typeof opts.expr === "object" ? opts.expr : EXPR[opts.expr || "neutral"];
  if (opts.exprB) E = blendExpr(E, opts.exprB, opts.exprT || 0);
  // body proportions (per character, C.body): head radius, hip height (smaller = shorter legs), torso length, limb weight, torso width, hand and foot scale
  const B = { R: 165, hip: 672, torso: 240, limb: 1, torsoW: 1, hand: 1, foot: 1, ...(C.body || {}) };
  const R = B.R, cx = 300, sole = 975, seated = !!opts.seated;
  const hipY = seated ? B.hip + 48 : B.hip, torsoLen = B.torso, neckLen = 22;
  // limb style per character: "line" (thin black, default) | "thick" (heavier black) | "pipe" (white tube with a black outline)
  const armStyle = C.armStyle || C.limbStyle || "line", legStyle = C.legStyle || C.limbStyle || "line";
  const limbLine = (style, pts, w) => style === "pipe" ? rimLine(p, pts, "#ffffff", w * 1.9, 4.2) : style === "thick" ? ln(p, pts, w * 1.7) : ln(p, pts, w);
  const armLine = (pts, w) => limbLine(armStyle, pts, w), legLine = (pts, w) => limbLine(legStyle, pts, w);
  const squash = opts.squash || 0;
  const torsoTop = hipY - torsoLen * (1 - squash * 0.5);
  const lean = (opts.bodyLean || 0) * Math.PI / 180;
  // body lean pivots at the hips
  const rotP = (x, y) => { const dx = x - cx, dy = y - hipY; return [cx + dx * Math.cos(lean) - dy * Math.sin(lean), hipY + dx * Math.sin(lean) + dy * Math.cos(lean)]; };
  const neck = rotP(cx + 4, torsoTop);
  const hx = neck[0] + (opts.headDX || 0), hy = neck[1] - neckLen - R + (opts.headDY || 0) + squash * 20;
  // ---- legs + feet ----
  if (seated) {
    for (const sd of [-1, 1]) {
      const hip = [cx + sd * 18, hipY - 6], knee = [cx + sd * 46, hipY + 40], foot = [cx + sd * 52, sole - 12];
      legLine([hip, knee, foot], 9 * B.limb);
      fo(p, ellPts(foot[0] + sd * 14, sole - 8, 34 * B.foot, 14 * B.foot, 0, 360, 0, 20), BLK, 0);
    }
  } else {
    for (const sd of [-1, 1]) {
      const hip = [cx + sd * 16, hipY - 4], foot = [cx + sd * 40, sole - 14];
      legLine([hip, [cx + sd * 24, (hipY + sole) / 2], foot], 9 * B.limb);
      fo(p, ellPts(foot[0] + sd * 14, sole - 9, 42 * B.foot, 17 * B.foot, 0, 360, 0, 20), BLK, 0);
    }
  }
  // ---- arm poses (per side): elbow + hand ----
  const sh = (sd) => rotP(cx + sd * 26, torsoTop + 14);
  const paperY = opts.paperY || 0;
  const pw = 1.1 * R, ph = 1.35 * R, pTop = torsoTop - 0.02 * R + paperY * 1.15 * R, pcx = cx + 6;
  const poses = {
    hang: (sd) => ({ e: [cx + sd * 74, torsoTop + 130], h: [cx + sd * 92, hipY + 30] }),
    read: (sd) => ({ e: [pcx + sd * (pw / 2 + 0.42 * R), pTop + ph * 0.95], h: [pcx + sd * (pw / 2 - 0.02 * R), pTop + ph * 0.72] }),
    lap: (sd) => ({ e: [cx + sd * 78, hipY - 40], h: [cx + sd * 52, hipY + 30] }),
    recoil: (sd) => ({ e: [cx + sd * 96, torsoTop + 120], h: [cx + sd * 92, torsoTop + 10] }),
    cross: (sd) => ({ e: [cx + sd * 66, torsoTop + 128], h: [cx - sd * 34, torsoTop + 96 + sd * 8] }),
  };
  const armAt = (sd) => {
    const A = poses[opts.pose || "hang"](sd);
    if (opts.poseB) { const B = poses[opts.poseB](sd), t = opts.poseT || 0; return { e: lerpP(A.e, B.e, t), h: lerpP(A.h, B.h, t) }; }
    return A;
  };
  const arms = [-1, 1].map((sd) => ({ sd, s: sh(sd), ...armAt(sd) }));
  const crossed = (opts.pose === "cross" && !opts.poseB) || (opts.poseB === "cross" && (opts.poseT || 0) > 0.5);
  // ---- torso: slim white tapered pill ----
  const tw0 = 30 * B.torsoW, tw1 = 42 * B.torsoW, tb = hipY + 8;
  const tpts = [];
  for (let i = 0; i <= 12; i++) { const t = i / 12, y = lerpN(torsoTop, tb - tw1, t), w = lerpN(tw0, tw1, t * t); tpts.push(rotP(cx + 4 + w, y)); }
  for (let i = 0; i <= 16; i++) { const a = Math.PI * i / 16; tpts.push(rotP(cx + 4 + Math.cos(a) * tw1, tb - tw1 + Math.sin(a) * tw1 * 1.0)); }
  for (let i = 12; i >= 0; i--) { const t = i / 12, y = lerpN(torsoTop, tb - tw1, t), w = lerpN(tw0, tw1, t * t); tpts.push(rotP(cx + 4 - w, y)); }
  for (let i = 1; i < 14; i++) { const a2 = Math.PI + Math.PI * i / 14; tpts.push(rotP(cx + 4 + Math.cos(a2) * tw0, torsoTop + Math.sin(a2) * tw0 * 0.5)); }   // rounded shoulders
  // arms behind the paper are drawn before it; hands on top
  const drawArm = (a) => { armLine([a.s, a.e, a.h], 8.5 * B.limb); };
  fo(p, tpts, "#ffffff", 0);
  p.clip(tpts, () => { p.ell(cx - 40, (torsoTop + tb) / 2 + 30, 34, torsoLen * 0.62, SHADE2, 0); });
  if (C.tie) p.clip(tpts, () => { // knot + blade, hanging from the neck
    const k = rotP(cx + 4, torsoTop + 8), b = [rotP(cx + 4 - 13, torsoTop + 150), rotP(cx + 4, torsoTop + 178), rotP(cx + 4 + 13, torsoTop + 150)];
    fo(p, [rotP(cx + 4 - 12, torsoTop + 2), rotP(cx + 4 + 12, torsoTop + 2), rotP(cx + 4 + 8, torsoTop + 22), rotP(cx + 4 - 8, torsoTop + 22)], C.tie, 3);
    fo(p, [rotP(cx + 4 - 8, torsoTop + 22), rotP(cx + 4 + 8, torsoTop + 22), rotP(cx + 4 + 16, torsoTop + 150), rotP(cx + 4, torsoTop + 182), rotP(cx + 4 - 16, torsoTop + 150)], C.tie, 3);
    ln(p, [rotP(cx + 4 - 5, torsoTop + 60), rotP(cx + 4 + 6, torsoTop + 52)], 4, "rgba(255,255,255,.35)");
  });
  fo(p, tpts, null, 7);
  // neck: thick black stick from the torso top into the head
  const neckTop = [hx - (opts.facing || 0) * 4, hy + R * 0.9];
  ln(p, [rotP(cx + 4, torsoTop + 6), neckTop], 13);
  if (crossed) { // crossed arms: upper arms first, then forearms across the chest
    for (const a of arms) armLine([a.s, a.e], 8.5 * B.limb);
    for (const a of arms) { armLine([a.e, a.h], 8.5 * B.limb); hand(p, a.h[0], a.h[1], Math.atan2(a.h[1] - a.e[1], a.h[0] - a.e[0]), R * B.hand, -a.sd); }
  } else if ((opts.pose || "hang") === "read") {
    for (const a of arms) drawArm(a);
    // the will: cream sheet with grey ruled lines (no readable text)
    const tilt = (opts.paperTilt || 0) * Math.PI / 180, pc = [pcx, pTop + ph / 2];
    const rot = (x, y) => [pc[0] + (x - pc[0]) * Math.cos(tilt) - (y - pc[1]) * Math.sin(tilt), pc[1] + (x - pc[0]) * Math.sin(tilt) + (y - pc[1]) * Math.cos(tilt)];
    const sheet = [rot(pcx - pw / 2, pTop), rot(pcx + pw / 2, pTop + 4), rot(pcx + pw / 2 + 3, pTop + ph), rot(pcx - pw / 2 - 2, pTop + ph - 3)];
    fo(p, sheet, PAPER, 0);
    p.clip(sheet, () => {
      p.ell(pcx - pw * 0.55, pTop + ph * 0.7, pw * 0.3, ph * 0.6, "#e7e0cc", 0);
      for (let i = 0; i < 9; i++) { const y = pTop + 0.16 * R + i * 0.11 * R, x0 = pcx - pw * 0.36, x1 = pcx + pw * (i % 3 === 2 ? 0.05 : 0.34); ln(p, [rot(x0, y), rot(x1, y + 1)], 3.2, "#b9b2a0"); }
    });
    fo(p, sheet, null, 6);
    for (const a of arms) hand(p, a.h[0], a.h[1], Math.atan2(a.h[1] - a.e[1], a.h[0] - a.e[0]), R * B.hand, -a.sd);
  } else {
    for (const a of arms) { drawArm(a); hand(p, a.h[0], a.h[1], Math.atan2(a.h[1] - a.e[1], a.h[0] - a.e[0]), R * B.hand, -a.sd); }
  }
  // ---- head (roll about the neck) ----
  const roll = (opts.headRoll || 0) + (opts.bodyLean || 0);
  p.rot = roll ? [roll * Math.PI / 180, neckTop[0], neckTop[1]] : null;
  stickHead(p, C, hx, hy, R, { E, mouth: opts.mouth, talkAmp: opts.talkAmp, look: opts.look, blink: opts.blink, facing: opts.facing, pitch: opts.pitch, glassesDrop: opts.glassesDrop });
  p.rot = null;
};
/** head centre in design units for a given pose (for aligning cameras / focus) */
export const stickHeadY = (seated) => (seated ? 720 : 672) - 240 - 22 - 165;
