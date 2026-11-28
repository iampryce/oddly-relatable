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
scene.fog = new THREE.Fog('#f1e4cf', 30, 120);

// ---------- world: a bright home (kitchen table + living-room corner) ----------
// floor y=0. Back wall z=-2.45 (kitchen: cabinets, window, clock), front wall z=+4.6 (living area: window, plant, shelf), side walls x=+-4.2.
// Kitchen table at (0,0,-0.9), top 0.78; Sam's chair behind it at z=-1.45; the sofa at z=3.0 faces the camera (-z).
const world = new THREE.Group(); scene.add(world);
const ZB = -2.45, ZF = 4.6, XW = 4.2, CEIL = 3.0;
const H2 = {
  wallA: toon({ color: '#f4e4c8' }), wallB: toon({ color: '#cfe6e0' }), trim: toon({ color: '#fbf8f0' }), floor: texM(P.planks(21), 1, 1, '#e0b27a'),
  rug: toon({ color: '#e07a5f' }), rug2: toon({ color: '#f3d9a6' }), cab: toon({ color: '#3f9a9c' }), cabD: toon({ color: '#2f7f82' }), counter: toon({ color: '#efe9db' }),
  table: toon({ color: '#c98f55' }), tableD: toon({ color: '#a8703f' }), chair: toon({ color: '#b57a45' }), sofa: toon({ color: '#78a9d8' }), sofaD: toon({ color: '#5f90c0' }),
  cushion: toon({ color: '#f2c14e' }), plant: toon({ color: '#4f9a4a' }), pot: toon({ color: '#c8643c' }), sky: new THREE.MeshBasicMaterial({ color: '#bfe3f5' }), frame: toon({ color: '#fbf8f0' }),
  placemat: toon({ color: '#7fb8d9' }), plate: toon({ color: '#ffffff' }), bowl: toon({ color: '#e6e0d2' }), orange: toon({ color: '#f08a24' }), salt: toon({ color: '#f6f6f6' }),
  pepper: toon({ color: '#3a3a40' }), steel: toon({ color: '#b8bec8' }), clockF: toon({ color: '#fffdf5' }), dark: toon({ color: '#2a2622' }), lampS: toon({ color: '#ffe9b0', side: THREE.DoubleSide }),
  art1: toon({ color: '#e07a5f' }), art2: toon({ color: '#81b29a' }), art3: toon({ color: '#f2cc8f' }),
};
M.floor = H2.floor;
const floor = add(new THREE.PlaneGeometry(XW * 2, ZF - ZB), H2.floor, 0, 0, (ZB + ZF) / 2, world, { cast: false }); floor.rotation.x = -Math.PI / 2;
floor.material.map.repeat.set(3, 3);
const rug = add(new THREE.PlaneGeometry(3.6, 2.2), H2.rug, 0.15, 0.004, 3.0, world, { cast: false }); rug.rotation.x = -Math.PI / 2;
const rugIn = add(new THREE.PlaneGeometry(3.2, 1.8), H2.rug2, 0.15, 0.006, 3.0, world, { cast: false }); rugIn.rotation.x = -Math.PI / 2;
const wall = (len, rotY, x, z, mat) => {
  const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = rotY; world.add(g);
  add(new THREE.PlaneGeometry(len, CEIL), mat, 0, CEIL / 2, 0, g, { cast: false });
  add(tbox(len, 0.12, 0.04, 1), H2.trim, 0, 0.06, 0.02, g); add(tbox(len, 0.07, 0.05, 1), H2.trim, 0, CEIL - 0.035, 0.025, g);
  return g;
};
wall(XW * 2, 0, 0, ZB, H2.wallA); wall(XW * 2, Math.PI, 0, ZF, H2.wallA);
wall(ZF - ZB, Math.PI / 2, -XW, (ZB + ZF) / 2, H2.wallB); wall(ZF - ZB, -Math.PI / 2, XW, (ZB + ZF) / 2, H2.wallB);
const ceil = add(new THREE.PlaneGeometry(XW * 2, ZF - ZB), H2.trim, 0, CEIL, (ZB + ZF) / 2, world, { cast: false }); ceil.rotation.x = Math.PI / 2;

// kitchen units along the back wall (left), counter, upper cabinets, kettle, fruit
for (let k = 0; k < 4; k++) { const x = -3.8 + k * 0.62;
  add(tbox(0.6, 0.86, 0.6, 1), k % 2 ? H2.cabD : H2.cab, x, 0.43, ZB + 0.31, world); add(box(0.04, 0.2, 0.03), H2.steel, x, 0.62, ZB + 0.63, world, { cast: false });
  add(tbox(0.6, 0.5, 0.34, 1), k % 2 ? H2.cab : H2.cabD, x, 2.05, ZB + 0.18, world); add(box(0.04, 0.16, 0.03), H2.steel, x, 1.88, ZB + 0.36, world, { cast: false }); }
add(tbox(2.55, 0.05, 0.66, 1), H2.counter, -3.22, 0.885, ZB + 0.34, world);
add(new THREE.CylinderGeometry(0.1, 0.12, 0.2, 16), H2.steel, -3.5, 1.0, ZB + 0.35, world);                       // kettle
const bowl0 = add(new THREE.CylinderGeometry(0.16, 0.1, 0.1, 18), H2.bowl, -2.6, 0.96, ZB + 0.4, world);
[[-0.05, 0.02], [0.06, -0.03], [0.0, 0.06]].forEach(([dx, dz]) => add(new THREE.SphereGeometry(0.06, 12, 10), H2.orange, -2.6 + dx, 1.04, ZB + 0.4 + dz, world));
// back wall window (right of the kitchen) with sky, frame and a wall clock
const win = (x, z, rot, w, h, y) => { const g = new THREE.Group(); g.position.set(x, y, z); g.rotation.y = rot; world.add(g);
  add(box(w, h, 0.02), H2.sky, 0, 0, 0.0, g, { cast: false });
  add(tbox(w + 0.14, 0.07, 0.08, 1), H2.frame, 0, h / 2 + 0.035, 0.03, g); add(tbox(w + 0.14, 0.07, 0.08, 1), H2.frame, 0, -h / 2 - 0.035, 0.03, g);
  for (const sx of [-1, 1]) add(tbox(0.07, h + 0.14, 0.08, 1), H2.frame, sx * (w / 2 + 0.035), 0, 0.03, g);
  add(tbox(0.05, h, 0.06, 1), H2.frame, 0, 0, 0.03, g); add(tbox(w, 0.05, 0.06, 1), H2.frame, 0, 0, 0.03, g);
  add(tbox(w + 0.3, 0.06, 0.22, 1), H2.frame, 0, -h / 2 - 0.09, 0.1, g);               // sill
  return g; };
win(1.6, ZB + 0.01, 0, 1.7, 1.2, 1.7);
{ const c = new THREE.Group(); c.position.set(-0.6, 2.25, ZB + 0.03); world.add(c);
  add(new THREE.CylinderGeometry(0.22, 0.22, 0.05, 28), H2.clockF, 0, 0, 0, c).rotation.x = Math.PI / 2;
  add(box(0.02, 0.15, 0.01), H2.dark, 0, 0.06, 0.03, c, { cast: false }); add(box(0.11, 0.02, 0.01), H2.dark, 0.04, 0, 0.03, c, { cast: false }); }
// living-area front wall: big window, framed pictures, shelf with a plant
win(-1.3, ZF - 0.01, Math.PI, 1.8, 1.3, 1.65);
[[1.5, 1.9, H2.art1, 0.6, 0.45], [2.25, 1.75, H2.art2, 0.4, 0.55], [1.9, 1.15, H2.art3, 0.35, 0.3]].forEach(([x, y, m, w, h]) => { const g = new THREE.Group(); g.position.set(x, y, ZF - 0.01); g.rotation.y = Math.PI; world.add(g);
  add(box(w + 0.08, h + 0.08, 0.03), H2.frame, 0, 0, 0, g, { cast: false }); add(box(w, h, 0.035), m, 0, 0, 0.005, g, { cast: false }); });
add(tbox(1.5, 0.05, 0.28, 1), H2.table, 1.9, 0.78, ZF - 0.18, world);
{ const pg = new THREE.Group(); pg.position.set(1.5, 0.81, ZF - 0.2); world.add(pg); add(new THREE.CylinderGeometry(0.1, 0.075, 0.16, 14), H2.pot, 0, 0.08, 0, pg);
  for (let k = 0; k < 7; k++) { const a = k / 7 * Math.PI * 2; const lf = add(new THREE.SphereGeometry(0.075, 10, 8), H2.plant, Math.cos(a) * 0.07, 0.28 + (k % 3) * 0.05, Math.sin(a) * 0.07, pg); lf.scale.set(0.8, 1.5, 0.5); lf.rotation.z = Math.cos(a) * 0.5; } }
add(new THREE.CylinderGeometry(0.17, 0.2, 0.03, 20), H2.dark, 3.3, 0.015, 3.9, world); add(new THREE.CylinderGeometry(0.018, 0.018, 1.6, 8), H2.dark, 3.3, 0.8, 3.9, world);
add(new THREE.CylinderGeometry(0.2, 0.3, 0.3, 24, 1, true), H2.lampS, 3.3, 1.7, 3.9, world, { cast: false });

// kitchen table + chairs
const DESK = new THREE.Vector3(0, 0, -0.9), DTOP = 0.78;
const tbl = new THREE.Group(); tbl.position.copy(DESK); world.add(tbl);
add(tbox(1.9, 0.05, 1.0, 1), H2.table, 0, DTOP - 0.025, 0, tbl);
for (const sx of [-1, 1]) for (const sz of [-1, 1]) add(tbox(0.07, DTOP - 0.05, 0.07, 1), H2.tableD, sx * 0.86, (DTOP - 0.05) / 2, sz * 0.43, tbl);
add(tbox(1.76, 0.07, 0.04, 1), H2.tableD, 0, DTOP - 0.09, 0.43, tbl); add(tbox(1.76, 0.07, 0.04, 1), H2.tableD, 0, DTOP - 0.09, -0.43, tbl);
const TOP = DTOP;
add(tbox(0.5, 0.008, 0.34, 1), H2.placemat, -0.5, TOP + 0.004, 0.22, tbl, { cast: false });                      // placemats + plates
add(tbox(0.5, 0.008, 0.34, 1), H2.placemat, 0.5, TOP + 0.004, 0.22, tbl, { cast: false });
add(new THREE.CylinderGeometry(0.12, 0.1, 0.02, 24), H2.plate, -0.5, TOP + 0.018, 0.22, tbl); add(new THREE.CylinderGeometry(0.12, 0.1, 0.02, 24), H2.plate, 0.5, TOP + 0.018, 0.22, tbl);
add(new THREE.CylinderGeometry(0.2, 0.12, 0.1, 22), H2.bowl, 0.62, TOP + 0.06, -0.22, tbl);                       // fruit bowl
[[-0.07, 0.0], [0.07, 0.03], [0.0, -0.06], [0.02, 0.07]].forEach(([dx, dz]) => add(new THREE.SphereGeometry(0.065, 12, 10), H2.orange, 0.62 + dx, TOP + 0.15, -0.22 + dz, tbl));
const shaker = (x, mat) => { add(new THREE.CylinderGeometry(0.022, 0.026, 0.09, 14), mat, x, TOP + 0.045, 0.02, tbl); add(new THREE.SphereGeometry(0.023, 10, 8), H2.steel, x, TOP + 0.093, 0.02, tbl); };
shaker(-0.3, H2.salt); shaker(-0.22, H2.pepper);                                                               // a real salt and pepper shaker (the size gag)
// dining chair (back toward -z means rotY 0 faces +z toward the camera)
const chair = (x, z, rotY = 0) => {
  const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = rotY; world.add(g);
  add(tbox(0.46, 0.05, 0.44, 1), H2.chair, 0, 0.45, 0, g);
  for (const [sx, sz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) add(tbox(0.04, sz < 0 ? 0.95 : 0.45, 0.04, 1), H2.tableD, sx * 0.2, sz < 0 ? 0.475 : 0.225, sz * 0.19, g);
  add(tbox(0.46, 0.08, 0.035, 1), H2.chair, 0, 0.92, -0.19, g); add(tbox(0.4, 0.14, 0.03, 1), H2.chair, 0, 0.72, -0.19, g); add(tbox(0.4, 0.14, 0.03, 1), H2.chair, 0, 0.52, -0.19, g);
  return g;
};
chair(0, -1.45, 0); chair(-1.2, -0.9, -Math.PI / 2); chair(1.2, -0.9, Math.PI / 2);

// the sofa (faces the camera, seat top y=0.47), cushions, a lamp table
const sofa = new THREE.Group(); sofa.position.set(0.15, 0, 3.12); world.add(sofa);
add(tbox(2.7, 0.3, 0.95, 1), H2.sofaD, 0, 0.2, 0, sofa);
for (let k = -1; k <= 1; k++) add(tbox(0.88, 0.14, 0.82, 1), H2.sofa, k * 0.9, 0.4, -0.04, sofa);
add(tbox(2.7, 0.62, 0.24, 1), H2.sofaD, 0, 0.62, 0.4, sofa);
for (const sx of [-1, 1]) add(tbox(0.22, 0.52, 0.95, 1), H2.sofaD, sx * 1.34, 0.4, 0, sofa);
const cu = add(tbox(0.4, 0.38, 0.12, 1), H2.cushion, 1.0, 0.68, 0.22, sofa); cu.rotation.z = 0.2;
add(tbox(0.45, 0.45, 0.45, 1), H2.table, -2.0, 0.225, 3.1, world); add(new THREE.CylinderGeometry(0.09, 0.07, 0.13, 14), H2.pot, -2.0, 0.515, 3.1, world);

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
