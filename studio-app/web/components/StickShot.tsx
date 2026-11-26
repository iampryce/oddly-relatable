'use client';
// The stick pipeline on the storyboard (2026-11-25): per shot, "Make still" (the set + the approved masters of the
// people in the shot, one paid image) and, once the owner approved the shot, "Animate" (paid per second of video), with
// the clip to approve; and "Animate all approved" with its total. Every paid button shows its price and asks first; the
// request carries that price. Nothing approves by itself.
import {useState} from 'react';
import {api} from '@/lib/api';
import {useAction} from '@/lib/hooks';
import {chosenClip, clipStatus, confirmText} from '@/lib/stickPipeline';
import {episodeIdFromBase} from '@/lib/shotChat';
import ShotChat from '@/components/ShotChat';

type Act = ReturnType<typeof useAction>;

export function AnimateAll({sk, base, act}: {sk: any; base: string; act: Act}) {
  const all = sk?.animate_all;
  if (!all?.cost || !all.shots.length) return null;
  const go = () => {
    if (!window.confirm(confirmText(`Animate ${all.shots.length} approved shot(s) (${all.shots.join(', ')})`, all.cost))) return;
    act.run('sk-all', () => api(`${base}/animate-all`, {body: {seconds: sk.video.seconds, confirm_usd: all.cost.usd}}));
  };
  return <button className="btn sm primary" disabled={!!act.busy} onClick={go}>Animate all approved · {all.cost.label}</button>;
}

export function StickShotRow({s, sk, base, act, names}: {s: any; sk: any; base: string; act: Act; names: Record<string, string>}) {
  const [prompt, setPrompt] = useState(false);
  const info = (sk?.shots || []).find((x: any) => x.index === s.index);
  if (!sk || !info) return null;
  const stillCost = sk.image?.cost, clipCost = sk.video?.cost;
  const missing = info.missing_masters.map((k: string) => names[k] || k);
  const clip = chosenClip(info);
  const cs = clipStatus(info);
  const eid = episodeIdFromBase(base);
  const still = () => {
    if (!window.confirm(confirmText(`Make a still for shot ${s.index}`, stillCost))) return;
    act.run('sk-still', () => api(`${base}/${s.index}/still`, {body: {confirm_usd: stillCost.usd}}));
  };
  const animate = () => {
    if (!window.confirm(confirmText(`Animate shot ${s.index} (${sk.video.seconds} s)`, clipCost))) return;
    act.run('sk-anim', () => api(`${base}/${s.index}/animate`, {body: {seconds: sk.video.seconds, confirm_usd: clipCost.usd}}));
  };
  const clipCall = (what: 'approve' | 'unapprove' | 'choose', id: number) => act.run('sk-clip', () => api(`${base}/${s.index}/clip/${what}`, {body: {asset_id: id}}));
  return (
    <div className="stack sk-row" style={{gap: 6}}>
      <div className="row small" style={{gap: 6, flexWrap: 'wrap'}}>
        <button className="btn sm" disabled={!!act.busy || info.busy || !stillCost || missing.length > 0}
          title={missing.length ? `Approve a master for ${missing.join(', ')} first` : 'The set and the approved masters as references'}
          onClick={still}>{s.versions.some((v: any) => v.source === 'still') ? 'Still again' : 'Make still'}{stillCost ? ` · ${stillCost.label}` : ''}</button>
        {s.approved && <button className="btn sm primary" disabled={!!act.busy || info.busy || !clipCost} onClick={animate}>
          {info.clips.length ? 'Animate again' : `Animate (${sk.video.seconds} s)`}{clipCost ? ` · ${clipCost.label}` : ''}</button>}
        <button className="btn sm" onClick={() => setPrompt(!prompt)}>{prompt ? 'Hide prompt' : 'Prompt'}</button>
        {info.busy && <span className="muted">making…</span>}
      </div>
      {missing.length > 0 && <span className="small muted">No approved master: {missing.join(', ')}</span>}
      {prompt && <pre className="small" style={{whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto'}}>{info.prompt}</pre>}
      {eid && <ShotChat step="still" item={s.index} episodeId={eid} onApplied={() => act.run('sk-chat', async () => {})} />}
      {clip && <figure style={{margin: 0}}>
        {clip.url && <video src={clip.url} controls preload="metadata" style={{width: '100%', borderRadius: 6}} />}
        <figcaption className="row small" style={{gap: 6, flexWrap: 'wrap'}}>
          <span className={`badge ${cs.tone}`}>{cs.text}</span><span className="muted">{clip.seconds} s · ${clip.usd.toFixed(2)}</span>
          {info.clip_approved
            ? <button className="btn sm" disabled={!!act.busy} onClick={() => clipCall('unapprove', clip.asset_id)}>Unapprove clip</button>
            : <button className="btn sm good" disabled={!!act.busy} onClick={() => clipCall('approve', clip.asset_id)}>Approve clip</button>}
          {info.clips.length > 1 && <select aria-label={`Clip of shot ${s.index}`} value={info.clip_chosen ?? ''}
            onChange={e => clipCall('choose', Number(e.target.value))}>
            {info.clips.map((c: any, i: number) => <option key={c.asset_id} value={c.asset_id}>Clip {i + 1}</option>)}</select>}
        </figcaption>
        {eid && <ShotChat step="clip" item={s.index} episodeId={eid} onApplied={() => act.run('sk-chat', async () => {})} />}</figure>}
    </div>);
}
