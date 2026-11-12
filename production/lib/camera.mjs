// Scene camera (AP-79): outside the renderer. A camera is a zoom about a pivot point that stays fixed on screen,
// plus optional small screen offsets (shake, drift). It applies to WORLD layers only (background, characters);
// screen-space UI (bubbles, header, hook, end card) is never transformed.
//
// Script camera notes are mapped, not invented:
//   "wide"                     -> zoom 1.0 (cut at the beat start)
//   "medium N×" / "medium"     -> zoom N (default 1.3), cut at the beat start
//   "close"                    -> zoom = maxZoom, cut
//   "hard cut, ..."            -> explicit cut (framing changes at a beat start are cuts anyway)
//   "slow push-in to N×"       -> eased zoom to N over the whole beat ("push-in" without "slow": over min(1 s, beat))
//   "pull back to wide"        -> eased zoom to 1.0 over min(1.2 s, beat)
//   "hold" / "still"           -> no change
//   "small shake" / "shake"    -> decaying shake over the beat;  "drift" -> slow drift over the beat
// Unknown wording is an error, so nothing is silently guessed.

export const CAMERA_DEFAULTS = Object.freeze({maxZoom: 1.5, minZoom: 1.0, mediumZoom: 1.3, pushDuration: 1.0, pullDuration: 1.2, shakeAmp: 10, driftAmp: 8});

const smooth = x => { x = Math.max(0, Math.min(1, x)); return x * x * (3 - 2 * x); };

// Parse one script camera note into actions. Returns {framing: {zoom}|null, move: {zoom, duration}|null, shake, drift, hold}.
export function parseCameraNote(note, o = CAMERA_DEFAULTS) {
  const n = String(note).toLowerCase().replace(/\s+/g, ' ').trim();
  const x = n.replace(/[×x](?=\b|$|,)/g, '');           // "1.5×" -> "1.5"
  const out = {note, framing: null, move: null, shake: /shake/.test(n), drift: /drift/.test(n), hold: false, cut: /hard cut/.test(n)};
  let m;
  if ((m = x.match(/push[- ]?in(?: to ([\d.]+))?/))) out.move = {zoom: m[1] ? +m[1] : o.mediumZoom, duration: /slow/.test(n) ? 'beat' : o.pushDuration};
  else if (/pull(?:s)? back/.test(n)) out.move = {zoom: /wide/.test(n) || !(m = x.match(/to ([\d.]+)/)) ? 1.0 : +m[1], duration: o.pullDuration};
  else if ((m = x.match(/medium(?: ([\d.]+))?/))) out.framing = {zoom: m[1] ? +m[1] : o.mediumZoom};
  else if (/\bclose\b/.test(n)) out.framing = {zoom: o.maxZoom};
  else if (/\bwide\b/.test(n)) out.framing = {zoom: 1.0};
  if (/\b(hold|still)\b/.test(n)) out.hold = true;
  const z = out.move?.zoom ?? out.framing?.zoom;
  if (z !== undefined && (!(z >= o.minZoom) || z > o.maxZoom + 1e-9)) throw new Error(`camera note "${note}": zoom ${z} is outside the allowed ${o.minZoom}–${o.maxZoom}× range`);
  if (!out.move && !out.framing && !out.hold && !out.shake && !out.drift && !out.cut) throw new Error(`camera note "${note}" is not recognised; use wide / medium N× / close / push-in to N× / pull back to wide / hold / still / shake / drift`);
  return out;
}

// Build a camera track from per-beat notes [{note, start, end}] (scene-relative seconds, ordered).
export function buildCameraTrack(marks, opts = {}) {
  const o = {...CAMERA_DEFAULTS, ...opts};
  const cuts = [], moves = [], shakes = [], drifts = [];
  let zoom = o.initialZoom ?? 1.0, lastT = -Infinity;
  for (const mk of marks) {
    if (mk.start < lastT - 1e-9) throw new Error('camera notes must be in time order');
    lastT = mk.start;
    const a = parseCameraNote(mk.note, o), beat = mk.end - mk.start;
    if (a.move) {
      const dur = a.move.duration === 'beat' ? beat : Math.min(a.move.duration, beat);
      if (Math.abs(a.move.zoom - zoom) > 1e-9) moves.push({start: mk.start, end: mk.start + dur, from: zoom, to: a.move.zoom, note: mk.note});
      zoom = a.move.zoom;
    } else if (a.framing && Math.abs(a.framing.zoom - zoom) > 1e-9) {
      cuts.push({t: mk.start, from: zoom, to: a.framing.zoom, note: mk.note});
      zoom = a.framing.zoom;
    }
    if (a.shake) shakes.push({start: mk.start, end: mk.end, amp: o.shakeAmp});
    if (a.drift) drifts.push({start: mk.start, end: mk.end, amp: o.driftAmp});
  }
  return {cuts, moves, shakes, drifts, initialZoom: o.initialZoom ?? 1.0, maxZoom: o.maxZoom};
}

// Zoom at time t: piecewise constant with eased moves and instantaneous cuts (deterministic).
export function zoomAt(track, t) {
  let z = track.initialZoom;
  const events = [...track.cuts.map(c => ({t: c.t, kind: 'cut', c})), ...track.moves.map(m => ({t: m.start, kind: 'move', m}))].sort((a, b) => a.t - b.t);
  for (const e of events) {
    if (t < e.t - 1e-9) break;
    if (e.kind === 'cut') z = e.c.to;
    else z = t >= e.m.end ? e.m.to : e.m.from + (e.m.to - e.m.from) * smooth((t - e.m.start) / (e.m.end - e.m.start));
  }
  return z;
}

// Small deterministic screen offsets: decaying shake, slow drift.
export function offsetAt(track, t) {
  let ox = 0, oy = 0;
  for (const s of track.shakes) if (t >= s.start && t < s.end) {
    const p = (t - s.start) / (s.end - s.start), a = s.amp * (1 - p);
    ox += a * Math.sin(2 * Math.PI * 9 * (t - s.start)); oy += a * 0.6 * Math.cos(2 * Math.PI * 7 * (t - s.start));
  }
  for (const d of track.drifts) if (t >= d.start && t < d.end) {
    const u = t - d.start;
    ox += d.amp * Math.sin(2 * Math.PI * u / 6); oy += d.amp * 0.5 * Math.sin(2 * Math.PI * u / 7);
  }
  return {ox, oy};
}

// Camera transform at time t. pivot: world point kept fixed on screen while zooming (e.g. the focus character's head top).
// coverRect: world rect of the background; offsets are clamped so the background always covers the frame.
export function cameraAt(track, t, {pivot, plane, coverRect = null}) {
  const z = zoomAt(track, t);
  let {ox, oy} = offsetAt(track, t);
  if (coverRect) {
    const sx0 = (coverRect.x - pivot.x) * z + pivot.x, sy0 = (coverRect.y - pivot.y) * z + pivot.y;
    const sx1 = sx0 + coverRect.w * z, sy1 = sy0 + coverRect.h * z;
    ox = Math.min(Math.max(ox, plane.width - sx1), -sx0);   // keep left edge <= 0 and right edge >= frame width
    oy = Math.min(Math.max(oy, plane.height - sy1), -sy0);
  }
  return {t, z, ox, oy, pivot};
}

export function applyCamera(cam, {x, y, w}) {
  return {x: (x - cam.pivot.x) * cam.z + cam.pivot.x + cam.ox, y: (y - cam.pivot.y) * cam.z + cam.pivot.y + cam.oy, w: w * cam.z};
}
