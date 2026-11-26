'use client';
// Guided page, step 9 "Talking shots" (API: talking_s2v.py). One row per talking shot of the storyboard: the approved
// still (click the character's head once if the marker is wrong), the line, the voice-only audio, the movement-guide
// status, the prompt (editable; written by GPT, or the labelled template), the shot's own cost and Render / Re-render.
// "Render all talking shots" shows the total first. Paid buttons ask first and send the "at most" amount they showed
// (the API refuses anything else with 409). Results wait for the owner's Approve click; nothing approves itself.
// Under every result video sits <ShotThreadSlot />, the mount point for the per-shot chat thread.
import Link from 'next/link';
import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import ShotThreadSlot from '@/components/ShotThreadSlot';
import {clickToStill, guideBadge, isActive, piecesText, progress, renderCost, usd} from '@/lib/talkingGuide';

type Act = ReturnType<typeof useAction>;

export default function GuideTalkingShots({id, onChange}: {id: string; onChange: () => unknown}) {
  const [poll, setPoll] = useState(15000);
  const {data: t, error, reload} = useApi<any>(`/episodes/${id}/talking`, poll);
  const act = useAction(async () => { await reload(); await onChange(); });
  const [now, setNow] = useState(() => Date.now() / 1000);
  const running = !!t && (t.busy || (t.shots || []).some((s: any) => isActive(s.run)));
  useEffect(() => { setPoll(running ? 4000 : 15000); if (t && !running) onChange(); }, [running]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!running) return;
    const h = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(h);
  }, [running]);
  if (!t) return error ? <ErrorBox error={error} /> : <p className="small muted">Loading…</p>;
  const av = t.availability || {};
  const total = t.total || {};
  const renderable = (t.shots || []).filter((s: any) => !s.blocked);
  const renderAll = () => {
    if (!window.confirm(`Render ${renderable.length} talking shot(s) on a rented GPU: ${renderCost(total)}`
      + `${total.sessions > 1 ? `, in ${total.sessions} GPU sessions` : ''}. The GPU is turned off when they are done. Start now?`)) return;
    act.run('all', () => api(`/episodes/${id}/talking/render`, {body: {shots: null, confirm_usd: total.usd_max}}));
  };
  return (
    <div className="stack">
      <ErrorBox error={act.error} />
      <div className="small" style={{maxWidth: 760}}>
        <p style={{margin: '0 0 6px'}}>Each talking shot is made by Wan 2.2 Speech-to-Video on a rented GPU. It starts from the
          approved still and moves the mouth to a voice-only copy of your line: everything except the speaker&rsquo;s own
          words is muted, so laughter or other voices do not move the mouth. The finished episode keeps your original audio.</p>
        <p style={{margin: 0}}>If the reference video shows the speaker&rsquo;s actor, the shot can also follow his head
          movement. Only a stick-figure skeleton of the head is drawn from the reference; its picture is never sent to any
          generator. Each result waits for your Approve.</p>
      </div>
      {!av.ok && av.reason && <p className="small bad">{av.reason}{' '}<Link href="/settings#gpu-worker">Open Settings</Link></p>}
      {av.ok && <p className="small muted">GPU: {(av.gpus || []).map((g: any) => `${g.id.replace('NVIDIA ', '')} ${usd(g.usd_per_hour)}/h`).join(', then ')}
        {!av.allow_expensive_gpus && ' (the A100 is off: Settings › GPU worker)'} · this month {usd(av.spent_usd)} of {usd(av.cap_usd)}</p>}
      {!t.reference_video && <p className="small muted">No reference video: the shots render without a movement guide.</p>}
      {(t.shots || []).length === 0 && <p className="small muted">No talking shots yet. They come from the storyboard: a shot where the person speaking is on screen.</p>}
      {(t.shots || []).length > 0 && <div className="row">
        <button className="btn primary" disabled={!!act.busy || t.busy || !av.ok || renderable.length === 0} onClick={renderAll}>
          {t.busy ? 'Rendering…' : `Render all talking shots${total.usd_max ? ` · up to ${usd(total.usd_max)}` : ''}`}</button>
        {renderable.length > 0 && <span className="small muted">{renderable.length} shot(s): {renderCost(total)}</span>}
        {t.busy && <button className="btn sm danger" disabled={!!act.busy} onClick={() => window.confirm('Turn the rented GPU off now? The shot rendering now fails and can be rendered again.')
          && act.run('stop', () => api(`/episodes/${id}/talking/stop`, {method: 'POST'}))}>Stop the GPU now</button>}
      </div>}
      {t.job?.status === 'failed' && <p className="small bad">The last render stopped: {t.job.error}</p>}
      {(t.shots || []).map((s: any) => <ShotRow key={s.index} s={s} id={id} act={act} busy={t.busy} canRun={av.ok} now={now} openaiKey={t.openai_key} />)}
      {t.settings && <p className="small muted">Settings &ldquo;B&rdquo;: {t.settings.steps} steps, CFG {t.settings.cfg}, {t.settings.sampler}/{t.settings.scheduler},
        shift {t.settings.shift}, {t.settings.size.join('×')} at {t.settings.fps} fps, pieces of up to {t.settings.piece_frames} frames.
        The first {t.settings.trim_start_frames} frames of each result are trimmed at assembly.</p>}
    </div>);
}

function ShotRow({s, id, act, busy, canRun, now, openaiKey}: {s: any; id: string; act: Act; busy: boolean; canRun: boolean;
  now: number; openaiKey: boolean}) {
  const [text, setText] = useState(s.prompt?.text || '');
  const [marks, setMarks] = useState(false);
  useEffect(() => { setText(s.prompt?.text || ''); }, [s.prompt?.text]);
  const head = s.still?.head;
  const g = guideBadge(s.guide);
  const prog = progress(s.run, now);
  const pe = s.prompt_estimate;
  const put = (body: any, label: string) => act.run(`${label}${s.index}`, () => api(`/episodes/${id}/talking/${s.index}`, {method: 'PUT', body}));
  const clickHead = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const p = clickToStill(e.clientX - r.left, e.clientY - r.top, r.width, r.height);
    if (window.confirm(`Set ${s.name}'s head here (${p.x}, ${p.y})? The movement guide is lined up with it.`)) put({head: p}, 'h');
  };
  const writePrompt = () => {
    if (openaiKey && !window.confirm(`Write this shot's prompt with ${pe?.model}: about ${usd(pe?.usd_typical, 4)}, at most ${usd(pe?.usd_max, 4)}. Send now?`)) return;
    act.run(`w${s.index}`, () => api(`/episodes/${id}/talking/${s.index}/write-prompt`, {body: {confirm_usd: pe?.usd_max ?? 0}}));
  };
  const renderOne = () => {
    if (text !== s.prompt?.text) { window.alert('Save the prompt first.'); return; }
    if (!window.confirm(`Render talking shot ${s.index} on a rented GPU: ${renderCost(s.estimate)} (includes starting the GPU). Start now?`)) return;
    act.run(`r${s.index}`, () => api(`/episodes/${id}/talking/render`, {body: {shots: [s.index], confirm_usd: s.estimate.usd_max}}));
  };
  return (
    <div className="card stack" style={{padding: 12}}>
      <div className="spread">
        <strong>Shot {s.index} · {s.name} <span className="small muted">{s.t0.toFixed(1)}–{s.t1.toFixed(1)} s · {piecesText(s.pieces)}</span></strong>
        <span className="row">
          {s.approved ? <span className="badge good">Approved</span> : s.renders.length > 0 ? <span className="badge warn">Needs your approval</span> : null}
          {s.blocked && <span className="badge">{s.blocked}</span>}
        </span>
      </div>
      <div style={{display: 'grid', gridTemplateColumns: 'minmax(180px, 280px) minmax(0, 1fr)', gap: 12}}>
        <div className="stack" style={{gap: 6}}>
          {s.still?.url ? <div role="button" tabIndex={0} aria-label="Click the character's head" onClick={clickHead}
            style={{position: 'relative', aspectRatio: '16 / 9', cursor: 'crosshair', borderRadius: 6, overflow: 'hidden', border: '1px solid var(--line)'}}>
            <img src={s.still.url} alt={`Shot ${s.index} still`} style={{width: '100%', height: '100%', objectFit: 'cover', display: 'block'}} />
            {head?.x != null && <span title={`head (${head.source === 'owner' ? 'set by you' : 'found automatically'})`} style={{position: 'absolute',
              left: `${(head.x / 1024) * 100}%`, top: `${(head.y / 576) * 100}%`, width: 12, height: 12, marginLeft: -6, marginTop: -6,
              borderRadius: '50%', border: '2px solid #e5484d', background: 'rgba(229,72,77,0.25)'}} />}
          </div> : <div className="small muted">No still yet</div>}
          {s.still?.url && <span className="small muted">{head?.x != null ? `Head ${head.source === 'owner' ? 'set by you' : 'found automatically'}: click the still to move it.`
            : 'Click the character’s head on the still.'}</span>}
          {s.voice_url ? <audio controls src={s.voice_url} style={{width: '100%'}} aria-label="Voice-only audio" />
            : <span className="small muted">Voice-only audio: made when rendering</span>}
        </div>
        <div className="stack" style={{gap: 8}}>
          <div className="small">&ldquo;{s.text || '…'}&rdquo;</div>
          <div className="row small">
            {g.text && <span className={`badge ${g.tone}`}>{g.text}</span>}
            <label className="row" style={{fontWeight: 400, color: 'inherit', margin: 0}}>
              <input type="checkbox" style={{width: 'auto'}} checked={s.guide?.on !== false} disabled={!!act.busy}
                onChange={e => put({guide: e.target.checked}, 'g')} /> Follow the actor&rsquo;s head</label>
            {s.guide?.signature && <span className="muted">Actor: {s.guide.signature}</span>}
            {(s.ref_frames || []).length > 0 && <button className="btn sm" onClick={() => setMarks(!marks)}>{marks ? 'Hide' : 'Which person is the actor?'}</button>}
          </div>
          {marks && <div className="stack small" style={{gap: 4}}>
            <span className="muted">Click a reference frame that shows {s.name}&rsquo;s actor. Your marks replace the automatic choice. (Private: never sent to a generator.)</span>
            <div className="row" style={{flexWrap: 'wrap', gap: 6}}>
              {s.ref_frames.map((f: any) => {
                const on = (s.actor_marks || []).includes(Math.round(f.t * 100) / 100);
                return <button key={f.t} className="btn sm" style={{padding: 2, outline: on ? '2px solid var(--good)' : 'none'}} disabled={!!act.busy}
                  onClick={() => act.run(`m${s.index}`, () => api(`/episodes/${id}/talking/actor`, {body: {character: s.speaker, t: f.t}}))}>
                  <img src={f.url} alt={`Reference at ${f.t} s`} style={{width: 96, display: 'block', borderRadius: 4}} /></button>;
              })}
              {(s.actor_marks || []).length > 0 && <button className="btn sm" disabled={!!act.busy}
                onClick={() => act.run(`m${s.index}`, () => api(`/episodes/${id}/talking/actor`, {body: {character: s.speaker, clear: true}}))}>Clear my marks</button>}
            </div>
          </div>}
          <div>
            <div className="spread small"><label htmlFor={`tp${s.index}`} style={{margin: 0}}>Prompt</label>
              <span className={`badge ${s.prompt?.source === 'gpt' ? 'good' : 'warn'}`}>{s.prompt?.label}{s.prompt?.edited ? ' · edited' : ''}</span></div>
            <textarea id={`tp${s.index}`} rows={4} value={text} onChange={e => setText(e.target.value)} maxLength={4000} />
            <div className="row">
              <button className="btn sm" disabled={!!act.busy || text === s.prompt?.text || !text.trim()} onClick={() => put({prompt: text}, 'p')}>Save prompt</button>
              <button className="btn sm" disabled={!!act.busy} onClick={writePrompt}>
                {openaiKey ? `Write with GPT · up to ${usd(pe?.usd_max, 4)}` : 'Use the template (no OpenAI key)'}</button>
            </div>
          </div>
          <div className="row">
            <button className="btn primary sm" disabled={!!act.busy || busy || !canRun || !!s.blocked} onClick={renderOne}>
              {s.renders.length ? 'Re-render' : 'Render'} · up to {usd(s.estimate?.usd_max)}</button>
            <span className="small muted">{renderCost(s.estimate)}</span>
          </div>
          {prog.label && <div className="stack" style={{gap: 4}} aria-live="polite">
            <span className={`small ${s.run?.status === 'failed' ? 'bad' : ''}`}>{prog.label}</span>
            {prog.pct !== null && <div style={{height: 6, background: 'var(--panel-2)', borderRadius: 3, overflow: 'hidden'}}
              role="progressbar" aria-valuenow={prog.pct} aria-valuemin={0} aria-valuemax={100}>
              <div style={{width: `${prog.pct}%`, height: '100%', background: 'var(--busy)'}} /></div>}
          </div>}
        </div>
      </div>
      {s.renders.length > 0 && <div className="row" style={{flexWrap: 'wrap', alignItems: 'flex-start', gap: 12}}>
        {s.renders.map((r: any) => <Result key={r.id} r={r} s={s} id={id} act={act} />)}
      </div>}
    </div>);
}

function Result({r, s, id, act}: {r: any; s: any; id: string; act: Act}) {
  const approved = s.approved === r.id;
  const setApproved = (rid: string | null) => act.run(`a${r.id}`, () => api(`/episodes/${id}/talking/${s.index}/approve`, {body: {render_id: rid}}));
  return (
    <figure style={{margin: 0, width: 300}} className="stack">
      <video controls src={r.preview_url || r.url} style={{width: '100%', borderRadius: 6, background: '#000'}} />
      <figcaption className="small muted">
        {new Date(r.at * 1000).toLocaleString('en-GB')} · {r.gpu} · {Math.round(r.seconds / 60)} min · {usd(r.usd, 3)}
        {' '}· {r.guide?.used ? `guide ${Math.round((r.guide.coverage || 0) * 100)}%` : 'no guide'}
        {r.prompt_source === 'template' ? ' · template prompt' : ''}
      </figcaption>
      <div className="row">
        {approved ? <><span className="badge good">Approved</span><button className="btn sm" disabled={!!act.busy} onClick={() => setApproved(null)}>Withdraw</button></>
          : <button className="btn sm good" disabled={!!act.busy} onClick={() => setApproved(r.id)}>Approve</button>}
      </div>
      <ShotThreadSlot item={{episodeId: id, step: 'talking', shot: s.index, renderId: r.id, assetId: r.asset_id ?? null}} />
    </figure>);
}
