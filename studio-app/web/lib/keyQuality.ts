// The keyed copy's built-in check (talking_key.py), in the shot comparison's cell: "Keyed", or "Key needs attention"
// with the reasons, and one line with the measurements (the background over grey, pink pixels left, the key colour
// at the start and at the end of the clip). Pure functions, tested with node --test.

export function keyQuality(k: any): {ok: boolean; reasons: string[]; line: string} {
  const q = k?.quality;
  if (!q) return {ok: true, reasons: [], line: ''};      // keyed before the check existed: nothing measured
  const rgb = (c: number[] | undefined) => (c && c.length === 3 ? `(${c.join(',')})` : '?');
  const line = `Check over grey: background up to ${q.bg_dev_max} off grey (limit ${q.limits?.bg_dev}), ` +
    `${q.pink_max} pink pixels left at most (limit ${q.limits?.pink}); key colour ${rgb(q.key_first)} at the start, ${rgb(q.key_last)} at the end`;
  return {ok: q.ok !== false, reasons: q.reasons || [], line};
}

export function checkFrames(at: number[] | undefined): string {
  const t = at || [];
  if (!t.length) return 'open';
  if (t.length <= 3) return t.map(x => `${x} s`).join(', ');
  return `one per second (${t.length} frames, ${t[0]}–${t[t.length - 1]} s)`;
}
