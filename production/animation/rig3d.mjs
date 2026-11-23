// Studio 3D rig animator (feat/3d-rig PR 2): the 3D stickman, drawn with three.js on the CPU (headless-gl: WebGL 1 in
// software; on Linux it needs a display, the studio runs it under Xvfb). Built from each character's approved 2D rig:
//   - a round torso in the clothing colour wearing the approved clothing art on its front,
//   - black tube limbs with round joints, mitten hands, shoes,
//   - the head: a flat picture that always faces the camera; front = the live 2D face (lip sync, blinks, eyes, the
//     line's expression), three-quarter / side / back = the owner's approved drawings when there are any, else mocks
//     (the live face squashed; the back: the head's outline filled with the hair colour). Left = the right drawing mirrored.
// The acting renderer keeps all its choreography, shots, bubbles, captions and banner; only the characters are drawn
// here, in passes composited onto its frame. Deterministic: no randomness, no clock.
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {deg, headView, pose3d} from './rig3d-pose.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(HERE, '../../skills/directing-stickman-videos/package.json'));

function dominant(img, createCanvas, region = null, skip = rgb => rgb[0] + rgb[1] + rgb[2] < 150) {
  const w = img.width, h = img.height, cv = createCanvas(w, h), x = cv.getContext('2d');
  x.drawImage(img, 0, 0);
  const [rx, ry, rw, rh] = region || [0, 0, w, h];
  const d = x.getImageData(rx, ry, rw, rh).data, n = new Map();
  for (let i = 0; i < d.length; i += 16) {
    if (d[i + 3] < 200) continue;
    const c = [d[i] & 0xf8, d[i + 1] & 0xf8, d[i + 2] & 0xf8];
    if (skip(c)) continue;
    const k = c.join(','); n.set(k, (n.get(k) || 0) + 1);
  }
  let best = null, cnt = -1;
  for (const [k, v] of n) if (v > cnt) { best = k; cnt = v; }
  return best ? best.split(',').map(Number) : [128, 128, 128];
}

export async function create3D({width, height, keys, C, drawHead, createCanvas, loadImage, cast}) {
  const THREE = require('three');
  const createGL = require('gl');
  const gl = createGL(width, height, {preserveDrawingBuffer: true, antialias: false, premultipliedAlpha: false, alpha: true});
  if (!gl) throw new Error('3D rig animator: no WebGL context (on Linux it needs a display: the studio runs it under Xvfb)');
  const canvas = {width, height, style: {}, addEventListener() {}, removeEventListener() {}, getContext: () => gl};
  const renderer = new THREE.WebGLRenderer({canvas, context: gl, alpha: true, premultipliedAlpha: false});
  renderer.setSize(width, height, false);
  renderer.setClearColor(0x000000, 0);
  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(0, width, 0, -height, -100000, 100000);
  camera.position.z = 50000;
  const srgb = (r, g, b) => new THREE.Color().setRGB(r / 255, g / 255, b / 255, THREE.SRGBColorSpace);
  const INK = srgb(18, 18, 18);
  const flat = col => new THREE.MeshBasicMaterial({color: col});
  // a picture from a canvas: rows flipped once in the plane's UVs (canvas row 0 is the top)
  const planeGeo = () => { const g = new THREE.PlaneGeometry(1, 1); const uv = g.attributes.uv; for (let i = 0; i < uv.count; i++) uv.setY(i, 1 - uv.getY(i)); return g; };
  const texFrom = (cv) => {
    const x = cv.getContext('2d'), d = x.getImageData(0, 0, cv.width, cv.height);
    const t = new THREE.DataTexture(new Uint8Array(d.data.buffer.slice(0)), cv.width, cv.height, THREE.RGBAFormat);
    t.colorSpace = THREE.SRGBColorSpace; t.magFilter = THREE.LinearFilter; t.minFilter = THREE.LinearFilter; t.generateMipmaps = false;
    t.needsUpdate = true; return t;
  };
  const toCanvas = (img, w = img.width, h = img.height) => { const cv = createCanvas(w, h); cv.getContext('2d').drawImage(img, 0, 0, w, h); return cv; };
  const unit = {cyl: new THREE.CylinderGeometry(1, 1, 1, 12, 1), ball: new THREE.SphereGeometry(1, 16, 12)};

  const R = {};
  for (const k of keys) {
    const c = C[k], S = c.S, lw = c.lw;
    const cloth = dominant(c.torso, createCanvas), shoe = dominant(c.shoeL, createCanvas);
    const hair = dominant(c.head, createCanvas, [0, 0, c.head.width, Math.max(1, Math.round(c.head.height * 0.22))]);
    const root = new THREE.Group(), body = new THREE.Group();
    root.add(body); scene.add(root);
    // torso: an ellipsoid in the clothing colour around the 2D torso's box, the clothing art on its front, an ink rim
    const tw = c.torso.width, th = c.torso.height, depth = tw * 0.62;
    const tc = {x: c.torsoOff.x + tw / 2, y: -(c.torsoOff.y + th / 2)};
    const torso = new THREE.Mesh(unit.ball, flat(srgb(...cloth)));
    torso.scale.set(tw / 2, th / 2, depth / 2); torso.position.set(tc.x, tc.y, 0); body.add(torso);
    const rim = new THREE.Mesh(unit.ball, new THREE.MeshBasicMaterial({color: INK, side: THREE.BackSide}));
    rim.scale.set(tw / 2 + lw * 0.7, th / 2 + lw * 0.7, depth / 2 + lw * 0.7); rim.position.copy(torso.position); body.add(rim);
    const decal = new THREE.Mesh(planeGeo(), new THREE.MeshBasicMaterial({map: texFrom(toCanvas(c.torso)), transparent: true, alphaTest: 0.35}));
    decal.scale.set(tw, th, 1); decal.position.set(tc.x, tc.y, depth / 2 * 0.97); body.add(decal);
    // limbs: unit cylinders placed between joints each frame, balls at the joints, mitten hands, shoes
    const r = lw * 0.5;
    const tube = () => { const m = new THREE.Mesh(unit.cyl, flat(INK)); body.add(m); return m; };
    const ball = (rad, col = INK) => { const m = new THREE.Mesh(unit.ball, flat(col)); m.scale.setScalar(rad); body.add(m); return m; };
    const limbs = {upper: [tube(), tube()], fore: [tube(), tube()], thigh: [tube(), tube()], shin: [tube(), tube()],
                   joints: Array.from({length: 8}, () => ball(r)), hands: [ball(r * 2.2), ball(r * 2.2)], shoes: [0, 1].map(() => {
                     const g = new THREE.Group(); const s = new THREE.Mesh(unit.ball, flat(srgb(...shoe)));
                     const o = new THREE.Mesh(unit.ball, new THREE.MeshBasicMaterial({color: INK, side: THREE.BackSide}));
                     const sw = c.shoeL.width, sh = c.shoeL.height;
                     s.scale.set(sw * 0.42, sh * 0.5, sw * 0.55); o.scale.set(sw * 0.42 + lw * 0.6, sh * 0.5 + lw * 0.6, sw * 0.55 + lw * 0.6);
                     s.position.z = o.position.z = sw * 0.18; g.add(s); g.add(o); body.add(g); return g; })};
    // the head: the live face canvas (front and mock turns), the approved drawings, the back mock
    const face = c.faces.neutral, fw = face.head.width, fh = face.head.height;
    const live = createCanvas(fw, fh);
    const liveTex = texFrom(live);
    const back = createCanvas(fw, fh), bx = back.getContext('2d');
    bx.drawImage(face.head, 0, 0); bx.globalCompositeOperation = 'source-in'; bx.fillStyle = '#121212'; bx.fillRect(0, 0, fw, fh);
    const inner = createCanvas(fw, fh), ix = inner.getContext('2d');
    ix.drawImage(face.head, 0, 0); ix.globalCompositeOperation = 'source-in'; ix.fillStyle = `rgb(${hair.join(',')})`; ix.fillRect(0, 0, fw, fh);
    bx.globalCompositeOperation = 'source-over'; bx.drawImage(inner, fw * 0.04, fh * 0.04, fw * 0.92, fh * 0.92);
    const drawn = {};
    for (const [angle, file] of Object.entries((cast[k] || {}).head_angles || {})) {
      try { const img = await loadImage(file); drawn[angle] = {tex: texFrom(toCanvas(img)), w: img.width, h: img.height}; } catch { /* the mock */ }
    }
    const head = new THREE.Mesh(planeGeo(), new THREE.MeshBasicMaterial({map: liveTex, transparent: true, alphaTest: 0.35, side: THREE.DoubleSide}));
    scene.add(head);
    R[k] = {c, S, root, body, torso, limbs, head, live, liveTex, backTex: texFrom(back), drawn, fw, fh, depth};
  }

  const tmp = {v: new THREE.Vector3(), up: new THREE.Vector3(0, 1, 0)};
  const place = (m, a, b, rad) => {
    const A = new THREE.Vector3(a.x, a.y, a.z), B = new THREE.Vector3(b.x, b.y, b.z), d = B.clone().sub(A), L = d.length();
    m.position.copy(A).add(B).multiplyScalar(0.5);
    m.scale.set(rad, Math.max(L, 0.001), rad);
    m.quaternion.setFromUnitVectors(tmp.up, L > 1e-6 ? d.normalize() : tmp.up);
  };
  const at = (m, p) => m.position.set(p.x, p.y, p.z);

  function posed(k, p, rank) {
    const X = R[k], c = X.c, S = X.S, q = pose3d(c, p, S);
    X.root.position.set(p.hip.x, -p.hip.y, rank * 2000);
    X.root.scale.set(S / Math.sqrt(q.squash), S * q.squash, S / Math.sqrt(q.squash));
    X.root.rotation.set(0, q.yaw * deg, 0);
    X.body.rotation.set(0, 0, q.roll);
    const r = c.lw * 0.5, L = X.limbs;
    q.legs.forEach((g, i) => {
      place(L.thigh[i], g.hip, g.knee, r); place(L.shin[i], g.knee, g.ankle, r);
      at(L.joints[i * 2], g.knee); at(L.joints[i * 2 + 1], g.hip);
      at(L.shoes[i], {x: g.ankle.x, y: g.ankle.y - q.dims.shoe * 0.5, z: g.ankle.z});
    });
    q.arms.forEach((a, i) => {
      place(L.upper[i], a.shoulder, a.elbow, r); place(L.fore[i], a.elbow, a.hand, r);
      at(L.joints[4 + i * 2], a.elbow); at(L.joints[5 + i * 2], a.shoulder); at(L.hands[i], a.hand);
    });
    // the head: at the neck, in front of the body, turned by its view; the face redrawn from the live 2D face
    X.root.updateMatrixWorld(true); X.body.updateMatrixWorld(true);
    const neck = new THREE.Vector3(q.neck.x, q.neck.y, 0).applyMatrix4(X.body.matrixWorld);
    const hv = headView(q.yaw, p.headYaw || 0);
    // the live face: redrawn and uploaded only when it changes (the software renderer's texture upload is the costly
    // part of a frame); the eyes' direction and the blink are quantised so a slow drift does not redraw every frame
    const fo = c.faces.neutral.headOff;
    const fp = {...p, look: {x: Math.round((p.look?.x || 0) * 10) / 10, y: Math.round((p.look?.y || 0) * 10) / 10},
                blink: Math.round((p.blink || 0) * 4) / 4};
    const key = `${fp.expression}|${fp.viseme}|${fp.blink}|${fp.look.x}|${fp.look.y}|${fp.pupilScale || 1}`;
    if (key !== X.faceKey) {
      const lx = X.live.getContext('2d');
      lx.setTransform(1, 0, 0, 1, 0, 0); lx.clearRect(0, 0, X.fw, X.fh);
      lx.translate(-fo.x, -fo.y); drawHead(lx, c, fp);
      X.liveTex.image.data.set(lx.getImageData(0, 0, X.fw, X.fh).data); X.liveTex.needsUpdate = true;
      X.faceKey = key;
    }
    let tex = X.liveTex, w = X.fw, h = X.fh, squash = 1;
    if (hv.view === 'back') tex = X.drawn.back?.tex || X.backTex;
    else if (hv.view !== 'front') {
      const d = X.drawn[hv.view];
      if (d) { tex = d.tex; w = d.w * (X.fh / d.h); } else squash = hv.view === 'side' ? 0.64 : 0.86;
    }
    X.head.material.map = tex;
    const hw = w * S * squash, hh = h * S;
    const cx = (fo.x + X.fw / 2) * S, cy = (fo.y + X.fh / 2) * S;     // the face's centre from the neck, set px (y down)
    const tilt = (p.lean || 0) + (p.headTilt || 0);
    X.head.scale.set(hv.flip ? -hw : hw, hh, 1);
    X.head.rotation.set(0, 0, -tilt);
    X.head.position.set(neck.x + (hv.view === 'front' || hv.view === 'back' ? cx : cx * 0.6 * Math.sign(hv.angle || 1)),
                        neck.y - cy - (p.headNod || 0) * S, rank * 2000 + X.depth * S + 400);
  }

  const pixels = new Uint8Array(width * height * 4);
  const out = createCanvas(width, height), ox = out.getContext('2d');
  // ONE image buffer for every pass, reused (fix/3d-render-memory): a new one per pass is native memory the canvas
  // library frees only lazily, about 8 MB a frame, and the worker's 4 GB limit killed the renderer after ~400 frames
  const img = ox.createImageData(width, height), stride = width * 4;
  // the screen box that holds these characters (set px -> output px), so only that part is rendered (the software
  // renderer's cost is per pixel: a wide shot of four seated characters is a third of the frame)
  function box(ks, poses, view, k) {
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (const key of ks) {
      const X = R[key], c = X.c, p = poses[key], S = X.S, fo = c.faces.neutral.headOff;
      const half = Math.max(X.fw * 0.7, c.armLen * 1.15, (c.legLen + 60) * 0.9) * S + 30;
      x0 = Math.min(x0, p.hip.x - half); x1 = Math.max(x1, p.hip.x + half);
      y0 = Math.min(y0, p.hip.y + (c.neck.y + fo.y) * S - 60 - (p.headNod ? Math.abs(p.headNod) * S : 0));
      y1 = Math.max(y1, p.hip.y + (c.footDrop + 60) * S);
    }
    const sx0 = Math.max(0, Math.floor((x0 - view.x0) * k)), sy0 = Math.max(0, Math.floor((y0 - view.y0) * k));
    const sx1 = Math.min(width, Math.ceil((x1 - view.x0) * k)), sy1 = Math.min(height, Math.ceil((y1 - view.y0) * k));
    return sx1 > sx0 && sy1 > sy0 ? {sx0, sy0, w: sx1 - sx0, h: sy1 - sy0} : null;
  }
  return {
    // draw the characters `ks` (in their 2D poses) for the view {x0, y0, w}, composited onto ctx
    draw(ctx, ks, poses, view) {
      if (!ks.length) return;
      const k = width / view.w, b = box(ks, poses, view, k);
      if (!b) return;
      // the camera sees exactly the box; the box is rendered into the bottom-left of the drawing buffer
      camera.left = view.x0 + b.sx0 / k; camera.right = view.x0 + (b.sx0 + b.w) / k;
      camera.top = -(view.y0 + b.sy0 / k); camera.bottom = -(view.y0 + (b.sy0 + b.h) / k);
      camera.updateProjectionMatrix();
      renderer.setViewport(0, 0, b.w, b.h); renderer.setScissor(0, 0, b.w, b.h); renderer.setScissorTest(true);
      const on = new Set(ks);
      // nearer the camera: lower on the screen (then cast order), so overlapping characters layer like the 2D renderer
      const order = [...ks].sort((a, c) => poses[a].hip.y - poses[c].hip.y || keys.indexOf(a) - keys.indexOf(c));
      for (const key of keys) { const vis = on.has(key); R[key].root.visible = vis; R[key].head.visible = vis; }
      order.forEach((key, i) => posed(key, poses[key], i));
      renderer.render(scene, camera);
      gl.readPixels(0, 0, b.w, b.h, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      // the box's rows, flipped (GL rows run bottom-up), into the top-left of the reused buffer; only that part is put
      const row = b.w * 4;
      for (let y = 0; y < b.h; y++) img.data.set(pixels.subarray((b.h - 1 - y) * row, (b.h - y) * row), y * stride);
      ox.clearRect(0, 0, width, height); ox.putImageData(img, 0, 0, 0, 0, b.w, b.h);   // a FULL clear: the canvas library keeps every put until the canvas is wholly cleared
      ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.drawImage(out, 0, 0, b.w, b.h, b.sx0, b.sy0, b.w, b.h); ctx.restore();
    },
  };
}
