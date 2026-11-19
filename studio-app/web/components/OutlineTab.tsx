'use client';
import {useState} from 'react';
import {api} from '@/lib/api';

// Long-form, pass 1: the three-act outline the owner approves before any scene is written (D-L1 to D-L5).
const lines = (v: string) => v.split('\n').map(x => x.trim()).filter(Boolean);

export default function OutlineTab({ep, can, act, characters}: {ep: any; can: (a: string) => boolean; act: any; characters: any[]}) {
  const o = ep.outline;
  const [instruction, setInstruction] = useState('');
  const [comment, setComment] = useState('');
  const [draft, setDraft] = useState<any>(null);
  const job = ep.jobs.find((j: any) => j.kind === 'generate_outline');
  const name = (k: string) => characters.find(c => c.key === k)?.name || k;
  const generate = () => act.run('gen', () => api(`/episodes/${ep.id}/outline/generate`, {body: {instruction}}));
  if (draft) {
    const setScene = (ai: number, si: number, patch: any) => setDraft((d: any) => ({...d, acts: d.acts.map((a: any, i: number) => i !== ai ? a : {...a, scenes: a.scenes.map((s: any, j: number) => j !== si ? s : {...s, ...patch})})}));
    const total = draft.acts.reduce((t: number, a: any) => t + a.scenes.reduce((u: number, s: any) => u + Number(s.est_seconds || 0), 0), 0);
    return (
      <div className="stack">
        <div className="card stack">
          <div className="spread"><h2 style={{margin: 0}}>Edit outline</h2><span className={`badge ${total > 450 ? 'bad' : total < 300 ? 'warn' : 'good'}`}>about {Math.round(total)} s</span></div>
          <div className="grid cols-2">
            <div><label htmlFor="o-title">Title</label><input id="o-title" value={draft.title} onChange={e => setDraft({...draft, title: e.target.value})} /></div>
            <div><label htmlFor="o-log">Logline</label><input id="o-log" value={draft.logline} onChange={e => setDraft({...draft, logline: e.target.value})} /></div>
          </div>
          <div className="grid cols-3">
            {['premise', 'twist', 'ending'].map(k => <div key={k}><label htmlFor={`o-${k}`}>{k}</label><textarea id={`o-${k}`} value={draft[k] || ''} onChange={e => setDraft({...draft, [k]: e.target.value})} /></div>)}
          </div>
        </div>
        {draft.acts.map((a: any, ai: number) => (
          <div key={ai} className="card stack">
            <h3>Act {ai + 1}: <input aria-label={`Act ${ai + 1} title`} style={{width: 'auto', display: 'inline-block'}} value={a.title} onChange={e => setDraft((d: any) => ({...d, acts: d.acts.map((x: any, i: number) => i === ai ? {...x, title: e.target.value} : x)}))} /></h3>
            {a.scenes.map((s: any, si: number) => (
              <div key={s.id} className="grid cols-3" style={{borderTop: '1px dashed var(--line)', paddingTop: 8}}>
                <div><label htmlFor={`${s.id}-h`}>{s.id}: heading</label><input id={`${s.id}-h`} value={s.heading} onChange={e => setScene(ai, si, {heading: e.target.value})} />
                  <label htmlFor={`${s.id}-s`}>Summary</label><textarea id={`${s.id}-s`} value={s.summary} onChange={e => setScene(ai, si, {summary: e.target.value})} /></div>
                <div><label htmlFor={`${s.id}-b`}>Beats (one per line)</label><textarea id={`${s.id}-b`} value={s.beats.join('\n')} onChange={e => setScene(ai, si, {beats: lines(e.target.value)})} />
                  <label htmlFor={`${s.id}-j`}>Jokes (one per line)</label><textarea id={`${s.id}-j`} value={s.jokes.join('\n')} onChange={e => setScene(ai, si, {jokes: lines(e.target.value)})} /></div>
                <div><label htmlFor={`${s.id}-e`}>Estimated seconds</label><input id={`${s.id}-e`} type="number" min={4} max={90} value={s.est_seconds} onChange={e => setScene(ai, si, {est_seconds: Number(e.target.value)})} />
                  <label htmlFor={`${s.id}-c`}>Characters (keys, comma separated)</label><input id={`${s.id}-c`} value={s.characters.join(', ')} onChange={e => setScene(ai, si, {characters: e.target.value.split(',').map((x: string) => x.trim()).filter(Boolean)})} />
                  <button className="btn sm danger" style={{marginTop: 8}} disabled={a.scenes.length === 1} onClick={() => setDraft((d: any) => ({...d, acts: d.acts.map((x: any, i: number) => i === ai ? {...x, scenes: x.scenes.filter((_: any, j: number) => j !== si)} : x)}))}>Remove scene</button></div>
              </div>))}
            <button className="btn sm" onClick={() => setDraft((d: any) => ({...d, acts: d.acts.map((x: any, i: number) => i !== ai ? x : {...x, scenes: [...x.scenes, {id: `a${ai + 1}s${x.scenes.length + 1}x`, heading: 'New scene', summary: '', beats: ['What changes here'], jokes: [], characters: x.scenes[0]?.characters || [], location: '', est_seconds: 12}]})}))}>Add scene</button>
          </div>))}
        <div className="card row">
          <button className="btn primary" disabled={!!act.busy} onClick={() => act.run('save', async () => { await api(`/episodes/${ep.id}/outline`, {method: 'PUT', body: {content: draft, note: 'edited in the dashboard'}}); setDraft(null); })}>Save as new version</button>
          <button className="btn" onClick={() => setDraft(null)}>Cancel</button>
        </div>
      </div>
    );
  }
  return (
    <div className="stack">
      {job && (job.status === 'queued' || job.status === 'running') && <div className="alert info small">The outline is being written…</div>}
      {job?.status === 'failed' && <div className="alert bad small">Outline generation failed: {job.error}</div>}
      {!o ? (
        <div className="card stack">
          <h2>Three-act outline</h2>
          <p className="muted">A long episode is written in two passes: first this outline, which you approve, then the scenes act by act. The story decides the length; it is never padded.</p>
          <input placeholder="Extra direction for the writer (optional)" value={instruction} onChange={e => setInstruction(e.target.value)} />
          <button className="btn primary" disabled={!can('generate_outline') || !!act.busy} onClick={generate}>Generate outline</button>
        </div>
      ) : (
        <>
          <div className="card stack">
            <div className="spread">
              <div><h2 style={{marginBottom: 2}}>{o.content.title}</h2>
                <div className="muted small">Outline v{o.version} · {o.source} · about {Math.round(o.content.runtime_estimate_seconds)} s
                  {o.approved && <> · <span className="badge good">approved</span></>}</div></div>
              <div className="row">
                <button className="btn" disabled={!can('edit_outline')} onClick={() => setDraft(JSON.parse(JSON.stringify(o.content)))}>Edit</button>
                <button className="btn" disabled={!can('generate_outline') || !!act.busy} onClick={generate}>Regenerate</button>
              </div>
            </div>
            <p><strong>Logline:</strong> {o.content.logline}</p>
            <div className="grid cols-3 small">
              <div><strong>Premise</strong><div className="muted">{o.content.premise || '—'}</div></div>
              <div><strong>Twist</strong><div className="muted">{o.content.twist || '—'}</div></div>
              <div><strong>Ending</strong><div className="muted">{o.content.ending || '—'}</div></div>
            </div>
            {o.content.quality_notes && <p className="small"><strong>Why it earns its length:</strong> {o.content.quality_notes}</p>}
            {o.warnings.map((w: string, i: number) => <div key={i} className="alert warn small">{w}</div>)}
            {o.content.new_characters?.length > 0 && <div className="alert info small"><strong>New characters:</strong> {o.content.new_characters.map((c: any) => `${c.name} (${c.visual_description})`).join('; ')}</div>}
          </div>
          {o.content.acts.map((a: any) => (
            <div key={a.act} className="card">
              <div className="spread"><h3 style={{margin: 0}}>Act {a.act}: {a.title}</h3>
                <span className="muted small">{a.scenes.length} scenes · about {Math.round(a.scenes.reduce((t: number, s: any) => t + s.est_seconds, 0))} s</span></div>
              <p className="muted small">{a.purpose}</p>
              <div className="table-wrap"><table>
                <thead><tr><th>Scene</th><th>What happens</th><th>Beats</th><th>Jokes</th><th>On screen</th><th>≈ s</th></tr></thead>
                <tbody>{a.scenes.map((s: any) => (
                  <tr key={s.id}><td><strong>{s.heading}</strong><div className="muted small mono">{s.id}</div></td><td className="small">{s.summary}</td>
                    <td className="small"><ul style={{margin: 0, paddingLeft: 16}}>{s.beats.map((b: string, i: number) => <li key={i}>{b}</li>)}</ul></td>
                    <td className="small"><ul style={{margin: 0, paddingLeft: 16}}>{s.jokes.map((b: string, i: number) => <li key={i}>{b}</li>)}</ul></td>
                    <td className="small">{s.characters.map(name).join(', ')}</td><td>{s.est_seconds}</td></tr>))}
                </tbody></table></div>
            </div>))}
          {can('generate_outline') && <div className="card"><label htmlFor="o-ins">Instruction for regeneration</label><input id="o-ins" value={instruction} onChange={e => setInstruction(e.target.value)} placeholder="e.g. a stronger midpoint twist" /></div>}
          {can('approve_outline') && (
            <div className="card stack">
              <h2>Your decision</h2>
              <textarea placeholder="Comment" value={comment} onChange={e => setComment(e.target.value)} />
              <div className="row">
                <button className="btn good" disabled={!!act.busy} onClick={() => act.run('ok', () => api(`/episodes/${ep.id}/outline/approve`, {body: {comment}}))}>Approve outline</button>
                <button className="btn danger" disabled={!!act.busy || !comment} onClick={() => act.run('no', () => api(`/episodes/${ep.id}/outline/reject`, {body: {comment}}))}>Send back</button>
              </div>
            </div>)}
          {ep.stage === 'outline_approved' && (
            <div className="card spread"><div><h2 style={{marginBottom: 2}}>Develop the scenes</h2><span className="muted">The writer develops act 1, then act 2, then act 3, each consistent with the acts before it.</span></div>
              <button className="btn primary" disabled={!!act.busy} onClick={() => act.run('dev', () => api(`/episodes/${ep.id}/script/generate`, {body: {}}))}>Develop scenes act by act</button></div>)}
        </>)}
    </div>
  );
}
