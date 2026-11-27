'use client';
import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {BulkDelete, DeleteButton} from '@/components/BinButtons';
import {useAction, useApi} from '@/lib/hooks';
import HeadAngles from '@/components/HeadAngles';
import StickMaster from '@/components/StickMaster';
import CastLibrary from '@/components/CastLibrary';
import {Empty, ErrorBox} from '@/components/ui';
import {groupCharacters, imageCost, isCandidate, jobFinished, jobText, needsRigCheck, poseRigText, removable, rigStatus, visiblePoses} from '@/lib/characterView';

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

function thumbOf(c: any): string | null {
  // the stick pipeline's approved master is the character's look when there is one
  const master = c.assets.find((a: any) => a.kind === 'master' && a.status === 'approved');
  if (master) return master.url;
  const poses = c.assets.filter((a: any) => a.kind === 'pose');
  const p = poses.find((a: any) => a.status === 'approved' && a.expression === 'neutral') || poses.find((a: any) => a.status === 'approved')
    || poses.find((a: any) => a.status === 'review');
  return p ? p.url : null;
}

function CharacterCard({c, reload, used, selectable, selected, onSelect}: {c: any; reload: () => unknown; used?: any[]; selectable?: boolean; selected?: boolean; onSelect?: (v: boolean) => void}) {
  const act = useAction(reload);
  const [exprs, setExprs] = useState(SUGGESTED);
  const [editing, setEditing] = useState(false);
  const [open, setOpen] = useState(false);
  const [allPoses, setAllPoses] = useState(false);
  const [plan, setPlan] = useState<any>(null);
  const [cands, setCands] = useState(3);
  const [cap, setCap] = useState(1);
  useEffect(() => {
    // the first sheet: only the expressions the story needs (neutral for a silent character), cost shown first
    if (!open || c.locked || c.art_status === 'approved' || plan) return;
    api(`/characters/${c.id}/sheet-plan`).then(p => { setPlan(p); setExprs(p.expressions.join(', ')); }).catch(() => {});
  }, [open, c.id, c.locked, c.art_status, plan]);
  const exprList = exprs.split(',').map(x => x.trim()).filter(Boolean);
  const hasNeutral = c.assets.some((a: any) => a.kind === 'pose' && a.status === 'approved' && a.expression === 'neutral');
  const genSheet = () => {
    if (!window.confirm(`Generate ${c.name}'s sheet: ${imageCost(exprList.length)}?`)) return;
    act.run('gen', () => api(`/characters/${c.id}/sheet`, {body: {expressions: exprList}}));
  };
  // a job this card started (candidates or a rig check), followed until it ends; its state and any error are shown
  const [follow, setFollow] = useState<any>(null);
  useEffect(() => {
    if (!follow || jobFinished(follow)) return;
    const t = setTimeout(() => api(`/jobs/${follow.id}`).then(j => { setFollow(j); if (jobFinished(j)) reload(); })
      .catch(e => setFollow({...follow, status: 'failed', error: `could not read the job: ${e.message}`})), 2000);
    return () => clearTimeout(t);
  }, [follow, reload]);
  const genCands = () => {
    if (!window.confirm(`Generate ${cands} body pose candidate(s) for ${c.name}: ${imageCost(cands)} (cap ${'$'}${cap.toFixed(2)}). Each is rig-checked; only passing ones are shown.`)) return;
    act.run('cands', async () => setFollow((await api(`/characters/${c.id}/body-candidates`, {body: {n: cands, max_usd: cap}})).job));
  };
  const runRigCheck = () => act.run('rig', async () => setFollow((await api(`/characters/${c.id}/rig-check`, {method: 'POST'})).job));
  const everyPose = c.assets.filter((a: any) => a.kind === 'pose');
  const poses = visiblePoses(c.assets, allPoses);
  const refs = c.assets.filter((a: any) => a.kind === 'reference');
  const sheet = c.assets.find((a: any) => a.kind === 'sheet');
  const sample = c.assets.find((a: any) => a.kind === 'voice-sample');
  const reviewing = poses.filter((p: any) => p.status === 'review').length;
  const candidates = poses.filter((p: any) => isCandidate(p, c.assets)).length;
  const upload = (file?: File) => file && act.run('upload', () => new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => api(`/characters/${c.id}/reference`, {body: {png_base64: String(r.result).split(',')[1]}}).then(resolve, reject);
    r.onerror = () => reject(new Error('could not read the file'));
    r.readAsDataURL(file);
  }));
  if (editing) return <CharacterForm initial={c} onDone={() => { setEditing(false); reload(); }} />;
  const rig = rigStatus(c);
  const approvedN = everyPose.filter((p: any) => p.status === 'approved').length;
  const live = (used || []).filter((e: any) => e.live);
  const header = (
    <div className="row" style={{alignItems: 'center', gap: 10, cursor: 'pointer'}} onClick={() => setOpen(!open)} role="button" aria-expanded={open}>
      {selectable && <input type="checkbox" checked={!!selected} onClick={e => e.stopPropagation()} onChange={e => onSelect?.(e.target.checked)} aria-label={`select ${c.name}`} />}
      {thumbOf(c) ? <img src={thumbOf(c)!} alt="" loading="lazy" style={{width: 40, height: 56, objectFit: 'contain', borderRadius: 4, background: 'var(--panel, #f4f4f4)'}} />
        : <div style={{width: 40, height: 56, borderRadius: 4, background: 'var(--panel, #eee)'}} />}
      <div style={{flex: 1, minWidth: 0}}><strong>{c.name}</strong> <span className="muted small mono">{c.key}</span>
        <div className="row small" style={{gap: 4, flexWrap: 'wrap'}}>
          <span className={`badge ${c.art_status === 'approved' ? 'good' : c.art_status === 'none' ? 'bad' : 'warn'}`}>art: {c.art_status}</span>
          <span className={`badge ${rig.tone}`}>{rig.label}</span>
          <span className="muted">{approvedN} approved pose(s){reviewing ? ` · ${reviewing} to review` : ''} · {live.length ? `in ${live.length} live episode(s)` : 'not in a live episode'}</span></div></div>
      <span className="muted small">{open ? '▾' : '▸'}</span>
    </div>);
  if (!open) return <div className="card">{header}</div>;
  return (
    <div className="card stack">
      {header}
      <div className="spread">
        <div><h2 style={{marginBottom: 2}}>{c.name} <span className="muted small mono">{c.key}</span></h2>
          <div className="row small"><span className={`badge ${c.art_status === 'approved' ? 'good' : c.art_status === 'none' ? 'bad' : 'warn'}`}>art: {c.art_status}</span>
            <span className="badge">{c.scope === 'episode' ? `from episode ${c.episode_id}` : 'recurring cast'}</span>{c.locked && <span className="badge">approved artwork · locked</span>}</div></div>
        <span className="row" style={{gap: 4}}><button className="btn sm" onClick={() => setEditing(true)}>{c.locked ? 'Set voice' : 'Edit'}</button>
          {!c.locked && <DeleteButton kind="character" id={c.id} label={c.name} onDone={reload} />}</span>
      </div>
      <ErrorBox error={act.error} />
      {follow && <div className={`small ${follow.status === 'failed' ? 'alert bad' : 'muted'}`} role="status">{jobText(follow)}</div>}
      <p className="small">{c.description || <span className="muted">No description.</span>}</p>
      {c.visual_description && <p className="small muted">Look: {c.visual_description}</p>}
      {!c.locked && <div className="row small" style={{gap: 6}}>
        {c.episode_id && <button className="btn sm" disabled={!!act.busy} onClick={() => act.run('look', () => api(`/characters/${c.id}/look/from-notes`, {method: 'POST'}))}>Write the look from the video notes (free)</button>}
        <button className="btn sm" disabled={!!act.busy} onClick={() => act.run('look-ai', () => api(`/characters/${c.id}/look/write`, {method: 'POST'}))}>Write the look (AI writer)</button>
        <span className="muted">Then edit it. The rig rules (single-line black limbs, both hands visible, sleeveless, no pockets) are always added by the studio.</span></div>}
      <div className="small"><strong>Expressions usable in scripts:</strong> {Object.keys(c.expressions).join(', ') || <span className="muted">none yet</span>}</div>
      {sheet && <div><strong className="small">Expression sheet</strong> <span className={`badge ${sheet.status === 'approved' ? 'good' : sheet.status === 'review' ? 'warn' : 'bad'}`}>{sheet.status}</span>
        <a href={sheet.url} target="_blank" rel="noreferrer"><img className="scene-img" style={{marginTop: 6}} src={sheet.url} alt={`${c.name} expression sheet`} loading="lazy" /></a></div>}
      {!c.locked && reviewing > 0 && (
        <div className="alert warn row" style={{justifyContent: 'space-between'}}><span>{reviewing} pose(s) await your review{candidates ? `, ${candidates} of them candidate(s) to replace an approved pose` : ''}. Only approved poses are used in production.
          {candidates > 0 && <> Approve sheet also decides the candidates (one approved pose per expression, the last one wins): approve or reject candidates one by one first.</>}</span>
          <span className="row"><button className="btn sm good" disabled={!!act.busy} onClick={() => act.run('ok', () => api(`/characters/${c.id}/sheet/decision`, {body: {decision: 'approve'}}))}>Approve sheet</button>
            <button className="btn sm danger" disabled={!!act.busy} onClick={() => act.run('no', () => api(`/characters/${c.id}/sheet/decision`, {body: {decision: 'reject'}}))}>Reject sheet</button></span></div>)}
      {poses.length > 0 && <div className="poses">{poses.map((p: any) => (
        <div key={p.id} className="pose">
          <a href={p.url} target="_blank" rel="noreferrer"><img src={p.url} alt={`${c.name} ${p.expression}`} loading="lazy" /></a>
          <div className="small">{p.expression}{p.made_by === 'face' ? <span className="badge good" title="Drawn by code on the approved neutral: only the face changes">face</span>
            : p.made_by === 'reference' ? <span className="badge good" title="Your own drawing, used unchanged">your drawing</span>
            : <span className="badge warn" title="Drawn separately by an image generator: hair, clothes or colours can differ">AI-drawn</span>}</div>
          <span className={`badge ${p.status === 'approved' ? 'good' : p.status === 'rejected' ? 'bad' : 'warn'}`}>{isCandidate(p, c.assets) ? 'Candidate' : p.status}</span>
          {!c.locked && (() => { const r = poseRigText(p, c.rig_check_job); return r && <div className={`small ${r.tone}`} style={{marginTop: 4}} title={p.rig_check?.message}>{r.text}</div>; })()}
          {!c.locked && <div style={{marginTop: 4}}><DeleteButton kind="pose" id={p.id} label={`${c.name}'s ${p.expression} pose (${p.status})`} onDone={reload} /></div>}
          {!c.locked && p.status === 'review' && <div className="row" style={{justifyContent: 'center', marginTop: 4}}>
            <button className="btn sm good" onClick={() => act.run('a', () => api(`/character-assets/${p.id}/decision`, {body: {decision: 'approve'}}))}>{p.expression === 'neutral' && hasNeutral ? 'Replace the approved neutral' : 'Approve'}</button>
            <button className="btn sm danger" onClick={() => act.run('r', () => api(`/character-assets/${p.id}/decision`, {body: {decision: 'reject'}}))}>Reject</button></div>}
        </div>))}</div>}
      {!c.locked && everyPose.some((p: any) => p.expression === 'neutral' && p.status === 'approved') && (
        <div className="row small" style={{gap: 6}}>
          <button className="btn sm" disabled={!!act.busy} title="Only the face changes (brows, eyelids, mouth); every other pixel is the approved neutral, so the character cannot drift"
            onClick={() => {
              const v = window.prompt('Face expressions to draw on the approved neutral (comma separated). Available: smug, shocked, angry, deadpan, worried, happy, laughing', 'smug, shocked, angry, deadpan, worried, happy');
              if (v) act.run('faces', async () => setFollow(await api(`/characters/${c.id}/face-expressions`, {body: {expressions: v.split(',').map(x => x.trim()).filter(Boolean)}})));
            }}>Face expressions from the neutral</button>
          <span className="muted">$0, no AI: only the face changes</span></div>)}
      {!c.locked && (() => {
        const inReview = everyPose.filter((p: any) => p.status === 'review');
        const faces = inReview.filter((p: any) => p.made_by === 'face');
        const others = inReview.filter((p: any) => p.made_by === 'generator');
        if (!faces.length && !others.length) return null;
        return (<div className="row small" style={{gap: 6}}>
          {faces.length > 0 && <button className="btn sm good" disabled={!!act.busy}
            onClick={() => act.run('faces-ok', () => api(`/characters/${c.id}/face-expressions/approve-all`, {method: 'POST'}))}>
            Approve all face expressions ({faces.length})</button>}
          {others.length > 0 && <button className="btn sm danger" disabled={!!act.busy}
            onClick={() => { if (window.confirm(`Reject the ${others.length} other pose(s) in review (drawn separately by an image generator, so they drift)? Approved poses are not touched; rejected ones stay in the history.`))
              act.run('others-no', () => api(`/characters/${c.id}/poses/reject-other-review`, {method: 'POST'})); }}>
            Reject other poses in review ({others.length})</button>}
        </div>);
      })()}
      <StickMaster characterId={c.id} name={c.name} locked={c.locked} />
      {c.art_status === 'approved' && <HeadAngles characterId={c.id} locked={c.locked} />}
      {!c.locked && needsRigCheck(c) && <div className="row small" style={{gap: 6}}><span className="muted">Some approved poses have not been rig-checked.</span>
        <button className="btn sm" disabled={!!act.busy} onClick={runRigCheck}>Run rig check</button><span className="muted">free; never changes an approval</span></div>}
      {everyPose.length > poses.length || allPoses ? <label className="small row" style={{gap: 6}}><input type="checkbox" checked={allPoses} onChange={e => setAllPoses(e.target.checked)} />
        Show all poses ({everyPose.length - visiblePoses(c.assets, false).length} superseded, rejected or extra hidden)</label> : null}
      {!c.locked && (
        <div className="stack">
          <div className="row">{refs.map((r: any) => <span key={r.id} className="small"><a href={r.url} target="_blank" rel="noreferrer">reference</a>
            {!c.locked && !everyPose.some((p: any) => p.expression === 'neutral' && ['review', 'approved'].includes(p.status)) &&
              <> <button className="btn sm" disabled={!!act.busy} title="Use this exact drawing as the neutral pose (no redraw); it then waits for your approval"
                onClick={() => act.run('refpose', () => api(`/characters/${c.id}/reference-as-pose`, {body: {asset_id: r.id}}))}>Use as neutral pose</button></>}</span>)}
            <label className="btn sm" style={{display: 'inline-block', margin: 0}}>Upload visual reference<input type="file" accept="image/png,image/jpeg" hidden onChange={e => upload(e.target.files?.[0])} /></label></div>
          <div><label htmlFor={`exprs-${c.id}`}>Expression sheet (comma separated; neutral is drawn first and anchors the rest; one image each, started only by you)</label>
            <div className="row"><input id={`exprs-${c.id}`} style={{flex: 1}} value={exprs} onChange={e => setExprs(e.target.value)} />
              <button className="btn primary" disabled={!!act.busy || !exprList.length} onClick={genSheet}>Generate sheet</button></div>
            <span className="muted small">{imageCost(exprList.length)}{plan ? ` · default: ${plan.reason}` : ''}</span></div>
          <div className="row small" style={{gap: 6, alignItems: 'center'}}><strong>Body pose candidates</strong>
            <input type="number" min={1} max={6} value={cands} onChange={e => setCands(Math.max(1, Math.min(6, Number(e.target.value) || 1)))} style={{width: 56}} aria-label="number of candidates" />
            <span>cap $</span><input type="number" min={0.1} max={10} step={0.1} value={cap} onChange={e => setCap(Number(e.target.value) || 1)} style={{width: 64}} aria-label="cost cap in dollars" />
            <button className="btn sm" disabled={!!act.busy} onClick={genCands}>Generate candidates</button>
            <span className="muted">{imageCost(cands)}; each is rig-checked and only passing ones are shown.</span></div>
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
  const {data: use, reload: reloadUse} = useApi<any>('/characters/usage', 30000);
  const {data: episodes} = useApi<any[]>('/episodes');
  const [creating, setCreating] = useState(false);
  const [checkNote, setCheckNote] = useState('');
  const [search, setSearch] = useState('');
  const [story, setStory] = useState<number | null>(null);
  const [cleanup, setCleanup] = useState(false);
  const [picked, setPicked] = useState<number[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const act = useAction(() => { reload(); reloadUse(); });
  const usage = use?.usage || {};
  const groups = groupCharacters(data || [], usage, use?.archived || [], story, search);
  const live = (episodes || []).filter((e: any) => e.stage !== 'published');
  const checkAll = async () => {
    const r = await api('/characters/rig-check-all', {method: 'POST'});
    setCheckNote(`Rig check queued for ${r.queued.length} character(s)${r.already_running ? ` (${r.already_running} already running)` : ''}. Results appear on the pose cards; approvals are not changed.`);
    reload();
  };
  const chosen = (data || []).filter(c => picked.includes(c.id));
  const archive = () => {
    if (!window.confirm(`Archive ${chosen.length} character(s): ${chosen.map(c => c.name).join(', ')}? They are hidden here and can be restored.`)) return;
    act.run('archive', async () => { await api('/characters/archive', {body: {ids: picked}}); setPicked([]); });
  };
  const remove = () => {
    const names = chosen.map(c => c.name);
    if (!window.confirm(`Move ${names.length} character(s) to the Bin: ${names.join(', ')}? They are hidden everywhere and can be restored for 30 days.`)) return;
    // through the Bin like every other delete (restorable; removed for good only from the Bin)
    act.run('delete', async () => { for (const id of picked) await api('/bin/move', {body: {kind: 'character', ref: String(id)}}); setPicked([]); });
  };
  const card = (c: any) => {
    const can = cleanup && removable(c, usage);
    return <CharacterCard key={c.id} c={c} reload={reload} used={usage[c.key]} selectable={can} selected={picked.includes(c.id)}
      onSelect={v => setPicked(v ? [...picked, c.id] : picked.filter(x => x !== c.id))} />;
  };
  const section = (title: string, list: any[], empty: string) => (
    <><h2>{title} <span className="muted small">({list.length})</span></h2>
      {list.length ? <div className="grid cols-2" style={{marginBottom: 20}}>{list.map(card)}</div> : <p className="muted small">{empty}</p>}</>);
  return (
    <>
      <div className="spread"><div><h1>Characters</h1><p className="sub">No fixed cast: stories introduce the characters they need. Approve their expression sheets, then keep the ones you want for future stories.</p></div>
        <div className="row"><button className="btn" title="Checks that the acting rig can be built from every approved pose (informational: approvals are never changed)" onClick={() => checkAll().catch(e => setCheckNote(e.message))}>Run rig check on all approved poses</button>
          {!creating && <button className="btn primary" onClick={() => setCreating(true)}>New character</button>}</div></div>
      {checkNote && <p className="small muted">{checkNote}</p>}
      <ErrorBox error={error || act.error} />
      <div style={{marginBottom: 16}}><CastLibrary /></div>
      {creating && <div style={{marginBottom: 16}}><CharacterForm initial={{}} onDone={() => { setCreating(false); reload(); }} /></div>}
      <div className="row" style={{gap: 8, marginBottom: 12, flexWrap: 'wrap'}}>
        <input type="search" placeholder="Search name or key" aria-label="Search characters" value={search} onChange={e => setSearch(e.target.value)} style={{flex: 1, minWidth: 180}} />
        <select aria-label="Story" value={story ?? ''} onChange={e => setStory(e.target.value ? Number(e.target.value) : null)}>
          <option value="">This story: choose an episode</option>
          {live.map((e: any) => <option key={e.id} value={e.id}>{e.title}</option>)}
        </select>
        <BulkDelete what="poses" label="Delete all rejected / never-approved poses" onDone={reload} />
        <button className={`btn ${cleanup ? 'primary' : ''}`} onClick={() => { setCleanup(!cleanup); setPicked([]); }}>{cleanup ? 'Done cleaning up' : 'Clean up'}</button>
      </div>
      {cleanup && <div className="alert row" style={{justifyContent: 'space-between'}}>
        <span className="small">Tick characters that no live episode uses (the others have no box). {picked.length} selected. Archive only hides a character on this page and keeps everything; Delete (on a card, or below) moves it to the Bin, where it is hidden everywhere and removed for good after 30 days.</span>
        <span className="row"><button className="btn sm" disabled={!picked.length || !!act.busy} onClick={archive}>Archive selected</button>
          <button className="btn sm danger" disabled={!picked.length || !!act.busy} onClick={remove}>Delete selected</button></span></div>}
      {data && !data.length && <Empty>No characters.</Empty>}
      {story != null && section("This story's characters", groups.story, 'No characters in this story yet.')}
      {section('Recurring cast', groups.recurring, 'No recurring characters match.')}
      {section('Everyone else', groups.others, 'No other characters match.')}
      {groups.archived.length > 0 && <><button className="btn sm" onClick={() => setShowArchived(!showArchived)}>{showArchived ? 'Hide' : 'Show'} archived ({groups.archived.length})</button>
        {showArchived && <div className="grid cols-2" style={{marginTop: 10}}>{groups.archived.map(c => (
          <div key={c.id} className="card row" style={{justifyContent: 'space-between'}}><span><strong>{c.name}</strong> <span className="muted small mono">{c.key}</span></span>
            <button className="btn sm" disabled={!!act.busy} onClick={() => act.run('restore', () => api('/characters/unarchive', {body: {ids: [c.id]}}))}>Restore</button></div>))}</div>}</>}
    </>
  );
}
