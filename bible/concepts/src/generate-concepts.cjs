'use strict';
// Visual-direction concept generator (Phase 1.5).
// THROWAWAY CONCEPT CODE: draws original vector concept art for comparison. It is NOT production tooling,
// does not touch the renderer, makes no network calls and uses no AI service.
// It reuses the `sharp` package that is already installed and locked for the Skill (no new dependency).
// Run: node bible/concepts/src/generate-concepts.cjs   (writes into bible/concepts/)
const fs = require('fs');
const path = require('path');
const {createRequire} = require('module');
const ROOT = path.resolve(__dirname, '..', '..', '..');
const sharp = createRequire(path.join(ROOT, 'skills/directing-stickman-videos/package.json'))('sharp');
const OUT = path.resolve(__dirname, '..');
fs.mkdirSync(path.join(OUT, 'svg'), {recursive: true});

const PH_GARMENT = '#8795AD'; // placeholder garment colour (neutral slate)
const INK = '#262A3B', TEAL = '#17A398', SKIN = '#D3D8E0', HAIR = '#3A4152', CANVAS = '#FBF8F2', SKY = '#8FD3F4';
const FONT = 'Arial, Helvetica, sans-serif';
const pt = p => p.map(n => +n.toFixed(1)).join(',');
const pts = a => a.map(pt).join(' ');

// ---------------------------------------------------------------- FEMI (shared character, same design in A and B)
// Local coordinates: feet centre = (0,0), y negative is up, native height ~300 units.
const POSES = {
  text: { // "The Text": weight shifted, reading the message
    hip: [-4, -135], sh: [0, -212], head: [-3, -262], tilt: -7, face: 'worried',
    legL: [[-14, -135], [-19, -68], [-24, 0]], legR: [[14, -135], [26, -70], [36, -2]],
    armL: [[-24, -210], [-35, -160], [-30, -118]], armR: [[24, -210], [46, -172], [33, -203]],
    phone: [38, -224, 10], fx: [],
  },
  frozen: { // perfectly vertical = frozen with fear
    hip: [0, -135], sh: [0, -212], head: [0, -262], tilt: 0, face: 'shock',
    legL: [[-12, -135], [-12, -68], [-12, 0]], legR: [[12, -135], [12, -68], [12, 0]],
    armL: [[-24, -210], [-28, -165], [-29, -122]], armR: [[24, -210], [28, -165], [29, -122]],
    phone: null, fx: ['lines', 'sweat'],
  },
  plead: { // hands clasped, leaning in, knees bent
    hip: [-6, -130], sh: [8, -205], head: [14, -253], tilt: 9, face: 'plead',
    legL: [[-16, -130], [-30, -66], [-24, 0]], legR: [[10, -130], [26, -66], [20, 0]],
    armL: [[-16, -203], [-30, -168], [2, -184]], armR: [[32, -203], [44, -168], [8, -186]],
    phone: null, clasp: [5, -185], fx: ['sweat2'],
  },
};

// Remap authored pose heights to the spec'd 3.6-head proportions (shorter legs/torso, larger relative head).
const G = y => y >= -135 ? y * 0.711 : y >= -212 ? -96 + (y + 135) * 0.805 : -158 + (y + 212) * 0.8;
const mp = a => [a[0], G(a[1]), ...a.slice(2)];
const mapPose = p => { const q = {...p}; for (const k of ['hip', 'sh', 'head', 'phone', 'clasp']) if (q[k]) q[k] = mp(q[k]); for (const k of ['legL', 'legR', 'armL', 'armR']) q[k] = q[k].map(mp); return q; };
const NATIVE_H = 246;

function femi(id, poseName, o) {
  // o.style: 'A' (Inkblock) | 'B' (2.5D Modern Pop). o.shade: 0 flat | 1 cel-shaded
  // style 'C' = thin-limb variant (owner's new reference direction): thin ink limbs, smaller hands, larger eyes and brows
  const P = mapPose(POSES[poseName]), A = o.style === 'A', C = o.style === 'C';
  const ow = A ? 6 : C ? 3.5 : 4, lw = A ? 8 : C ? 4.5 : 6, fw = A ? 4.5 : C ? 3 : 3.5, hr = A ? 9 : C ? 7 : 8;
  const [hx, hy] = P.hip, [sx, sy] = P.sh;
  const tp = [[sx - 25, sy], [sx + 25, sy], [hx + 21, hy], [hx - 21, hy]];
  const limb = ps => `<polyline points="${pts(ps)}" fill="none" stroke="${INK}" stroke-width="${lw}" stroke-linecap="round" stroke-linejoin="round"/>`;
  const shoe = f => `<rect x="${f[0] - 15}" y="${f[1] - 11}" width="30" height="14" rx="7" fill="#6B7280" stroke="${INK}" stroke-width="${ow - 1}"/>`;
  const hand = h => `<circle cx="${h[0]}" cy="${h[1]}" r="${hr}" fill="${SKIN}" stroke="${INK}" stroke-width="${ow - 1}"/>`;
  let s = `<g id="${id}">`;
  s += limb(P.legL) + limb(P.legR) + shoe(P.legL[2]) + shoe(P.legR[2]);
  // torso: outline layer then fill layer (rounded corners through round joins)
  s += `<polygon points="${pts(tp)}" fill="${INK}" stroke="${INK}" stroke-width="${14 + ow * 2}" stroke-linejoin="round"/>`;
  s += `<polygon points="${pts(tp)}" fill="${PH_GARMENT}" stroke="${PH_GARMENT}" stroke-width="14" stroke-linejoin="round"/>`;
  if (o.shade) {
    s += `<clipPath id="${id}tc"><polygon points="${pts(tp)}"/></clipPath>`;
    s += `<rect x="${sx + 8}" y="${sy - 20}" width="60" height="120" fill="#000" opacity=".2" clip-path="url(#${id}tc)"/>`;
    s += `<path d="M${sx - 24},${sy + 4} L${hx - 20},${hy - 2}" stroke="#fff" stroke-opacity=".4" stroke-width="3" stroke-linecap="round"/>`;
  }
  s += `<polygon points="${pts([[sx - 9, sy - 1], [sx, sy + 14], [sx + 9, sy - 1]])}" fill="#E8F6F4" stroke="${INK}" stroke-width="3" stroke-linejoin="round"/>`;
  s += limb(P.armL) + limb(P.armR);
  if (P.phone) {
    const [px, py, pr] = P.phone;
    s += `<g transform="translate(${px} ${py}) rotate(${pr})"><rect x="-10" y="-17" width="20" height="34" rx="5" fill="${INK}"/><rect x="-7.5" y="-13.5" width="15" height="27" rx="2.5" fill="${CANVAS}"/><rect x="-6" y="-10" width="10" height="6" rx="3" fill="#B8E5E0"/><rect x="-4" y="-2" width="10" height="6" rx="3" fill="${TEAL}"/><circle cx="-2" cy="8" r="1.3" fill="#999"/><circle cx="1.5" cy="8" r="1.3" fill="#999"/><circle cx="5" cy="8" r="1.3" fill="#999"/></g>`;
  }
  s += hand(P.armL[2]) + hand(P.armR[2]);
  if (P.clasp) s += hand([P.clasp[0] + 3, P.clasp[1] - 2]) + hand([P.clasp[0] - 3, P.clasp[1] + 1]);
  // neck
  s += `<line x1="${sx}" y1="${sy}" x2="${P.head[0]}" y2="${P.head[1] + 30}" stroke="${INK}" stroke-width="${lw}" stroke-linecap="round"/>`;
  // head group
  const f = P.face;
  s += `<g transform="translate(${P.head[0]} ${P.head[1]}) rotate(${P.tilt} 0 34)">`;
  s += `<rect x="-25" y="-32" width="50" height="64" rx="21" fill="${SKIN}" stroke="${INK}" stroke-width="${ow}"/>`;
  if (o.shade) {
    s += `<clipPath id="${id}hc"><rect x="-25" y="-32" width="50" height="64" rx="21"/></clipPath>`;
    s += `<rect x="8" y="-34" width="30" height="70" fill="#000" opacity=".18" clip-path="url(#${id}hc)"/>`;
  }
  s += `<path d="M-26,-6 Q-29,-33 -10,-36 L10,-36 Q29,-33 26,-6 Q15,-19 0,-19 Q-15,-19 -26,-6Z" fill="${HAIR}" stroke="${INK}" stroke-width="3" stroke-linejoin="round"/>`;
  if (C) s += '<g transform="translate(0 3) scale(1.14) translate(0 -3)">'; // bigger eyes, glasses and brows
  // glasses
  // (placeholder figure: no glasses, so the face reads as a blank, neutral stand-in)
  // eyes
  if (f === 'shock') {
    for (const x of [-12, 12]) s += `<circle cx="${x}" cy="3" r="6.5" fill="#fff" stroke="${INK}" stroke-width="2.5"/><circle cx="${x}" cy="3" r="2.3" fill="${INK}"/>`;
  } else if (f === 'plead') {
    for (const x of [-12, 12]) s += `<rect x="${x - 3.6}" y="-4" width="7.2" height="14" rx="3.6" fill="${INK}"/><circle cx="${x + 1}" cy="-1" r="1.6" fill="#fff"/><circle cx="${x - 1.2}" cy="5" r="1" fill="#fff"/>`;
  } else {
    for (const x of [-12, 12]) s += `<rect x="${x - 3}" y="-3" width="6" height="12" rx="3" fill="${INK}"/><circle cx="${x + 1}" cy="0" r="1.4" fill="#fff"/>`;
  }
  // brows: A = floating (never touches the outline; "lift-off" on shock). B = attached, simple raise.
  const bw = A ? 6 : C ? 5.5 : 4.5, brow = (a, b) => `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="${HAIR}" stroke-width="${bw}" stroke-linecap="round"/>`;
  if (f === 'shock') {
    if (A) s += brow([-19, -50], [-5, -51]) + brow([5, -51], [19, -50]) + `<path d="M-14,-44 q-3,-3 0,-5 M14,-44 q3,-3 0,-5" fill="none" stroke="${INK}" stroke-width="2.5" stroke-linecap="round"/>`;
    else s += `<path d="M-21,-14 Q-13,-24 -5,-15" fill="none" stroke="${HAIR}" stroke-width="${bw}" stroke-linecap="round"/><path d="M5,-15 Q13,-24 21,-14" fill="none" stroke="${HAIR}" stroke-width="${bw}" stroke-linecap="round"/>`;
  } else if (f === 'plead') {
    s += brow([-22, -12], [-6, -23]) + brow([6, -23], [22, -12]);
  } else {
    s += brow([-21, -15], [-6, -20]) + brow([6, -20], [21, -15]);
  }
  // mouth
  if (f === 'shock') s += `<ellipse cx="0" cy="23" rx="5" ry="7" fill="#6E2B2B" stroke="${INK}" stroke-width="3"/>`;
  else if (f === 'plead') s += `<path d="M-9,24 q4.5,-6 9,0 t9,0" fill="none" stroke="${INK}" stroke-width="${fw}" stroke-linecap="round"/>`;
  else s += `<path d="M-8,22 q4,-4 8,0 t8,0" fill="none" stroke="${INK}" stroke-width="${fw}" stroke-linecap="round"/>`;
  if (C) s += '</g>';
  // FX
  const drop = (x, y, k = 1) => `<path transform="translate(${x} ${y}) scale(${k})" d="M0,-9 Q7,2 0,8 Q-7,2 0,-9Z" fill="${SKY}" stroke="${INK}" stroke-width="2"/>`;
  if (P.fx.includes('sweat')) s += drop(36, -12) + drop(40, 8, .7);
  if (P.fx.includes('sweat2')) s += drop(-38, -16, 1.3) + drop(38, -6) + drop(41, 14, .7);
  if (P.fx.includes('lines')) {
    const c = A ? INK : '#FFC845';
    s += `<g stroke="${c}" stroke-width="3.5" stroke-linecap="round"><line x1="-40" y1="-30" x2="-52" y2="-40"/><line x1="-42" y1="-14" x2="-57" y2="-18"/><line x1="40" y1="-30" x2="52" y2="-40"/><line x1="42" y1="-14" x2="57" y2="-18"/></g>`;
  }
  s += '</g></g>';
  return s;
}

const cat = (x, y, k) => `<g transform="translate(${x} ${y}) scale(${k})"><path d="M-46,4 Q-92,-26 -72,-80 q9,-9 22,-5" fill="none" stroke="#3A3F50" stroke-width="10" stroke-linecap="round"/><ellipse cx="0" cy="0" rx="50" ry="34" fill="#3A3F50" stroke="${INK}" stroke-width="4"/><ellipse cx="-22" cy="30" rx="14" ry="7" fill="#fff" stroke="${INK}" stroke-width="3"/><ellipse cx="22" cy="30" rx="14" ry="7" fill="#fff" stroke="${INK}" stroke-width="3"/><circle cx="36" cy="-32" r="27" fill="#3A3F50" stroke="${INK}" stroke-width="4"/><polygon points="14,-52 18,-80 34,-58" fill="#3A3F50" stroke="${INK}" stroke-width="4" stroke-linejoin="round"/><polygon points="40,-58 58,-80 62,-50" fill="#3A3F50" stroke="${INK}" stroke-width="4" stroke-linejoin="round"/><rect x="24" y="-42" width="8" height="14" rx="4" fill="#FFC845"/><rect x="42" y="-42" width="8" height="14" rx="4" fill="#FFC845"/><rect x="26" y="-39" width="3" height="8" rx="1.5" fill="${INK}"/><rect x="44" y="-39" width="3" height="8" rx="1.5" fill="${INK}"/></g>`;

const FILTERS = `
<filter id="warm" x="-50%" y="-50%" width="200%" height="200%"><feColorMatrix type="matrix" values="1.04 0 0 0 0.02  0 0.98 0 0 0.005  0 0 0.9 0 0  0 0 0 1 0"/></filter>
<filter id="castShadow" filterUnits="userSpaceOnUse" x="-3000" y="-3000" width="6000" height="6000"><feMorphology operator="dilate" radius="3"/><feColorMatrix type="matrix" values="0 0 0 0 0.1  0 0 0 0 0.1  0 0 0 0 0.16  0 0 0 0.34 0"/><feGaussianBlur stdDeviation="3"/></filter>
<filter id="soft" filterUnits="userSpaceOnUse" x="-3000" y="-3000" width="6000" height="6000"><feGaussianBlur stdDeviation="10"/></filter>
<filter id="soft4" filterUnits="userSpaceOnUse" x="-3000" y="-3000" width="6000" height="6000"><feGaussianBlur stdDeviation="4"/></filter>
<filter id="desat" x="0" y="0" width="100%" height="100%"><feColorMatrix type="saturate" values="0.45"/></filter>
<radialGradient id="vig" cx="50%" cy="50%" r="75%"><stop offset="55%" stop-color="#000" stop-opacity="0"/><stop offset="100%" stop-color="#000" stop-opacity=".55"/></radialGradient>`;

const wrap = (w, h, body, defs = '') => `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><defs>${FILTERS}${defs}</defs>${body}</svg>`;
const label = (x, y, t, size = 30, fill = INK, weight = 700, anchor = 'start', op = 1) => `<text x="${x}" y="${y}" font-family="${FONT}" font-size="${size}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}" opacity="${op}">${t}</text>`;

// ---------------------------------------------------------------- SCENE A: Inkblock flat stage-set living room
function sceneA(pose, {doom = false} = {}) {
  const FY = 880, FX = 700, S = 540 / NATIVE_H;
  let b = `<rect width="1920" height="1080" fill="#EDE3D3"/><rect y="778" width="1920" height="302" fill="#C8A27A"/><rect y="760" width="1920" height="18" fill="#D8CFC0"/><line x1="0" y1="778" x2="1920" y2="778" stroke="#A98863" stroke-width="3"/>`;
  // window + soft light
  b += `<polygon points="1180,778 1620,778 1400,1010 960,1010" fill="#fff" opacity=".2"/><rect x="1180" y="140" width="440" height="330" fill="#CFE8F5" stroke="#8A7A64" stroke-width="5"/><line x1="1400" y1="140" x2="1400" y2="470" stroke="#8A7A64" stroke-width="4"/><line x1="1180" y1="305" x2="1620" y2="305" stroke="#8A7A64" stroke-width="4"/><rect x="1130" y="120" width="60" height="400" rx="10" fill="#7FBFB8"/><rect x="1610" y="120" width="60" height="400" rx="10" fill="#7FBFB8"/>`;
  // wall clock + frame
  b += `<circle cx="600" cy="190" r="52" fill="#fff" stroke="#8A7A64" stroke-width="4"/><line x1="600" y1="190" x2="600" y2="156" stroke="${INK}" stroke-width="4" stroke-linecap="round"/><line x1="600" y1="190" x2="624" y2="204" stroke="${INK}" stroke-width="4" stroke-linecap="round"/><rect x="800" y="150" width="130" height="165" rx="8" fill="#F7F1E6" stroke="#8A7A64" stroke-width="5"/><circle cx="865" cy="215" r="26" fill="#D9B79A"/><rect x="835" y="245" width="60" height="50" rx="14" fill="#E7B49A"/>`;
  // shelf with ring binder + "WORK" box (planted props)
  b += `<rect x="80" y="440" width="380" height="16" fill="#B08658" stroke="#8A6C48" stroke-width="3"/><rect x="110" y="368" width="46" height="72" rx="5" fill="#FF7A3C" stroke="#8A6C48" stroke-width="3"/><rect x="170" y="352" width="120" height="88" rx="6" fill="#D9B27A" stroke="#8A6C48" stroke-width="3"/>${label(230, 405, 'WORK', 24, '#6B4F2A', 800, 'middle')}<circle cx="345" cy="410" r="30" fill="#9CC9A6" stroke="#8A6C48" stroke-width="3"/>`;
  // plant
  b += `<rect x="150" y="690" width="70" height="86" rx="10" fill="#E08A57" stroke="#8A5A3A" stroke-width="4"/><ellipse cx="185" cy="650" rx="60" ry="44" fill="#6FAE7E" stroke="#4E8660" stroke-width="4"/><ellipse cx="150" cy="620" rx="30" ry="40" fill="#7FBF8E" stroke="#4E8660" stroke-width="4"/>`;
  // sofa
  b += `<rect x="1000" y="500" width="700" height="260" rx="44" fill="#5FA8A0" stroke="#2F5E59" stroke-width="4"/><rect x="1060" y="640" width="580" height="130" rx="30" fill="#4F968F" stroke="#2F5E59" stroke-width="4"/><rect x="970" y="590" width="100" height="200" rx="40" fill="#5FA8A0" stroke="#2F5E59" stroke-width="4"/><rect x="1630" y="590" width="100" height="200" rx="40" fill="#5FA8A0" stroke="#2F5E59" stroke-width="4"/><rect x="1180" y="560" width="120" height="110" rx="26" fill="#F59A68" stroke="#A85A2F" stroke-width="4" transform="rotate(-10 1240 615)"/>`;
  b += cat(1018, 566, .95);
  // rug + coffee table
  b += `<rect x="960" y="896" width="760" height="120" rx="16" fill="#E9B79A" stroke="#B87A5A" stroke-width="4"/><rect x="990" y="912" width="700" height="88" rx="10" fill="none" stroke="#fff" stroke-opacity=".6" stroke-width="4"/><rect x="1100" y="820" width="460" height="28" rx="6" fill="#A97C50" stroke="#6B4F2A" stroke-width="4"/><rect x="1130" y="846" width="26" height="64" fill="#8E6A42" stroke="#6B4F2A" stroke-width="3"/><rect x="1504" y="846" width="26" height="64" fill="#8E6A42" stroke="#6B4F2A" stroke-width="3"/><rect x="1380" y="790" width="46" height="30" rx="8" fill="#fff" stroke="${INK}" stroke-width="3"/>`;
  // placeholder figure: contact shadow + sprite
  b += `<ellipse cx="${FX}" cy="${FY + 6}" rx="${58 * S}" ry="${10 * S}" fill="${INK}" opacity=".16"/>`;
  b += `<use xlink:href="#femiA" transform="translate(${FX} ${FY}) scale(${S})"/>`;
  const defs = `<g id="femiA">${femi('fa', pose, {style: 'A', shade: 0})}</g>`;
  // Doom Tint (signature mood tint): desaturate + indigo multiply-style wash + vignette
  const body = doom
    ? `<g filter="url(#desat)">${b}</g><rect width="1920" height="1080" fill="${INK}" opacity=".38"/><rect width="1920" height="1080" fill="url(#vig)"/>`
    : b;
  return wrap(1920, 1080, body, defs);
}

// ---------------------------------------------------------------- SCENE B: 2.5D Modern Pop dimensional living room
const F = 1005.7, CAM = 1.4, VP = [960, 430];
const PR = (X, Y, Z) => [VP[0] + X * F / Z, VP[1] + (CAM - Y) * F / Z];
const poly = (a, fill, extra = '') => `<polygon points="${pts(a)}" fill="${fill}" ${extra}/>`;
function box(x0, x1, y0, y1, z0, z1, c, stroke = .22) {
  const st = `stroke="#000" stroke-opacity="${stroke}" stroke-width="2.5" stroke-linejoin="round"`;
  let s = '';
  if (x0 > 0) s += poly([PR(x0, y0, z0), PR(x0, y0, z1), PR(x0, y1, z1), PR(x0, y1, z0)], c.left, st);
  if (x1 < 0) s += poly([PR(x1, y0, z0), PR(x1, y0, z1), PR(x1, y1, z1), PR(x1, y1, z0)], c.right, st);
  if (y1 < CAM) s += poly([PR(x0, y1, z0), PR(x1, y1, z0), PR(x1, y1, z1), PR(x0, y1, z1)], c.top, st);
  s += poly([PR(x0, y0, z0), PR(x1, y0, z0), PR(x1, y1, z0), PR(x0, y1, z0)], c.front, st);
  return s;
}
const floorQuad = (x0, x1, z0, z1, fill, extra = '') => poly([PR(x0, 0, z0), PR(x1, 0, z0), PR(x1, 0, z1), PR(x0, 0, z1)], fill, extra);

function sceneB(pose, mode /* 'flat' | 'lit' | 'cel' */, {empty = false, layer = 'all', style = 'B'} = {}) {
  const lit = mode !== 'flat', cel = mode === 'cel';
  const fxz = {X: -0.75, Z: 3.4}, [FX, FY] = PR(fxz.X, 0, fxz.Z), S = 1.75 * F / fxz.Z / NATIVE_H;
  let b = '';
  const floor = [[0, 910], [520, 650], [1400, 650], [1920, 910], [1920, 1080], [0, 1080]];
  const defs = `
  <linearGradient id="gFloor" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#B38A62"/><stop offset=".7" stop-color="#C9A27A"/><stop offset="1" stop-color="#D7B48B"/></linearGradient>
  <linearGradient id="gBack" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#E6DACA"/><stop offset="1" stop-color="#F3EADB"/></linearGradient>
  <linearGradient id="gLeft" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#CFC2AE"/><stop offset="1" stop-color="#DDD1BE"/></linearGradient>
  <linearGradient id="gRight" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#EFE5D3"/><stop offset="1" stop-color="#F9F1E2"/></linearGradient>
  <linearGradient id="gSky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#BFE3F6"/><stop offset="1" stop-color="#F1FAFF"/></linearGradient>
  <linearGradient id="gBeam" x1="1" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".45"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
  <radialGradient id="gLamp" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#FFE3A8" stop-opacity=".75"/><stop offset="1" stop-color="#FFE3A8" stop-opacity="0"/></radialGradient>
  <clipPath id="floorClip"><polygon points="${pts(floor)}"/></clipPath>
  <g id="femiB">${femi('fb', pose, {style, shade: cel ? 1 : 0})}</g>`;
  // room shell
  b += poly([[80, 0], [1840, 0], [1400, 215], [520, 215]], '#F6F1E8');
  b += poly([[0, 0], [80, 0], [520, 215], [520, 650], [0, 910]], 'url(#gLeft)');
  b += poly([[1840, 0], [1920, 0], [1920, 910], [1400, 650], [1400, 215]], 'url(#gRight)');
  b += `<rect x="520" y="215" width="880" height="435" fill="url(#gBack)"/>`;
  b += poly(floor, 'url(#gFloor)');
  // floor planks converge to the vanishing point
  b += '<g clip-path="url(#floorClip)" stroke="#000" stroke-opacity=".07" stroke-width="2">';
  for (let x = -2400; x <= 4400; x += 140) b += `<line x1="${x}" y1="1080" x2="${VP[0]}" y2="${VP[1]}"/>`;
  b += '</g>';
  // skirting + corner ambient occlusion
  b += poly([PR(-2.8, 0, 6.4), PR(2.8, 0, 6.4), PR(2.8, 0.12, 6.4), PR(-2.8, 0.12, 6.4)], '#fff', 'opacity=".55"');
  b += `<line x1="520" y1="215" x2="520" y2="650" stroke="#000" stroke-opacity=".16" stroke-width="10" filter="url(#soft4)"/><line x1="1400" y1="215" x2="1400" y2="650" stroke="#000" stroke-opacity=".14" stroke-width="10" filter="url(#soft4)"/><line x1="520" y1="650" x2="1400" y2="650" stroke="#000" stroke-opacity=".16" stroke-width="8" filter="url(#soft4)"/>`;
  // window on right wall (perspective quad) + light
  const yTop = x => 215 - (254 / 520) * (x - 1400), yBot = x => 650 + (260 / 520) * (x - 1400);
  const wy = (x, t) => yTop(x) + t * (yBot(x) - yTop(x));
  const wq = [[1500, wy(1500, .2)], [1760, wy(1760, .2)], [1760, wy(1760, .62)], [1500, wy(1500, .62)]];
  b += poly(wq, 'url(#gSky)', 'stroke="#fff" stroke-width="9" stroke-linejoin="round"');
  const mx = 1630;
  b += `<line x1="${mx}" y1="${wy(mx, .2)}" x2="${mx}" y2="${wy(mx, .62)}" stroke="#fff" stroke-width="7"/><line x1="1500" y1="${wy(1500, .41)}" x2="1760" y2="${wy(1760, .41)}" stroke="#fff" stroke-width="7"/>`;
  b += poly([wq[0], wq[1], [1700, 800], [1480, 690]], 'url(#gBeam)', 'opacity=".55"');
  b += poly([[1480, 690], [1700, 800], [1280, 960], [1060, 850]], '#fff', 'opacity=".22" filter="url(#soft4)"');
  // wall decor: frame, clock, shelf with binder + WORK box
  b += poly([PR(-0.3, 1.5, 6.4), PR(0.45, 1.5, 6.4), PR(0.45, 2.1, 6.4), PR(-0.3, 2.1, 6.4)], '#F7F1E6', 'stroke="#8A7A64" stroke-width="4"');
  const cc = PR(1.1, 2.0, 6.4);
  b += `<circle cx="${cc[0]}" cy="${cc[1]}" r="26" fill="#fff" stroke="#8A7A64" stroke-width="4"/><line x1="${cc[0]}" y1="${cc[1]}" x2="${cc[0]}" y2="${cc[1] - 16}" stroke="${INK}" stroke-width="3" stroke-linecap="round"/><line x1="${cc[0]}" y1="${cc[1]}" x2="${cc[0] + 11}" y2="${cc[1] + 6}" stroke="${INK}" stroke-width="3" stroke-linecap="round"/>`;
  const wood = {front: '#B08658', top: '#C79B6B', left: '#9A7347', right: '#BA8F5F'};
  b += box(-2.5, -1.0, 1.0, 1.05, 6.1, 6.38, wood);
  b += box(-2.35, -2.15, 1.05, 1.5, 6.15, 6.35, {front: '#FF7A3C', top: '#FF9A6C', left: '#D9622B', right: '#FF8A55'});
  b += box(-2.0, -1.35, 1.05, 1.4, 6.15, 6.35, {front: '#D9B27A', top: '#E8C796', left: '#B8915A', right: '#D4AB70'});
  { const t = PR(-1.68, 1.22, 6.15); b += `<text x="${t[0]}" y="${t[1]}" font-family="${FONT}" font-size="15" font-weight="800" fill="#6B4F2A" text-anchor="middle">WORK</text>`; }
  const iBack = b.length; // everything above = back layer (room shell, window, wall decor)
  // floor shadows (ambient occlusion) under furniture
  const ao =(x0, x1, z0, z1) => floorQuad(x0 - .1, x1 + .1, z0 - .05, z1 + .12, '#000', 'opacity=".28" filter="url(#soft)"');
  b += ao(0, 2.2, 5.45, 6.35) + ao(-0.2, 0.9, 4.3, 5.0) + ao(1.85, 2.4, 5.7, 6.2);
  // rug
  b += floorQuad(-1.9, 1.2, 2.95, 5.4, '#E7B49A', 'stroke="#C98C6E" stroke-width="3"');
  b += floorQuad(-1.7, 1.0, 3.2, 5.2, 'none', 'stroke="#fff" stroke-opacity=".55" stroke-width="4"');
  // sofa
  const teal = {front: '#4FA79F', top: '#6CC0B6', left: '#3C8680', right: '#5CB5AC'};
  b += box(0, 2.2, 0.0, 0.42, 5.45, 6.35, teal);            // base
  b += box(0, 2.2, 0.42, 0.95, 5.95, 6.35, teal);           // backrest
  b += box(0, 0.25, 0.42, 0.72, 5.45, 5.95, teal);          // left arm
  b += box(1.95, 2.2, 0.42, 0.72, 5.45, 5.95, teal);        // right arm
  b += box(0.25, 1.95, 0.42, 0.55, 5.45, 5.95, {front: '#62B7AE', top: '#80D0C6', left: '#4FA79F', right: '#6CC0B6'});
  b += box(0.5, 0.95, 0.55, 0.95, 5.85, 6.15, {front: '#F59A68', top: '#FFB78C', left: '#D9794A', right: '#FFA574'}); // pillow
  const cp = PR(0.12, 0.74, 5.7);
  b += cat(cp[0] + 14, cp[1] - 8, .42);
  // coffee table
  b += box(-0.15, 0.85, 0.34, 0.4, 4.3, 5.0, wood);
  for (const [lx, lz] of [[-0.12, 4.33], [0.78, 4.33], [-0.12, 4.9], [0.78, 4.9]]) b += box(lx, lx + .07, 0, 0.34, lz, lz + .07, {front: '#8E6A42', top: '#A27A4E', left: '#7A5A36', right: '#96704A'}, .15);
  b += box(0.5, 0.62, 0.4, 0.5, 4.5, 4.62, {front: '#fff', top: '#fff', left: '#ddd', right: '#eee'});
  // floor lamp (with warm glow) and plant
  const l0 = PR(-2.2, 0, 5.8), l1 = PR(-2.2, 1.5, 5.8), l2 = PR(-2.2, 1.85, 5.8);
  b += `<ellipse cx="${l1[0]}" cy="${l1[1] - 20}" rx="120" ry="110" fill="url(#gLamp)"/><line x1="${l0[0]}" y1="${l0[1]}" x2="${l1[0]}" y2="${l1[1]}" stroke="#555" stroke-width="5" stroke-linecap="round"/><polygon points="${pts([[l1[0] - 20, l1[1]], [l1[0] + 20, l1[1]], [l2[0] + 12, l2[1]], [l2[0] - 12, l2[1]]])}" fill="#F8E7C2" stroke="#B89B62" stroke-width="3"/>`;
  b += box(2.1, 2.4, 0, 0.35, 5.8, 6.1, {front: '#E08A57', top: '#F0A67C', left: '#B96B3F', right: '#E8996A'});
  { const p = PR(2.25, 0.62, 5.95); b += `<ellipse cx="${p[0]}" cy="${p[1]}" rx="38" ry="30" fill="#6FAE7E" stroke="#4E8660" stroke-width="3"/><ellipse cx="${p[0] - 18}" cy="${p[1] - 20}" rx="18" ry="26" fill="#7FBF8E" stroke="#4E8660" stroke-width="3"/>`; }
  const iMid = b.length; // iBack..iMid = mid layer (rug, sofa, cat, table, lamp, plant)
  // foreground layer: a large, soft, near-camera plant (depth/parallax test)
  const fp = PR(-2.05, 0, 2.3), fk = F / 2.3;
  const front = `<g filter="url(#soft4)"><rect x="${fp[0] - 0.2 * fk}" y="${fp[1] - 0.45 * fk}" width="${0.4 * fk}" height="${0.45 * fk}" rx="14" fill="#E08A57" stroke="#8A5A3A" stroke-width="5"/><ellipse cx="${fp[0]}" cy="${fp[1] - 0.95 * fk}" rx="${0.5 * fk}" ry="${0.55 * fk}" fill="#5FA06F" stroke="#3F7A52" stroke-width="5"/><ellipse cx="${fp[0] - 0.3 * fk}" cy="${fp[1] - 1.25 * fk}" rx="${0.22 * fk}" ry="${0.4 * fk}" fill="#6FB07E" stroke="#3F7A52" stroke-width="5"/><ellipse cx="${fp[0] + 0.28 * fk}" cy="${fp[1] - 1.15 * fk}" rx="${0.2 * fk}" ry="${0.36 * fk}" fill="#4F9060" stroke="#3F7A52" stroke-width="5"/></g>`;
  if (layer === 'back') return wrap(1920, 1080, b.slice(0, iBack), defs);
  if (layer === 'mid') return wrap(1920, 1080, b.slice(iBack, iMid), defs);
  if (layer === 'front') return wrap(1920, 1080, front, defs);
  // placeholder figure: contact shadow, optional cast shadow, sprite
  if (!empty) {
  b += `<ellipse cx="${FX}" cy="${FY + 5}" rx="${52 * S}" ry="${9 * S}" fill="#000" opacity=".34" filter="url(#soft4)"/>`;
  if (lit) b += `<use xlink:href="#femiB" filter="url(#castShadow)" transform="translate(${FX} ${FY}) scale(${S}) matrix(1 0 0.5 -0.16 0 0)"/>`;
  b += `<use xlink:href="#femiB" ${lit ? 'filter="url(#warm)"' : ''} transform="translate(${FX} ${FY}) scale(${S})"/>`;
  }
  // global light/vignette (environment only is graded; flat mode keeps the sprite untouched)
  b += `<rect width="1920" height="1080" fill="#FFE2AA" opacity=".07"/><rect width="1920" height="1080" fill="url(#vig)" opacity=".5"/>`;
  return wrap(1920, 1080, b, defs);
}

// ---------------------------------------------------------------- character sheets (3 comparable poses)
function sheet(style) {
  const A = style === 'A', names = ['text', 'frozen', 'plead'];
  const titles = ['1  The Text', '2  Frozen' + (A ? ' (brow lift-off)' : ' (raised brows)'), '3  Pleading'];
  const defs = names.map((n, i) => `<g id="s${i}">${femi('sf' + i, n, {style, shade: 0})}</g>`).join('');
  let b = A
    ? `<rect width="1920" height="540" fill="${CANVAS}"/><line x1="0" y1="470" x2="1920" y2="470" stroke="#D9D1C2" stroke-width="3"/>`
    : `<rect width="1920" height="540" fill="#EAF0F5"/><polygon points="0,540 0,300 1920,300 1920,540" fill="#DCE5EC"/><g stroke="#000" stroke-opacity=".06" stroke-width="2">${Array.from({length: 40}, (_, i) => `<line x1="${-1500 + i * 130}" y1="540" x2="960" y2="150"/>`).join('')}</g>`;
  names.forEach((n, i) => {
    const x = 330 + i * 630, y = 470;
    b += A ? `<ellipse cx="${x}" cy="${y + 4}" rx="70" ry="9" fill="${INK}" opacity=".15"/>`
      : `<ellipse cx="${x}" cy="${y + 4}" rx="66" ry="10" fill="#000" opacity=".3" filter="url(#soft4)"/><use xlink:href="#s${i}" filter="url(#castShadow)" transform="translate(${x} ${y}) scale(1.5) matrix(1 0 0.5 -0.16 0 0)"/>`;
    b += `<use xlink:href="#s${i}" ${A ? '' : 'filter="url(#warm)"'} transform="translate(${x} ${y}) scale(1.5)"/>`;
    b += label(x, 520, titles[i], 24, INK, 700, 'middle', .8);
  });
  b += label(40, 50, A ? 'CONCEPT A · INKBLOCK — Placeholder figure (character sheet)' : 'CONCEPT B · 2.5D MODERN POP — Placeholder figure (character sheet)', 28, INK, 800);
  return wrap(1920, 540, b, defs);
}

const png = async (name, svg, w = 1920) => {
  fs.writeFileSync(path.join(OUT, 'svg', name + '.svg'), svg);
  const file = path.join(OUT, name + '.png');
  await sharp(Buffer.from(svg), {density: 72}).resize({width: w}).png().toFile(file);
  return file;
};

(async () => {
  // --empty-reference DIR : write ONLY a character-free layout reference (used as an input for external plate experiments)
  const ei = process.argv.indexOf('--empty-reference');
  if (ei > -1) { const f = path.join(path.resolve(process.argv[ei + 1]), 'B-layout-reference-empty.png'); fs.mkdirSync(path.dirname(f), {recursive: true}); await sharp(Buffer.from(sceneB('frozen', 'lit', {empty: true}))).png().toFile(f); console.log('wrote', f); return; }
  // --thin-limb-test : render the thin-limb variant (style 'C') in the layered room, plus its three-pose sheet
  if (process.argv.includes('--thin-limb-test')) {
    await png('C-thinlimb-scene', sceneB('frozen', 'lit', {style: 'C'}));
    await png('C-thinlimb-character-sheet', sheet('C').replace('CONCEPT B · 2.5D MODERN POP — Placeholder figure (character sheet)', 'THIN-LIMB VARIANT — Placeholder figure (character sheet)'));
    console.log('wrote thin-limb variant'); return;
  }
  // --export-spike DIR : rasterise the vector concept into renderer-ready PNGs for a technical spike
  //   room-back/mid/front.png (1920x1080), doom-tint.png, and per-pose figure-<pose>.png + figure-<pose>-shadow.png
  //   (sprite canvas 1200x930 px, feet anchor at (900,795), 3 px per native unit)
  const xi = process.argv.indexOf('--export-spike');
  if (xi > -1) {
    const dir = path.resolve(process.argv[xi + 1]); fs.mkdirSync(dir, {recursive: true});
    for (const l of ['back', 'mid', 'front']) await sharp(Buffer.from(sceneB('frozen', 'lit', {empty: true, layer: l}))).png().toFile(path.join(dir, `room-${l}.png`));
    await sharp(Buffer.from(wrap(1920, 1080, `<rect width="1920" height="1080" fill="${INK}" opacity=".45"/><rect width="1920" height="1080" fill="url(#vig)"/>`))).png().toFile(path.join(dir, 'doom-tint.png'));
    const vb = body => `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1200" height="930" viewBox="-300 -265 400 310"><defs>${FILTERS}`;
    for (const pose of Object.keys(POSES)) {
      const defs = `<g id="fx">${femi('fe', pose, {style: 'B', shade: 0})}</g>`;
      const head = vb() + defs + '</defs>';
      await sharp(Buffer.from(head + `<use xlink:href="#fx" filter="url(#warm)"/></svg>`)).png().toFile(path.join(dir, `figure-${pose}.png`));
      await sharp(Buffer.from(head + `<ellipse cx="0" cy="4" rx="52" ry="9" fill="#000" opacity=".34" filter="url(#soft4)"/><use xlink:href="#fx" filter="url(#castShadow)" transform="matrix(1 0 0.5 -0.16 0 0)"/></svg>`)).png().toFile(path.join(dir, `figure-${pose}-shadow.png`));
    }
    console.log('wrote spike assets to', dir, fs.readdirSync(dir).join(', '));
    return;
  }
  // --composite PLATE OUT : place the flat placeholder figure (Level 2: scene tint + contact/cast shadow) on an external background plate
  const ci = process.argv.indexOf('--composite');
  if (ci > -1) {
    const plate = path.resolve(process.argv[ci + 1]), outFile = path.resolve(process.argv[ci + 2]);
    const meta = await sharp(plate).metadata(), W = meta.width, H = meta.height;
    const x = 0.31 * W, y = 0.84 * H, sc = (0.47 * H) / NATIVE_H;
    const sprite = wrap(W, H,
      `<ellipse cx="${x}" cy="${y + 4}" rx="${52 * sc}" ry="${9 * sc}" fill="#000" opacity=".34" filter="url(#soft4)"/>` +
      `<use xlink:href="#fx" filter="url(#castShadow)" transform="translate(${x} ${y}) scale(${sc}) matrix(1 0 0.5 -0.16 0 0)"/>` +
      `<use xlink:href="#fx" filter="url(#warm)" transform="translate(${x} ${y}) scale(${sc})"/>`,
      `<g id="fx">${femi('fc', 'frozen', {style: 'B', shade: 0})}</g>`);
    await sharp(plate).composite([{input: await sharp(Buffer.from(sprite)).png().toBuffer()}]).png().toFile(outFile);
    console.log('wrote', outFile);
    return;
  }
  const out = {};
  out.sA = await png('A-inkblock-scene', sceneA('frozen'));
  out.sAd = await png('A-inkblock-scene-doom-tint', sceneA('frozen', {doom: true}));
  out.sB = await png('B-modernpop25d-scene', sceneB('frozen', 'lit'));
  for (const m of ['flat', 'lit', 'cel']) out['l' + m] = await png('B-level-' + m, sceneB('frozen', m));
  out.shA = await png('A-inkblock-character-sheet', sheet('A'));
  out.shB = await png('B-modernpop25d-character-sheet', sheet('B'));

  // flat-vs-lit levels panel (same pose, same room; crop around placeholder figure)
  const crop = {left: 380, top: 250, width: 600, height: 700};
  const cols = [['flat', 'Level 1 · Fully flat sprite', 'contact shadow only'], ['lit', 'Level 2 · Flat sprite + scene light', 'warm tint + cast shadow'], ['cel', 'Level 3 · One-tone cel shade', 'shade side + rim highlight']];
  const tiles = [];
  for (let i = 0; i < 3; i++) tiles.push({input: await sharp(out['l' + cols[i][0]]).extract(crop).png().toBuffer(), left: 40 + i * 620, top: 110});
  let lv = `<rect width="1920" height="900" fill="#F4F6F8"/>` + label(40, 60, 'Concept B — how flat should the character be inside the dimensional room?', 32, INK, 800);
  lv += label(40, 92, 'Same pose, same room, same light. Only the character treatment changes.', 22, INK, 400, 'start', .75);
  cols.forEach((c, i) => { lv += label(40 + i * 620 + 300, 845, c[1], 24, INK, 800, 'middle') + label(40 + i * 620 + 300, 877, c[2], 20, INK, 400, 'middle', .7); });
  const base = await sharp(Buffer.from(wrap(1920, 900, lv))).png().toBuffer();
  await sharp(base).composite(tiles).png().toFile(path.join(OUT, 'B-levels-flat-vs-lit.png'));

  // side-by-side comparison board
  const half = 950, h = Math.round(half * 1080 / 1920);
  const tl = async (f, w) => sharp(f).resize({width: w}).png().toBuffer();
  const bar = Buffer.from(wrap(260, 28, '<rect width="260" height="28" fill="' + INK + '"/>' + label(130, 20, 'DOOM TINT (mood tint)', 15, '#fff', 800, 'middle')));
  const doomInset = await sharp(await sharp(out.sAd).extract({left: 300, top: 220, width: 800, height: 700}).resize({width: 260}).png().toBuffer()).extend({bottom: 28, background: INK}).composite([{input: bar, left: 0, top: 228}]).png().toBuffer();
  const board = `<rect width="1920" height="1000" fill="#fff"/>` + label(30, 55, 'CONCEPT A · INKBLOCK', 34, INK, 800) + label(985, 55, 'CONCEPT B · 2.5D MODERN POP', 34, INK, 800)
    + label(30, 82, 'Flat colour-block stage set · floating brows · mood tints', 20, INK, 400, 'start', .75)
    + label(985, 82, 'Flat sprite in a perspective room · light, shadow and depth', 20, INK, 400, 'start', .75)
    + label(960, 985, 'Same neutral placeholder figure and the same three poses in both. It is a stand-in, not a character. Concept art drawn locally as vectors — not AI-generated, not final artwork.', 20, INK, 400, 'middle', .7);
  const sheetH = Math.round(half * 540 / 1920);
  await sharp(Buffer.from(wrap(1920, 1000, board))).composite([
    {input: await tl(out.sA, half), left: 20, top: 100},
    {input: await tl(out.sB, half), left: 970, top: 100},
    {input: await tl(out.shA, half), left: 20, top: 100 + h + 20},
    {input: await tl(out.shB, half), left: 970, top: 100 + h + 20},
    {input: doomInset, left: 20 + half - 270, top: 100 + 10},
  ]).png().toFile(path.join(OUT, 'COMPARE_A_vs_B.png'));
  console.log('done', fs.readdirSync(OUT).filter(f => f.endsWith('.png')).join(', '));
})().catch(e => { console.error(e); process.exit(1); });
