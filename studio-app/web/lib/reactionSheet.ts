// The reaction sheet and the shot list on the storyboard (2026-11-24): the choices the editing rows offer and a quick
// check before saving (the API checks again and has the last word: approved expressions, the scene's span, the cast).
// Pure; node --test.
export const MOVES = ['none', 'lift', 'flinch', 'dip', 'tilt', 'turn_to', 'lean_in', 'chin_up', 'glance'] as const;
export const STRENGTHS = ['light', 'medium', 'strong'] as const;
export const SHOT_TYPES = [['wide', 'Wide'], ['medium', 'Medium'], ['mcu', 'Medium close-up'], ['cu', 'Close-up'],
  ['ots', 'Over the shoulder']] as const;

export type Word = {word: string; start: number; end: number};
export type Beat = {word: number; word_text?: string; t?: number; expression: string; move: string; strength: string;
  reason: string; estimated?: boolean};
export type Shot = {start: number; end: number; type: string; camera: string; on_screen: string[]; over_shoulder_of?: string};

// the storyboard line's words, from the recording's transcript (by the line's id); only words with text
export function wordsOf(transcriptLines: any[] | undefined, lineId: string | undefined): Word[] {
  const ln = (transcriptLines || []).find(x => x.id === lineId);
  return (ln?.words || []).filter((w: any) => String(w.word || '').trim());
}

export function wordLabel(w: Word, i: number): string {
  return `${i + 1}. ${w.word} (${w.start.toFixed(2)} s)`;
}

// a beat's time: set by hand, else its word's start
export function beatTime(b: Beat, words: Word[]): number | null {
  if (typeof b.t === 'number' && Number.isFinite(b.t)) return b.t;
  return words[b.word] ? words[b.word].start : null;
}

export function newBeat(words: Word[], after?: Beat): Beat {
  const w = after ? Math.min(words.length - 1, after.word + 1) : 0;
  return {word: Math.max(0, w), expression: 'neutral', move: 'none', strength: 'medium', reason: ''};
}

// what is sent: the time only when it was set by hand (else the API takes the word's start)
export function beatForServer(b: Beat): Beat {
  const out: Beat = {word: b.word, expression: b.expression, move: b.move, strength: b.strength, reason: b.reason};
  if (typeof b.t === 'number' && Number.isFinite(b.t)) out.t = b.t;
  if (b.estimated) out.estimated = true;
  return out;
}

export function newShot(prev: Shot | undefined, lo: number, cast: string[]): Shot {
  const start = prev ? prev.end : lo;
  return {start: +start.toFixed(2), end: +(start + 1).toFixed(2), type: 'mcu', camera: '', on_screen: cast.slice(0, 1)};
}

// the first problem the API would also refuse, for a message before saving ('' when none)
export function shotsProblem(shots: Shot[]): string {
  for (let i = 0; i < shots.length; i++) {
    const s = shots[i];
    if (!(s.end > s.start)) return `shot ${i + 1}: it must end after it starts`;
    if (!s.on_screen.length) return `shot ${i + 1}: say who is on screen`;
    if (s.type === 'ots' && !s.over_shoulder_of) return `shot ${i + 1}: an over-the-shoulder shot needs whose shoulder`;
    if (i && s.start < shots[i - 1].end - 1e-6) return `shot ${i + 1}: it starts before shot ${i} ends`;
  }
  return '';
}

// the span of scene `index` on the recording (as the API computes it): previous scene's last line end -> next scene's
// first line start
export function sceneSpan(scenes: any[], index: number, duration?: number): [number, number] {
  const lines = (s: any) => (s?.lines || []).filter((x: any) => typeof x.start === 'number');
  const prev = scenes.slice(0, index).flatMap(s => lines(s).map((x: any) => x.end));
  const next = scenes.slice(index + 1).flatMap(s => lines(s).map((x: any) => x.start));
  const own = lines(scenes[index]);
  const lo = prev.length ? Math.max(...prev) : 0;
  const hi = next.length ? Math.min(...next) : duration || (own.length ? Math.max(...own.map((x: any) => x.end)) + 4 : lo + 4);
  return [lo, hi];
}
