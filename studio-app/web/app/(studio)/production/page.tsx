'use client';
import Link from 'next/link';
import {api, when} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {EpisodeTable, ErrorBox, JobStatus} from '@/components/ui';
import {MotionComparison} from '@/components/MotionComparison';
import {useState} from 'react';
import {recentRows} from '@/lib/jobsView';
import {BulkDelete, DeleteButton} from '@/components/BinButtons';
import {ShotComparison} from '@/components/ShotComparison';

export default function Production() {
  const {data: eps} = useApi<any[]>('/episodes?stage=producing,production_failed,storyboard_approved', 5000);
  const {data: jobs, error, reload} = useApi<any[]>('/jobs?limit=150', 4000);
  const act = useAction(reload);
  const [more, setMore] = useState(false);
  const clearOne = (j: any) => {
    if (!window.confirm(`Clear failed job #${j.id} (${j.kind.replace(/_/g, ' ')})? It is hidden here; nothing is deleted.`)) return;
    act.run('clear', () => api(`/jobs/${j.id}/clear`, {method: 'POST'}));
  };
  const clearOld = () => act.run('clear-all', async () => {
    const p: any = await api('/jobs/clear-failed', {body: {confirm: false}});
    const kept = p.kept.length ? `\n\n${p.kept.length} stay, because production still needs them:\n` + p.kept.map((k: any) => `#${k.id}: ${k.reason}`).join('\n') : '';
    if (!p.count) { window.alert('No failed job from before today can be cleared.' + kept); return; }
    if (window.confirm(`Clear ${p.count} failed job(s) from before today? They are hidden here; nothing is deleted.${kept}`)) await api('/jobs/clear-failed', {body: {confirm: true}});
  });
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
          <td className="row" style={{gap: 4}}>{j.status === 'failed' && <button className="btn sm primary" disabled={!!act.busy} onClick={() => act.run('retry', () => api(`/jobs/${j.id}/retry`, {method: 'POST'}))}>Retry</button>}
            {j.status === 'failed' && (j.keep_reason ? <span className="muted small" title={j.keep_reason}>kept: {j.keep_reason}</span>
              : <button className="btn sm" disabled={!!act.busy} onClick={() => clearOne(j)}>Clear</button>)}</td>
        </tr>))}
      </tbody></table></div>);
  return (
    <>
      <h1>Production</h1><p className="sub">Image generation, scene preparation, voice and rendering. Failed jobs can be retried on their own.</p>
      <ErrorBox error={error || act.error} />
      <ShotComparison />
      <MotionComparison />
      <div className="spread"><h2>Episodes in production</h2><BulkDelete what="episodes" label="Delete failed episodes" onDone={reload} /></div>
      {eps && <EpisodeTable episodes={eps} empty="No episode is in production." />}
      <div className="card" style={{marginTop: 16}}><h2>Running and queued ({active.length})</h2>{table(active, 'Nothing is running.')}</div>
      <div className="card" style={{marginTop: 16}}><div className="spread"><h2>Failed ({failed.length})</h2>
        {failed.length > 0 && <button className="btn sm" disabled={!!act.busy} onClick={clearOld}>Clear all failed jobs older than today</button>}</div>
        <p className="muted small">Clearing hides a failed job here; it is never deleted and stays in its episode&apos;s history. A failed job that a live episode still needs to retry stays, with the reason.</p>
        {table(failed, 'No failed jobs.')}</div>
      <div className="card" style={{marginTop: 16}}><h2>Recent jobs</h2>{table(recentRows(jobs || [], more), 'No jobs yet.')}
        {(jobs || []).length > 10 && <button className="btn sm" onClick={() => setMore(!more)}>{more ? 'Show the latest 10' : `Show more (${Math.min((jobs || []).length, 40) - 10} more)`}</button>}</div>
    </>
  );
}
