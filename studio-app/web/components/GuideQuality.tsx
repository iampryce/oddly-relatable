'use client';
// Guided page, step 10 "Quality check" (API: clip_qa.py). One row per finished talking or reaction clip (the approved
// result, else the newest): its video, the problems Gemini found with their time, and the shot's chat thread, where
// the check's answer arrives as a message from "Quality check" with one suggested fix. Applying the fix is the owner's
// click and goes through the shot's own paid route with its price. "Check" shows its price first.
import Link from 'next/link';
import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import ShotChat from '@/components/ShotChat';
import {checkSummary, issueText} from '@/lib/autopilot';
import {costText} from '@/lib/guide';

export default function GuideQuality({id, onChange}: {id: string; onChange: () => unknown}) {
  const [poll, setPoll] = useState(15000);
  const {data: q, error, reload} = useApi<any>(`/episodes/${id}/quality`, poll);
  const act = useAction(async () => { await reload(); await onChange(); });
  useEffect(() => { setPoll(q?.busy ? 4000 : 15000); if (q && !q.busy) onChange(); }, [q?.busy]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!q) return error ? <ErrorBox error={error} /> : <p className="small muted">Loading…</p>;
  const prov = q.provider || {};
  const est = q.estimate_unchecked;
  const check = (shots: number[] | null, again: boolean, e: any) => {
    if (!e || !window.confirm(`Quality check: ${costText(e) || e.label}. Start now? (${prov.free ? 'free tier' : 'paid'}, not retried by itself)`)) return;
    act.run('check', () => api(`/episodes/${id}/quality/check`, {body: {shots, again, confirm_usd: e.usd_max}}));
  };
  return (
    <div className="stack">
      <ErrorBox error={act.error} />
      {!prov.ready && <p className="small bad">{prov.note} <Link href="/settings">Open Settings</Link></p>}
      {prov.ready && <p className="small muted">Checked by {prov.label}. Each clip&rsquo;s frames, the whole clip when it is
        small, the approved masters and when the speaker talks are sent. Your reference video is never sent.</p>}
      {(q.clips || []).length === 0 && <p className="small muted">No finished clips yet: talking shots (step 9) and reaction shots (step 8) come here.</p>}
      {est && <div className="row">
        <button className="btn primary" disabled={!!act.busy || q.busy || !prov.ready} onClick={() => check(null, false, est)}>
          {q.busy ? 'Checking…' : `Check ${est.clips} clip(s) · ${prov.free ? 'free' : `up to $${est.usd_max.toFixed(4)}`}`}</button>
        <span className="small muted">{est.label}</span></div>}
      {q.job?.status === 'failed' && <p className="small bad">The last check stopped: {q.job.error}</p>}
      {q.usd > 0 && <p className="small muted">Quality checks for this episode so far: ${q.usd.toFixed(4)}</p>}
      {(q.clips || []).map((c: any) => {
        const sum = checkSummary(c);
        return (
          <div key={`${c.step}-${c.shot}`} className="gd-shot">
            <div className="gd-shot-text">
              <div className="spread small"><strong>{c.kind === 'talking' ? 'Talking' : 'Reaction'} shot {c.shot}</strong>
                <span className="row"><span className={`badge ${c.approved ? 'good' : ''}`}>{c.approved ? 'Approved result' : 'Newest result'}</span>
                  <span className={`badge ${sum.tone}`}>{sum.text}</span></span></div>
              {c.check?.summary && <p className="small">{c.check.summary}</p>}
              {(c.check?.issues || []).length > 0 && <ul className="small gd-beats">
                {c.check.issues.map((i: any, k: number) => <li key={k}>{issueText(i)}</li>)}</ul>}
              {c.check && <p className="small muted">{c.check.model}{c.check.free_tier ? ' (free tier)' : ''} · ${(c.check.usd || 0).toFixed(4)}
                {prov.ready && c.estimate && <> · <button className="btn sm" disabled={!!act.busy || q.busy}
                  onClick={() => check([c.shot], true, c.estimate)}>Check again</button></>}</p>}
            </div>
            {c.url && <video className="qa-video" src={c.url} controls preload="metadata" />}
            <div className="gd-shot-chat"><ShotChat step={c.step} item={c.shot} episodeId={id} onApplied={reload} /></div>
          </div>);
      })}
    </div>);
}
