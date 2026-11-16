'use client';
import {useId} from 'react';
// Structured editor for one scene: heading, location, direction and its dialogue lines.
export type Line = {speaker: string; text: string; expression?: string; shot?: string; duration?: number};
export type Scene = {id?: string; heading: string; location: string; description: string; action: string; camera: string; lines: Line[]};

export function SceneEditor({scene, onChange, characters, environments}: {
  scene: Scene; onChange: (s: Scene) => void; characters: any[]; environments: string[];
}) {
  const uid = useId();   // unique per editor: several scenes are edited on one page
  const set = (k: keyof Scene, v: any) => onChange({...scene, [k]: v});
  const setLine = (i: number, patch: Partial<Line>) => set('lines', scene.lines.map((l, j) => (j === i ? {...l, ...patch} : l)));
  const move = (i: number, d: number) => {
    const lines = [...scene.lines]; const [x] = lines.splice(i, 1); lines.splice(i + d, 0, x); set('lines', lines);
  };
  const exprs = (key: string) => Object.keys(characters.find(c => c.key === key)?.expressions || {});
  return (
    <div className="stack">
      <div className="grid cols-2">
        <div><label htmlFor={`${uid}-heading-1`}>Heading</label><input id={`${uid}-heading-1`} value={scene.heading} onChange={e => set('heading', e.target.value)} /></div>
        <div><label htmlFor={`${uid}-location-2`}>Location</label>
          <select id={`${uid}-location-2`} value={scene.location} onChange={e => set('location', e.target.value)}>
            <option value="">Default set</option>{environments.map(x => <option key={x} value={x}>{x}</option>)}
          </select></div>
      </div>
      <div className="grid cols-3">
        <div><label htmlFor={`${uid}-what-we-see-3`}>What we see</label><textarea id={`${uid}-what-we-see-3`} value={scene.description} onChange={e => set('description', e.target.value)} /></div>
        <div><label htmlFor={`${uid}-action-and-reactions-4`}>Action and reactions</label><textarea id={`${uid}-action-and-reactions-4`} value={scene.action} onChange={e => set('action', e.target.value)} /></div>
        <div><label htmlFor={`${uid}-camera-direction-5`}>Camera direction</label><textarea id={`${uid}-camera-direction-5`} value={scene.camera} onChange={e => set('camera', e.target.value)} /></div>
      </div>
      <div>
        <label>Dialogue and beats</label>
        {scene.lines.map((l, i) => (
          <div key={i} className="row" style={{marginBottom: 6, alignItems: 'flex-start'}}>
            <select style={{width: 150}} value={l.speaker} onChange={e => setLine(i, {speaker: e.target.value})} aria-label="Speaker">
              {characters.map(c => <option key={c.key} value={c.key}>{c.name}</option>)}
            </select>
            <input style={{flex: 1, minWidth: 200}} value={l.text} maxLength={140} onChange={e => setLine(i, {text: e.target.value})} aria-label="Line" />
            <input style={{width: 120}} list={`exp-${l.speaker}`} value={l.expression || ''} placeholder="expression" onChange={e => setLine(i, {expression: e.target.value})} aria-label="Expression" />
            <datalist id={`exp-${l.speaker}`}>{exprs(l.speaker).map(x => <option key={x} value={x} />)}</datalist>
            <select style={{width: 96}} value={l.shot || 'wide'} onChange={e => setLine(i, {shot: e.target.value})} aria-label="Shot">
              <option value="wide">wide</option><option value="medium">medium</option><option value="close">close</option>
            </select>
            <input style={{width: 70}} type="number" step="0.1" min={0.8} max={8} placeholder="sec" value={l.duration ?? ''}
                   onChange={e => setLine(i, {duration: e.target.value === '' ? undefined : Number(e.target.value)})} aria-label="Seconds" />
            <button className="btn sm" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move up">↑</button>
            <button className="btn sm" disabled={i === scene.lines.length - 1} onClick={() => move(i, 1)} aria-label="Move down">↓</button>
            <button className="btn sm danger" onClick={() => set('lines', scene.lines.filter((_, j) => j !== i))} aria-label="Remove line">✕</button>
          </div>))}
        <button className="btn sm" onClick={() => set('lines', [...scene.lines, {speaker: scene.lines.at(-1)?.speaker || characters[0]?.key || '', text: '', expression: 'neutral', shot: 'wide'}])}>Add line</button>
      </div>
    </div>
  );
}

export function SceneView({scene, characters}: {scene: Scene; characters: any[]}) {
  const name = (k: string) => characters.find(c => c.key === k)?.name || k;
  return (
    <div className="stack">
      {(scene.description || scene.action || scene.camera) && (
        <div className="grid cols-3 small">
          <div><strong>What we see</strong><div className="muted">{scene.description || '—'}</div></div>
          <div><strong>Action</strong><div className="muted">{scene.action || '—'}</div></div>
          <div><strong>Camera</strong><div className="muted">{scene.camera || '—'}</div></div>
        </div>)}
      <div>{scene.lines.map((l, i) => (
        <div key={i} className="line">
          <span className="speaker">{name(l.speaker)}</span><span>{l.text}</span>
          <span className="muted small">{l.expression}</span><span className="muted small">{l.shot}{l.duration ? ` · ${l.duration}s` : ''}</span>
        </div>))}</div>
    </div>
  );
}
