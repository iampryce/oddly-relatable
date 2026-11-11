// THROWAWAY technical spike (scratchpad only, not repo tooling): builds a project.json for the UNMODIFIED renderer
// to test layered parallax, sprite+shadow compositing, pose swaps, snap zoom/shake and a tint overlay.
// Usage: node build-spike.cjs SPIKE_DIR
const fs = require('fs'), path = require('path');
const dir = path.resolve(process.argv[2]);
const FPS = 30;
const clamp = x => Math.max(0, Math.min(1, x)), ease = x => { x = clamp(x); return x * x * (3 - 2 * x); }, lerp = (a, b, t) => a + (b - a) * t;
const r = n => +n.toFixed(3);

// Scene geometry in the renderer's design plane (1280 x 720). Plates are 1920x1080 px -> 1280 design units wide.
const FOOT = {x: 492, y: 563};          // placeholder figure's feet (design units)
const S0 = 345 / 738;                    // design units per sprite pixel (figure ~345 units tall; sprite is 3 px/native unit)
const ANCHOR = {x: 900, y: 795};         // feet anchor inside the 1200x930 sprite canvas
const PAR = {back: 0.85, mid: 0.95, sprite: 1.0, front: 1.35};   // parallax coefficients (fraction of the camera zoom applied)

const shots = [
  {start: 0, end: 2.4, pose: 'text', cam: t => ({z: lerp(1.0, 1.12, ease(t / 2.4)), cx: lerp(640, 600, ease(t / 2.4)), cy: 360})},
  {start: 2.4, end: 4.2, pose: 'frozen', cam: t => {
    let z = 2.0, cx = 500, cy = 305;
    if (t > 0.6) z = lerp(2.0, 2.55, ease((t - 0.6) / 0.15));                       // snap zoom on the shock
    if (t > 0.75 && t < 1.35) { const a = 9 * (1 - (t - 0.75) / 0.6); cx += Math.sin(t * 70) * a; cy += Math.cos(t * 55) * a * 0.6; } // shake
    return {z, cx, cy};
  }},
  {start: 4.2, end: 6.0, pose: 'plead', doom: true, cam: t => ({z: lerp(1.25, 1.0, ease(t / 1.8)), cx: lerp(560, 640, ease(t / 1.8)), cy: lerp(380, 360, ease(t / 1.8))})},
];

function layerKeys(span, cam, kind, doomAlpha) {
  const keys = [];
  for (let f = 0; f < Math.round(span * FPS); f++) {
    const t = f / FPS, {z, cx, cy} = cam(t);
    const Zi = 1 + (z - 1) * PAR[kind === 'plate-back' ? 'back' : kind === 'plate-mid' ? 'mid' : kind === 'plate-front' ? 'front' : 'sprite'];
    if (kind.startsWith('plate')) {
      keys.push({t: r(t), x: r((0 - cx) * Zi + 640), y: r((0 - cy) * Zi + 360), w: r(1280 * Zi)});
    } else {
      const fx = (FOOT.x - cx) * Zi + 640, fy = (FOOT.y - cy) * Zi + 360, k = S0 * Zi;
      keys.push({t: r(t), x: r(fx - ANCHOR.x * k), y: r(fy - ANCHOR.y * k), w: r(1200 * k)});
    }
  }
  return keys;
}

const project = {
  version: 1, style: 'B1', grid: false, width: 1920, height: 1080, fps: FPS,
  voice: {path: 'silent.wav', lead: 0, tail: 0},
  captions: [
    {start: 0.2, end: 2.3, text: 'Wide shot with a slow push-in.'},
    {start: 2.5, end: 4.1, text: 'Snap zoom and shake on the shock.'},
    {start: 4.3, end: 5.9, text: 'Tint overlay, pulling back.'},
  ],
  shots: shots.map(s => {
    const span = s.end - s.start, cam = s.cam;
    const L = [];
    L.push({type: 'image', path: 'assets/room-back.png', x: 0, y: 0, w: 1280, keys: layerKeys(span, cam, 'plate-back')});
    L.push({type: 'image', path: 'assets/room-mid.png', x: 0, y: 0, w: 1280, keys: layerKeys(span, cam, 'plate-mid')});
    L.push({type: 'image', path: `assets/figure-${s.pose}-shadow.png`, x: 0, y: 0, w: 100, keys: layerKeys(span, cam, 'sprite')});
    L.push({type: 'image', path: `assets/figure-${s.pose}.png`, x: 0, y: 0, w: 100, keys: layerKeys(span, cam, 'sprite')});
    L.push({type: 'image', path: 'assets/room-front.png', x: 0, y: 0, w: 1280, keys: layerKeys(span, cam, 'plate-front')});
    if (s.doom) {
      const keys = [];
      for (let f = 0; f < Math.round(span * FPS); f++) { const t = f / FPS; keys.push({t: r(t), alpha: r(0.95 * ease((t - 0.3) / 0.5))}); }
      L.push({type: 'image', path: 'assets/doom-tint.png', x: 0, y: 0, w: 1280, keys});
    }
    return {start: s.start, end: s.end, layers: L};
  }),
  sfx: [],
};
fs.writeFileSync(path.join(dir, 'project.json'), JSON.stringify(project));
console.log('wrote project.json', fs.statSync(path.join(dir, 'project.json')).size, 'bytes;', project.shots.reduce((n, s) => n + s.layers.reduce((m, l) => m + (l.keys?.length || 0), 0), 0), 'keyframes');
