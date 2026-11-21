'use client';
// The episode's own set (owner decision 2026-11-21): no silent default. Production starts only once an APPROVED set is
// chosen here. Generating a new set for the story is the main action; reusing a set is a deliberate pick that shows
// which other episodes already use it. The video notes' setting word is a suggestion only, never applied by itself.
import {useState} from 'react';
import Link from 'next/link';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from './ui';
import SetProposal from './SetProposal';

export default function EpisodeSetPicker({ep, act}: {ep: any; act: ReturnType<typeof useAction>}) {
  const {data, error, reload} = useApi<any>(`/episodes/${ep.id}/set-options`);
  const [open, setOpen] = useState(false);
  if (!data) return error ? <ErrorBox error={error} /> : null;
  const current = data.options.find((o: any) => o.id === data.current);
  const locked = ['producing', 'publishing'].includes(ep.stage);
  const pick = (o: any) => {
    if (o.used_in.length && !window.confirm(`"${o.label}" is already used in ${o.used_in.length} earlier episode(s): ${o.used_in.map((e: any) => e.title).join(', ')}. Use it again for this story?`)) return;
    act.run('set', async () => { await api(`/episodes/${ep.id}/set`, {method: 'PUT', body: {set_id: o.id}}); await reload(); setOpen(false); });
  };
  return (
    <div className="card stack">
      <div className="spread">
        <div><h2 style={{margin: 0}}>Set</h2>
          {current ? <span className="small">{current.label}{current.used_in.length ? ` · also in ${current.used_in.length} other episode(s)` : ' · only in this episode'}</span>
            : <span className="small" style={{color: 'var(--bad, #b00)'}}>No set chosen yet: production cannot start until you choose one (there is no default).</span>}</div>
        <div className="row">
          <button className="btn" disabled={locked} onClick={() => setOpen(!open)}>{open ? 'Close' : current ? 'Change set' : 'Choose an approved set'}</button>
        </div>
      </div>
      {data.suggestion && <p className="small">The video notes describe the place as <b>{data.suggestion.word}</b>{data.suggestion.set_id
        ? <>; the approved set <b>{data.options.find((o: any) => o.id === data.suggestion.set_id)?.label}</b> matches (a suggestion: nothing is applied until you choose it).</>
        : '; no approved set matches yet. Generate one for this story.'}</p>}
      {data.candidates.length > 0 && <p className="muted small">Waiting for approval in Settings › <Link href="/settings#sets">Sets</Link>: {data.candidates.map((c: any) => c.label).join(', ')}.</p>}
      <SetProposal ep={ep} candidates={data.candidates} onChange={reload} />
      {open && <div className="grid cols-3">
        {data.options.map((o: any) => (
          <div key={o.id} className="card stack" style={{padding: 10, outline: o.id === data.current ? '2px solid var(--accent, #36c)' : undefined}}>
            {o.thumbnail && <img src={o.thumbnail} alt={o.label} style={{width: '100%', aspectRatio: '9 / 16', objectFit: 'cover', borderRadius: 6}} />}
            <strong>{o.label}</strong>
            <span className="muted small">{o.source === 'repository' ? 'studio plate' : 'approved set'} · {o.style_version}{o.seat ? ' · has a seat' : ''}</span>
            <span className="small">{o.used_in.length ? `Used in ${o.used_in.length} earlier episode(s): ${o.used_in.map((e: any) => e.title).join(', ')}` : 'Not used in any other episode'}</span>
            <button className="btn sm" disabled={!!act.busy || o.id === data.current || locked} onClick={() => pick(o)}>{o.id === data.current ? 'Chosen' : 'Use this set'}</button>
            {data.current && o.id !== data.current && <label className="small row" style={{gap: 4}}>
              <input type="checkbox" disabled={!!act.busy || locked} checked={(ep.scene_set_ids || []).includes(o.id)}
                onChange={e => act.run('scene-sets', () => api(`/episodes/${ep.id}/scene-sets`, {method: 'PUT', body: {set_ids: e.target.checked
                  ? [...(ep.scene_set_ids || []), o.id] : (ep.scene_set_ids || []).filter((x: string) => x !== o.id)}}))} />
              Also for scene changes</label>}
          </div>))}
      </div>}
    </div>
  );
}
