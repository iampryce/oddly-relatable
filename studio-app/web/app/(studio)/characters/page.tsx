'use client';
import {useState} from 'react';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {Empty, ErrorBox} from '@/components/ui';

const BLANK = {key: '', name: '', description: '', visual_description: '', bubble_style: 'neutral', scope: 'recurring', default_expression: 'neutral'};
const SUGGESTED = 'neutral, happy, laughing, shocked, angry, sad, smug, scared, confused, deadpan';

function CharacterForm({initial, onDone}: {initial: any; onDone: () => void}) {
  const [f, setF] = useState({...BLANK, ...initial});
  const {busy, error, run} = useAction(onDone);
  const set = (k: string, v: string) => setF((x: any) => ({...x, [k]: v}));
  const body = () => ({key: f.key, name: f.name, description: f.description, visual_description: f.visual_description, bubble_style: f.bubble_style,
                       scope: f.scope, episode_id: f.episode_id ?? null, default_expression: f.default_expression});
  return (
    <div className="card stack">
      <h2>{initial.id ? `Edit ${initial.name}` : 'New character'}</h2>
      <ErrorBox error={error} />
      <div className="grid cols-3">
        <div><label htmlFor="characters-name-1">Name</label><input id="characters-name-1" value={f.name} onChange={e => set('name', e.target.value)} /></div>
        <div><label htmlFor="characters-key-used-in-scripts-2">Key (used in scripts)</label><input id="characters-key-used-in-scripts-2" value={f.key} disabled={!!initial.id} placeholder="e.g. dad" onChange={e => set('key', e.target.value.toLowerCase())} /></div>
        <div><label htmlFor="characters-speech-bubble-style-3">Speech bubble style</label><select id="characters-speech-bubble-style-3" value={f.bubble_style} onChange={e => set('bubble_style', e.target.value)}>
          <option value="neutral">Neutral (white)</option><option value="him">Rust</option><option value="her">Cream</option></select></div>
      </div>
      <div className="grid cols-2">
        <div><label htmlFor="characters-who-they-are-personality-4">Who they are (personality, comic role)</label><textarea id="characters-who-they-are-personality-4" value={f.description} onChange={e => set('description', e.target.value)} /></div>
        <div><label htmlFor="characters-how-they-look-used-for-i-5">How they look (used for image generation and consistency)</label><textarea id="characters-how-they-look-used-for-i-5" value={f.visual_description} onChange={e => set('visual_description', e.target.value)} placeholder="Head shape, hair, face, clothing colours, proportions, posture" /></div>
      </div>
      <div className="grid cols-2">
        <div><label htmlFor="characters-scope-6">Scope</label><select id="characters-scope-6" value={f.scope} onChange={e => set('scope', e.target.value)}><option value="recurring">Recurring cast</option><option value="episode">One episode only</option></select></div>
        <div><label htmlFor="characters-default-expression-7">Default expression</label><input id="characters-default-expression-7" value={f.default_expression} onChange={e => set('default_expression', e.target.value)} /></div>
      </div>
      <div className="row">
        <button className="btn primary" disabled={!!busy || !f.name || !f.key} onClick={() => run('save', () => initial.id ? api(`/characters/${initial.id}`, {method: 'PUT', body: body()}) : api('/characters', {body: body()}))}>Save</button>
        <button className="btn" onClick={onDone}>Cancel</button>
      </div>
    </div>
  );
}

function CharacterCard({c, reload}: {c: any; reload: () => unknown}) {
  const act = useAction(reload);
  const [exprs, setExprs] = useState(SUGGESTED);
  const [editing, setEditing] = useState(false);
  const poses = c.assets.filter((a: any) => a.kind === 'pose');
  const refs = c.assets.filter((a: any) => a.kind === 'reference');
  const upload = (file?: File) => file && act.run('upload', () => new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => api(`/characters/${c.id}/reference`, {body: {png_base64: String(r.result).split(',')[1]}}).then(resolve, reject);
    r.onerror = () => reject(new Error('could not read the file'));
    r.readAsDataURL(file);
  }));
  if (editing) return <CharacterForm initial={c} onDone={() => { setEditing(false); reload(); }} />;
  return (
    <div className="card stack">
      <div className="spread">
        <div><h2 style={{marginBottom: 2}}>{c.name} <span className="muted small mono">{c.key}</span></h2>
          <div className="row small"><span className={`badge ${c.art_status === 'approved' ? 'good' : c.art_status === 'none' ? 'bad' : 'warn'}`}>art: {c.art_status}</span>
            <span className="badge">{c.scope}</span>{c.locked && <span className="badge">approved artwork · locked</span>}</div></div>
        {!c.locked && <button className="btn sm" onClick={() => setEditing(true)}>Edit</button>}
      </div>
      <ErrorBox error={act.error} />
      <p className="small">{c.description || <span className="muted">No description.</span>}</p>
      {c.visual_description && <p className="small muted">Look: {c.visual_description}</p>}
      <div className="small"><strong>Expressions usable in scripts:</strong> {Object.keys(c.expressions).join(', ') || <span className="muted">none yet</span>}</div>
      {poses.length > 0 && <div className="poses">{poses.map((p: any) => (
        <div key={p.id} className="pose">
          <a href={p.url} target="_blank" rel="noreferrer"><img src={p.url} alt={`${c.name} ${p.expression}`} loading="lazy" /></a>
          <div className="small">{p.expression}</div>
          <span className={`badge ${p.status === 'approved' ? 'good' : p.status === 'rejected' ? 'bad' : 'warn'}`}>{p.status}</span>
          {!c.locked && p.status === 'review' && <div className="row" style={{justifyContent: 'center', marginTop: 4}}>
            <button className="btn sm good" onClick={() => act.run('a', () => api(`/character-assets/${p.id}/decision`, {body: {decision: 'approve'}}))}>Approve</button>
            <button className="btn sm danger" onClick={() => act.run('r', () => api(`/character-assets/${p.id}/decision`, {body: {decision: 'reject'}}))}>Reject</button></div>}
        </div>))}</div>}
      {!c.locked && (
        <div className="stack">
          <div className="row">{refs.map((r: any) => <a key={r.id} href={r.url} target="_blank" rel="noreferrer" className="small">reference</a>)}
            <label className="btn sm" style={{display: 'inline-block', margin: 0}}>Upload visual reference<input type="file" accept="image/png,image/jpeg" hidden onChange={e => upload(e.target.files?.[0])} /></label></div>
          <div><label>Generate expression poses (comma separated; each is one image, started only by you)</label>
            <div className="row"><input style={{flex: 1}} value={exprs} onChange={e => setExprs(e.target.value)} />
              <button className="btn primary" disabled={!!act.busy} onClick={() => act.run('gen', () => api(`/characters/${c.id}/poses/generate`, {body: {expressions: exprs.split(',').map(x => x.trim()).filter(Boolean)}}))}>Generate poses</button></div></div>
        </div>)}
    </div>
  );
}

export default function Characters() {
  const {data, error, reload} = useApi<any[]>('/characters', 8000);
  const [creating, setCreating] = useState(false);
  return (
    <>
      <div className="spread"><div><h1>Characters</h1><p className="sub">Reusable cast and one-off characters. Only owner-approved poses are used in production.</p></div>
        {!creating && <button className="btn primary" onClick={() => setCreating(true)}>New character</button>}</div>
      <ErrorBox error={error} />
      {creating && <div style={{marginBottom: 16}}><CharacterForm initial={{}} onDone={() => { setCreating(false); reload(); }} /></div>}
      {data && !data.length && <Empty>No characters.</Empty>}
      <div className="grid cols-2">{(data || []).map(c => <CharacterCard key={c.id} c={c} reload={reload} />)}</div>
    </>
  );
}
