'use client';
// A NEW set for every episode (owner rules 2026-11-21 and 2026-11-22). Audio episodes: the video's set notes (words
// only, one per distinct room, editable) are proposed verbatim, one proposal per room; script-first: the AI writer
// proposes from the story. The page shows exactly what is sent to the image API, as labelled parts (studio style /
// your description / studio rules / variety guard), and nothing is generated until the cost is confirmed.
import {useEffect, useState} from 'react';
import Link from 'next/link';
import {api} from '@/lib/api';
import {useApi} from '@/lib/hooks';
import {ErrorBox} from './ui';
import {roomTitle} from '@/lib/setView';

function Parts({parts}: {parts: any[]}) {
  return <div className="stack small">{parts.map((p: any, i: number) => (
    <div key={i}><span className="badge">{p.part}</span><pre className="small" style={{whiteSpace: 'pre-wrap', margin: '2px 0 0'}}>{p.text}</pre></div>))}</div>;
}

function RoomBox({ep, r, i, data, locked, busy, run}: {ep: any; r: any; i: number; data: any; locked: boolean; busy: string; run: (l: string, f: () => Promise<unknown>) => void}) {
  const [text, setText] = useState(r.text || '');
  useEffect(() => { setText(r.text || ''); }, [r.text]);
  const dirty = text.trim() !== (r.text || '');
  const generate = (views = false) => {
    if (!window.confirm(views ? `Generate both sides of the room: ${data.two_cost} (two linked set candidates)?`
      : `Generate one set candidate for ${roomTitle(r, i)} (${data.image_cost}) from exactly the prompt shown?`)) return;
    run('generate', () => api(`/episodes/${ep.id}/set-proposal/generate`, {body: {text: text.trim(), room: i, views}}));
  };
  return (
    <div className="stack" style={{borderLeft: '3px solid var(--line, #ddd)', paddingLeft: 8}}>
      <strong className="small">{roomTitle(r, i)}{r.source ? <span className="muted"> · {r.source === 'edited' ? 'your edit' : `from the ${r.source}`}</span> : null}
        {r.seats ? <span className="muted"> · seats for at least {r.seats}</span> : null}</strong>
      <textarea rows={3} value={text} disabled={locked} aria-label={`description for ${roomTitle(r, i)}`} onChange={e => setText(e.target.value)} />
      <div className="row small" style={{gap: 6}}>
        <button className="btn sm" disabled={!!busy || locked || !dirty || text.trim().length < 10}
          onClick={() => run('save', () => api(`/episodes/${ep.id}/set-proposal`, {method: 'PUT', body: {text, room: i}}))}>Save</button>
        <button className="btn sm primary" disabled={!!busy || locked || dirty || !r.text} onClick={() => generate(false)}
          title={dirty ? 'Save first, so the prompt below is exactly what is sent' : ''}>Generate this set ({data.image_cost})</button>
        {i === 0 && data.two_views && <button className="btn sm" disabled={!!busy || locked || dirty || !r.text} onClick={() => generate(true)}>Generate both sides of the room ({data.two_cost})</button>}
      </div>
      {!dirty && r.parts?.length > 0 && <details><summary className="small">Sent to the image API (exactly), part by part</summary><Parts parts={r.parts} /></details>}
      {dirty && <p className="muted small">Save to see the exact prompt that will be sent.</p>}
    </div>);
}

export default function SetProposal({ep, candidates, onChange}: {ep: any; candidates: any[]; onChange: () => unknown}) {
  const [writing, setWriting] = useState(false);
  const {data, error, reload} = useApi<any>(`/episodes/${ep.id}/set-proposal`, writing ? 3000 : 0);
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [first, setFirst] = useState('');
  const [variety, setVariety] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<number, string>>({});
  useEffect(() => { if (data && writing && data.source === 'writer') setWriting(false); }, [data, writing]);
  if (!data) return error ? <ErrorBox error={error} /> : null;
  const locked = ['producing', 'publishing'].includes(ep.stage);
  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label); setErr('');
    try { await fn(); await reload(); onChange(); } catch (e: any) { setErr(e.message); } finally { setBusy(''); }
  };
  const propose = () => run('propose', async () => {
    const r: any = await api(`/episodes/${ep.id}/set-proposal/propose`, {method: 'POST'});
    if (r.job) setWriting(true);
  });
  const mine = candidates.filter((c: any) => c.for_this_episode);
  const rooms: any[] = data.rooms || [];
  const vText = variety ?? data.variety ?? '';
  return (
    <div className="stack" style={{borderTop: '1px solid var(--line, #ddd)', paddingTop: 10}}>
      <strong>A new set for this story</strong>
      <span className="muted small">Each episode gets its own new set; an earlier set is used only when you keep it for reuse and choose it.</span>
      <ErrorBox error={err} />
      {data.set_notes?.length > 0 && <details open={rooms.length === 0}><summary className="small">Set notes from the video ({data.set_notes.length} room(s); words only, editable)</summary>
        <div className="stack small">
          <span className="muted">Made from a few frames per room when the video was analysed (the frames and the video are deleted). To make them again, upload the video again.</span>
          {data.set_notes.map((n: any, i: number) => {
            const v = notes[i] ?? n.text;
            return <div key={i} className="stack"><strong>{n.room}{n.edited ? ' · your edit' : ''}{n.seats ? ` · ${n.seats} seat(s)` : ''}</strong>
              <textarea rows={3} value={v} disabled={locked} aria-label={`set notes for ${n.room}`} onChange={e => setNotes(x => ({...x, [i]: e.target.value}))} />
              <div><button className="btn sm" disabled={!!busy || locked || v.trim() === n.text || v.trim().length < 10}
                onClick={() => run('notes', async () => { await api(`/episodes/${ep.id}/set-notes`, {method: 'PUT', body: {room: i, text: v}}); setNotes(x => { const y = {...x}; delete y[i]; return y; }); })}>Save the notes</button></div></div>;
          })}</div></details>}
      {data.set_notes_note && <p className="small muted">{data.set_notes_note}</p>}
      <div className="row small" style={{gap: 6}}>
        <button className="btn sm" disabled={!!busy || locked || !data.can_propose || writing} onClick={propose}>
          {data.propose_with === 'video notes' ? `Propose from the video notes (free${data.set_notes?.length ? `, ${data.set_notes.length} room(s)` : ''})` : 'Propose from the story (AI writer)'}</button>
        {writing && <span className="muted">The AI writer is proposing a description…</span>}
        {!data.can_propose && <span className="muted">{data.propose_with === 'video notes' ? 'No video notes: write the description yourself.' : 'Write the script first, or write the description yourself.'}</span>}
      </div>
      {rooms.map((r: any, i: number) => <RoomBox key={i} ep={ep} r={r} i={i} data={data} locked={locked} busy={busy} run={run} />)}
      {rooms.length === 0 && <div className="stack">
        <label htmlFor={`set-text-${ep.id}`} className="small">Description (an original place; no names, brands or on-screen text)</label>
        <textarea id={`set-text-${ep.id}`} rows={3} value={first} disabled={locked} onChange={e => setFirst(e.target.value)} />
        <div><button className="btn sm" disabled={!!busy || locked || first.trim().length < 10}
          onClick={() => run('save', () => api(`/episodes/${ep.id}/set-proposal`, {method: 'PUT', body: {text: first}}))}>Save the description</button></div></div>}
      <details><summary className="small">Variety guard ({data.variety_source === 'your edit' ? 'your edit' : 'from the recent sets'}; sent with every new set of this episode)</summary>
        <div className="stack small">
          {data.recent_sets?.length > 0 ? <span className="muted">Recent sets: {data.recent_sets.join(' · ')}</span> : <span className="muted">No recent sets yet.</span>}
          <textarea rows={5} value={vText} disabled={locked} aria-label="variety guard" onChange={e => setVariety(e.target.value)} />
          <div className="row" style={{gap: 6}}>
            <button className="btn sm" disabled={!!busy || locked || vText === (data.variety || '')}
              onClick={() => run('variety', async () => { await api(`/episodes/${ep.id}/set-proposal/variety`, {method: 'PUT', body: {text: vText}}); setVariety(null); })}>Save the variety guard</button>
            {data.variety_source === 'your edit' && <button className="btn sm" disabled={!!busy || locked}
              onClick={() => run('variety', async () => { await api(`/episodes/${ep.id}/set-proposal/variety`, {method: 'PUT', body: {text: ''}}); setVariety(null); })}>Back to the automatic guard</button>}
          </div></div></details>
      {mine.length > 0 && <div className="row small" style={{gap: 8, flexWrap: 'wrap'}}>
        {mine.map((c: any) => <span key={c.id} className="row" style={{gap: 4}}>{c.thumbnail && <img src={c.thumbnail} alt="" style={{width: 30, height: 45, objectFit: 'cover', borderRadius: 3}} />}{c.label}</span>)}
        <Link href="/settings#sets" className="small">Approve or reject in Settings › Sets</Link></div>}
    </div>
  );
}
