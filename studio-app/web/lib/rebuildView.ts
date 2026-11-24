// "Rebuild scenes from audio" (Audio tab, after the script was approved): the confirmation the owner reads, from the
// server's preview (what is discarded, what is kept, what it costs). Pure; tested with node --test.
export function rebuildCost(preview: any, mode: 'writer' | 'simple'): string {
  if (mode === 'simple') return 'free (simple split)';
  const w = preview?.cost?.writer || {};
  if (w.provider === 'none') return `free: ${w.note}`;
  return `about $${Number(w.usd || 0).toFixed(4)} (${w.provider}${w.note ? `; ${w.note}` : ''})`;
}

// The reaction beats and shot lists a rebuild would discard ('' when there are none): asked as a second, separate
// confirmation, and the server refuses without it (owner request 2026-11-24).
export function sheetLoss(preview: any): string {
  const b = Number(preview?.discards?.reaction_beats || 0), s = Number(preview?.discards?.shot_lists || 0);
  if (!b && !s) return '';
  const what = [b ? `${b} reaction beat(s)` : '', s ? `${s} shot list(s)` : ''].filter(Boolean).join(' and ');
  return `The storyboard has ${what}. Rebuilding the scenes discards them, and they cannot be restored. Discard them and rebuild?`;
}

export function rebuildConfirmText(preview: any, mode: 'writer' | 'simple'): string {
  const d = preview?.discards || {};
  const sheet = [d.reaction_beats ? `${d.reaction_beats} reaction beat(s)` : '', d.shot_lists ? `${d.shot_lists} shot list(s)` : ''].filter(Boolean).join(' and ');
  const discards = [`${d.storyboard_scenes ?? 0} storyboard scene(s)` + (d.stills_unlinked ? ` and their stills (${d.stills_unlinked}; the images stay in storage)` : ''),
    sheet ? `${sheet} on the storyboard` : '', d.script_approval, d.scene_edits].filter(Boolean);
  return [`Rebuild the scenes from the audio with the ${mode === 'writer' ? 'AI writer' : 'simple split'}: ${rebuildCost(preview, mode)}.`,
    '', 'This discards:', ...discards.map((x: string) => `- ${x}`),
    '', 'This keeps:', ...(preview?.keeps || []).map((x: string) => `- ${x}`),
    '', `Afterwards: ${preview?.after || ''}`].join('\n');
}
