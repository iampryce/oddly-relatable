'use client';
// Shot comparison (Production > Motion Model Comparison): AI video models against the rig animator on ONE line of a
// real episode, from our own approved art (the episode's set plate + the speaker's approved neutral pose) and the
// line's own recorded audio. Planning is free; each paid request shows its exact body, what it sends and its estimate,
// and runs only when you click Run. Results show side by side with the rig render, with actual cost per clip and per
// second, and every clip carries our original line audio at exactly the line's length.
import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import {DeleteButton} from '@/components/BinButtons';

const usd = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? '—' : `$${x.toFixed(d)}`);

export function ShotComparison() {
  const eps = useApi<any[]>('/episodes').data || [];
  const audioEps = eps.filter((e: any) => e.source === 'audio');
  const [eid, setEid] = useState<number | null>(null);
  const opts = useApi<any>(eid ? `/motion/shot/options?episode_id=${eid}` : null).data;
  const {data, error, reload} = useApi<any>('/motion/shot', 4000);
  const {busy, error: actError, run} = useAction(reload);
  const [pick, setPick] = useState<number>(-1);
  const [action, setAction] = useState('');
  useEffect(() => { if (opts && pick >= 0) setAction(opts.lines[pick]?.action || ''); }, [opts, pick]);
  const line = opts && pick >= 0 ? opts.lines[pick] : null;
  const plan = data?.plans?.[0];
  return (
    <div className="card stack" id="shot-comparison">
      <h2>Shot comparison: AI models vs the rig</h2>
      <p className="muted small">One recorded line of your episode. The models get only our own approved art (the episode&apos;s set plate with the speaker&apos;s approved neutral pose) and, for the avatar model, the line&apos;s own audio. Nothing from the reference video is ever sent. Planning is free; each model runs only when you click Run, after you see its request and estimate.</p>
      <ErrorBox error={error || actError} />
      <div className="row" style={{gap: 8, flexWrap: 'wrap'}}>
        <select aria-label="Episode" value={eid ?? ''} onChange={e => { setEid(e.target.value ? Number(e.target.value) : null); setPick(-1); }}>
          <option value="">Choose an audio episode</option>{audioEps.map((e: any) => <option key={e.id} value={e.id}>{e.title}</option>)}</select>
        {opts && <select aria-label="Line" value={pick} onChange={e => setPick(Number(e.target.value))}>
          <option value={-1}>Choose a line</option>
          {opts.lines.map((l: any, i: number) => <option key={i} value={i} disabled={!l.ready}>Scene {l.scene}, line {l.line + 1} · {l.speaker} · {l.seconds ?? '?'} s · {l.text.slice(0, 40)}{l.ready ? '' : ` (${l.why_not})`}</option>)}</select>}
      </div>
      {line && <>
        <label htmlFor="shot-action" className="small">Action (from the video notes&apos; words; edit before use)</label>
        <textarea id="shot-action" rows={2} value={action} onChange={e => setAction(e.target.value)} />
        <button className="btn" disabled={!!busy || action.trim().length < 3} onClick={() => run('plan', () => api('/motion/shot/plan', {body: {episode_id: eid, scene_id: line.scene_id, line: line.line, action}}))}>Plan this shot (free: first frame, line audio, rig render)</button>
      </>}
      {opts && <p className="small">Experimental budget: {usd(opts.spent_usd)} of {usd(opts.budget_usd)} used. Models: {opts.models.map((m: any) => `${m.label} (${m.price}; ${m.why})`).join(' · ')}</p>}
      {plan && <div className="stack" style={{borderTop: '1px solid var(--line, #ddd)', paddingTop: 8}}>
        <strong>Latest plan: scene line &ldquo;{plan.text}&rdquo; ({plan.seconds} s) · {plan.status}{plan.error ? `: ${plan.error}` : ''}</strong>
        <p className="small">Budget: {usd(plan.spent_usd)} of {usd(plan.budget_usd)} used.</p>
        {plan.status === 'ready' && <div className="row" style={{gap: 12, alignItems: 'flex-start', flexWrap: 'wrap'}}>
          <div className="stack small"><b>Wide first frame</b>{plan.frame_url && <img src={plan.frame_url} alt="wide first frame" style={{width: 160, borderRadius: 6}} />}</div>
          <div className="stack small"><b>Line audio (ours)</b>{plan.audio_url && <audio controls src={plan.audio_url} style={{width: 220}} />}</div>
          <div className="stack small"><b>Rig animator</b>{plan.rig_url ? <video controls src={plan.rig_url} style={{width: 160}} /> : <span className="muted">{plan.rig_error || 'not rendered'}</span>}</div>
          {(plan.requests || []).map((r: any) => (
            <div key={r.model} className="stack small" style={{maxWidth: 300}}>
              <b>{r.label}</b>
              <span>{r.price} · estimate {usd(r.estimate.usd, 3)} ({r.estimate.billed_seconds} s billed){r.estimate.note ? ` · ${r.estimate.note}` : ''}</span>
              <span className="muted">Sends: {r.sends.join(' + ')}</span>
              <label className="row" style={{gap: 4}}>First frame
                <select value={r.framing} disabled={!!busy || r.result?.status === 'queued' || r.result?.status === 'running'}
                  onChange={e => run('framing', () => api(`/motion/shot/${plan.id}/framing`, {method: 'PUT', body: {model: r.model, framing: e.target.value}}))}>
                  <option value="wide">wide (the whole set)</option><option value="medium">medium (head and upper body)</option></select></label>
              {r.frame_url && <img src={r.frame_url} alt={`${r.framing} first frame sent to ${r.label}`} style={{width: 110, borderRadius: 6}} />}
              <details><summary>Exact request</summary><pre style={{whiteSpace: 'pre-wrap'}}>{r.endpoint}{'\n'}{JSON.stringify(r.body, null, 1)}</pre></details>
              {r.result?.url ? <><video controls src={r.result.url} style={{width: 160}} /><DeleteButton kind="clip" id={r.result.asset_id} label={`the ${r.label} clip`} onDone={reload} /></> : null}
              {r.result?.binned && <span className="muted">clip in the Bin</span>}
              {r.result?.status === 'done' && <span>actual {usd(r.result.actual_usd, 3)} · {usd(r.result.per_second_usd, 3)} per second · length {r.result.check.length_ok ? 'OK' : 'off'} ({r.result.check.video_seconds} s video, {r.result.check.audio_seconds} s audio){r.result.check.held_last_frame ? ' · last frame held' : ''}</span>}
              {r.result?.status === 'failed' && <span className="bad">{r.result.error}</span>}
              {(!r.result || r.result.status === 'failed') && <button className="btn sm primary" disabled={!!busy}
                onClick={() => { if (window.confirm(`Run ${r.label} on this line: estimated ${usd(r.estimate.usd, 3)} (budget ${usd(plan.spent_usd)} of ${usd(plan.budget_usd)} used)?`)) run('run', () => api(`/motion/shot/${plan.id}/run`, {body: {model: r.model}})); }}>Run (paid)</button>}
              {(r.result?.status === 'queued' || r.result?.status === 'running') && <span className="muted">{r.result.status}…</span>}
            </div>))}
        </div>}
      </div>}
    </div>);
}
