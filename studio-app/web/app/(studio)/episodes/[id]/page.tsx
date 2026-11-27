'use client';
// An episode, simply (owner-approved layout, 2026-11-25): one column of six steps, each one line. Finished steps stay
// folded; only what needs the owner is open. One "Generate" runs the next FREE steps the episode allows and stops at
// every decision of the owner's and at every paid step (those show their cost and have their own button). Nothing on
// this page approves anything by itself: every approve, reject and paid start is a button the owner presses.
// Every detail is still in the Advanced view (/episodes/{id}/advanced), which the "Open" links lead to.
import Link from 'next/link';
import {use, useEffect, useRef, useState} from 'react';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import NextStepBanner from '@/components/NextStepBanner';
import EpisodeCharacters from '@/components/EpisodeCharacters';
import {AnimateAll, StickShotRow} from '@/components/StickShot';
import {jobLine, showLastError, type Section} from '@/lib/workspace';
import {episodeCharacters, generatePlan, ICON, money, STEP_TONE, steps, type Step} from '@/lib/dashboard';
import {activeJobs, EXPRESSIONS, lastFailure, makingText, peopleText, retakeBody, retakeForm, retakeRunning, SHOT_SIZES,
  shotStatus, sideMembers, summary, timeRange, type RetakeForm, type ShotSize} from '@/lib/shotFrames';

const BUSY = ['audio_preparing', 'audio_transcribing', 'outline_generating', 'script_generating', 'storyboard_generating', 'producing', 'publishing'];

export default function EpisodePage({params}: {params: Promise<{id: string}>}) {
  const {id} = use(params);
  const [poll, setPoll] = useState(5000);
  const {data: ep, error, reload} = useApi<any>(`/episodes/${id}`, poll);
  const {data: ws, reload: reloadWs} = useApi<any>(`/episodes/${id}/workspace`, poll);
  const audio = ep?.source === 'audio';
  const {data: au, reload: reloadAu} = useApi<any>(audio ? `/episodes/${id}/audio` : null, poll * 2);
  const {data: cast} = useApi<any[]>(ep?.script_version ? `/episodes/${id}/cast?v=${ep.script_version}` : null, 30000);
  const {data: library} = useApi<any[]>('/characters', 60000);
  const {data: panel, reload: reloadPanel} = useApi<any>(`/episodes/${id}/set-panel`, 15000);
  const building = audio && ep?.stage === 'audio_labelling';
  const {data: estimate} = useApi<any>(building ? `/episodes/${id}/audio/scenes/estimate` : null, 30000);
  const reloadAll = async () => { await reload(); await reloadWs(); await reloadPanel(); if (audio) await reloadAu(); };
  const act = useAction(reloadAll);
  const [auto, setAuto] = useState(false);
  const inFlight = useRef(false);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  useEffect(() => { setOpen({}); setAuto(false); }, [id]);
  useEffect(() => {
    if (!ep) return;
    const active = BUSY.includes(ep.stage) || ep.jobs.some((j: any) => j.status === 'queued' || j.status === 'running');
    setPoll(active ? 3000 : 15000);
  }, [ep]);

  const plan = generatePlan(ep, ws, estimate);
  // Generate: run the free step, then keep going (after each job finishes) until a decision or a paid step stops it
  const runFree = async () => {
    if (plan.kind !== 'free' || inFlight.current) return;
    inFlight.current = true;
    const ok = await act.run('generate', () => api(plan.path, {method: 'POST', body: plan.body}));
    inFlight.current = false;
    if (!ok) setAuto(false);
  };
  useEffect(() => {
    if (!auto || act.busy) return;
    if (plan.kind === 'free') runFree();
    else if (plan.why !== 'working' && plan.why !== 'checking') setAuto(false);
  }, [auto, plan.kind, plan.kind === 'free' ? plan.path : plan.why, act.busy]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (error && !ep) return <ErrorBox error={error} />;
  if (!ep || !ws) return <p className="muted">Loading…</p>;
  const lib = library || [];
  const chars = episodeCharacters(cast || null, au || null, lib);
  const candidates = (panel?.sets || []).filter((x: any) => x.status === 'candidate' && x.for_this_episode);
  const facts = {lines: au?.lines?.length, shots: au?.video_notes?.ranges?.length || 0, characters: chars.length,
    approvedCharacters: chars.filter(c => c.status === 'approved').length, setsWaiting: candidates.length,
    storyboardScenes: ep.scenes?.length || 0};
  const list = steps(ws, ep, facts);
  const isOpen = (s: Step) => open[s.key] ?? (s.state === 'you' || s.state === 'failed');
  const adv = (section?: string, extra = '') => `/episodes/${ep.id}/advanced${section ? `?open=${section}${extra}` : ''}`;
  const ctx: Ctx = {ep, ws, act, adv, chars, panel, candidates, estimate, au, reload: reloadAll};
  return (
    <>
      <div className="ep-head">
        <div>
          <p className="small" style={{margin: '0 0 4px'}}><Link href="/">← Episodes</Link></p>
          <h1>{ep.title}</h1>
          <span className="muted small">{ep.format === 'long' ? 'YouTube long' : 'Short'}{ep.layout === 'landscape' ? ' · 16:9' : ep.format === 'short' ? ' · 9:16' : ''} · <Link href={adv()}>Advanced view</Link> · <Link href={`/episodes/${ep.id}/guide`}>Guided steps</Link></span>
        </div>
        <div className="ep-generate">
          <button className="btn primary" disabled={plan.kind !== 'free' || !!act.busy} onClick={() => { setAuto(true); runFree(); }}>
            {act.busy === 'generate' ? 'Generating…' : 'Generate'}</button>
          <span className={`small ${plan.kind === 'free' ? '' : 'muted'}`} role="status">{plan.kind === 'free' ? `Next: ${plan.label}` : plan.text}</span>
        </div>
      </div>
      <NextStepBanner id={ep.id} />
      <ErrorBox error={act.error} />
      {showLastError(ep) && <div className="alert bad small">{ep.last_error}</div>}
      <ol className="steps-list">
        {list.map(s => (
          <li key={s.key} className={`stp stp-${s.state}`}>
            <button type="button" className="stp-line" aria-expanded={isOpen(s)} onClick={() => setOpen(o => ({...o, [s.key]: !isOpen(s)}))}>
              <span className="stp-n">{s.n}</span>
              <span className="stp-title">{s.title}</span>
              <span className={`stp-text ${STEP_TONE[s.state]}`}><span aria-hidden className="stp-icon">{ICON[s.state]}</span> {s.text}</span>
            </button>
            {isOpen(s) && <div className="stp-body"><StepBody s={s} c={ctx} /><Details s={s} c={ctx} /></div>}
          </li>))}
      </ol>
    </>
  );
}

type Ctx = {ep: any; ws: any; act: ReturnType<typeof useAction>; adv: (section?: string, extra?: string) => string; chars: ReturnType<typeof episodeCharacters>;
  panel: any; candidates: any[]; estimate: any; au: any; reload: () => unknown};

// What the owner can do in a step: the decisions are buttons the owner presses; anything bigger opens the Advanced view.
function StepBody({s, c}: {s: Step; c: Ctx}) {
  switch (s.key) {
    case 'source': return <Pending s={s} c={c} />;
    case 'characters': return <Characters c={c} s={s} />;
    case 'sets': return <Sets c={c} s={s} />;
    case 'storyboard': return <Storyboard c={c} s={s} />;
    case 'video': return <VideoStep c={c} s={s} />;
    case 'final': return <Final c={c} s={s} />;
  }
}

// The sections of a step that are not finished: their one-line note and a link to the step in the Advanced view.
function Pending({s, c, skip = []}: {s: Step; c: Ctx; skip?: string[]}) {
  const rows = s.sections.filter(x => !['done', 'not_needed', 'waiting'].includes(x.status) && !skip.includes(x.key));
  if (!rows.length) return null;
  return <div className="stack">{rows.map(x => (
    <div key={x.key} className="spread pending">
      <span className={`small ${x.status === 'failed' ? 'bad' : ''}`}>{x.title}: {x.note}</span>
      <Link className="btn sm" href={c.adv(x.key)}>Open</Link>
    </div>))}</div>;
}

// Notes, jobs and logs: folded by default.
function Details({s, c}: {s: Step; c: Ctx}) {
  const jobs = s.sections.flatMap(x => x.jobs || []);
  return (
    <details className="stp-details">
      <summary className="small">details</summary>
      <ul className="small muted">
        {s.sections.map((x: Section) => <li key={x.key}><strong>{x.title}</strong> ({x.label}): {x.note}</li>)}
        {jobs.map((j: any) => <li key={j.id} className={j.status === 'failed' ? 'bad' : ''}>{jobLine(j)}</li>)}
        {s.key === 'storyboard' && (c.ep.scenes || []).map((sc: any) => <li key={sc.id}>Scene {sc.position}: {sc.heading}{sc.location ? ` · ${sc.location}` : ''}{sc.description ? ` · ${sc.description}` : ''}</li>)}
      </ul>
      <Link className="small" href={c.adv(s.sections[0]?.key)}>Everything about this step in the Advanced view</Link>
    </details>);
}

function Characters({c, s}: {c: Ctx; s: Step}) {
  const waiting = c.chars.filter(x => x.status !== 'approved');
  return (
    <div className="stack">
      {!c.chars.length ? <p className="muted small">The characters come from the speakers once the recording is transcribed.</p>
        : <div className="chars">{c.chars.map(x => (
          <Link key={x.key} href={x.id ? `/characters` : c.adv('cast')} className={`char ${x.status}`} title={`${x.name}: ${x.role}`}>
            {x.thumb ? <img src={x.thumb} alt="" /> : <span className="char-ph" aria-hidden>{x.name.slice(0, 1).toUpperCase()}</span>}
            <span className="small">{x.name}</span>
            <span className={`badge ${x.status === 'approved' ? 'good' : x.status === 'missing' ? 'bad' : 'warn'}`}>{x.status === 'missing' ? x.role : x.status}</span>
          </Link>))}</div>}
      {c.ep.source === 'audio' ? <EpisodeCharacters id={c.ep.id} onChange={c.reload} />
        : waiting.some(x => x.status === 'review' || x.status === 'none') && <p className="small">Approve their poses on the <Link href="/characters">Characters</Link> page (your decision; new pose sheets are paid and start from the Advanced view, with their cost).</p>}
      <Pending s={s} c={c} skip={c.ep.source === 'audio' ? ['cast'] : []} />
    </div>);
}

function Sets({c, s}: {c: Ctx; s: Step}) {
  const {ep, act, panel, candidates} = c;
  const locked = ['producing', 'publishing'].includes(ep.stage);
  const approved = (panel?.sets || []).filter((x: any) => x.status === 'approved' && !x.chosen);
  const chosen = (panel?.sets || []).find((x: any) => x.chosen);
  return (
    <div className="stack">
      {chosen && <p className="small">This episode's set: <strong>{chosen.label}</strong></p>}
      {candidates.length > 0 && <div className="set-grid">{candidates.map((x: any) => (
        <div key={x.id} className="set-card">
          {x.url ? <a href={x.url} target="_blank" rel="noreferrer"><img src={x.url} alt={x.label} /></a> : <div className="card empty small">No picture</div>}
          <strong className="small">{x.label}</strong>
          <div className="row">
            <button className="btn sm good" disabled={locked || !!act.busy} onClick={() => act.run('set-ok', () => api(`/sets/${x.id}/decide`, {body: {decision: 'approve', blocking: x.blocking}}))}>Approve</button>
            <button className="btn sm danger" disabled={locked || !!act.busy} onClick={() => act.run('set-no', () => api(`/sets/${x.id}/decide`, {body: {decision: 'reject'}}))}>Reject</button>
          </div>
        </div>))}</div>}
      {!chosen && approved.length > 0 && <div className="row">{approved.map((x: any) => (
        <button key={x.id} className="btn sm" disabled={locked || !!act.busy} onClick={() => act.run('set-use', () => api(`/episodes/${ep.id}/set`, {method: 'PUT', body: {set_id: x.id}}))}>Use {x.label} for this episode</button>))}</div>}
      {!chosen && <div className="spread pending"><span className="small muted">Generate a new set or reuse a kept one (paid image; its cost{panel?.image_cost ? `, ${panel.image_cost},` : ''} is shown before it starts).</span>
        <Link className="btn sm" href={c.adv('set')}>Open</Link></div>}
    </div>);
}

function Storyboard({c, s}: {c: Ctx; s: Step}) {
  const {ep, act, estimate} = c;
  const can = (a: string) => ep.allowed_actions.includes(a);
  const scriptSec = s.sections.find(x => x.key === 'script');
  const build = scriptSec?.status === 'action' && scriptSec.label === 'build' && can('build_audio_scenes');
  const writerUsd = estimate?.writer?.usd;
  const frames = (ep.scenes || []).filter((sc: any) => sc.reference?.url);
  return (
    <div className="stack">
      {build && <div className="spread pending">
        <span className="small">Build the scenes around the recorded lines.</span>
        <div className="row">
          <button className="btn sm" disabled={!!act.busy} onClick={() => act.run('scenes', () => api(`/episodes/${ep.id}/audio/scenes`, {body: {mode: 'simple'}}))}>Simple split (free)</button>
          {writerUsd !== 0 && <button className="btn sm primary" disabled={!!act.busy || !estimate}
            onClick={() => { if (window.confirm(`Build the scenes with the AI writer (${estimate?.writer?.provider}): about ${money(writerUsd)}. Start now?`)) act.run('scenes', () => api(`/episodes/${ep.id}/audio/scenes`, {body: {mode: 'writer'}})); }}>
            AI writer · {estimate ? `about ${money(writerUsd)}` : 'checking cost…'}</button>}
        </div></div>}
      {can('approve_script') && <div className="spread pending">
        <span className="small">The scenes are ready: read them, then approve (or edit and send back in the Advanced view).</span>
        <div className="row"><Link className="btn sm" href={c.adv('script')}>Read</Link>
          <button className="btn sm good" disabled={!!act.busy} onClick={() => act.run('script-ok', () => api(`/episodes/${ep.id}/script/approve`, {body: {comment: ''}}))}>Approve script</button></div></div>}
      {frames.length > 0 && <div className="frames">{(ep.scenes || []).map((sc: any) => (
        <figure key={sc.id}>{sc.reference?.url ? <a href={sc.reference.url} target="_blank" rel="noreferrer"><img src={sc.reference.url} alt={`Scene ${sc.position}`} /></a>
          : <div className="frame-ph small muted">no frame yet</div>}<figcaption className="small muted">{sc.position}. {sc.heading}</figcaption></figure>))}</div>}
      {can('approve_storyboard') && <div className="spread pending">
        <span className="small">One frame per shot. Approve them all, or send scenes back in the Advanced view.</span>
        <div className="row"><Link className="btn sm" href={c.adv('storyboard')}>Send some back</Link>
          <button className="btn sm good" disabled={!!act.busy} onClick={() => act.run('sb-ok', () => api(`/episodes/${ep.id}/storyboard/approve`, {body: {comment: ''}}))}>Approve all</button></div></div>}
      {ep.source === 'audio' && (ep.scenes || []).length > 0 && <ShotFrames c={c} />}
      <Pending s={s} c={c} skip={[...(build || can('approve_script') ? ['script'] : []), ...(can('approve_storyboard') ? ['storyboard'] : [])]} />
    </div>);
}

// One frame per shot of the reference video, for the video generator (shot_frames.py). Every action here is free (CPU
// on the server) and every approval is the owner's click: nothing approves by itself.
function ShotFrames({c}: {c: Ctx}) {
  const {ep} = c;
  const base = `/episodes/${ep.id}/shot-frames`;
  const [poll, setPoll] = useState(15000);
  const {data: v, reload} = useApi<any>(base, poll);
  // the stick pipeline: stills and clips per shot, their prices (stick_shots.py)
  const {data: sk, reload: reloadSk} = useApi<any>(`/episodes/${ep.id}/stick-shots`, poll);
  const act = useAction(async () => { await reload(); await reloadSk(); });
  const busy = activeJobs(v).length > 0 || (sk?.shots || []).some((x: any) => x.busy);
  useEffect(() => { setPoll(busy ? 3000 : 15000); }, [busy]);
  const names = Object.fromEntries(c.chars.map(x => [x.key, x.name]));
  const making = makingText(v);
  const animating = activeJobs(v, 'shot_animatic').length > 0;
  const shots: any[] = v?.shots || [];
  const failure = lastFailure(v);
  const lastStick = (sk?.jobs || [])[0];
  const stickFailure = lastStick?.status === 'failed' ? `${lastStick.kind === 'stick_shot_still' ? 'Still' : 'Animation'} of shot ${lastStick.payload?.index}: ${lastStick.error}` : '';
  if (!v) return <p className="small muted">Loading the shot frames…</p>;
  return (
    <div className="stack sf">
      <ErrorBox error={act.error} />
      {failure && <div className="alert bad small">{failure}</div>}
      {stickFailure && <div className="alert bad small">{stickFailure}</div>}
      {!shots.length ? <div className="spread pending">
        <span className="small">{making || 'One frame per shot of the video, drawn from the approved characters and sets.'}</span>
        <button className="btn sm primary" disabled={!!act.busy || !!making} onClick={() => act.run('sf-make', () => api(base, {method: 'POST'}))}>
          {making ? 'Making…' : 'Make storyboard (free)'}</button></div>
        : <>
          <div className="spread sf-toolbar">
            <span className="small">{summary(v)}{making ? ` · ${making}` : ''}</span>
            <div className="row">
              <button className="btn sm good" disabled={!!act.busy || busy || shots.every(s => s.approved)}
                onClick={() => act.run('sf-all', () => api(`${base}/approve-all`, {method: 'POST'}))}>Approve all</button>
              <AnimateAll sk={sk} base={base} act={act} />
              <button className="btn sm" disabled={!!act.busy || animating || !!making}
                onClick={() => act.run('sf-anim', () => api(`${base}/animatic`, {method: 'POST'}))}>{animating ? 'Making the animatic…' : 'Make animatic (free)'}</button>
              <button className="btn sm" disabled={!!act.busy || busy}
                onClick={() => { if (window.confirm('Draw every frame again? The current frames and their takes are replaced by a new storyboard.')) act.run('sf-make', () => api(base, {method: 'POST'})); }}>Make again</button>
            </div>
          </div>
          {v.animatic_url && <figure className="sf-animatic">
            <video src={v.animatic_url} controls preload="metadata" className={ep.layout === 'landscape' ? 'wide' : 'tall'} />
            <figcaption className="small muted">Animatic: the storyboard on the recording · a draft, not for publishing</figcaption></figure>}
          <div className="sf-grid">{shots.map(s => <ShotCard key={s.index} s={s} v={v} sk={sk} base={base} act={act} names={names} />)}</div>
        </>}
    </div>);
}

function ShotCard({s, v, sk, base, act, names}: {s: any; v: any; sk: any; base: string; act: ReturnType<typeof useAction>; names: Record<string, string>}) {
  const [panel, setPanel] = useState<'' | 'retake' | 'versions'>('');
  const st = shotStatus(s);
  const drawing = retakeRunning(v, s.index);
  const locked = !!act.busy || activeJobs(v, 'shot_frames').length > 0;
  const toggle = (p: 'retake' | 'versions') => setPanel(x => (x === p ? '' : p));
  return (
    <article className={`sf-card ${s.approved ? 'ok' : ''}`}>
      <a className="sf-thumb" href={s.url || undefined} target="_blank" rel="noreferrer">
        {s.url ? <img src={s.url} alt={`Shot ${s.index}`} loading="lazy" /> : <span className="small muted">no frame</span>}
        {drawing && <span className="sf-drawing small">Drawing a new take…</span>}
      </a>
      <div className="sf-meta">
        <div className="spread"><strong>Shot {s.index}</strong><span className={`badge ${st.tone}`}>{st.text}</span></div>
        <span className="small muted">{timeRange(s)} · {s.shot} · {s.versions.length} {s.versions.length === 1 ? 'take' : 'takes'}</span>
        <span className="small sf-people">{peopleText(s.people, names)}</span>
      </div>
      <div className="row">
        <button className="btn sm" aria-expanded={panel === 'retake'} disabled={locked || drawing} onClick={() => toggle('retake')}>Retake</button>
        <button className="btn sm" aria-expanded={panel === 'versions'} disabled={s.versions.length < 2} onClick={() => toggle('versions')}>Versions</button>
        {s.approved
          ? <button className="btn sm" disabled={locked} onClick={() => act.run('sf-un', () => api(`${base}/${s.index}/unapprove`, {method: 'POST'}))}>Unapprove</button>
          : <button className="btn sm good" disabled={locked || drawing || !s.chosen} onClick={() => act.run('sf-ok', () => api(`${base}/${s.index}/approve`, {method: 'POST'}))}>Approve</button>}
      </div>
      <StickShotRow s={s} sk={sk} base={base} act={act} names={names} />
      {panel === 'retake' && <Retake s={s} v={v} base={base} act={act} names={names} done={() => setPanel('')} />}
      {panel === 'versions' && <div className="sf-versions">{s.versions.map((x: any, i: number) => (
        <button key={x.asset_id} type="button" className={`sf-take ${x.asset_id === s.chosen ? 'on' : ''}`} disabled={locked || x.asset_id === s.chosen}
          title={x.note || (x.source === 'first' ? 'first take' : 'retake')}
          onClick={() => act.run('sf-choose', () => api(`${base}/${s.index}/choose`, {body: {asset_id: x.asset_id}}))}>
          {x.url ? <img src={x.url} alt={`Take ${i + 1}`} loading="lazy" /> : <span className="small muted">no frame</span>}
          <span className="small">Take {i + 1}{x.asset_id === s.chosen ? ' · chosen' : ''}</span>
          {x.note && <span className="small muted">{x.note}</span>}
        </button>))}</div>}
    </article>);
}

function Retake({s, v, base, act, names, done}: {s: any; v: any; base: string; act: ReturnType<typeof useAction>;
  names: Record<string, string>; done: () => void}) {
  const [f, setF] = useState<RetakeForm>(() => retakeForm(s));
  const sides = Object.keys(v.sides || {});
  const members = sideMembers(v, f.side);
  const {body, error} = retakeBody(s, f);
  const togglePerson = (k: string) => setF(x => ({...x, people: x.people.includes(k) ? x.people.filter(p => p !== k)
    : members.filter(m => m === k || x.people.includes(m))}));
  const submit = async (e: {preventDefault: () => void}) => {
    e.preventDefault();
    if (error) return;
    if (await act.run('sf-retake', () => api(`${base}/${s.index}/retake`, {body}))) done();
  };
  return (
    <form className="sf-retake" onSubmit={submit}>
      <div className="sf-fields">
        <div><label htmlFor={`sz-${s.index}`}>Shot size</label>
          <select id={`sz-${s.index}`} value={f.shot} onChange={e => setF({...f, shot: e.target.value as ShotSize})}>
            {SHOT_SIZES.map(z => <option key={z} value={z}>{z}</option>)}</select></div>
        {sides.length > 1 && <div><label htmlFor={`sd-${s.index}`}>Side of the room</label>
          <select id={`sd-${s.index}`} value={f.side} onChange={e => setF({...f, side: e.target.value, people: [...sideMembers(v, e.target.value)], emotions: {}})}>
            {sides.map(x => <option key={x} value={x}>{x}</option>)}</select></div>}
      </div>
      <fieldset className="sf-people-list">
        <legend className="small muted">People in the shot</legend>
        {members.map(k => (
          <div key={k} className="sf-person">
            <label className="check"><input type="checkbox" checked={f.people.includes(k)} onChange={() => togglePerson(k)} /> {names[k] || k}</label>
            {f.people.includes(k) && <select aria-label={`Expression for ${names[k] || k}`} value={f.emotions[k] || ''}
              onChange={e => setF({...f, emotions: {...f.emotions, [k]: e.target.value}})}>
              <option value="">expression: as before</option>
              {EXPRESSIONS.map(x => <option key={x} value={x}>{x}</option>)}</select>}
          </div>))}
        {!f.people.length && <p className="small muted">Nobody: the frame shows the room only.</p>}
      </fieldset>
      {error && <p className="small bad">{error}</p>}
      <div className="row">
        <button className="btn sm primary" type="submit" disabled={!!act.busy || !!error}>Draw a new take (free)</button>
        <button className="btn sm" type="button" onClick={done}>Cancel</button>
        <span className="small muted">The older takes are kept; the new one needs your approval.</span>
      </div>
    </form>);
}

function VideoStep({c, s}: {c: Ctx; s: Step}) {
  const {ep, ws, act} = c;
  const talking = s.sections.find(x => x.key === 'talking');
  const next = ws.next;
  const talkingCost = next?.section === 'talking' && next.cost_usd ? `about ${money(next.cost_usd)}` : 'cost shown before it starts';
  const canStart = ep.allowed_actions.includes('start_production') && !!ep.set_id;
  const start = () => {
    if (!window.confirm('Start production: scene preparation, voices and the full render of this episode. Any paid provider it uses is the one set in Settings. Start now?')) return;
    act.run('production', () => api(`/episodes/${ep.id}/production/start`, {method: 'POST'}));
  };
  return (
    <div className="stack">
      {ep.source === 'audio' && talking && !['waiting', 'done'].includes(talking.status) && <div className="spread pending">
        <span className="small">Talking shots: {talking.note} <span className="muted">· cost: {talkingCost}</span></span>
        <Link className="btn sm primary" href={c.adv('talking', '&run=talking')}>Go</Link></div>}
      {ep.allowed_actions.includes('start_production') && <div className="spread pending">
        <span className="small">{ep.set_id ? 'Render the episode.' : 'Choose the set first (step 3).'} <span className="muted">· not started by Generate</span></span>
        <button className="btn sm primary" disabled={!canStart || !!act.busy} onClick={start}>Start production</button></div>}
      <Pending s={s} c={c} skip={['talking', ...(ep.allowed_actions.includes('start_production') ? ['production'] : [])]} />
    </div>);
}

function Final({c, s}: {c: Ctx; s: Step}) {
  const {ep, act} = c;
  const can = (a: string) => ep.allowed_actions.includes(a);
  return (
    <div className="stack">
      {ep.video && ['video_review', 'final_approved', 'publish_failed', 'publishing', 'published'].includes(ep.stage) &&
        <video src={ep.video.url} controls preload="metadata" className={ep.layout === 'landscape' ? 'wide' : 'tall'} />}
      {can('approve_video') && <div className="spread pending">
        <span className="small">Watch it, then approve it or ask for changes.</span>
        <div className="row"><Link className="btn sm" href={c.adv('review')}>Ask for changes</Link>
          <button className="btn sm good" disabled={!!act.busy} onClick={() => act.run('video-ok', () => api(`/episodes/${ep.id}/video/approve`, {body: {comment: ''}}))}>Approve video</button></div></div>}
      {(can('approve_publish') || can('publish')) && <div className="spread pending">
        <span className="small">Check the YouTube details and approve the publication (you type PUBLISH there).</span>
        <Link className="btn sm primary" href={c.adv('publishing')}>Open publishing</Link></div>}
      {ep.publish?.youtube_url && <p className="small">Published: <a href={ep.publish.youtube_url} target="_blank" rel="noreferrer">{ep.publish.youtube_url}</a></p>}
      <Pending s={s} c={c} skip={[...(can('approve_video') ? ['review'] : []), ...(can('approve_publish') || can('publish') ? ['publishing'] : [])]} />
    </div>);
}
