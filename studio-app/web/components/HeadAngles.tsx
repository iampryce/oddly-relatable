'use client';
// Head angles for the Studio 3D rig animator (feat/3d-rig PR 1): three-quarter, side and back drawings of the neutral
// head, drawn from the approved front pose. Started only by you (cost first, capped) and each drawing approved by you;
// until an angle is approved the 3D renderer uses a mock made from the front head.
import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from './ui';
import {angleLabel, angleStatusText} from '@/lib/headAngles';

export default function HeadAngles({characterId, locked}: {characterId: number; locked: boolean}) {
  const [poll, setPoll] = useState(0);
  const {data, error, reload} = useApi<any>(`/characters/${characterId}/head-angles`, poll);
  const act = useAction(reload);
  const [cap, setCap] = useState(1);
  const [pick, setPick] = useState<string[] | null>(null);
  const running = !!data?.job;
  useEffect(() => { setPoll(running ? 4000 : 0); }, [running]);   // refresh while a drawing job runs
  if (!data) return error ? <ErrorBox error={error} /> : null;
  const chosen = pick ?? data.missing;
  const each = data.cost_each;
  const low = (each.usd_low * chosen.length).toFixed(2), high = (each.usd_high * chosen.length).toFixed(2);
  const generate = () => {
    if (!window.confirm(`Draw ${chosen.length} head angle(s) (${chosen.map(angleLabel).join(', ')}) from the approved front pose: about $${low}-$${high}, cap $${cap.toFixed(2)}?`)) return;
    act.run('gen', () => api(`/characters/${characterId}/head-angles/generate`, {body: {angles: chosen, max_usd: cap}}));
  };
  const decide = (id: number, decision: string) => act.run(decision, () => api(`/head-angles/${id}/decision`, {body: {decision}}));
  return (
    <div className="stack small" style={{borderTop: '1px solid var(--line)', paddingTop: 8}}>
      <strong>Head angles (3D rig)</strong>
      <span className="muted">{data.note}</span>
      <ErrorBox error={act.error} />
      <div className="poses">
        {data.front && <div className="pose"><img src={data.front.url} alt="front (approved neutral pose)" loading="lazy" /><div>front</div><span className="badge good">approved pose</span></div>}
        {data.angles.map((r: any) => (
          <div key={r.angle} className="pose">
            {r.approved ? <img src={r.approved.url} alt={`${r.angle} (approved)`} loading="lazy" /> : <div className="card empty small" style={{minHeight: 80}}>mock in use</div>}
            <div>{angleLabel(r.angle)}</div>
            <span className={`badge ${r.status === 'approved' ? 'good' : r.status === 'review' ? 'warn' : ''}`}>{angleStatusText(r)}</span>
            {r.review.map((x: any) => <div key={x.id} className="stack" style={{marginTop: 4}}>
              <img src={x.url} alt={`${r.angle} for review`} loading="lazy" />
              {!locked && <div className="row" style={{justifyContent: 'center'}}>
                <button className="btn sm good" disabled={!!act.busy} onClick={() => decide(x.id, 'approve')}>Approve</button>
                <button className="btn sm danger" disabled={!!act.busy} onClick={() => decide(x.id, 'reject')}>Reject</button></div>}
            </div>)}
          </div>))}
      </div>
      {data.job && <div className="alert info small">Drawing head angles: {data.job.status}{data.job.progress?.current ? ` (${data.job.progress.current})` : ''}…</div>}
      {!locked && <div className="row" style={{gap: 6, flexWrap: 'wrap', alignItems: 'center'}}>
        {data.angles.map((r: any) => <label key={r.angle} className="row" style={{gap: 3}}><input type="checkbox" checked={chosen.includes(r.angle)}
          onChange={e => setPick(e.target.checked ? [...chosen, r.angle] : chosen.filter((a: string) => a !== r.angle))} />{angleLabel(r.angle)}</label>)}
        <span>cap $</span><input type="number" min={0.1} max={10} step={0.1} value={cap} onChange={e => setCap(Number(e.target.value) || 1)} style={{width: 64}} aria-label="head angles cost cap in dollars" />
        <button className="btn sm" disabled={!!act.busy || !data.can_generate || !chosen.length} onClick={generate}>Draw {chosen.length} angle(s) (about ${low}-${high})</button>
        {data.reason && <span className="muted">{data.reason}</span>}
      </div>}
    </div>);
}
