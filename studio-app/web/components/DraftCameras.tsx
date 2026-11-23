'use client';
// The draft's camera per scene: the set plate with the 9:16 crop drawn on it (the computed one by default), everyone's
// place, and the safe margin. The crop can be moved and resized; it always stays 9:16 and inside the plate (no bars).
import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import {clampCrop} from '@/lib/talkingShots';

export default function DraftCameras({ep}: {ep: any}) {
  const c = useApi<any>(`/episodes/${ep.id}/draft/cameras`);
  const [err, setErr] = useState('');
  const save = async (scene_id: number, crop: any) => {
    setErr('');
    try { await api(`/episodes/${ep.id}/draft/cameras`, {method: 'PUT', body: {scene_id, crop}}); await c.reload(); } catch (e: any) { setErr(e.message); }
  };
  if (!c.data) return <ErrorBox error={c.error} />;
  return (
    <div className="stack">
      <ErrorBox error={err} />
      <div className="row" style={{gap: 12, flexWrap: 'wrap', alignItems: 'flex-start'}}>
        {c.data.scenes.map((s: any) => s.error ? <div key={s.scene_id} className="small bad">Scene {s.scene}: {s.error}</div>
          : <SceneCamera key={s.scene_id} s={s} margin={c.data.safe_margin} onSave={crop => save(s.scene_id, crop)} />)}
      </div>
    </div>);
}

function SceneCamera({s, margin, onSave}: {s: any; margin: number; onSave: (crop: any) => void}) {
  const start = s.own || s.computed;
  const [crop, setCrop] = useState({x: start.x, y: start.y, w: start.w});
  useEffect(() => { const b = s.own || s.computed; setCrop({x: b.x, y: b.y, w: b.w}); }, [s.own?.x, s.own?.y, s.own?.w, s.computed.x, s.computed.y, s.computed.w]);  // eslint-disable-line react-hooks/exhaustive-deps
  const {w: pw, h: ph} = s.plate;
  const set = (k: string, v: number) => setCrop(cr => clampCrop({...cr, [k]: v}, pw, ph));
  const h = crop.w * 16 / 9;
  const m = margin * crop.w;
  const changed = !s.own ? (crop.x !== s.computed.x || crop.y !== s.computed.y || crop.w !== s.computed.w)
    : (crop.x !== s.own.x || crop.y !== s.own.y || crop.w !== s.own.w);
  return (
    <div className="stack small" style={{width: 220}}>
      <strong>Scene {s.scene} {s.own ? '· your crop' : '· computed crop'}</strong>
      <svg viewBox={`0 0 ${pw} ${ph}`} style={{width: 220, background: '#ddd'}} aria-label={`scene ${s.scene} crop on the set`}>
        {s.plate_url && <image href={s.plate_url} x={0} y={0} width={pw} height={ph} />}
        <path d={`M0 0H${pw}V${ph}H0Z M${crop.x} ${crop.y}v${h}h${crop.w}v${-h}Z`} fill="rgba(0,0,0,0.45)" fillRule="evenodd" />
        {Object.entries(s.boxes).map(([k, b]: [string, any]) => (
          <rect key={k} x={b.left} y={b.top} width={b.right - b.left} height={b.shoulder_y - b.top} fill="none" stroke="#2b8a3e" strokeWidth={4}><title>{k}</title></rect>))}
        <rect x={crop.x} y={crop.y} width={crop.w} height={h} fill="none" stroke="#e8590c" strokeWidth={6} />
        <line x1={crop.x + m} x2={crop.x + m} y1={crop.y} y2={crop.y + h} stroke="#e8590c" strokeDasharray="12 10" strokeWidth={3} />
        <line x1={crop.x + crop.w - m} x2={crop.x + crop.w - m} y1={crop.y} y2={crop.y + h} stroke="#e8590c" strokeDasharray="12 10" strokeWidth={3} />
      </svg>
      <label>Left <input type="range" min={0} max={Math.max(0, pw - crop.w)} value={crop.x} onChange={e => set('x', Number(e.target.value))} /></label>
      <label>Top <input type="range" min={0} max={Math.max(0, ph - h)} value={crop.y} onChange={e => set('y', Number(e.target.value))} /></label>
      <label>Width <input type="range" min={120} max={Math.min(pw, ph * 9 / 16)} value={crop.w} onChange={e => set('w', Number(e.target.value))} /></label>
      {(s.notes || []).map((n: string, i: number) => <div key={i} className="muted">{n}</div>)}
      <div className="row" style={{gap: 6}}>
        <button className="btn sm" disabled={!changed} onClick={() => onSave(crop)}>Use this crop</button>
        {s.own && <button className="btn sm" onClick={() => onSave(null)}>Back to computed</button>}
      </div>
    </div>);
}
