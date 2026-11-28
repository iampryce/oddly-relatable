// The three studios in one dashboard (docs/studios.md, owner decision 2026-11-28). Only Stick Man Studio is active; the
// other two stay locked until its four unlock gates pass. This is the whole model for now: no persistence, no routing.
export type StudioId = 'stick-man' | 'cinematic' | 'kids-stories';

export type Studio = {id: StudioId; label: string; locked: boolean};

export const STUDIOS: readonly Studio[] = [
  {id: 'stick-man', label: 'Stick Man Studio', locked: false},
  {id: 'cinematic', label: 'Cinematic Studio', locked: true},
  {id: 'kids-stories', label: 'Kids Stories Studio', locked: true},
];

export const ACTIVE_STUDIO: StudioId = 'stick-man';

export const LOCKED_NOTE = 'Locked until the Stick Man Studio unlock gates pass';

export function studioOf(id: string): Studio | undefined {
  return STUDIOS.find(s => s.id === id);
}
