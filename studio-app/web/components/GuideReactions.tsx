'use client';
// Guided page, steps 6-8 "Reactions and close-ups" (API: reactions.py). One component, three parts:
//   closeups  pick the seating picture of each side of the room, then each reaction shot's crop (click to move it,
//             slider to zoom) and "Approve crop" (free).
//   faces     the face ovals, the poses from the acting notes (what each face shows, when, the prompt with its
//             eyeline), "Make poses" (paid, price confirmed first), and Approve / Redo on every pose with its chat.
//   movement  the timeline, the move prompts, "Animate" (paid, price confirmed first), the assembled shot with
//             Approve and its chat.
// Paid buttons send the "at most" amount they showed (the API refuses anything else with 409). Nothing approves itself.
import Link from 'next/link';
import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import ShotChat from '@/components/ShotChat';
import {isActive, progress, usd} from '@/lib/talkingGuide';
import {clickToPicture, cropStyle, moveKey, ovalStyle, poseBadge, poseButton, poseItem, segmentText, widthToZoom,
  zoomToWidth, BASE_H, BASE_W} from '@/lib/reactionsGuide';

type Act = ReturnType<typeof useAction>;
type Part = 'closeups' | 'faces' | 'movement';

const pic = {position: 'relative' as const, borderRadius: 6, overflow: 'hidden', border: '1px solid var(--line)'};

export default function GuideReactions({id, part, onChange}: {id: string; part: Part; onChange: () => unknown}) {
  const [poll, setPoll] = useState(15000);
  const {data: r, error, reload} = useApi<any>(`/episodes/${id}/reactions`, poll);
  const act = useAction(async () => { await reload(); await onChange(); });
  const [now, setNow] = useState(() => Date.now() / 1000);
  const running = !!r && (r.busy || (r.shots || []).some((s: any) => isActive(s.run) || s.run?.status === 'running'));
  useEffect(() => { setPoll(running ? 4000 : 15000); if (r && !running) onChange(); }, [running]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!running) return;
    const h = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(h);
  }, [running]);
  if (!r) return error ? <ErrorBox error={error} /> : <p className="small muted">Loading…</p>;
  const av = r.availability || {};
  const shots = r.shots || [];
  return (
    <div className="stack">
      <ErrorBox error={act.error} />
      {part !== 'closeups' && !av.ok && av.reason && <p className="small bad">{av.reason}{' '}<Link href="/settings#gpu-worker">Open Settings</Link></p>}
      {part !== 'closeups' && av.ok && <p className="small muted">GPU: {(av.gpus || []).map((g: any) => `${g.id.replace('NVIDIA ', '')} ${usd(g.usd_per_hour)}/h`).join(', then ')}
        {' '}· this month {usd(av.spent_usd)} of {usd(av.cap_usd)}
        {r.busy && <> · <button className="btn sm danger" disabled={!!act.busy} onClick={() => window.confirm('Turn the rented GPU off now? The step running now fails and can be run again.')
          && act.run('stop', () => api(`/episodes/${id}/reactions/stop`, {method: 'POST'}))}>Stop the GPU now</button></>}</p>}
      {r.job?.status === 'failed' && part !== 'closeups' && <p className="small bad">The last GPU run stopped: {r.job.error}</p>}
      {shots.length === 0 && <p className="small muted">No reaction shots yet. They come from the storyboard: every shot where nobody on screen is talking.</p>}
      {part === 'closeups' && <Masters r={r} id={id} act={act} />}
      {shots.map((s: any) => <ShotCard key={s.index} s={s} id={id} act={act} part={part} r={r} now={now} />)}
    </div>);
}

function Masters({r, id, act}: {r: any; id: string; act: Act}) {
  return (
    <div className="stack" style={{gap: 8}}>
      {(r.masters || []).map((m: any) => (
        <div key={m.side} className="card stack" style={{padding: 10, gap: 6}}>
          <div className="spread"><strong>Seating picture: {m.side} <span className="small muted">({m.shots} reaction shot(s))</span></strong>
            <span className="row small">Eyes look
              <select aria-label={`Eyeline for ${m.side}`} value={m.eyeline || m.eyeline_default} disabled={!!act.busy}
                onChange={e => act.run(`e${m.side}`, () => api(`/episodes/${id}/reactions/masters`, {method: 'PUT', body: {side: m.side, eyeline: e.target.value}}))}>
                <option value="left">slightly screen-left (listeners)</option>
                <option value="right">slightly screen-right (speaker)</option>
              </select></span></div>
          {m.candidates.length === 0 && <span className="small muted">No approved still on this side yet (step 5).</span>}
          <div className="row" style={{flexWrap: 'wrap', gap: 8}}>
            {m.candidates.map((c: any) => (
              <button key={c.asset_id} className="btn sm" style={{padding: 2, outline: m.chosen === c.asset_id ? '3px solid var(--good)' : 'none'}}
                disabled={!!act.busy} title={`Shot ${c.shot}, ${c.framing}, ${c.people} people`}
                onClick={() => act.run(`m${m.side}`, () => api(`/episodes/${id}/reactions/masters`, {method: 'PUT', body: {side: m.side, asset_id: c.asset_id}}))}>
                {c.url ? <img src={c.url} alt={`Shot ${c.shot} still`} style={{width: 150, display: 'block', borderRadius: 4}} /> : `Shot ${c.shot}`}
                <span className="small">{m.chosen === c.asset_id ? 'Chosen' : m.suggested === c.asset_id ? 'Suggested' : `Shot ${c.shot}`}</span>
              </button>))}
          </div>
        </div>))}
    </div>);
}

function ShotCard({s, id, act, part, r, now}: {s: any; id: string; act: Act; part: Part; r: any; now: number}) {
  const prog = progress(s.run?.status === 'running' ? {...s.run, status: 'rendering'} : s.run, now);
  const badge = part === 'closeups' ? (s.crop_approved ? ['Crop approved', 'good'] : s.crop ? ['Needs your approval', 'warn'] : ['', ''])
    : part === 'movement' ? (s.approved ? ['Approved', 'good'] : (s.clips || []).length ? ['Needs your approval', 'warn'] : ['', '']) : ['', ''];
  return (
    <div className="card stack" style={{padding: 12}}>
      <div className="spread">
        <strong>Shot {s.index} · {s.people.map((p: any) => p.name).join(', ')} <span className="small muted">{s.t0.toFixed(1)}–{s.t1.toFixed(1)} s · {s.kind === 'close' ? 'close-up' : 'group'} · {s.side}</span></strong>
        <span className="row">{badge[0] && <span className={`badge ${badge[1]}`}>{badge[0]}</span>}{s.blocked && <span className="badge">{s.blocked}</span>}</span>
      </div>
      {prog.label && part !== 'closeups' && <span className={`small ${s.run?.status === 'failed' ? 'bad' : ''}`} aria-live="polite">{prog.label}</span>}
      {!s.blocked && part === 'closeups' && <CropPart s={s} id={id} act={act} />}
      {!s.blocked && part === 'faces' && <FacesPart s={s} id={id} act={act} r={r} />}
      {!s.blocked && part === 'movement' && <MovePart s={s} id={id} act={act} r={r} />}
    </div>);
}

function CropPart({s, id, act}: {s: any; id: string; act: Act}) {
  const m = s.master;
  const [zoom, setZoom] = useState(() => (m && s.crop ? widthToZoom(s.crop.w, m.size[0], m.size[1]) : 50));
  useEffect(() => { if (m && s.crop) setZoom(widthToZoom(s.crop.w, m.size[0], m.size[1])); }, [s.crop?.w]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!m || !s.crop) return null;
  const put = (cx: number, cy: number, w: number) => act.run(`c${s.index}`, () => api(`/episodes/${id}/reactions/${s.index}/crop`, {method: 'PUT', body: {cx, cy, w}}));
  const centre = {x: s.crop.x + s.crop.w / 2, y: s.crop.y + s.crop.h / 2};
  const click = (e: React.MouseEvent<HTMLDivElement>) => {
    const b = e.currentTarget.getBoundingClientRect();
    const p = clickToPicture(e.clientX - b.left, e.clientY - b.top, b.width, b.height, m.size[0], m.size[1]);
    put(p.x, p.y, s.crop.w);
  };
  return (
    <div style={{display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 12}}>
      <div className="stack" style={{gap: 6}}>
        <div role="button" tabIndex={0} aria-label="Click to move the crop" onClick={click} style={{...pic, cursor: 'crosshair', aspectRatio: `${m.size[0]} / ${m.size[1]}`}}>
          {m.url && <img src={m.url} alt="Seating picture" style={{width: '100%', height: '100%', display: 'block'}} />}
          <span style={{position: 'absolute', ...cropStyle(s.crop, m.size[0], m.size[1]), border: '2px solid #e5484d', boxShadow: '0 0 0 9999px rgba(0,0,0,0.35)'}} />
        </div>
        <label className="small row" style={{margin: 0}}>Zoom
          <input type="range" min={5} max={100} value={zoom} disabled={!!act.busy} onChange={e => setZoom(Number(e.target.value))}
            onMouseUp={() => put(centre.x, centre.y, zoomToWidth(zoom, m.size[0], m.size[1]))}
            onKeyUp={() => put(centre.x, centre.y, zoomToWidth(zoom, m.size[0], m.size[1]))} /></label>
        <span className="small muted">Crop {s.crop.source === 'owner' ? 'set by you' : 'suggested from the head'}. Click the picture to move it.</span>
      </div>
      <div className="stack" style={{gap: 6}}>
        {s.base_url && <img src={s.base_url} alt={`Shot ${s.index} crop`} style={{width: '100%', borderRadius: 6}} />}
        <div className="row">
          {s.crop_approved ? <><span className="badge good">Approved</span>
            <button className="btn sm" disabled={!!act.busy} onClick={() => act.run(`a${s.index}`, () => api(`/episodes/${id}/reactions/${s.index}/crop/approve`, {body: {approved: false}}))}>Withdraw</button></>
            : <button className="btn sm good" disabled={!!act.busy} onClick={() => act.run(`a${s.index}`, () => api(`/episodes/${id}/reactions/${s.index}/crop/approve`, {body: {approved: true}}))}>Approve crop</button>}
        </div>
      </div>
    </div>);
}

function FacesPart({s, id, act, r}: {s: any; id: string; act: Act; r: any}) {
  const [who, setWho] = useState(s.people[0]?.key);
  if (!s.crop) return null;
  const o = s.ovals?.[who];
  const putOval = (patch: any) => act.run(`o${s.index}`, () => api(`/episodes/${id}/reactions/${s.index}/oval`, {method: 'PUT', body: {character: who, ...o, ...patch, source: undefined}}));
  const click = (e: React.MouseEvent<HTMLDivElement>) => {
    const b = e.currentTarget.getBoundingClientRect();
    const p = clickToPicture(e.clientX - b.left, e.clientY - b.top, b.width, b.height, BASE_W, BASE_H);
    putOval({cx: p.x, cy: p.y});
  };
  const todo = s.poses_todo || [];
  const makeAll = () => {
    const e = s.estimate_poses;
    if (!window.confirm(`Make ${todo.length} pose(s) of shot ${s.index} on a rented GPU: ${e.label}. The GPU is turned off when they are done. Start now?`)) return;
    act.run(`g${s.index}`, () => api(`/episodes/${id}/reactions/${s.index}/poses/generate`, {body: {poses: null, confirm_usd: e.usd_max}}));
  };
  return (
    <div className="stack">
      {!s.crop_approved && <p className="small bad">Approve this shot&rsquo;s crop in step 6 first.</p>}
      <div style={{display: 'grid', gridTemplateColumns: 'minmax(200px, 360px) minmax(0, 1fr)', gap: 12}}>
        <div className="stack" style={{gap: 6}}>
          <div role="button" tabIndex={0} aria-label="Click to move the face oval" onClick={click} style={{...pic, cursor: 'crosshair', aspectRatio: '16 / 9'}}>
            {s.base_url && <img src={s.base_url} alt={`Shot ${s.index} crop`} style={{width: '100%', height: '100%', display: 'block'}} />}
            {Object.entries(s.ovals || {}).map(([k, ov]: [string, any]) => <span key={k} title={k} style={{position: 'absolute', ...ovalStyle(ov), borderRadius: '50%',
              border: `2px solid ${k === who ? '#e5484d' : '#f5a524'}`}} />)}
          </div>
          {s.people.length > 1 && <select aria-label="Whose face oval" value={who} onChange={e => setWho(e.target.value)}>
            {s.people.map((p: any) => <option key={p.key} value={p.key}>{p.name}</option>)}</select>}
          {o && <div className="row small">
            <label style={{margin: 0}}>Width <input type="range" min={8} max={400} defaultValue={o.rx} key={`rx${o.rx}`} disabled={!!act.busy} onMouseUp={e => putOval({rx: Number((e.target as HTMLInputElement).value)})} /></label>
            <label style={{margin: 0}}>Height <input type="range" min={8} max={360} defaultValue={o.ry} key={`ry${o.ry}`} disabled={!!act.busy} onMouseUp={e => putOval({ry: Number((e.target as HTMLInputElement).value)})} /></label>
          </div>}
          <span className="small muted">Only the inside of the oval can change. Click the picture to move {s.people.find((p: any) => p.key === who)?.name}&rsquo;s oval.</span>
        </div>
        <div className="stack" style={{gap: 6}}>
          <strong className="small">Acting notes for this shot</strong>
          {(s.beats || []).length === 0 && <span className="small muted">No acting notes for this shot yet (step 2). Pose 0 is the crop as it is; add poses below.</span>}
          {(s.beats || []).map((b: any) => <div key={b.index} className="small">{Number(b.t_start).toFixed(1)} s · {b.character}: {b.expression}{b.eyes_and_gaze ? `; ${b.eyes_and_gaze}` : ''} <span className="muted">({b.hold_or_move}, {b.intensity})</span></div>)}
          <div className="row">
            <button className="btn sm" disabled={!!act.busy} onClick={() => window.confirm('Make the poses again from the acting notes? Pose pictures made so far leave the list.')
              && act.run(`fb${s.index}`, () => api(`/episodes/${id}/reactions/${s.index}/poses/from-beats`, {method: 'POST'}))}>Poses from the notes again</button>
            <ShotChat step="acting" item={s.index} episodeId={id} onApplied={() => act.run('x', async () => {})} />
          </div>
        </div>
      </div>
      <div className="row">
        <button className="btn primary sm" disabled={!!act.busy || r.busy || !r.availability?.ok || !s.crop_approved || todo.length === 0} onClick={makeAll}>{poseButton(s.estimate_poses, todo.length)}</button>
        {todo.length > 0 && <span className="small muted">{s.estimate_poses?.label}</span>}
      </div>
      <div className="row" style={{flexWrap: 'wrap', alignItems: 'flex-start', gap: 12}}>
        {s.poses.map((p: any) => <PoseCard key={p.id} p={p} s={s} id={id} act={act} r={r} />)}
      </div>
    </div>);
}

function PoseCard({p, s, id, act, r}: {p: any; s: any; id: string; act: Act; r: any}) {
  const [label, setLabel] = useState(p.label);
  const [t, setT] = useState(String(p.t));
  const [wants, setWants] = useState<Record<string, string>>(() => Object.fromEntries(s.people.map((x: any) => [x.key, p.faces[x.key]?.want || ''])));
  const [prompts, setPrompts] = useState<Record<string, string>>(() => Object.fromEntries(Object.entries(p.faces).map(([k, f]: [string, any]) => [k, f.prompt?.text || ''])));
  useEffect(() => {
    setLabel(p.label); setT(String(p.t));
    setWants(Object.fromEntries(s.people.map((x: any) => [x.key, p.faces[x.key]?.want || ''])));
    setPrompts(Object.fromEntries(Object.entries(p.faces).map(([k, f]: [string, any]) => [k, f.prompt?.text || ''])));
  }, [JSON.stringify(p.faces), p.label, p.t]);   // eslint-disable-line react-hooks/exhaustive-deps
  const b = poseBadge(p, s.crop_approved);
  const base = `/episodes/${id}/reactions/${s.index}/poses/${p.i}`;
  const save = () => {
    const changedPrompts = Object.fromEntries(Object.entries(prompts).filter(([k, v]) => v && v !== p.faces[k]?.prompt?.text && wants[k] === (p.faces[k]?.want || '')));
    act.run(`s${p.id}`, () => api(base, {method: 'PUT', body: {label, ...(p.i > 0 ? {t: Number(t)} : {}), faces: wants,
      ...(Object.keys(changedPrompts).length ? {prompts: changedPrompts} : {})}}));
  };
  const write = () => {
    const pe = r.prompt_estimate;
    const n = Object.keys(p.faces).length;
    if (r.openai_key && !window.confirm(`Write ${n} face prompt(s) with ${pe?.model}: at most ${usd((pe?.usd_max || 0) * n, 4)}. Send now?`)) return;
    act.run(`w${p.id}`, () => api(`${base}/write-prompt`, {body: {confirm_usd: (pe?.usd_max || 0) * n}}));
  };
  const redo = () => {
    const e = p.estimate;
    if (!window.confirm(`Make pose ${p.i} again on a rented GPU: ${e.label}. Start now?`)) return;
    act.run(`r${p.id}`, () => api(`/episodes/${id}/reactions/${s.index}/poses/generate`, {body: {poses: [p.i], confirm_usd: e.usd_max}}));
  };
  return (
    <figure className="card stack" style={{margin: 0, width: 330, padding: 10, gap: 6}}>
      <div className="spread small"><strong>Pose {p.i}{p.i > 0 ? ` · ${p.t.toFixed(2)} s` : ''}</strong><span className={`badge ${b.tone}`}>{b.text}</span></div>
      <input aria-label="Pose name" value={label} onChange={e => setLabel(e.target.value)} maxLength={120} />
      {p.i > 0 && <label className="small row" style={{margin: 0}}>Starts at <input type="number" step={0.05} min={0} value={t} onChange={e => setT(e.target.value)} style={{width: 80}} /> s into the shot</label>}
      {s.people.map((x: any) => (
        <div key={x.key} className="stack" style={{gap: 2}}>
          <label className="small" style={{margin: 0}}>{x.name}&rsquo;s face (empty: as in the crop)</label>
          <input value={wants[x.key] || ''} maxLength={400} onChange={e => setWants({...wants, [x.key]: e.target.value})} placeholder="e.g. total shock, eyes wide" />
          {p.faces[x.key] && <>
            <span className={`badge ${p.faces[x.key].prompt.source === 'gpt' ? 'good' : p.faces[x.key].prompt.source === 'owner' ? '' : 'warn'}`} style={{alignSelf: 'flex-start'}}>{p.faces[x.key].prompt.label}</span>
            <textarea aria-label={`Prompt for ${x.name}`} rows={4} value={prompts[x.key] || ''} maxLength={4000} onChange={e => setPrompts({...prompts, [x.key]: e.target.value})} /></>}
        </div>))}
      <div className="row">
        <button className="btn sm" disabled={!!act.busy} onClick={save}>Save</button>
        {!p.as_is && <button className="btn sm" disabled={!!act.busy} onClick={write}>{r.openai_key ? 'Write with GPT' : 'Use the template (no OpenAI key)'}</button>}
        {p.i > 0 && <button className="btn sm" disabled={!!act.busy} onClick={() => window.confirm(`Remove pose ${p.i}?`) && act.run(`d${p.id}`, () => api(base, {method: 'DELETE'}))}>Remove</button>}
        <button className="btn sm" disabled={!!act.busy} onClick={() => act.run(`n${p.id}`, () => api(`/episodes/${id}/reactions/${s.index}/poses`, {body: {after: p.i}}))}>Add a pose after</button>
      </div>
      {p.as_is && s.base_url && <img src={s.base_url} alt="The crop as it is" style={{width: '100%', borderRadius: 4}} />}
      {(p.takes || []).map((tk: any) => (
        <div key={tk.id} className="stack" style={{gap: 4}}>
          {tk.url && <img src={tk.url} alt={`Pose ${p.i} picture`} style={{width: '100%', borderRadius: 4, opacity: tk.valid ? 1 : 0.5}} />}
          <div className="row small">
            <span className="muted">{new Date(tk.at * 1000).toLocaleString('en-GB')} · {usd(tk.usd, 3)}{tk.reused?.length ? ' · face reused' : ''}{tk.valid ? '' : ' · old crop'}</span>
            {p.approved_take === tk.id
              ? <button className="btn sm" disabled={!!act.busy} onClick={() => act.run(`a${p.id}`, () => api(`${base}/approve`, {body: {take_id: null}}))}>Withdraw</button>
              : tk.valid && <button className="btn sm good" disabled={!!act.busy} onClick={() => act.run(`a${p.id}`, () => api(`${base}/approve`, {body: {take_id: tk.id}}))}>Approve</button>}
          </div>
        </div>))}
      {!p.as_is && <button className="btn sm primary" disabled={!!act.busy || r.busy || !r.availability?.ok || !s.crop_approved} onClick={redo}>
        {(p.takes || []).length ? 'Redo' : 'Make'} · up to {usd(p.estimate?.usd_max)}</button>}
      <ShotChat step="pose" item={poseItem(s.index, p.i)} episodeId={id} onApplied={() => act.run('x', async () => {})} />
    </figure>);
}

function MovePart({s, id, act, r}: {s: any; id: string; act: Act; r: any}) {
  const [texts, setTexts] = useState<Record<string, string>>(() => Object.fromEntries((s.moves || []).map((m: any) => [m.name, m.text])));
  useEffect(() => { setTexts(Object.fromEntries((s.moves || []).map((m: any) => [m.name, m.text]))); }, [JSON.stringify(s.moves)]);   // eslint-disable-line react-hooks/exhaustive-deps
  const changed = Object.fromEntries((s.moves || []).filter((m: any) => texts[m.name] !== m.text).map((m: any) => [moveKey(m.name), texts[m.name] || '']));
  const animate = () => {
    const e = s.estimate_animate;
    if (!window.confirm(`Animate shot ${s.index} on a rented GPU: ${e.label}. Then the shot is put together on the studio server (free). Start now?`)) return;
    act.run(`an${s.index}`, () => api(`/episodes/${id}/reactions/${s.index}/animate`, {body: {move_prompts: Object.keys(changed).length ? changed : null, confirm_usd: e.usd_max}}));
  };
  return (
    <div className="stack">
      <div className="stack" style={{gap: 2}}>
        <strong className="small">Timeline (25 frames a second)</strong>
        {(s.timeline || []).map((g: any, k: number) => <span key={k} className="small">{segmentText(g)}</span>)}
      </div>
      {(s.moves || []).map((m: any) => (
        <div key={m.name} className="stack" style={{gap: 2}}>
          <label className="small" style={{margin: 0}}>{m.kind === 'move' ? `Move into pose ${moveKey(m.name)}` : `Living hold of pose ${m.name.slice(5)}`}
            {' '}<span className="muted">({m.source === 'owner' ? 'your text' : 'template'})</span></label>
          <textarea rows={2} maxLength={1500} value={texts[m.name] || ''} onChange={e => setTexts({...texts, [m.name]: e.target.value})} />
        </div>))}
      <div className="row">
        <button className="btn sm" disabled={!!act.busy || !Object.keys(changed).length} onClick={() => act.run(`mv${s.index}`, () => api(`/episodes/${id}/reactions/${s.index}/moves`, {method: 'PUT', body: {move_prompts: changed}}))}>Save moves</button>
        <button className="btn primary sm" disabled={!!act.busy || r.busy || !r.availability?.ok || !!s.animate_blocked} onClick={animate}>
          {(s.clips || []).length ? 'Animate again' : 'Animate'} · up to {usd(s.estimate_animate?.usd_max)}</button>
        <span className="small muted">{s.animate_blocked || s.estimate_animate?.label}</span>
      </div>
      {(s.clips || []).length > 0 && <div className="row" style={{flexWrap: 'wrap', alignItems: 'flex-start', gap: 12}}>
        {s.clips.map((c: any) => (
          <figure key={c.id} style={{margin: 0, width: 340}} className="stack">
            <video controls src={c.preview_url || c.url} style={{width: '100%', borderRadius: 6, background: '#000'}} />
            <figcaption className="small muted">{new Date(c.at * 1000).toLocaleString('en-GB')} · {c.frames} frames at {c.fps} fps · {usd(c.usd, 3)}</figcaption>
            <div className="row">
              {s.approved === c.id
                ? <><span className="badge good">Approved</span><button className="btn sm" disabled={!!act.busy} onClick={() => act.run(`ap${c.id}`, () => api(`/episodes/${id}/reactions/${s.index}/approve`, {body: {clip_id: null}}))}>Withdraw</button></>
                : <button className="btn sm good" disabled={!!act.busy} onClick={() => act.run(`ap${c.id}`, () => api(`/episodes/${id}/reactions/${s.index}/approve`, {body: {clip_id: c.id}}))}>Approve</button>}
            </div>
          </figure>))}
      </div>}
      <ShotChat step="clip" item={s.index} episodeId={id} onApplied={() => act.run('x', async () => {})} />
    </div>);
}
