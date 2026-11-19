'use client';
import {api} from '@/lib/api';

// Long-form production: each segment (at most 58 s), its scenes, status, render time and video; failed segments retry alone.
export default function SegmentsPanel({ep, act}: {ep: any; act: any}) {
  const segs = ep.segments || [];
  const join = ep.jobs.find((j: any) => j.kind === 'join_segments' && j.revision === ep.revision);
  const plan = ep.jobs.find((j: any) => j.kind === 'plan_segments' && j.revision === ep.revision);
  if (!segs.length && !plan) return null;
  const total = segs.reduce((t: number, s: any) => t + s.seconds, 0);
  const done = segs.filter((s: any) => s.status === 'done').length;
  return (
    <div className="card">
      <div className="spread"><h2 style={{margin: 0}}>Segments (revision {ep.revision})</h2>
        <span className="muted small">{done} of {segs.length} ready · {total.toFixed(1)} s{join ? ` · join ${join.status}` : ''}</span></div>
      {plan?.status === 'failed' && <div className="alert bad small">Segment planning failed: {plan.error}</div>}
      {join?.status === 'failed' && <div className="alert bad small">Joining failed: {join.error}
        <button className="btn sm" style={{marginLeft: 8}} onClick={() => act.run('retry', () => api(`/jobs/${join.id}/retry`, {method: 'POST'}))}>Retry join</button></div>}
      <div className="table-wrap"><table>
        <thead><tr><th>#</th><th>Scenes</th><th>Length</th><th>Status</th><th>Render</th><th></th></tr></thead>
        <tbody>{segs.map((s: any) => (
          <tr key={s.id}>
            <td>{s.position}</td>
            <td className="small mono">{s.parts.map((p: any) => `${p.scene}${p.lines[0] > 0 ? ` (from line ${p.lines[0] + 1})` : ''}`).join(', ')}</td>
            <td>{s.seconds.toFixed(1)} s</td>
            <td><span className={`badge ${s.status === 'done' ? 'good' : s.status === 'failed' ? 'bad' : s.status === 'rendering' ? 'busy' : 'warn'}`}>{s.reused_from ? 'reused (unchanged)' : s.status}</span>
              {s.error && <div className="small" style={{color: 'var(--bad)'}}>{s.error}</div>}</td>
            <td className="small muted">{s.render_seconds ? `${s.render_seconds} s` : s.reused_from ? '—' : ''}</td>
            <td><div className="row" style={{justifyContent: 'flex-end'}}>
              {s.video && <a className="btn sm" href={s.video.url} target="_blank" rel="noreferrer">Preview</a>}
              {s.status === 'failed' && s.job_id && <button className="btn sm primary" disabled={!!act.busy} onClick={() => act.run('retry', () => api(`/jobs/${s.job_id}/retry`, {method: 'POST'}))}>Retry segment</button>}
            </div></td>
          </tr>))}</tbody>
      </table></div>
    </div>
  );
}
