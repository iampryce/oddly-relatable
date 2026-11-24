// The Talking shots section's running total for the ticked lines (each line's estimate: its audio rounded up, with
// the provider's 3 s minimum, at $0.015/s; the server computes each line's figure). Pure; node --test.
export function talkingTotal(rows: {estimate_usd?: number | null; status?: string}[]): number {
  return Math.round(rows.reduce((s, r) => s + (r.status === 'keyed' ? 0 : r.estimate_usd || 0), 0) * 10000) / 10000;
}

// The estimate the server shows for one line (for tests and the label): seconds rounded up, at least 3, at the rate.
export function lineEstimate(seconds: number, rate = 0.015, min = 3): number {
  return Math.round(rate * Math.max(min, Math.ceil(Math.round(seconds * 1000) / 1000)) * 10000) / 10000;
}

// The draft's crop as the owner moves it: 9:16, at most the plate's size, and inside the plate (no bars).
export function clampCrop(c: {x: number; y: number; w: number}, pw: number, ph: number): {x: number; y: number; w: number} {
  const w = Math.max(120, Math.min(c.w, pw, ph * 9 / 16));
  const h = w * 16 / 9;
  return {w: Math.round(w), x: Math.round(Math.min(Math.max(0, c.x), pw - w)), y: Math.round(Math.min(Math.max(0, c.y), ph - h))};
}

// One Talking shots row's clip and keying, in words (the same as its shot comparison cell): keying, failed (with the
// reason), keyed, or "key needs attention" (with the reasons); which links and previews exist; and whether Key again
// (free) is offered. Pure; node --test.
export type RowMedia = {state: string; tone: '' | 'warn' | 'bad' | 'muted'; reasons: string[]; keyAgain: boolean;
  clip?: string; overSet?: string; overGrey?: string; check?: string; keyed?: string; checkFrames: number};

export function rowMedia(r: any): RowMedia {
  const k = r?.key;
  const urls = k?.urls || {};
  const base = {reasons: [] as string[], keyAgain: !!r?.can_key_again, clip: r?.clip_url || undefined,
    overSet: urls.over_set || undefined, overGrey: urls.over_grey || undefined, check: urls.check || undefined,
    keyed: urls.keyed || undefined, checkFrames: (k?.check_at || []).length};
  if (r?.clip_binned) return {...base, state: 'clip in the Bin', tone: 'muted', keyAgain: false};
  if (!r?.clip_url && !k) return {...base, state: '', tone: ''};
  if (!k) return {...base, state: 'clip, not keyed yet', tone: 'muted'};
  if (k.status === 'queued' || k.status === 'running') return {...base, state: `keying ${k.colour || ''} out… (free)`.replace('  ', ' '), tone: 'muted', keyAgain: false};
  if (k.status === 'failed') return {...base, state: `keying failed: ${k.error || 'no reason recorded'}`, tone: 'bad'};
  const q = k.quality;
  if (q && q.ok === false) return {...base, state: 'key needs attention', tone: 'warn', reasons: q.reasons || []};
  return {...base, state: 'keyed', tone: ''};
}
