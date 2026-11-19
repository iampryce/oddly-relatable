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

export const STAGE_LABEL: Record<string, string> = {
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
