'use client';
// Guided page, step 11 "Assembly and your review" (API: assembly.py). The shot-by-shot list of what goes into the
// episode (approved talking and reaction clips; a shot without an approved clip shows its approved still, listed as
// "still, not animated"), with each shot's length and warnings; "Put the episode together" (free, on the studio
// server); the finished video; and "Approve the final cut", which is only ever the owner's click. Under the video, the
// final cut's chat thread (final:<episode>): advice, or one shot made again through its own step.
import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import ShotChat from '@/components/ShotChat';
import {lengthText, sourceText} from '@/lib/autopilot';

export default function GuideAssembly({id, onChange}: {id: string; onChange: () => unknown}) {
  const [poll, setPoll] = useState(15000);
  const {data: a, error, reload} = useApi<any>(`/episodes/${id}/assembly`, poll);
  const act = useAction(async () => { await reload(); await onChange(); });
  useEffect(() => { setPoll(a?.busy ? 4000 : 15000); if (a && !a.busy) onChange(); }, [a?.busy]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!a) return error ? <ErrorBox error={error} /> : <p className="small muted">Loading…</p>;
  const cut = (a.cuts || [])[0];
  const stills = (a.rows || []).filter((r: any) => r.source === 'still').length;
  const pr = a.presentation || {};
  return (
    <div className="stack">
      <ErrorBox error={act.error} />
      {!a.ffmpeg && <p className="small bad">FFmpeg is not set up on the studio server, so the episode cannot be put together.</p>}
      <p className="small muted">{a.size?.[0]}×{a.size?.[1]} at {a.fps} fps over your original recording
        {' '}· dialogue on screen: {pr.mode === 'none' ? 'none' : pr.mode}{pr.hook ? ' · POV banner on' : ''}
        {!a.node && (pr.hook || pr.mode !== 'none') ? ' (the banner and dialogue need Node on the server: left out for now)' : ''}</p>
      {(a.rows || []).length > 0 && <table className="ap-table small">
        <thead><tr><th>Shot</th><th>Starts</th><th>Length</th><th>Source</th><th>Warnings</th></tr></thead>
        <tbody>{a.rows.map((r: any) => (
          <tr key={r.index} className={r.source === 'missing' ? 'bad' : ''}>
            <td>{r.index}</td><td>{r.start.toFixed(2)} s</td><td>{lengthText(r)}</td>
            <td><span className={`badge ${r.source === 'still' ? 'warn' : r.source === 'missing' ? 'bad' : 'good'}`}>{sourceText(r)}</span></td>
            <td className="muted">{(r.warnings || []).join('; ')}</td></tr>))}</tbody>
      </table>}
      {stills > 0 && <p className="small muted">{stills} shot(s) are still pictures, not animated.</p>}
      <div className="row">
        <button className="btn primary" disabled={!!act.busy || a.busy || !a.ffmpeg || (a.missing || []).length > 0 || !(a.rows || []).length}
          onClick={() => act.run('make', () => api(`/episodes/${id}/assembly`, {method: 'POST'}))}>
          {a.busy ? 'Putting it together…' : cut ? 'Put the episode together again (free)' : 'Put the episode together (free)'}</button>
        {(a.missing || []).length > 0 && <span className="small bad">Approve a still or clip for shot(s) {a.missing.join(', ')} first.</span>}
      </div>
      {a.job?.status === 'failed' && <p className="small bad">The last assembly stopped: {a.job.error}</p>}
      {cut && <div className="stack">
        <video className="as-video" src={cut.url} controls preload="metadata" />
        <div className="spread small">
          <span>{cut.seconds.toFixed(2)} s · {cut.frames} frames{cut.stills ? ` · ${cut.stills} still(s)` : ''}
            {!cut.current && <span className="warn"> · made before your latest approvals: put it together again</span>}</span>
          {cut.approved
            ? <span className="row"><span className="badge good">Final cut approved{a.approved_by ? ` by ${a.approved_by}` : ''}</span>
              <button className="btn sm" disabled={!!act.busy} onClick={() => act.run('unapprove', () => api(`/episodes/${id}/assembly/approve`, {body: {cut_id: null}}))}>Withdraw approval</button></span>
            : <button className="btn good" disabled={!!act.busy || !cut.current}
              onClick={() => act.run('approve', () => api(`/episodes/${id}/assembly/approve`, {body: {cut_id: cut.id}}))}>Approve the final cut</button>}
        </div>
        {(cut.warnings || []).length > 0 && <p className="small warn">{cut.warnings.join(' ')}</p>}
        <ShotChat step="final" item={id} episodeId={id} onApplied={reload} />
      </div>}
    </div>);
}
