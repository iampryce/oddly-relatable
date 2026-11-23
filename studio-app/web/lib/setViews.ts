// Set views (feat/set-views): the words the Set panel uses for views. Pure; node --test.
export const VIEW_LABEL: Record<string, string> = {
  wide: 'wide (everyone)', speaker: 'speaker (from the audience\'s side)',
  audience: 'audience (the listeners, from the speaker\'s side)', 'two-shot': 'two-shot (the speaker and the nearest listener, side-on)',
};

export function viewStatusText(v: {status: string; seats?: number; seats_needed?: number}): string {
  if (v.status === 'missing') return 'not made: shots that want it use the wide view';
  const seats = v.seats_needed ? ` · ${v.seats ?? 0} seat(s) for ${v.seats_needed}` : '';
  return `${v.status}${seats}`;
}

// The view plan in words: "Scene 1, L1 (close): speaker view".
export function planLine(r: {scene: number; line: string | number; shot: string; view: string; note?: string}): string {
  return `Scene ${r.scene}, ${r.line} (${r.shot}): ${r.view} view${r.note ? ` (${r.note})` : ''}`;
}
