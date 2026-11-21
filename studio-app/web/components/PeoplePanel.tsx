'use client';
// The video's people and their beats (feat/action-beats). Numbered people from the notes are mapped to characters by
// YOU (the studio only suggests from timing); beats are acted only for confirmed people. Every beat can be removed or
// changed; the derived beats stay as the "was" values. Lying down and kneeling are listed but will be skipped.
import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {useApi} from '@/lib/hooks';
import {ErrorBox} from './ui';

const TYPES = ['enter', 'exit', 'sit_down', 'stand_up', 'walk', 'lean_in', 'lean_back', 'turn_to', 'turn_away', 'nod', 'head_shake', 'phone_to_ear', 'gesture'];

export default function PeoplePanel({episodeId, characters, editable}: {episodeId: number; characters: {key: string; name: string}[]; editable: boolean}) {
  const {data, error, reload} = useApi<any>(`/episodes/${episodeId}/people`);
  const [map, setMap] = useState<Record<string, number | null>>({});
  const [beats, setBeats] = useState<any[] | null>(null);
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  useEffect(() => { if (data) setMap(data.map || {}); }, [data]);
  if (!data) return error ? null : null;
  if (!data.people?.length) return null;
  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label); setErr('');
    try { await fn(); await reload(); setBeats(null); } catch (e: any) { setErr(e.message); } finally { setBusy(''); }
  };
  const personOf = (key: string) => map[key] ?? null;
  const setPerson = (key: string, v: string) => setMap({...map, [key]: v ? Number(v) : null});
  const list = beats || data.beats;
  const edit = (i: number, patch: any) => setBeats(list.map((b: any, j: number) => j === i ? {...b, ...patch} : b));
  return (
    <div className="card stack">
      <h2 style={{margin: 0}}>People in the video</h2>
      <p className="muted small">Numbered by the vision notes (never named or described). Choose who is who: the studio only suggests{data.talking_informative ? ' from who seems to talk during each line' : ' (the video does not show clearly who talks, so there is no suggestion)'}. Beats are acted only for confirmed people; the speaker then follows the recorded lines.</p>
      <ErrorBox error={err} />
      <div className="grid cols-2">
        {characters.map(c => (
          <div key={c.key} className="row small" style={{gap: 6}}>
            <label htmlFor={`person-${c.key}`} style={{minWidth: 110}}>{c.name}</label>
            <select id={`person-${c.key}`} disabled={!editable} value={personOf(c.key) ?? ''} onChange={e => setPerson(c.key, e.target.value)}>
              <option value="">not in the video</option>
              {data.people.map((p: any) => <option key={p.person} value={p.person}>person {p.person} ({p.appearances} frames)</option>)}
            </select>
            {data.suggestion?.[c.key] && personOf(c.key) == null && <span className="muted">suggested: person {data.suggestion[c.key]}</span>}
          </div>))}
      </div>
      {editable && <div className="row">
        <button className="btn primary" disabled={!!busy} onClick={() => run('map', () => api(`/episodes/${episodeId}/people`, {method: 'PUT', body: {map}}))}>Confirm who is who</button>
        {data.notes_edited && <button className="btn" disabled={!!busy} onClick={() => { if (window.confirm('Rebuild the ranges and beats from the video frames? Your edits to the notes ranges and beats are replaced.')) run('rebuild', () => api(`/episodes/${episodeId}/notes/rebuild`, {method: 'POST'})); }}>Rebuild from the video frames</button>}
      </div>}
      <h3 style={{margin: '8px 0 0'}}>Action beats {data.beats_edited && <span className="muted small">(edited)</span>}</h3>
      {!list.length && <p className="muted small">No beats: nobody moves, turns or gestures for long enough in the frames.</p>}
      {list.map((b: any, i: number) => (
        <div key={b.id || i} className="row small" style={{gap: 6, opacity: b.supported === false ? 0.6 : 1}}>
          <input type="number" step="0.1" min={0} style={{width: 72}} disabled={!editable} value={b.t} aria-label="time" onChange={e => edit(i, {t: Number(e.target.value)})} />
          <span>person {b.person}</span>
          <select disabled={!editable} value={b.type} aria-label="beat" onChange={e => edit(i, {type: e.target.value})}>
            {[...TYPES, ...(TYPES.includes(b.type) ? [] : [b.type])].map(t => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
          </select>
          <span className="muted">{b.text || ''}</span>
          {editable && <button className="btn sm" onClick={() => setBeats(list.filter((_: any, j: number) => j !== i))}>Remove</button>}
        </div>))}
      {editable && beats && <div className="row">
        <button className="btn primary" disabled={!!busy} onClick={() => run('beats', () => api(`/episodes/${episodeId}/beats`, {method: 'PUT', body: {beats: beats.map(({text, supported, ...b}: any) => b)}}))}>Save beats</button>
        <button className="btn" onClick={() => setBeats(null)}>Undo changes</button></div>}
    </div>);
}
