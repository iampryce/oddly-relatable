'use client';
import Link from 'next/link';
import {when} from '@/lib/api';
import {useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';

export default function Overview() {
  const {data: o, error} = useApi<any>('/overview', 10000);
  const {data: health} = useApi<any>('/health', 30000);
  const stats: [string, number | undefined, string][] = o ? [
    ['Videos created', o.videos_created, '/library'], ['Ideas awaiting processing', o.ideas_awaiting, '/ideas'],
    ['Scripts awaiting approval', o.scripts_awaiting_approval, '/scripts'], ['Currently processing', o.processing, '/production'],
    ['Videos awaiting review', o.videos_awaiting_review, '/library'], ['Completed videos', o.completed, '/library'],
    ['Failed production jobs', o.failed_jobs, '/production'], ['Published', o.published, '/publishing'],
  ] : [];
  return (
    <>
      <div className="spread"><div><h1>Overview</h1><p className="sub">Everything in the studio at a glance.</p></div>
        <Link className="btn primary" href="/ideas?new=1">New idea</Link></div>
      <ErrorBox error={error} />
      {health?.queue === 'redis-down' && <div className="alert warn">The job queue (Redis) is not reachable: new jobs will wait until it is back.</div>}
      {health?.queue === 'none' && <div className="alert warn">No job queue is configured on this server, so queued jobs will not run.</div>}
      {health?.queue === 'database-polling' && <div className="alert info small">Development mode: the worker picks up jobs from the database (no Redis).</div>}
      <div className="grid cols-4">
        {stats.map(([label, n, href]) => (
          <Link key={label} href={href} className="card stat" style={{color: 'inherit', textDecoration: 'none'}}>
            <div className="l">{label}</div><div className="n">{n ?? 0}</div>
          </Link>))}
      </div>
      <div className="card" style={{marginTop: 16}}>
        <h2>Recent activity</h2>
        {!o?.activity?.length ? <p className="muted">No activity yet. Start by submitting an idea.</p> : (
          <div className="table-wrap"><table><tbody>
            {o.activity.map((a: any, i: number) => (
              <tr key={i}>
                <td className="muted small" style={{width: 140}}>{when(a.created_at)}</td>
                <td><span className={`badge ${a.kind === 'error' ? 'bad' : a.kind === 'approval' ? 'good' : ''}`}>{a.kind}</span></td>
                <td>{a.episode_id ? <Link href={`/episodes/${a.episode_id}`}>{a.message}</Link> : a.message}</td>
              </tr>))}
          </tbody></table></div>)}
      </div>
    </>
  );
}
