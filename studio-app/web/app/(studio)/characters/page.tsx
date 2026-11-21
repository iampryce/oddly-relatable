'use client';
import {useState} from 'react';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {Empty, ErrorBox} from '@/components/ui';

const BLANK = {key: '', name: '', description: '', visual_description: '', bubble_style: 'neutral', scope: 'recurring', default_expression: 'neutral', voice: '', voice_style: '', voice_speed: null, skin_tone: ''};
const SUGGESTED = 'neutral, happy, laughing, shocked, angry, worried, smug, scared';

function CharacterForm({initial, onDone}: {initial: any; onDone: () => void}) {
  const [f, setF] = useState({...BLANK, ...initial});
  const {busy, error, run} = useAction(onDone);
  const [pick, setPick] = useState<{text: string; bad?: boolean} | null>(null);
  const [picking, setPicking] = useState(false);
  const suggest = async () => {
    setPicking(true); setPick(null);
    try {
      const r: any = await api(`/characters/${initial.id}/suggest-voice`, {body: {use_ai: true}});
      if (r.voice) { set('voice', r.voice); setPick({text: `Picked ${r.label}${r.ai ? ' (AI)' : ''}: ${r.reason}. Review, then Save.`}); }
      else setPick({text: r.reason, bad: true});
    } catch (e: any) { setPick({text: String(e?.message || e), bad: true}); }
    setPicking(false);
  };
  const set = (k: string, v: string) => setF((x: any) => ({...x, [k]: v}));
  const body = () => ({key: f.key, name: f.name, description: f.description, visual_description: f.visual_description, bubble_style: f.bubble_style,
                       scope: f.scope, episode_id: f.episode_id ?? null, default_expression: f.default_expression, voice: f.voice || '', voice_style: f.voice_style || '',
                       voice_speed: f.voice_speed === '' || f.voice_speed == null ? null : Number(f.voice_speed), skin_tone: f.skin_tone || ''});
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
      <div className="grid cols-2">
        <div><label htmlFor="characters-voice">Voice (provider voice: e.g. OpenAI "onyx", an ElevenLabs voice id, a Piper model path, or fish:&lt;Fish voice id&gt;)</label>
          <input id="characters-voice" value={f.voice} onChange={e => set('voice', e.target.value)} placeholder="default voice if empty" />
          {initial.id && <div className="row"><button type="button" className="btn sm" disabled={picking} onClick={suggest}>{picking ? 'Picking…' : 'Pick a voice for me'}</button>
            {pick && <span className={pick.bad ? 'muted small' : 'small'}>{pick.text}</span>}</div>}
          <label htmlFor="characters-skin">Skin tone (art style v2; empty = white head like the rest of the cast)</label>
          <input id="characters-skin" value={f.skin_tone || ''} maxLength={40} onChange={e => set('skin_tone', e.target.value)} placeholder="e.g. warm medium brown" />
          <label htmlFor="characters-voice-speed">Voice speed (0.5–2, empty = normal; Fish Audio)</label>
          <input id="characters-voice-speed" type="number" step="0.05" min={0.5} max={2} value={f.voice_speed ?? ''} onChange={e => set('voice_speed', e.target.value)} /></div>
        <div><label htmlFor="characters-voice-style">How they sound (given to the voice model)</label>
          <textarea id="characters-voice-style" value={f.voice_style} onChange={e => set('voice_style', e.target.value)} placeholder="Age, pace, tone; e.g. deep, slow, deadpan" /></div>
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
  const poses = c.assets.filter((a: any) => a.kind === 'pose' && a.status !== 'rejected');
  const refs = c.assets.filter((a: any) => a.kind === 'reference');
  const sheet = c.assets.find((a: any) => a.kind === 'sheet');
  const sample = c.assets.find((a: any) => a.kind === 'voice-sample');
  const reviewing = poses.filter((p: any) => p.status === 'review').length;
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
            <span className="badge">{c.scope === 'episode' ? `from episode ${c.episode_id}` : 'recurring cast'}</span>{c.locked && <span className="badge">approved artwork · locked</span>}</div></div>
        <button className="btn sm" onClick={() => setEditing(true)}>{c.locked ? 'Set voice' : 'Edit'}</button>
      </div>
      <ErrorBox error={act.error} />
      <p className="small">{c.description || <span className="muted">No description.</span>}</p>
      {c.visual_description && <p className="small muted">Look: {c.visual_description}</p>}
      <div className="small"><strong>Expressions usable in scripts:</strong> {Object.keys(c.expressions).join(', ') || <span className="muted">none yet</span>}</div>
      {sheet && <div><strong className="small">Expression sheet</strong> <span className={`badge ${sheet.status === 'approved' ? 'good' : sheet.status === 'review' ? 'warn' : 'bad'}`}>{sheet.status}</span>
        <a href={sheet.url} target="_blank" rel="noreferrer"><img className="scene-img" style={{marginTop: 6}} src={sheet.url} alt={`${c.name} expression sheet`} loading="lazy" /></a></div>}
      {!c.locked && reviewing > 0 && (
        <div className="alert warn row" style={{justifyContent: 'space-between'}}><span>{reviewing} pose(s) await your review. Only approved poses are used in production.</span>
          <span className="row"><button className="btn sm good" disabled={!!act.busy} onClick={() => act.run('ok', () => api(`/characters/${c.id}/sheet/decision`, {body: {decision: 'approve'}}))}>Approve sheet</button>
            <button className="btn sm danger" disabled={!!act.busy} onClick={() => act.run('no', () => api(`/characters/${c.id}/sheet/decision`, {body: {decision: 'reject'}}))}>Reject sheet</button></span></div>)}
      {poses.length > 0 && <div className="poses">{poses.map((p: any) => (
        <div key={p.id} className="pose">
          <a href={p.url} target="_blank" rel="noreferrer"><img src={p.url} alt={`${c.name} ${p.expression}`} loading="lazy" /></a>
          <div className="small">{p.expression}</div>
          <span className={`badge ${p.status === 'approved' ? 'good' : p.status === 'rejected' ? 'bad' : 'warn'}`}>{p.status}</span>
          {!c.locked && p.status === 'approved' && (p.rig_check
            ? <div className={`small ${p.rig_check.ok === false ? 'alert bad' : 'muted'}`} style={{marginTop: 4}} title={p.rig_check.message}>
                {p.rig_check.ok === true ? `Rig check: OK (${p.rig_check.role === 'body' ? 'body and face' : 'face'})`
                  : p.rig_check.ok === false ? `Rig check failed: ${p.rig_check.message}` : `Rig check: ${p.rig_check.message}`}</div>
            : <div className="small muted" style={{marginTop: 4}}>Rig check: waiting for the worker</div>)}
          {!c.locked && p.status === 'review' && <div className="row" style={{justifyContent: 'center', marginTop: 4}}>
            <button className="btn sm good" onClick={() => act.run('a', () => api(`/character-assets/${p.id}/decision`, {body: {decision: 'approve'}}))}>Approve</button>
            <button className="btn sm danger" onClick={() => act.run('r', () => api(`/character-assets/${p.id}/decision`, {body: {decision: 'reject'}}))}>Reject</button></div>}
        </div>))}</div>}
      {!c.locked && (
        <div className="stack">
          <div className="row">{refs.map((r: any) => <a key={r.id} href={r.url} target="_blank" rel="noreferrer" className="small">reference</a>)}
            <label className="btn sm" style={{display: 'inline-block', margin: 0}}>Upload visual reference<input type="file" accept="image/png,image/jpeg" hidden onChange={e => upload(e.target.files?.[0])} /></label></div>
          <div><label htmlFor={`exprs-${c.id}`}>Expression sheet (comma separated; neutral is drawn first and anchors the rest; one image each, started only by you)</label>
            <div className="row"><input id={`exprs-${c.id}`} style={{flex: 1}} value={exprs} onChange={e => setExprs(e.target.value)} />
              <button className="btn primary" disabled={!!act.busy} onClick={() => act.run('gen', () => api(`/characters/${c.id}/sheet`, {body: {expressions: exprs.split(',').map(x => x.trim()).filter(Boolean)}}))}>Generate sheet</button></div></div>
          {c.art_status === 'approved' && <div><button className="btn" disabled={!!act.busy} onClick={() => act.run('restyle', () => api(`/characters/${c.id}/restyle`, {method: 'POST', body: {}}))}>Restyle to house style</button>
            <span className="muted small"> Redraws {c.name} in Character 01&apos;s stickman style (keeps their traits). The current art stays in use until you approve the new sheet.</span></div>}
          {c.scope === 'episode' && c.art_status === 'approved' && <div><button className="btn" disabled={!!act.busy} onClick={() => act.run('promote', () => api(`/characters/${c.id}/promote`, {method: 'POST'}))}>Add to recurring cast</button>
            <span className="muted small"> Saves {c.name} for reuse in future stories.</span></div>}
        </div>)}
      <div className="row small">
        <strong>Voice:</strong> {c.voice || <span className="muted">default</span>}{c.voice_speed ? ` (speed ${c.voice_speed})` : ''}{c.voice_style && <span className="muted">· {c.voice_style}</span>}
        <button className="btn sm" disabled={!!act.busy} onClick={() => act.run('voice', () => api(`/characters/${c.id}/voice/preview`, {body: {}}))}>Preview voice</button>
      </div>
      {sample && <audio controls preload="none" src={sample.url} style={{width: '100%'}} />}
    </div>
  );
}

export default function Characters() {
  const {data, error, reload} = useApi<any[]>('/characters', 8000);
  const [creating, setCreating] = useState(false);
  const [checkNote, setCheckNote] = useState('');
  const checkAll = async () => {
    const r = await api('/characters/rig-check-all', {method: 'POST'});
    setCheckNote(`Rig check queued for ${r.queued.length} character(s)${r.already_running ? ` (${r.already_running} already running)` : ''}. Results appear on the pose cards; approvals are not changed.`);
    reload();
  };
  return (
    <>
      <div className="spread"><div><h1>Characters</h1><p className="sub">No fixed cast: stories introduce the characters they need. Approve their expression sheets, then keep the ones you want for future stories.</p></div>
        <div className="row"><button className="btn" title="Checks that the acting rig can be built from every approved pose (informational: approvals are never changed)" onClick={() => checkAll().catch(e => setCheckNote(e.message))}>Run rig check on all approved poses</button>
          {!creating && <button className="btn primary" onClick={() => setCreating(true)}>New character</button>}</div></div>
      {checkNote && <p className="small muted">{checkNote}</p>}
      <ErrorBox error={error} />
      {creating && <div style={{marginBottom: 16}}><CharacterForm initial={{}} onDone={() => { setCreating(false); reload(); }} /></div>}
      {data && !data.length && <Empty>No characters.</Empty>}
      <h2>Recurring cast</h2>
      <div className="grid cols-2" style={{marginBottom: 20}}>{(data || []).filter(c => c.scope === 'recurring').map(c => <CharacterCard key={c.id} c={c} reload={reload} />)}</div>
      <h2>Introduced by stories</h2>
      {data && !data.some(c => c.scope === 'episode') && <Empty>No story-specific characters yet. When a script introduces one, it appears here for its expression sheet.</Empty>}
      <div className="grid cols-2">{(data || []).filter(c => c.scope === 'episode').map(c => <CharacterCard key={c.id} c={c} reload={reload} />)}</div>
    </>
  );
}
