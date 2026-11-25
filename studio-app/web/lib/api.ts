// Client for the studio API (same origin; the session is an httpOnly cookie the browser sends automatically).
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T = any>(path: string, opts: {method?: string; body?: unknown} = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: opts.method || (opts.body !== undefined ? 'POST' : 'GET'),
    headers: opts.body !== undefined ? {'Content-Type': 'application/json'} : undefined,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    credentials: 'same-origin',
    cache: 'no-store',
  });
  if (res.status === 401 && typeof window !== 'undefined' && !path.startsWith('/auth/')) {
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const d = data?.detail;
    const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map((x: any) => `${(x.loc || []).slice(1).join('.')}: ${x.msg}`).join('; ') : res.statusText;
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

// Raw file upload (the audio-first episode's recording): the file is the request body, sent with its audio or video
// type. A video is only a carrier for its audio (Stage 1b); `hints` asks for the text-only video notes, and `window` is a
// Short's window (up to 3 min) chosen before the upload (so only that part of the video is analysed).
const MEDIA_EXT: Record<string, string> = {mp3: 'audio/mpeg', wav: 'audio/wav', m4a: 'audio/mp4', aac: 'audio/aac', ogg: 'audio/ogg',
  webm: 'audio/webm', flac: 'audio/flac', mp4: 'video/mp4', mov: 'video/quicktime', mkv: 'video/x-matroska', m4v: 'video/x-m4v',
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp'};
export const mediaType = (file: File) => file.type || MEDIA_EXT[(file.name.split('.').pop() || '').toLowerCase()] || 'application/octet-stream';
export const isVideoFile = (file: File | null) => !!file && mediaType(file).startsWith('video/');
export async function uploadAudio<T = any>(path: string, file: File, opts: {hints?: boolean; window?: {start: number; end: number} | null} = {}): Promise<T> {
  const type = mediaType(file);
  const q = new URLSearchParams();
  if (opts.hints && type.startsWith('video/')) q.set('hints', 'true');
  if (opts.window && type.startsWith('video/')) { q.set('start', String(opts.window.start)); q.set('end', String(opts.window.end)); }
  const url = `/api${path}${q.toString() ? `?${q}` : ''}`;
  const res = await fetch(url, {method: 'PUT', body: file, headers: {'Content-Type': type}, credentials: 'same-origin', cache: 'no-store'});
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, typeof data?.detail === 'string' ? data.detail : res.statusText);
  return data as T;
}

// Any raw file upload (a video to read the room from, the owner's own set reference): the file is the body.
export async function uploadFile<T = any>(path: string, file: File, query: Record<string, string> = {}): Promise<T> {
  const q = new URLSearchParams(query).toString();
  const res = await fetch(`/api${path}${q ? `?${q}` : ''}`, {method: 'PUT', body: file, headers: {'Content-Type': mediaType(file)},
    credentials: 'same-origin', cache: 'no-store'});
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, typeof data?.detail === 'string' ? data.detail : res.statusText);
  return data as T;
}

export const STAGE_LABEL: Record<string, string> = {
  audio_upload: 'Audio needed', audio_preparing: 'Extracting audio', audio_transcribing: 'Transcribing audio', audio_labelling: 'Label speakers',
  script_pending: 'Script needed', outline_generating: 'Writing outline', outline_review: 'Outline review',
  outline_approved: 'Outline approved', script_generating: 'Writing script', script_review: 'Script review',
  script_approved: 'Script approved', storyboard_generating: 'Building storyboard', storyboard_review: 'Storyboard review',
  storyboard_approved: 'Ready for production', producing: 'In production', production_failed: 'Production failed',
  video_review: 'Video review', final_approved: 'Approved', publishing: 'Publishing', published: 'Published',
  publish_failed: 'Publishing failed',
};

export function stageTone(stage: string): string {
  if (/failed/.test(stage)) return 'bad';
  if (/review|pending/.test(stage)) return 'warn';
  if (/generating|producing|publishing/.test(stage)) return 'busy';
  if (/approved|published/.test(stage)) return 'good';
  return 'muted';
}

export function when(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString(undefined, {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'});
}
