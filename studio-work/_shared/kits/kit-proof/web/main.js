// Episode 15 study, landscape 1920x1080 @25 fps. Engine sections are the kit's (toon materials, ink contract,
// add/tbox, lights, cards, render targets/post, applyLight, drawActors, swapForNd, renderFrame); the world is new.
import * as THREE from './lib/three.module.js';
import * as T from './toon.js';
import * as P from './paint.js';
import * as SP from './studypaint.js';
import { TOTAL, shotAt, camAt, dofAt, lightFor, actorsAt, FAMX, FAMZ } from './story.js';

const W = 1920, H = 1080;
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, preserveDrawingBuffer: true });
renderer.setPixelRatio(1); renderer.setSize(W, H, false);
renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.NoToneMapping;

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(30, W / H, 0.05, 200);
const rx = (a) => a * Math.PI / 180;

// ---------- materials ----------
const grad = (() => { const d = new Uint8Array([105, 105, 105, 255, 255, 255, 255, 255]); const t = new THREE.DataTexture(d, 2, 1); t.minFilter = t.magFilter = THREE.NearestFilter; t.needsUpdate = true; return t; })();
const toon = (opts) => new THREE.MeshToonMaterial({ gradientMap: grad, ...opts });
const texM = (c, rx_ = 1, ry_ = 1, color = '#ffffff') => toon({ map: P.tex(c, rx_, ry_), color });
const M = {
  wall: texM(SP.greenWall(1)), wains: texM(SP.woodPanel(2, [22, 40, 22], 2)), wood: texM(SP.woodGrain(3, [22, 42, 24])), woodD: texM(SP.woodGrain(13, [20, 40, 16])),
  woodL: texM(SP.woodGrain(23, [26, 44, 34])), drawers: texM(SP.drawers(4, 3)), leather: texM(SP.leather(5)), leatherP: texM(SP.plainLeather()),
  rug: texM(SP.rug()), floor: texM(P.planks(21), 1, 1, '#9a6a48'), gilt: texM(SP.gilt()), curtain: texM(SP.curtain()), brick: texM(SP.brick()),
  paper: texM(SP.paperStack()), cabinet: texM(SP.woodPanel(8, [22, 40, 20], 1)),
  brass: toon({ color: '#c99a3a' }), black: toon({ color: '#1a1614' }), marble: texM(P.marble(10), 1, 1, '#d8d2c6'), ceiling: toon({ color: '#d9c9a6' }),
  shade: toon({ color: '#3f8a4a', side: THREE.DoubleSide }), deskTop: toon({ color: '#2f6a3b' }), paperM: toon({ color: '#f2ecdb' }), log: toon({ color: '#5a3a22' }),
  pens: [toon({ color: '#2f4f9a' }), toon({ color: '#b8282b' }), toon({ color: '#d9a845' })], glass: new THREE.MeshBasicMaterial({ color: '#dff0e4' }),
};
M.portrait = new THREE.MeshToonMaterial({ gradientMap: grad, map: P.tex(SP.portrait()) }); M.portrait.map.wrapS = M.portrait.map.wrapT = THREE.ClampToEdgeWrapping;
M.rug.map.wrapS = M.rug.map.wrapT = THREE.ClampToEdgeWrapping;

// ---------- ink / normal-depth contract (kit) ----------
const ndMat = new THREE.ShaderMaterial({
  vertexShader: `varying vec3 vN; varying float vD; void main(){ vN = normalize(normalMatrix*normal); vec4 mv = modelViewMatrix*vec4(position,1.); vD = -mv.z; gl_Position = projectionMatrix*mv; }`,
  fragmentShader: `varying vec3 vN; varying float vD; void main(){ vec3 n = normalize(vN); if(!gl_FrontFacing) n = -n; gl_FragColor = vec4(n*.5+.5, vD); }`,
  side: THREE.DoubleSide,
});
const cardNd = (map) => new THREE.ShaderMaterial({
  uniforms: { map: { value: map } },
  vertexShader: `varying vec2 vUv; varying float vD; void main(){ vUv=uv; vec4 mv = modelViewMatrix*vec4(position,1.); vD=-mv.z; gl_Position=projectionMatrix*mv; }`,
  fragmentShader: `uniform sampler2D map; varying vec2 vUv; varying float vD; void main(){ if(texture2D(map,vUv).a<.5) discard; gl_FragColor=vec4(0.,0.,0.,vD); }`,
  side: THREE.DoubleSide,
});

// ---------- helpers (kit) ----------
const add = (geo, mat, x = 0, y = 0, z = 0, parent = scene, opts = {}) => {
  const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); m.castShadow = opts.cast ?? true; m.receiveShadow = true; parent.add(m); return m;
};
const box = (w, h, d) => new THREE.BoxGeometry(w, h, d);
const tbox = (w, h, d, t = 2) => {
  const g = box(w, h, d), uv = g.attributes.uv;
  const dims = [[d, h], [d, h], [w, d], [w, d], [w, h], [w, h]];
  for (let f = 0; f < 6; f++) for (let k = 0; k < 4; k++) { const i = f * 4 + k; uv.setXY(i, uv.getX(i) * dims[f][0] / t, uv.getY(i) * dims[f][1] / t); }
  return g;
};
/** box whose front (+z) face shows the whole texture once (drawer fronts, panels, paintings) */
const fbox = (w, h, d) => box(w, h, d);
/** many coloured boxes merged into one mesh (books) */
const mergeBoxes = (list) => {
  const pos = [], nor = [], col = [], c = new THREE.Color(), m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler();
  for (const b of list) {
    const g = box(b.w, b.h, b.d).toNonIndexed(); e.set(b.rx || 0, b.ry || 0, b.rz || 0); q.setFromEuler(e);
    m4.compose(new THREE.Vector3(b.x, b.y, b.z), q, new THREE.Vector3(1, 1, 1)); g.applyMatrix4(m4);
    pos.push(...g.attributes.position.array); nor.push(...g.attributes.normal.array); c.set(b.c);
    for (let i = 0; i < g.attributes.position.count; i++) col.push(c.r, c.g, c.b);
  }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3)); g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  return g;
};
const bookMat = toon({ vertexColors: true });

// ---------- lights ----------
const hemi = new THREE.HemisphereLight('#ffffff', '#ffffff', 1); scene.add(hemi);
const sun = new THREE.DirectionalLight('#ffffff', 2); sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048); sun.shadow.bias = -0.0005; sun.shadow.normalBias = 0.02; sun.shadow.radius = 3;
scene.add(sun); scene.add(sun.target);
scene.fog = new THREE.Fog('#1c1a14', 30, 120);

// ---------- world: the study ----------
// floor y=0. Back wall (behind the desk) z=-2.45, front wall z=+4.6, side walls x=+-4.2. Desk faces +z (the family).
const world = new THREE.Group(); scene.add(world);
const ZB = -2.45, ZF = 4.6, XW = 4.2, CEIL = 3.3;
const floor = add(new THREE.PlaneGeometry(XW * 2, ZF - ZB), M.floor, 0, 0, (ZB + ZF) / 2, world, { cast: false }); floor.rotation.x = -Math.PI / 2;
floor.material.map.repeat.set(3, 3);
const rugM = add(new THREE.PlaneGeometry(4.4, 3.3), M.rug, 0.2, 0.004, 1.3, world, { cast: false }); rugM.rotation.x = -Math.PI / 2;
const ceil = add(new THREE.PlaneGeometry(XW * 2, ZF - ZB), M.ceiling, 0, CEIL, (ZB + ZF) / 2, world, { cast: false }); ceil.rotation.x = Math.PI / 2;
/** a wall: wainscot below 0.9 m, green panelled above, chair rail + skirting + cornice (3D, inked) */
const wall = (len, rotY, x, z) => {
  const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = rotY; world.add(g);
  const up = add(new THREE.PlaneGeometry(len, CEIL - 0.9), M.wall.clone(), 0, 0.9 + (CEIL - 0.9) / 2, 0, g, { cast: false });
  up.material.map = up.material.map.clone(); up.material.map.repeat.set(len / 0.9, 1); up.material.map.needsUpdate = true;
  const lo = add(new THREE.PlaneGeometry(len, 0.9), M.wains.clone(), 0, 0.45, 0, g, { cast: false });
  lo.material.map = lo.material.map.clone(); lo.material.map.repeat.set(len / 1.4, 1); lo.material.map.needsUpdate = true;
  add(tbox(len, 0.07, 0.05, 1), M.woodD, 0, 0.9, 0.025, g); add(tbox(len, 0.14, 0.03, 1), M.woodD, 0, 0.07, 0.015, g);
  add(tbox(len, 0.16, 0.08, 1), M.woodD, 0, CEIL - 0.08, 0.04, g);
  return g;
};
wall(XW * 2, 0, 0, ZB); wall(XW * 2, Math.PI, 0, ZF); wall(ZF - ZB, Math.PI / 2, -XW, (ZB + ZF) / 2); wall(ZF - ZB, -Math.PI / 2, XW, (ZB + ZF) / 2);

/** bookcase against a wall, front facing +z of its group */
const bookcase = (x, z, rotY, w = 1.15, h = 2.55, seed = 1) => {
  const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = rotY; world.add(g);
  const d = 0.38, t = 0.05;
  add(tbox(w, h, 0.03, 1), M.woodD, 0, h / 2, -d / 2 + 0.015, g, { cast: false });
  for (const s of [-1, 1]) add(tbox(0.07, h, d, 1), M.wood, s * (w / 2 - 0.035), h / 2, 0, g);
  add(tbox(w + 0.12, 0.12, d + 0.08, 1), M.wood, 0, h + 0.06, 0.02, g); add(tbox(w + 0.06, 0.05, d + 0.04, 1), M.woodL, 0, h - 0.02, 0.01, g);
  add(tbox(w, 0.5, d + 0.02, 1), M.cabinet, 0, 0.25, 0.01, g); // cupboard base
  const shelves = [0.5, 0.96, 1.42, 1.88, 2.3], books = [], r = P.rng(seed * 31 + 7);
  const cols = ['#6e2a24', '#3d5a3a', '#7a4a26', '#2f3f5a', '#8a6a3a', '#5a2232', '#4a3a28', '#7c3a2a', '#355046', '#9a7a4a'];
  shelves.forEach((sy, i) => {
    add(tbox(w - 0.14, t, d - 0.04, 1), M.woodL, 0, sy, 0, g);
    if (i === shelves.length - 1) return;
    let bx = -w / 2 + 0.09; const top = shelves[i + 1] - sy - t;
    while (bx < w / 2 - 0.12) {
      const bw = 0.03 + r() * 0.035, bh = top * (0.62 + r() * 0.3), lean = r() < 0.08 ? 0.25 : 0;
      if (r() < 0.06) { bx += 0.06; continue; }
      books.push({ w: bw, h: bh, d: d * 0.72, x: bx + bw / 2 + (lean ? bh * 0.12 : 0), y: sy + t / 2 + bh / 2, z: 0.02, rz: -lean, c: cols[(r() * cols.length) | 0] });
      bx += bw + 0.004 + (lean ? bh * 0.25 : 0);
    }
  });
  add(mergeBoxes(books), bookMat, 0, 0, 0, g);
  return g;
};
bookcase(-1.62, ZB + 0.2, 0, 1.15, 2.55, 1); bookcase(1.62, ZB + 0.2, 0, 1.15, 2.55, 2);
bookcase(-3.4, ZB + 0.2, 0, 1.1, 2.55, 3); bookcase(3.4, ZB + 0.2, 0, 1.1, 2.55, 4);
bookcase(-XW + 0.2, 0.2, Math.PI / 2, 1.2, 2.55, 5); bookcase(-XW + 0.2, 1.6, Math.PI / 2, 1.2, 2.55, 6);
bookcase(-0.2, ZF - 0.2, Math.PI, 1.1, 2.55, 7);

// gilt-framed portrait above the armchair
const portraitG = new THREE.Group(); portraitG.position.set(0, 1.98, ZB + 0.03); world.add(portraitG);
{ const pw = 0.44, ph = 0.54, fw = 0.07;
  add(box(pw, ph, 0.02), M.portrait, 0, 0, 0.01, portraitG, { cast: false });
  for (const s of [-1, 1]) { add(tbox(fw, ph + 2 * fw, 0.06, 0.3), M.gilt, s * (pw / 2 + fw / 2), 0, 0.03, portraitG); add(tbox(pw + 2 * fw, fw, 0.06, 0.3), M.gilt, 0, s * (ph / 2 + fw / 2), 0.03, portraitG); }
  for (const s of [-1, 1]) add(new THREE.SphereGeometry(0.035, 10, 8), M.brass, s * (pw / 2 + fw / 2), ph / 2 + fw / 2, 0.06, portraitG);
}

// green leather wingback armchair (behind the desk)
const CHAIR = new THREE.Vector3(0, 0, -1.72);
const arm = new THREE.Group(); arm.position.copy(CHAIR); world.add(arm);
{ add(tbox(1.0, 0.42, 0.75, 0.6), M.leatherP, 0, 0.29, 0.12, arm);                       // base
  add(tbox(0.86, 0.12, 0.62, 0.6), M.leatherP, 0, 0.55, 0.14, arm);                     // cushion
  const back = add(box(0.92, 1.05, 0.2), M.leather, 0, 0.98, -0.2, arm); back.rotation.x = -0.08; // tufted back
  const backTop = add(new THREE.CylinderGeometry(0.1, 0.1, 0.92, 16), M.leatherP, 0, 1.5, -0.24, arm); backTop.rotation.z = Math.PI / 2;
  for (const s of [-1, 1]) {
    const wing = add(box(0.12, 0.62, 0.5), M.leatherP, s * 0.5, 1.08, -0.04, arm); wing.rotation.y = s * 0.25;
    const wt = add(new THREE.CylinderGeometry(0.07, 0.07, 0.5, 12), M.leatherP, s * 0.5, 1.39, -0.04, arm); wt.rotation.x = Math.PI / 2; wt.rotation.y = s * 0.25;
    add(tbox(0.16, 0.26, 0.72, 0.6), M.leatherP, s * 0.48, 0.63, 0.12, arm);
    const roll = add(new THREE.CylinderGeometry(0.11, 0.11, 0.76, 16), M.leatherP, s * 0.48, 0.77, 0.12, arm); roll.rotation.x = Math.PI / 2;
    for (let k = 0; k < 7; k++) add(new THREE.SphereGeometry(0.012, 6, 5), M.brass, s * 0.59, 0.69, -0.18 + k * 0.09, arm, { cast: false });
  }
}

// big dark-wood desk
const DESK = new THREE.Vector3(0, 0, -0.9), DTOP = 0.78;
const desk = new THREE.Group(); desk.position.copy(DESK); world.add(desk);
{ const w = 2.1, d = 0.95;
  add(tbox(w + 0.08, 0.06, d + 0.08, 0.8), M.wood, 0, DTOP - 0.03, 0, desk);
  add(box(w - 0.24, 0.008, d - 0.24), M.deskTop, 0, DTOP + 0.004, 0, desk, { cast: false });
  for (const s of [-1, 1]) {
    const ped = add(box(0.62, DTOP - 0.1, d), [M.wood, M.wood, M.wood, M.wood, M.drawers, M.wood], s * (w / 2 - 0.31), (DTOP - 0.06) / 2 + 0.02, 0, desk);
    add(tbox(0.68, 0.06, d + 0.04, 0.6), M.woodD, s * (w / 2 - 0.31), 0.03, 0, desk);
  }
  add(box(w - 1.24, 0.6, 0.03), M.cabinet, 0, 0.44, -0.1, desk);                          // modesty panel
  const ctr = add(box(w - 1.24, 0.12, d), [M.wood, M.wood, M.wood, M.wood, M.drawers, M.wood], 0, DTOP - 0.12, 0, desk);
  // desk things
  const TOP = DTOP + 0.008;
  const pot = add(new THREE.CylinderGeometry(0.06, 0.055, 0.13, 14), M.woodL, -0.7, TOP + 0.065, 0.15, desk);
  [[-0.02, 0.2], [0.02, -0.25], [0.0, 0.05]].forEach(([dx, tl], i) => { const pn = add(new THREE.CylinderGeometry(0.008, 0.008, 0.22, 6), M.pens[i], -0.7 + dx, TOP + 0.16, 0.15 + dx, desk); pn.rotation.z = tl; });
  add(tbox(0.28, 0.025, 0.2, 0.3), M.deskTop, -0.42, TOP + 0.013, 0.22, desk);            // notebook
  const ppr = add(box(0.34, 0.01, 0.25), M.paper, 0.05, TOP + 0.005, 0.25, desk, { cast: false }); ppr.rotation.y = 0.08;
  const pen = add(new THREE.CylinderGeometry(0.008, 0.008, 0.16, 6), M.pens[0], -0.18, TOP + 0.01, 0.28, desk); pen.rotation.z = Math.PI / 2; pen.rotation.y = 0.5;
  for (const [bx, bz, by, bw] of [[0.45, 0.12, 0, 0.3], [0.47, 0.11, 0.075, 0.24]]) add(tbox(bw, 0.075, 0.18, 0.4), M.woodL, bx, TOP + 0.0375 + by, bz, desk);
  // brass lamp with a green shade
  const lamp = new THREE.Group(); lamp.position.set(0.82, TOP, 0.0); desk.add(lamp);
  add(new THREE.CylinderGeometry(0.09, 0.11, 0.03, 18), M.brass, 0, 0.015, 0, lamp);
  add(new THREE.CylinderGeometry(0.018, 0.025, 0.3, 10), M.brass, 0, 0.17, 0, lamp);
  add(new THREE.SphereGeometry(0.04, 12, 8), M.brass, 0, 0.12, 0, lamp);
  add(new THREE.CylinderGeometry(0.08, 0.17, 0.16, 20, 1, true), M.shade, 0, 0.36, 0, lamp);
}

// family chairs: wooden, slatted backs, a row facing the desk
const chair = (x, z, rotY = Math.PI) => {
  const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = rotY; world.add(g);
  add(tbox(0.46, 0.05, 0.44, 0.5), M.woodL, 0, 0.45, 0, g);
  for (const [sx, sz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) add(tbox(0.04, sz < 0 ? 1.0 : 0.45, 0.04, 0.5), M.wood, sx * 0.2, sz < 0 ? 0.5 : 0.225, sz * 0.19, g);
  add(tbox(0.46, 0.09, 0.035, 0.5), M.wood, 0, 0.95, -0.19, g);
  for (let k = -2; k <= 2; k++) add(tbox(0.035, 0.4, 0.02, 0.5), M.woodL, k * 0.075, 0.69, -0.19, g);
  add(tbox(0.42, 0.04, 0.03, 0.5), M.wood, 0, 0.5, -0.19, g);
  return g;
};
FAMX.forEach((x) => chair(x, FAMZ));

// front wall: fireplace, window with green curtains
const fire = new THREE.Group(); fire.position.set(2.3, 0, ZF); fire.rotation.y = Math.PI; world.add(fire);
{ add(tbox(1.5, 0.06, 0.7, 1), M.marble, 0, 0.03, 0.3, fire);
  for (const s of [-1, 1]) add(tbox(0.28, 1.15, 0.24, 0.6), M.wood, s * 0.62, 0.575, 0.1, fire);
  add(tbox(1.6, 0.26, 0.26, 0.6), M.cabinet, 0, 1.15, 0.1, fire); add(tbox(1.72, 0.06, 0.34, 1), M.woodL, 0, 1.31, 0.12, fire);
  add(box(0.96, 0.9, 0.05), M.marble, 0, 0.47, 0.0, fire, { cast: false }); add(box(0.7, 0.66, 0.06), M.brick, 0, 0.36, 0.01, fire, { cast: false });
  for (let k = 0; k < 3; k++) { const lg = add(new THREE.CylinderGeometry(0.05, 0.05, 0.5, 10), M.log, 0, 0.1 + (k === 2 ? 0.08 : 0), 0.1 + (k === 2 ? 0 : (k - 0.5) * 0.08), fire); lg.rotation.z = Math.PI / 2; }
  add(tbox(0.22, 0.2, 0.1, 0.3), M.woodL, -0.4, 1.44, 0.12, fire); add(new THREE.CylinderGeometry(0.06, 0.06, 0.02, 16), M.brass, -0.4, 1.44, 0.18, fire).rotation.x = Math.PI / 2;
  add(new THREE.CylinderGeometry(0.02, 0.02, 0.24, 8), toon({ color: '#f4efe2' }), 0.55, 1.46, 0.12, fire); add(new THREE.CylinderGeometry(0.04, 0.05, 0.03, 10), M.brass, 0.55, 1.35, 0.12, fire);
  const pg = new THREE.Group(); pg.position.set(0, 2.05, -0.02); pg.scale.setScalar(0.9); fire.add(pg);
  add(box(0.5, 0.62, 0.02), M.portrait, 0, 0, 0.01, pg, { cast: false });
  for (const s of [-1, 1]) { add(tbox(0.075, 0.77, 0.06, 0.3), M.gilt, s * 0.29, 0, 0.03, pg); add(tbox(0.65, 0.075, 0.06, 0.3), M.gilt, 0, s * 0.35, 0.03, pg); }
}
const win = new THREE.Group(); win.position.set(-1.7, 0, ZF); win.rotation.y = Math.PI; world.add(win);
{ add(box(1.0, 1.6, 0.02), M.glass, 0, 1.75, 0.0, win, { cast: false });
  for (const xx of [-0.5, 0, 0.5]) add(tbox(0.06, 1.66, 0.06, 1), M.woodL, xx, 1.75, 0.03, win);
  for (const yy of [0.95, 1.48, 2.02, 2.55]) add(tbox(1.06, 0.06, 0.06, 1), M.woodL, 0, yy, 0.03, win);
  add(tbox(1.2, 0.08, 0.2, 1), M.woodL, 0, 0.92, 0.08, win);
  for (const s of [-1, 1]) { const cu = add(box(0.38, 2.5, 0.08), M.curtain, s * 0.68, 1.6, 0.1, win); cu.rotation.y = s * 0.05; }
  const rod = add(new THREE.CylinderGeometry(0.02, 0.02, 1.9, 8), M.brass, 0, 2.86, 0.14, win); rod.rotation.z = Math.PI / 2;
}

// ---------- cards (kit, higher-res canvas) ----------
const CW = 1440, CH = 2400, CM = 2.25;
const cardGeo = new THREE.PlaneGeometry(CM * 0.6, CM); cardGeo.translate(0, CM / 2 - CM * 0.025, 0);
class Card {
  constructor() {
    [this.c, this.g] = (() => { const c = document.createElement('canvas'); c.width = CW; c.height = CH; return [c, c.getContext('2d')]; })();
    this.t = new THREE.CanvasTexture(this.c); this.t.colorSpace = THREE.SRGBColorSpace; this.t.anisotropy = 4;
    this.mat = new THREE.MeshBasicMaterial({ map: this.t, transparent: true, alphaTest: 0.02, side: THREE.DoubleSide, fog: true });
    this.mesh = new THREE.Mesh(cardGeo, this.mat); this.mesh.userData.nd = cardNd(this.t); this.mesh.castShadow = true;
    this.mesh.customDepthMaterial = new THREE.MeshDepthMaterial({ depthPacking: THREE.RGBADepthPacking, map: this.t, alphaTest: 0.5 });
    scene.add(this.mesh); this.key = ''; this.mesh.visible = false;
  }
  draw(key, fn) {
    if (key === this.key) return; this.key = key;
    const g = this.g; g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, CW, CH); g.setTransform(CW / 600, 0, 0, CH / 1000, 0, 0);
    const p = new T.Pen(g); fn(p); this.t.needsUpdate = true;
  }
}
const cards = []; const getCard = (i) => cards[i] || (cards[i] = new Card());

// ---------- render targets & post (kit) ----------
const rtColor = new THREE.WebGLRenderTarget(W, H, { samples: 4, type: THREE.HalfFloatType });
const rtNd = new THREE.WebGLRenderTarget(W, H, { type: THREE.HalfFloatType, minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter });
const rtInk = new THREE.WebGLRenderTarget(W, H, { type: THREE.HalfFloatType });
const fsCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1), fsGeo = new THREE.PlaneGeometry(2, 2);
const fs = (mat) => { const s = new THREE.Scene(); s.add(new THREE.Mesh(fsGeo, mat)); return s; };
const inkU = { col: { value: rtColor.texture }, nd: { value: rtNd.texture }, res: { value: new THREE.Vector2(W, H) }, px: { value: 1.6 }, fogCol: { value: new THREE.Color() },
  sat: { value: 1.08 }, lift: { value: new THREE.Color(0, 0, 0) }, gain: { value: new THREE.Color(1, 1, 1) }, vig: { value: 0.22 }, flash: { value: 0 } };
const inkScene = fs(new THREE.ShaderMaterial({ uniforms: inkU, vertexShader: `varying vec2 vUv; void main(){ vUv=uv; gl_Position=vec4(position.xy,0.,1.); }`,
  fragmentShader: `uniform sampler2D col, nd; uniform vec2 res; uniform float px, sat, vig, flash; uniform vec3 fogCol, lift, gain; varying vec2 vUv;
  float edgeAt(vec2 uv, float r){
    vec4 c = texture2D(nd, uv); if (dot(c.rgb,c.rgb) < .01) return 0.; float d = c.a; vec3 n = c.rgb*2.-1.;
    float e = 0.; float rr = r * clamp(3./d, .62, 1.25);
    for (int i=0;i<16;i++){ float a = float(i)*.785398 + (i>7 ? .39 : 0.); float k = i>7 ? .5 : 1.;
      vec2 o = vec2(cos(a), sin(a))*rr*k/res; vec4 s = texture2D(nd, uv+o);
      float ds = s.a; bool card = dot(s.rgb,s.rgb) < .01;
      if (card && ds > 0.) continue;
      if (card) ds = 1e4;
      vec3 ns = s.rgb*2.-1.;
      e = max(e, smoothstep(.006, .02, (ds - d)/d));
      if (!card && abs(ds-d)/d < .06) e = max(e, smoothstep(.88, .72, dot(n, ns)) * .9);
    }
    return e;
  }
  void main(){
    vec3 c = texture2D(col, vUv).rgb;
    float e = edgeAt(vUv, px);
    c = mix(c, vec3(.012,.01,.014), e);
    if (flash < -0.5) c = vec3(e);
    float l = dot(c, vec3(.299,.587,.114)); c = mix(vec3(l), c, sat);
    c = c*gain + lift;
    vec2 q = vUv-.5; c *= 1. - vig*dot(q*vec2(1.,.75), q*vec2(1.,.75))*2.2;
    c = mix(c, vec3(1.), flash);
    gl_FragColor = vec4(c,1.); }` }));
const dofU = { src: { value: rtInk.texture }, nd: { value: rtNd.texture }, res: { value: new THREE.Vector2(W, H) }, focus: { value: 5 }, cinf: { value: 0 }, near: { value: 1 } };
const dofScene = fs(new THREE.ShaderMaterial({ uniforms: dofU, vertexShader: `varying vec2 vUv; void main(){ vUv=uv; gl_Position=vec4(position.xy,0.,1.); }`,
  fragmentShader: `uniform sampler2D src, nd; uniform vec2 res; uniform float focus, cinf, near; varying vec2 vUv;
  float coc(vec2 uv){ float d = texture2D(nd, uv).a; if (d <= 0.) d = 2000.; float k = 1. - focus/d; return k > 0. ? cinf*k : min(-k*cinf*near, cinf*1.4); }
  void main(){
    float c0 = coc(vUv);
    if (cinf < .5 || c0 < .6) { gl_FragColor = linearToOutputTexel(vec4(texture2D(src, vUv).rgb, 1.)); return; }
    vec3 acc = vec3(0.); float wsum = 0.;
    for (int i=0;i<48;i++){ float fi = float(i); float r = sqrt((fi+.5)/48.); float a = fi*2.39996;
      vec2 o = vec2(cos(a), sin(a))*r*c0/res; float cs = coc(vUv+o);
      float w = smoothstep(r*c0-1.5, r*c0+.5, cs + .5);
      acc += texture2D(src, vUv+o).rgb*w; wsum += w; }
    gl_FragColor = linearToOutputTexel(vec4(acc/max(wsum,1e-3), 1.)); }` }));
dofScene.children[0].material.toneMapped = false;

// ---------- per-frame state ----------
const tmpV = new THREE.Vector3();
function applyLight(L) {
  hemi.color.set(L.sky); hemi.groundColor.set(L.ground); hemi.intensity = L.hemi;
  sun.color.set(L.sun); sun.intensity = L.sunI;
  inkU.sat.value = L.sat; inkU.gain.value.set(L.gain || '#ffffff'); inkU.lift.value.set(L.lift || '#000000');
}
function placeSun(L, focus) {
  const az = rx(L.az), el = rx(L.el); tmpV.set(Math.cos(el) * Math.cos(az), Math.sin(el), Math.cos(el) * Math.sin(az));
  sun.position.copy(focus).addScaledVector(tmpV, 12); sun.target.position.copy(focus);
  const ext = L.shadowExt || 4, sc = sun.shadow.camera; sc.left = -ext; sc.right = ext; sc.top = ext; sc.bottom = -ext; sc.near = 0.5; sc.far = 30; sc.updateProjectionMatrix();
}
function drawActors(list, cam) {
  cards.forEach((c) => { c.mesh.visible = false; });
  list.forEach((a, i) => {
    const c = getCard(i);
    c.draw(a.key, a.draw);
    c.mesh.visible = true; c.mesh.position.set(a.x, a.y, a.z);
    const s = a.s || 1; c.mesh.scale.set(s, s, s);
    c.mesh.rotation.set(0, Math.atan2(cam.position.x - a.x, cam.position.z - a.z) + (a.yaw || 0), a.roll || 0);
    c.mesh.castShadow = a.shadow !== false; c.mesh.renderOrder = a.order || 2;
  });
}
const swapForNd = (on) => {
  scene.traverse((o) => {
    if (!o.isMesh) return;
    if (on) { o.userData.mat0 = o.material; if (o.userData.ndSkip) { o.userData.vis0 = o.visible; o.visible = false; return; } o.material = o.userData.nd || ndMat; }
    else { o.material = o.userData.mat0; if (o.userData.vis0 !== undefined) { o.visible = o.userData.vis0; delete o.userData.vis0; } }
  });
};

window.renderFrame = (f) => {
  const S = shotAt(f), L = lightFor(S, f), C = camAt(f);
  applyLight(L);
  camera.position.set(...C.pos); camera.up.set(0, 1, 0); camera.lookAt(...C.look); camera.rotateZ(rx(C.roll || 0));
  camera.fov = C.fov; camera.updateProjectionMatrix(); camera.updateMatrixWorld();
  placeSun(L, new THREE.Vector3(...(C.shadowAt || C.look)));
  drawActors(actorsAt(f, T), camera);
  renderer.setRenderTarget(rtColor); renderer.setClearColor(0x000000, 1); renderer.clear(); renderer.render(scene, camera);
  const fog = scene.fog; scene.fog = null; const sm = renderer.shadowMap.enabled; renderer.shadowMap.enabled = false; renderer.shadowMap.autoUpdate = false;
  swapForNd(true); renderer.setRenderTarget(rtNd); renderer.setClearColor(0x000000, 0); renderer.clear(); renderer.render(scene, camera); swapForNd(false);
  scene.fog = fog; renderer.shadowMap.enabled = sm; renderer.shadowMap.autoUpdate = true;
  const D = dofAt(f);
  inkU.px.value = L.ink ?? 2.2; inkU.flash.value = window.DEBUG_E ? -1 : (C.flash || 0); inkU.vig.value = L.vig ?? 0.22;
  renderer.setRenderTarget(rtInk); renderer.render(inkScene, fsCam);
  dofU.focus.value = D.focus; dofU.cinf.value = D.cinf; dofU.near.value = D.near ?? 1;
  renderer.setRenderTarget(null); renderer.render(dofScene, fsCam);
  return true;
};
window.TOTAL = TOTAL;
window.ready = true;
