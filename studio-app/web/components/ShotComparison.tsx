'use client';
// Shot comparison, batch mode (Production > Motion Model Comparison). One screen: pick the episode, tick lines and
// models; planning (first frames from our approved art, the line's own audio cut, the rig render) starts by itself for
// every ticked line. One summary (exact clips, total estimate, budget with approved-but-uncharged runs against the cap)
// and ONE "Run selected" confirm before anything paid runs. Results: one row per line, rig / i2v / avatar side by side.
import {useEffect, useMemo, useState} from 'react';
import {api} from '@/lib/api';
import {useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import {DeleteButton} from '@/components/BinButtons';
import {clipCell, lineKey, toggleAll} from '@/lib/shotBatch';

const usd = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? '—' : `$${x.toFixed(d)}`);
const PAID = ['kling-2.6-pro-i2v', 'kling-avatar-v2-standard'];
const LABEL: Record<string, string> = {rig: 'Rig animator (free)', 'kling-2.6-pro-i2v': 'Kling i2v', 'kling-avatar-v2-standard': 'Kling Avatar'};

export function ShotComparison() {
  const eps = useApi<any[]>('/episodes').data || [];
  const audioEps = eps.filter((e: any) => e.source === 'audio');
  const [eid, setEid] = useState<number | null>(null);
  const opts = useApi<any>(eid ? `/motion/shot/options?episode_id=${eid}` : null).data;
  const batch = useApi<any>(eid ? `/motion/shot-batch?episode_id=${eid}` : null, 3000);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [models, setModels] = useState<Set<string>>(new Set(['rig', ...PAID]));
  const [framing, setFraming] = useState<Record<string, string>>({});
  const [summary, setSummary] = useState<any>(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const lines: any[] = opts?.lines || [];
  const plans: any[] = batch.data?.plans || [];
  const planOf = (l: any) => plans.find(p => p.scene_id === l.scene_id && p.line === l.line);
  const chosen = lines.filter(l => picked.has(lineKey(l)));
  const chosenPlans = chosen.map(planOf).filter(Boolean);

  // planning runs by itself for every ticked line (free); existing plans are reused
  useEffect(() => {
    if (!eid || !chosen.length) return;
    const missing = chosen.filter(l => !planOf(l) || planOf(l).status === 'failed');
    if (!missing.length) return;
    api('/motion/shot-batch/plan', {body: {episode_id: eid, lines: missing.map(l => ({scene_id: l.scene_id, line: l.line}))}})
      .then(() => batch.reload()).catch(e => setErr(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eid, picked, plans.length]);

  // the one summary (free): recomputed whenever the selection, models or plans change
  const paidModels = PAID.filter(m => models.has(m));
  const ids = chosenPlans.map((p: any) => p.id).join(',');
  const statusSig = chosenPlans.map((p: any) => `${p.id}:${p.status}`).join(',');   // every selected plan's state
  useEffect(() => {
    if (!ids) { setSummary(null); return; }
    api('/motion/shot-batch/run', {body: {plan_ids: ids.split(','), models: [...models], framing, confirm: false}})
      .then(setSummary).catch(e => setErr(e.message));
  }, [ids, statusSig, paidModels.join(','), JSON.stringify(framing), batch.data?.spent_usd, batch.data?.pending_usd]);   // eslint-disable-line react-hooks/exhaustive-deps

  const runSelected = async () => {
    if (!summary?.clips) return;
    if (!window.confirm(`Run ${summary.clips} clip(s): estimated ${usd(summary.total_usd)}. Budget: ${usd(summary.spent_usd)} spent + ${usd(summary.pending_usd)} approved, of ${usd(summary.budget_usd)}.`)) return;
    setBusy(true); setErr('');
    try { await api('/motion/shot-batch/run', {body: {plan_ids: ids.split(','), models: [...models], framing, confirm: true, expected_usd: summary.total_usd}}); await batch.reload(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const retry = async (p: any, model: string, est: number) => {
    if (!window.confirm(`Retry ${LABEL[model]} for this line: estimated ${usd(est, 3)}?`)) return;
    try { await api(`/motion/shot/${p.id}/run`, {body: {model}}); await batch.reload(); } catch (e: any) { setErr(e.message); }
  };
  const saveAction = async (p: any, action: string) => {
    if (action.trim() === p.action) return;
    try { await api(`/motion/shot/${p.id}/action`, {method: 'PUT', body: {action}}); await batch.reload(); } catch (e: any) { setErr(e.message); }
  };
  const columns = useMemo(() => ['rig', ...PAID].filter(m => models.has(m)), [models]);

  return (
    <div className="card stack" id="shot-comparison">
      <h2>Shot comparison: AI models vs the rig (batch)</h2>
      <p className="muted small">Tick lines and models. The models get only our own approved art (the set plate with the speaker&apos;s approved neutral pose) and, for the avatar model, the line&apos;s own audio; nothing from the reference video. Planning is free and starts by itself; nothing paid runs until you click Run selected.</p>
      <ErrorBox error={err || batch.error} />
      <div className="row" style={{gap: 8, flexWrap: 'wrap'}}>
        <select aria-label="Episode" value={eid ?? ''} onChange={e => { setEid(e.target.value ? Number(e.target.value) : null); setPicked(new Set()); }}>
          <option value="">Choose an audio episode</option>{audioEps.map((e: any) => <option key={e.id} value={e.id}>{e.title}</option>)}</select>
        {['rig', ...PAID].map(m => <label key={m} className="row small" style={{gap: 4}}><input type="checkbox" checked={models.has(m)}
          onChange={e => { const n = new Set(models); if (e.target.checked) n.add(m); else n.delete(m); setModels(n); }} />{LABEL[m]}</label>)}
        {PAID.map(m => <label key={m} className="small row" style={{gap: 4}}>{LABEL[m]} framing
          <select value={framing[m] || ''} onChange={e => setFraming(f => { const n = {...f}; if (e.target.value) n[m] = e.target.value; else delete n[m]; return n; })}>
            <option value="">default ({m.includes('avatar') ? 'medium' : 'wide'})</option><option value="wide">wide</option><option value="medium">medium</option></select></label>)}
      </div>
      {opts && <div className="stack small">
        <div className="row" style={{gap: 6}}><strong>Lines</strong>
          <button className="btn sm" onClick={() => setPicked(toggleAll(lines.filter(l => l.ready), true))}>All lines</button>
          <button className="btn sm" onClick={() => setPicked(new Set())}>None</button>
          {batch.data && <span className="muted">{batch.data.preparing} preparing · {batch.data.ready} ready</span>}</div>
        {lines.map(l => {
          const p = planOf(l);
          return (
            <div key={lineKey(l)} className="stack" style={{borderTop: '1px solid var(--line, #eee)', paddingTop: 4}}>
              <label className="row" style={{gap: 6}}><input type="checkbox" disabled={!l.ready} checked={picked.has(lineKey(l))}
                onChange={e => { const n = new Set(picked); if (e.target.checked) n.add(lineKey(l)); else n.delete(lineKey(l)); setPicked(n); }} />
                Scene {l.scene}, line {l.line + 1} · {l.speaker} · {l.seconds} s · &ldquo;{l.text}&rdquo;
                {!l.ready && <span className="muted">({l.why_not})</span>}
                {picked.has(lineKey(l)) && <span className="muted">{p ? p.status : 'planning…'}{p?.error ? `: ${p.error}` : ''}</span>}</label>
              {picked.has(lineKey(l)) && p && <details><summary>show/edit action and requests</summary>
                <textarea rows={2} defaultValue={p.action} onBlur={e => saveAction(p, e.target.value)} aria-label="action" />
                {(p.requests || []).filter((r: any) => models.has(r.model)).map((r: any) => (
                  <details key={r.model}><summary>show request: {r.label} ({usd(r.estimate.usd, 3)}, {r.framing} frame)</summary>
                    {r.frame_url && <img src={r.frame_url} alt={`${r.framing} first frame`} style={{width: 100}} />}
                    <pre style={{whiteSpace: 'pre-wrap'}}>{r.endpoint}{'\n'}{JSON.stringify(r.body, null, 1)}</pre></details>))}
              </details>}
            </div>);
        })}
      </div>}
      {summary && <div className="card stack" style={{background: 'var(--panel, #f7f7f7)'}}>
        <strong>Summary: {summary.clips} paid clip(s){summary.rig ? ' + the rig renders (free)' : ''}, estimated {usd(summary.total_usd)}</strong>
        <span className={`small ${summary.fits ? '' : 'bad'}`}>Budget: {usd(summary.spent_usd)} spent + {usd(summary.pending_usd)} approved, not yet charged, of {usd(summary.budget_usd)}{summary.fits ? '' : ': over the cap, so Run selected is refused'}</span>
        {summary.skipped?.length > 0 && <span className="muted small">Not included: {summary.skipped.join('; ')}</span>}
        <div><button className="btn primary" disabled={busy || !summary.clips || !summary.fits} onClick={runSelected}>Run selected</button></div>
      </div>}
      {chosenPlans.length > 0 && <div className="table-wrap"><table>
        <thead><tr><th>Line</th>{columns.map(c => <th key={c}>{LABEL[c]}</th>)}</tr></thead>
        <tbody>{chosenPlans.map((p: any) => (
          <tr key={p.id}><td className="small">&ldquo;{p.text}&rdquo; ({p.seconds} s)</td>
            {columns.map(c => {
              const cell = clipCell(p, c);
              return <td key={c} className="small">
                {cell.url && <video controls src={cell.url} style={{width: 140}} />}
                {cell.url && cell.assetId != null && <div><DeleteButton kind="clip" id={cell.assetId} label={`the ${LABEL[c]} clip of "${p.text.slice(0, 40)}"`} onDone={batch.reload} /></div>}
                {cell.binned && <div className="muted">clip in the Bin</div>}
                {cell.cost && <div>{cell.cost}</div>}
                {cell.check && <div className={cell.lengthOk ? 'muted' : 'bad'}>{cell.check}</div>}
                {cell.state && <div className="muted">{cell.state}</div>}
                {cell.failed && <div className="bad">{cell.failed} <button className="btn sm" onClick={() => retry(p, c, cell.estimate || 0)}>Retry</button></div>}
              </td>;
            })}</tr>))}</tbody></table></div>}
    </div>);
}
