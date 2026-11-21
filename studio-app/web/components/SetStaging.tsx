'use client';
// Marking a set's seats and table front before approval (feat/seating). Click the picture to place a seat (at the
// feet; the hips are placed a little above and can be adjusted), or two corners for the table front: the part of the
// picture drawn again over seated characters, so they sit behind the table. Coordinates are the image's pixels.
import {useState} from 'react';

type Seat = {x: number; hip_y: number; feet_y: number};
type Box = {x0: number; y0: number; x1: number; y1: number};

export default function SetStaging({url, width, height, blocking, onChange}: {url: string; width: number; height: number; blocking: any; onChange: (b: any) => void}) {
  const [mode, setMode] = useState<'seat' | 'table' | null>(null);
  const [corner, setCorner] = useState<{x: number; y: number} | null>(null);
  const seats: Seat[] = blocking.seats || (blocking.seat ? [blocking.seat] : []);
  const tf: Box | null = blocking.table_front || null;
  const W = 300, k = W / width;
  const put = (patch: any) => { const {seat: _old, ...rest} = blocking; onChange({...rest, seats, ...patch}); };
  const click = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const x = Math.round((e.clientX - r.left) / k), y = Math.round((e.clientY - r.top) / k);
    if (mode === 'seat') { put({seats: [...seats, {x, feet_y: y, hip_y: Math.max(0, y - Math.round(height * 0.08))}]}); setMode(null); }
    else if (mode === 'table') {
      if (!corner) { setCorner({x, y}); return; }
      put({table_front: {x0: Math.min(corner.x, x), y0: Math.min(corner.y, y), x1: Math.max(corner.x, x), y1: Math.max(corner.y, y)}});
      setCorner(null); setMode(null);
    }
  };
  const num = (v: number, set: (n: number) => void, label: string) => <input type="number" aria-label={label} value={v} style={{width: 72}} onChange={e => set(Number(e.target.value))} />;
  return (
    <div className="stack">
      <div className="row" style={{gap: 6}}>
        <button type="button" className={`btn sm ${mode === 'seat' ? 'primary' : ''}`} onClick={() => setMode(mode === 'seat' ? null : 'seat')}>Add a seat (click its front edge)</button>
        <button type="button" className={`btn sm ${mode === 'table' ? 'primary' : ''}`} onClick={() => { setMode(mode === 'table' ? null : 'table'); setCorner(null); }}>Mark the table front (two corners)</button>
        {mode && <span className="muted">{mode === 'table' ? (corner ? 'now the opposite corner' : 'click one corner') : 'click where the seated feet rest'}</span>}
      </div>
      <div onClick={click} style={{position: 'relative', width: W, height: height * k, cursor: mode ? 'crosshair' : 'default'}}>
        <img src={url} alt="set" style={{width: W, height: height * k, borderRadius: 6, display: 'block'}} />
        <div style={{position: 'absolute', left: 0, right: 0, top: blocking.floor_y * k, borderTop: '2px solid red'}} />
        {seats.map((s, i) => <div key={i} title={`seat ${i + 1}`} style={{position: 'absolute', left: s.x * k - 7, top: s.hip_y * k - 7, width: 14, height: 14, borderRadius: 7, border: '3px solid gold', color: 'gold', fontSize: 10, lineHeight: '8px', textAlign: 'center'}}>{i + 1}</div>)}
        {tf && <div style={{position: 'absolute', left: tf.x0 * k, top: tf.y0 * k, width: (tf.x1 - tf.x0) * k, height: (tf.y1 - tf.y0) * k, border: '2px solid orange'}} />}
      </div>
      {seats.map((s, i) => <div key={i} className="row small" style={{gap: 4}}>Seat {i + 1}: x {num(s.x, n => put({seats: seats.map((o, j) => j === i ? {...o, x: n} : o)}), `seat ${i + 1} x`)}
        hips {num(s.hip_y, n => put({seats: seats.map((o, j) => j === i ? {...o, hip_y: n} : o)}), `seat ${i + 1} hips`)}
        feet {num(s.feet_y, n => put({seats: seats.map((o, j) => j === i ? {...o, feet_y: n} : o)}), `seat ${i + 1} feet`)}
        <button type="button" className="btn sm" onClick={() => put({seats: seats.filter((_, j) => j !== i)})}>Remove</button></div>)}
      {tf && <div className="row small" style={{gap: 4}}>Table front: {(['x0', 'y0', 'x1', 'y1'] as const).map(c => <span key={c}>{c} {num(tf[c], n => put({table_front: {...tf, [c]: n}}), `table front ${c}`)}</span>)}
        <button type="button" className="btn sm" onClick={() => put({table_front: null})}>Remove</button></div>}
      <span className="muted small">red: floor line · gold: seats (seated characters take them speaker first) · orange: table front</span>
    </div>);
}
