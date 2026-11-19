'use client';
import Link from 'next/link';
import {api, when} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {EpisodeTable, ErrorBox, JobStatus} from '@/components/ui';
import {MotionComparison} from '@/components/MotionComparison';

export default function Production() {
  const {data: eps} = useApi<any[]>('/episodes?stage=producing,production_failed,storyboard_approved', 5000);
  const {data: jobs, error, reload} = useApi<any[]>('/jobs?limit=150', 4000);
  const act = useAction(reload);
  const failed = (jobs || []).filter(j => j.status === 'failed');
  const active = (jobs || []).filter(j => j.status === 'queued' || j.status === 'running');
  const table = (rows: any[], empty: string) => !rows.length ? <p className="muted">{empty}</p> : (
    <div className="table-wrap"><table>
      <thead><tr><th>Job</th><th>Step</th><th>Episode</th><th>Status</th><th>Detail</th><th>Time</th><th></th></tr></thead>
      <tbody>{rows.map(j => (
        <tr key={j.id}>
          <td className="mono">#{j.id}</td><td>{j.kind.replace(/_/g, ' ')}</td>
          <td>{j.episode_id ? <Link href={`/episodes/${j.episode_id}`}>Episode {j.episode_id}</Link> : j.character_id ? <Link href="/characters">Character</Link> : '—'}</td>
          <td><JobStatus status={j.status} />{j.attempts > 1 && <span className="badge" title="automatic retries of temporary provider errors">attempt {j.attempts}</span>}</td>
          <td className="small">{j.error ? <span style={{color: 'var(--bad)'}}>{j.error}</span> : (j.progress?.stages || []).map((s: any) => `${s.stage} ${s.status === 'done' ? '✓' : '…'}`).join(' · ')}</td>
          <td className="muted small">{when(j.started_at || j.created_at)}</td>
          <td>{j.status === 'failed' && <button className="btn sm primary" disabled={!!act.busy} onClick={() => act.run('retry', () => api(`/jobs/${j.id}/retry`, {method: 'POST'}))}>Retry</button>}</td>
        </tr>))}
      </tbody></table></div>);
  return (
    <>
      <h1>Production</h1><p className="sub">Image generation, scene preparation, voice and rendering. Failed jobs can be retried on their own.</p>
      <ErrorBox error={error || act.error} />
      <MotionComparison />
      <h2>Episodes in production</h2>
      {eps && <EpisodeTable episodes={eps} empty="No episode is in production." />}
      <div className="card" style={{marginTop: 16}}><h2>Running and queued ({active.length})</h2>{table(active, 'Nothing is running.')}</div>
      <div className="card" style={{marginTop: 16}}><h2>Failed ({failed.length})</h2>{table(failed, 'No failed jobs.')}</div>
      <div className="card" style={{marginTop: 16}}><h2>Recent jobs</h2>{table((jobs || []).slice(0, 40), 'No jobs yet.')}</div>
    </>
  );
}
