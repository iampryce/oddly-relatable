// The New short wizard (API: narrated_short.py): pure helpers for the page (node --test). The API decides everything
// (prices, gates, what can start); these only shape the words, the step list and the confirmation questions.

export type StepKey = 'choose' | 'ideas' | 'script' | 'scenes' | 'voice' | 'pictures' | 'motion' | 'assembly' | 'publish';
export type StepState = 'done' | 'waiting' | 'todo' | 'busy';

export const STEPS: {key: StepKey; n: number; title: string}[] = [
  {key: 'choose', n: 1, title: 'Choose'}, {key: 'ideas', n: 2, title: 'Ideas'}, {key: 'script', n: 3, title: 'Script'},
  {key: 'scenes', n: 4, title: 'Scenes'}, {key: 'voice', n: 5, title: 'Voice'}, {key: 'pictures', n: 6, title: 'Pictures'},
  {key: 'motion', n: 7, title: 'Motion'}, {key: 'assembly', n: 8, title: 'Timing and assembly'},
  {key: 'publish', n: 9, title: 'Publish pack'},
];

// Plain-English help per step (what it does, what it costs, what you decide).
export const HELP: Record<StepKey, string> = {
  choose: 'Pick the niche, one or two of your house characters (their approved master is the only source of their look), '
    + 'the frame (9:16 for Shorts) and how long the video should be. Free.',
  ideas: 'GPT writes 10 ideas with a hook line, a twist and why each one is easy to animate, or you type your own. '
    + 'Ideas that present facts as true are marked "check before publishing". The price is shown on the button.',
  script: 'GPT writes the narration on the story template: a hook first, a short setup, 2-4 bigger and bigger beats, '
    + 'a "But..." pivot and the payoff as the last words (about 3.7 words a second). Edit it freely, then approve it.',
  scenes: 'The approved script is split into one scene per sentence (3-6 seconds each). For each scene there is a picture '
    + 'prompt (your characters as reference images, a clean 3D-style background, bright colours) and an animation '
    + 'prompt (one simple action). GPT writes them, or use the free templates. You can edit both.',
  voice: 'Gemini reads the script in the voice and style you choose (free on the free tier, which lets Google use the text; '
    + 'or paid on a paid-tier key), or upload your own recording. The words are then timed so every scene starts on its '
    + 'first word. Listen, then approve a take.',
  pictures: 'One picture per scene from Nano Banana, with your characters\' approved masters as the reference images. '
    + 'Each picture shows its price first. Approve each one, or redo it with the chat under it.',
  motion: 'Each approved picture becomes a short clip with Wan 2.2 on a rented GPU: one session for all the scenes, '
    + 'turned off when done. The estimate (start-up plus about 2.5 minutes per clip) is shown first.',
  assembly: 'Free, on the studio server: every scene runs exactly from its sentence\'s first word to the next scene\'s '
    + 'first word. Clips are cut, held or slowed a little (never sped up). Music is levelled 6 dB under the voice; '
    + 'captions are on by default. Watch the result and approve it.',
  publish: 'GPT writes a thumbnail idea (your character plus the one visual idea, 3-5 words), 5 titles, a description '
    + 'and hashtags; Nano Banana makes the thumbnail. Nothing is uploaded from here.',
};

export const NICHE_HINT: Record<string, string> = {
  what_if: '"What if every lie made you smaller?"', money: 'Saving, spending and money traps',
  psychology: 'Habits, rules of thumb, self-improvement', history: 'True stories from the past (check the facts)',
  weird_facts: 'Strange but true (check the facts)', custom: 'Your own niche',
};

// $0.04, $1.20, and small text-model prices with up to four decimals ($0.0123)
function money(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(x)) return 'cost unknown';
  if (x >= 1 || x === 0) return `$${x.toFixed(2)}`;
  let s = x.toFixed(4);
  while (s.endsWith('0') && s.split('.')[1].length > 2) s = s.slice(0, -1);
  return `$${s}`;
}
export const usd = money;

// 30 -> "30 s", 90 -> "1 min 30 s", 600 -> "10 min"
export function lengthLabel(s: number): string {
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60), r = s % 60;
  return r ? `${m} min ${r} s` : `${m} min`;
}

export function targetWords(seconds: number, wps = 3.7): number {
  return Math.round(seconds * wps);
}

export function wordCount(text: string): number {
  return (text || '').trim().split(/\s+/).filter(Boolean).length;
}

// "112 words, about 30 s (target 111)"
export function scriptLength(text: string, targetSeconds: number, wps = 3.7): string {
  const w = wordCount(text);
  return `${w} words, about ${Math.round(w / wps)} s (target about ${targetWords(targetSeconds, wps)} words)`;
}

export function approvedScript(v: any): any | null {
  const a = v?.script?.approved;
  return a ? (v.script.versions || []).find((x: any) => x.v === a) || null : null;
}

export function latestScript(v: any): any | null {
  const vs = v?.script?.versions || [];
  return vs.length ? vs[vs.length - 1] : null;
}

// where each step stands, from the wizard's view (the API's facts only)
export function stepStates(v: any): Record<StepKey, StepState> {
  const scenes: any[] = v?.scenes?.items || [];
  const takes: any[] = v?.voice?.takes || [];
  const cuts: any[] = v?.final?.cuts || [];
  const approvedTake = takes.find(t => t.id === v?.voice?.approved);
  const pub = v?.publish || {};
  const st = (done: boolean, waiting: boolean, busy = false): StepState => busy ? 'busy' : done ? 'done' : waiting ? 'waiting' : 'todo';
  const jobs: any[] = v?.jobs || [];
  const running = (kind: string) => jobs.some(j => j.kind === kind && (j.status === 'queued' || j.status === 'running'));
  return {
    choose: st((v?.choose?.characters || []).length > 0, false),
    ideas: st(!!v?.idea, !!(v?.ideas?.items || []).length),
    script: st(!!approvedScript(v), (v?.script?.versions || []).length > 0),
    scenes: st(scenes.length > 0 && scenes.every(s => s.picture_prompt), scenes.length > 0),
    voice: st(!!approvedTake && approvedTake.fits, takes.some(t => t.fits), running('short_voice')),
    pictures: st(scenes.length > 0 && scenes.every(s => s.picture_approved), scenes.some(s => (s.pictures || []).length),
      running('short_picture')),
    motion: st(scenes.length > 0 && scenes.every(s => (s.clips || []).length), scenes.some(s => (s.clips || []).length),
      running('short_motion')),
    assembly: st(!!v?.final?.approved, cuts.length > 0, running('short_assembly')),
    publish: st(!!(pub.titles || []).length && !!pub.thumbnail_approved, !!(pub.titles || []).length || !!(pub.thumbnails || []).length,
      running('short_thumbnail')),
  };
}

export const STATE_TEXT: Record<StepState, {text: string; tone: string}> = {
  done: {text: 'Done', tone: 'good'}, waiting: {text: 'Waiting for you', tone: 'warn'},
  todo: {text: 'To do', tone: ''}, busy: {text: 'Working', tone: 'busy'},
};

// the question asked before a paid start; the button then sends the same amount as confirm_usd
export function paidConfirm(what: string, est: any): string {
  if (!est || est.usd_max == null) return `${what}: the cost is unknown, so it cannot start.`;
  return `${what}: ${est.label || `at most ${money(est.usd_max)}`}. Start now? (paid; not retried by itself)`;
}

// "Write 10 ideas · up to $0.0123"
export function paidLabel(what: string, est: any, busy = false): string {
  if (busy) return 'Working…';
  if (!est) return what;
  if (est.usd_max == null) return `${what} (cost unknown)`;
  return est.usd_max === 0 ? `${what} · free` : `${what} · up to ${money(est.usd_max)}`;
}

// the voice step's price line, with the free-tier warning when it applies
export function voiceCostText(est: any): string {
  if (!est) return 'Approve the script first.';
  if (est.blocked) return est.blocked;
  return est.label + (est.warning ? ` ${est.warning}` : '');
}

// a scene's timing line: "0.00-3.24 s (81 frames)" once timed, else the estimate from the words
export function sceneTime(s: any): string {
  if (s?.timed) return `${s.timed.start.toFixed(2)}-${(s.timed.start + s.timed.seconds).toFixed(2)} s (${s.timed.frames} frames)`;
  return `about ${Number(s?.estimated_seconds || 0).toFixed(1)} s (estimated from the words)`;
}

export function chosenPicture(s: any): any | null {
  return (s?.pictures || []).find((p: any) => p.asset_id === s.picture_chosen) || null;
}

export function chosenClip(s: any): any | null {
  return (s?.clips || []).find((c: any) => c.asset_id === s.clip_chosen) || null;
}

// "8 of 9 pictures approved"
export function picturesSummary(scenes: any[]): string {
  const n = (scenes || []).length;
  const ok = (scenes || []).filter(s => s.picture_approved).length;
  return `${ok} of ${n} picture${n === 1 ? '' : 's'} approved`;
}

// captions on/off in words
export function captionsText(on: boolean): string {
  return on ? 'Captions on: bold, high contrast, upper middle, a few words at a time'
    : 'Captions off';
}
