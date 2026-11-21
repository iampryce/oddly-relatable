'use client';
// The Reference plan (owner decision 2026-11-21): before the scenes are built, every notes range shows what it will
// drive (set, seating, shot, reactors) with the vision model's unedited value, your edit, a used / ignored toggle and
// a note on anything the renderer cannot do yet. Nothing is built until you accept the plan; an edit withdraws it.
import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {useApi} from '@/lib/hooks';
import {ErrorBox} from './ui';

const LABEL: Record<string, string> = {set: 'Set', view: 'View', seating: 'Seating', shot: 'Shot', reactors: 'Reactors', movement: 'Movement'};

export default function ReferencePlan({episodeId, notesKey}: {episodeId: number; notesKey: string}) {
  const {data, error, reload} = useApi<any>(`/episodes/${episodeId}/reference-plan`);
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  useEffect(() => { reload(); }, [notesKey, reload]);
  if (!data) return error ? <ErrorBox error={error} /> : null;
  const ignored = data.ranges.flatMap((r: any) => Object.entries(r.items).filter(([, it]: any) => !it.used).map(([f]) => `${r.index}:${f}`));
  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label); setErr('');
    try { await fn(); await reload(); } catch (e: any) { setErr(e.message); } finally { setBusy(''); }
  };
  const toggle = (key: string, use: boolean) => run('toggle', () => api(`/episodes/${episodeId}/reference-plan`,
    {method: 'PUT', body: {ignored: use ? ignored.filter((k: string) => k !== key) : [...ignored, key]}}));
  return (
    <div className="card stack">
      <div className="spread"><h2 style={{margin: 0}}>Reference plan</h2>
        <span className={`badge ${data.accepted ? 'good' : 'warn'}`}>{data.accepted ? 'accepted' : 'not accepted yet'}</span></div>
      <p className="muted small">What the video notes will drive in this episode, per time range. Untick anything you do not want used. "Was" is what the vision model said before your edits (edit the notes above). Dialogue and timing always stay as recorded.</p>
      <ErrorBox error={err} />
      {data.ranges.map((r: any) => (
        <div key={r.index} className="stack" style={{borderTop: '1px solid var(--line, #ddd)', paddingTop: 6}}>
          <strong className="small">{r.start.toFixed(1)}-{r.end.toFixed(1)} s <span className="muted">{r.line_ids.join(', ') || 'no line'}</span></strong>
          {Object.entries(r.items).map(([f, it]: any) => (
            <label key={f} className="row small" style={{gap: 6, alignItems: 'baseline', opacity: it.used ? 1 : 0.55}}>
              <input type="checkbox" checked={it.used} disabled={!!busy} onChange={e => toggle(`${r.index}:${f}`, e.target.checked)} />
              <b style={{minWidth: 70}}>{LABEL[f]}</b>
              <span>{it.value}{it.edited && <span className="muted"> (was: {it.original})</span>}</span>
              <span className="muted">· {it.used ? 'used' : 'ignored'} · {it.note}</span>
            </label>))}
        </div>))}
      <div className="row">
        <button className="btn primary" disabled={!!busy || data.accepted} onClick={() => run('accept', () => api(`/episodes/${episodeId}/reference-plan/accept`, {method: 'POST'}))}>
          {data.accepted ? 'Plan accepted' : 'Accept the plan'}</button>
        {ignored.length > 0 && <span className="muted small">{ignored.length} item(s) ignored</span>}
      </div>
    </div>
  );
}
