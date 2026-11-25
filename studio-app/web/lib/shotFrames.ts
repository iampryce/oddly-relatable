// The storyboard in the dashboard (2026-11-25): one frame per shot, its takes, the owner's approvals and the animatic.
// Pure helpers for /episodes/{id}/shot-frames; node --test. Nothing here approves anything: approvals are the owner's
// clicks only, and every action of this step is free (CPU on the server).

export type ShotSize = 'close' | 'medium' | 'wide';
export const SHOT_SIZES: ShotSize[] = ['close', 'medium', 'wide'];
// expressions the retake form offers; the renderer uses the nearest approved face of each character
export const EXPRESSIONS = ['neutral', 'happy', 'sad', 'angry', 'surprised', 'shocked', 'worried', 'serious', 'confused', 'smug', 'deadpan'];

// 75.4 -> "1:15"
export function clock(t: number | null | undefined): string {
  const s = Math.max(0, Math.floor(Number(t) || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export function timeRange(shot: {t0: number; t1: number}): string {
  return `${clock(shot.t0)}–${clock(shot.t1)}`;
}

// "Ralph, Sidney" (names from the episode's characters), or "the room" when nobody is on screen
export function peopleText(people: string[], names: Record<string, string> = {}): string {
  return people?.length ? people.map(k => names[k] || k).join(', ') : 'the room';
}

export function shotStatus(shot: any): {tone: 'good' | ''; text: 'approved' | 'draft'} {
  return shot?.approved ? {tone: 'good', text: 'approved'} : {tone: '', text: 'draft'};
}

// the characters the retake form may put in a shot: those on the chosen side, in seat order
export function sideMembers(plan: any, side: string): string[] {
  return (plan?.sides || {})[side] || [];
}

export type RetakeForm = {shot: ShotSize; side: string; people: string[]; emotions: Record<string, string>};

export function retakeForm(shot: any): RetakeForm {
  return {shot: shot.shot, side: shot.side, people: [...(shot.people || [])], emotions: {...(shot.emotions || {})}};
}

// What the retake sends: only what changed (an untouched form asks for the same shot drawn again). Expressions are
// sent for people in the shot only; "" (no choice) is left out. A close shot of several people is refused here as by
// the API (it shows one person).
export function retakeBody(shot: any, f: RetakeForm): {body: Record<string, unknown>; error?: string} {
  const body: Record<string, unknown> = {};
  if (f.shot !== shot.shot) body.shot = f.shot;
  if (f.side !== shot.side) body.side = f.side;
  const same = f.people.length === (shot.people || []).length && f.people.every((p, i) => p === shot.people[i]);
  if (!same || f.side !== shot.side) body.people = f.people;
  const faces: Record<string, string> = {};
  for (const k of f.people) if (f.emotions[k] && f.emotions[k] !== (shot.emotions || {})[k]) faces[k] = f.emotions[k];
  if (Object.keys(faces).length) body.emotions = faces;
  if (f.shot === 'close' && f.people.length > 1) return {body, error: 'A close shot shows one person: choose medium or wide, or one person.'};
  return {body};
}

// The jobs of this step that are queued or running (from the GET's `jobs`), and the one for a given shot's retake.
export function activeJobs(v: any, kind?: string): any[] {
  return (v?.jobs || []).filter((j: any) => (j.status === 'queued' || j.status === 'running') && (!kind || j.kind === kind));
}

export function retakeRunning(v: any, index: number): boolean {
  return activeJobs(v, 'shot_frame_retake').some(j => j.payload?.index === index);
}

// "Drawing frames: 3 of 12" while the frames are being made
export function makingText(v: any): string {
  const j = activeJobs(v, 'shot_frames')[0];
  if (!j) return '';
  const p = j.progress;
  return j.status === 'queued' ? 'Queued…' : p?.total ? `Drawing frames: ${p.done} of ${p.total}` : 'Drawing frames…';
}

// the last failure of this step's jobs, when it is newer than the last success of the same kind
export function lastFailure(v: any): string {
  const jobs = [...(v?.jobs || [])].sort((a: any, b: any) => b.id - a.id);
  for (const j of jobs) {
    if (j.status === 'failed') return `${j.kind === 'shot_animatic' ? 'Animatic' : j.kind === 'shot_frame_retake' ? `Retake of shot ${j.payload?.index}` : 'Shot frames'}: ${j.error || 'failed'}`;
    if (j.status === 'succeeded') return '';
  }
  return '';
}

export function summary(v: any): string {
  const n = v?.shots?.length || 0;
  const ok = (v?.shots || []).filter((s: any) => s.approved).length;
  return `${n} ${n === 1 ? 'shot' : 'shots'} · ${ok} approved`;
}
