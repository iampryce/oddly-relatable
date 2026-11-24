// Production page: "Recent jobs" shows the latest 10; "Show more" shows up to 40.
export function recentRows<T>(jobs: T[], more: boolean): T[] {
  return jobs.slice(0, more ? 40 : 10);
}

// Quiet by default (owner decision 2026-11-23). Nothing is cleared or deleted: these only decide what the lists show.
//   - a failed job older than a day is hidden behind a count, unless a live episode still needs it (keep_reason);
//   - succeeded prepare and key jobs (routine, free, many) are not listed in Recent jobs.
export const QUIET_KINDS = ['shot_prepare', 'shot_key', 'scene_prepare', 'audio_media_prepare'];
export const FAILED_SHOWN_HOURS = 24;

type J = {kind: string; status: string; keep_reason?: string | null; finished_at?: string | null; started_at?: string | null; created_at?: string | null};

export function isOldFailure(j: J, now: number = Date.now()): boolean {
  if (j.status !== 'failed' || j.keep_reason) return false;
  const at = Date.parse(j.finished_at || j.started_at || j.created_at || '');
  return Number.isFinite(at) && now - at > FAILED_SHOWN_HOURS * 3600 * 1000;
}

export function quietJobs<T extends J>(jobs: T[], showOld: boolean, now: number = Date.now()):
    {failed: T[]; hiddenFailed: number; recent: T[]; hiddenRoutine: number} {
  const allFailed = jobs.filter(j => j.status === 'failed');
  const old = allFailed.filter(j => isOldFailure(j, now));
  const routine = jobs.filter(j => j.status === 'succeeded' && QUIET_KINDS.includes(j.kind));
  return {
    failed: showOld ? allFailed : allFailed.filter(j => !isOldFailure(j, now)),
    hiddenFailed: showOld ? 0 : old.length,
    recent: jobs.filter(j => !(j.status === 'succeeded' && QUIET_KINDS.includes(j.kind)) && (showOld || !isOldFailure(j, now))),
    hiddenRoutine: routine.length,
  };
}
