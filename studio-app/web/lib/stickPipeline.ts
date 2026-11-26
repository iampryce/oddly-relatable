// The stick pipeline (2026-11-25): character masters, sheets from the approved master, shot stills and animation.
// Pure helpers for the pages; node --test. Prices come from the API: images are priced PER IMAGE, video PER SECOND of
// video (WaveSpeed's model list gives a video model's price per second: $0.06/s is $0.30 for a 5 s clip). Nothing here
// starts or approves anything: every paid action is a click on a button that shows its price first.

export type Cost = {usd: number; label: string};

// $0.04, $0.30, $1.20; tiny chat costs keep four decimals
export function usd(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(x)) return 'cost unknown';
  return `$${x > 0 && x < 0.01 ? x.toFixed(4) : x.toFixed(2)}`;
}

// chat messages cost fractions of a cent: four decimals under a dollar
export function usd4(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(x)) return 'cost unknown';
  return `$${x < 1 ? x.toFixed(4) : x.toFixed(2)}`;
}

export function imageCost(count: number, perImage: number): Cost {
  const total = Math.round(count * perImage * 10000) / 10000;
  return {usd: total, label: `${count} image${count === 1 ? '' : 's'} x ${usd(perImage)} = ${usd(total)}`};
}

// seconds x price per second (x clips): never the per-second price alone
export function videoCost(seconds: number, perSecond: number, clips = 1): Cost {
  const each = Math.round(seconds * perSecond * 10000) / 10000;
  const total = Math.round(clips * each * 10000) / 10000;
  const one = `${seconds} s x ${usd(perSecond)}/s = ${usd(each)}`;
  return {usd: total, label: clips === 1 ? one : `${clips} clips x ${one} = ${usd(total)}`};
}

// the question asked before a paid start; the button sends the same amount as confirm_usd
export function confirmText(what: string, cost: Cost | null | undefined): string {
  return cost ? `${what}: ${cost.label}. Start now? (paid, not retried by itself)` : `${what}: the cost is unknown, so it cannot start.`;
}

// Animate all: approved shots with a frame and no clip yet (the API decides too; this is for the button's label)
export function animateAllShots(shots: any[]): number[] {
  return (shots || []).filter(s => s.approved && s.chosen && !(s.clips || []).length).map(s => s.index);
}

export function clipStatus(info: any): {tone: 'good' | 'warn' | ''; text: string} {
  if (!info?.clips?.length) return {tone: '', text: 'no clip'};
  return info.clip_approved ? {tone: 'good', text: 'clip approved'} : {tone: 'warn', text: 'clip to review'};
}

export function chosenClip(info: any): any | null {
  return (info?.clips || []).find((c: any) => c.asset_id === info.clip_chosen) || null;
}

// "about $0.0040 (at most $0.0820)" for a chat message before it is sent
export function chatEstimateText(e: any): string {
  if (!e) return '';
  return `${e.label}: about ${usd4(e.usd_typical)} (at most ${usd4(e.usd_max)}), ~${e.input_tokens} tokens in`;
}

// "1,200 in / 300 out tokens · $0.0108" after the answer
export function chatUsageText(m: any): string {
  if (!m?.usage) return '';
  const n = (x: number) => x.toLocaleString('en-US');
  return `${n(m.usage.input_tokens)} in / ${n(m.usage.output_tokens)} out tokens · ${usd4(m.usd)}`;
}
