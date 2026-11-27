// The episode page's Characters (speaker_cast.py): the choice per speaker label as one select value, and the body sent.

export type Proposal = {kind: 'library' | 'existing' | 'new'; library_id?: string; character_key?: string; name: string};
export type SpeakerRow = {label: string; lines: number; proposal: Proposal};

export function choiceValue(p: Proposal): string {
  if (p.kind === 'library') return `library:${p.library_id}`;
  if (p.kind === 'existing') return `existing:${p.character_key}`;
  return 'new';
}

export function choicesBody(rows: SpeakerRow[], picks: Record<string, string>) {
  return rows.map(r => {
    const v = picks[r.label] ?? choiceValue(r.proposal);
    if (v.startsWith('library:')) return {label: r.label, kind: 'library' as const, library_id: v.slice(8)};
    if (v.startsWith('existing:')) return {label: r.label, kind: 'existing' as const, character_key: v.slice(9)};
    return {label: r.label, kind: 'new' as const, name: r.label};
  });
}
