// "Rebuild scenes from audio" (Audio tab, after the script was approved): the confirmation the owner reads, from the
// server's preview (what is discarded, what is kept, what it costs). Pure; tested with node --test.
export function rebuildCost(preview: any, mode: 'writer' | 'simple'): string {
  if (mode === 'simple') return 'free (simple split)';
  const w = preview?.cost?.writer || {};
  if (w.provider === 'none') return `free: ${w.note}`;
  return `about $${Number(w.usd || 0).toFixed(4)} (${w.provider}${w.note ? `; ${w.note}` : ''})`;
}

export function rebuildConfirmText(preview: any, mode: 'writer' | 'simple'): string {
  const d = preview?.discards || {};
  const discards = [`${d.storyboard_scenes ?? 0} storyboard scene(s)` + (d.stills_unlinked ? ` and their stills (${d.stills_unlinked}; the images stay in storage)` : ''),
    d.script_approval, d.scene_edits].filter(Boolean);
  return [`Rebuild the scenes from the audio with the ${mode === 'writer' ? 'AI writer' : 'simple split'}: ${rebuildCost(preview, mode)}.`,
    '', 'This discards:', ...discards.map((x: string) => `- ${x}`),
    '', 'This keeps:', ...(preview?.keeps || []).map((x: string) => `- ${x}`),
    '', `Afterwards: ${preview?.after || ''}`].join('\n');
}
