// Suggested speakers (speaker_suggest.py): the review table's pure helpers (node --test). Nothing is saved until the
// owner accepts rows; the value accepted for a row is the owner's edit, else the matching character's key, else the
// suggested label.

export type SuggestRow = {line_id: string; start: number; end: number; text: string; current: string; label: string;
  confidence: number; level: string; character_key: string | null; character_name: string | null};

export function defaultValue(r: SuggestRow): string {
  return r.character_key || r.label || '';
}

// The rows to accept: the picked ones (all rows when `all`), with the owner's edits, skipping empty speakers.
export function acceptBody(rows: SuggestRow[], edits: Record<string, string>, picked: Set<string>, all = false): {line_id: string; speaker: string}[] {
  return rows
    .filter(r => all || picked.has(r.line_id))
    .map(r => ({line_id: r.line_id, speaker: (edits[r.line_id] ?? defaultValue(r)).trim().slice(0, 40)}))
    .filter(r => r.speaker);
}

// The rows picked at first: every row with a suggestion whose line has no speaker yet (a typed speaker is never
// replaced unless the owner ticks it).
export function initialPicks(rows: SuggestRow[]): Set<string> {
  return new Set(rows.filter(r => r.label && !r.current).map(r => r.line_id));
}

export function confidenceText(r: SuggestRow, source: string): string {
  if (!r.label) return 'no suggestion';
  return `${r.level} (${Math.round(r.confidence * 100)}%)${source === 'text' ? ', text only' : ''}`;
}

const usd = (x: number) => `$${x < 0.01 && x > 0 ? x.toFixed(4) : x.toFixed(2)}`;

// The button's price: the paid model's "at most" price, or free when only the free tier is ticked.
export function videoPrice(est: any, paid: boolean, free: boolean): string {
  if (!est) return 'cost shown when the video is ready';
  if (!paid && free) return 'free tier, $0.00';
  if (!paid && !free) return 'tick a tier first';
  return `about ${usd(est.usd_typical)}, at most ${usd(est.usd_max)}`;
}

export function confirmAmount(est: any, paid: boolean): number {
  return paid && est ? est.usd_max : 0;
}
