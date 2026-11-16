'use client';
import Link from 'next/link';
import {Suspense, useEffect, useState} from 'react';
import {useRouter, useSearchParams} from 'next/navigation';
import {api, when} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {Empty, ErrorBox} from '@/components/ui';

const BLANK = {title: '', premise: '', notes: '', characters: [] as string[], target_seconds: 45, interactive: 'none'};

function IdeaForm({initial, characters, onDone}: {initial: any; characters: any[]; onDone: () => void}) {
  const [f, setF] = useState({...BLANK, ...initial});
  const {busy, error, run} = useAction(onDone);
  const set = (k: string, v: any) => setF((x: any) => ({...x, [k]: v}));
  const save = (status: 'draft' | 'submitted') => run(status, () => {
    const body = {title: f.title, premise: f.premise, notes: f.notes, characters: f.characters, target_seconds: Number(f.target_seconds), interactive: f.interactive, status};
    return initial.id ? api(`/ideas/${initial.id}`, {method: 'PUT', body}) : api('/ideas', {body});
  });
  return (
    <div className="card">
      <h2>{initial.id ? 'Edit idea' : 'New idea'}</h2>
      <ErrorBox error={error} />
      <div className="field"><label htmlFor="t">Title</label><input id="t" value={f.title} onChange={e => set('title', e.target.value)} placeholder="e.g. The group chat at 2 a.m." /></div>
      <div className="field"><label htmlFor="p">The idea</label><textarea id="p" value={f.premise} onChange={e => set('premise', e.target.value)} placeholder="What happens, who it happens to, and why it's funny" /></div>
      <div className="field"><label htmlFor="n">Direction (optional)</label><textarea id="n" value={f.notes} onChange={e => set('notes', e.target.value)} placeholder="Twist, tone, reactions you want, things to avoid" /></div>
      <div className="grid cols-3">
        <div className="field"><label>Characters</label>
          {characters.map(c => (
            <label key={c.key} className="row" style={{fontWeight: 400, color: 'inherit'}}>
              <input type="checkbox" style={{width: 'auto'}} checked={f.characters.includes(c.key)}
                     onChange={e => set('characters', e.target.checked ? [...f.characters, c.key] : f.characters.filter((k: string) => k !== c.key))} />
              {c.name}{c.art_status !== 'approved' && <span className="badge warn">no art yet</span>}
            </label>))}
        </div>
        <div className="field"><label htmlFor="len">Target length (seconds)</label><input id="len" type="number" min={10} max={60} value={f.target_seconds} onChange={e => set('target_seconds', e.target.value)} /></div>
        <div className="field"><label htmlFor="i">Interactive</label>
          <select id="i" value={f.interactive} onChange={e => set('interactive', e.target.value)}>
            <option value="none">No</option><option value="viewer-choice">Viewer choice (comment A or B)</option><option value="poll">Question to viewers</option>
          </select></div>
      </div>
      <div className="row">
        <button className="btn" disabled={!!busy || !f.title || !f.premise} onClick={() => save('draft')}>Save as draft</button>
        <button className="btn primary" disabled={!!busy || !f.title || !f.premise} onClick={() => save('submitted')}>Submit idea</button>
        <button className="btn" onClick={onDone}>Cancel</button>
      </div>
    </div>
  );
}

function Ideas() {
  const router = useRouter();
  const params = useSearchParams();
  const {data: ideas, error, reload} = useApi<any[]>('/ideas');
  const {data: characters} = useApi<any[]>('/characters');
  const [editing, setEditing] = useState<any>(null);
  const act = useAction(reload);
  useEffect(() => { if (params.get('new')) setEditing({}); }, [params]);
  const start = (idea: any) => act.run('start', async () => {
    const ep = await api(`/ideas/${idea.id}/start`, {body: {generate_script: true}});
    router.push(`/episodes/${ep.id}`);
  });
  const archive = (idea: any) => act.run('archive', () => api(`/ideas/${idea.id}/archive`, {method: 'POST'}));
  return (
    <>
      <div className="spread"><div><h1>Ideas</h1><p className="sub">Every episode starts from your idea. Nothing is hard-coded.</p></div>
        {!editing && <button className="btn primary" onClick={() => setEditing({})}>New idea</button>}</div>
      <ErrorBox error={error || act.error} />
      {editing && <div style={{marginBottom: 16}}><IdeaForm initial={editing} characters={characters || []} onDone={() => { setEditing(null); reload(); }} /></div>}
      {!ideas?.length ? <Empty>No ideas yet.</Empty> : (
        <div className="card table-wrap"><table>
          <thead><tr><th>Idea</th><th>Status</th><th>Length</th><th>Updated</th><th></th></tr></thead>
          <tbody>{ideas.map(i => (
            <tr key={i.id}>
              <td><strong>{i.title}</strong><div className="muted small">{i.premise.slice(0, 160)}</div></td>
              <td><span className={`badge ${i.status === 'in_production' ? 'busy' : i.status === 'submitted' ? 'warn' : ''}`}>{i.status.replace('_', ' ')}</span></td>
              <td>{i.target_seconds}s</td>
              <td className="muted small">{when(i.updated_at)}</td>
              <td><div className="row" style={{justifyContent: 'flex-end'}}>
                {i.episode_id ? <Link className="btn sm" href={`/episodes/${i.episode_id}`}>Open episode</Link> : i.status !== 'archived' && <>
                  <button className="btn sm" onClick={() => setEditing(i)}>Edit</button>
                  <button className="btn sm" onClick={() => archive(i)}>Archive</button>
                  <button className="btn sm primary" disabled={!!act.busy} onClick={() => start(i)}>Start production</button></>}
              </div></td>
            </tr>))}
          </tbody></table></div>)}
    </>
  );
}

export default function IdeasPage() {
  return <Suspense><Ideas /></Suspense>;
}
