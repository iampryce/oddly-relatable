'use client';
// The episode's Talking shots section: every line with its talking-shot status (not run / preparing / queued /
// running / done / keyed / failed) and cost, one "Run selected lines" that shows the TOTAL estimate, each plan's cap
// and the experimental budget first and starts only after the owner accepts; and the free first draft of the whole
// episode ("Draft: not for publishing"). Paid calls are never retried by themselves: a failed line stays failed until
// it is ticked and run again.
import {useState} from 'react';
import {api} from '@/lib/api';
import {useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import {talkingTotal} from '@/lib/talkingShots';
import DraftCameras from '@/components/DraftCameras';

const IT = 'wavespeed-infinitetalk-fast';
const usd = (x: number | null | undefined, d = 3) => (x === null || x === undefined ? '—' : `$${x.toFixed(d)}`);

export default function TalkingShots({ep}: {ep: any}) {
  const t = useApi<any>(`/episodes/${ep.id}/talking-shots`, 4000);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const rows: any[] = t.data?.lines || [];
  const key = (r: any) => `${r.scene_id}:${r.line}`;
  const chosen = rows.filter(r => picked.has(key(r)));
  const total = talkingTotal(chosen);

  const run = async () => {
    setErr('');
    const missing = chosen.filter(r => !r.plan_ready || r.blocked?.startsWith('make the'));
    setBusy(true);
    try {
      if (missing.length) {
        // free: plans without the text writer or the rig render, and the cutout first frame where it is missing
        await api(`/episodes/${ep.id}/talking-shots/prepare`, {body: {lines: missing.map(r => ({scene_id: r.scene_id, line: r.line}))}});
        await t.reload();
        setErr(`Preparing ${missing.length} line(s) (free). Press Run selected lines again when they show as ready.`);
        return;
      }
      const ids = chosen.map(r => r.plan_id);
      const s = await api('/motion/shot-batch/run', {body: {plan_ids: ids, models: [IT], confirm: false}});
      const caps = chosen.map(r => `scene ${r.scene}, line ${r.line + 1}: ${usd(r.cap_used_usd)} of ${usd(r.cap_usd, 2)} used`).join('\n');
      const skipped = s.skipped?.length ? `\nNot included: ${s.skipped.join('; ')}` : '';
      if (!s.clips) { setErr(`Nothing to run.${skipped}`); return; }
      if (!window.confirm(`Run ${s.clips} talking shot(s) on WaveSpeed InfiniteTalk fast.\nTOTAL estimate: ${usd(s.total_usd)} (audio rounded up per line, 3 s minimum, $0.015/s).\n` +
        `Per-plan caps:\n${caps}\nExperimental budget: ${usd(s.spent_usd, 2)} spent + ${usd(s.pending_usd, 2)} approved, of ${usd(s.budget_usd, 2)}.${skipped}\n\nStart now?`)) return;
      await api('/motion/shot-batch/run', {body: {plan_ids: ids, models: [IT], confirm: true, expected_usd: s.total_usd}});
      setPicked(new Set());
      await t.reload();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const makeDraft = async () => {
    setErr('');
    try { await api(`/episodes/${ep.id}/draft`, {body: {}}); await t.reload(); } catch (e: any) { setErr(e.message); }
  };
  const d = t.data?.draft;
  return (
    <div className="stack">
      <p className="small muted">{t.data?.model?.label}: {t.data?.model?.price}. Terms: {t.data?.model?.terms}. Each line is a paid
        call started only by you after the total is shown; a failed line stays failed until you run it again.</p>
      <ErrorBox error={err || t.error} />
      <div className="row" style={{gap: 6}}>
        <button className="btn sm" onClick={() => setPicked(new Set(rows.filter(r => r.status !== 'keyed').map(key)))}>All not keyed</button>
        <button className="btn sm" onClick={() => setPicked(new Set())}>None</button>
        <button className="btn primary sm" disabled={busy || !chosen.length} onClick={run}>Run selected lines{chosen.length ? ` (${chosen.length}, about ${usd(total)})` : ''}</button>
        <span className="muted small">Experimental budget: {usd(t.data?.spent_usd, 2)} spent + {usd(t.data?.pending_usd, 2)} approved, of {usd(t.data?.budget_usd, 2)}</span>
      </div>
      <div className="table-wrap"><table>
        <thead><tr><th></th><th>Scene · line</th><th>Line</th><th>Audio</th><th>Status</th><th>Cost</th><th>Plan cap</th><th>Keyed</th></tr></thead>
        <tbody>{rows.map(r => (
          <tr key={key(r)}>
            <td><input type="checkbox" aria-label={`scene ${r.scene} line ${r.line + 1}`} checked={picked.has(key(r))}
              disabled={['queued', 'running', 'preparing'].includes(r.status)}
              onChange={e => { const n = new Set(picked); if (e.target.checked) n.add(key(r)); else n.delete(key(r)); setPicked(n); }} /></td>
            <td className="small">{r.scene} · {r.line + 1}</td>
            <td className="small">{r.speaker}: &ldquo;{String(r.text).slice(0, 48)}{String(r.text).length > 48 ? '…' : ''}&rdquo;</td>
            <td className="small">{r.seconds} s</td>
            <td className={`small ${r.status === 'failed' ? 'bad' : String(r.message || '').startsWith('key needs attention') ? 'warn' : ''}`}>{r.status}{r.message ? ` · ${r.message}` : ''}{r.blocked && !r.blocked.startsWith('make the') ? ` · ${r.blocked}` : ''}</td>
            <td className="small">{r.actual_usd != null ? `${usd(r.actual_usd)} (charged)` : `${usd(r.estimate_usd)} (estimate)`}</td>
            <td className="small">{r.cap_usd != null ? `${usd(r.cap_used_usd)} of ${usd(r.cap_usd, 2)}` : '—'}</td>
            <td className="small">{r.preview_url ? <a href={r.preview_url} target="_blank" rel="noreferrer">over the set</a> : ''}</td>
          </tr>))}</tbody></table></div>
      <div className="card stack">
        <strong>First draft (free)</strong>
        <p className="small muted">The whole episode at 1080×1920: each scene&apos;s crop of the approved set (filling the frame, no bars), everyone at their seats from their approved neutral poses,
          the speaker&apos;s keyed talking clip where one exists (else the neutral pose and a &ldquo;no clip yet&rdquo; mark), the recording
          as the sound and the end card. Saved in the Video Library as &ldquo;Draft: not for publishing&rdquo;; never offered to publishing.</p>
        <details><summary>Camera per scene (the crop of the set; computed by default, yours to adjust)</summary><DraftCameras ep={ep} /></details>
        <div><button className="btn sm" disabled={d?.status === 'queued' || d?.status === 'running'} onClick={makeDraft}>Make the draft (free)</button></div>
        {d && d.status !== 'succeeded' && <div className={`small ${d.status === 'failed' ? 'bad' : 'muted'}`}>Draft {d.status}{d.error ? `: ${d.error}` : ''}</div>}
        {d?.url && <div className="stack small">
          <div>{d.label} · {d.seconds} s</div>
          {(d.notes || []).map((n: string, i: number) => <div key={i} className="muted">Note: {n}</div>)}
          <video controls src={d.url} style={{width: 220}} />
          <div className="row" style={{gap: 8}}>{(d.pieces || []).map((p: any) => <a key={p.scene} href={p.url} target="_blank" rel="noreferrer">Scene {p.scene}</a>)}</div>
        </div>}
      </div>
    </div>);
}
