// 3D camera (Gate 1): native 3D characters seen through a perspective camera, drawn with three.js on the CPU
// (headless-gl: WebGL 1 in software; on Linux it needs a display, e.g. xvfb-run). Separate from the parked Studio 3D rig
// animator (rig3d.mjs), which is unchanged.
//
// The look (owner review of the first stills, 2026-11-24):
//   - flat colours, no shading at all;
//   - one ink line of the art's own width on every edge: each part is drawn a second time in a flat "part number"
//     colour, and wherever two different parts (or a part and the room) meet, a line of that width is drawn centred on
//     the edge. Limbs and hands are ink already and make no lines;
//   - drawn 4x larger and averaged down (a box filter), so the edges are smooth.
// A character is built from its spec (production/animation/cast3d/<key>.json), measured from the approved art:
//   - torso: a round shape turned from the traced vest outline, the clothing details drawn on its front;
//   - head: a ball the size of the approved head; the face sits on a gently curved plate just in front of it that turns
//     with the head and is cut to the head's outline (so it never shows an edge). The face is either flat vector shapes
//     (eyes, pupils, brows, mouth; Rhubarb's visemes for the mouth) or, for comparison, a picture;
//   - hair: the approved hair's traced outline, given depth and rounded edges, behind the face;
//   - limbs of the measured thickness, the approved curled mitten hands (traced), shoes standing on the floor.
// Deterministic: no randomness, no clock.
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {boxDown, expression, inkMask, mouthShape, pixelsAcross, planarUV, plateZ, seated, throughPeak} from './cam3d-math.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(HERE, '../../skills/directing-stickman-videos/package.json'));

const FLAT_V = `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
// flat colour or picture, sRGB in and out (no conversion, no light); a picture's clear parts are not drawn
const FLAT_F = `
uniform vec3 uColor; uniform float uUseMap; uniform sampler2D uMap; varying vec2 vUv;
void main() {
  vec4 c = uUseMap > 0.5 ? texture2D(uMap, vUv) : vec4(uColor, 1.0);
  if (c.a < 0.5) discard;
  gl_FragColor = vec4(c.rgb, 1.0);
}`;
const ID_F = `uniform vec3 uId; void main() { gl_FragColor = vec4(uId, 1.0); }`;
export const INK_ID = 65535;                                    // limbs and hands: no lines of their own

const css = c => `rgb(${c.join(',')})`;

export async function createCam3D({width, height, ss = 4, background = [246, 243, 236], floor = [228, 221, 207], ink = [14, 14, 14]}) {
  const THREE = require('three');
  const createGL = require('gl');
  const {createCanvas} = require('@napi-rs/canvas');
  const W = width * ss, H = height * ss;
  const gl = createGL(W, H, {preserveDrawingBuffer: true, antialias: false, alpha: false, stencil: true});
  if (!gl) throw new Error('3D camera: no WebGL context (on Linux it needs a display, e.g. xvfb-run)');
  const canvas = {width: W, height: H, style: {}, addEventListener() {}, removeEventListener() {}, getContext: () => gl};
  const renderer = new THREE.WebGLRenderer({canvas, context: gl, antialias: false, stencil: true});
  renderer.setSize(W, H, false);
  const scene = new THREE.Scene();
  const v3 = c => new THREE.Vector3(c[0] / 255, c[1] / 255, c[2] / 255);
  let nextId = 1;
  const ids = new Map();
  const idMat = id => {
    if (!ids.has(id)) ids.set(id, new THREE.ShaderMaterial({vertexShader: FLAT_V, fragmentShader: ID_F, side: THREE.DoubleSide,
      uniforms: {uId: {value: new THREE.Vector3((id % 256) / 255, Math.floor(id / 256) / 255, 0)}}}));
    return ids.get(id);
  };
  const M = {
    flat: (colour, map = null, opts = {}) => new THREE.ShaderMaterial({vertexShader: FLAT_V, fragmentShader: FLAT_F,
      side: opts.side ?? THREE.FrontSide, uniforms: {uColor: {value: v3(colour)}, uUseMap: {value: map ? 1 : 0}, uMap: {value: map}}}),
  };
  // a part: its own part number (every edge against another part gets a line), or the ink number (no lines)
  const part = (mesh, {id = nextId++, inkPart = false} = {}) => { mesh.userData.id = inkPart ? INK_ID : id; return mesh; };
  // a texture from a canvas (rows top first: the shapes' texture coordinates put v = 0 at the picture's top row)
  const texture = cv => {
    const d = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height);
    const t = new THREE.DataTexture(new Uint8Array(d.data.buffer.slice(0)), cv.width, cv.height, THREE.RGBAFormat);
    t.magFilter = THREE.LinearFilter; t.minFilter = THREE.LinearMipmapLinearFilter; t.generateMipmaps = true;
    t.needsUpdate = true; return t;
  };
  const refresh = (t, cv) => { t.image.data.set(cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data); t.needsUpdate = true; };

  const ground = part(new THREE.Mesh(new THREE.PlaneGeometry(40, 40), M.flat(floor)), {id: 0});
  ground.rotation.x = -Math.PI / 2; scene.add(ground);

  const colourPx = new Uint8Array(W * H * 4), idPx = new Uint8Array(W * H * 4), idGrid = new Uint16Array(W * H);
  const out = createCanvas(width, height), ox = out.getContext('2d'), img = ox.createImageData(width, height);
  const clear = c => renderer.setClearColor(new THREE.Color().setRGB(...c.map(v => v / 255), THREE.SRGBColorSpace), 1);
  return {
    THREE, scene, M, part, texture, refresh, createCanvas, ss,
    // one frame from a camera {position, target, fov}; `line`: the ink line's width in world units
    render(cam, line) {
      const camera = new THREE.PerspectiveCamera(cam.fov, width / height, 0.05, 100);
      camera.position.set(cam.position.x, cam.position.y, cam.position.z);
      camera.lookAt(cam.target.x, cam.target.y, cam.target.z);
      camera.updateMatrixWorld(true);
      const meshes = [];
      scene.traverse(o => { if (o.isMesh) meshes.push(o); });
      // the colours
      clear(background); renderer.render(scene, camera);
      gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, colourPx);
      // the part numbers (the face plate has none: its lines are drawn in it)
      const keep = meshes.map(m => [m, m.material, m.visible]);
      for (const m of meshes) { if (m.userData.plate) m.visible = false; else m.material = idMat(m.userData.id ?? 0); }
      clear([0, 0, 0]); renderer.render(scene, camera);
      gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, idPx);
      for (const [m, mat, vis] of keep) { m.material = mat; m.visible = vis; }
      for (let i = 0; i < W * H; i++) idGrid[i] = idPx[i * 4] + idPx[i * 4 + 1] * 256;
      // the line: the art's width, at the distance of what the camera looks at
      const dist = camera.position.distanceTo(new THREE.Vector3(cam.target.x, cam.target.y, cam.target.z));
      const mask = inkMask(idGrid, W, H, pixelsAcross(line, dist, cam.fov, H), INK_ID);
      img.data.set(boxDown(colourPx, W, H, ss, mask, ink));
      ox.putImageData(img, 0, 0);
      return out;
    },
  };
}

// ---------------------------------------------------------------- the face
// The face picture covers the head's front, x and y in head radii (x to the viewer's right, y down); transparent
// except for the features.
export function paintFace(ctx, N, spec, state = {}) {
  const F = spec.face, ink = css(spec.colours.ink), e = expression(state.expression), k = N / 2;
  ctx.clearRect(0, 0, N, N);
  ctx.save(); ctx.translate(k, k); ctx.scale(k, k);              // head radii from here on
  ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = ink;
  const E = F.eyes;
  for (const s of [-1, 1]) {
    // eyes: white, an ink rim, upright oval pupils turned inwards (his look), an eyelid closing from the top
    const cx = s * E.x, cy = E.y;
    ctx.beginPath(); ctx.ellipse(cx, cy, E.rx, E.ry, 0, 0, Math.PI * 2); ctx.fillStyle = css(spec.colours.eye_white); ctx.fill();
    ctx.save(); ctx.clip();
    const px = cx - s * E.pupil_in + (state.look?.x || 0) * E.rx * 0.5 + e.pupil.x, py = cy + E.pupil_dy + (state.look?.y || 0) * E.ry * 0.5 + e.pupil.y;
    ctx.beginPath(); ctx.ellipse(px, py, E.pupil_rx, E.pupil_ry, 0, 0, Math.PI * 2); ctx.fillStyle = ink; ctx.fill();
    const lid = Math.max(e.lid, state.blink || 0);
    if (lid > 0) { ctx.fillStyle = css(spec.colours.skin); ctx.fillRect(cx - E.rx, cy - E.ry, 2 * E.rx, 2 * E.ry * lid); }
    ctx.restore();
    ctx.beginPath(); ctx.ellipse(cx, cy, E.rx, E.ry, 0, 0, Math.PI * 2); ctx.lineWidth = E.line; ctx.stroke();
    // brows: the traced arch (outer end, top, inner end), mirrored for the other side
    const B = F.brows, m = p => [s < 0 ? p[0] : -p[0], p[1] + e.brow.dy + (p === B.outer ? 1 : -1) * e.brow.tilt];
    const a = m(B.outer), b = m(B.inner), c = throughPeak(a, m(B.peak), b);
    ctx.beginPath(); ctx.moveTo(...a); ctx.quadraticCurveTo(...c, ...b); ctx.lineWidth = B.line; ctx.stroke();
  }
  if (F.nose) { ctx.beginPath(); ctx.arc(0, F.nose.y, F.nose.r, 0, Math.PI); ctx.lineWidth = E.line; ctx.stroke(); }
  // mouth: Rhubarb's viseme shape, sized to the face's mouth, keeping the expression's bend
  const Mo = F.mouth, sh = mouthShape(state.viseme || 'X'), bend = (Mo.bend || 0) + e.bend;
  if (sh.kind === 'line') {
    const w = Mo.w * sh.w / 2, y = Mo.y + sh.dy;
    ctx.beginPath(); ctx.moveTo(-w, y); ctx.quadraticCurveTo(0, y + 2 * bend * w, w, y); ctx.lineWidth = Mo.line; ctx.stroke();
  } else {
    const w = Mo.w * sh.w, h = Mo.w * sh.h;
    ctx.beginPath(); ctx.ellipse(0, Mo.y + h / 2 - Mo.line * 0.5, w / 2, h / 2, 0, 0, Math.PI * 2); ctx.fillStyle = ink; ctx.fill();
  }
  ctx.restore();
}

// The face as a picture (for comparison): the approved art's face, cut from inside the head's outline, its skin made
// clear so only the features show.
export function paintFacePicture(ctx, N, spec, img) {
  const H = spec.head, inner = (H.r - spec.line) / H.r, skin = spec.colours.skin;
  ctx.clearRect(0, 0, N, N);
  ctx.drawImage(img, H.cx - H.r, H.cy - H.r, 2 * H.r, 2 * H.r, 0, 0, N, N);
  const d = ctx.getImageData(0, 0, N, N), px = d.data;
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
    const x = -1 + 2 * (i + 0.5) / N, y = -1 + 2 * (j + 0.5) / N, o = (j * N + i) * 4;
    const dc = Math.hypot(px[o] - skin[0], px[o + 1] - skin[1], px[o + 2] - skin[2]);
    if (x * x + y * y > (inner * 0.985) ** 2 || dc < 40) px[o + 3] = 0; else px[o + 3] = 255;
  }
  ctx.putImageData(d, 0, 0);
}

// ---------------------------------------------------------------- the clothing's drawn details
// The torso picture covers the torso's front: art px, x from -hw to hw around the centre line, y from top to bottom.
function paintClothing(ctx, CW, CH, spec, hw, top, bottom) {
  const C = spec.clothing, col = spec.colours, ink = css(col.ink);
  ctx.fillStyle = css(col.top); ctx.fillRect(0, 0, CW, CH);
  ctx.save(); ctx.scale(CW / (2 * hw), CH / (bottom - top)); ctx.translate(hw, -top);
  ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = ink; ctx.lineWidth = spec.line;
  if (C.kind === 'cardigan') {
    const v = C.vneck, tip = top + v.depth, trim = 22, open = 8;
    // the lapel trim either side of the V, the shirt inside it
    ctx.fillStyle = css(col.top_trim);
    for (const s of [-1, 1]) {
      ctx.beginPath(); ctx.moveTo(s * v.half, top - 2); ctx.lineTo(s * (v.half + trim), top - 2); ctx.lineTo(s * open, tip + trim * 1.3);
      ctx.lineTo(s * open, bottom + 2); ctx.lineTo(0, bottom + 2); ctx.lineTo(0, tip); ctx.closePath(); ctx.fill();
      ctx.beginPath(); ctx.moveTo(s * (v.half + trim), top); ctx.lineTo(s * open, tip + trim * 1.3); ctx.lineWidth = spec.line * 0.5; ctx.stroke();
    }
    ctx.lineWidth = spec.line;
    ctx.beginPath(); ctx.moveTo(-v.half, top - 2); ctx.lineTo(v.half, top - 2); ctx.lineTo(0, tip); ctx.closePath();
    ctx.fillStyle = css(col.shirt); ctx.fill(); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(-open, tip + trim); ctx.lineTo(-open, bottom); ctx.stroke();
    if (C.collar) {
      for (const s of [-1, 1]) {
        ctx.beginPath(); ctx.moveTo(s * v.half * 0.92, top + 14); ctx.lineTo(s * 4, top + 30); ctx.lineTo(s * v.half * 0.5, top + 62); ctx.closePath();
        ctx.fillStyle = css(col.shirt); ctx.fill(); ctx.lineWidth = spec.line * 0.6; ctx.stroke();
      }
      ctx.beginPath(); ctx.arc(0, top + 70, 5, 0, Math.PI * 2); ctx.fillStyle = ink; ctx.fill();
    }
    for (const y of C.buttons.ys) { ctx.beginPath(); ctx.arc(C.buttons.x, y, C.buttons.r, 0, Math.PI * 2); ctx.fillStyle = ink; ctx.fill(); }
    const P = C.pockets;
    if (P) for (const s of [-1, 1]) {
      const x = s * P.x - P.w / 2, y = P.y - P.h / 2, r = P.h / 2;
      ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + P.w, y, x + P.w, y + P.h, r); ctx.arcTo(x + P.w, y + P.h, x, y + P.h, r);
      ctx.arcTo(x, y + P.h, x, y, r); ctx.arcTo(x, y, x + P.w, y, r); ctx.closePath(); ctx.lineWidth = spec.line * 0.6; ctx.stroke();
    }
  }
  ctx.restore();
}

// ---------------------------------------------------------------- the character
// opts.face: 'shapes' (vector shapes, the default) or 'picture' with opts.faceImage (the approved art, for comparison).
export function buildCharacter(R, spec, opts = {}) {
  const {THREE, M, part, texture, createCanvas} = R, col = spec.colours, J = seated(spec), U = J.U;
  const g = new THREE.Group();
  const add = (mesh, parent = g, o = {}) => { parent.add(part(mesh, o)); return mesh; };
  const ball = new THREE.SphereGeometry(1, 48, 32);
  const stencil = (mat, ref, func) => {
    mat.stencilWrite = true; mat.stencilRef = ref; mat.stencilFunc = func;
    mat.stencilFail = mat.stencilZFail = THREE.KeepStencilOp;
    mat.stencilZPass = func === THREE.AlwaysStencilFunc ? THREE.ReplaceStencilOp : THREE.KeepStencilOp;
    return mat;
  };

  // torso: turned from the traced vest outline (round, flattened front to back); the front half wears the details
  const T = spec.torso, top = Math.min(...T.profile.map(p => p[1])), bottom = spec.hips.y;
  const hw = Math.max(...T.profile.map(p => p[0]));
  const prof = [...T.profile].sort((a, b) => b[1] - a[1]).map(([r, y]) => new THREE.Vector2(Math.max(r * U, 1e-4), (bottom - y) * U));
  const box = {x0: -hw * U, x1: hw * U, y0: (bottom - bottom) * U, y1: (bottom - top) * U};
  const lathe = (start, len) => {
    const geo = new THREE.LatheGeometry(prof, 64, start, len), p = geo.attributes.position, uv = geo.attributes.uv;
    for (let i = 0; i < p.count; i++) { const q = planarUV(p.getX(i), p.getY(i), box); uv.setXY(i, q.u, q.v); }
    return geo;
  };
  const cloth = createCanvas(512, 1024);
  paintClothing(cloth.getContext('2d'), 512, 1024, spec, hw, top, bottom);
  const torso = new THREE.Group(); torso.position.set(0, J.torsoBottom, 0); torso.scale.set(1, 1, T.depth_ratio); g.add(torso);
  const torsoId = {id: 100};
  add(new THREE.Mesh(lathe(-Math.PI / 2, Math.PI), M.flat(col.top, texture(cloth))), torso, torsoId);
  add(new THREE.Mesh(lathe(Math.PI / 2, Math.PI), M.flat(col.top)), torso, torsoId);

  // head: a ball the approved head's size (it marks the stencil: the face plate is cut to it)
  const hr = J.headR, head = new THREE.Group(); head.position.set(J.head.x, J.head.y, J.head.z); g.add(head);
  const hs = new THREE.Group(); hs.scale.set(hr, hr, hr); head.add(hs);
  const skull = add(new THREE.Mesh(ball, stencil(M.flat(col.skin), 1, THREE.AlwaysStencilFunc)), hs, {id: 101});
  skull.scale.z = spec.head.depth; skull.renderOrder = 0;
  // ears and hair clear the stencil where they cover the head
  const E = spec.head.ears;
  for (const s of [-1, 1]) {
    const ear = add(new THREE.Mesh(ball, stencil(M.flat(col.skin), 0, THREE.AlwaysStencilFunc)), hs, {id: 102 + (s > 0 ? 1 : 0)});
    ear.position.set(s * E.x, -E.y, -0.1); ear.scale.set(E.r, E.r, E.r * 0.5); ear.renderOrder = 1;
  }
  const Hh = spec.hair, cx = spec.head.cx, cy = spec.head.cy, r = spec.head.r;
  // the visible edge as a smooth curve through the traced points, closed under the head (hidden) with straight lines
  const P = ([x, y]) => new THREE.Vector2((x - cx) / r, (cy - y) / r), shape = new THREE.Shape();
  shape.moveTo(...P(Hh.outline[0]).toArray()); shape.splineThru(Hh.outline.slice(1).map(P));
  for (const p of Hh.hidden || []) shape.lineTo(...P(p).toArray());
  shape.closePath();
  const [z0, z1] = Hh.depth, bev = Hh.bevel;
  const hairGeo = new THREE.ExtrudeGeometry(shape, {depth: z1 - z0 - 2 * bev, bevelEnabled: true, bevelThickness: bev,
    bevelSize: bev * 0.35, bevelOffset: -bev * 0.35, bevelSegments: 5, curveSegments: 12});
  const hair = add(new THREE.Mesh(hairGeo, stencil(M.flat(col.hair, null, {side: THREE.DoubleSide}), 0, THREE.AlwaysStencilFunc)), hs, {id: 104});
  hair.position.z = z0 + bev; hair.renderOrder = 1;
  // the face plate: in front of the face, cut to where the head shows
  const N = opts.faceSize || 1024, face = createCanvas(N, N);
  if (opts.face === 'picture') paintFacePicture(face.getContext('2d'), N, spec, opts.faceImage);
  else paintFace(face.getContext('2d'), N, spec, {});
  const faceTex = texture(face);
  const plateGeo = new THREE.PlaneGeometry(2, 2, 64, 64), pp = plateGeo.attributes.position, puv = plateGeo.attributes.uv;
  for (let i = 0; i < pp.count; i++) {
    const x = pp.getX(i), y = pp.getY(i), q = planarUV(x, y, {x0: -1, x1: 1, y0: -1, y1: 1});
    pp.setZ(i, plateZ(x, y, spec.head.depth, spec.face.plate_radius)); puv.setXY(i, q.u, q.v);
  }
  plateGeo.computeVertexNormals();
  const plate = new THREE.Mesh(plateGeo, stencil(M.flat(col.skin, faceTex), 1, THREE.EqualStencilFunc));
  plate.userData.plate = true; plate.renderOrder = 10; hs.add(plate);

  // limbs: ink tubes of the measured thickness, round joints
  const cyl = new THREE.CylinderGeometry(1, 1, 1, 20, 1), inkMat = M.flat(col.ink, null, {side: THREE.DoubleSide});
  const up = new THREE.Vector3(0, 1, 0), V = p => new THREE.Vector3(p.x, p.y, p.z);
  const tube = (a, b, rad) => {
    const A = V(a), B = V(b), d = B.clone().sub(A), L = d.length();
    const m = add(new THREE.Mesh(cyl, inkMat), g, {inkPart: true}); m.position.copy(A).add(B).multiplyScalar(0.5);
    m.scale.set(rad, L, rad); m.quaternion.setFromUnitVectors(up, d.normalize());
  };
  const dot = (p, rad) => { const m = add(new THREE.Mesh(ball, inkMat), g, {inkPart: true}); m.position.copy(V(p)); m.scale.setScalar(rad); };
  const legR = spec.leg.thickness / 2 * U, armR = spec.arm.thickness / 2 * U;
  for (const L of J.legs) { tube(L.hip, L.knee, legR); tube(L.knee, L.ankle, legR); dot(L.knee, legR); dot(L.ankle, legR); }
  // hands: the approved curled mitten (traced), at the wrist, following the forearm; the right one mirrored
  const [wx, wy] = spec.arm.wrist, ht = spec.hand.thickness * U;
  const handShape = new THREE.Shape(spec.hand.outline.map(([x, y]) => new THREE.Vector2((x - wx) * U, (wy - y) * U)));
  const handGeo = new THREE.ExtrudeGeometry(handShape, {depth: ht * 0.6, bevelEnabled: true, bevelThickness: ht * 0.2,
    bevelSize: 0.002, bevelOffset: -0.002, bevelSegments: 3, curveSegments: 8});
  handGeo.translate(0, 0, -ht * 0.3);
  const down = new THREE.Vector3(0, -1, 0);
  J.arms.forEach((A, i) => {
    tube(A.shoulder, A.elbow, armR); tube(A.elbow, A.wrist, armR); dot(A.elbow, armR); dot(A.shoulder, armR);
    const hand = add(new THREE.Mesh(handGeo, inkMat), g, {inkPart: true});
    hand.position.copy(V(A.wrist));
    hand.quaternion.setFromUnitVectors(down, V(A.wrist).sub(V(A.elbow)).normalize());
    if (i === 1) hand.scale.x = -1;                                // the art's left hand, mirrored for the right
  });
  // shoes: domes standing on the floor (flat soles), toes forward
  const S = spec.shoe, dome = new THREE.SphereGeometry(1, 40, 20, 0, Math.PI * 2, 0, Math.PI / 2);
  J.legs.forEach((L, i) => {
    const shoe = add(new THREE.Mesh(dome, M.flat(col.shoes)), g, {id: 110 + i});
    shoe.position.set(L.sole.x + (i ? 1 : -1) * 0.008, 0, L.sole.z + 0.03);
    shoe.scale.set((S.w - spec.line) / 2 * U, (S.h - spec.line / 2) * U, S.length / 2 * U);
  });

  return {
    group: g, joints: J,
    // the face for a frame (shapes only): expression (brows, lids), viseme (mouth), look, blink; redrawn and uploaded
    setFace(state) { paintFace(face.getContext('2d'), N, spec, state); R.refresh(faceTex, face); },
  };
}

// ---------------------------------------------------------------- the chair
// A plain wooden chair like the study's (slatted back, square legs, low stretchers), in its sampled colours.
export const STUDY_CHAIR = {seat: [74, 51, 37], frame: [64, 44, 32], edge: [52, 38, 28]};
export function buildChair(R, J, c = STUDY_CHAIR) {
  const {THREE, M, part} = R, g = new THREE.Group();
  let n = 200;
  const block = (size, at, colour) => { const m = part(new THREE.Mesh(new THREE.BoxGeometry(...size), M.flat(colour)), {id: n++}); m.position.set(...at); g.add(m); return m; };
  const top = J.seatTop, sw = 0.46, sd = 0.29, st = 0.032, z0 = -0.115, z1 = z0 + sd, lg = 0.03, back = 0.34;
  block([sw, 0.006, sd], [0, top - 0.003, (z0 + z1) / 2], c.seat);
  block([sw, st - 0.006, sd], [0, top - 0.006 - (st - 0.006) / 2, (z0 + z1) / 2], c.edge);
  for (const x of [-1, 1]) {
    const lx = x * (sw / 2 - lg / 2 - 0.006);
    block([lg, top - st, lg], [lx, (top - st) / 2, z1 - lg / 2 - 0.006], c.frame);                // front leg
    block([lg, top - st + back, lg], [lx, (top - st + back) / 2, z0 + lg / 2], c.frame);         // back leg and post
    block([0.016, 0.022, sd - 2 * lg], [lx, 0.1, (z0 + z1) / 2], c.frame);                         // side stretcher
  }
  block([sw - 2 * lg + 0.012, 0.02, 0.016], [0, 0.12, z1 - lg / 2 - 0.006], c.frame);              // front stretcher
  const railH = 0.07, railY = top + back - railH / 2 - 0.004;
  block([sw - 0.012, railH, 0.024], [0, railY, z0 + lg / 2], c.frame);                             // top rail
  for (const [x, w] of [[-0.1, 0.022], [0, 0.034], [0.1, 0.022]])
    block([w, back - railH - 0.03, 0.014], [x, top + (back - railH - 0.03) / 2 + 0.01, z0 + lg / 2], c.frame);   // slats
  return g;
}
