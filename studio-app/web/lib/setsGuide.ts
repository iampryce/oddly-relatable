// Step 5 of the guided page, "Sets and seating masters": small pure helpers (node --test). The API (room_sets.py)
// reports the facts and does every check; these only place things on the pictures and word them.

const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));

export type Box = {x: number; y: number; w: number; h: number};

// Two points dragged on a picture (picture pixels) as a box inside the picture, at least 8 px each way.
export function dragBox(a: {x: number; y: number}, b: {x: number; y: number}, picW: number, picH: number): Box {
  const x0 = clamp(Math.min(a.x, b.x), 0, picW), x1 = clamp(Math.max(a.x, b.x), 0, picW);
  const y0 = clamp(Math.min(a.y, b.y), 0, picH), y1 = clamp(Math.max(a.y, b.y), 0, picH);
  const w = Math.max(8, Math.round(x1 - x0)), h = Math.max(8, Math.round(y1 - y0));
  return {x: Math.round(Math.min(x0, picW - w)), y: Math.round(Math.min(y0, picH - h)), w, h};
}

// A box or an oval (picture pixels) drawn over the picture shown at any size, in percent.
export function boxStyle(b: Box, picW: number, picH: number): Record<string, string> {
  const p = (v: number, of: number) => `${((v / Math.max(1, of)) * 100).toFixed(2)}%`;
  return {left: p(b.x, picW), top: p(b.y, picH), width: p(b.w, picW), height: p(b.h, picH)};
}

export function ovalBox(o: {cx: number; cy: number; rx: number; ry: number}): Box {
  return {x: o.cx - o.rx, y: o.cy - o.ry, w: 2 * o.rx, h: 2 * o.ry};
}

// "Slightly screen-left, toward Mortimer (the usual rule)"
export function eyelineText(e: any): string {
  if (!e) return '';
  const dir = e.direction === 'right' ? 'Slightly screen-right' : 'Slightly screen-left';
  return `${dir}, toward ${e.toward}${e.owner ? ' (your choice)' : ' (the usual rule: the main speaker’s side looks right, the others look left toward the speaker)'}`;
}

// The badge of a wall or a seating picture.
export function pictureBadge(rec: any): {text: string; tone: string} {
  if (rec?.busy) return {text: 'Being made', tone: 'busy'};
  if (rec?.approved) return {text: 'Approved', tone: 'good'};
  if ((rec?.takes || []).length) return {text: 'Needs your approval', tone: 'warn'};
  return {text: 'Not made yet', tone: ''};
}

// The character check of one picture, in one line.
export function checkBadge(c: any): {text: string; tone: string} {
  if ((c?.flags || []).length) return {text: 'A character may be missing or merged', tone: 'bad'};
  if (c?.gemini) return {text: `Gemini sees all ${c.names.length}`, tone: 'good'};
  if (c?.heads == null) return {text: 'Heads not counted', tone: ''};
  return {text: `${c.heads} head(s) for ${c.names.length} character(s)`, tone: 'good'};
}

export function repairBadge(r: any): {text: string; tone: string} {
  if (r.approved === true) return {text: 'Approved: it is the picture now', tone: 'good'};
  if (r.approved === false) return {text: 'Rejected', tone: ''};
  if (r.status === 'done') return {text: 'Needs your decision', tone: 'warn'};
  if (r.status === 'failed') return {text: 'Failed', tone: 'bad'};
  return {text: 'Running on the GPU', tone: 'busy'};
}

// "Make the picture · $0.04"
export function makeLabel(cost: any, again: boolean): string {
  const what = again ? 'Make another picture' : 'Make the picture';
  return cost && cost.usd != null ? `${what} · $${cost.usd.toFixed(2)}` : what;
}

export const TOOL_TEXT: Record<string, string> = {
  background: 'Repaint the background behind the people',
  face: 'Fix one face',
};

// What a repair target is called in the picker: "wall:ab12" -> "Wall: back wall"
export function targetLabel(t: string, view: any): string {
  const [kind, ref] = t.split(':');
  if (kind === 'wall') return `Wall: ${(view?.walls || []).find((w: any) => w.id === ref)?.name || ref}`;
  if (kind === 'seating') return `Seating: ${(view?.seating || []).find((s: any) => s.side === ref)?.label || ref}`;
  return `Shot ${ref} still`;
}
