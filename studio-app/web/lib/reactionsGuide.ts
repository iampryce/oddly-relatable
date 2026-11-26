// Steps 6-8 of the guided page, "Reactions and close-ups": small pure helpers (node --test). The API (reactions.py)
// reports the facts and does every check; these only place things on the pictures and word them.

export const BASE_W = 1280;
export const BASE_H = 720;

const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));

// A click on a picture shown at any size, as a point in that picture's own pixels.
export function clickToPicture(clickX: number, clickY: number, boxW: number, boxH: number, picW: number, picH: number): {x: number; y: number} {
  return {x: Math.round((clamp(clickX, 0, boxW) / Math.max(1, boxW)) * picW), y: Math.round((clamp(clickY, 0, boxH) / Math.max(1, boxH)) * picH)};
}

// The crop box (master pixels) drawn over the master thumbnail, in percent.
export function cropStyle(c: {x: number; y: number; w: number; h: number}, mw: number, mh: number): Record<string, string> {
  const p = (v: number, of: number) => `${((v / Math.max(1, of)) * 100).toFixed(2)}%`;
  return {left: p(c.x, mw), top: p(c.y, mh), width: p(c.w, mw), height: p(c.h, mh)};
}

// A face oval (1280x720 base pixels) drawn over the crop thumbnail, in percent.
export function ovalStyle(o: {cx: number; cy: number; rx: number; ry: number}): Record<string, string> {
  const p = (v: number, of: number) => `${((v / of) * 100).toFixed(2)}%`;
  return {left: p(o.cx - o.rx, BASE_W), top: p(o.cy - o.ry, BASE_H), width: p(2 * o.rx, BASE_W), height: p(2 * o.ry, BASE_H)};
}

// The zoom slider (5..100, percent of the widest 16:9 box the master allows) as a crop width, and back.
export function maxCropWidth(mw: number, mh: number): number {
  return Math.min(mw, (mh * 16) / 9);
}
export function zoomToWidth(zoom: number, mw: number, mh: number): number {
  return Math.round((clamp(zoom, 5, 100) / 100) * maxCropWidth(mw, mh));
}
export function widthToZoom(w: number, mw: number, mh: number): number {
  return Math.round(clamp((w / Math.max(1, maxCropWidth(mw, mh))) * 100, 5, 100));
}

// The chat thread item of one pose: thread key "pose:<shot>:<pose>"
export function poseItem(shot: number, pose: number): string {
  return `${shot}:${pose}`;
}

// One timeline segment in words: "0.00–0.60 s living hold on pose 0", "0.60–0.95 s move 0 → 1"
export function segmentText(s: {kind: string; a: number; b: number; t0: number; t1: number}): string {
  const span = `${s.t0.toFixed(2)}–${s.t1.toFixed(2)} s`;
  if (s.kind === 'move') return `${span} move ${s.a} → ${s.b}`;
  return `${span} ${s.kind === 'live' ? 'living hold' : 'still hold'} on pose ${s.a}`;
}

// The status badge of one pose card.
export function poseBadge(p: any, cropApproved: boolean): {text: string; tone: string} {
  if (p.as_is) return cropApproved ? {text: 'The approved crop', tone: 'good'} : {text: 'Approve the crop first', tone: ''};
  if (p.ready) return {text: 'Approved', tone: 'good'};
  if ((p.takes || []).some((t: any) => t.valid)) return {text: 'Needs your approval', tone: 'warn'};
  if ((p.takes || []).length) return {text: 'Old crop: make it again', tone: 'warn'};
  return {text: 'Not made yet', tone: ''};
}

// The key of a move prompt as the API takes it: the pose a move goes into ("2"), or "hold-2" for a living hold.
export function moveKey(name: string): string {
  const m = /^mv-\d+-(\d+)$/.exec(name);
  if (m) return m[1];
  const h = /^hold-(\d+)$/.exec(name);
  return h ? `hold-${h[1]}` : name;
}

// "Make 2 poses · up to $0.44" (or a note when there is nothing to pay for: every face reused)
export function poseButton(est: any, n: number): string {
  if (!n) return 'Nothing to make';
  return est && est.usd_max > 0 ? `Make ${n} pose${n > 1 ? 's' : ''} · up to $${est.usd_max.toFixed(2)}` : `Make ${n} pose${n > 1 ? 's' : ''} (faces reused, free)`;
}
