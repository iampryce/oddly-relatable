// The Talking shots section's running total for the ticked lines (each line's estimate: its audio rounded up, with
// the provider's 3 s minimum, at $0.015/s; the server computes each line's figure). Pure; node --test.
export function talkingTotal(rows: {estimate_usd?: number | null; status?: string}[]): number {
  return Math.round(rows.reduce((s, r) => s + (r.status === 'keyed' ? 0 : r.estimate_usd || 0), 0) * 10000) / 10000;
}

// The estimate the server shows for one line (for tests and the label): seconds rounded up, at least 3, at the rate.
export function lineEstimate(seconds: number, rate = 0.015, min = 3): number {
  return Math.round(rate * Math.max(min, Math.ceil(Math.round(seconds * 1000) / 1000)) * 10000) / 10000;
}
