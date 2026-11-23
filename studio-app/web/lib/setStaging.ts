// A set's staging in words (Settings > Sets): how many seats, whether the table front is marked. Pure; node --test.
export function stagingSummary(b: any): string {
  const seats = (b?.seats || (b?.seat ? [b.seat] : [])).length;
  return `Staging: ${seats} seat(s)${b?.table_front ? ', table front marked' : ', no table front'}, floor line at ${b?.floor_y ?? '—'} px`;
}

// Seats side by side closer than one head width at the smallest cast height (the same rule as the API's
// acting.spacing_warnings): "seats 2 and 3 are 129 px apart; need 134 px". A warning while you mark or edit seats,
// never a refusal. Seats are numbered as the picture shows them (1-based, the set's order); only seats in the same
// row are compared (hips less than one head width apart in height).
export function spacingWarnings(seats: {x: number; hip_y?: number}[], need: number): {seats: [number, number]; gap: number; text: string}[] {
  if (!need) return [];
  const pts = (seats || []).map((s, i) => ({x: s.x, y: s.hip_y ?? 0, n: i + 1})).sort((a, b) => a.x - b.x);
  const out: {seats: [number, number]; gap: number; text: string}[] = [];
  pts.forEach((p, i) => {
    const q = pts.slice(i + 1).find(o => Math.abs(o.y - p.y) < need);
    if (!q) return;
    const gap = Math.round(q.x - p.x);
    if (gap < need) out.push({seats: [p.n, q.n], gap, text: `seats ${p.n} and ${q.n} are ${gap} px apart; need ${need} px`});
  });
  return out;
}

// Where a seated character faces (feat/3d-rig PR 3; the Studio 3D rig animator turns them): the seat's own choice, else
// '' = by the scene: the reference plan's facings (the speaker turns towards the person addressed), else towards the
// speaker. The owner's choice always wins.
export const FACINGS = ['speaker', 'camera', 'away'] as const;
export function seatFacing(seats: any[], i: number): string {
  return seats[i]?.facing || '';
}
export function facingLabel(f: string): string {
  if (!f) return 'by the scene (the reference plan, else toward the speaker)';
  if (f.startsWith('seat:')) return `toward seat ${Number(f.split(':')[1]) + 1}`;
  return ({speaker: 'toward the speaker', camera: 'toward the camera', away: 'away from the camera'} as Record<string, string>)[f] || f;
}
// The arrow drawn on the picture: x -1 (left), 1 (right) or 0; y 1 (towards the camera, drawn down) or -1 (away).
export function facingArrow(seats: any[], i: number): {x: number; y: number} | null {
  const f = seatFacing(seats, i);
  if (!f) return null;                                 // decided by the scene: no fixed arrow
  if (f === 'camera') return {x: 0, y: 1};
  if (f === 'away') return {x: 0, y: -1};
  const n = f === 'speaker' ? 0 : Number(f.split(':')[1]);
  const t = seats[n];
  if (!t || n === i || Math.abs(t.x - seats[i].x) < 1) return {x: 0, y: 1};
  return {x: Math.sign(t.x - seats[i].x), y: 0};
}
