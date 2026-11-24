'use client';
// The episode's Talking shots section: every line with its talking-shot status (not run / preparing / queued /
// running / done / keyed / failed) and cost, one "Run selected lines" that shows the TOTAL estimate, each plan's cap
// and the experimental budget first and starts only after the owner accepts; and the free first draft of the whole
// episode ("Draft: not for publishing"). Paid calls are never retried by themselves: a failed line stays failed until
// it is ticked and run again.
import {useEffect, useRef, useState} from 'react';
import {api} from '@/lib/api';
import {useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import {rowMedia, talkingTotal} from '@/lib/talkingShots';
import DraftCameras from '@/components/DraftCameras';

const IT = 'wavespeed-infinitetalk-fast';
const usd = (x: number | null | undefined, d = 3) => (x === null || x === undefined ? '—' : `$${x.toFixed(d)}`);

export default function TalkingShots({ep, autoRun = 0}: {ep: any; autoRun?: number}) {
  const t = useApi<any>(`/episodes/${ep.id}/talking-shots`, 4000);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const rows: any[] = t.data?.lines || [];
  const key = (r: any) => `${r.scene_id}:${r.line}`;
  const chosen = rows.filter(r => picked.has(key(r)));
  const total = talkingTotal(chosen);

  const run = async (chosen: any[]) => {
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
  // Key again (free): keys the stored clip again; the clip and the provider's file are only read, nothing is sent anywhere
  const keyAgain = async (r: any) => {
    setErr('');
    try { await api(`/motion/shot/${r.plan_id}/key`, {body: {model: IT}}); await t.reload(); } catch (e: any) { setErr(e.message); }
  };
  // The Now box's "Run N line(s)": the lines not keyed and not running, through this same flow (free preparation
  // first where needed; then the TOTAL, each plan's cap and the budget in the confirm, and nothing starts without OK)
  const handled = useRef(0);
  useEffect(() => {
    if (!autoRun || autoRun === handled.current || !t.data) return;
    handled.current = autoRun;
    const todo = rows.filter(r => !['keyed', 'queued', 'running', 'preparing'].includes(r.status));
    setPicked(new Set(todo.map(key)));
    if (todo.length) run(todo);
  }, [autoRun, t.data]);   // eslint-disable-line react-hooks/exhaustive-deps
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
        <button className="btn primary sm" disabled={busy || !chosen.length} onClick={() => run(chosen)}>Run selected lines{chosen.length ? ` (${chosen.length}, about ${usd(total)})` : ''}</button>
        <span className="muted small">Experimental budget: {usd(t.data?.spent_usd, 2)} spent + {usd(t.data?.pending_usd, 2)} approved, of {usd(t.data?.budget_usd, 2)}</span>
      </div>
      <div className="table-wrap"><table>
        <thead><tr><th></th><th>Scene · line</th><th>Line</th><th>Audio</th><th>Status</th><th>Cost</th><th>Plan cap</th><th>Clip and key</th></tr></thead>
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
            <td className="small"><RowClip r={r} onKeyAgain={() => keyAgain(r)} /></td>
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

// A row's talking clip and its keyed copy: the state (keyed / key needs attention and why / keying / failed), the
// previews over grey and over the set, the clip itself, the check frames and the transparent copy, and Key again (free).
function RowClip({r, onKeyAgain}: {r: any; onKeyAgain: () => void}) {
  const m = rowMedia(r);
  if (!m.state) return null;
  return (
    <div className="stack" style={{gap: 4}}>
      <div className={m.tone}>{m.state}{m.reasons.length ? `: ${m.reasons.join('; ')}` : ''}</div>
      {(m.overGrey || m.overSet) && <div className="row" style={{gap: 4}}>
        {m.overGrey && <video controls preload="none" src={m.overGrey} style={{width: 90}} aria-label={`scene ${r.scene} line ${r.line + 1}, keyed over grey`} />}
        {m.overSet && <video controls preload="none" src={m.overSet} style={{width: 90}} aria-label={`scene ${r.scene} line ${r.line + 1}, keyed over the set`} />}
      </div>}
      <div className="row" style={{gap: 8, flexWrap: 'wrap'}}>
        {m.clip && <a href={m.clip} target="_blank" rel="noreferrer">clip</a>}
        {m.check && <a href={m.check} target="_blank" rel="noreferrer">check frames{m.checkFrames ? ` (${m.checkFrames})` : ''}</a>}
        {m.keyed && <a href={m.keyed} download>transparent copy</a>}
      </div>
      {m.keyAgain && <div><button className="btn sm" onClick={onKeyAgain}>Key again (free)</button></div>}
    </div>);
}
