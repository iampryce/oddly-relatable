// Cast from video (guided step 4): pure helpers for the GuideCast component and the cast library (node --test).
// The API checks every price (confirm_usd) and every approval; these only shape what the page shows and sends.

export const STYLE_ORDER = ['stick', 'flat2d', '3d', 'anime', 'clay'] as const;
export type StyleId = typeof STYLE_ORDER[number];

export const HEAD_NOTE = 'Automatic head finding works for the stick-man style; for other styles click each head once.';

export function money(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(x)) return 'cost unknown';
  return `$${x.toFixed(2)}`;
}

// "3 pictures x $0.04 = $0.12" (images are priced per picture)
export function imageCost(n: number, each: number): {usd: number; label: string} {
  const usd = Math.round(n * each * 10000) / 10000;
  return {usd, label: `${n} picture${n === 1 ? '' : 's'} x ${money(each)} = ${money(usd)}`};
}

// the styles ticked for a preview, in the presets' order
export function orderedStyles(ticked: Iterable<string>): StyleId[] {
  const t = new Set(ticked);
  return STYLE_ORDER.filter(s => t.has(s));
}

// One garment per line: "cardigan - green". Blank lines are dropped; a line without " - " has no colour.
export function clothingToText(list: {garment: string; colour?: string}[] | null | undefined): string {
  return (list || []).map(g => (g.colour ? `${g.garment} - ${g.colour}` : g.garment)).join('\n');
}

export function textToClothing(text: string): {garment: string; colour: string}[] {
  return text.split('\n').map(l => l.trim()).filter(Boolean).slice(0, 8).map(l => {
    const i = l.indexOf(' - ');
    return i < 0 ? {garment: l, colour: ''} : {garment: l.slice(0, i).trim(), colour: l.slice(i + 3).trim()};
  }).filter(g => g.garment);
}

export function linesToList(text: string, max = 6): string[] {
  return text.split('\n').map(l => l.trim()).filter(Boolean).slice(0, max);
}

// a one-line summary of a description, for the collapsed card
export function descriptionSummary(d: any): string {
  if (!d) return '';
  const hair = [d.hair?.style, d.hair?.colour].filter(Boolean).join(', ');
  const bits = [d.role, d.age, d.build, hair && `hair: ${hair}`, d.accessory && `accessory: ${d.accessory}`].filter(Boolean);
  return bits.join(' · ');
}

// the approval body: the owner must choose library or this episode only (no default)
export function approveBody(assetId: number, keep: 'library' | 'episode', newVersion: boolean) {
  return {asset_id: assetId, keep, new_version: newVersion};
}

export function keepText(keep: 'library' | 'episode'): string {
  return keep === 'library'
    ? 'Save to my cast library (reusable in later episodes at no cost)'
    : 'Use in this episode only';
}

export function headNote(hf: any): string {
  return hf && hf.auto === false ? (hf.note || HEAD_NOTE) : '';
}
