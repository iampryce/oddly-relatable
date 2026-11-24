'use client';
// Storyboard frames: painted frames for the episode's shot list, made with the image provider chosen in Settings
// (Codex on the ChatGPT plan at $0, or OpenAI at a price shown first). One job makes the chosen frames one at a time
// and stops at the first failure. Frames are drafts; only the owner approves one, with their own click.
import {useState} from 'react';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox, JobStatus} from '@/components/ui';

const fmt = (s?: number | null) => s == null ? '' : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

export default function StoryboardFrames({episodeId}: {episodeId: number}) {
  const {data, reload} = useApi<any>(`/episodes/${episodeId}/storyboard-frames`, 4000);
  const {busy, error, run} = useAction(reload);
  const [pick, setPick] = useState<Record<string, boolean>>({});
  const [est, setEst] = useState<any>(null);
  const [open, setOpen] = useState<string>('');
  if (!data) return null;
  const frames: any[] = data.frames || [];
  const chosen = frames.filter(f => pick[f.frame]).map(f => f.frame);
  const notMade = frames.filter(f => !f.latest).map(f => f.frame);
  const made = frames.filter(f => f.latest).length, approved = frames.filter(f => f.approved_asset_id).length;
  const running = ['queued', 'running'].includes(data.job?.status);

  const choose = (ids: string[]) => { setEst(null); setPick(Object.fromEntries(ids.map(i => [i, true]))); };
  const estimate = () => run('estimate', async () => setEst(await api(`/episodes/${episodeId}/storyboard-frames/estimate`, {method: 'POST', body: {frames: chosen}})));
  const make = () => run('make', async () => {
    await api(`/episodes/${episodeId}/storyboard-frames/make`, {method: 'POST', body: {frames: chosen, confirm_total: est?.total ?? 0}});
    setEst(null); setPick({});
  });

  return (
    <div className="card stack" id="storyboard-frames">
      <div className="spread"><h2>Storyboard frames</h2>
        <span className="muted small">{frames.length} frames · {made} made · {approved} approved · <span className="badge">{data.status}</span></span></div>
      <p className="muted small">Made with the image provider in Settings ({data.provider === 'codex-cli' ? 'Codex, ChatGPT plan: $0 per frame' : data.provider === 'openai' ? 'OpenAI: priced per frame, shown before you start' : 'none chosen'}).
        One frame at a time; stops at the first failure and never retries by itself. Reference images are our own approved art only.</p>
      <ErrorBox error={error} />
      {frames.length === 0 && <div className="muted">No frame plan yet. The plan (frames, prompts, references, shots) is uploaded for the episode first.</div>}
      {data.job && <div className="small">Last run ({(data.job.result?.made || []).length} made): <JobStatus status={data.job.status} /> {data.job.error ? <span className="muted">{data.job.error}</span> : null}</div>}
      {frames.length > 0 && !running && (
        <div className="row">
          <button className="btn sm" onClick={() => choose(notMade)} disabled={!notMade.length}>Select not made ({notMade.length})</button>
          <button className="btn sm" onClick={() => choose([])} disabled={!chosen.length}>Clear</button>
          <button className="btn" disabled={!!busy || !chosen.length} onClick={estimate}>Check cost for {chosen.length} frame{chosen.length === 1 ? '' : 's'}</button>
          {est && <>
            <span className="badge good">{est.label}</span>
            <button className="btn primary" disabled={!!busy} onClick={make}>{est.total > 0 ? `Make ${est.frames} frames (up to $${est.total.toFixed(2)})` : `Make ${est.frames} frames ($0)`}</button></>}
        </div>)}
      <div className="grid cols-3">
        {frames.map(f => {
          const img = f.latest?.asset?.url;
          const isApproved = f.approved_asset_id && f.approved_asset_id === f.latest?.asset_id;
          return (
            <div key={f.frame} className="card stack" style={{padding: 10}}>
              <div className="spread">
                <label className="small"><input type="checkbox" disabled={running} checked={!!pick[f.frame]} onChange={e => { setEst(null); setPick(o => ({...o, [f.frame]: e.target.checked})); }} /> <strong>{f.frame}</strong> {f.title}</label>
                {f.approved_asset_id ? <span className="badge good">approved</span> : f.latest ? <span className="badge warn">draft</span> : <span className="badge">not made</span>}
              </div>
              {img ? <a href={img} target="_blank" rel="noopener noreferrer"><img src={img} alt={`Storyboard frame ${f.frame}`} style={{width: '100%', borderRadius: 6}} /></a>
                : <div className="muted small" style={{aspectRatio: '16/9', display: 'grid', placeItems: 'center', background: 'var(--panel-2, #0001)', borderRadius: 6}}>not made yet</div>}
              <div className="muted small">Shots {f.shots.map((s: any) => s.n).join(', ') || '—'}{f.shots[0]?.start != null && ` · ${fmt(f.shots[0].start)}–${fmt(f.shots[f.shots.length - 1].end)}`}
                {f.latest && ` · ${f.latest.provider}${f.latest.seconds ? `, ${Math.round(f.latest.seconds)} s` : ''}`}{f.made.length > 1 && ` · ${f.made.length} versions`}</div>
              {f.missing_refs.length > 0 && <div className="alert warn small">Missing references: {f.missing_refs.join(', ')}</div>}
              <div className="row">
                {f.latest && !isApproved && <button className="btn sm" disabled={!!busy} onClick={() => run('approve', () => api(`/episodes/${episodeId}/storyboard-frames/frames/${f.frame}/approve?asset_id=${f.latest.asset_id}`, {method: 'POST'}))}>Approve this version</button>}
                {f.approved_asset_id && <button className="btn sm" disabled={!!busy} onClick={() => run('unapprove', () => api(`/episodes/${episodeId}/storyboard-frames/frames/${f.frame}/unapprove`, {method: 'POST'}))}>Withdraw approval</button>}
                <button className="btn sm" onClick={() => setOpen(open === f.frame ? '' : f.frame)}>{open === f.frame ? 'Hide prompt' : 'Prompt'}</button>
              </div>
              {open === f.frame && <pre className="small" style={{whiteSpace: 'pre-wrap', maxHeight: 240, overflow: 'auto'}}>{f.prompt}</pre>}
            </div>);
        })}
      </div>
    </div>);
}
