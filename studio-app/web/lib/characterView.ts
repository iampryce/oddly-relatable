// Characters page view helpers (owner request 2026-11-21): collapsed cards, grouping, search, hidden extra poses.
// The body pose's rig check (the pose the acting rig builds the body from), for the collapsed card.
export function rigStatus(c: any): {label: string; tone: string} {
  if (c.locked) return {label: 'rig: repository art', tone: ''};
  const approved = c.assets.filter((a: any) => a.kind === 'pose' && a.status === 'approved');
  if (!approved.length) return {label: 'rig: no approved pose', tone: 'warn'};
  const body = approved.find((a: any) => a.rig_check?.role === 'body');
  if (!body) return {label: 'rig: not checked', tone: 'warn'};
  return body.rig_check.ok ? {label: 'rig: OK', tone: 'good'} : {label: 'rig: failed', tone: 'bad'};
}

// Poses shown by default: approved ones, and poses awaiting review for an expression with no approved pose yet.
export function visiblePoses(assets: any[], all: boolean): any[] {
  const poses = assets.filter((a: any) => a.kind === 'pose');
  if (all) return poses;
  const approvedExp = new Set(poses.filter((p: any) => p.status === 'approved').map((p: any) => p.expression));
  return poses.filter((p: any) => p.status === 'approved' || (p.status === 'review' && !approvedExp.has(p.expression)));
}

export type Usage = Record<string, {id: number; title: string; stage: string; live: boolean}[]>;

// Recurring cast / this story's characters / everyone else / archived, filtered by a search over name and key.
export function groupCharacters(chars: any[], usage: Usage, archived: number[], storyId: number | null, search: string) {
  const q = search.trim().toLowerCase();
  const hit = (c: any) => !q || c.name.toLowerCase().includes(q) || c.key.toLowerCase().includes(q);
  const inStory = (c: any) => storyId != null && (c.episode_id === storyId || (usage[c.key] || []).some(e => e.id === storyId));
  const arch = new Set(archived);
  const out = {recurring: [] as any[], story: [] as any[], others: [] as any[], archived: [] as any[]};
  for (const c of chars.filter(hit)) {
    if (arch.has(c.id)) out.archived.push(c);
    else if (inStory(c)) out.story.push(c);
    else if (c.scope === 'recurring') out.recurring.push(c);
    else out.others.push(c);
  }
  return out;
}

// A character can be archived or deleted only when no live episode uses it (and it is not locked repository art).
export function removable(c: any, usage: Usage): boolean {
  return !c.locked && !(usage[c.key] || []).some(e => e.live);
}
