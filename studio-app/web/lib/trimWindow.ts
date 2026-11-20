// The Short's window on a longer recording (audio-first Stage 1b): at most `max` seconds inside the recording.
// The server checks the same rules; this only keeps the form honest before sending.

export const round1 = (x: number) => Math.round(x * 10) / 10;

export function windowError(start: number, end: number, duration: number | null, max: number): string | null {
  if (!Number.isFinite(start) || !Number.isFinite(end)) return 'Enter a start and an end in seconds.';
  if (start < 0) return 'The window cannot start before the recording.';
  if (end <= start) return 'The window must end after it starts.';
  if (end - start > max + 0.05) return `A Short's window is at most ${max} s (this one is ${round1(end - start)} s).`;
  if (duration != null && end > duration + 0.05) return `The window ends after the recording (${round1(duration)} s).`;
  return null;
}

// A window starting at `start`, as long as allowed: `max` seconds, or up to the end of the recording.
export function windowFrom(start: number, duration: number | null, max: number): {start: number; end: number} {
  const total = duration ?? start + max;
  const s = Math.max(0, Math.min(start, Math.max(0, total - Math.min(max, total))));
  return {start: round1(s), end: round1(Math.min(total, s + max))};
}
