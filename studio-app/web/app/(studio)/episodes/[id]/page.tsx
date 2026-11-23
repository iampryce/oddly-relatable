'use client';
// The episode workspace (feat/episode-workspace, owner request 2026-11-22): everything about the episode on one page, in
// collapsible sections with a status badge each. Finished sections start collapsed; a section that blocks the next
// step is expanded and flagged, and the banner at the top says what is blocking the episode and where. Each section
// shows its own jobs (queued / running / failed with the message). The statuses come from /episodes/{id}/workspace.
import {use, useEffect, useState} from 'react';
import {api, when} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox, JobStatus, Pipeline, Stage} from '@/components/ui';
import {Scene, SceneEditor, SceneView} from '@/components/SceneEditor';
import SceneSetSelect from '@/components/SceneSetSelect';
import {BulkDelete, DeleteButton} from '@/components/BinButtons';
import CastPanel from '@/components/CastPanel';
import LineExpressions from '@/components/LineExpressions';
import {hookNote} from '@/lib/hookView';
import OutlineTab from '@/components/OutlineTab';
import SegmentsPanel from '@/components/SegmentsPanel';
import AudioPanel, {type AudioParts} from '@/components/AudioPanel';
import EpisodeSetPicker from '@/components/EpisodeSetPicker';
import {joinWithPrevious, splitScene} from '@/lib/audioScenes';
import {bannerText, isOpen, jobLine, TONE, type Section} from '@/lib/workspace';

const BUSY = ['audio_preparing', 'audio_transcribing', 'outline_generating', 'script_generating', 'storyboard_generating', 'producing', 'publishing'];
const AUDIO_ONLY = ['people', 'plan', 'lines', 'notes'];

function loadOpen(id: string): Record<string, boolean> {
  try { return JSON.parse(window.localStorage.getItem(`episode-open-${id}`) || '{}') || {}; } catch { return {}; }
}
function saveOpen(id: string, v: Record<string, boolean>) {
  try { window.localStorage.setItem(`episode-open-${id}`, JSON.stringify(v)); } catch { /* private window: not remembered */ }
}

export default function EpisodePage({params}: {params: Promise<{id: string}>}) {
  const {id} = use(params);
  const [poll, setPoll] = useState(5000);
  const {data: ep, error, reload} = useApi<any>(`/episodes/${id}`, poll);
  const {data: ws, reload: reloadWs} = useApi<any>(`/episodes/${id}/workspace`, poll);
  const {data: characters} = useApi<any[]>('/characters');
  const {data: settings} = useApi<any>('/settings');
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});
  const [seen, setSeen] = useState<Set<string>>(new Set());
  const reloadAll = async () => { await reload(); await reloadWs(); };
  const act = useAction(reloadAll);
  useEffect(() => { setOverrides(loadOpen(id)); }, [id]);
  useEffect(() => {
    if (!ep) return;
    const active = BUSY.includes(ep.stage) || ep.jobs.some((j: any) => j.status === 'queued' || j.status === 'running');
    setPoll(active ? 3000 : 15000);
  }, [ep]);
  // a section opened once stays mounted while collapsed (an unsaved edit in it survives closing it)
  useEffect(() => {
    if (!ws) return;
    setSeen(prev => {
      const next = new Set(prev);
      for (const s of ws.sections as Section[]) if (isOpen(s, overrides)) next.add(s.key);
      return next.size === prev.size ? prev : next;
    });
  }, [ws, overrides]);
  if (error && !ep) return <ErrorBox error={error} />;
  if (!ep || !characters) return <p className="muted">Loading…</p>;
  const can = (a: string) => ep.allowed_actions.includes(a);
  const ctx = {ep, can, act, characters, environments: settings?.environments || [], reload: reloadAll};
  // functional update: several quick toggles in a row each keep the others' state
  const toggle = (key: string, open: boolean) => setOverrides(prev => { const v = {...prev, [key]: open}; saveOpen(id, v); return v; });
  const goTo = (key: string) => { toggle(key, true); setTimeout(() => document.getElementById(`ws-${key}`)?.scrollIntoView({behavior: 'smooth', block: 'start'}), 50); };
  const banner = bannerText(ws);
  const sections: Section[] = (ws?.sections || []).filter((s: Section) => ep.source === 'audio' || !AUDIO_ONLY.includes(s.key));

  const body = (key: string, parts: AudioParts | null) => {
    const p = parts || ({} as AudioParts);
    switch (key) {
      case 'set': return <EpisodeSetPicker ep={ep} act={act} />;
      case 'people': return p.people || <p className="muted small">No per-person video notes: nobody to confirm.</p>;
      case 'plan': return p.plan || <p className="muted small">No video notes, so there is no Reference plan.</p>;
      case 'lines': return <>{p.recording}{p.lines}{p.tidy}</>;
      case 'notes': return p.notes || <p className="muted small">No video notes. Upload a video with "notes" ticked (Lines and speakers) to get them.</p>;
      case 'cast': return <>{p.cast}{ep.script ? <CastPanel episodeId={ep.id} onChange={reloadAll} />
        : <p className="muted small">{ep.source === 'audio' ? 'The poses each character needs are listed once the scenes are built.' : 'The cast comes from the script.'}</p>}</>;
      case 'script': return <>{ep.format === 'long' && <OutlineTab ep={ep} can={can} act={act} characters={characters} />}{p.scenes}<ScriptTab {...ctx} /></>;
      case 'storyboard': return <StoryboardTab {...ctx} />;
      case 'production': return <ProductionTab {...ctx} />;
      case 'review': return <ReviewTab {...ctx} />;
      case 'publishing': return <PublishTab {...ctx} />;
      default: return null;
    }
  };
  const render = (parts: AudioParts | null) => (
    <div className="stack">
      {sections.map(s => {
        const open = isOpen(s, overrides);
        const mounted = open || seen.has(s.key);
        return <WsSection key={s.key} s={s} open={open} onToggle={() => toggle(s.key, !open)} act={act}>{mounted ? body(s.key, parts) : null}</WsSection>;
      })}
      <WsSection s={{key: 'history', title: 'History', status: 'waiting', label: 'log', note: 'Decisions, script versions, activity and every file.', blocking: false, open: false, jobs: []}}
        open={!!overrides.history} onToggle={() => toggle('history', !overrides.history)} act={act}>{overrides.history ? <HistoryTab {...ctx} /> : null}</WsSection>
    </div>);
  return (
    <>
      <div className="spread">
        <div><h1>{ep.title} <DeleteButton kind="episode" id={ep.id} label={`episode ${ep.id} "${ep.title}"`} onDone={() => { window.location.href = '/bin'; }} /></h1><div className="row"><Stage stage={ep.stage} />{ep.format === 'long' && <span className="badge busy">long episode · 3 acts</span>}<span className="muted">Revision {ep.revision} · {ep.next_step}</span></div></div>
        <DialogueDisplay ep={ep} act={act} /><HookBanner ep={ep} act={act} />
      </div>
      <Pipeline stage={ep.stage} source={ep.source} />
      {ws && <div className={`alert ${banner.tone} ws-banner`} role="status">
        <strong>{ws.blocker ? 'What is blocking this episode' : ws.running?.length ? 'In progress' : 'Status'}:</strong> {banner.text}
        {ws.blocker && <> <button className="btn sm" onClick={() => goTo(ws.blocker.section)}>Go to {ws.blocker.title}</button></>}</div>}
      <ErrorBox error={act.error} />
      {ep.last_error && <div className="alert bad">{ep.last_error}</div>}
      {!ws ? <p className="muted">Loading the sections…</p>
        : ep.source === 'audio' ? <AudioPanel episodeId={ep.id} onChange={reloadAll} render={parts => render(parts)} /> : render(null)}
    </>
  );
}

// One collapsible section: its title, status badge, "blocking" flag and note in the header; its jobs at the top.
function WsSection({s, open, onToggle, act, children}: {s: Section; open: boolean; onToggle: () => void; act: ReturnType<typeof useAction>; children: React.ReactNode}) {
  return (
    <section id={`ws-${s.key}`} className={`card ws-section${s.blocking ? ' ws-blocking' : ''}`} aria-label={s.title}>
      <button type="button" className="ws-head" aria-expanded={open} onClick={onToggle}>
        <span className="ws-caret" aria-hidden>{open ? '▾' : '▸'}</span>
        <h2>{s.title}</h2>
        <span className={`badge ${TONE[s.status] || ''}`}>{s.label}</span>
        {s.blocking && <span className="badge bad">blocking</span>}
        <span className="muted small ws-note">{s.note}</span>
      </button>
      {s.jobs?.length > 0 && <div className="stack" style={{marginTop: 8}}>{s.jobs.map((j: any) => (
        <div key={j.id} className={`alert small ${j.status === 'failed' ? 'bad' : 'info'} row`} style={{justifyContent: 'space-between'}}>
          <span>{jobLine(j)}</span>
          {j.status === 'failed' && <button className="btn sm" disabled={!!act.busy} onClick={() => act.run('retry', () => api(`/jobs/${j.id}/retry`, {method: 'POST'}))}>Retry</button>}
        </div>))}</div>}
      <div className="ws-body" hidden={!open}>{children}</div>
    </section>);
}

// What the viewer sees of the dialogue in the next render (bubbles | none | captions).
function DialogueDisplay({ep, act}: {ep: any; act: ReturnType<typeof useAction>}) {
  const locked = ['producing', 'publishing'].includes(ep.stage);
  return (
    <div style={{minWidth: 220}}>
      <label htmlFor="dialogue-display">Dialogue on screen</label>
      <select id="dialogue-display" value={ep.dialogue_display || 'bubbles'} disabled={locked || !!act.busy}
              onChange={e => act.run('dialogue', () => api(`/episodes/${ep.id}/dialogue-display`, {method: 'PUT', body: {value: e.target.value}}))}>
        <option value="none">None (audio only)</option><option value="captions">Captions</option><option value="bubbles">Speech bubbles</option>
      </select>
      <div className="muted small">{locked ? 'Locked while rendering' : 'Applies to the next render'}</div>
    </div>
  );
}

// The "POV" hook banner (per episode; audio episodes start with it off): on or off, and its own text (empty: the
// script's hook). Applies to the stills and the next render.
function HookBanner({ep, act}: {ep: any; act: ReturnType<typeof useAction>}) {
  const locked = ['producing', 'publishing'].includes(ep.stage);
  const [text, setText] = useState<string>(ep.hook_text || '');
  useEffect(() => { setText(ep.hook_text || ''); }, [ep.hook_text]);
  const save = (enabled: boolean, t: string) => act.run('hook', () => api(`/episodes/${ep.id}/hook`, {method: 'PUT', body: {enabled, text: t}}));
  return (
    <div style={{minWidth: 260}}>
      <label className="row" style={{gap: 6}}><input type="checkbox" checked={!!ep.hook_banner} disabled={locked || !!act.busy}
        onChange={e => save(e.target.checked, text)} />Hook banner ("POV: ...")</label>
      {ep.hook_banner && <div className="row" style={{gap: 4}}>
        <input aria-label="hook banner text" value={text} maxLength={120} placeholder="the script's hook" disabled={locked || !!act.busy}
          onChange={e => setText(e.target.value)} />
        <button className="btn sm" disabled={locked || !!act.busy || text === (ep.hook_text || '')} onClick={() => save(true, text)}>Save</button></div>}
      <div className="muted small">{hookNote(ep, locked)}</div>
    </div>
  );
}

type Ctx = {ep: any; can: (a: string) => boolean; act: ReturnType<typeof useAction>; characters: any[]; environments: string[]; reload: () => unknown};

function lastJob(ep: any, kind: string, sceneId?: number) {
  return ep.jobs.find((j: any) => j.kind === kind && (sceneId === undefined || j.scene_id === sceneId));
}

function JobNote({job}: {job?: any}) {
  if (!job) return null;
  if (job.status === 'failed') return <div className="alert bad small">{job.kind} failed: {job.error}</div>;
  if (job.status === 'queued' || job.status === 'running') return <div className="alert info small">{job.kind.replace(/_/g, ' ')} {job.status}…</div>;
  return null;
}

// ------------------------------------------------------------------ script
const EMPTY_SCRIPT = (chars: any[]) => ({
  title: '', logline: '', hook: '', twist: '', interactive: {type: 'none'},
  characters: chars.slice(0, 1).map(c => ({key: c.key, role: ''})),
  scenes: [{id: 's1', heading: 'Scene 1', location: '', description: '', action: '', camera: '', lines: [{speaker: chars[0]?.key || '', text: '', expression: 'neutral', shot: 'wide'}]}],
});

function ScriptTab({ep, can, act, characters, environments}: Ctx) {
  const [draft, setDraft] = useState<any>(null);
  const [note, setNote] = useState('');
  const [instruction, setInstruction] = useState('');
  const [comment, setComment] = useState('');
  const s = ep.script?.content;
  const job = lastJob(ep, 'generate_act') || lastJob(ep, 'generate_script') || lastJob(ep, 'regenerate_section');
  const long = ep.format === 'long';
  const audio = ep.source === 'audio';   // Stage 2: scenes around the recorded dialogue (built in the Audio tab)
  const save = () => act.run('save', async () => { await api(`/episodes/${ep.id}/script`, {method: 'PUT', body: {content: draft, note}}); setDraft(null); });
  const regen = (section: string) => act.run('regen', () => api(`/episodes/${ep.id}/script/regenerate-section`, {body: {section, instruction}}));
  if (draft) {
    const set = (k: string, v: any) => setDraft((d: any) => ({...d, [k]: v}));
    const castKeys = draft.characters.map((c: any) => c.key);
    return (
      <div className="stack">
        <div className="card stack">
          <h2>Edit script</h2>
          <div className="grid cols-2">
            <div><label htmlFor="id-title-1">Title</label><input id="id-title-1" value={draft.title} onChange={e => set('title', e.target.value)} /></div>
            <div><label htmlFor="id-on-screen-hook-2">On-screen hook</label><input id="id-on-screen-hook-2" value={draft.hook} maxLength={60} onChange={e => set('hook', e.target.value)} /></div>
          </div>
          <div className="grid cols-2">
            <div><label htmlFor="id-logline-3">Logline</label><textarea id="id-logline-3" value={draft.logline} onChange={e => set('logline', e.target.value)} /></div>
            <div><label htmlFor="id-twist-4">Twist</label><textarea id="id-twist-4" value={draft.twist} onChange={e => set('twist', e.target.value)} /></div>
          </div>
          <div><label>Cast</label>
            {characters.map(c => (
              <label key={c.key} className="row" style={{fontWeight: 400, color: 'inherit'}}>
                <input type="checkbox" style={{width: 'auto'}} checked={castKeys.includes(c.key)}
                       onChange={e => set('characters', e.target.checked ? [...draft.characters, {key: c.key, role: ''}] : draft.characters.filter((x: any) => x.key !== c.key))} />
                {c.name}
              </label>))}
          </div>
          <div className="grid cols-3">
            <div><label htmlFor="id-interactive-5">Interactive</label>
              <select id="id-interactive-5" value={draft.interactive?.type || 'none'} onChange={e => set('interactive', e.target.value === 'none' ? {type: 'none'} : {type: e.target.value, question: draft.interactive?.question || '', options: draft.interactive?.options || ['', '']})}>
                <option value="none">No</option><option value="viewer-choice">Viewer choice</option><option value="poll">Question</option>
              </select></div>
            {draft.interactive?.type !== 'none' && <>
              <div><label htmlFor="id-question-6">Question</label><input id="id-question-6" value={draft.interactive.question} onChange={e => set('interactive', {...draft.interactive, question: e.target.value})} /></div>
              <div><label htmlFor="id-options-one-per-line-7">Options (one per line)</label><textarea id="id-options-one-per-line-7" value={draft.interactive.options.join('\n')} onChange={e => set('interactive', {...draft.interactive, options: e.target.value.split('\n')})} /></div>
            </>}
          </div>
        </div>
        {draft.scenes.map((sc: Scene, i: number) => (
          <div key={i} className="card">
            <div className="spread"><h3>Scene {i + 1}</h3>
              {!audio && <button className="btn sm danger" disabled={draft.scenes.length === 1} onClick={() => set('scenes', draft.scenes.filter((_: any, j: number) => j !== i))}>Remove scene</button>}
              {audio && <span className="row">
                {sc.lines.length > 1 && <select aria-label="Split this scene" value="" style={{width: 'auto'}} onChange={e => { const k = Number(e.target.value); if (k) setDraft((d: any) => ({...d, scenes: splitScene(d.scenes, i, k)})); }}>
                  <option value="">Split after line…</option>{sc.lines.slice(0, -1).map((l: any, k: number) => <option key={k} value={k + 1}>{l.line_id || k + 1}: {l.text.slice(0, 30)}</option>)}</select>}
                {i > 0 && <button className="btn sm" onClick={() => set('scenes', joinWithPrevious(draft.scenes, i))}>Join with the scene before</button>}
              </span>}</div>
            <SceneEditor scene={sc} characters={characters.filter(c => castKeys.includes(c.key))} environments={environments}
                         onChange={n => set('scenes', draft.scenes.map((x: any, j: number) => (j === i ? n : x)))} />
          </div>))}
        <div className="card row">
          {!audio && <button className="btn" onClick={() => set('scenes', [...draft.scenes, {id: `s${draft.scenes.length + 1}`, heading: `Scene ${draft.scenes.length + 1}`, location: '', description: '', action: '', camera: '', lines: [{speaker: castKeys[0] || '', text: '', expression: 'neutral', shot: 'wide'}]}])}>Add scene</button>}
          <input style={{flex: 1, minWidth: 200}} placeholder="What changed (optional)" value={note} onChange={e => setNote(e.target.value)} />
          <button className="btn primary" disabled={!!act.busy} onClick={save}>Save as new version</button>
          <button className="btn" onClick={() => setDraft(null)}>Cancel</button>
        </div>
      </div>
    );
  }
  return (
    <div className="stack">
      <JobNote job={job} />
      {!s && long ? (
        <div className="card stack">
          <h2>No scenes yet</h2>
          <p className="muted">Long episodes are written from the approved three-act outline (Outline tab), act by act.</p>
          {ep.stage === 'outline_approved' && <button className="btn primary" disabled={!!act.busy} onClick={() => act.run('dev', () => api(`/episodes/${ep.id}/script/generate`, {body: {}}))}>Develop scenes act by act</button>}
        </div>
      ) : !s && audio ? (
        <div className="card stack">
          <h2>No scenes yet</h2>
          <p className="muted">An audio episode's scenes are built around the recorded lines: label the speakers, set up the cast, then build the scenes (above).</p>
        </div>
      ) : !s ? (
        <div className="card stack">
          <h2>No script yet</h2>
          <p className="muted">Generate an original script from the idea with the configured AI writer, or write it yourself.</p>
          {ep.idea && <p><strong>Idea:</strong> {ep.idea.premise}</p>}
          <input placeholder="Extra direction for the writer (optional)" value={instruction} onChange={e => setInstruction(e.target.value)} />
          <div className="row">
            <button className="btn primary" disabled={!can('generate_script') || !!act.busy} onClick={() => act.run('gen', () => api(`/episodes/${ep.id}/script/generate`, {body: {instruction}}))}>Generate script</button>
            <button className="btn" disabled={!can('edit_script')} onClick={() => setDraft(EMPTY_SCRIPT(characters))}>Write it myself</button>
          </div>
        </div>
      ) : (
        <>
          <div className="card">
            <div className="spread">
              <div><h2 style={{marginBottom: 2}}>{s.title}</h2><div className="muted small">Version {ep.script.version} · {ep.script.source} · about {ep.script.estimated_seconds}s
                {ep.approved_script_version === ep.script.version && <> · <span className="badge good">approved</span></>}</div></div>
              <div className="row">
                <button className="btn" disabled={!can('edit_script')} onClick={() => setDraft(JSON.parse(JSON.stringify(s)))}>Edit</button>
                {!audio && <button className="btn" disabled={!can('generate_script') || !!act.busy} onClick={() => act.run('gen', () => api(`/episodes/${ep.id}/script/generate`, {body: {instruction}}))}>Regenerate all</button>}
              </div>
            </div>
            <div className="grid cols-3" style={{marginTop: 12}}>
              <div><strong>Logline</strong><div className="muted">{s.logline || '—'}</div></div>
              <div><strong>Hook</strong><div className="muted">{s.hook || '—'}</div></div>
              <div><strong>Twist</strong><div className="muted">{s.twist || '—'}</div></div>
            </div>
            {s.interactive?.type !== 'none' && <p><strong>Interactive:</strong> {s.interactive.question} — {s.interactive.options.join(' / ')}</p>}
            {s.new_characters?.length > 0 && <div className="alert info small"><strong>New characters in this story:</strong> {s.new_characters.map((c: any) => `${c.name} (${c.visual_description})`).join('; ')}. Their expression sheets are generated from the Cast panel below.</div>}
            <p className="small"><strong>Cast:</strong> {s.characters.map((c: any) => `${characters.find(x => x.key === c.key)?.name || c.key}${c.role ? ` (${c.role})` : ''}`).join(', ')}</p>
          </div>
          {(ep.script.warnings || []).map((w: string, i: number) => <div key={i} className="alert warn small">{w}</div>)}
          {s.scenes.map((sc: any, i: number) => (
            <div key={sc.id} className="stack">
            {long && sc.act !== s.scenes[i - 1]?.act && (
              <div className="spread" style={{marginTop: 8}}><h2 style={{margin: 0}}>Act {sc.act}</h2>
                <button className="btn sm" disabled={!can('regenerate_section') || !!act.busy} onClick={() => regen(`act:${sc.act}`)}>Rewrite act {sc.act}</button></div>)}
            <div className="card">
              <div className="spread"><h3>{sc.heading}</h3>
                {!audio && <button className="btn sm" disabled={!can('regenerate_section') || !!act.busy} onClick={() => regen(`scene:${sc.id}`)}>Regenerate this scene</button>}</div>
              <SceneView scene={sc} characters={characters} />
            </div>
            </div>))}
          {audio && <div className="alert info small">The dialogue comes from the recording. Scenes are runs of recorded lines (a cut falls only between two lines). Edit to change headings, expressions and shots or to join scenes; to rebuild the scenes from the recording, use "Rebuild scenes from audio" above (after the script is approved: it discards the storyboard and the script approval; poses, sets and the Reference plan stay).</div>}
          {can('regenerate_section') && !audio && (
            <div className="card row">
              <input style={{flex: 1, minWidth: 220}} placeholder="Instruction for regeneration, e.g. 'make the twist darker'" value={instruction} onChange={e => setInstruction(e.target.value)} />
              {['title', 'hook', 'twist'].map(x => <button key={x} className="btn sm" disabled={!!act.busy} onClick={() => regen(x)}>Regenerate {x}</button>)}
            </div>)}
          {can('approve_script') && (
            <div className="card stack">
              <h2>Your decision</h2>
              <textarea placeholder="Comment (optional for approval, recommended for rejection)" value={comment} onChange={e => setComment(e.target.value)} />
              <div className="row">
                <button className="btn good" disabled={!!act.busy} onClick={() => act.run('approve', () => api(`/episodes/${ep.id}/script/approve`, {body: {comment}}))}>Approve script</button>
                <button className="btn danger" disabled={!!act.busy || !comment} onClick={() => act.run('reject', () => api(`/episodes/${ep.id}/script/reject`, {body: {comment}}))}>Reject (keep editing)</button>
              </div>
            </div>)}
          {ep.stage === 'script_approved' && <div className="alert good">Script approved. Continue in the Storyboard section.</div>}
        </>)}
    </div>
  );
}

// ------------------------------------------------------------------ storyboard
function StoryboardTab({ep, can, act, characters, environments, reload}: Ctx) {
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState<Scene | null>(null);
  const [instruction, setInstruction] = useState('');
  const [marked, setMarked] = useState<number[]>([]);
  const [comment, setComment] = useState('');
  const gen = lastJob(ep, 'generate_storyboard');
  return (
    <div className="stack">
      <JobNote job={gen} />
      {can('generate_storyboard') && (
        <div className="card spread"><div><h2 style={{marginBottom: 2}}>{ep.scenes.length ? 'Rebuild storyboard' : 'Build the storyboard'}</h2>
          <span className="muted">Scene breakdown from the approved script, with renderer stills for each scene.</span></div>
          <button className="btn primary" disabled={!!act.busy} onClick={() => act.run('sb', () => api(`/episodes/${ep.id}/storyboard/generate`, {method: 'POST'}))}>{ep.scenes.length ? 'Rebuild from script' : 'Generate storyboard'}</button></div>)}
      {!ep.scenes.length && !can('generate_storyboard') && <p className="muted">The storyboard becomes available once the script is approved.</p>}
      {ep.scenes.map((sc: any) => {
        const ref = lastJob(ep, 'scene_reference', sc.id) || lastJob(ep, 'regenerate_scene', sc.id);
        return (
          <div key={sc.id} className="card">
            <div className="spread">
              <div className="row"><h3 style={{margin: 0}}>Scene {sc.position}: {sc.heading}</h3>
                <span className={`badge ${sc.status === 'needs_revision' ? 'bad' : sc.status === 'ready' ? 'good' : ''}`}>{sc.status.replace('_', ' ')}</span>
                <span className="muted small">{sc.location || 'default set'} · {sc.characters.map((k: string) => characters.find(c => c.key === k)?.name || k).join(', ')}</span></div>
              <div className="row">
                {can('reject_storyboard') && <label className="row small" style={{fontWeight: 400}}><input type="checkbox" style={{width: 'auto'}} checked={marked.includes(sc.id)} onChange={e => setMarked(e.target.checked ? [...marked, sc.id] : marked.filter(x => x !== sc.id))} />mark for revision</label>}
                <button className="btn sm" disabled={!can('edit_scene')} onClick={() => { setEditing(sc.id); setDraft({...sc}); }}>Edit</button>
                {ep.source !== 'audio' && <button className="btn sm" disabled={!can('regenerate_scene') || !!act.busy} onClick={() => act.run('rs', () => api(`/episodes/${ep.id}/scenes/${sc.id}/regenerate`, {body: {instruction: instruction || sc.revision_note}}))}>Regenerate</button>}
                <button className="btn sm" disabled={!can('scene_reference') || !!act.busy} onClick={() => act.run('ref', () => api(`/episodes/${ep.id}/scenes/${sc.id}/reference`, {method: 'POST'}))}>Refresh stills</button>
              </div>
            </div>
            {sc.revision_note && <div className="alert warn small">Revision note: {sc.revision_note}</div>}
            <JobNote job={ref} />
            <SceneSetSelect ep={ep} scene={sc} onChange={reload} />
            <div className="grid cols-2" style={{marginTop: 10}}>
              <div>{editing === sc.id && draft ? (
                <div className="stack">
                  <SceneEditor scene={draft} onChange={setDraft} characters={characters} environments={environments} />
                  <div className="row">
                    <button className="btn primary" disabled={!!act.busy} onClick={() => act.run('save', async () => { await api(`/episodes/${ep.id}/scenes/${sc.id}`, {method: 'PUT', body: draft}); setEditing(null); await api(`/episodes/${ep.id}/scenes/${sc.id}/reference`, {method: 'POST'}); })}>Save scene</button>
                    <button className="btn" onClick={() => setEditing(null)}>Cancel</button>
                  </div>
                </div>) : <><SceneView scene={sc} characters={characters} /><LineExpressions ep={ep} scene={sc} characters={characters} act={act} /></>}</div>
              <div>{sc.reference ? <a href={sc.reference.url} target="_blank" rel="noreferrer"><img className="scene-img" src={sc.reference.url} alt={`Scene ${sc.position} stills`} /></a>
                : <div className="card empty small">No stills yet{ref?.status === 'failed' ? ' (see the error above)' : ''}</div>}</div>
            </div>
          </div>);
      })}
      {can('regenerate_scene') && <div className="card"><label htmlFor="id-instruction-used-when-re-8">Instruction used when regenerating a scene</label><input id="id-instruction-used-when-re-8" value={instruction} onChange={e => setInstruction(e.target.value)} placeholder="e.g. bigger reaction before the twist" /></div>}
      {can('approve_storyboard') && (
        <div className="card stack">
          <h2>Your decision</h2>
          <textarea placeholder="Comment" value={comment} onChange={e => setComment(e.target.value)} />
          <div className="row">
            <button className="btn good" disabled={!!act.busy} onClick={() => act.run('ok', () => api(`/episodes/${ep.id}/storyboard/approve`, {body: {comment}}))}>Approve storyboard</button>
            <button className="btn danger" disabled={!!act.busy || !comment || !marked.length} onClick={() => act.run('no', async () => { await api(`/episodes/${ep.id}/storyboard/reject`, {body: {comment, scene_ids: marked}}); setMarked([]); })}>Send marked scenes back ({marked.length})</button>
          </div>
        </div>)}
      {ep.stage === 'storyboard_approved' && <div className="alert good">Storyboard approved. Start production in the Production section.</div>}
    </div>
  );
}

// ------------------------------------------------------------------ production
function JobRow({job, act}: {job: any; act: Ctx['act']}) {
  const [log, setLog] = useState<string | null>(null);
  const stages = job.progress?.stages || [];
  return (
    <>
      <tr>
        <td className="mono">#{job.id}</td><td>{job.kind.replace(/_/g, ' ')}{job.scene_id ? <span className="muted small"> · scene {job.scene_id}</span> : null}</td>
        <td><JobStatus status={job.status} />{job.attempts > 1 && <span className="muted small"> · attempt {job.attempts}</span>}</td>
        <td className="small">{stages.length ? stages.map((s: any) => `${s.stage} ${s.status === 'done' ? '✓' : s.status === 'failed' ? '✕' : '…'}`).join(' · ') : job.result?.skipped ? <span className="muted">Skipped: {job.result.skipped}</span> : ''}
          {job.error && <div style={{color: 'var(--bad)'}}>{job.error}</div>}</td>
        <td className="muted small">{when(job.finished_at || job.started_at || job.created_at)}</td>
        <td><div className="row" style={{justifyContent: 'flex-end'}}>
          <button className="btn sm" onClick={async () => setLog(log === null ? (await api(`/jobs/${job.id}`)).log || '(empty log)' : null)}>{log === null ? 'Log' : 'Hide log'}</button>
          {job.status === 'failed' && <button className="btn sm primary" disabled={!!act.busy} onClick={() => act.run('retry', () => api(`/jobs/${job.id}/retry`, {method: 'POST'}))}>Retry</button>}
        </div></td>
      </tr>
      {log !== null && <tr><td colSpan={6}><pre className="log">{log}</pre></td></tr>}
    </>
  );
}

function ProductionTab({ep, can, act}: Ctx) {
  const prodJobs = ep.jobs.filter((j: any) => ['scene_prepare', 'scene_voice', 'audio_slice', 'render_episode', 'plan_segments', 'render_segment', 'join_segments'].includes(j.kind) && j.revision === ep.revision);
  const done = prodJobs.filter((j: any) => j.status === 'succeeded').length;
  return (
    <div className="stack">
      {can('start_production') && (<>
        <div className="card spread"><div><h2 style={{marginBottom: 2}}>Start production</h2><span className="muted">Scene preparation, voice, then the full render with QA.</span></div>
          <button className="btn primary" disabled={!!act.busy || !ep.set_id} title={ep.set_id ? '' : 'Choose the episode\'s set first'} onClick={() => act.run('start', () => api(`/episodes/${ep.id}/production/start`, {method: 'POST'}))}>Start production</button></div>
        {!ep.set_id && <div className="alert warn small">Choose this episode's set first (the Set section): there is no default set.</div>}</>)}
      {ep.stage === 'production_failed' && <div className="alert bad">A production job failed. Fix the cause (see the error and log), then retry only that job.</div>}
      {ep.format === 'long' && <SegmentsPanel ep={ep} act={act} />}
      {ep.scenes.length > 0 && (
        <div className="card">
          <h2>Scenes</h2>
          <div className="table-wrap"><table><thead><tr><th>Scene</th><th>Production</th><th></th></tr></thead><tbody>
            {ep.scenes.map((sc: any) => (
              <tr key={sc.id}><td>{sc.position}. {sc.heading}</td>
                <td><span className={`badge ${({done: 'good', ready: 'good', failed: 'bad', running: 'busy'} as any)[sc.production_status] || ''}`}>{sc.production_status}</span></td>
                <td style={{textAlign: 'right'}}>{can('rerun_scene') && ep.stage === 'production_failed' && <button className="btn sm" onClick={() => act.run('rerun', () => api(`/episodes/${ep.id}/scenes/${sc.id}/rerun`, {method: 'POST'}))}>Re-run scene</button>}</td></tr>))}
          </tbody></table></div>
        </div>)}
      <div className="card">
        <div className="spread"><h2>Jobs (revision {ep.revision})</h2>{prodJobs.length > 0 && <span className="muted small">{done} of {prodJobs.length} done</span>}</div>
        {prodJobs.length > 0 && <div className="progress" style={{marginBottom: 12}}><div style={{width: `${(100 * done) / Math.max(1, prodJobs.length)}%`}} /></div>}
        {!prodJobs.length ? <p className="muted">No production jobs for this revision yet.</p> : (
          <div className="table-wrap"><table><thead><tr><th>Job</th><th>Step</th><th>Status</th><th>Progress / error</th><th>Time</th><th></th></tr></thead>
            <tbody>{prodJobs.map((j: any) => <JobRow key={j.id} job={j} act={act} />)}</tbody></table></div>)}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ review
function ReviewTab({ep, can, act}: Ctx) {
  const [target, setTarget] = useState('scenes');
  const [scenes, setScenes] = useState<number[]>([]);
  const [segs, setSegs] = useState<number[]>([]);
  const [comment, setComment] = useState('');
  const files = ep.assets.filter((a: any) => a.revision === ep.revision && ['report', 'manifest', 'storyboard-sheet', 'audio'].includes(a.kind));
  return (
    <div className="stack">
      {!ep.video ? <div className="card empty">No video for revision {ep.revision} yet.</div> : (
        <div className="grid cols-2">
          <div className="card"><video src={ep.video.url} controls preload="metadata" /><p className="muted small">{ep.video.label} · {(ep.video.size / 1e6).toFixed(1)} MB</p></div>
          <div className="stack">
            <div className="card"><h2>Production files</h2>
              <ul>{files.map((a: any) => <li key={a.id}><a href={a.url} target="_blank" rel="noreferrer">{a.label}</a> <span className="muted small">{a.kind}</span></li>)}</ul></div>
            {can('approve_video') && (
              <div className="card stack">
                <h2>Your decision</h2>
                <textarea placeholder="Comment" value={comment} onChange={e => setComment(e.target.value)} />
                <button className="btn good" disabled={!!act.busy} onClick={() => act.run('ok', () => api(`/episodes/${ep.id}/video/approve`, {body: {comment}}))}>Approve final video</button>
                <hr style={{border: 0, borderTop: '1px solid var(--line)', width: '100%'}} />
                <h3>Or request a revision</h3>
                <select value={target} onChange={e => setTarget(e.target.value)}>
                  <option value="scenes">Re-produce selected scenes</option><option value="storyboard">Change the storyboard (selected scenes marked)</option><option value="script">Rewrite the script</option>
                  {ep.format === 'long' && <option value="segments">Re-render selected segments</option>}
                </select>
                {target === 'segments' && (ep.segments || []).map((g: any) => (
                  <label key={g.id} className="row" style={{fontWeight: 400, color: 'inherit'}}><input type="checkbox" style={{width: 'auto'}} checked={segs.includes(g.position)}
                    onChange={e => setSegs(e.target.checked ? [...segs, g.position] : segs.filter(x => x !== g.position))} />Segment {g.position} ({g.seconds.toFixed(0)} s: {g.parts.map((p: any) => p.scene).join(', ')})</label>))}
                {target !== 'script' && target !== 'segments' && ep.scenes.map((sc: any) => (
                  <label key={sc.id} className="row" style={{fontWeight: 400, color: 'inherit'}}><input type="checkbox" style={{width: 'auto'}} checked={scenes.includes(sc.id)}
                    onChange={e => setScenes(e.target.checked ? [...scenes, sc.id] : scenes.filter(x => x !== sc.id))} />Scene {sc.position}: {sc.heading}</label>))}
                <button className="btn danger" disabled={!!act.busy || !comment || (target === 'scenes' && !scenes.length) || (target === 'segments' && !segs.length)}
                        onClick={() => act.run('rev', () => api(`/episodes/${ep.id}/video/request-revision`, {body: {target, comment, scene_ids: scenes, segment_positions: segs}}))}>Request revision</button>
              </div>)}
            {['final_approved', 'publishing', 'published', 'publish_failed'].includes(ep.stage) && <div className="alert good">Final video approved. Continue in Publishing.</div>}
          </div>
        </div>)}
    </div>
  );
}

// ------------------------------------------------------------------ publishing
function PublishTab({ep, can, act}: Ctx) {
  const p = ep.publish;
  const [f, setF] = useState<any>(null);
  const [confirm, setConfirm] = useState('');
  // Reload the form whenever the saved record changes (after Save, approval or a new revision).
  const saved = JSON.stringify(p);
  useEffect(() => { if (p) setF({...p, tags: (p.tags || []).join(', ')}); }, [saved]);  // eslint-disable-line react-hooks/exhaustive-deps
  if (!p) return <div className="card empty">Publishing opens after you approve the final video.</div>;
  const approvedNow = p.status === 'approved' && p.approved_revision === ep.revision && p.approved_video_asset_id === ep.video?.id;
  const images = ep.assets.filter((a: any) => a.content_type.startsWith('image/'));
  const save = () => act.run('save', async () => {
    const body = {title: f.title, description: f.description, tags: f.tags.split(',').map((t: string) => t.trim()).filter(Boolean), category_id: f.category_id,
                  privacy: f.privacy, made_for_kids: f.made_for_kids, thumbnail_asset_id: f.thumbnail_asset_id || null};
    await api(`/episodes/${ep.id}/publish`, {method: 'PUT', body});
  });
  return (
    <div className="grid cols-2">
      <div className="card stack">
        <h2>YouTube details</h2>
        {f && <>
          <div><label htmlFor="id-title-9">Title</label><input id="id-title-9" value={f.title} maxLength={100} disabled={!can('edit_publish')} onChange={e => setF({...f, title: e.target.value})} /></div>
          <div><label htmlFor="id-description-10">Description</label><textarea id="id-description-10" value={f.description} disabled={!can('edit_publish')} onChange={e => setF({...f, description: e.target.value})} /></div>
          <div><label htmlFor="id-tags-comma-separated-11">Tags (comma separated)</label><input id="id-tags-comma-separated-11" value={f.tags} disabled={!can('edit_publish')} onChange={e => setF({...f, tags: e.target.value})} /></div>
          <div className="grid cols-2">
            <div><label htmlFor="id-visibility-12">Visibility</label><select id="id-visibility-12" value={f.privacy} disabled={!can('edit_publish')} onChange={e => setF({...f, privacy: e.target.value})}>
              <option value="private">Private</option><option value="unlisted">Unlisted</option><option value="public">Public</option></select></div>
            <div><label htmlFor="id-thumbnail-13">Thumbnail</label><select id="id-thumbnail-13" value={f.thumbnail_asset_id || ''} disabled={!can('edit_publish')} onChange={e => setF({...f, thumbnail_asset_id: e.target.value ? Number(e.target.value) : null})}>
              <option value="">YouTube default</option>{images.map((a: any) => <option key={a.id} value={a.id}>{a.label} (#{a.id})</option>)}</select></div>
          </div>
          <label className="row" style={{fontWeight: 400, color: 'inherit'}}><input type="checkbox" style={{width: 'auto'}} checked={f.made_for_kids} disabled={!can('edit_publish')} onChange={e => setF({...f, made_for_kids: e.target.checked})} />Made for kids</label>
          {can('edit_publish') && <button className="btn" disabled={!!act.busy} onClick={save}>Save details</button>}
        </>}
      </div>
      <div className="stack">
        <div className="card">
          <h2>Preview</h2>
          <p><strong>{p.title || '(no title)'}</strong></p>
          <p className="muted small" style={{whiteSpace: 'pre-wrap'}}>{p.description || '(no description)'}</p>
          <p className="small">{p.tags.map((t: string) => `#${t}`).join(' ')}</p>
          <p className="small">Visibility: <strong>{p.privacy}</strong> · Status: <span className={`badge ${p.status === 'published' ? 'good' : p.status === 'failed' ? 'bad' : approvedNow ? 'good' : 'warn'}`}>{p.status}</span></p>
          {p.youtube_url && <p>Published: <a href={p.youtube_url} target="_blank" rel="noreferrer">{p.youtube_url}</a></p>}
          {p.error && <div className="alert bad small">{p.error}</div>}
        </div>
        {can('approve_publish') && !approvedNow && (
          <div className="card stack">
            <h2>Approve publication</h2>
            <p className="muted small">Nothing is uploaded until you approve these exact details for this exact video. Editing the details afterwards withdraws the approval.</p>
            <label htmlFor="confirm">Type PUBLISH to approve</label>
            <input id="confirm" value={confirm} onChange={e => setConfirm(e.target.value)} autoComplete="off" />
            <button className="btn good" disabled={confirm !== 'PUBLISH' || !!act.busy} onClick={() => act.run('approve', async () => { await api(`/episodes/${ep.id}/publish/approve`, {body: {confirm}}); setConfirm(''); })}>Approve publication</button>
          </div>)}
        {can('publish') && approvedNow && (
          <div className="card stack">
            <div className="alert good small">Approved by {p.approved_by} on {when(p.approved_at)}.</div>
            <button className="btn primary" disabled={!!act.busy} onClick={() => act.run('publish', () => api(`/episodes/${ep.id}/publish/start`, {method: 'POST'}))}>Publish to YouTube now</button>
          </div>)}
        <JobNote job={lastJob(ep, 'publish_youtube')} />
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ history
function HistoryTab({ep}: Ctx) {
  return (
    <div className="grid cols-2">
      <div className="card"><h2>Decisions</h2>
        {!ep.reviews.length ? <p className="muted">No decisions yet.</p> : <div className="table-wrap"><table><tbody>
          {ep.reviews.map((r: any) => <tr key={r.id}><td className="muted small">{when(r.created_at)}</td><td>{r.gate}</td>
            <td><span className={`badge ${r.decision === 'approved' ? 'good' : 'warn'}`}>{r.decision.replace('_', ' ')}</span></td><td className="small">r{r.revision} {r.comment}</td></tr>)}
        </tbody></table></div>}
        <h2 style={{marginTop: 16}}>Script versions</h2>
        <ul>{ep.script_versions.map((v: any) => <li key={v.version}>v{v.version} · {v.source}{v.note ? ` — ${v.note}` : ''} <span className="muted small">{when(v.created_at)}</span></li>)}</ul>
      </div>
      <div className="card"><h2>Activity</h2>
        <div className="table-wrap"><table><tbody>{ep.events.map((e: any, i: number) => <tr key={i}><td className="muted small">{when(e.created_at)}</td><td className="small">{e.message}</td></tr>)}</tbody></table></div>
        <h2 style={{marginTop: 16}}>All assets</h2>
        <ul>{ep.assets.map((a: any) => <li key={a.id}><a href={a.url} target="_blank" rel="noreferrer">{a.label || a.kind}</a> <span className="muted small">r{a.revision} · {a.kind}</span></li>)}</ul>
      </div>
    </div>
  );
}
