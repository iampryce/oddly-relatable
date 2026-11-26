// Step 9 of the guided page, "Talking shots": small pure helpers (node --test). The API (talking_s2v.py) reports the
// facts; the words live here.

export const usd = (x: number | null | undefined, d = 2) =>
  x === null || x === undefined ? '—' : `$${x < 0.01 && x > 0 ? x.toFixed(4) : x.toFixed(d)}`;

// "about $0.40, at most $0.55 (about 22 GPU min)"
export function renderCost(e: any): string {
  if (!e || !e.minutes) return '';
  return `about ${usd(e.usd_typical)}, at most ${usd(e.usd_max)} (about ${Math.round(e.minutes)} GPU min)`;
}

// Live progress of one shot's render: queued and preparing show no bar; while rendering, the share of the estimated
// time that has passed, held at 95% until the result arrives.
export function progress(run: any, nowSec: number): {label: string; pct: number | null} {
  if (!run) return {label: '', pct: null};
  if (run.status === 'queued') return {label: run.stage || 'Waiting to start', pct: null};
  if (run.status === 'rendering') {
    const est = Math.max(1, run.est_s || 1);
    const done = Math.max(0, nowSec - (run.started || nowSec));
    const pct = Math.min(95, Math.round((100 * done) / est));
    const left = Math.max(0, Math.round((est - done) / 60));
    return {label: `${run.stage || 'Rendering'} · ${pct}%${left ? ` · about ${left} min left` : ''}`, pct};
  }
  if (run.status === 'failed') return {label: `Failed: ${run.error || 'unknown error'}`, pct: null};
  if (run.status === 'skipped') return {label: run.error || 'Not started', pct: null};
  return {label: '', pct: null};
}

export function isActive(run: any): boolean {
  return !!run && (run.status === 'queued' || run.status === 'rendering');
}

// The movement guide line shown on each row, with a tone for the badge.
export function guideBadge(g: any): {text: string; tone: string} {
  if (!g) return {text: '', tone: ''};
  const tone = g.state === 'ok' ? 'good' : g.state === 'off' ? '' : g.state === 'not_read' ? 'busy' : 'warn';
  return {text: g.text, tone};
}

// The click on a still thumbnail (shown at any size) as a point in the 1024x576 still the model sees.
export function clickToStill(clickX: number, clickY: number, boxW: number, boxH: number): {x: number; y: number} {
  const x = Math.round((Math.max(0, Math.min(boxW, clickX)) / Math.max(1, boxW)) * 1024);
  const y = Math.round((Math.max(0, Math.min(boxH, clickY)) / Math.max(1, boxH)) * 576);
  return {x, y};
}

// "2 pieces (77 + 37 frames)" for a shot longer than one 77-frame piece
export function piecesText(p: number[] | undefined): string {
  if (!p || p.length === 0) return '';
  return p.length === 1 ? `1 piece (${p[0]} frames)` : `${p.length} pieces (${p.join(' + ')} frames)`;
}
