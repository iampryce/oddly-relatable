'use client';
// A set for every episode (owner decision 2026-11-21): the studio proposes an original set description (audio: a fixed
// sentence from the video notes' lists; script-first: the AI writer from the story), the owner edits it, and "Generate
// this set" sends exactly the prompt shown below, after the cost is confirmed. The candidate is approved in Settings.
import {useEffect, useState} from 'react';
import Link from 'next/link';
import {api} from '@/lib/api';
import {useApi} from '@/lib/hooks';
import {ErrorBox} from './ui';

export default function SetProposal({ep, candidates, onChange}: {ep: any; candidates: any[]; onChange: () => unknown}) {
  const [writing, setWriting] = useState(false);
  const {data, error, reload} = useApi<any>(`/episodes/${ep.id}/set-proposal`, writing ? 3000 : 0);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  useEffect(() => {
    if (!data) return;
    if (writing && data.source === 'writer') setWriting(false);
    setText(t => (t && !writing ? t : data.text || ''));
  }, [data, writing]);
  if (!data) return error ? <ErrorBox error={error} /> : null;
  const locked = ['producing', 'publishing'].includes(ep.stage);
  const dirty = text.trim() !== (data.text || '');
  const prompt = data.prompt && !dirty ? data.prompt : '';
  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label); setErr('');
    try { await fn(); await reload(); onChange(); } catch (e: any) { setErr(e.message); } finally { setBusy(''); }
  };
  const propose = () => run('propose', async () => {
    const r: any = await api(`/episodes/${ep.id}/set-proposal/propose`, {method: 'POST'});
    if (r.job) setWriting(true); else setText(r.text);
  });
  const save = () => run('save', async () => { const r: any = await api(`/episodes/${ep.id}/set-proposal`, {method: 'PUT', body: {text}}); setText(r.text); });
  const generate = () => {
    if (!window.confirm(`Generate one set candidate (${data.image_cost}) from exactly the prompt shown?`)) return;
    run('generate', () => api(`/episodes/${ep.id}/set-proposal/generate`, {body: {text: text.trim()}}));
  };
  const generateBoth = () => {
    if (!window.confirm(`Generate both sides of the room: ${data.two_cost} (two linked set candidates, the same description with a view line each; you approve and mark each one)?`)) return;
    run('generate', () => api(`/episodes/${ep.id}/set-proposal/generate`, {body: {text: text.trim(), views: true}}));
  };
  const mine = candidates.filter((c: any) => c.for_this_episode);
  return (
    <div className="stack" style={{borderTop: '1px solid var(--line, #ddd)', paddingTop: 10}}>
      <strong>Proposed set for this story</strong>
      <ErrorBox error={err} />
      <div className="row small" style={{gap: 6}}>
        <button className="btn sm" disabled={!!busy || locked || !data.can_propose || writing} onClick={propose}>
          {data.propose_with === 'video notes' ? 'Propose from the video notes (free)' : 'Propose from the story (AI writer)'}</button>
        {writing && <span className="muted">The AI writer is proposing a description…</span>}
        {!data.can_propose && <span className="muted">{data.propose_with === 'video notes' ? 'No video notes: write the description yourself.' : 'Write the script first, or write the description yourself.'}</span>}
        {data.source && <span className="muted">Current text: {data.source === 'edited' ? 'your edit' : `from the ${data.source}`}</span>}
      </div>
      <label htmlFor={`set-text-${ep.id}`} className="small">Description (an original place; no names, brands or on-screen text)</label>
      <textarea id={`set-text-${ep.id}`} rows={3} value={text} disabled={locked} onChange={e => setText(e.target.value)} />
      <div className="row small" style={{gap: 6}}>
        <button className="btn sm" disabled={!!busy || locked || !dirty || text.trim().length < 10} onClick={save}>Save the description</button>
        <button className="btn sm primary" disabled={!!busy || locked || dirty || !data.text} onClick={generate}
          title={dirty ? 'Save the description first, so the prompt below is exactly what is sent' : ''}>Generate this set ({data.image_cost})</button>
        {data.two_views && <button className="btn sm" disabled={!!busy || locked || dirty || !data.text} onClick={generateBoth}>Generate both sides of the room ({data.two_cost})</button>}
      </div>
      {data.two_views && !dirty && data.view_prompts?.['reverse side'] && <details><summary className="small">The notes show one room from two sides (shot / reverse shot): the two prompts sent for both sides</summary>
        {Object.entries(data.view_prompts).map(([v, p]: any) => <pre key={v} className="small" style={{whiteSpace: 'pre-wrap'}}>{p}</pre>)}</details>}
      {prompt ? <details><summary className="small">Sent to the image API (exactly)</summary><pre className="small" style={{whiteSpace: 'pre-wrap'}}>{prompt}</pre></details>
        : data.text ? <p className="muted small">Save the description to see the exact prompt that will be sent.</p> : null}
      {mine.length > 0 && <div className="row small" style={{gap: 8, flexWrap: 'wrap'}}>
        {mine.map((c: any) => <span key={c.id} className="row" style={{gap: 4}}>{c.thumbnail && <img src={c.thumbnail} alt="" style={{width: 30, height: 45, objectFit: 'cover', borderRadius: 3}} />}{c.label}</span>)}
        <Link href="/settings#sets" className="small">Approve or reject in Settings › Sets</Link></div>}
    </div>
  );
}
