'use client';
// The stick pipeline on a character card (2026-11-25): Generate master (studio style prompt + this character's look +
// the style reference image) -> candidates for the owner's review; the approved master is the character from then on.
// Expressions and Turnaround are made from the approved master only. Every button shows its price first and asks
// before it starts; only the owner's Approve approves anything.
import {useEffect, useState} from 'react';
import Link from 'next/link';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox, JobStatus} from '@/components/ui';
import {confirmText} from '@/lib/stickPipeline';
import ShotChat from '@/components/ShotChat';

export default function StickMaster({characterId, name, locked}: {characterId: number; name: string; locked: boolean}) {
  const [poll, setPoll] = useState(15000);
  const {data: st, reload} = useApi<any>(`/characters/${characterId}/stick`, poll);
  const act = useAction(reload);
  const [showPrompt, setShowPrompt] = useState(false);
  useEffect(() => { setPoll(st?.busy ? 3000 : 15000); }, [st?.busy]);
  if (!st) return null;
  const paid = (what: string, path: string, cost: any) => {
    if (!window.confirm(confirmText(what, cost))) return;
    act.run(path, () => api(`/characters/${characterId}/stick/${path}`, {body: {confirm_usd: cost.usd}}));
  };
  const decide = (id: number, decision: 'approve' | 'reject') =>
    act.run(`d${id}`, () => api(`/characters/${characterId}/stick/assets/${id}/decision`, {body: {decision}}));
  const job = st.jobs?.[0];
  const off = st.provider?.label === 'off';
  return (
    <div className="stack stick-master" style={{borderTop: '1px solid var(--line, #ddd)', paddingTop: 10}}>
      <div className="spread"><strong>Stick master</strong><span className="muted small">{st.provider?.label}</span></div>
      <ErrorBox error={act.error} />
      {job && ['queued', 'running', 'failed'].includes(job.status) && <div className="small">
        {job.kind === 'stick_master' ? 'Master candidates' : `${job.payload?.sheet} sheet`}: <JobStatus status={job.status} />
        {job.error && <span className="bad"> {job.error}</span>}</div>}
      {st.master ? <div className="row" style={{alignItems: 'flex-start', gap: 10}}>
        <a href={st.master.url} target="_blank" rel="noreferrer"><img src={st.master.url} alt={`${name} master`} style={{width: 110, borderRadius: 6}} /></a>
        <span className="small"><span className="badge good">approved master</span><br />Every new image of {name} is made from this one.</span></div>
        : <p className="small muted">No approved master yet.</p>}
      {st.candidates.length > 0 && <div className="poses">{st.candidates.map((a: any) => (
        <div key={a.id} className="pose">
          <a href={a.url} target="_blank" rel="noreferrer"><img src={a.url} alt={`${name} master candidate`} loading="lazy" /></a>
          <span className="badge warn">candidate</span>
          <div className="row" style={{justifyContent: 'center', marginTop: 4}}>
            <button className="btn sm good" disabled={!!act.busy} onClick={() => decide(a.id, 'approve')}>{st.master ? 'Replace master' : 'Approve as master'}</button>
            <button className="btn sm danger" disabled={!!act.busy} onClick={() => decide(a.id, 'reject')}>Reject</button></div>
        </div>))}</div>}
      {st.sheets.length > 0 && <div className="poses">{st.sheets.map((a: any) => (
        <div key={a.id} className="pose">
          <a href={a.url} target="_blank" rel="noreferrer"><img src={a.url} alt={`${name} ${a.sheet} sheet`} loading="lazy" /></a>
          <div className="small">{a.sheet}</div>
          <span className={`badge ${a.status === 'approved' ? 'good' : 'warn'}`}>{a.status}</span>
          {a.status === 'review' && <div className="row" style={{justifyContent: 'center', marginTop: 4}}>
            <button className="btn sm good" disabled={!!act.busy} onClick={() => decide(a.id, 'approve')}>Approve</button>
            <button className="btn sm danger" disabled={!!act.busy} onClick={() => decide(a.id, 'reject')}>Reject</button></div>}
        </div>))}</div>}
      {!locked && <div className="row small" style={{gap: 6, flexWrap: 'wrap'}}>
        <button className="btn sm primary" disabled={!!act.busy || st.busy || off || !st.style_reference?.set}
          onClick={() => paid(`Generate ${name}'s master candidates`, 'master', st.costs.master)}>
          Generate master · {st.costs.master.label}</button>
        <button className="btn sm" disabled={!!act.busy || st.busy || off || !st.master}
          onClick={() => paid(`${name}: expressions sheet from the approved master`, 'expressions', st.costs.expressions)}>
          Expressions · {st.costs.expressions.label}</button>
        <button className="btn sm" disabled={!!act.busy || st.busy || off || !st.master}
          onClick={() => paid(`${name}: turnaround from the approved master`, 'turnaround', st.costs.turnaround)}>
          Turnaround · {st.costs.turnaround.label}</button>
        <button className="btn sm" onClick={() => setShowPrompt(!showPrompt)}>{showPrompt ? 'Hide prompt' : 'Prompt'}</button>
      </div>}
      {!st.style_reference?.set && <p className="small muted">Choose the style reference image in <Link href="/settings#studio-style">Settings › Studio style</Link> first.</p>}
      {showPrompt && <pre className="small" style={{whiteSpace: 'pre-wrap', maxHeight: 240, overflow: 'auto'}}>{st.prompt}</pre>}
      {!locked && <ShotChat step="master" item={characterId} onApplied={reload} />}
    </div>);
}
