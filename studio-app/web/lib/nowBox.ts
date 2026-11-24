// The Now box at the top of an episode (2026-11-23): the single next action and its cost, from the workspace's `next`.
// Its button never starts anything paid by itself: "run_talking" hands the lines to the Talking shots section's own Run
// flow, whose confirm shows the total first; "open" opens the step, whose own button and confirm do the rest.
// Pure; node --test.
export type Now = {title: string; text: string; cost: string; tone: '' | 'muted'; button: null | {action: 'open' | 'run_talking'; label: string; section: string}};

export function nowBox(next: any): Now | null {
  if (!next) return null;
  const button = next.button ? {...next.button, section: next.section} : null;
  return {title: next.title, text: next.text, cost: next.cost_text || '', tone: next.kind === 'working' ? 'muted' : '', button};
}
