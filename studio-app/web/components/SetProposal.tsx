'use client';
// A NEW set for every episode (owner rules 2026-11-21 and 2026-11-22). The set notes (words only, one per distinct room,
// editable; from the video notes or from "Read the room from a video") are proposed verbatim, one proposal per room;
// script-first episodes without set notes: the AI writer proposes from the story. Every set is TEXT ONLY unless you
// attach a reference picture of your own; your description leads the prompt and the studio's short style follows it.
// The page shows the exact request sent to the image API in one box, and nothing is generated until you confirm the cost.
import {useEffect, useState} from 'react';
import {api, uploadFile} from '@/lib/api';
import {useApi} from '@/lib/hooks';
import {ErrorBox} from './ui';
import {roomTitle} from '@/lib/setView';
import {videoSeconds} from './VideoNotesOptions';

const usd = (n: number) => `$${n < 0.01 ? n.toFixed(4) : n.toFixed(3)}`;

// "Read the room from a video": set notes only (the recording, lines, speakers and cast are not touched; the video is
// deleted after use). The cost and the cap show before anything is sent.
function ReadTheRoom({ep, locked, busy, run}: {ep: any; locked: boolean; busy: string; run: (l: string, f: () => Promise<unknown>) => void}) {
  const [file, setFile] = useState<File | null>(null);
  const [est, setEst] = useState<any>(null);
  useEffect(() => {
    let live = true;
    if (!file) { setEst(null); return; }
    videoSeconds(file).then(s => api(`/episodes/${ep.id}/set-notes/read-video/estimate?seconds=${s ?? 0}`)).then(e => { if (live) setEst(e); }).catch(() => live && setEst(null));
    return () => { live = false; };
  }, [file, ep.id]);
  const ok = est?.configured && est.within_cap;
  return (
    <details><summary className="small">Read the room from a video (set notes only)</summary>
      <div className="stack small">
        <span className="muted">Upload a video of the kind of room you want. A few frames are described once in words only (room, furniture with shape, material and colour, walls, floor and light as colour words, windows, doors and bookcases, and who sits or stands where); the video and the frames are deleted after the call. The recording, the lines, the speakers and the cast are not touched.</span>
        <input type="file" accept="video/*" aria-label="video to read the room from" disabled={locked || !!busy} onChange={e => setFile(e.target.files?.[0] || null)} />
        {file && !est && <span className="muted">Working out the cost…</span>}
        {est && !est.configured && <span className="alert warn">{est.message}</span>}
        {est?.configured && <span className={est.within_cap ? 'muted' : 'alert bad'}>{est.frames} frame(s), one call to {est.provider} · about {usd(est.usd)} · cap ${Number(est.cap_usd).toFixed(2)}{est.within_cap ? '' : ': over the cap, so it will be refused'}</span>}
        {file && <div><button className="btn sm primary" disabled={locked || !!busy || !ok}
          onClick={() => run('read', async () => { await uploadFile(`/episodes/${ep.id}/set-notes/read-video`, file); setFile(null); })}>Read the room{ok ? ` (about ${usd(est.usd)})` : ''}</button></div>}
      </div></details>);
}

// The owner's own reference picture: the only picture ever attached to a set request (no video frame, no third-party image).
function OwnReference({ep, data, locked, busy, run}: {ep: any; data: any; locked: boolean; busy: string; run: (l: string, f: () => Promise<unknown>) => void}) {
  const [file, setFile] = useState<File | null>(null);
  const [own, setOwn] = useState(false);
  if (data.reference) return (
    <div className="row small" style={{gap: 6}}>{data.reference.url && <img src={data.reference.url} alt="your reference" style={{width: 40, height: 60, objectFit: 'cover', borderRadius: 3}} />}
      <span>New sets follow your own reference picture ({data.reference.label}).</span>
      <button className="btn sm" disabled={locked || !!busy} onClick={() => run('ref', () => api(`/episodes/${ep.id}/set-proposal/reference`, {method: 'DELETE'}))}>Remove (back to text only)</button></div>);
  return (
    <details><summary className="small">Attach a reference picture of your own (optional; sets are text only without one)</summary>
      <div className="stack small">
        <input type="file" accept="image/png,image/jpeg,image/webp" aria-label="your own reference picture" disabled={locked || !!busy} onChange={e => setFile(e.target.files?.[0] || null)} />
        <label className="row" style={{gap: 4}}><input type="checkbox" checked={own} onChange={e => setOwn(e.target.checked)} />This picture is my own (not a video frame or someone else's image)</label>
        <div><button className="btn sm" disabled={locked || !!busy || !file || !own}
          onClick={() => run('ref', async () => { await uploadFile(`/episodes/${ep.id}/set-proposal/reference`, file!, {own: 'true'}); setFile(null); setOwn(false); })}>Attach</button></div>
      </div></details>);
}

function RoomBox({ep, r, i, data, locked, busy, run}: {ep: any; r: any; i: number; data: any; locked: boolean; busy: string; run: (l: string, f: () => Promise<unknown>) => void}) {
  const [text, setText] = useState(r.text || '');
  useEffect(() => { setText(r.text || ''); }, [r.text]);
  const dirty = text.trim() !== (r.text || '');
  const seat = data.seat_cost?.configured ? `, plus about ${usd(data.seat_cost.usd)} each for the suggested seats` : '';
  const generate = (views = false) => {
    if (!window.confirm(views ? `Generate both sides of the room: ${data.two_cost} (two linked set candidates)${seat}?`
      : `Generate one set candidate for ${roomTitle(r, i)} (${data.image_cost}${seat}) from exactly the request shown?`)) return;
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
      {!dirty && r.request_text && <details><summary className="small">The exact request that will be sent ({r.request?.reference_image === 'none (text only)' ? 'text only' : 'with your own reference picture'})</summary>
        <pre className="small" style={{whiteSpace: 'pre-wrap', margin: 0}}>{r.request_text}</pre></details>}
      {dirty && <p className="muted small">Save to see the exact request that will be sent.</p>}
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
      {data.set_notes?.length > 0 && <details open={rooms.length === 0}><summary className="small">Set notes from {data.set_notes_from || 'the video'} ({data.set_notes.length} room(s); words only, editable, used verbatim)</summary>
        <div className="stack small">
          <span className="muted">Made from a few frames per room (the frames and the video are deleted). To make them again, read the room from a video below.</span>
          {data.set_notes.map((n: any, i: number) => {
            const v = notes[i] ?? n.text;
            return <div key={i} className="stack"><strong>{n.room}{n.edited ? ' · your edit' : ''}{n.seats ? ` · ${n.seats} seat(s)` : ''}</strong>
              <textarea rows={3} value={v} disabled={locked} aria-label={`set notes for ${n.room}`} onChange={e => setNotes(x => ({...x, [i]: e.target.value}))} />
              <div><button className="btn sm" disabled={!!busy || locked || v.trim() === n.text || v.trim().length < 10}
                onClick={() => run('notes', async () => { await api(`/episodes/${ep.id}/set-notes`, {method: 'PUT', body: {room: i, text: v}}); setNotes(x => { const y = {...x}; delete y[i]; return y; }); })}>Save the notes</button></div></div>;
          })}</div></details>}
      {data.set_notes_note && <p className="small muted">{data.set_notes_note}</p>}
      <ReadTheRoom ep={ep} locked={locked} busy={busy} run={run} />
      <OwnReference ep={ep} data={data} locked={locked} busy={busy} run={run} />
      <div className="row small" style={{gap: 6}}>
        <button className="btn sm" disabled={!!busy || locked || !data.can_propose || writing} onClick={propose}>
          {data.propose_with === 'set notes' ? `Propose from the set notes (free, ${data.set_notes.length} room(s))` : data.propose_with === 'video notes' ? 'Propose from the video notes (free)' : 'Propose from the story (AI writer)'}</button>
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
      {mine.length > 0 && <p className="muted small">{mine.length} candidate(s) wait for your decision in the panel above.</p>}
    </div>
  );
}
