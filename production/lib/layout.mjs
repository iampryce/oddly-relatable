// Chat-stack layout: turns timed items (messages, typing indicators) into renderer keyframes.
// The newest item sits at the bottom of the chat zone; earlier items slide up as new ones arrive,
// and fade out once they pass the top of the zone. A typing indicator occupies a slot while visible;
// when it disappears the stack slides back (or the reply that replaces it takes the slot).
const EPS = 1e-6;

export const LAYOUT_DEFAULTS = Object.freeze({
  marginX: 64,          // side margin for bubbles (design units)
  zoneTop: 470,         // top of the chat zone (below hook/header)
  zoneBottom: 1180,     // bottom of the chat zone (above the character's face)
  gap: 20,              // vertical gap between bubbles
  slide: 0.28,          // seconds for the stack to slide when a new item arrives
  enter: 0.2,           // fade/rise-in duration of a new bubble
  enterRise: 26,        // design units a new bubble rises while appearing
  exitFade: 0.14,       // typing indicator fade-out
  safe: {top: 0.06, bottom: 0.18, left: 0.04, right: 0.04}, // fractions of the frame kept clear for platform UI
});

export function bubbleX(side, width, plane, o = LAYOUT_DEFAULTS) {
  return side === 'left' ? o.marginX : plane.width - o.marginX - width;
}

// Strictly increasing keyframe builder (the renderer rejects equal or decreasing key times).
class Keys {
  constructor() { this.list = []; }
  add(t, props) {
    const last = this.list.at(-1);
    if (last && Math.abs(last.t - t) < 0.0005) { Object.assign(last, props); return; }
    if (last && t < last.t) t = last.t + 0.001;
    this.list.push({t: +t.toFixed(3), ...props});
  }
}

// items: [{id, start, end (Infinity for messages), width, height, x}]
// Returns per-item {from, to, keys} plus settled snapshots of every bubble rectangle for layout checks.
export function stackLayout(items, opts = {}) {
  const o = {...LAYOUT_DEFAULTS, ...opts};
  const times = [...new Set(items.flatMap(it => [it.start, ...(Number.isFinite(it.end) ? [it.end] : [])]))].sort((a, b) => a - b);
  const activeAt = t => items.filter(it => it.start <= t + EPS && t < it.end - EPS).sort((a, b) => a.start - b.start || a.order - b.order);

  // Settled target position of every active item at each event time.
  const states = times.map(t => {
    const active = activeAt(t), pos = new Map();
    let cursor = o.zoneBottom;
    for (let i = active.length - 1; i >= 0; i--) {
      const it = active[i], y = cursor - it.height;
      pos.set(it.id, {y, visible: y >= o.zoneTop - 0.5});
      cursor = y - o.gap;
    }
    return {t, pos};
  });

  const out = new Map(), snapshots = [];
  for (const [si, st] of states.entries()) {
    snapshots.push({t: st.t, rects: [...st.pos].filter(([, p]) => p.visible).map(([id, p]) => {
      const it = items.find(x => x.id === id); return {id, x: it.x, y: p.y, w: it.width, h: it.height};
    })});
    const next = states[si + 1]?.t ?? Infinity;
    for (const [id, p] of st.pos) {
      const it = items.find(x => x.id === id);
      let rec = out.get(id);
      const alpha = p.visible ? 1 : 0;
      const span = (dur) => Math.max(0.04, Math.min(dur, next - st.t - 0.02)); // never overrun the next event
      if (!rec) {
        rec = {id, from: it.start, to: Number.isFinite(it.end) ? it.end : undefined, keys: new Keys(), last: p};
        rec.keys.add(st.t, {y: p.y + o.enterRise, alpha: 0});
        rec.keys.add(st.t + span(o.enter), {y: p.y, alpha});
        out.set(id, rec);
      } else if (Math.abs(rec.last.y - p.y) > 0.01 || rec.last.visible !== p.visible) {
        rec.keys.add(st.t, {y: rec.last.y, alpha: rec.last.visible ? 1 : 0});
        rec.keys.add(st.t + span(o.slide), {y: p.y, alpha});
      }
      rec.last = p;
    }
  }
  // Typing indicators fade out just before they end.
  for (const it of items) if (Number.isFinite(it.end)) {
    const rec = out.get(it.id);
    if (!rec) continue;
    rec.keys.add(Math.max(it.start + 0.05, it.end - o.exitFade), {alpha: rec.last.visible ? 1 : 0});
    rec.keys.add(it.end - 0.001, {alpha: 0});
  }
  const layers = items.map(it => {
    const rec = out.get(it.id);
    return rec ? {id: it.id, x: it.x, from: rec.from, to: rec.to, keys: rec.keys.list} : null;
  }).filter(Boolean);
  return {layers, snapshots, times};
}

// Same interpolation the renderer uses (keyState in autopilot-render.mjs): hold outside the key range,
// smoothstep between neighbouring keys that carry the property.
const smooth = x => { x = Math.max(0, Math.min(1, x)); return x * x * (3 - 2 * x); };
export function interpolate(keys, prop, t, fallback) {
  const ks = keys.filter(k => k[prop] !== undefined);
  if (!ks.length) return fallback;
  if (t <= ks[0].t) return ks[0][prop];
  if (t >= ks.at(-1).t) return ks.at(-1)[prop];
  const i = ks.findIndex(k => k.t > t), a = ks[i - 1], b = ks[i];
  return a[prop] + (b[prop] - a[prop]) * smooth((t - a.t) / (b.t - a.t));
}

// Typing dots: each dot follows its bubble (same y + offset, same fade) and pulses in turn.
export function dotKeys(bubbleKeys, dy, start, end, phase, period = 0.9) {
  const times = new Set(bubbleKeys.map(k => k.t));
  for (let t = start + 0.05; t < end - 0.02; t += 0.15) times.add(+t.toFixed(3));
  const k = new Keys();
  for (const t of [...times].sort((a, b) => a - b)) {
    const inWindow = t >= start && t < end;
    const pulse = inWindow ? 0.35 + 0.65 * Math.max(0, Math.sin(2 * Math.PI * ((t - start) / period - phase))) : 1;
    k.add(t, {y: +(interpolate(bubbleKeys, 'y', t, 0) + dy).toFixed(2), alpha: +(interpolate(bubbleKeys, 'alpha', t, 1) * pulse).toFixed(3)});
  }
  return k.list;
}

const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

// Composition checks over the settled snapshots: safe zones, face, hook and header overlaps.
export function checkLayout({snapshots, plane, faceBoxes = [], hook = null, header = null, safe = LAYOUT_DEFAULTS.safe}) {
  const issues = [];
  const zone = {x: plane.width * safe.left, y: plane.height * safe.top, w: plane.width * (1 - safe.left - safe.right), h: plane.height * (1 - safe.top - safe.bottom)};
  const inside = r => r.x >= zone.x - 0.5 && r.y >= zone.y - 0.5 && r.x + r.w <= zone.x + zone.w + 0.5 && r.y + r.h <= zone.y + zone.h + 0.5;
  for (const s of snapshots) for (const r of s.rects) {
    if (!inside(r)) issues.push({t: s.t, id: r.id, problem: 'outside safe zone'});
    for (const f of faceBoxes) if (s.t >= f.from - EPS && s.t < f.to - EPS && overlap(r, f)) issues.push({t: s.t, id: r.id, problem: `covers the character's face (pose ${f.pose})`});
    if (hook && s.t >= hook.from - EPS && s.t < hook.to - EPS && overlap(r, hook)) issues.push({t: s.t, id: r.id, problem: 'overlaps the hook'});
    if (header && overlap(r, header)) issues.push({t: s.t, id: r.id, problem: 'overlaps the header'});
  }
  for (const [name, r] of [['hook', hook], ['header', header]]) if (r && !inside(r)) issues.push({t: r.from ?? 0, id: name, problem: 'outside safe zone'});
  if (hook && header && overlap(hook, header)) issues.push({t: hook.from, id: 'hook', problem: 'overlaps the header'});
  return {ok: issues.length === 0, issues, safeZone: zone};
}
