'use client';
// A storyboard scene's set (feat/scene-sets): one of the episode's sets; changed while the storyboard is in review.
import {useState} from 'react';
import {api} from '@/lib/api';

export default function SceneSetSelect({ep, scene, onChange}: {ep: any; scene: any; onChange: () => unknown}) {
  const [err, setErr] = useState('');
  const sets: string[] = [ep.set_id, ...(ep.scene_set_ids || [])].filter(Boolean);
  const current = scene.set_id || ep.set_id;
  if (sets.length < 2) return current ? <div className="small muted">Set: {current}</div> : null;
  const change = async (v: string) => {
    setErr('');
    try { await api(`/episodes/${ep.id}/scenes/${scene.id}/set`, {method: 'PUT', body: {set_id: v}}); await onChange(); }
    catch (e: any) { setErr(e.message); }
  };
  return (
    <div className="row small" style={{gap: 6}}>
      <label htmlFor={`scene-set-${scene.id}`}>Set</label>
      <select id={`scene-set-${scene.id}`} value={current} disabled={ep.stage !== 'storyboard_review'} onChange={e => change(e.target.value)}>
        {sets.map(s => <option key={s} value={s}>{s}{s === ep.set_id ? ' (episode set)' : ''}</option>)}
      </select>
      {scene.staging && <span className="muted">starts: {Object.entries(scene.staging).map(([k, v]) => `${k} ${v}`).join(', ')}</span>}
      {err && <span className="bad">{err}</span>}
    </div>);
}
