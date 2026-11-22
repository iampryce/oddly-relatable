// Episode sets (feat/episode-sets): the words the set pages use for rooms, a set's reuse state and the picker groups.
// Pure functions, tested with node --test.

export function roomTitle(r: any, i: number): string {
  return r.room ? `Room ${i + 1}: ${r.room}` : (i === 0 ? 'The set' : `Room ${i + 1}`);
}

// Where a set comes from, as the picker shows it.
export function reuseLabel(o: any): string {
  if (o.source === 'repository') return 'studio plate (kept for reuse)';
  if (o.own) return o.kept ? 'made for this episode · kept for future episodes' : 'made for this episode';
  if (o.kept) return 'kept for reuse';
  return 'already used by this episode';
}

// This episode's own sets first, then the kept ones.
export function pickerGroups(options: any[]): {own: any[]; kept: any[]} {
  return {own: options.filter(o => o.own || (!o.kept && o.source !== 'repository')), kept: options.filter(o => !o.own && (o.kept || o.source === 'repository'))};
}

// The extra cost of the set notes in the notes estimate (shown before an upload).
export function setNotesCost(est: any): string {
  if (!est?.set_notes?.usd && est?.set_notes?.usd !== 0) return '';
  return `includes set notes: about $${est.set_notes.usd.toFixed(3)} (${est.set_notes.frames} frames, ${est.set_notes.rooms_assumed} rooms assumed)`;
}
