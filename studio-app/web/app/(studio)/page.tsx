'use client';
import Link from 'next/link';
import {when} from '@/lib/api';
import {useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import {diskBanner, diskLine, diskNotice, reportLine, size} from '@/lib/diskView';

export default function Overview() {
  const {data: o, error} = useApi<any>('/overview', 10000);
  const {data: health} = useApi<any>('/health', 30000);
  const {data: disk} = useApi<any>('/system/disk', 60000);
  const banner = diskBanner(disk);
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
      {banner && <div className={`alert ${banner.tone}`} role={banner.tone === 'bad' ? 'alert' : 'status'}>{banner.text}</div>}
      <div className="grid cols-4">
        {stats.map(([label, n, href]) => (
          <Link key={label} href={href} className="card stat" style={{color: 'inherit', textDecoration: 'none'}}>
            <div className="l">{label}</div><div className="n">{n ?? 0}</div>
          </Link>))}
      </div>
      {disk && <div className="card" style={{marginTop: 16}}>
        <div className="spread"><h2>Disk</h2><span className="muted small">{diskLine(disk)}</span></div>
        <div className="disk-bar" role="meter" aria-label="Disk used" aria-valuemin={0} aria-valuemax={100} aria-valuenow={disk.percent}>
          <span className={disk.level === 'critical' ? 'bad' : disk.level === 'warn' ? 'warn' : 'good'} style={{width: `${Math.min(100, disk.percent)}%`}} />
        </div>
        {disk.report?.consumers?.length > 0 && <div className="table-wrap"><table><tbody>
          {disk.report.consumers.map((c: any) => (
            <tr key={c.key}><td>{c.label}</td><td className="small" style={{textAlign: 'right', width: 120}}>{size(c.bytes)}</td></tr>))}
        </tbody></table></div>}
        {diskNotice(disk) && <div className="warn small">{diskNotice(disk)}</div>}
        <p className="muted small" style={{marginBottom: 0}}>{reportLine(disk)}</p>
      </div>}
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
