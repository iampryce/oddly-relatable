// "Make whole episode", the quality check and the final cut: pure helpers for the guided page (node --test).
// The API decides everything (budget gate, approval gates, provider readiness); these only shape the words.

export type ApStatus = 'off' | 'running' | 'waiting' | 'paused' | 'stopped' | 'finished';

export const AP_STATUS: Record<ApStatus, {text: string; tone: string}> = {
  off: {text: 'Not started', tone: ''},
  running: {text: 'Running', tone: 'busy'},
  waiting: {text: 'Waiting for you', tone: 'warn'},
  paused: {text: 'Paused', tone: 'warn'},
  stopped: {text: 'Stopped', tone: ''},
  finished: {text: 'Finished', tone: 'good'},
};

export function apStatus(s: any): {text: string; tone: string} {
  return AP_STATUS[(s?.status as ApStatus)] || AP_STATUS.off;
}

const money = (x: number) => `$${(Number.isFinite(x) ? x : 0).toFixed(2)}`;

// "$1.20 of $10.00 used · $8.80 left"
export function budgetText(s: any): string {
  if (!s || !s.budget_usd) return 'No budget set yet';
  return `${money(s.spent_usd)} of ${money(s.budget_usd)} used · ${money(s.remaining_usd)} left`;
}

// 0..100 for the progress bar of the budget (never above 100)
export function budgetPercent(s: any): number {
  if (!s || !s.budget_usd) return 0;
  return Math.max(0, Math.min(100, Math.round((s.spent_usd / s.budget_usd) * 100)));
}

// a budget the owner typed: a positive amount up to $500 with at most cents, else null
export function parseBudget(text: string): number | null {
  const t = String(text || '').trim().replace(/^\$/, '');
  if (!/^\d+(\.\d{1,2})?$/.test(t)) return null;
  const n = Number(t);
  return n > 0 && n <= 500 ? n : null;
}

// which buttons make sense now
export function controls(s: any): {start: boolean; pause: boolean; resume: boolean; stop: boolean} {
  const st = (s?.status || 'off') as ApStatus;
  const live = st === 'running' || st === 'waiting';
  return {start: st === 'off' || st === 'stopped' || st === 'finished', pause: live, resume: st === 'paused',
    stop: live || st === 'paused'};
}

// the confirm dialog for the budget: the only consent the autopilot ever gets
export function startConfirmText(budget: number): string {
  return `Make the whole episode with a budget of ${money(budget)}. The autopilot runs the steps in order, starts paid `
    + `work only while it fits in this budget and the monthly GPU cap, and stops to wait for your approvals `
    + `(masters, pictures, crops, poses, clips and the final cut). It never approves anything for you. Start now?`;
}

// a provider row: "Ready" / "Not ready" / "Not needed"
export function providerBadge(p: any): {text: string; tone: string} {
  if (p.ready) return {text: 'Ready', tone: 'good'};
  return p.essential ? {text: 'Needed: not ready', tone: 'bad'} : {text: 'Skipped', tone: 'warn'};
}

// the shot list of the final cut: "Talking shot (approved)" / "Still, not animated"
export function sourceText(r: any): string {
  const t = String(r?.label || r?.source || '');
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : '';
}

// "2.40 s" from frames at 25 fps (or seconds)
export function lengthText(r: any): string {
  const s = r?.seconds ?? (r?.frames ? r.frames / 25 : 0);
  return `${Number(s).toFixed(2)} s`;
}

// a quality-check problem in one line: "1.2 s · clear · style: A nose appears."
export function issueText(i: any): string {
  return `${Number(i.t || 0).toFixed(1)} s · ${i.severity} · ${i.kind}: ${i.what}`;
}

export function checkSummary(c: any): {text: string; tone: string} {
  if (!c?.check) return {text: 'Not checked', tone: ''};
  const n = (c.check.issues || []).length;
  const clear = (c.check.issues || []).filter((i: any) => i.severity === 'clear').length;
  if (!n) return {text: 'No problems found', tone: 'good'};
  return {text: `${n} problem(s)${clear ? `, ${clear} clear` : ''}`, tone: clear ? 'bad' : 'warn'};
}
