// Shot comparison batch mode: line selection keys and what each result-grid cell shows.
export const lineKey = (l: {scene_id: number; line: number}) => `${l.scene_id}:${l.line}`;

export function toggleAll(lines: {scene_id: number; line: number}[], on: boolean): Set<string> {
  return new Set(on ? lines.map(lineKey) : []);
}

export type Cell = {url?: string; cost?: string; check?: string; lengthOk?: boolean; state?: string; failed?: string; estimate?: number;
  assetId?: number; binned?: boolean; gpu?: string; terms?: string; key?: any};

// One cell of the grid: the rig render (free) or a model's clip with its actual cost per clip and per second, the
// length check, its state while queued or running, or its failure reason (with a retry).
export function clipCell(plan: any, model: string): Cell {
  if (model === 'rig') {
    if (plan.rig_url) return {url: plan.rig_url, cost: 'free', check: lengthText(plan.rig_check), lengthOk: plan.rig_check?.length_ok};
    if (plan.status === 'preparing') return {state: 'preparing…'};
    return {state: plan.rig_error || 'not rendered'};
  }
  const r = (plan.results || {})[model];
  const est = (plan.requests || []).find((q: any) => q.model === model)?.estimate?.usd;
  if (!r) return {state: plan.status === 'ready' ? `not run (estimate $${(est ?? 0).toFixed(3)})` : 'preparing…', estimate: est};
  // a clip whose provider terms are not confirmed in writing says so, and that it is not for publishing
  const terms = r.terms ? {terms: `${r.terms}${r.publishable === false ? ' · not for publishing' : ''}`} : {};
  if (r.status === 'failed') return {failed: r.error || 'failed', estimate: est, ...terms};
  if (r.status !== 'done') return {state: `${r.status}…${r.progress?.status ? ` (${r.progress.status})` : ''}`};
  if (r.binned) return {binned: true, cost: `$${r.actual_usd.toFixed(3)} · $${r.per_second_usd.toFixed(3)}/s`, ...terms};   // deleted to the Bin
  return {url: r.url, cost: `$${r.actual_usd.toFixed(3)} · $${r.per_second_usd.toFixed(3)}/s`, check: lengthText(r.check), lengthOk: r.check?.length_ok,
    assetId: r.asset_id, ...terms, ...(r.key ? {key: r.key} : {}), ...(r.gpu_seconds !== undefined ? {gpu: `${r.gpu_seconds} GPU s on ${r.worker}; boot and idle time are on the session`} : {})};
}

function lengthText(c: any): string {
  if (!c) return '';
  return `${c.length_ok ? 'length OK' : 'length off'} (${c.video_seconds} s video, ${c.audio_seconds} s audio)${c.held_last_frame ? ', last frame held' : ''}`;
}
