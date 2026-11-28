// Characters page view helpers (owner request 2026-11-21): collapsed cards, grouping, search, hidden extra poses.

// A studio pose in the default dimension (standing, front; every pose from before the pose dimension). Imported assets
// and seated or turned poses are shown in the Imported panel and decided there, one by one.
export function isStandardPose(a: any): boolean {
  return a.kind === 'pose' && !a.imported && [['posture', 'standing'], ['body_turn', 'front'], ['view', 'front'], ['framing', 'full']]
    .every(([k, v]) => a[k] == null || a[k] === v);
}

// The body pose's rig check (the pose the acting rig builds the body from), for the collapsed card.
export function rigStatus(c: any): {label: string; tone: string} {
  if (c.locked) return {label: 'rig: repository art', tone: ''};
  const approved = c.assets.filter((a: any) => isStandardPose(a) && a.status === 'approved');
  if (!approved.length) return {label: 'rig: no approved pose', tone: 'warn'};
  if (c.rig_check_job) return {label: `rig: check ${c.rig_check_job.status}`, tone: 'warn'};
  const body = approved.find((a: any) => a.rig_check?.role === 'body');
  if (!body) return {label: 'rig: not checked', tone: 'warn'};
  return body.rig_check.ok ? {label: 'rig: OK', tone: 'good'} : {label: 'rig: failed', tone: 'bad'};
}

// Poses shown by default: approved ones and every pose awaiting review, including candidates for an expression that
// already has an approved pose (e.g. body pose candidates). Superseded, rejected and rig-failed poses stay hidden
// until "show all poses".
export function visiblePoses(assets: any[], all: boolean): any[] {
  const poses = assets.filter(isStandardPose);
  if (all) return poses;
  return poses.filter((p: any) => p.status === 'approved' || p.status === 'review');
}

// A pose awaiting review for an expression that already has an approved pose: approving it replaces that pose.
export function isCandidate(p: any, assets: any[]): boolean {
  return isStandardPose(p) && p.status === 'review' &&
    assets.some((a: any) => isStandardPose(a) && a.status === 'approved' && a.expression === p.expression);
}

// What a pose card says about its rig check. Approved poses: the result, or the job when one is queued or running,
// or "not checked yet". Candidates awaiting review: their own check (made when they were generated), if any.
export function poseRigText(p: any, job: {id: number; status: string} | null): {text: string; tone: string} | null {
  const r = p.rig_check;
  if (r) {
    if (r.role === 'body') {
      if (r.ok === true) return {text: 'Rig check: OK (body pose: body and face)', tone: 'muted'};
      if (r.ok === false) return {text: `Rig check failed (body pose): ${r.message}`, tone: 'alert bad'};
      return {text: `Rig check: ${r.message}`, tone: 'muted'};
    }
    if (r.ok === true) return {text: 'Head-only pose: face OK (no body check; never blocks production)', tone: 'muted'};
    if (r.ok === false) return {text: 'Head-only pose: face not rigged, the neutral face is used instead (no body check; never blocks production)', tone: 'muted'};
    return {text: `Head-only pose: ${r.message}`, tone: 'muted'};
  }
  if (p.status !== 'approved') return null;
  if (job?.status === 'queued') return {text: `Rig check: queued, waiting for the worker (job ${job.id})`, tone: 'muted'};
  if (job?.status === 'running') return {text: `Rig check: running (job ${job.id})`, tone: 'muted'};
  return {text: 'Rig check: not checked yet', tone: 'warn'};
}

// The "Run rig check" button: some approved pose has no result and no check is queued or running.
export function needsRigCheck(c: any): boolean {
  if (c.locked || c.rig_check_job) return false;
  return c.assets.some((a: any) => isStandardPose(a) && a.status === 'approved' && !a.rig_check);
}

// A job the page started and follows: queued, running (with progress), then the result or the error.
export function jobText(j: any): string {
  if (!j) return '';
  if (j.status === 'queued') return `Queued job ${j.id}…`;
  if (j.status === 'running') {
    const p = j.progress || {};
    return `Running job ${j.id}…${p.total ? ` (${p.done || 0} of ${p.total} done)` : ''}`;
  }
  if (j.status === 'failed') return `Job ${j.id} failed: ${j.error || 'no reason given'}`;
  if (j.status === 'cancelled') return `Job ${j.id} was cancelled`;
  const r = j.result || {};
  if (j.kind === 'body_candidates') {
    const passed = (r.passed || []).length, failed = (r.failed || []).length;
    return `${passed + failed} done: ${passed} passed, ${failed} failed the rig check` + (passed ? ' (shown below as candidates)' : '');
  }
  if (j.kind === 'rig_check') return `Rig check done: ${r.checked ?? 0} pose(s) checked, ${r.failed ?? 0} failed`;
  return `Job ${j.id} done`;
}

export function jobFinished(j: any): boolean {
  return !!j && !['queued', 'running'].includes(j.status);
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

// The image cost shown before any generation (the image provider's range per image).
export function imageCost(images: number): string {
  return `${images} image(s), about $${(images * 0.05).toFixed(2)}-$${(images * 0.2).toFixed(2)}`;
}
