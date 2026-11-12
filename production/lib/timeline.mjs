// Animation timeline (AP-79): pose segments + transitions for one cast member, evaluated per frame and combined
// with the camera into renderer keyframes. Transitions never alter artwork: they only move, scale or fade a layer.
//   cut       : the new pose replaces the old one on the frame it starts (AP-78 behaviour)
//   pop       : the new pose appears with a short scale bounce anchored at the feet
//   crossfade : the new pose dissolves in over the old one (old stays opaque underneath, then is removed)
import {applyCamera} from './camera.mjs';

export const TRANSITION_DEFAULTS = Object.freeze({popDuration: 0.2, popAmp: 0.06, crossfade: 0.16});

// Plan one layer per pose segment: visibility window plus scale(t) and alpha(t) in world space.
export function planPoseLayers(segments, opts = {}) {
  const o = {...TRANSITION_DEFAULTS, ...opts};
  const plans = segments.map(s => ({pose: s.pose, start: s.start, end: s.end, transition: s.transition || 'cut', from: s.start, to: s.end, fadeIn: null, fadeOut: null, pop: null}));
  plans.forEach((p, i) => {
    const prev = plans[i - 1];
    if (!prev || p.transition === 'cut') return;
    if (p.transition === 'pop') {
      p.pop = {start: p.start, end: p.start + Math.min(o.popDuration, p.end - p.start), amp: o.popAmp};
    } else if (p.transition === 'crossfade') {
      // Centre the overlap on the pose change, limited to half of either neighbouring segment.
      const half = Math.min(o.crossfade / 2, (p.end - p.start) / 2, (prev.end - prev.start) / 2);
      p.from = p.start - half; prev.to = p.start + half;
      // Dissolve over: the outgoing pose stays opaque underneath while the incoming pose fades in on top
      // (two half-transparent poses would let the room show through the character).
      p.fadeIn = {start: p.start - half, end: p.start + half};
    } else throw new Error(`Unknown transition: ${p.transition}`);
  });
  return plans;
}

export function scaleAt(plan, t) {
  if (!plan.pop || t < plan.pop.start || t >= plan.pop.end) return 1;
  const u = (t - plan.pop.start) / (plan.pop.end - plan.pop.start);
  return 1 + plan.pop.amp * Math.sin(Math.PI * u);           // rises and settles back to exactly 1
}
export function alphaAt(plan, t) {
  let a = 1;
  if (plan.fadeIn && t < plan.fadeIn.end) a = Math.min(a, Math.max(0, (t - plan.fadeIn.start) / (plan.fadeIn.end - plan.fadeIn.start)));
  if (plan.fadeOut && t > plan.fadeOut.start) a = Math.min(a, Math.max(0, (plan.fadeOut.end - t) / (plan.fadeOut.end - plan.fadeOut.start)));
  return a;
}

// World rectangle of a pose at scale s, anchored at the feet point.
export function poseRect(info, placement, s = 1) {
  const k = placement.figureHeight / info.figureHeight * s;
  return {x: placement.feetX - info.feet.x * k, y: placement.feetY - info.feet.y * k, w: info.width * k, k};
}

// Sample a layer value function on the frame grid of [from, to) and keep only the keys the renderer needs:
// the endpoints of every constant run, plus every frame where the value changes (moves, cuts, transitions).
// Frame-exact keys mean the renderer's own smoothstep interpolation never runs between moving keys.
export function sampleKeys(valueAt, from, to, fps) {
  const first = Math.ceil(from * fps - 1e-6), last = Math.ceil(to * fps - 1e-6) - 1;
  const vals = [];
  for (let f = first; f <= last; f++) vals.push({t: +(f / fps).toFixed(4), ...valueAt(f / fps)});
  const same = (a, b) => a && b && a.x === b.x && a.y === b.y && a.w === b.w && a.alpha === b.alpha;
  return vals.filter((v, i) => i === 0 || i === vals.length - 1 || !same(v, vals[i - 1]) || !same(v, vals[i + 1]));
}

const r2 = v => Math.round(v * 100) / 100, r3 = v => Math.round(v * 1000) / 1000;

// Renderer image layers for one cast member: one per planned pose layer, camera applied per frame.
export function castLayers({plans, infos, placement, cameraFor, fps, assetPathFor}) {
  return plans.map(plan => {
    const info = infos.get(plan.pose);
    const keys = sampleKeys(t => {
      const sc = applyCamera(cameraFor(t), poseRect(info, placement, scaleAt(plan, t)));
      return {x: r2(sc.x), y: r2(sc.y), w: r2(sc.w), alpha: r3(alphaAt(plan, t))};
    }, plan.from, plan.to, fps);
    return {type: 'image', path: assetPathFor(info), x: keys[0].x, y: keys[0].y, w: keys[0].w, from: +plan.from.toFixed(4), to: +plan.to.toFixed(4), keys};
  });
}

// Camera-only layer (background, shadows): same per-frame camera, no transitions.
export function worldLayer({path, rect, cameraFor, from, to, fps}) {
  const keys = sampleKeys(t => { const s = applyCamera(cameraFor(t), rect); return {x: r2(s.x), y: r2(s.y), w: r2(s.w), alpha: 1}; }, from, to, fps);
  return {type: 'image', path, x: keys[0].x, y: keys[0].y, w: keys[0].w, keys};
}
