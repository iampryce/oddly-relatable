'use client';
// Shot comparison, batch mode (Production > Motion Model Comparison). One screen: pick the episode, tick lines and
// models; planning (first frames from our approved art, the line's own audio cut, the rig render) starts by itself for
// every ticked line. One summary (exact clips, total estimate, budget with approved-but-uncharged runs against the cap)
// and ONE "Run selected" confirm before anything paid runs. Results: one row per line, rig / i2v / avatar side by side.
// A line can also get the owner's own first frame (uploaded, confirmed made from our approved art): a second plan beside
// the original-art one, with the same audio and action, and every request has its own Run with its estimate.
import {useEffect, useMemo, useState} from 'react';
import {api, uploadFile} from '@/lib/api';
import {useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import {DeleteButton} from '@/components/BinButtons';
import {clipCell, lineKey, toggleAll} from '@/lib/shotBatch';
import {gpuLine} from '@/lib/gpuView';

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
  const gpuModels: any[] = opts?.gpu_models || [];
  const talking: any[] = opts?.talking || [];
  const ALL = [...PAID, ...talking.map(m => m.id), ...gpuModels.map(m => m.id)];
  const label = (m: string) => { const g = gpuModels.find(x => x.id === m); const t = talking.find(x => x.id === m);
    return LABEL[m] || (t ? `${t.short} (WaveSpeed)` : g ? `${g.short} (GPU)` : m); };
  // the talking-shot provider from Settings is ticked once the options arrive; the fallback is never ticked by itself
  useEffect(() => { if (opts?.talking_provider) setModels(ms => new Set([...ms, opts.talking_provider])); }, [opts?.talking_provider]);
  const plans: any[] = batch.data?.plans || [];
  const ownPlans: any[] = batch.data?.own_plans || [];
  const ownOf = (p: any) => ownPlans.filter(o => o.base_plan === p.id);
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
  const paidModels = ALL.filter(m => models.has(m));
  const ids = chosenPlans.map((p: any) => p.id).join(',');
  const statusSig = chosenPlans.map((p: any) => `${p.id}:${p.status}`).join(',');   // every selected plan's state
  useEffect(() => {
    if (!ids) { setSummary(null); return; }
    api('/motion/shot-batch/run', {body: {plan_ids: ids.split(','), models: [...models], framing, confirm: false}})
      .then(setSummary).catch(e => setErr(e.message));
  }, [ids, statusSig, paidModels.join(','), JSON.stringify(framing), batch.data?.spent_usd, batch.data?.pending_usd]);   // eslint-disable-line react-hooks/exhaustive-deps

  const runSelected = async () => {
    if (!summary?.clips) return;
    const g = summary.gpu?.clips ? `\n${summary.gpu.clips} self-hosted clip(s), estimated ${usd(summary.gpu.estimate_usd, 3)} of GPU time. ${gpuLine(summary.gpu)}` : '';
    if (!window.confirm(`Run ${summary.clips} clip(s): estimated ${usd(summary.total_usd)}. Experimental budget: ${usd(summary.spent_usd)} spent + ${usd(summary.pending_usd)} approved, of ${usd(summary.budget_usd)}.${g}`)) return;
    setBusy(true); setErr('');
    try { await api('/motion/shot-batch/run', {body: {plan_ids: ids.split(','), models: [...models], framing, confirm: true, expected_usd: summary.total_usd}}); await batch.reload(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const retry = async (p: any, model: string, est: number) => {
    if (!window.confirm(`Retry ${label(model)} for this line: estimated ${usd(est, 3)}?`)) return;
    try { await api(`/motion/shot/${p.id}/run`, {body: {model}}); await batch.reload(); } catch (e: any) { setErr(e.message); }
  };
  const runOne = async (p: any, r: any) => {
    const whose = p.own_frame ? 'your own first frame' : 'the original art';
    if (!window.confirm(`Run ${r.label} on ${whose} for this line: estimated ${usd(r.estimate.usd, 3)}${r.estimate?.note ? ` (${r.estimate.note})` : ''}${p.talking && r.provider ? `. This plan's talking cap: ${usd(p.talking.spent_usd, 3)} of ${usd(p.talking.cap_usd)} used` : ''}. Experimental budget: ${usd(batch.data?.spent_usd)} spent + ${usd(batch.data?.pending_usd)} approved, of ${usd(batch.data?.budget_usd)}.`)) return;
    try { await api(`/motion/shot/${p.id}/run`, {body: {model: r.model}}); await batch.reload(); } catch (e: any) { setErr(e.message); }
  };
  const requests = (p: any) => (p.requests || []).filter((r: any) => models.has(r.model)).map((r: any) => (
    <details key={r.model}><summary>show request: {r.label} ({usd(r.estimate.usd, 3)}{r.backend === 'gpu' ? `, about ${r.estimate.gpu_seconds} GPU s` : ''}{p.own_frame ? ', your first frame' : `, ${r.framing} frame`}){r.blocked ? ` · cannot run: ${r.blocked}` : ''}{r.result ? ` · ${r.result.status}` : ''}</summary>
      {r.sends && <div className="muted">Sends: {r.sends.join('; ')}</div>}
      {r.estimate?.note && <div className="muted">{r.estimate.note}</div>}
      {r.frame_url && <img src={r.frame_url} alt={`${p.own_frame ? 'your' : r.framing} first frame`} style={{width: 100}} />}
      <pre style={{whiteSpace: 'pre-wrap'}}>{r.endpoint}{'\n'}{JSON.stringify(r.body, null, 1)}</pre>
      {r.terms && <div className="muted">Terms: {r.terms}. Not for publishing until confirmed.</div>}
      {r.seed !== undefined && r.seed !== null && <label className="row small" style={{gap: 4}}>Seed
        <input type="number" min={0} defaultValue={r.seed} style={{width: 130}} aria-label={`seed for ${r.label}`}
          onBlur={e => Number(e.target.value) !== r.seed && edit(`/motion/shot/${p.id}/seed`, {model: r.model, seed: Number(e.target.value)})} /></label>}
      {r.blocked?.startsWith('make the') && !p.own_frame && <button className="btn sm" onClick={() => edit(`/motion/shot/${p.id}/frame`, {framing: r.framing}, 'POST')}>Make the {r.framing === 'head' ? 'head-and-shoulders' : r.framing} first frame (free)</button>}
      {!r.result && !r.blocked && <button className="btn sm" onClick={() => runOne(p, r)}>Run this ({usd(r.estimate.usd, 3)})</button>}
    </details>));
  const edit = async (path: string, body: any, method = 'PUT') => {
    try { await api(path, {method, body}); await batch.reload(); } catch (e: any) { setErr(e.message); }
  };
  const talkingBox = (p: any) => p.talking && (p.requests || []).some((r: any) => r.provider && models.has(r.model)) && (
    <div className="stack small" style={{borderLeft: '3px solid var(--line, #ddd)', paddingLeft: 8}}>
      <strong>Talking shots (WaveSpeed)</strong>
      <label>Prompt (neutral wording only; attitude comes from the scene&apos;s expression setting){p.talking.prompt_is_default ? ' · default' : ''}
        <textarea rows={3} defaultValue={p.talking.prompt} aria-label="talking-shot prompt"
          onBlur={e => e.target.value.trim() !== p.talking.prompt && edit(`/motion/shot/${p.id}/talking-prompt`, {prompt: e.target.value})} /></label>
      <label className="row" style={{gap: 4}}>This plan&apos;s hard cap (USD): ${p.talking.spent_usd.toFixed(3)} used of
        <input type="number" min={0.05} max={10} step={0.05} defaultValue={p.talking.cap_usd} style={{width: 90}} aria-label="plan cap"
          onBlur={e => Number(e.target.value) !== p.talking.cap_usd && edit(`/motion/shot/${p.id}/talking-cap`, {cap_usd: Number(e.target.value)})} /></label>
    </div>);
  const saveAction = async (p: any, action: string) => {
    if (action.trim() === p.action) return;
    try { await api(`/motion/shot/${p.id}/action`, {method: 'PUT', body: {action}}); await batch.reload(); } catch (e: any) { setErr(e.message); }
  };
  const columns = useMemo(() => ['rig', ...ALL].filter(m => models.has(m)), [models, ALL.join(',')]);   // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="card stack" id="shot-comparison">
      <h2>Shot comparison: AI models vs the rig (batch)</h2>
      {opts?.gpu && <p className="small muted">{gpuLine(opts.gpu)}</p>}
      <p className="muted small">Tick lines and models. The models get only our own approved art (the set plate with the speaker&apos;s approved neutral pose) and, for the avatar model, the line&apos;s own audio; nothing from the reference video. Planning is free and starts by itself; nothing paid runs until you click Run selected, or a request&apos;s own Run (its estimate is shown first). Under a line&apos;s requests you can add your own first frame as a second plan.</p>
      <ErrorBox error={err || batch.error} />
      <div className="row" style={{gap: 8, flexWrap: 'wrap'}}>
        <select aria-label="Episode" value={eid ?? ''} onChange={e => { setEid(e.target.value ? Number(e.target.value) : null); setPicked(new Set()); }}>
          <option value="">Choose an audio episode</option>{audioEps.map((e: any) => <option key={e.id} value={e.id}>{e.title}</option>)}</select>
        {['rig', ...ALL].map(m => <label key={m} className="row small" style={{gap: 4}}><input type="checkbox" checked={models.has(m)}
          onChange={e => { const n = new Set(models); if (e.target.checked) n.add(m); else n.delete(m); setModels(n); }} />{label(m)}
          {gpuModels.find(g => g.id === m && !g.pinned) && <span className="muted"> (workflow not pinned)</span>}</label>)}
        {[...PAID, ...talking.map(t => t.id)].map(m => { const t = talking.find(x => x.id === m);
          const def = t ? t.framing : m.includes('avatar') ? 'medium' : 'wide';
          return <label key={m} className="small row" style={{gap: 4}}>{label(m)} framing
          <select value={framing[m] || ''} onChange={e => setFraming(f => { const n = {...f}; if (e.target.value) n[m] = e.target.value; else delete n[m]; return n; })}>
            <option value="">default ({def === 'head' ? 'head and shoulders' : def})</option><option value="wide">wide</option><option value="medium">medium</option><option value="head">head and shoulders</option></select></label>; })}
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
                <div className="muted">Tone: {p.tone || '—'} · from {p.action_source || 'phrase matcher'}{p.action_cost ? ` · writer cost about ${usd(p.action_cost.usd, 4)}${p.action_cost.note ? ` (${p.action_cost.note})` : ''}` : ''}{p.action_note ? ` · ${p.action_note}` : ''}</div>
                <textarea rows={2} defaultValue={p.action} onBlur={e => saveAction(p, e.target.value)} aria-label="action" />
                {talkingBox(p)}
                {requests(p)}
                {p.status === 'ready' && <OwnFrameUpload plan={p} onDone={batch.reload} onError={setErr} />}
                {ownOf(p).map((o: any) => (
                  <div key={o.id} className="stack" style={{borderLeft: '3px solid var(--line, #ddd)', paddingLeft: 8}}>
                    <strong>Your own first frame</strong>
                    <div className="muted">{o.own_frame?.note} · uploaded by {o.own_frame?.by} · same line audio, action and rig render as the original; free until you click Run</div>
                    {o.frame_url && <img src={o.frame_url} alt="your own first frame" style={{width: 100}} />}
                    <textarea rows={2} defaultValue={o.action} onBlur={e => saveAction(o, e.target.value)} aria-label="action for your first frame" />
                    {talkingBox(o)}
                    {requests(o)}
                  </div>))}
              </details>}
            </div>);
        })}
      </div>}
      {summary && <div className="card stack" style={{background: 'var(--panel, #f7f7f7)'}}>
        <strong>Summary: {summary.clips} paid clip(s){summary.rig ? ' + the rig renders (free)' : ''}, estimated {usd(summary.total_usd)}</strong>
        <span className={`small ${summary.fits ? '' : 'bad'}`}>fal.ai budget: {usd(summary.spent_usd)} spent + {usd(summary.pending_usd)} approved, not yet charged, of {usd(summary.budget_usd)}{summary.fits ? '' : ': over a cap or the GPU cannot run, so Run selected is refused'}</span>
        {summary.gpu?.clips > 0 && <span className={`small ${summary.gpu.ok ? '' : 'bad'}`}>{summary.gpu.clips} self-hosted clip(s), about {usd(summary.gpu.estimate_usd, 3)} of GPU time · {gpuLine(summary.gpu)}</span>}
        {summary.skipped?.length > 0 && <span className="muted small">Not included: {summary.skipped.join('; ')}</span>}
        <div><button className="btn primary" disabled={busy || !summary.clips || !summary.fits} onClick={runSelected}>Run selected</button></div>
      </div>}
      {chosenPlans.length > 0 && <div className="table-wrap"><table>
        <thead><tr><th>Line</th>{columns.map(c => <th key={c}>{label(c)}</th>)}</tr></thead>
        <tbody>{chosenPlans.flatMap((p: any) => [p, ...ownOf(p)]).map((p: any) => (
          <tr key={p.id}><td className="small">&ldquo;{p.text}&rdquo; ({p.seconds} s){p.own_frame ? <div className="muted">your first frame</div> : null}</td>
            {columns.map(c => {
              const cell = clipCell(p, c);
              return <td key={c} className="small">
                {cell.url && <video controls src={cell.url} style={{width: 140}} />}
                {cell.url && cell.assetId != null && <div><DeleteButton kind="clip" id={cell.assetId} label={`the ${label(c)} clip of "${p.text.slice(0, 40)}"`} onDone={batch.reload} /></div>}
                {cell.gpu && <div className="muted">{cell.gpu}</div>}
                {cell.binned && <div className="muted">clip in the Bin</div>}
                {cell.cost && <div>{cell.cost}</div>}
                {cell.terms && <div className="muted">{cell.terms}</div>}
                {cell.check && <div className={cell.lengthOk ? 'muted' : 'bad'}>{cell.check}</div>}
                {cell.state && <div className="muted">{cell.state}</div>}
                {cell.failed && <div className="bad">{cell.failed} <button className="btn sm" onClick={() => retry(p, c, cell.estimate || 0)}>Retry</button></div>}
              </td>;
            })}</tr>))}</tbody></table></div>}
    </div>);
}

// The owner's own first frame for a line (free): an image they made from our approved art, confirmed before upload.
function OwnFrameUpload({plan, onDone, onError}: {plan: any; onDone: () => void; onError: (m: string) => void}) {
  const [file, setFile] = useState<File | null>(null);
  const [ownArt, setOwnArt] = useState(false);
  const [busy, setBusy] = useState(false);
  const send = async () => {
    if (!file) return;
    setBusy(true);
    try { await uploadFile(`/motion/shot/${plan.id}/own-frame`, file, {own_art: 'true'}); setFile(null); setOwnArt(false); onDone(); }
    catch (e: any) { onError(e.message); } finally { setBusy(false); }
  };
  return (
    <div className="row small" style={{gap: 8, flexWrap: 'wrap'}}>
      <span>Use my own first frame (free):</span>
      <input type="file" accept="image/png,image/jpeg,image/webp" aria-label="your own first frame" onChange={e => setFile(e.target.files?.[0] || null)} />
      <label className="row" style={{gap: 4}}><input type="checkbox" checked={ownArt} onChange={e => setOwnArt(e.target.checked)} />
        made from our own approved art (no third-party picture or video frame)</label>
      <button className="btn sm" disabled={!file || !ownArt || busy} onClick={send}>{busy ? 'Uploading…' : 'Add as a second plan'}</button>
      <span className="muted">PNG, JPEG or WebP up to 15 MB; cropped to 9:16 and scaled to 720×1280 if needed</span>
    </div>);
}
