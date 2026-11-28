'use client';
// The cinematic steps (API: cinematic.py): story -> screenplay -> cast and voices -> locations -> shot stills ->
// voices -> motion and dialogue shots -> final cut with the YouTube synthetic-content notice. Every paid button shows
// its price and the request carries it (the API refuses any other price with 409); nothing is approved for the owner.
// "Make whole episode" (the autopilot) on top runs the same steps and stops at each approval.
import Link from 'next/link';
import {use, useEffect, useState} from 'react';
import {api, uploadFile} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import Autopilot from '@/components/Autopilot';
import GuideCast from '@/components/GuideCast';
import ShotChat from '@/components/ShotChat';
import {CAMERAS, DISCLOSURE, money, progress, shotLine, shotStatus} from '@/lib/cinematic';

type Act = ReturnType<typeof useAction>;

export default function CinematicPage({params}: {params: Promise<{id: string}>}) {
  const {id} = use(params);
  const [poll, setPoll] = useState(15000);
  const {data: v, error, reload} = useApi<any>(`/episodes/${id}/cinematic`, poll);
  const act = useAction(reload);
  useEffect(() => { setPoll(v?.busy ? 4000 : 15000); }, [v?.busy]);
  if (!v) return error ? <ErrorBox error={error} /> : <p className="muted">Loading…</p>;
  const steps = progress(v);
  return (
    <>
      <div className="ep-head"><div>
        <p className="small" style={{margin: '0 0 4px'}}><Link href="/">← Episodes</Link></p>
        <h1>{v.episode.title}</h1>
        <p className="sub">Cinematic episode: realistic invented actors. Work down the steps; each paid button shows its price.</p>
      </div></div>
      <ErrorBox error={act.error} />
      <Autopilot id={id} onChange={reload} />
      <ol className="row small" aria-label="Progress" style={{listStyle: 'none', padding: 0, flexWrap: 'wrap'}}>
        {steps.map((s, i) => <li key={s.key}><span className={`badge ${s.done ? 'good' : ''}`}>{i + 1}. {s.title}{s.done ? ' ✓' : ''}</span></li>)}
      </ol>
      <Story v={v} />
      <Screenplay v={v} id={id} act={act} />
      {v.screenplay?.approved && <>
        <Cast v={v} id={id} act={act} reload={reload} />
        <Locations v={v} id={id} act={act} />
        <Settings v={v} id={id} act={act} />
        <Lines v={v} id={id} act={act} reload={reload} />
        <Shots v={v} id={id} act={act} reload={reload} />
        <Final v={v} id={id} act={act} />
      </>}
    </>);
}

function Card({n, title, children}: {n: number; title: string; children: React.ReactNode}) {
  return <section className="card stack" style={{marginTop: 12}}><h2 className="gd-title"><span className="gd-n">{n}</span>{title}</h2>{children}</section>;
}

function Story({v}: {v: any}) {
  const s = v.story || {};
  return (
    <Card n={1} title="Story">
      {s.source === 'idea' && <p style={{margin: 0}}>{s.idea}</p>}
      {s.source === 'bible' && <p style={{margin: 0}}><strong>{s.passage}</strong> ({s.translation}){s.angle ? ` — ${s.angle}` : ''}
        {s.scripture_text ? <span className="small muted"> · passage text included ({s.check?.status === 'ok' ? 'public-domain check OK' : 'confirmed public domain by you'})</span> : null}</p>}
      {s.source === 'script' && <pre className="small" style={{whiteSpace: 'pre-wrap', margin: 0, maxHeight: 200, overflow: 'auto'}}>{s.script}</pre>}
    </Card>);
}

function Screenplay({v, id, act}: {v: any; id: string; act: Act}) {
  const sp = v.screenplay || {};
  const [text, setText] = useState('');
  const [editing, setEditing] = useState(false);
  useEffect(() => { setText(sp.content ? JSON.stringify(sp.content, null, 1) : ''); }, [JSON.stringify(sp.content)]);   // eslint-disable-line react-hooks/exhaustive-deps
  const est = sp.estimate;
  const write = (template = false) => {
    if (!template && v.keys.openai && est && !window.confirm(`Write the screenplay with ${est.model}: about ${money(est.usd_typical, 4)}, at most ${money(est.usd_max, 4)}. Send now? (paid, not retried by itself)`)) return;
    act.run('sp', () => api(`/episodes/${id}/cinematic/screenplay/write`, {body: {confirm_usd: v.keys.openai && !template ? est?.usd_max : null, template}}));
  };
  const save = () => {
    let parsed;
    try { parsed = JSON.parse(text); } catch { act.setError('The screenplay is not valid JSON'); return; }
    act.run('sp-save', () => api(`/episodes/${id}/cinematic/screenplay`, {method: 'PUT', body: {screenplay: parsed}})).then(ok => ok && setEditing(false));
  };
  const shots = (sp.content?.scenes || []).flatMap((s: any) => s.shots.map((x: any) => ({...x, location: s.location})));
  return (
    <Card n={2} title="Screenplay">
      <div className="row">
        <button className="btn primary" disabled={!!act.busy} onClick={() => write(false)}>
          {sp.content ? 'Write again' : 'Write the screenplay'}{v.keys.openai && est ? ` · up to ${money(est.usd_max, 4)}` : ' (template, free)'}</button>
        {v.keys.openai && <button className="btn sm" disabled={!!act.busy} onClick={() => write(true)}>Use the free template instead</button>}
        {!v.keys.openai && <span className="small muted">No OpenAI key: a template is made (from your script line by line, if you gave one).</span>}
      </div>
      {sp.content && <>
        <p className="small muted" style={{margin: 0}}>{sp.label}{sp.usd ? ` · ${money(sp.usd, 4)} so far` : ''}</p>
        {(sp.content.warnings || []).length > 0 && <ul className="small warn">{sp.content.warnings.map((w: string) => <li key={w}>{w}</li>)}</ul>}
        <p style={{margin: 0}}><strong>{sp.content.title}</strong> {sp.content.logline}</p>
        <p className="small" style={{margin: 0}}>Characters: {(sp.content.characters || []).map((c: any) => `${c.name}${c.role ? ` (${c.role})` : ''}`).join(', ')}.
          Locations: {(sp.content.locations || []).map((l: any) => l.name).join(', ')}.</p>
        <ol className="small">{shots.map((s: any, i: number) => <li key={i}>{s.location}: {shotLine(s)}</li>)}</ol>
        {editing ? <>
          <textarea aria-label="Screenplay (JSON)" rows={16} className="mono small" value={text} onChange={e => setText(e.target.value)} />
          <div className="row"><button className="btn sm" disabled={!!act.busy} onClick={save}>Save my changes</button>
            <button className="btn sm" onClick={() => setEditing(false)}>Cancel</button></div>
        </> : <button className="btn sm" onClick={() => setEditing(true)}>Edit the screenplay</button>}
        <div className="row">
          {sp.approved ? <><span className="badge good">Approved{sp.approved_by ? ` by ${sp.approved_by}` : ''}</span>
            <button className="btn sm" disabled={!!act.busy} onClick={() => act.run('sp-un', () => api(`/episodes/${id}/cinematic/screenplay/approve`, {body: {approve: false}}))}>Withdraw approval</button></>
            : <button className="btn good" disabled={!!act.busy} onClick={() => act.run('sp-ok', () => api(`/episodes/${id}/cinematic/screenplay/approve`, {body: {approve: true}}))}>Approve the screenplay</button>}
        </div>
      </>}
    </Card>);
}

function Cast({v, id, act, reload}: {v: any; id: string; act: Act; reload: () => unknown}) {
  const [pick, setPick] = useState<Record<number, string>>({});
  return (
    <Card n={3} title="Cast and voices">
      <p className="small muted" style={{margin: 0}}>Invented people only, in the “Cinematic realistic” style: never a real person’s likeness.</p>
      {!v.cast_made ? <button className="btn primary" disabled={!!act.busy} onClick={() => act.run('cast', () => api(`/episodes/${id}/cinematic/cast`, {method: 'POST'}))}>
        Make the cast from the screenplay (free)</button>
        : <>
          <GuideCast id={id} onChange={reload} />
          <h3 style={{margin: '8px 0 0'}}>Voices ({v.voice_engine.label}; {v.voice_engine.weights_licence})</h3>
          {v.cast.map((c: any) => {
            const val = pick[c.id] ?? c.voice ?? c.suggested_voice ?? '';
            return (
              <div key={c.id} className="row small">
                <strong style={{minWidth: 140}}>{c.name}</strong>
                <select aria-label={`Voice of ${c.name}`} value={val} onChange={e => setPick({...pick, [c.id]: e.target.value})}>
                  <option value="">Choose…</option>
                  {v.voices.map((x: any) => <option key={x.id} value={x.id}>{x.label}{x.id === c.suggested_voice ? ' (suggested)' : ''}</option>)}</select>
                <button className="btn sm" disabled={!!act.busy || !val || val === c.voice}
                  onClick={() => act.run(`v${c.id}`, () => api(`/episodes/${id}/cinematic/voices`, {method: 'PUT', body: {character_id: c.id, voice: val}}))}>
                  {c.voice ? 'Change voice' : 'Save voice'}</button>
                {c.voice ? <span className="badge good">{c.voice}</span> : <span className="badge warn">no voice yet</span>}
              </div>);
          })}
        </>}
    </Card>);
}

function Locations({v, id, act}: {v: any; id: string; act: Act}) {
  const cost = v.location_cost;
  return (
    <Card n={4} title="Locations">
      {!v.locations_made ? <button className="btn primary" disabled={!!act.busy} onClick={() => act.run('loc', () => api(`/episodes/${id}/cinematic/locations`, {method: 'POST'}))}>
        Make the locations from the screenplay (free)</button>
        : v.locations.map((l: any) => (
          <div key={l.wall_id} className="stack">
            <strong>{l.name}</strong>
            <p className="small muted" style={{margin: 0}}>{l.prompt}</p>
            <div className="cine-takes">{l.takes.map((t: any) => (
              <button key={t.id} type="button" className="btn sm" title="Approve this picture" disabled={!!act.busy}
                onClick={() => act.run(`la${t.id}`, () => api(`/episodes/${id}/room-sets/walls/${l.wall_id}/approve`, {body: {take_id: t.id}}))}>
                <img src={t.url} alt={`${l.name} take`} className={l.approved === t.id ? 'on' : ''} />{l.approved === t.id ? 'Approved' : 'Approve'}</button>))}</div>
            <button className="btn sm" disabled={!!act.busy || l.busy} onClick={() => {
              if (!window.confirm(`Draw a picture of “${l.name}”: ${cost.label}. Start now? (paid)`)) return;
              act.run(`lm${l.wall_id}`, () => api(`/episodes/${id}/room-sets/walls/${l.wall_id}/make`, {body: {confirm_usd: cost.usd}}));
            }}>{l.busy ? 'Drawing…' : `Draw a picture · ${money(cost.usd)}`}</button>
          </div>))}
    </Card>);
}

function Settings({v, id, act}: {v: any; id: string; act: Act}) {
  const s = v.settings;
  const put = (body: any) => act.run('set', () => api(`/episodes/${id}/cinematic/settings`, {method: 'PUT', body}));
  return (
    <Card n={5} title="How stills and voices are made">
      <div className="grid cols-3">
        <div><label htmlFor="c-still">Shot stills</label>
          <select id="c-still" value={s.still_provider} onChange={e => put({still_provider: e.target.value})}>
            {Object.entries(v.still_providers).map(([k, l]) => <option key={k} value={k}>{l as string}</option>)}</select></div>
        <div><label htmlFor="c-voice">Voices</label>
          <select id="c-voice" value={s.voice_source} onChange={e => put({voice_source: e.target.value})}>
            {Object.entries(v.voice_sources).map(([k, l]) => <option key={k} value={k}>{l as string}</option>)}</select></div>
      </div>
      {!v.availability.ok && <p className="small warn" style={{margin: 0}}>Rented GPU: {v.availability.reason}</p>}
    </Card>);
}

function Lines({v, id, act, reload}: {v: any; id: string; act: Act; reload: () => unknown}) {
  const upload = (lid: string, f: File | null) => {
    if (!f || !window.confirm('Is this your own recording (or licensed to you)?')) return;
    act.run(`u${lid}`, () => uploadFile(`/episodes/${id}/cinematic/lines/${lid}/upload`, f, {rights: 'own'}));
  };
  return (
    <Card n={6} title="Voices (dialogue lines)">
      {v.settings.voice_source === 'tts' && <div className="row">
        <button className="btn primary" disabled={!!act.busy || !v.kokoro_installed} onClick={() => act.run('lines', () => api(`/episodes/${id}/cinematic/lines/generate`, {body: {}}))}>
          Speak the lines without a take (free)</button>
        {!v.kokoro_installed && <span className="small bad">Kokoro is not installed on the studio server.</span>}</div>}
      {v.lines.length === 0 && <p className="small muted">The screenplay has no dialogue.</p>}
      {v.lines.map((ln: any) => (
        <div key={ln.id} className="stack" style={{borderTop: '1px solid var(--line)', paddingTop: 8}}>
          <div className="spread small"><span><strong>{ln.id} · {ln.speaker}</strong> ({ln.emotion}): “{ln.text}”</span>
            {ln.approved ? <span className="badge good">Take approved</span> : ln.takes.length ? <span className="badge warn">Listen and approve</span> : <span className="badge">No take yet</span>}</div>
          {ln.takes.map((t: any) => (
            <div key={t.id} className="row small">
              <audio controls src={t.url} preload="none" />
              <span className="muted">{t.source === 'upload' ? 'your recording' : t.voice}{t.seconds ? ` · ${t.seconds.toFixed(1)} s` : ''}</span>
              {ln.approved === t.id ? <button className="btn sm" disabled={!!act.busy} onClick={() => act.run(`la${t.id}`, () => api(`/episodes/${id}/cinematic/lines/${ln.id}/approve`, {body: {take_id: null}}))}>Withdraw</button>
                : <button className="btn sm good" disabled={!!act.busy} onClick={() => act.run(`la${t.id}`, () => api(`/episodes/${id}/cinematic/lines/${ln.id}/approve`, {body: {take_id: t.id}}))}>Approve this take</button>}
            </div>))}
          <div className="row small">
            {v.settings.voice_source === 'tts' && <button className="btn sm" disabled={!!act.busy || !v.kokoro_installed}
              onClick={() => act.run(`g${ln.id}`, () => api(`/episodes/${id}/cinematic/lines/generate`, {body: {lines: [ln.id]}}))}>Speak again (free)</button>}
            <label className="btn sm" style={{margin: 0, color: 'inherit'}}>Upload my recording
              <input type="file" accept="audio/*" hidden onChange={e => upload(ln.id, e.target.files?.[0] || null)} /></label>
          </div>
          <ShotChat step="cine_line" item={ln.id} episodeId={id} onApplied={reload} />
        </div>))}
    </Card>);
}

function Shots({v, id, act, reload}: {v: any; id: string; act: Act; reload: () => unknown}) {
  const [est, setEst] = useState<any>(null);
  useEffect(() => { api(`/episodes/${id}/cinematic/render/estimate`, {body: {}}).then(setEst, () => setEst(null)); },
    [JSON.stringify(v.shots.map((s: any) => [s.approved, s.render_ready, (s.renders || []).length]))]);   // eslint-disable-line react-hooks/exhaustive-deps
  const renderAll = () => {
    if (!est || !est.shots.length || !window.confirm(`Make shot(s) ${est.shots.join(', ')} on the rented GPU: ${est.label}. Start now? (paid)`)) return;
    act.run('render', () => api(`/episodes/${id}/cinematic/render`, {body: {shots: est.shots, confirm_usd: est.usd_max}}));
  };
  return (
    <Card n={7} title="Shot stills, motion and dialogue shots">
      <div className="row">
        <button className="btn primary" disabled={!!act.busy || !est?.shots?.length || !v.availability.ok} onClick={renderAll}>
          Make all ready shots{est?.shots?.length ? ` (${est.shots.length}) · up to ${money(est.usd_max)}` : ''}</button>
        <button className="btn sm" disabled={!!act.busy} onClick={() => { if (window.confirm('Turn the rented GPU off now?')) act.run('stop', () => api(`/episodes/${id}/cinematic/stop`, {method: 'POST'})); }}>Turn the GPU off</button>
      </div>
      <div className="cine-shots">{v.shots.map((s: any) => <ShotCard key={s.n} s={s} v={v} id={id} act={act} reload={reload} />)}</div>
    </Card>);
}

function ShotCard({s, v, id, act, reload}: {s: any; v: any; id: string; act: Act; reload: () => unknown}) {
  const st = shotStatus(s);
  const cost = v.still_cost;
  const [prompt, setPrompt] = useState(s.motion_prompt || '');
  const still = (end: boolean) => {
    if (!cost || !window.confirm(`A new ${end ? 'end ' : ''}still of shot ${s.n}: ${cost.label}. Start now? (paid)`)) return;
    act.run(`st${s.n}`, () => api(`/episodes/${id}/cinematic/shots/${s.n}/still`, {body: {confirm_usd: cost.usd, end}}));
  };
  const make = () => {
    const e = s.render_estimate;
    if (!e || !window.confirm(`Make shot ${s.n} on the rented GPU: ${e.label}. Start now? (paid)`)) return;
    act.run(`r${s.n}`, () => api(`/episodes/${id}/cinematic/render`, {body: {shots: [s.n], confirm_usd: e.usd_max}}));
  };
  const approveTake = (tid: string | null, end = false) => act.run(`a${s.n}`, () => api(`/episodes/${id}/cinematic/shots/${s.n}/still/approve`, {body: {take_id: tid, end}}));
  return (
    <div className="card stack" style={{padding: 10}}>
      <div className="spread small"><strong>Shot {s.n}</strong><span className={`badge ${st.tone}`}>{st.text}</span></div>
      <p className="small" style={{margin: 0}}>{shotLine(s)}</p>
      {s.run?.status === 'failed' && <p className="small bad" style={{margin: 0}}>{s.run.error}</p>}
      <div className="cine-takes">{s.stills.map((t: any) => (
        <button key={t.id} type="button" className="btn sm" disabled={!!act.busy} onClick={() => approveTake(s.approved === t.id ? null : t.id)}>
          <img src={t.url} alt={`Shot ${s.n} still`} className={s.approved === t.id ? 'on' : ''} />{s.approved === t.id ? 'Approved' : 'Approve'}</button>))}</div>
      <div className="row small">
        <button className="btn sm" disabled={!!act.busy} onClick={() => still(false)}>New still{cost ? ` · ${money(cost.usd)}` : ''}</button>
        {s.kind === 'motion' && <button className="btn sm" disabled={!!act.busy} onClick={() => still(true)}>New end still</button>}
      </div>
      {s.kind === 'motion' && s.end_stills.length > 0 && <>
        <div className="cine-takes">{s.end_stills.map((t: any) => (
          <button key={t.id} type="button" className="btn sm" disabled={!!act.busy} onClick={() => approveTake(s.end_approved === t.id ? null : t.id, true)}>
            <img src={t.url} alt={`Shot ${s.n} end still`} className={s.end_approved === t.id ? 'on' : ''} />{s.end_approved === t.id ? 'End approved' : 'Approve as end'}</button>))}</div>
        <label className="check small"><input type="checkbox" checked={s.use_end} onChange={e => act.run(`ue${s.n}`, () => api(`/episodes/${id}/cinematic/shots/${s.n}`, {method: 'PUT', body: {use_end: e.target.checked}}))} />
          Move from the start still to the approved end still</label></>}
      <ShotChat step="cine_still" item={s.n} episodeId={id} onApplied={reload} />
      <div className="row small">
        <label htmlFor={`cam${s.n}`}>Camera</label>
        <select id={`cam${s.n}`} value={s.camera} onChange={e => act.run(`c${s.n}`, () => api(`/episodes/${id}/cinematic/shots/${s.n}`, {method: 'PUT', body: {camera: e.target.value}}))}>
          {CAMERAS.map(c => <option key={c} value={c}>{c}</option>)}</select>
      </div>
      <textarea aria-label={`Motion prompt of shot ${s.n}`} rows={3} className="small" placeholder="Motion prompt (empty: the template)"
        value={prompt} onChange={e => setPrompt(e.target.value)} />
      <div className="row small">
        <button className="btn sm" disabled={!!act.busy || prompt === (s.motion_prompt || '')}
          onClick={() => act.run(`mp${s.n}`, () => api(`/episodes/${id}/cinematic/shots/${s.n}`, {method: 'PUT', body: {motion_prompt: prompt}}))}>Save prompt</button>
        <button className="btn sm primary" disabled={!!act.busy || !s.render_ready || !v.availability.ok} title={s.render_blocked || ''} onClick={make}>
          {s.renders.length ? 'Make again' : 'Make the shot'}{s.render_estimate ? ` · up to ${money(s.render_estimate.usd_max)}` : ''}</button>
      </div>
      {!s.render_ready && s.render_blocked && <p className="small muted" style={{margin: 0}}>To make it: {s.render_blocked}.</p>}
      {s.renders.map((r: any) => (
        <div key={r.id} className="stack">
          <video controls preload="none" src={r.url} />
          <div className="row small"><span className="muted">{r.kind} · {r.gpu} · {money(r.usd)}</span>
            <button className="btn sm good" disabled={!!act.busy} onClick={() => act.run(`ra${r.id}`, () => api(`/episodes/${id}/cinematic/shots/${s.n}/render/approve`, {body: {render_id: s.approved_render === r.id ? null : r.id}}))}>
              {s.approved_render === r.id ? 'Withdraw approval' : 'Approve this shot'}</button></div>
        </div>))}
      <ShotChat step="cine_shot" item={s.n} episodeId={id} onApplied={reload} />
    </div>);
}

function Final({v, id, act}: {v: any; id: string; act: Act}) {
  const p = v.plan;
  const music = (f: File | null) => {
    if (!f || !window.confirm('Is this music royalty-free or licensed for your videos?')) return;
    act.run('music', () => uploadFile(`/episodes/${id}/cinematic/music`, f, {rights: 'royalty_free', name: f.name}));
  };
  return (
    <Card n={8} title="Final cut and YouTube notice">
      <div className="alert warn" role="note"><strong>{DISCLOSURE}</strong></div>
      <label className="check"><input type="checkbox" checked={v.disclosure.acknowledged}
        onChange={e => act.run('disc', () => api(`/episodes/${id}/cinematic/disclosure`, {method: 'PUT', body: {acknowledged: e.target.checked}}))} />
        I will tick “Altered or synthetic content” when I upload this video to YouTube</label>
      <div className="row small">
        Music: {v.music ? <><span>{v.music.name || 'uploaded'}</span>{v.music.url && <audio controls preload="none" src={v.music.url} />}
          <button className="btn sm" disabled={!!act.busy} onClick={() => act.run('mdel', () => api(`/episodes/${id}/cinematic/music`, {method: 'DELETE'}))}>Remove</button></>
          : <span className="muted">none</span>}
        <label className="btn sm" style={{margin: 0, color: 'inherit'}}>Upload royalty-free music
          <input type="file" accept="audio/*" hidden onChange={e => music(e.target.files?.[0] || null)} /></label>
        <label className="check"><input type="checkbox" checked={v.settings.captions}
          onChange={e => act.run('cap', () => api(`/episodes/${id}/cinematic/settings`, {method: 'PUT', body: {captions: e.target.checked}}))} />Captions</label>
      </div>
      <p className="small muted" style={{margin: 0}}>{p.rows.length} shots, {p.seconds.toFixed(1)} s
        {p.missing.length ? ` · shot(s) ${p.missing.join(', ')} need an approved still or clip` : ''}</p>
      <button className="btn primary" disabled={!!act.busy || p.missing.length > 0 || !p.rows.length}
        onClick={() => act.run('asm', () => api(`/episodes/${id}/cinematic/assemble`, {method: 'POST'}))}>Put the episode together (free)</button>
      {v.cuts.map((c: any) => (
        <div key={c.id} className="stack">
          <video controls preload="none" src={c.url} style={{maxWidth: 640, width: '100%'}} />
          <div className="row small"><span className="muted">{c.seconds.toFixed(1)} s{c.stills ? ` · ${c.stills} still(s), not animated` : ''}{c.current ? '' : ' · older than the current shots'}</span>
            {c.approved ? <><span className="badge good">Approved</span>
              <button className="btn sm" disabled={!!act.busy} onClick={() => act.run('cun', () => api(`/episodes/${id}/cinematic/cut/approve`, {body: {cut_id: null}}))}>Withdraw</button></>
              : <button className="btn sm good" disabled={!!act.busy || !v.disclosure.acknowledged} title={v.disclosure.acknowledged ? '' : 'Tick the YouTube notice first'}
                onClick={() => act.run('cok', () => api(`/episodes/${id}/cinematic/cut/approve`, {body: {cut_id: c.id}}))}>Approve the final cut</button>}</div>
        </div>))}
    </Card>);
}
