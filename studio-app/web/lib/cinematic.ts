// Cinematic mode (API: cinematic.py): pure helpers for the new-episode cards and the cinematic steps page
// (node --test). The API checks every price (confirm_usd), the scripture guard and every approval; these only shape
// what the page shows and sends.

export type Mode = 'cartoon' | 'cinematic';
export const MODES: {id: Mode; title: string; text: string}[] = [
  {id: 'cartoon', title: 'Cartoon', text: 'Stick figures and cartoon styles from your video and recording (today’s flow).'},
  {id: 'cinematic', title: 'Cinematic — realistic actors, real acting',
    text: 'Invented human actors, lip-synced dialogue, film shots and effects. From an idea, a Bible passage or your script.'},
];

export type Source = 'idea' | 'bible' | 'script';
export const SOURCES: {id: Source; label: string}[] = [
  {id: 'idea', label: 'An idea or logline'}, {id: 'bible', label: 'A Bible passage'}, {id: 'script', label: 'My own script'},
];
export const TRANSLATIONS = [
  {id: 'KJV', label: 'King James Version (public domain)'}, {id: 'WEB', label: 'World English Bible (public domain)'},
  {id: 'ASV', label: 'American Standard Version (public domain)'},
];

export const DISCLOSURE = "Contains realistic AI-generated people — tick 'Altered or synthetic content' when uploading";

export function money(x: number | null | undefined, digits = 2): string {
  if (x == null || !Number.isFinite(x)) return 'cost unknown';
  return `$${x.toFixed(digits)}`;
}

// the body of POST /cinematic-episodes (only the fields of the chosen source)
export function storyBody(src: Source, f: {idea?: string; passage?: string; translation?: string; text?: string; angle?: string;
  script?: string; confirm?: boolean}): Record<string, unknown> {
  if (src === 'idea') return {source: src, idea: (f.idea || '').trim()};
  if (src === 'script') return {source: src, script: (f.script || '').trim()};
  return {source: src, passage: (f.passage || '').trim(), translation: f.translation || 'KJV', scripture_text: (f.text || '').trim(),
    angle: (f.angle || '').trim(), confirm_public_domain: !!f.confirm};
}

export function storyReady(src: Source, f: {idea?: string; passage?: string; script?: string}): boolean {
  if (src === 'idea') return (f.idea || '').trim().length >= 10;
  if (src === 'script') return (f.script || '').trim().length >= 20;
  return /\d/.test(f.passage || '');
}

// what the scripture guard said, in a sentence
export function guardText(r: any): {tone: string; text: string} {
  if (!r) return {tone: 'muted', text: ''};
  if (r.status === 'refused') return {tone: 'bad', text: `Refused: ${(r.reasons || []).join('; ')}`};
  if (r.status === 'flagged') return {tone: 'warn', text: `Check: ${(r.reasons || []).join('; ')}`};
  return {tone: 'good', text: 'Public-domain text: OK'};
}

export const SIZE_LABEL: Record<string, string> = {
  'extreme wide': 'Extreme wide', wide: 'Wide', medium: 'Medium', 'medium close': 'Medium close-up', close: 'Close-up',
  'extreme close': 'Extreme close-up', 'over the shoulder': 'Over the shoulder', insert: 'Insert',
};
export const CAMERAS = ['static', 'push in', 'pull out', 'pan left', 'pan right', 'tilt up', 'tilt down', 'tracking', 'orbit',
  'crane up', 'crane down', 'handheld'];

// one line per shot for the screenplay table
export function shotLine(s: any): string {
  const who = (s.characters || []).join(', ');
  const ln = s.line ? ` — ${s.line.speaker} (${s.line.emotion}): “${s.line.text}”` : '';
  return `${SIZE_LABEL[s.size] || s.size}, ${s.camera}${who ? ` · ${who}` : ''}: ${s.action || ''}${ln}${s.vfx ? ` [VFX: ${s.vfx}]` : ''}`.trim();
}

// a shot's status for its badge
export function shotStatus(s: any): {tone: string; text: string} {
  if (s.run && (s.run.status === 'queued' || s.run.status === 'running')) return {tone: 'busy', text: 'Making…'};
  if (s.approved_render) return {tone: 'good', text: 'Shot approved'};
  if ((s.renders || []).length) return {tone: 'warn', text: 'Watch and approve the shot'};
  if (s.render_ready) return {tone: '', text: 'Ready to make'};
  if (s.approved) return {tone: '', text: s.render_blocked || 'Still approved'};
  if ((s.stills || []).length) return {tone: 'warn', text: 'Approve a still'};
  return {tone: '', text: 'No still yet'};
}

// the cinematic page's steps and whether each is done, from the view
export function progress(v: any): {key: string; title: string; done: boolean}[] {
  const shots: any[] = v?.shots || [];
  const lines: any[] = v?.lines || [];
  return [
    {key: 'story', title: 'Story', done: !!v?.story},
    {key: 'screenplay', title: 'Screenplay', done: !!v?.screenplay?.approved},
    {key: 'cast', title: 'Cast and voices', done: !!v?.cast_made && (v.cast || []).every((c: any) => c.master)},
    {key: 'locations', title: 'Locations', done: !!v?.locations_made && (v.locations || []).every((l: any) => l.approved)},
    {key: 'stills', title: 'Shot stills', done: shots.length > 0 && shots.every(s => s.approved)},
    {key: 'voices', title: 'Voices', done: lines.every(l => l.approved)},
    {key: 'shots', title: 'Motion and dialogue shots', done: shots.length > 0 && shots.every(s => s.approved_render)},
    {key: 'final', title: 'Final cut and YouTube notice', done: !!v?.approved_cut && !!v?.disclosure?.acknowledged},
  ];
}
