// Self-hosted GPU (Settings > GPU worker, and the shot comparison's summary): the words the owner sees for the GPU's
// state, its month against the cap and each session. Pure functions, tested with node --test.
const usd = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? '—' : `$${x.toFixed(d)}`);

export function gpuLine(g: any): string {
  if (!g) return '';
  if (g.mode === 'off') return 'Self-hosted GPU: off (Settings > GPU worker)';
  if (g.mode === 'own') return `Self-hosted GPU: our own machine, no rental cost${g.ok ? '' : ` · cannot run: ${g.reason}`}`;
  const parts = [`Self-hosted GPU: rented ${g.gpu_type} at ${usd(g.price_per_hour)}/h`,
    `${usd(g.spent_usd)} spent this month of the ${usd(g.cap_usd)} cap`];
  if (g.live_session) parts.push('a session is running');
  else if (g.reservation_usd) parts.push(`a new session reserves ${usd(g.reservation_usd)} (boot + up to ${g.max_lifetime_minutes} min)`);
  if (g.warning) parts.push(`over ${Math.round(g.warn_at * 100)}% of the cap`);
  if (!g.ok) parts.push(`cannot run: ${g.reason}`);
  return parts.join(' · ');
}

export function sessionLine(s: any): string {
  const when = (t: number | null | undefined) => (t ? new Date(t * 1000).toISOString().slice(0, 16).replace('T', ' ') : '');
  const head = `${s.gpu_type} · ${usd(s.price_per_hour)}/h · ${s.clips || 0} clip(s) · ${usd(s.cost_usd)}`;
  if (s.status === 'ended') return `${head} · ended ${when(s.ended_at)} (${s.reason})`;
  return `${head} · ${s.status} since ${when(s.launched_at)} · reserved ${usd(s.reserved_usd)}`;
}

// cost per clip including the session's boot and idle time (the proof of concept's pass/fail figure)
export function allInPerClip(s: any): number | null {
  return s.clips ? s.cost_usd / s.clips : null;
}
