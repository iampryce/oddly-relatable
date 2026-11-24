// The episode workspace (feat/episode-workspace): the words and badge tones of its sections, which sections are open,
// the blocking banner, the set panel's seat line and costs. Pure functions; node --test.

export type Section = {key: string; title: string; status: string; label: string; note: string; blocking: boolean;
  open: boolean; jobs: any[]};

export const TONE: Record<string, string> = {done: 'good', action: 'warn', failed: 'bad', running: 'busy', todo: '',
  waiting: '', not_needed: ''};

// A section is open when the server says so (only the current step: quiet by default, 2026-11-23), unless the owner
// opened or closed it during this visit (not kept: the next visit starts quiet again).
export function isOpen(s: Section, overrides: Record<string, boolean>): boolean {
  return overrides[s.key] ?? s.open;
}

// The banner shows only what truly blocks the next step; work in progress is one quiet line, and "nothing is
// blocking" needs no banner at all.
export function bannerText(ws: any): {tone: string; text: string} | null {
  if (ws?.blocker) return {tone: 'warn', text: `Blocked at ${ws.blocker.title}: ${ws.blocker.message}`};
  return null;
}

export function workingText(ws: any): string {
  return ws?.running?.length ? `Working: ${ws.running.join(', ')}.` : '';
}

// The episode's last error is shown only while the episode is in a failed stage (an old error after a retry that
// worked is history, not news).
export function showLastError(ep: any): boolean {
  return !!ep?.last_error && String(ep?.stage || '').endsWith('_failed');
}

export function jobLine(j: any): string {
  const what = String(j.kind || '').replace(/_/g, ' ');
  if (j.status === 'failed') return `${what} #${j.id} failed: ${j.error || 'no message'}`;
  return `${what} #${j.id} ${j.status}…`;
}

// "N seats for M people", and what happens to the extra people.
export function seatsLine(seats: number, people: number): {text: string; short: boolean} {
  const s = `${seats} seat${seats === 1 ? '' : 's'}`;
  if (!people) return {text: s, short: false};
  const text = `${s} for ${people} ${people === 1 ? 'person' : 'people'}`;
  return seats < people ? {text: `${text}: ${people - seats} seated person(s) will stand`, short: true} : {text, short: false};
}

// A candidate's cost: the image (estimate) and the seat suggestion (its estimate).
export function candidateCost(x: any): string {
  const img = x?.estimated_usd != null ? `image about $${Number(x.estimated_usd).toFixed(2)}` : `image ${x?.cost || 'about $0.05-0.20'}`;
  const sug = x?.suggested;
  if (!sug) return img;
  return `${img} · seat suggestion about $${Number(sug.estimated_usd ?? 0).toFixed(3)}`;
}

export function statusTone(status: string): string {
  return ({approved: 'good', candidate: 'warn', rejected: 'bad'} as Record<string, string>)[status] || '';
}
