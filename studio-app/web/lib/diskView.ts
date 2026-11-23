// Disk usage on the Overview page (GET /api/system/disk): the line under the bar, the yellow warning from 80% and the
// red banner from 90% that names the biggest consumers from the weekly housekeeping report. Read-only: the page only
// shows; anything to remove is done on the server with maintenance.sh. Pure functions, tested with node --test.
// Sizes are shown as df -h shows them (powers of 1024), so the numbers match what the server says.

export function size(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = bytes, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  return `${i === 0 ? v : v < 10 ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
}

export function diskLine(d: any): string {
  if (!d) return '';
  return `${size(d.used)} used of ${size(d.size)} (${d.percent}%) · ${size(d.free)} free`;
}

export function biggestText(d: any, n = 4): string {
  const list: any[] = (d?.biggest || []).slice(0, n);
  return list.map(c => `${String(c.label).toLowerCase()} ${size(c.bytes)}`).join(', ');
}

export type Banner = {tone: 'warn' | 'bad'; text: string} | null;

export function diskBanner(d: any): Banner {
  if (!d || d.level === 'ok' || !d.level) return null;
  const left = `${size(d.free)} free`;
  const how = 'On the server, maintenance.sh without options (a dry run) lists what can be removed.';
  if (d.level === 'warn') return {tone: 'warn', text: `The disk is ${d.percent}% full (${left}). ${how}`};
  const big = biggestText(d);
  const report = d.report;
  const freeable = report?.would_free?.total ? ` The last report says about ${size(report.would_free.total)} could be freed.` : '';
  const from = big ? ` Biggest: ${big}${report?.stale ? ` (report ${Math.round(report.age_days)} days old)` : ''}.` : ' No housekeeping report yet to say what uses it.';
  return {tone: 'bad', text: `The disk is ${d.percent}% full (${left}): deploys and new clips can fail.${from}${freeable} ${how}`};
}

export function reportLine(d: any): string {
  if (!d) return '';
  if (!d.report) return d.report_problem || '';
  const r = d.report;
  const age = r.age_days < 1 ? 'today' : `${Math.round(r.age_days)} day(s) ago`;
  const frees = r.mode === 'apply' ? (r.freed?.total ? ` · freed ${size(r.freed.total)}` : '')
    : (r.would_free?.total ? ` · --apply would free about ${size(r.would_free.total)}` : '');
  return `Housekeeping report from ${age} (${r.mode === 'apply' ? 'applied' : 'dry run'})${frees}${r.stale ? ' · old: the weekly report has not run' : ''}`;
}
