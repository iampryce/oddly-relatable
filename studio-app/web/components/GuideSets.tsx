'use client';
// Guided page, step 5 "Sets and seating masters" (API: room_sets.py). Four parts, top to bottom:
//   walls     one straight-on picture per wall (the image model cannot turn the camera, so each wall is described
//             as if you stand facing it), the establishing still used for style only; Make (paid), Approve.
//   seating   one picture per side of the room with its characters seated in order, the side's eyeline; Make
//             (paid), Approve, and "Use for close-ups" (step 6 then zooms into it).
//   repairs   on an approved picture: repaint the background behind the people (drag a box) or fix one face (click
//             the face), on the rented GPU (paid); before / after, Approve or Reject.
//   check     every approved still and seating picture: heads counted, "Ask Gemini" (paid or free tier), flags and
//             "Remake this picture" (paid).
// Each wall, seating picture and repair has its chat thread. Paid buttons send the price they showed (the API refuses
// anything else with 409). Nothing approves itself.
import Link from 'next/link';
import {useEffect, useRef, useState} from 'react';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import ShotChat from '@/components/ShotChat';
import {headNote} from '@/lib/cast';
import HeadClicker from '@/components/HeadClicker';
import {clickToPicture} from '@/lib/reactionsGuide';
import {isActive, progress, usd} from '@/lib/talkingGuide';
import {boxStyle, checkBadge, dragBox, eyelineText, makeLabel, ovalBox, pictureBadge, repairBadge, targetLabel, TOOL_TEXT,
  type Box} from '@/lib/setsGuide';

type Act = ReturnType<typeof useAction>;
const pic = {position: 'relative' as const, borderRadius: 6, overflow: 'hidden', border: '1px solid var(--line)'};
const thumb = {width: 220, display: 'block', borderRadius: 4};

export default function GuideSets({id, onChange}: {id: string; onChange: () => unknown}) {
  const [poll, setPoll] = useState(15000);
  const {data: v, error, reload} = useApi<any>(`/episodes/${id}/room-sets`, poll);
  const act = useAction(async () => { await reload(); await onChange(); });
  const [now, setNow] = useState(() => Date.now() / 1000);
  const [repairOn, setRepairOn] = useState<string>('');
  const running = !!v && (v.busy || (v.repairs || []).some((r: any) => isActive(r.run) || r.run?.status === 'running'));
  useEffect(() => { setPoll(running ? 4000 : 15000); if (v && !running) onChange(); }, [running]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!running) return;
    const h = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(h);
  }, [running]);
  if (!v) return error ? <ErrorBox error={error} /> : <p className="small muted">Loading…</p>;
  return (
    <div className="stack">
      <ErrorBox error={act.error} />
      <p className="small">The image model cannot turn the camera around a room: asked to &ldquo;show the other side&rdquo;, it
        draws the same view again. So each wall is drawn on its own, straight-on, as if you stand facing it, and we list what is on it.
        The establishing still is only used for the style, colours and materials.</p>
      {v.job?.status === 'failed' && <p className="small bad">The last run stopped: {v.job.error}</p>}
      <StylePicker v={v} id={id} act={act} />
      <h3 className="gd-sub">Walls</h3>
      {(v.walls || []).map((w: any) => <WallCard key={w.id} w={w} v={v} id={id} act={act} onRepair={() => setRepairOn(`wall:${w.id}`)} />)}
      <AddWall v={v} id={id} act={act} />
      <h3 className="gd-sub">Seating pictures (one per side of the room)</h3>
      {!v.sides_known && <p className="small muted">No sides of the room yet. They come from the storyboard: <Link href={`/episodes/${id}`}>make its shot frames</Link> first.</p>}
      {(v.seating || []).map((s: any) => <SeatingCard key={s.side} s={s} v={v} id={id} act={act} onRepair={() => setRepairOn(`seating:${s.side}`)} />)}
      <h3 className="gd-sub">Repairs</h3>
      <RepairTool v={v} id={id} act={act} target={repairOn} setTarget={setRepairOn} />
      {(v.repairs || []).map((r: any) => <RepairCard key={r.id} r={r} id={id} act={act} now={now} />)}
      <h3 className="gd-sub">Are all the characters there?</h3>
      <CharacterCheck v={v} id={id} act={act} onRepair={setRepairOn} />
    </div>);
}

function StylePicker({v, id, act}: {v: any; id: string; act: Act}) {
  const sr = v.style_ref;
  return (
    <div className="row small" style={{flexWrap: 'wrap'}}>
      <span>Style reference for the walls:</span>
      <select aria-label="Style reference" value={sr?.asset_id || ''} disabled={!!act.busy || !(v.style_options || []).length}
        onChange={e => act.run('style', () => api(`/episodes/${id}/room-sets/style-reference`, {method: 'PUT', body: {asset_id: e.target.value ? Number(e.target.value) : null}}))}>
        {!(v.style_options || []).length && <option value="">None yet (approve a wide still first): text only</option>}
        {(v.style_options || []).map((o: any) => <option key={o.asset_id} value={o.asset_id}>{o.label}</option>)}
      </select>
      {sr?.source === 'suggested' && <span className="muted">(suggested: the first approved wide shot)</span>}
      {sr?.url && <img src={sr.url} alt="Style reference" style={{width: 96, borderRadius: 4}} />}
    </div>);
}

function AddWall({v, id, act}: {v: any; id: string; act: Act}) {
  const [name, setName] = useState('');
  const [side, setSide] = useState('');
  const [contents, setContents] = useState('');
  const add = () => act.run('addwall', async () => {
    await api(`/episodes/${id}/room-sets/walls`, {body: {name, side, contents}});
    setName(''); setContents('');
  });
  return (
    <div className="card stack" style={{padding: 10, gap: 6}}>
      <strong className="small">Add a wall</strong>
      <div className="grid cols-3">
        <div><label htmlFor="wall-name">Name</label>
          <input id="wall-name" value={name} maxLength={80} placeholder="e.g. family side wall" onChange={e => setName(e.target.value)} /></div>
        <div><label htmlFor="wall-side">Behind which side?</label>
          <select id="wall-side" value={side} onChange={e => setSide(e.target.value)}>
            <option value="">None (a wall nobody sits in front of)</option>
            {(v.seating || []).map((s: any) => <option key={s.side} value={s.side}>{s.label}</option>)}</select></div>
        <div><label htmlFor="wall-what">What is on it</label>
          <input id="wall-what" value={contents} maxLength={1500} placeholder="e.g. a stone fireplace, a portrait, bookcases"
            onChange={e => setContents(e.target.value)} /></div>
      </div>
      <div><button className="btn sm" disabled={!!act.busy || !name.trim()} onClick={add}>Add the wall (free)</button></div>
    </div>);
}

function PromptBox({p, onSave, onWrite, act, busyKey, writeLabel}: {p: any; onSave: (t: string) => void; onWrite: () => void;
  act: Act; busyKey: string; writeLabel: string}) {
  const [text, setText] = useState(p?.text || '');
  useEffect(() => { setText(p?.text || ''); }, [p?.text]);
  return (
    <div className="stack" style={{gap: 4}}>
      <div className="small muted">Prompt · {p?.label}</div>
      <textarea aria-label="Prompt" rows={5} maxLength={4000} value={text} onChange={e => setText(e.target.value)} />
      <div className="row">
        <button className="btn sm" disabled={!!act.busy || text === p?.text} onClick={() => onSave(text)}>Save prompt</button>
        {p?.source !== 'template' && <button className="btn sm" disabled={!!act.busy} onClick={() => onSave('')}>Back to the template</button>}
        <button className="btn sm" disabled={!!act.busy} onClick={onWrite}>{act.busy === busyKey ? 'Writing…' : writeLabel}</button>
      </div>
    </div>);
}

function writeWithGpt(v: any, act: Act, key: string, path: string) {
  const est = v.prompt_estimate;
  if (v.openai_key) {
    if (!window.confirm(`Write this prompt with ${est.model}: about $${est.usd_typical.toFixed(4)}, at most $${est.usd_max.toFixed(4)}. Send now? (paid, not retried by itself)`)) return;
    act.run(key, () => api(path, {body: {confirm_usd: est.usd_max}}));
  } else {
    act.run(key, () => api(path, {body: {}}));
  }
}

function Takes({rec, approve, act, label}: {rec: any; approve: (id: string | null) => void; act: Act; label: string}) {
  if (!(rec.takes || []).length) return null;
  return (
    <div className="row" style={{flexWrap: 'wrap', gap: 10, alignItems: 'flex-start'}}>
      {rec.takes.map((t: any, i: number) => (
        <figure key={t.id} className="stack" style={{gap: 4, margin: 0}}>
          {t.url && <a href={t.url} target="_blank" rel="noreferrer"><img src={t.url} alt={`${label}, picture ${i + 1}`} style={{...thumb,
            outline: rec.approved === t.id ? '3px solid var(--good)' : 'none'}} /></a>}
          <figcaption className="row small">
            {t.source === 'repair' ? 'Repaired' : `Picture ${i + 1}`}{t.usd ? ` · ${usd(t.usd)}` : ''}
            {rec.approved === t.id
              ? <button className="btn sm" disabled={!!act.busy} onClick={() => approve(null)}>Withdraw</button>
              : <button className="btn sm good" disabled={!!act.busy} onClick={() => approve(t.id)}>Approve</button>}
          </figcaption>
        </figure>))}
    </div>);
}

function WallCard({w, v, id, act, onRepair}: {w: any; v: any; id: string; act: Act; onRepair: () => void}) {
  const b = pictureBadge(w);
  const base = `/episodes/${id}/room-sets/walls/${w.id}`;
  const make = () => {
    const c = v.image_cost;
    if (!c || !window.confirm(`Draw the wall "${w.name}" straight-on (${c.provider}): ${c.label}. Start now? (paid, not retried by itself)`)) return;
    act.run(`mk${w.id}`, () => api(`${base}/make`, {body: {confirm_usd: c.usd}}));
  };
  return (
    <div className="card stack" style={{padding: 12}}>
      <div className="spread">
        <strong>{w.name} <span className="small muted">{w.side ? `behind ${(v.seating || []).find((s: any) => s.side === w.side)?.label || w.side}` : ''}</span></strong>
        <span className="row"><span className={`badge ${b.tone}`}>{b.text}</span>
          <button className="btn sm danger" disabled={!!act.busy || w.busy} onClick={() => window.confirm(`Remove the wall "${w.name}"? Its pictures stay in the episode's files.`)
            && act.run(`rm${w.id}`, () => api(base, {method: 'DELETE'}))}>Remove</button></span>
      </div>
      <WallFields w={w} v={v} base={base} act={act} />
      <PromptBox p={w.prompt} act={act} busyKey={`wp${w.id}`} writeLabel={v.openai_key ? `Write with GPT · up to $${v.prompt_estimate.usd_max.toFixed(4)}` : 'Use the template (no OpenAI key)'}
        onSave={t => act.run(`ps${w.id}`, () => api(base, {method: 'PUT', body: {prompt: t}}))}
        onWrite={() => writeWithGpt(v, act, `wp${w.id}`, `${base}/write-prompt`)} />
      <div className="row">
        <button className="btn sm primary" disabled={!!act.busy || w.busy || !v.image_cost} onClick={make}>
          {w.busy ? 'Being drawn…' : makeLabel(v.image_cost, (w.takes || []).length > 0)}</button>
        {w.approved && <button className="btn sm" onClick={onRepair}>Repair this picture</button>}
      </div>
      {w.run?.status === 'failed' && <p className="small bad">The last picture failed: {w.run.error}</p>}
      <Takes rec={w} label={w.name} act={act} approve={tid => act.run(`ap${w.id}`, () => api(`${base}/approve`, {body: {take_id: tid}}))} />
      <ShotChat step="wall" item={w.id} episodeId={id} onApplied={() => act.run(`c${w.id}`, async () => {})} />
    </div>);
}

function WallFields({w, v, base, act}: {w: any; v: any; base: string; act: Act}) {
  const [contents, setContents] = useState(w.contents);
  useEffect(() => { setContents(w.contents); }, [w.contents]);
  return (
    <div className="grid cols-3">
      <div><label htmlFor={`ws-${w.id}`}>Behind which side?</label>
        <select id={`ws-${w.id}`} value={w.side} disabled={!!act.busy}
          onChange={e => act.run(`sd${w.id}`, () => api(base, {method: 'PUT', body: {side: e.target.value}}))}>
          <option value="">None</option>
          {(v.seating || []).map((s: any) => <option key={s.side} value={s.side}>{s.label}</option>)}</select></div>
      <div style={{gridColumn: 'span 2'}}><label htmlFor={`wc-${w.id}`}>What is on it</label>
        <div className="row"><input id={`wc-${w.id}`} value={contents} maxLength={1500} onChange={e => setContents(e.target.value)} />
          <button className="btn sm" disabled={!!act.busy || contents === w.contents}
            onClick={() => act.run(`wc${w.id}`, () => api(base, {method: 'PUT', body: {contents}}))}>Save</button></div></div>
    </div>);
}

function SeatingCard({s, v, id, act, onRepair}: {s: any; v: any; id: string; act: Act; onRepair: () => void}) {
  const b = pictureBadge(s);
  const base = `/episodes/${id}/room-sets/seating/${encodeURIComponent(s.side)}`;
  const make = () => {
    const c = v.image_cost;
    if (!c || !window.confirm(`Seat ${s.people.map((p: any) => p.name).join(', ')} in "${s.label}" (${c.provider}): ${c.label}. Start now? (paid, not retried by itself)`)) return;
    act.run(`ms${s.side}`, () => api(`${base}/make`, {body: {confirm_usd: c.usd}}));
  };
  return (
    <div className="card stack" style={{padding: 12}}>
      <div className="spread">
        <strong>{s.label} <span className="small muted">seat order, left to right: {s.people.map((p: any) => p.name).join(' · ')}</span></strong>
        <span className={`badge ${b.tone}`}>{b.text}</span>
      </div>
      <div className="row small" style={{flexWrap: 'wrap'}}>Eyes look:
        <select aria-label={`Eyeline for ${s.label}`} value={s.eyeline.owner || ''} disabled={!!act.busy}
          onChange={e => act.run(`el${s.side}`, () => api(`${base}/eyeline`, {method: 'PUT', body: {eyeline: e.target.value || null}}))}>
          <option value="">The usual rule ({s.eyeline.default === 'right' ? 'screen-right' : 'screen-left'})</option>
          <option value="left">Slightly screen-left</option>
          <option value="right">Slightly screen-right</option></select>
        <span className="muted">{eyelineText(s.eyeline)}. Used here, in the close-ups and in the talking shots.</span></div>
      {s.wall ? <div className="row small"><img src={s.wall.url} alt="Approved wall" style={{width: 120, borderRadius: 4}} />
        <span className="muted">Image 1: the approved wall behind this side. Then each character&apos;s approved master, in seat order.</span></div>
        : <p className="small muted">No approved wall behind this side yet: its set picture is used as image 1. Add a wall above and approve it for a better match.</p>}
      {s.missing_masters.length > 0 && <p className="small bad">Approve a master for {s.missing_masters.join(', ')} first (step 4).</p>}
      {s.prompt && <PromptBox p={s.prompt} act={act} busyKey={`sp${s.side}`} writeLabel={v.openai_key ? `Write with GPT · up to $${v.prompt_estimate.usd_max.toFixed(4)}` : 'Use the template (no OpenAI key)'}
        onSave={t => act.run(`ss${s.side}`, () => api(base, {method: 'PUT', body: {prompt: t}}))}
        onWrite={() => writeWithGpt(v, act, `sp${s.side}`, `${base}/write-prompt`)} />}
      <div className="row">
        <button className="btn sm primary" disabled={!!act.busy || s.busy || !v.image_cost || s.missing_masters.length > 0} onClick={make}>
          {s.busy ? 'Being drawn…' : makeLabel(v.image_cost, (s.takes || []).length > 0)}</button>
        {s.approved && <button className="btn sm" onClick={onRepair}>Repair this picture</button>}
        {s.approved && (s.used_for_closeups ? <span className="badge good">Used for the close-ups</span>
          : <button className="btn sm good" disabled={!!act.busy} onClick={() => act.run(`uc${s.side}`, () => api(`${base}/use-for-closeups`, {method: 'POST'}))}>Use for the close-ups (step 6)</button>)}
      </div>
      {s.run?.status === 'failed' && <p className="small bad">The last picture failed: {s.run.error}</p>}
      <Takes rec={s} label={s.label} act={act} approve={tid => act.run(`as${s.side}`, () => api(`${base}/approve`, {body: {take_id: tid}}))} />
      <ShotChat step="seating" item={s.side} episodeId={id} onApplied={() => act.run(`c${s.side}`, async () => {})} />
    </div>);
}

function targets(v: any): {t: string; url: string | null; people: any[]}[] {
  const out: {t: string; url: string | null; people: any[]}[] = [];
  for (const w of v.walls || []) {
    const t = (w.takes || []).find((x: any) => x.id === w.approved);
    if (t) out.push({t: `wall:${w.id}`, url: t.url, people: []});
  }
  for (const s of v.seating || []) {
    const t = (s.takes || []).find((x: any) => x.id === s.approved);
    if (t) out.push({t: `seating:${s.side}`, url: t.url, people: s.people});
  }
  for (const c of v.checks || []) if (c.target.startsWith('still:')) out.push({t: c.target, url: c.url, people: c.people || []});
  return out;
}

function RepairTool({v, id, act, target, setTarget}: {v: any; id: string; act: Act; target: string; setTarget: (t: string) => void}) {
  const opts = targets(v);
  const cur = opts.find(o => o.t === target);
  const check = (v.checks || []).find((c: any) => c.target === target);
  const [tool, setTool] = useState<'background' | 'face'>('background');
  const [want, setWant] = useState('');
  const [box, setBox] = useState<Box | null>(null);
  const [oval, setOval] = useState<any>(null);
  const [who, setWho] = useState('');
  const [size, setSize] = useState<[number, number] | null>(null);
  const start = useRef<{x: number; y: number} | null>(null);
  useEffect(() => { setBox(null); setOval(null); setWho(''); setSize(check?.size || null); }, [target]);   // eslint-disable-line react-hooks/exhaustive-deps
  const est = v.repair_estimates?.[tool];
  const av = v.availability || {};
  const pt = (e: React.MouseEvent<HTMLDivElement>) => {
    const b = e.currentTarget.getBoundingClientRect();
    return clickToPicture(e.clientX - b.left, e.clientY - b.top, b.width, b.height, size?.[0] || 1, size?.[1] || 1);
  };
  const people = cur?.people || [];
  const run = () => {
    if (!est || !window.confirm(`${TOOL_TEXT[tool]} on ${targetLabel(target, v)}: ${est.label}. Start the rented GPU now? (paid, not retried by itself)`)) return;
    const body: any = {target, tool, want, confirm_usd: est.usd_max};
    if (tool === 'background' && box) body.box = box;
    if (tool === 'face') { if (oval) body.oval = oval; if (who) body.character = who; }
    act.run('repair', () => api(`/episodes/${id}/room-sets/repairs`, {body}));
  };
  if (!opts.length) return <p className="small muted">Approve a wall, a seating picture or a still first: repairs work on approved pictures.</p>;
  return (
    <div className="card stack" style={{padding: 12}}>
      <div className="row small" style={{flexWrap: 'wrap'}}>
        <label htmlFor="rp-target" style={{margin: 0}}>Picture</label>
        <select id="rp-target" value={target} onChange={e => setTarget(e.target.value)}>
          <option value="">Choose…</option>
          {opts.map(o => <option key={o.t} value={o.t}>{targetLabel(o.t, v)}</option>)}</select>
        <label htmlFor="rp-tool" style={{margin: 0}}>Tool</label>
        <select id="rp-tool" value={tool} onChange={e => setTool(e.target.value as any)}>
          <option value="background">{TOOL_TEXT.background}</option>
          <option value="face">{TOOL_TEXT.face}</option></select>
      </div>
      {!av.ok && av.reason && <p className="small bad">{av.reason} <Link href="/settings#gpu-worker">Open Settings</Link></p>}
      {cur && <>
        <p className="small muted">{tool === 'background'
          ? 'Drag a box over the background to change (for example the wall above the chair backs). The people are cut out first and pasted back exactly as they are; a second pass cleans the thin outline around them. No box: the area above the heads.'
          : 'Click the face to fix. Only the eyes, brows, mouth and moustache change inside the oval; everything else keeps its exact pixels.'}</p>
        <div role="button" tabIndex={0} aria-label={tool === 'background' ? 'Drag to draw the box' : 'Click the face'}
          style={{...pic, cursor: 'crosshair', maxWidth: 720, aspectRatio: size ? `${size[0]} / ${size[1]}` : undefined}}
          onMouseDown={e => { if (tool === 'background' && size) start.current = pt(e); }}
          onMouseUp={e => {
            if (!size) return;
            const p = pt(e);
            if (tool === 'background' && start.current) { setBox(dragBox(start.current, p, size[0], size[1])); start.current = null; }
            if (tool === 'face') { const r = size[0] * 0.045; setOval({cx: p.x, cy: p.y, rx: r, ry: r * 1.05}); }
          }}>
          {cur.url && <img src={cur.url} alt="Picture to repair" draggable={false} style={{width: '100%', display: 'block'}}
            onLoad={e => { const im = e.currentTarget; if (!size) setSize([im.naturalWidth, im.naturalHeight]); }} />}
          {size && tool === 'background' && box && <span style={{position: 'absolute', ...boxStyle(box, size[0], size[1]), border: '2px dashed #e5484d', background: 'rgba(229,72,77,0.15)'}} />}
          {size && tool === 'face' && oval && <span style={{position: 'absolute', ...boxStyle(ovalBox(oval), size[0], size[1]), border: '2px solid #e5484d', borderRadius: '50%'}} />}
        </div>
        {tool === 'face' && people.length > 1 && <div className="row small">Whose face?
          <select aria-label="Whose face" value={who} onChange={e => setWho(e.target.value)}>
            <option value="">Choose…</option>
            {people.map((p: any) => <option key={p.key} value={p.key}>{p.name}</option>)}</select></div>}
        <div><label htmlFor="rp-want">{tool === 'background' ? 'What should be there instead' : 'What the face should show'}</label>
          <textarea id="rp-want" rows={2} maxLength={2000} value={want} onChange={e => setWant(e.target.value)}
            placeholder={tool === 'background' ? 'e.g. replace the window with the fireplace wall and the bearded portrait' : 'e.g. a small worried frown, eyes slightly screen-left'} /></div>
        <div className="row">
          <button className="btn sm primary" disabled={!!act.busy || !av.ok || want.trim().length < 3 || !est || (tool === 'face' && people.length > 1 && !who)} onClick={run}>
            {act.busy === 'repair' ? 'Starting…' : `${TOOL_TEXT[tool]} · up to ${usd(est?.usd_max)}`}</button>
          {est && <span className="small muted">{est.label}</span>}
        </div></>}
    </div>);
}

function RepairCard({r, id, act, now}: {r: any; id: string; act: Act; now: number}) {
  const b = repairBadge(r);
  const prog = progress(r.run?.status === 'running' ? {...r.run, status: 'rendering'} : r.run, now);
  const decide = (approved: boolean) => act.run(`rd${r.id}`, () => api(`/episodes/${id}/room-sets/repairs/${r.id}/approve`, {body: {approved}}));
  return (
    <div className="card stack" style={{padding: 12}}>
      <div className="spread"><strong>{TOOL_TEXT[r.tool]} · {r.label} <span className="small muted">“{r.want}”</span></strong>
        <span className={`badge ${b.tone}`}>{b.text}</span></div>
      {prog.label && <span className={`small ${r.run?.status === 'failed' ? 'bad' : ''}`} aria-live="polite">{prog.label}</span>}
      <div style={{display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 10}}>
        <figure style={{margin: 0}}>{r.before_url && <img src={r.before_url} alt="Before" style={{width: '100%', borderRadius: 4}} />}
          <figcaption className="small muted">Before</figcaption></figure>
        <figure style={{margin: 0}}>{r.after_url ? <img src={r.after_url} alt="After" style={{width: '100%', borderRadius: 4}} />
          : <div className="small muted">Not ready yet</div>}<figcaption className="small muted">After{r.usd ? ` · ${usd(r.usd)}` : ''}</figcaption></figure>
      </div>
      {r.mask_url && <details className="small"><summary>Show the area that was repainted</summary><img src={r.mask_url} alt="Repainted area" style={{width: 240, borderRadius: 4}} /></details>}
      {r.status === 'done' && r.approved == null && <div className="row">
        <button className="btn sm good" disabled={!!act.busy} onClick={() => decide(true)}>Approve: use the repaired picture</button>
        <button className="btn sm" disabled={!!act.busy} onClick={() => decide(false)}>Reject</button></div>}
      <ShotChat step="repair" item={r.id} episodeId={id} onApplied={() => act.run(`c${r.id}`, async () => {})} />
    </div>);
}

function CharacterCheck({v, id, act, onRepair}: {v: any; id: string; act: Act; onRepair: (t: string) => void}) {
  const [free, setFree] = useState(false);
  const g = v.gemini || {};
  const ask = (c: any) => {
    const est = g.estimate;
    if (!window.confirm(`Ask ${g.model} which characters are visible in ${c.label}: about $${est.usd_typical.toFixed(4)}, at most $${est.usd_max.toFixed(4)}${free ? ' (the free tier may be used)' : ''}. Send now? (paid, not retried by itself)`)) return;
    act.run(`g${c.target}`, () => api(`/episodes/${id}/room-sets/checks/gemini`, {body: {target: c.target, use_free_tier: free, confirm_usd: est.usd_max}}));
  };
  const remake = (c: any) => {
    const cost = v.image_cost;
    if (!cost || !window.confirm(`Remake ${c.label} with every character spelled out (${c.names.join(', ')}): ${cost.label}. Start now? (paid, not retried by itself)`)) return;
    act.run(`rm${c.target}`, () => api(`/episodes/${id}/room-sets/checks/remake`, {body: {target: c.target, confirm_usd: cost.usd}}));
  };
  const checks = v.checks || [];
  if (!checks.length) return <p className="small muted">Nothing to check yet: approved stills and seating pictures are checked here.</p>;
  return (
    <div className="stack">
      <p className="small muted">Every approved still and seating picture should show every character listed for it. Heads are counted for free; Gemini can also look (in Episode 15 one character was merged into another in every wide shot).</p>
      {headNote(v.head_finding) && <p className="small warn" role="note">{headNote(v.head_finding)} Until then, heads are not counted here; Gemini can still look.</p>}
      {!g.key_set && <p className="small muted">Add the Gemini key in <Link href="/settings">Settings › Credentials</Link> to ask Gemini.</p>}
      <label className="row small" style={{fontWeight: 400, color: 'inherit'}}>
        <input type="checkbox" style={{width: 'auto'}} checked={free} onChange={e => setFree(e.target.checked)} />
        Use the free tier if the paid model is busy ({(g.free_models || []).join(', ')}). The free tier may let Google use the picture to train its models.</label>
      {checks.map((c: any) => {
        const b = checkBadge(c);
        return (
          <div key={c.target} className="card row" style={{padding: 10, alignItems: 'flex-start', gap: 12, flexWrap: 'wrap'}}>
            {c.url && <img src={c.url} alt={c.label} style={{width: 200, borderRadius: 4}} />}
            <div className="stack" style={{gap: 4, flex: 1, minWidth: 220}}>
              <div className="spread"><strong>{c.label}</strong><span className={`badge ${b.tone}`}>{b.text}</span></div>
              <div className="small">Should show: {c.names.join(', ')}</div>
              {c.gemini && <div className="small muted">Gemini ({c.gemini.model}{c.gemini.free_tier ? ', free tier' : ''}): sees {c.gemini.visible.join(', ') || 'nobody listed'}{c.gemini.notes ? `. ${c.gemini.notes}` : ''}</div>}
              {(c.flags || []).map((f: string, i: number) => <div key={i} className="small bad" role="alert">⚠ {f}</div>)}
              {headNote(v.head_finding) && c.asset_id && <HeadClicker episodeId={id} assetId={c.asset_id} url={c.url} onSaved={() => act.run(`h${c.target}`, async () => {})} />}
              <div className="row">
                <button className="btn sm" disabled={!!act.busy || !g.key_set} onClick={() => ask(c)}>Ask Gemini · up to ${g.estimate?.usd_max?.toFixed(4)}</button>
                {(c.flags || []).length > 0 && <button className="btn sm primary" disabled={!!act.busy || !v.image_cost} onClick={() => remake(c)}>
                  Remake this picture · ${v.image_cost?.usd?.toFixed(2)}</button>}
                {(c.flags || []).length > 0 && c.target.startsWith('seating:') && <button className="btn sm" onClick={() => onRepair(c.target)}>Repair instead</button>}
              </div>
            </div>
          </div>);
      })}
    </div>);
}
