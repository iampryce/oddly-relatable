// Episode 15 study, landscape 1920x1080 @25 fps. Engine sections are the kit's (toon materials, ink contract,
// add/tbox, lights, cards, render targets/post, applyLight, drawActors, swapForNd, renderFrame); the world is new.
import * as THREE from './lib/three.module.js';
import * as T from './toon.js';
import * as P from './paint.js';
import * as SP from './studypaint.js';
import { TOTAL, shotAt, camAt, dofAt, lightFor, actorsAt, FAMX, FAMZ, ART } from './story.js';
import { loadHeads } from './arthead.js';

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
scene.fog = new THREE.Fog('#e9e2d2', 40, 140);

// ---------- world: a workshop (x around 0) and a back yard (x around 20), side by side; the camera cuts between them ----------
const world = new THREE.Group(); scene.add(world);
const ZB = -2.45, ZF = 4.6, XW = 4.2, CEIL = 3.2, YX = 20;
const W2 = {
  floor: texM(P.planks(21), 1, 1, '#c99a62'), wall: toon({ color: '#d8c3a0' }), wallS: toon({ color: '#c9b08a' }), trim: toon({ color: '#6b4a2e' }), beam: toon({ color: '#8a5d3b' }),
  peg: toon({ color: '#b99a6c' }), steel: toon({ color: '#aab2bf' }), dark: toon({ color: '#2a2622' }), wood: toon({ color: '#d9a366' }), woodD: toon({ color: '#b07a44' }), red: toon({ color: '#c8452f' }),
  sky: new THREE.MeshBasicMaterial({ color: '#bfe3f5' }), dust: toon({ color: '#ead7a8' }), bench: toon({ color: '#9b6a3c' }), benchTop: toon({ color: '#c58a52' }),
  grass: toon({ color: '#86c06a' }), grassD: toon({ color: '#6fae58' }), path: toon({ color: '#d9c9a6' }), fence: toon({ color: '#f1e8d6' }), hedge: toon({ color: '#4f9a4a' }), trunk: toon({ color: '#8a5d3b' }), leaf: toon({ color: '#5aa84f' }),
  sun: new THREE.MeshBasicMaterial({ color: '#fff3b0' }), flower: toon({ color: '#f2b5c9' }), flowerY: toon({ color: '#f6d44a' }),
};
M.floor = W2.floor;
// ----- workshop -----
const floor = add(new THREE.PlaneGeometry(XW * 2, ZF - ZB), W2.floor, 0, 0, (ZB + ZF) / 2, world, { cast: false }); floor.rotation.x = -Math.PI / 2; floor.material.map.repeat.set(3, 3);
const wallW = (len, rotY, x, z, mat) => { const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = rotY; world.add(g);
  add(new THREE.PlaneGeometry(len, CEIL), mat, 0, CEIL / 2, 0, g, { cast: false }); add(tbox(len, 0.14, 0.05, 1), W2.trim, 0, 0.07, 0.025, g); add(tbox(len, 0.12, 0.06, 1), W2.trim, 0, CEIL - 0.06, 0.03, g); return g; };
wallW(XW * 2, 0, 0, ZB, W2.wall); wallW(XW * 2, Math.PI, 0, ZF, W2.wall); wallW(ZF - ZB, Math.PI / 2, -XW, (ZB + ZF) / 2, W2.wallS); wallW(ZF - ZB, -Math.PI / 2, XW, (ZB + ZF) / 2, W2.wallS);
add(new THREE.PlaneGeometry(XW * 2, ZF - ZB), W2.trim, 0, CEIL, (ZB + ZF) / 2, world, { cast: false }).rotation.x = Math.PI / 2;
for (let k = -3; k <= 3; k++) add(tbox(0.16, 0.2, ZF - ZB, 1), W2.beam, k * 1.2, CEIL - 0.1, (ZB + ZF) / 2, world);
// pegboard with tools on the back wall
add(box(3.0, 1.3, 0.04), W2.peg, -1.5, 1.75, ZB + 0.03, world, { cast: false });
for (let k = 0; k < 4; k++) { const hx = -2.7 + k * 0.62, hy = 1.95;                                        // hammers, wrench-like bars, a saw
  if (k % 2 === 0) { add(box(0.04, 0.34, 0.03), W2.woodD, hx, hy, ZB + 0.07, world, { cast: false }); add(box(0.14, 0.07, 0.04), W2.steel, hx, hy + 0.17, ZB + 0.07, world, { cast: false }); }
  else add(box(0.05, 0.4, 0.03), W2.steel, hx, hy, ZB + 0.07, world, { cast: false }); }
{ const saw = add(new THREE.ConeGeometry(0.1, 0.55, 3), W2.steel, -0.35, 1.7, ZB + 0.07, world, { cast: false }); saw.rotation.z = Math.PI / 2; saw.scale.z = 0.2; }
// window with sky, right side
{ const g = new THREE.Group(); g.position.set(2.1, 1.75, ZB + 0.01); world.add(g); add(box(1.5, 1.15, 0.02), W2.sky, 0, 0, 0, g, { cast: false });
  add(tbox(1.64, 0.07, 0.08, 1), W2.trim, 0, 0.61, 0.03, g); add(tbox(1.64, 0.07, 0.08, 1), W2.trim, 0, -0.61, 0.03, g); for (const sx of [-1, 1]) add(tbox(0.07, 1.29, 0.08, 1), W2.trim, sx * 0.785, 0, 0.03, g);
  add(tbox(0.05, 1.15, 0.06, 1), W2.trim, 0, 0, 0.03, g); add(tbox(1.5, 0.05, 0.06, 1), W2.trim, 0, 0, 0.03, g); }
// workbench along the back wall, with a vise, a red toolbox and planks leaning on the wall
{ const bg = new THREE.Group(); bg.position.set(-1.6, 0, ZB + 0.55); world.add(bg);
  add(tbox(2.6, 0.07, 0.8, 1), W2.benchTop, 0, 0.9, 0, bg); for (const sx of [-1, 1]) for (const sz of [-1, 1]) add(tbox(0.09, 0.87, 0.09, 1), W2.bench, sx * 1.2, 0.435, sz * 0.34, bg);
  add(tbox(2.4, 0.08, 0.05, 1), W2.bench, 0, 0.5, -0.34, bg); add(tbox(0.34, 0.2, 0.2, 1), W2.steel, 0.9, 1.03, 0.2, bg); add(tbox(0.5, 0.2, 0.26, 1), W2.red, -0.7, 1.04, -0.1, bg); }
for (let k = 0; k < 4; k++) { const pl = add(tbox(0.16, 1.8, 0.03, 1), k % 2 ? W2.wood : W2.woodD, 3.3 + k * 0.17, 0.9, ZB + 0.12 + k * 0.04, world); pl.rotation.z = -0.08; }
// sawhorses and sawdust
for (const sx of [-1, 1]) { const sh = new THREE.Group(); sh.position.set(0.2 + sx * 0.9, 0, -1.2); world.add(sh);
  add(tbox(0.12, 0.08, 0.6, 1), W2.woodD, 0, 0.62, 0, sh); for (const sz of [-1, 1]) { const lg = add(tbox(0.07, 0.66, 0.07, 1), W2.woodD, 0, 0.3, sz * 0.26, sh); lg.rotation.x = sz * 0.28; } }
for (let k = 0; k < 14; k++) { const d = add(new THREE.CylinderGeometry(0.05 + (k % 3) * 0.02, 0.05 + (k % 3) * 0.02, 0.004, 14), W2.dust, -2.4 + (k * 0.37) % 5.2, 0.004, -0.6 + ((k * 0.53) % 2.4), world, { cast: false }); }
// ----- back yard -----
const yard = new THREE.Group(); yard.position.set(YX, 0, 0); world.add(yard);
add(new THREE.PlaneGeometry(13, 14), W2.grass, 0, 0, 2.5, yard, { cast: false }).rotation.x = -Math.PI / 2;
for (let k = 0; k < 18; k++) add(new THREE.CircleGeometry(0.5 + (k % 4) * 0.25, 14), W2.grassD, -6 + (k * 1.9) % 12, 0.003, -1 + ((k * 1.3) % 6), yard, { cast: false }).rotation.x = -Math.PI / 2;
add(new THREE.PlaneGeometry(1.3, 9), W2.path, 0, 0.004, 1.5, yard, { cast: false }).rotation.x = -Math.PI / 2;
for (let k = -9; k <= 9; k++) { add(tbox(0.17, 1.3, 0.04, 1), W2.fence, k * 0.38, 0.65, -3.0, yard); add(tbox(0.17, 0.09, 0.05, 1), W2.fence, k * 0.38, 1.3, -3.0, yard); }
add(tbox(7.4, 0.07, 0.06, 1), W2.fence, 0, 0.35, -3.03, yard); add(tbox(7.4, 0.07, 0.06, 1), W2.fence, 0, 0.95, -3.03, yard);
for (let k = 0; k < 5; k++) { const h = add(new THREE.SphereGeometry(0.55, 14, 10), W2.hedge, -5.6 + k * 0.9, 0.4, -3.4, yard); h.scale.set(1, 0.8, 0.8); }
{ const t = new THREE.Group(); t.position.set(-3.6, 0, -2.2); yard.add(t); add(new THREE.CylinderGeometry(0.16, 0.22, 1.6, 10), W2.trunk, 0, 0.8, 0, t);
  [[0, 2.1, 0, 0.95], [-0.5, 1.8, 0.1, 0.7], [0.55, 1.85, -0.1, 0.72]].forEach(([x, y, z, r]) => add(new THREE.SphereGeometry(r, 14, 10), W2.leaf, x, y, z, t)); }
for (let k = 0; k < 9; k++) { const fx = 2.6 + (k * 0.37) % 2.6, fz = -2.4 + (k * 0.61) % 1.2; add(new THREE.CylinderGeometry(0.01, 0.01, 0.2, 5), W2.hedge, fx, 0.1, fz, yard, { cast: false }); add(new THREE.SphereGeometry(0.05, 8, 6), k % 2 ? W2.flower : W2.flowerY, fx, 0.22, fz, yard, { cast: false }); }
add(new THREE.PlaneGeometry(26, 14), W2.sky, 0, 6, -8, yard, { cast: false }); add(new THREE.CircleGeometry(0.7, 28), W2.sun, 4.5, 5.2, -7.9, yard, { cast: false });

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
await loadHeads(T, ART || {});
window.ready = true;
