// The episode's "POV" hook banner, in words (episode page, next to "Dialogue on screen"). Pure; node --test.
export function hookNote(ep: any, locked: boolean): string {
  if (locked) return 'Locked while rendering';
  if (!ep.hook_banner) return ep.source === 'audio' ? 'Off (audio episodes start without a banner); applies to the stills and the next render'
    : 'Off; applies to the stills and the next render';
  return `Shows "${ep.hook_text || 'the script\'s hook'}" at the top; applies to the stills and the next render`;
}
