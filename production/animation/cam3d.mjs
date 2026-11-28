// 3D camera (Gate 1): native 3D characters seen through a perspective camera, drawn with three.js on the CPU
// (headless-gl: WebGL 1 in software; on Linux it needs a display, e.g. xvfb-run). Separate from the parked Studio 3D rig
// animator (rig3d.mjs), which is unchanged.
//
// A character is built from its spec (production/animation/cast3d/<key>.json), never from a picture:
//   - flat toon shading (two tones) and a black ink outline: every rounded part has an inside-out copy pushed out
//     along its normals, drawn in ink behind it (the "inverted hull"); boxes get a slightly bigger inside-out box;
//   - the head is a ball; the face (eyes, pupils, brows, mouth) and the hairline are VECTOR shapes drawn into a picture
//     pressed onto the front of the ball, so they turn and foreshorten with it. The mouth takes Rhubarb's visemes
//     (A-H, X); the brows and eyes take an expression's settings (cam3d-math.mjs);
//   - the hair, ears, clothing (with its drawn details: neckline, collar, buttons, pockets), stick limbs, mitten hands
//     and shoes are native shapes in the spec's colours.
// Deterministic: no randomness, no clock.
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {mouthShape, expression, planarUV, seated, shellScale} from './cam3d-math.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(HERE, '../../skills/directing-stickman-videos/package.json'));

const TOON_V = `
varying vec3 vN; varying vec2 vUv;
void main() { vN = normalize(normalMatrix * normal); vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
// two tones: lit, or a little darker on the side away from the light. Colours are sRGB in and out (no conversion).
const TOON_F = `
uniform vec3 uColor; uniform vec3 uLight; uniform float uShade; uniform float uUseMap; uniform sampler2D uMap;
varying vec3 vN; varying vec2 vUv;
void main() {
  vec3 c = uUseMap > 0.5 ? texture2D(uMap, vUv).rgb : uColor;
  float lit = dot(normalize(vN), uLight) > -0.3 ? 1.0 : uShade;
  gl_FragColor = vec4(c * lit, 1.0);
}`;
// the outline: the inside-out copy, pushed out along its normals (view space) by uThick world units
const INK_V = `
uniform float uThick;
void main() { vec4 mv = modelViewMatrix * vec4(position, 1.0); mv.xyz += normalize(normalMatrix * normal) * uThick; gl_Position = projectionMatrix * mv; }`;
const INK_F = `uniform vec3 uInk; void main() { gl_FragColor = vec4(uInk, 1.0); }`;

const css = c => `rgb(${c.join(',')})`;

export async function createCam3D({width, height, ss = 2, background = [246, 243, 236], floor = [228, 221, 207]}) {
  const THREE = require('three');
  const createGL = require('gl');
  const {createCanvas} = require('@napi-rs/canvas');
  const W = width * ss, H = height * ss;
  const gl = createGL(W, H, {preserveDrawingBuffer: true, antialias: false, alpha: false});
  if (!gl) throw new Error('3D camera: no WebGL context (on Linux it needs a display, e.g. xvfb-run)');
  const canvas = {width: W, height: H, style: {}, addEventListener() {}, removeEventListener() {}, getContext: () => gl};
  const renderer = new THREE.WebGLRenderer({canvas, context: gl, antialias: false});
  renderer.setSize(W, H, false);
  renderer.setClearColor(new THREE.Color().setRGB(...background.map(v => v / 255), THREE.SRGBColorSpace), 1);
  const scene = new THREE.Scene();
  const light = {value: new THREE.Vector3(0, 0, 1)};          // in view space, set per render
  const lightWorld = new THREE.Vector3(-0.55, 0.75, 0.6).normalize();
  const v3 = c => new THREE.Vector3(c[0] / 255, c[1] / 255, c[2] / 255);

  const M = {
    toon: (colour, map = null, shade = 0.88) => new THREE.ShaderMaterial({vertexShader: TOON_V, fragmentShader: TOON_F,
      uniforms: {uColor: {value: v3(colour)}, uLight: light, uShade: {value: shade}, uUseMap: {value: map ? 1 : 0}, uMap: {value: map}}}),
    ink: (colour, thick) => new THREE.ShaderMaterial({vertexShader: INK_V, fragmentShader: INK_F, side: THREE.BackSide,
      uniforms: {uInk: {value: v3(colour)}, uThick: {value: thick}}}),
    flat: colour => new THREE.ShaderMaterial({vertexShader: TOON_V, fragmentShader: TOON_F,
      uniforms: {uColor: {value: v3(colour)}, uLight: light, uShade: {value: 1}, uUseMap: {value: 0}, uMap: {value: null}}}),
  };
  // a texture from a canvas (rows top first: the shapes' texture coordinates put v = 0 at the picture's top row)
  const texture = cv => {
    const d = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height);
    const t = new THREE.DataTexture(new Uint8Array(d.data.buffer.slice(0)), cv.width, cv.height, THREE.RGBAFormat);
    t.magFilter = THREE.LinearFilter; t.minFilter = THREE.LinearMipmapLinearFilter; t.generateMipmaps = true;
    t.needsUpdate = true; return t;
  };
  const refresh = (t, cv) => { t.image.data.set(cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data); t.needsUpdate = true; };

  const ground = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), M.flat(floor));
  ground.rotation.x = -Math.PI / 2; scene.add(ground);

  const pixels = new Uint8Array(W * H * 4);
  const big = createCanvas(W, H), bx = big.getContext('2d'), img = bx.createImageData(W, H);
  const out = createCanvas(width, height), ox = out.getContext('2d');
  return {
    THREE, scene, M, texture, refresh, createCanvas,
    // one frame from a camera {position, target, fov}: rendered at ss x the size, then scaled down (the smoothing)
    render(cam) {
      const camera = new THREE.PerspectiveCamera(cam.fov, width / height, 0.05, 100);
      camera.position.set(cam.position.x, cam.position.y, cam.position.z);
      camera.lookAt(cam.target.x, cam.target.y, cam.target.z);
      camera.updateMatrixWorld(true);
      light.value.copy(lightWorld).transformDirection(camera.matrixWorldInverse);
      renderer.render(scene, camera);
      gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      const row = W * 4;
      for (let y = 0; y < H; y++) img.data.set(pixels.subarray((H - 1 - y) * row, (H - y) * row), y * row);
      bx.putImageData(img, 0, 0);
      ox.imageSmoothingEnabled = true; ox.imageSmoothingQuality = 'high';
      ox.drawImage(big, 0, 0, W, H, 0, 0, width, height);
      return out;
    },
  };
}

// ---------------------------------------------------------------- the face and the hairline (vector shapes)
// The face picture covers the head's front, x and y in head radii (x to the viewer's right, y down), pressed onto the
// ball from the front. The hairline is where the hair's shapes meet the ball, found per pixel, with an ink edge.
function hairBlobs(spec) {
  const h = spec.hair;
  return [{c: [h.mass.c[0], -h.mass.c[1], h.mass.c[2]], r: h.mass.r},
          ...(h.tufts || []).map(([x, y, z, r]) => ({c: [x, -y, z], r: [r, r, r]}))];
}

function paintHairline(ctx, N, spec, front, ink) {
  const blobs = hairBlobs(spec), depth = spec.head.depth, t = spec.line / spec.head.r * 0.55;
  const skin = spec.colours.skin, hair = spec.colours.hair, d = ctx.getImageData(0, 0, N, N), px = d.data;
  for (let j = 0; j < N; j++) {
    const y = -1 + 2 * (j + 0.5) / N;
    for (let i = 0; i < N; i++) {
      const x = -1 + 2 * (i + 0.5) / N, q = 1 - x * x - y * y;
      const P = [x, -y, (front ? 1 : -1) * depth * Math.sqrt(Math.max(0, q))];
      let inside = false, near = Infinity;
      for (const b of blobs) {
        let f = 0, g2 = 0;
        for (let k = 0; k < 3; k++) { const u = (P[k] - b.c[k]) / b.r[k]; f += u * u; g2 += (2 * u / b.r[k]) ** 2; }
        if (f < 1) inside = true;
        near = Math.min(near, (f - 1) / Math.sqrt(g2 || 1));    // distance outside the shape, roughly
      }
      const c = inside ? hair : near < t ? ink : skin, o = (j * N + i) * 4;
      px[o] = c[0]; px[o + 1] = c[1]; px[o + 2] = c[2]; px[o + 3] = 255;
    }
  }
  ctx.putImageData(d, 0, 0);
}

export function paintFace(ctx, N, spec, state = {}, base = null) {
  const F = spec.face, ink = css(spec.colours.ink), e = expression(state.expression), k = N / 2;
  if (base) ctx.drawImage(base, 0, 0); else { ctx.fillStyle = css(spec.colours.skin); ctx.fillRect(0, 0, N, N); }
  ctx.save(); ctx.translate(k, k); ctx.scale(k, k);              // head radii from here on
  ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = ink;
  // eyes: white, ink rim, pupils turned inwards (his look), an eyelid closing from the top
  for (const s of [-1, 1]) {
    const E = F.eyes, cx = s * E.x, cy = E.y;
    ctx.beginPath(); ctx.ellipse(cx, cy, E.rx, E.ry, 0, 0, Math.PI * 2);
    ctx.fillStyle = css(spec.colours.eye_white); ctx.fill();
    ctx.save(); ctx.clip();
    const px = cx - s * E.pupil_in + (state.look?.x || 0) * E.rx * 0.5 + e.pupil.x, py = cy + E.pupil_dy + (state.look?.y || 0) * E.ry * 0.5 + e.pupil.y;
    ctx.beginPath(); ctx.arc(px, py, E.pupil_r, 0, Math.PI * 2); ctx.fillStyle = ink; ctx.fill();
    const lid = Math.max(e.lid, state.blink || 0);
    if (lid > 0) { ctx.fillStyle = css(spec.colours.skin); ctx.fillRect(cx - E.rx, cy - E.ry, 2 * E.rx, 2 * E.ry * lid); }
    ctx.restore();
    ctx.beginPath(); ctx.ellipse(cx, cy, E.rx, E.ry, 0, 0, Math.PI * 2); ctx.lineWidth = E.line; ctx.stroke();
    // brows: an arch over each eye
    const B = F.brows, bx = s * B.x, by = B.y + e.brow.dy, w = B.w / 2, tilt = s * (B.tilt + e.brow.tilt), a = B.arch * e.brow.arch;
    ctx.beginPath(); ctx.moveTo(bx - w, by + a + tilt * w); ctx.quadraticCurveTo(bx, by - a, bx + w, by + a - tilt * w);
    ctx.lineWidth = B.line; ctx.stroke();
  }
  if (F.nose) { ctx.beginPath(); ctx.arc(0, F.nose.y, F.nose.r, 0, Math.PI); ctx.lineWidth = F.eyes.line; ctx.stroke(); }
  // mouth: Rhubarb's viseme shape, sized to the face's mouth, keeping the expression's bend
  const Mo = F.mouth, m = mouthShape(state.viseme || 'X'), bend = (Mo.bend || 0) + e.bend;
  if (m.kind === 'line') {
    const w = Mo.w * m.w / 2, y = Mo.y + m.dy;
    ctx.beginPath(); ctx.moveTo(-w, y); ctx.quadraticCurveTo(0, y + 2 * bend * w, w, y); ctx.lineWidth = Mo.line; ctx.stroke();
  } else {
    const w = Mo.w * m.w, h = Mo.w * m.h;
    ctx.beginPath(); ctx.ellipse(0, Mo.y + h / 2 - Mo.line * 0.5, w / 2, h / 2, 0, 0, Math.PI * 2); ctx.fillStyle = ink; ctx.fill();
  }
  ctx.restore();
}

// ---------------------------------------------------------------- the clothing's drawn details
// The torso picture covers the torso's front, in px of the spec's source picture (its centre line is x = 0).
function paintClothing(ctx, CW, CH, spec) {
  const T = spec.torso, C = spec.clothing, col = spec.colours, ink = css(col.ink), hw = T.width / 2, top = T.top;
  ctx.fillStyle = css(col.top); ctx.fillRect(0, 0, CW, CH);
  ctx.save(); ctx.scale(CW / T.width, CH / (T.bottom - T.top)); ctx.translate(hw, -top);
  ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = ink; ctx.lineWidth = spec.line * 0.45;
  if (C.kind === 'cardigan') {
    const v = C.vneck, tip = top + v.depth, trim = 22, open = 8;
    // the lapel trim either side of the V, the shirt inside it
    ctx.fillStyle = css(col.top_trim);
    for (const s of [-1, 1]) {
      ctx.beginPath(); ctx.moveTo(s * v.half, top - 2); ctx.lineTo(s * (v.half + trim), top - 2); ctx.lineTo(s * open, tip + trim * 1.3);
      ctx.lineTo(s * open, T.bottom + 2); ctx.lineTo(0, T.bottom + 2); ctx.lineTo(0, tip); ctx.closePath(); ctx.fill();
      ctx.beginPath(); ctx.moveTo(s * (v.half + trim), top); ctx.lineTo(s * open, tip + trim * 1.3); ctx.stroke();
    }
    ctx.beginPath(); ctx.moveTo(-v.half, top - 2); ctx.lineTo(v.half, top - 2); ctx.lineTo(0, tip); ctx.closePath();
    ctx.fillStyle = css(col.shirt); ctx.fill(); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(-open, tip + trim); ctx.lineTo(-open, T.bottom); ctx.stroke();
    if (C.collar) {
      for (const s of [-1, 1]) {
        ctx.beginPath(); ctx.moveTo(s * v.half * 0.92, top + 6); ctx.lineTo(s * 4, top + 26); ctx.lineTo(s * v.half * 0.5, top + 58); ctx.closePath();
        ctx.fillStyle = css(col.shirt); ctx.fill(); ctx.stroke();
      }
      ctx.beginPath(); ctx.arc(0, top + 64, 5, 0, Math.PI * 2); ctx.fillStyle = ink; ctx.fill();
    }
    for (const y of C.buttons.ys) { ctx.beginPath(); ctx.arc(C.buttons.x, y, C.buttons.r, 0, Math.PI * 2); ctx.fillStyle = ink; ctx.fill(); }
    const P = C.pockets;
    if (P) for (const s of [-1, 1]) {
      const x = s * P.x - P.w / 2, y = P.y - P.h / 2, r = P.h / 2;
      ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + P.w, y, x + P.w, y + P.h, r); ctx.arcTo(x + P.w, y + P.h, x, y + P.h, r);
      ctx.arcTo(x, y + P.h, x, y, r); ctx.arcTo(x, y, x + P.w, y, r); ctx.closePath(); ctx.stroke();
    }
  }
  ctx.restore();
}

// ---------------------------------------------------------------- the character
export function buildCharacter(R, spec, opts = {}) {
  const {THREE, M, texture, createCanvas} = R, col = spec.colours, J = seated(spec, opts.kneesApart ?? 8), U = J.U;
  const thick = spec.line * U * 0.5;                              // the outline: half the art's line width
  const g = new THREE.Group();
  const add = (mesh, parent = g) => { parent.add(mesh); return mesh; };
  const ball = new THREE.SphereGeometry(1, 40, 28);
  const ellipsoid = (c, r, mat, parent = g, t = thick) => {
    // inked ellipsoid: the outline is its own inside-out ellipsoid (an exact constant thickness on a scaled ball)
    const m = add(new THREE.Mesh(ball, mat), parent); m.position.set(...c); m.scale.set(...r);
    const o = add(new THREE.Mesh(ball, M.ink(col.ink, 0)), parent); o.position.set(...c); o.scale.set(...r.map(v => v + t));
    return m;
  };

  // torso: a lathe (round, a little flattened front to back), front half wearing the clothing's drawn details
  const T = spec.torso, tw = T.width * U, th = (T.bottom - T.top) * U;
  const prof = T.profile.map(([r, y]) => new THREE.Vector2(Math.max(r * tw / 2, 1e-4), y * th));
  const box = {x0: -tw / 2, x1: tw / 2, y0: 0, y1: th};
  const lathe = (start, len) => {
    const geo = new THREE.LatheGeometry(prof, 48, start, len), p = geo.attributes.position, uv = geo.attributes.uv;
    for (let i = 0; i < p.count; i++) { const q = planarUV(p.getX(i), p.getY(i), box); uv.setXY(i, q.u, q.v); }
    return geo;
  };
  const CW = 512, CH = 1024, cloth = createCanvas(CW, CH);
  paintClothing(cloth.getContext('2d'), CW, CH, spec);
  const torso = new THREE.Group(); torso.position.set(0, J.torsoBottom, 0); torso.scale.set(1, 1, T.depth_ratio); g.add(torso);
  add(new THREE.Mesh(lathe(-Math.PI / 2, Math.PI), M.toon(col.top, texture(cloth))), torso);
  add(new THREE.Mesh(lathe(Math.PI / 2, Math.PI), M.toon(col.top)), torso);
  add(new THREE.Mesh(new THREE.LatheGeometry(prof, 48), M.ink(col.ink, thick)), torso);

  // head: a ball, the face picture on its front half, the hairline painted where the hair meets it
  const hr = J.headR, head = new THREE.Group(); head.position.set(J.head.x, J.head.y, J.head.z); g.add(head);
  const hs = new THREE.Group(); hs.scale.set(hr, hr, hr); head.add(hs);
  const half = (start) => {
    const geo = new THREE.SphereGeometry(1, 64, 48, start, Math.PI), p = geo.attributes.position, uv = geo.attributes.uv;
    for (let i = 0; i < p.count; i++) { const q = planarUV(p.getX(i), p.getY(i), {x0: -1, x1: 1, y0: -1, y1: 1}); uv.setXY(i, q.u, q.v); }
    return geo;
  };
  const N = opts.faceSize || 1024;
  const hairFront = createCanvas(N, N), hairBack = createCanvas(N, N), face = createCanvas(N, N);
  paintHairline(hairFront.getContext('2d'), N, spec, true, col.ink);
  paintHairline(hairBack.getContext('2d'), N, spec, false, col.ink);
  paintFace(face.getContext('2d'), N, spec, {}, hairFront);
  const faceTex = texture(face);
  const front = add(new THREE.Mesh(half(0), M.toon(col.skin, faceTex)), hs); front.scale.z = spec.head.depth;
  const back = add(new THREE.Mesh(half(Math.PI), M.toon(col.skin, texture(hairBack))), hs); back.scale.z = spec.head.depth;
  const headInk = add(new THREE.Mesh(ball, M.ink(col.ink, 0)), hs); headInk.scale.set(1 + thick / hr, 1 + thick / hr, spec.head.depth + thick / hr);
  // ears: set back behind the head's outline, so the head's ink line runs in front of them
  const E = spec.head.ears;
  for (const s of [-1, 1]) ellipsoid([s * E.x, -E.y, -0.22], [E.r, E.r * 1.15, E.r * 0.6], M.toon(col.skin), hs, thick / hr);
  // hair: the mass on the top and back, and the tufts
  for (const b of hairBlobs(spec)) ellipsoid(b.c, b.r, M.toon(col.hair), hs, thick / hr);

  // limbs: ink tubes between the joints, round joints, mitten hands, shoes
  const tubeR = spec.line * U / 2, cyl = new THREE.CylinderGeometry(1, 1, 1, 16, 1), inkMat = M.flat(col.ink);
  const up = new THREE.Vector3(0, 1, 0);
  const tube = (a, b) => {
    const A = new THREE.Vector3(a.x, a.y, a.z), B = new THREE.Vector3(b.x, b.y, b.z), d = B.clone().sub(A), L = d.length();
    const m = add(new THREE.Mesh(cyl, inkMat)); m.position.copy(A).add(B).multiplyScalar(0.5); m.scale.set(tubeR, L, tubeR);
    m.quaternion.setFromUnitVectors(up, d.normalize());
  };
  const dot = (p, r = tubeR) => { const m = add(new THREE.Mesh(ball, inkMat)); m.position.set(p.x, p.y, p.z); m.scale.setScalar(r); };
  for (const L of J.legs) { tube(L.hip, L.knee); tube(L.knee, L.ankle); dot(L.knee); dot(L.hip); }
  for (const A of J.arms) {
    tube(A.shoulder, A.elbow); tube(A.elbow, A.hand); dot(A.elbow); dot(A.shoulder);
    const hr2 = spec.hand.r * U, m = add(new THREE.Mesh(ball, inkMat));
    m.position.set(A.hand.x, A.hand.y + hr2 * 0.3, A.hand.z); m.scale.set(hr2 * 0.85, hr2, hr2 * 0.8);
  }
  const S = spec.shoe;
  for (const L of J.legs) ellipsoid([L.sole.x, S.h * U * 0.42, L.sole.z + S.w * U * 0.22], [S.w * U * 0.36, S.h * U * 0.42, S.w * U * 0.55], M.toon(col.shoes));

  return {
    group: g, joints: J,
    // the face for a frame: expression (brows, lids), viseme (mouth), look, blink; redrawn and uploaded
    setFace(state) { paintFace(face.getContext('2d'), N, spec, state, hairFront); R.refresh(faceTex, face); },
  };
}

// a plain chair under a seated character: seat, four legs and a back, inked
export function buildChair(R, J, colour = [120, 138, 160], ink = [14, 14, 14]) {
  const {THREE, M} = R, g = new THREE.Group(), t = 0.006;
  const block = (size, at) => {
    const geo = new THREE.BoxGeometry(...size), m = new THREE.Mesh(geo, M.toon(colour)); m.position.set(...at); g.add(m);
    const o = new THREE.Mesh(geo, M.ink(ink, 0)); o.position.set(...at); o.scale.set(...shellScale(size, t)); g.add(o);
  };
  const top = J.hipY - 0.009, sw = 0.36, sd = 0.3, st = 0.035, z0 = -0.13, z1 = z0 + sd;
  block([sw, st, sd], [0, top - st / 2, (z0 + z1) / 2]);
  for (const x of [-1, 1]) for (const z of [z0 + 0.02, z1 - 0.02]) block([0.026, top - st, 0.026], [x * (sw / 2 - 0.02), (top - st) / 2, z]);
  block([sw, 0.36, 0.028], [0, top + 0.2, z0 + 0.014]);
  return g;
}
