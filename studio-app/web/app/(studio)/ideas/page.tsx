'use client';
import Link from 'next/link';
import {Suspense, useEffect, useState} from 'react';
import {useRouter, useSearchParams} from 'next/navigation';
import {api, uploadAudio, when} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {Empty, ErrorBox} from '@/components/ui';

const BLANK = {title: '', premise: '', notes: '', characters: [] as string[], target_seconds: 45, interactive: 'none', format: 'short', continues_episode_id: null as number | null};

function IdeaForm({initial, characters, shorts, onDone}: {initial: any; characters: any[]; shorts: any[]; onDone: () => void}) {
  const [f, setF] = useState({...BLANK, ...initial});
  const {busy, error, run} = useAction(onDone);
  const set = (k: string, v: any) => setF((x: any) => ({...x, [k]: v}));
  const save = (status: 'draft' | 'submitted') => run(status, () => {
    const body = {title: f.title, premise: f.premise, notes: f.notes, characters: f.characters, target_seconds: Number(f.target_seconds), interactive: f.format === 'long' ? 'none' : f.interactive, status,
                  format: f.format, continues_episode_id: f.format === 'long' && f.continues_episode_id ? Number(f.continues_episode_id) : null};
    return initial.id ? api(`/ideas/${initial.id}`, {method: 'PUT', body}) : api('/ideas', {body});
  });
  return (
    <div className="card">
      <h2>{initial.id ? 'Edit idea' : 'New idea'}</h2>
      <ErrorBox error={error} />
      <div className="field"><label htmlFor="t">Title</label><input id="t" value={f.title} onChange={e => set('title', e.target.value)} placeholder="e.g. The group chat at 2 a.m." /></div>
      <div className="field"><label htmlFor="p">The idea</label><textarea id="p" value={f.premise} onChange={e => set('premise', e.target.value)} placeholder="What happens, who it happens to, and why it's funny" /></div>
      <div className="field"><label htmlFor="n">Direction (optional)</label><textarea id="n" value={f.notes} onChange={e => set('notes', e.target.value)} placeholder="Twist, tone, reactions you want, things to avoid" /></div>
      <div className="grid cols-2">
        <div className="field"><label htmlFor="fmt">Format</label>
          <select id="fmt" value={f.format} onChange={e => { set('format', e.target.value); set('target_seconds', e.target.value === 'long' ? 360 : 45); }}>
            <option value="short">Short (up to 60 s)</option><option value="long">Long episode (3 acts, 5–7 minutes)</option>
          </select></div>
        {f.format === 'long' && <div className="field"><label htmlFor="cont">Continues a Short (optional)</label>
          <select id="cont" value={f.continues_episode_id ?? ''} onChange={e => set('continues_episode_id', e.target.value ? Number(e.target.value) : null)}>
            <option value="">Standalone episode</option>{shorts.map(x => <option key={x.id} value={x.id}>{x.title}</option>)}
          </select></div>}
      </div>
      {f.format === 'long' && <p className="muted small">Long episodes start with a three-act outline for your approval; scenes are then written act by act. The story decides the length: it is never padded to reach five minutes.</p>}
      <div className="grid cols-3">
        <div className="field"><label>Characters</label>
          {characters.map(c => (
            <label key={c.key} className="row" style={{fontWeight: 400, color: 'inherit'}}>
              <input type="checkbox" style={{width: 'auto'}} checked={f.characters.includes(c.key)}
                     onChange={e => set('characters', e.target.checked ? [...f.characters, c.key] : f.characters.filter((k: string) => k !== c.key))} />
              {c.name}{c.art_status !== 'approved' && <span className="badge warn">no art yet</span>}
            </label>))}
        </div>
        <div className="field"><label htmlFor="len">Target length (seconds)</label><input id="len" type="number" min={10} max={f.format === 'long' ? 450 : 60} value={f.target_seconds} onChange={e => set('target_seconds', e.target.value)} /></div>
        <div className="field"><label htmlFor="i">Interactive</label>
          <select id="i" value={f.interactive} disabled={f.format === 'long'} onChange={e => set('interactive', e.target.value)}>
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

// Audio-first: the owner's audio file is the voice track; the studio builds the characters, script and scenes around it.
// Upload only (no link downloader). The rights confirmation and its source are required; the server refuses without them.
function AudioEpisodeForm({onDone}: {onDone: (episodeId?: number) => void}) {
  const [title, setTitle] = useState('');
  const [format, setFormat] = useState('short');
  const [file, setFile] = useState<File | null>(null);
  const [rights, setRights] = useState(false);
  const [source, setSource] = useState('');
  const {busy, error, run} = useAction();
  const create = () => run('create', async () => {
    const ep = await api('/audio-episodes', {body: {title, format, rights_confirmed: rights, rights_source: source || null}});
    await uploadAudio(`/episodes/${ep.id}/audio`, file!);
    onDone(ep.id);
  });
  return (
    <div className="card">
      <h2>New episode from audio</h2>
      <p className="muted small">Upload a recording of the dialogue. It is transcribed into timed lines; you label who says each line and set up the cast. The uploaded audio is the voice track (no generated voices).</p>
      <ErrorBox error={error} />
      <div className="grid cols-2">
        <div className="field"><label htmlFor="at">Title</label><input id="at" value={title} onChange={e => setTitle(e.target.value)} /></div>
        <div className="field"><label htmlFor="af">Format</label><select id="af" value={format} onChange={e => setFormat(e.target.value)}>
          <option value="short">Short (audio up to 60 s)</option><option value="long">Long episode (audio up to 7½ minutes)</option></select></div>
      </div>
      <div className="field"><label htmlFor="afile">Audio file (MP3, WAV, M4A, AAC, OGG, FLAC; up to 60 MB)</label>
        <input id="afile" type="file" accept="audio/*" onChange={e => setFile(e.target.files?.[0] || null)} /></div>
      <div className="field"><label htmlFor="asrc">Where the audio comes from</label>
        <select id="asrc" value={source} onChange={e => setSource(e.target.value)}>
          <option value="">Choose…</option><option value="own_recording">My own recording</option><option value="licensed">Licensed</option>
          <option value="voice_actor">Voice actor (recorded for me)</option><option value="other">Other</option></select></div>
      <label className="row" style={{fontWeight: 400, color: 'inherit'}}>
        <input type="checkbox" style={{width: 'auto'}} checked={rights} onChange={e => setRights(e.target.checked)} required />
        I have the right to use this audio
      </label>
      <div className="row" style={{marginTop: 12}}>
        <button className="btn primary" disabled={!!busy || !title || !file || !rights || !source} onClick={create}>{busy ? 'Uploading…' : 'Create and upload'}</button>
        <button className="btn" onClick={() => onDone()}>Cancel</button>
      </div>
    </div>
  );
}

function Ideas() {
  const router = useRouter();
  const params = useSearchParams();
  const {data: ideas, error, reload} = useApi<any[]>('/ideas');
  const {data: characters} = useApi<any[]>('/characters');
  const {data: episodes} = useApi<any[]>('/episodes');
  const shorts = (episodes || []).filter(e => e.format === 'short' && e.script_version);
  const [editing, setEditing] = useState<any>(null);
  const [fromAudio, setFromAudio] = useState(false);
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
        {!editing && !fromAudio && <div className="row"><button className="btn" onClick={() => setFromAudio(true)}>New from audio</button>
          <button className="btn primary" onClick={() => setEditing({})}>New idea</button></div>}</div>
      <ErrorBox error={error || act.error} />
      {fromAudio && <div style={{marginBottom: 16}}><AudioEpisodeForm onDone={id => { setFromAudio(false); if (id) router.push(`/episodes/${id}`); }} /></div>}
      {editing && <div style={{marginBottom: 16}}><IdeaForm initial={editing} characters={characters || []} shorts={shorts} onDone={() => { setEditing(null); reload(); }} /></div>}
      {!ideas?.length ? <Empty>No ideas yet.</Empty> : (
        <div className="card table-wrap"><table>
          <thead><tr><th>Idea</th><th>Status</th><th>Length</th><th>Updated</th><th></th></tr></thead>
          <tbody>{ideas.map(i => (
            <tr key={i.id}>
              <td><strong>{i.title}</strong> {i.format === 'long' && <span className="badge busy">long episode</span>}<div className="muted small">{i.premise.slice(0, 160)}</div></td>
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
