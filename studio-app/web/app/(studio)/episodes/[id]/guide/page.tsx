'use client';
// Guided generation: every step from the uploads to the final review, in order, each with what it does, why, what it
// needs, its live cost and its status, and a help panel that walks through the current step one instruction at a time.
// Paid buttons show their price and ask first; the request carries that price (the API refuses any other with 409).
// Nothing here approves anything by itself. "Make whole episode" (the autopilot) sits on top: one budget, then it runs
// the steps and stops at every approval.
import Link from 'next/link';
import {use, useEffect, useState} from 'react';
import {api, uploadFile} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import GuideReactions from '@/components/GuideReactions';
import GuideSets from '@/components/GuideSets';
import ShotChat from '@/components/ShotChat';
import GuideTalkingShots from '@/components/GuideTalkingShots';
import Autopilot from '@/components/Autopilot';
import GuideAssembly from '@/components/GuideAssembly';
import GuideQuality from '@/components/GuideQuality';
import GuideCast from '@/components/GuideCast';
import {costText, currentStep, KIND_LABEL, moveHelp, STATUS_TEXT, STATUS_TONE, statusOf, STEPS, type GuideStep} from '@/lib/guide';

type Act = ReturnType<typeof useAction>;

export default function GuidePage({params}: {params: Promise<{id: string}>}) {
  const {id} = use(params);
  const [poll, setPoll] = useState(15000);
  const {data: g, error, reload} = useApi<any>(`/episodes/${id}/guide`, poll);
  const act = useAction(reload);
  const [help, setHelp] = useState<[number, number] | null>(null);
  useEffect(() => {
    const running = g && Object.values(g.steps).some((s: any) => s.status === 'running');
    setPoll(running ? 4000 : 15000);
    if (g && help === null) setHelp([currentStep(g), 0]);
  }, [g]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!g) return error ? <ErrorBox error={error} /> : <p className="muted">Loading…</p>;
  return (
    <>
      <div className="ep-head">
        <div>
          <p className="small" style={{margin: '0 0 4px'}}><Link href={`/episodes/${id}`}>← {g.episode.title}</Link></p>
          <h1>Guided steps</h1>
          <p className="sub">Work down the list. Each step says what it does, what it needs and what it costs.</p>
        </div>
      </div>
      <ErrorBox error={act.error} />
      <Autopilot id={id} onChange={reload} />
      <div className="gd-layout">
        <ol className="gd-steps">
          {STEPS.map((s, i) => <StepCard key={s.key} n={i + 1} s={s} g={g} id={id} act={act} reload={reload}
            current={help?.[0] === i} onHelp={() => setHelp([i, 0])} />)}
        </ol>
        {help && <HelpPanel pos={help} setPos={setHelp} />}
      </div>
    </>);
}

function HelpPanel({pos, setPos}: {pos: [number, number]; setPos: (p: [number, number]) => void}) {
  const [si, li] = pos;
  const s = STEPS[si];
  const first = si === 0 && li === 0;
  const last = si === STEPS.length - 1 && li === s.help.length - 1;
  return (
    <aside className="card gd-help" aria-label="Help" aria-live="polite">
      <div className="small muted">Help · step {si + 1} of {STEPS.length}</div>
      <h2>{s.title}</h2>
      <p className="gd-help-line">{s.help[li]}</p>
      <div className="small muted">Instruction {li + 1} of {s.help.length}</div>
      <div className="row" style={{marginTop: 10}}>
        <button className="btn sm" disabled={first} onClick={() => setPos(moveHelp(pos, -1))}>Back</button>
        <button className="btn sm primary" disabled={last} onClick={() => setPos(moveHelp(pos, 1))}>Next</button>
      </div>
    </aside>);
}

function StepCard({n, s, g, id, act, reload, current, onHelp}: {n: number; s: GuideStep; g: any; id: string; act: Act;
  reload: () => unknown; current: boolean; onHelp: () => void}) {
  const st = statusOf(g, s.key);
  const info = g.steps[s.key] || {};
  return (
    <li className={`card gd-step ${current ? 'gd-current' : ''}`}>
      <div className="spread">
        <h2 className="gd-title"><span className="gd-n">{n}</span>{s.title}</h2>
        <span className="row">
          {s.available ? <span className={`badge ${STATUS_TONE[st]}`}>{STATUS_TEXT[st]}</span>
            : <span className="badge">Not in the dashboard yet</span>}
          <button className="btn sm" onClick={onHelp}>Help</button></span>
      </div>
      <dl className="gd-facts">
        <dt>What this step does</dt><dd>{s.what}</dd>
        <dt>Why</dt><dd>{s.why}</dd>
        <dt>You need</dt><dd>{s.before}</dd>
        {s.available && <><dt>Cost</dt><dd>{info.cost ? costText(info.cost) : s.key === 'upload' ? 'Free' : 'Shown when the step can start'}</dd></>}
        {info.detail && <><dt>Where you are</dt><dd>{info.detail}</dd></>}
      </dl>
      {s.available && <div className="gd-action">
        {s.key === 'upload' && <UploadStep g={g} id={id} act={act} />}
        {s.key === 'acting' && <ActingStep id={id} onChange={reload} />}
        {s.key === 'prompts' && <PromptStep g={g} id={id} onChange={reload} />}
        {s.key === 'masters' && <GuideCast id={id} onChange={reload} />}
        {s.key === 'sets' && <><GuideSets id={id} onChange={reload} />
          <p className="small"><Link className="btn sm" href={`/episodes/${id}`}>Open the storyboard</Link>
          {' '}for the shot stills made from these pictures. Each still shows its price on its own button.</p></>}
        {(s.key === 'closeups' || s.key === 'faces' || s.key === 'movement') && <GuideReactions id={id} part={s.key} onChange={reload} />}
        {s.key === 'talking' && <GuideTalkingShots id={id} onChange={reload} />}
        {s.key === 'quality' && <GuideQuality id={id} onChange={reload} />}
        {s.key === 'assembly' && <GuideAssembly id={id} onChange={reload} />}
      </div>}
    </li>);
}

function UploadStep({g, id, act}: {g: any; id: string; act: Act}) {
  const it = g.steps.upload.items;
  const ref = it.reference_video;
  const pick = (f: File | null) => { if (f) act.run('ref', () => uploadFile(`/episodes/${id}/guide/reference-video`, f)); };
  const remove = () => { if (window.confirm('Remove the reference video?')) act.run('ref-del', () => api(`/episodes/${id}/guide/reference-video`, {method: 'DELETE'})); };
  const tick = (ok: boolean) => <span className={`badge ${ok ? 'good' : ''}`}>{ok ? '✓ Added' : 'Missing'}</span>;
  return (
    <div className="stack">
      <div className="row small">Script {tick(it.script)} Voice recording {tick(it.voice)}
        {!(it.script && it.voice) && <Link href={`/episodes/${id}`}>Add them on the episode page</Link>}</div>
      <div className="row small">Reference video {tick(!!ref)}
        {ref && <span className="muted">{(ref.size / 1048576).toFixed(1)} MB{ref.seconds ? ` · ${ref.seconds.toFixed(0)} s` : ''} · private</span>}</div>
      <div className="row">
        <label className="btn sm" style={{margin: 0, color: 'inherit'}}>
          {act.busy === 'ref' ? 'Uploading…' : ref ? 'Replace the reference video' : 'Choose the reference video'}
          <input type="file" accept="video/mp4,video/quicktime,video/webm" hidden disabled={!!act.busy}
            onChange={e => pick(e.target.files?.[0] || null)} /></label>
        {ref && <button className="btn sm" disabled={!!act.busy} onClick={remove}>Remove</button>}
      </div>
    </div>);
}

function ActingStep({id, onChange}: {id: string; onChange: () => unknown}) {
  const [poll, setPoll] = useState(15000);
  const {data: a, reload} = useApi<any>(`/episodes/${id}/acting-analysis`, poll);
  const act = useAction(async () => { await reload(); await onChange(); });
  const [free, setFree] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => { setPoll(a?.busy ? 4000 : 15000); if (a && !a.busy) onChange(); }, [a?.busy]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!a) return null;
  const est = a.estimate;
  const start = () => {
    if (!est || !window.confirm(`Acting analysis: ${est.label}. Start now? (paid, not retried by itself)`)) return;
    act.run('go', () => api(`/episodes/${id}/acting-analysis`, {body: {confirm_usd: est.usd_max, use_free_tier: free}}));
  };
  const job = a.job;
  const shots = a.result?.shots || [];
  return (
    <div className="stack">
      <ErrorBox error={act.error} />
      {!a.key_set && <p className="small bad">Add the Gemini key in <Link href="/settings">Settings › Credentials</Link> first.</p>}
      {!a.reference_video && <p className="small muted">Upload the reference video in step 1 first.</p>}
      {a.reference_video && est && <p className="small muted">{est.batches} request(s) to {est.model}, {est.video_seconds} s of video,
        {' '}shots from {a.shots_from === 'storyboard' ? 'your storyboard' : `${a.shots.length} even slices of the video (no storyboard yet)`}.</p>}
      <label className="row small" style={{fontWeight: 400, color: 'inherit'}}>
        <input type="checkbox" style={{width: 'auto'}} checked={free} onChange={e => setFree(e.target.checked)} />
        Use the free tier if the paid model is busy ({(a.free_models || []).join(', ')}). The free tier may let Google use the video to train its models.</label>
      <div className="row">
        <button className="btn primary" disabled={!!act.busy || a.busy || !est || !a.key_set || !a.reference_video} onClick={start}>
          {a.busy ? 'Analysing…' : a.result ? 'Analyse again' : 'Analyse the acting'}{est ? ` · up to $${est.usd_max.toFixed(2)}` : ''}</button>
        {a.result && !a.accepted && <button className="btn good" disabled={!!act.busy} onClick={() => act.run('ok', () => api(`/episodes/${id}/acting-analysis/accept`, {method: 'POST'}))}>These notes look right</button>}
        {a.result && <button className="btn sm" onClick={() => setOpen(!open)}>{open ? 'Hide the notes' : `Show the notes (${shots.length} shots)`}</button>}
      </div>
      {job && job.status === 'failed' && <p className="small bad">The last run failed: {job.error}</p>}
      {a.partial && <p className="small warn">Stopped early: {a.partial}. The shots that came back are kept.</p>}
      {a.result && <p className="small muted">Last run: {(a.model_used || []).join(', ')} · {a.usage?.input_tokens?.toLocaleString('en-US')} in / {a.usage?.output_tokens?.toLocaleString('en-US')} out tokens · ${(a.usd || 0).toFixed(4)}</p>}
      {open && <div className="stack">{shots.map((s: any) => (
        <div key={s.shot} className="gd-shot">
          <div className="gd-shot-text">
            <strong>Shot {s.shot}</strong> <span className="small muted">{s.what_the_reference_shows}</span>
            <ul className="small gd-beats">{(s.beats || []).map((b: any, i: number) => (
              <li key={i}><span className="mono">{b.t_start}–{b.t_end} s</span> <strong>{b.character}</strong>
                {b.on_word ? <> on &ldquo;{b.on_word}&rdquo;</> : null}: {[b.expression, b.eyes_and_gaze, b.head_and_body, b.hands].filter(Boolean).join('; ')}
                {b.intensity ? <span className="muted"> ({b.hold_or_move}, {b.intensity})</span> : null}</li>))}</ul>
          </div>
          {(a.frames?.[String(s.shot)] || []).length > 0 && <figure className="gd-frames">
            {a.frames[String(s.shot)].map((f: any) => <a key={f.t} href={f.url} target="_blank" rel="noreferrer"><img src={f.url} alt={`Reference at ${f.t} s`} loading="lazy" /></a>)}
            <figcaption className="small muted">Reference — private, never sent to an image or video generator</figcaption>
          </figure>}
          <div className="gd-shot-chat"><ShotChat step="acting" item={s.shot} episodeId={id} onApplied={reload} /></div>
        </div>))}</div>}
    </div>);
}

function PromptStep({g, id, onChange}: {g: any; id: string; onChange: () => unknown}) {
  const {data: list, reload} = useApi<any>(`/episodes/${id}/prompts`);
  const act = useAction(async () => { await reload(); await onChange(); });
  const [kind, setKind] = useState('still');
  const [character, setCharacter] = useState<string>('');
  const [shot, setShot] = useState<string>('');
  const [notes, setNotes] = useState('');
  const [est, setEst] = useState<any>(null);
  const [estErr, setEstErr] = useState('');
  const chars: any[] = g.steps.masters?.characters || [];
  const body = {kind, notes, character_id: character ? Number(character) : null, shot: shot ? Number(shot) : null};
  useEffect(() => {
    setEst(null); setEstErr('');
    if (!notes.trim() && !shot && !character) return;
    const t = setTimeout(() => api(`/episodes/${id}/prompts/estimate`, {body}).then(setEst, e => setEstErr(e.message)), 500);
    return () => clearTimeout(t);
  }, [kind, character, shot, notes]);   // eslint-disable-line react-hooks/exhaustive-deps
  const write = () => {
    if (!est || !window.confirm(`Write a ${KIND_LABEL[kind].toLowerCase()} prompt with ${est.model}: about $${est.usd_typical.toFixed(4)}, at most $${est.usd_max.toFixed(4)}. Send now? (paid, not retried by itself)`)) return;
    act.run('write', () => api(`/episodes/${id}/prompts/write`, {body: {...body, confirm_usd: est.usd_max}}));
  };
  return (
    <div className="stack">
      <ErrorBox error={act.error} />
      {list && !list.key_set && <p className="small bad">Add the OpenAI key in <Link href="/settings">Settings › Credentials</Link> first.</p>}
      <div className="grid cols-3">
        <div><label htmlFor="pw-kind">What you are making</label>
          <select id="pw-kind" value={kind} onChange={e => setKind(e.target.value)}>
            {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
        <div><label htmlFor="pw-char">Character</label>
          <select id="pw-char" value={character} onChange={e => setCharacter(e.target.value)}>
            <option value="">{kind === 'master' ? 'Choose…' : 'None'}</option>
            {chars.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></div>
        <div><label htmlFor="pw-shot">Shot number (adds its acting notes)</label>
          <input id="pw-shot" type="number" min={1} value={shot} onChange={e => setShot(e.target.value)} /></div>
      </div>
      <div><label htmlFor="pw-notes">Your notes for this shot or beat</label>
        <textarea id="pw-notes" rows={3} maxLength={6000} value={notes} onChange={e => setNotes(e.target.value)}
          placeholder="e.g. Ann reads the letter, freezes, then slowly looks up at Bob." /></div>
      <div className="spread small">
        <span className={estErr ? 'bad' : 'muted'} role="status">{estErr || (est ? `${est.model}: about $${est.usd_typical.toFixed(4)}, at most $${est.usd_max.toFixed(4)}${est.uses_acting ? ' · acting notes included' : ''}` : '')}</span>
        <button className="btn primary" disabled={!!act.busy || !est || !list?.key_set} onClick={write}>
          {act.busy === 'write' ? 'Writing…' : est ? `Write prompt · up to $${est.usd_max.toFixed(4)}` : 'Write prompt'}</button>
      </div>
      {(list?.prompts || []).map((p: any) => <PromptItem key={p.id} p={p} id={id} act={act} chars={chars} />)}
      {list && list.usd > 0 && <p className="small muted">Prompts for this episode so far: ${list.usd.toFixed(4)}</p>}
    </div>);
}

function PromptItem({p, id, act, chars}: {p: any; id: string; act: Act; chars: any[]}) {
  const [text, setText] = useState(p.text);
  useEffect(() => { setText(p.text); }, [p.text]);
  const who = chars.find(c => c.id === p.character_id)?.name;
  const save = (approve: boolean) => act.run(`p${p.id}`, () => api(`/episodes/${id}/prompts/${p.id}`, {method: 'PUT', body: {text, approve}}));
  const remove = () => { if (window.confirm('Delete this prompt?')) act.run(`d${p.id}`, () => api(`/episodes/${id}/prompts/${p.id}`, {method: 'DELETE'})); };
  return (
    <div className="gd-prompt">
      <div className="spread small">
        <span><strong>{KIND_LABEL[p.kind]}</strong>{who ? ` · ${who}` : ''}{p.shot ? ` · shot ${p.shot}` : ''}
          <span className="muted"> · {p.model} · {p.usage.input_tokens} in / {p.usage.output_tokens} out tokens · ${p.usd.toFixed(4)}</span></span>
        <span className={`badge ${p.status === 'approved' ? 'good' : 'warn'}`}>{p.status === 'approved' ? 'Ready to use' : 'Check and edit'}</span>
      </div>
      <textarea aria-label="Prompt text" rows={5} value={text} onChange={e => setText(e.target.value)} />
      <div className="row">
        <button className="btn sm" disabled={!!act.busy || text === p.text} onClick={() => save(false)}>Save changes</button>
        {(p.status !== 'approved' || text !== p.text) && <button className="btn sm good" disabled={!!act.busy || !text.trim()} onClick={() => save(true)}>Use this prompt</button>}
        <button className="btn sm danger" disabled={!!act.busy} onClick={remove}>Delete</button>
      </div>
      <ShotChat step="prompt" item={p.id} episodeId={id} onApplied={() => act.run(`c${p.id}`, async () => {})} />
    </div>);
}

