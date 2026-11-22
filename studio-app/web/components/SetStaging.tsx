'use client';
// A set's staging, edited on the picture (feat/seating; feat/episode-workspace adds the floor and standing lines): click
// the picture to place a seat (at the feet; the hips are placed a little above and can be adjusted), two corners for the
// desk or table front (the part of the picture drawn again over seated characters, so they sit behind it), the floor
// line (where standing feet rest), or the two ends of the standing area. Coordinates are the image's pixels.
import {useState} from 'react';

type Seat = {x: number; hip_y: number; feet_y: number};
type Box = {x0: number; y0: number; x1: number; y1: number};
type Mode = 'seat' | 'table' | 'floor' | 'stand' | null;

const HINT: Record<string, string> = {seat: 'click where the seated feet rest', table: 'click one corner of the desk front',
  table2: 'now the opposite corner', floor: 'click where standing feet rest', stand: 'click the left end of the standing area',
  stand2: 'now the right end'};

export default function SetStaging({url, width, height, blocking, onChange, size = 300}: {url: string; width: number; height: number;
  blocking: any; onChange: (b: any) => void; size?: number}) {
  const [mode, setMode] = useState<Mode>(null);
  const [corner, setCorner] = useState<{x: number; y: number} | null>(null);
  const seats: Seat[] = blocking.seats || (blocking.seat ? [blocking.seat] : []);
  const tf: Box | null = blocking.table_front || null;
  const W = size, k = W / width;
  const put = (patch: any) => { const {seat: _old, ...rest} = blocking; onChange({...rest, seats, ...patch}); };
  const pick = (m: Mode) => { setMode(mode === m ? null : m); setCorner(null); };
  const click = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const x = Math.round((e.clientX - r.left) / k), y = Math.round((e.clientY - r.top) / k);
    if (mode === 'seat') { put({seats: [...seats, {x, feet_y: y, hip_y: Math.max(0, y - Math.round(height * 0.08))}]}); setMode(null); }
    else if (mode === 'floor') { put({floor_y: y}); setMode(null); }
    else if (mode === 'table' || mode === 'stand') {
      if (!corner) { setCorner({x, y}); return; }
      if (mode === 'table') put({table_front: {x0: Math.min(corner.x, x), y0: Math.min(corner.y, y), x1: Math.max(corner.x, x), y1: Math.max(corner.y, y)}});
      else put({stand_min_x: Math.min(corner.x, x), stand_max_x: Math.max(corner.x, x)});
      setCorner(null); setMode(null);
    }
  };
  const num = (v: number, set: (n: number) => void, label: string) => <input type="number" aria-label={label} value={v ?? ''} style={{width: 72}} onChange={e => set(Number(e.target.value))} />;
  const btn = (m: Exclude<Mode, null>, label: string) => <button type="button" className={`btn sm ${mode === m ? 'primary' : ''}`} onClick={() => pick(m)}>{label}</button>;
  return (
    <div className="stack">
      <div className="row" style={{gap: 6, flexWrap: 'wrap'}}>
        {btn('seat', 'Add a seat')}{btn('table', 'Mark the desk front')}{btn('floor', 'Set the floor line')}{btn('stand', 'Set the standing area')}
        {mode && <span className="muted small">{HINT[(mode === 'table' || mode === 'stand') && corner ? `${mode}2` : mode]}</span>}
      </div>
      <div onClick={click} role="img" aria-label="set picture with its staging"
           style={{position: 'relative', width: W, height: height * k, flex: 'none', cursor: mode ? 'crosshair' : 'default'}}>
        <img src={url} alt="set" style={{width: W, height: height * k, borderRadius: 6, display: 'block'}} />
        <div title="floor line" style={{position: 'absolute', left: 0, right: 0, top: blocking.floor_y * k, borderTop: '2px solid red'}} />
        {blocking.stand_min_x != null && <div title="standing area" style={{position: 'absolute', left: blocking.stand_min_x * k, top: blocking.floor_y * k - 5,
          width: (blocking.stand_max_x - blocking.stand_min_x) * k, height: 10, border: '2px solid #28c8ff', borderRadius: 3}} />}
        {seats.map((s, i) => <div key={i} title={`seat ${i + 1}${i === 0 ? ' (the speaker sits here first)' : ''}`}>
          <div style={{position: 'absolute', left: s.x * k - 9, top: s.hip_y * k - 9, width: 18, height: 18, borderRadius: 9,
            border: '3px solid gold', background: 'rgba(0,0,0,.45)', color: 'gold', fontSize: 10, lineHeight: '12px', textAlign: 'center', fontWeight: 700}}>{i + 1}</div>
          <div style={{position: 'absolute', left: s.x * k - 12, top: s.feet_y * k, width: 24, borderTop: '2px solid gold'}} /></div>)}
        {tf && <div title="desk front" style={{position: 'absolute', left: tf.x0 * k, top: tf.y0 * k, width: (tf.x1 - tf.x0) * k, height: (tf.y1 - tf.y0) * k, border: '2px solid orange'}} />}
      </div>
      <details><summary className="small">Exact positions (pixels)</summary><div className="stack">
      <div className="row small" style={{gap: 4, flexWrap: 'wrap'}}>Floor line y {num(blocking.floor_y, n => put({floor_y: n}), 'floor line')}
        standing from x {num(blocking.stand_min_x, n => put({stand_min_x: n}), 'standing area from x')} to {num(blocking.stand_max_x, n => put({stand_max_x: n}), 'standing area to x')}</div>
      {seats.map((s, i) => <div key={i} className="row small" style={{gap: 4, flexWrap: 'wrap'}}>Seat {i + 1}{i === 0 ? ' (speaker)' : ''}: x {num(s.x, n => put({seats: seats.map((o, j) => j === i ? {...o, x: n} : o)}), `seat ${i + 1} x`)}
        hips {num(s.hip_y, n => put({seats: seats.map((o, j) => j === i ? {...o, hip_y: n} : o)}), `seat ${i + 1} hips`)}
        feet {num(s.feet_y, n => put({seats: seats.map((o, j) => j === i ? {...o, feet_y: n} : o)}), `seat ${i + 1} feet`)}
        <button type="button" className="btn sm" onClick={() => put({seats: seats.filter((_, j) => j !== i)})}>Remove</button></div>)}
      {tf && <div className="row small" style={{gap: 4, flexWrap: 'wrap'}}>Desk front: {(['x0', 'y0', 'x1', 'y1'] as const).map(c => <span key={c}>{c} {num(tf[c], n => put({table_front: {...tf, [c]: n}}), `table front ${c}`)}</span>)}
        <button type="button" className="btn sm" onClick={() => put({table_front: null})}>Remove</button></div>}
      </div></details>
      <span className="muted small">{seats.length} seat(s){tf ? ', desk front marked' : ', no desk front'} · red: floor line · blue: standing area · gold: seats (seated characters take them in order, the speaker first) · orange: desk front</span>
    </div>);
}
