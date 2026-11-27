'use client';
// "Suggest speakers" on Lines and speakers (speaker_suggest.py). From the video: Gemini watches and listens to the
// private reference video and suggests a short label per line ("Doctor", "Patient") with how sure it is. Without a
// reference video: the text model guesses from the words only (less sure). Both are paid: the price is shown and
// confirmed first. The suggestions wait in a table: accept all, accept line by line, or edit a label first. Nothing is
// saved until you accept.
import {useEffect, useState} from 'react';
import Link from 'next/link';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from './ui';
import {acceptBody, confidenceText, confirmAmount, defaultValue, initialPicks, videoPrice, type SuggestRow} from '@/lib/speakerSuggest';

const fmt = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`;
const money = (x: number) => `$${x < 0.01 && x > 0 ? x.toFixed(4) : x.toFixed(2)}`;

export default function SpeakerSuggest({episodeId, editable, dirty, onApplied}: {episodeId: number; editable: boolean; dirty: boolean;
  onApplied: () => unknown}) {
  const base = `/episodes/${episodeId}/audio/speaker-suggestions`;
  const [poll, setPoll] = useState(15000);
  const {data: v, reload} = useApi<any>(base, poll);
  const act = useAction(async () => { await reload(); });
  const [paid, setPaid] = useState(true);
  const [free, setFree] = useState(false);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const sug = v?.suggestion;
  const rows: SuggestRow[] = sug?.rows || [];
  useEffect(() => { setPoll(v?.busy ? 4000 : 15000); }, [v?.busy]);
  useEffect(() => { setEdits({}); setPicked(initialPicks(rows)); }, [sug?.made]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!v || !editable) return null;
  const job = v.job;
  const fromVideo = () => {
    const amount = confirmAmount(v.video_estimate, paid);
    const msg = `Suggest the speakers from the reference video (${v.video_estimate.label}).`
      + (paid ? ` Paid model, at most ${money(amount)}.` : '')
      + (free ? ' Free tier allowed: Google may use the video to improve its models.' : '')
      + ' Nothing is saved until you accept. Start now?';
    if (!window.confirm(msg)) return;
    act.run('video', () => api(`${base}/video`, {body: {confirm_usd: amount, paid_tier: paid, use_free_tier: free}}));
  };
  const fromText = () => {
    const e = v.text_estimate;
    if (!window.confirm(`Suggest the speakers from the text only (${e.model}): about ${money(e.usd_typical)}, at most ${money(e.usd_max)}. `
      + 'The text alone is less reliable than the video. Nothing is saved until you accept. Start now?')) return;
    act.run('text', () => api(`${base}/text`, {body: {confirm_usd: e.usd_max}}));
  };
  const accept = (all: boolean) => act.run('accept', async () => {
    await api(`${base}/accept`, {body: {rows: acceptBody(rows, edits, picked, all)}});
    await onApplied();
  });
  const toggle = (id: string) => setPicked(p => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const labels = [...new Set(rows.map(r => defaultValue(r)).filter(Boolean))];
  return (
    <div className="stack" style={{borderTop: '1px solid var(--line, #ddd)', paddingTop: 8}}>
      <ErrorBox error={act.error} />
      <div className="spread">
        <strong>Suggest speakers</strong>
        {job?.status === 'failed' && !v.busy && <span className="small bad">The last suggestion failed: {job.error}</span>}
      </div>
      {v.busy ? <p className="small">Watching and listening to the reference video… (a minute or two)</p>
        : v.reference_video ? <>
          <div className="row small" style={{flexWrap: 'wrap'}}>
            <label className="check"><input type="checkbox" checked={paid} onChange={e => setPaid(e.target.checked)} />My Gemini key is on a paid tier</label>
            <label className="check"><input type="checkbox" checked={free} onChange={e => setFree(e.target.checked)} />Use the free tier (Google may use the video to improve its models)</label>
          </div>
          <div className="row">
            <button className="btn sm primary" disabled={!!act.busy || dirty || !v.keys.gemini || !v.video_estimate || (!paid && !free)} onClick={fromVideo}>
              Suggest speakers from the video · {videoPrice(v.video_estimate, paid, free)}</button>
            {!v.keys.gemini && <span className="small muted">Save the Gemini key in Settings › Credentials first.</span>}
          </div>
          <p className="small muted">Gemini watches the private reference video with its sound and suggests who says each line. Only words come back.</p>
        </> : <>
          <p className="small muted">There is no reference video for this episode, so the speakers can only be guessed from the words.
            {' '}For better suggestions, add the video in <Link href={`/episodes/${episodeId}/guide`}>guided step 1</Link>.</p>
          <div className="row">
            <button className="btn sm" disabled={!!act.busy || dirty || !v.keys.openai || !v.text_estimate} onClick={fromText}>
              Suggest from the text only{v.text_estimate ? ` · at most ${money(v.text_estimate.usd_max)}` : ''}</button>
            {!v.keys.openai && <span className="small muted">Save the OpenAI key in Settings › Credentials first.</span>}
          </div>
        </>}
      {dirty && <p className="small muted">Save your line edits first: the suggestion uses the saved lines.</p>}
      {sug && <>
        <p className="small">
          {sug.source === 'video' ? 'Suggested from the video' : 'Suggested from the text only (less reliable)'} by {sug.model} · {money(sug.usd || 0)}.
          {' '}Check each row: edit a label if it is wrong, tick the rows you want, then accept. Nothing is saved until you do.</p>
        {sug.stale && <div className="alert warn small">The lines changed after this suggestion was made. Ask for a new one.</div>}
        <datalist id="suggested-speakers">{labels.map(l => <option key={l} value={l} />)}</datalist>
        <div className="table-wrap"><table>
          <thead><tr><th></th><th>Time</th><th>Line</th><th>Now</th><th>Suggested speaker</th><th>How sure</th></tr></thead>
          <tbody>{rows.map(r => (
            <tr key={r.line_id}>
              <td><input type="checkbox" style={{width: 'auto'}} aria-label={`Accept line ${r.line_id}`} checked={picked.has(r.line_id)}
                disabled={sug.stale} onChange={() => toggle(r.line_id)} /></td>
              <td className="small" style={{whiteSpace: 'nowrap'}}>{fmt(r.start)}–{fmt(r.end)}</td>
              <td className="small">{r.text}</td>
              <td className="small muted">{r.current || '—'}</td>
              <td style={{minWidth: 140}}><input list="suggested-speakers" value={edits[r.line_id] ?? defaultValue(r)} disabled={sug.stale}
                aria-label={`Suggested speaker for line ${r.line_id}`} maxLength={40}
                onChange={e => setEdits(x => ({...x, [r.line_id]: e.target.value}))} />
                {r.character_name && <span className="small muted"> = {r.character_name}</span>}</td>
              <td className={`small ${r.level === 'low' ? 'muted' : ''}`}>{confidenceText(r, sug.source)}</td>
            </tr>))}</tbody>
        </table></div>
        <div className="row">
          <button className="btn sm primary" disabled={!!act.busy || dirty || sug.stale || !picked.size} onClick={() => accept(false)}>Accept the ticked rows ({picked.size})</button>
          <button className="btn sm" disabled={!!act.busy || dirty || sug.stale} onClick={() => accept(true)}>Accept all</button>
          <button className="btn sm" disabled={!!act.busy} onClick={() => act.run('discard', () => api(base, {method: 'DELETE'}))}>Discard</button>
        </div>
      </>}
    </div>);
}
