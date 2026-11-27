'use client';
// Guided step 4 "Cast": the characters described from the reference video (words only: the video's pictures never go
// to an image model), the episode's style (five presets, with an optional side-by-side preview of one character in
// each), master candidates per character and the owner's approval (saved to the cast library or this episode only).
// Every paid button shows its price and the request carries it (the API refuses any other with 409). Nothing is
// chosen or approved for the owner.
import Link from 'next/link';
import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import ShotChat from '@/components/ShotChat';
import {approveBody, clothingToText, descriptionSummary, headNote, imageCost, keepText, linesToList, money,
  orderedStyles, STYLE_ORDER, textToClothing} from '@/lib/cast';

type Act = ReturnType<typeof useAction>;

export default function GuideCast({id, onChange}: {id: string; onChange: () => unknown}) {
  const [poll, setPoll] = useState(15000);
  const {data: v, error, reload} = useApi<any>(`/episodes/${id}/cast-video`, poll);
  const act = useAction(async () => { await reload(); await onChange(); });
  const running = !!v && (v.describe?.busy || (v.characters || []).some((c: any) => c.busy));
  useEffect(() => { setPoll(running ? 4000 : 15000); if (v && !running) onChange(); }, [running]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!v) return error ? <ErrorBox error={error} /> : <p className="small muted">Loading…</p>;
  const note = headNote(v.head_finding);
  return (
    <div className="stack">
      <ErrorBox error={act.error} />
      <Describe v={v} id={id} act={act} />
      {(v.descriptions || []).length > 0 && <Descriptions v={v} id={id} act={act} />}
      <Styles v={v} id={id} act={act} />
      {v.style && <div className="stack">
        <h3 style={{margin: '8px 0 0'}}>Masters in &ldquo;{v.styles.find((s: any) => s.id === v.style)?.label}&rdquo;</h3>
        {(v.characters || []).map((c: any) => <CharacterCard key={c.id} c={c} v={v} id={id} act={act} />)}
      </div>}
      {note && <p className="small warn" role="note">{note}</p>}
      <p className="small muted">Saved characters are listed on the <Link href="/characters">Characters page</Link>.</p>
    </div>);
}

function Describe({v, id, act}: {v: any; id: string; act: Act}) {
  const d = v.describe || {};
  const est = d.estimate;
  const [free, setFree] = useState(false);
  const go = () => {
    if (!est || !window.confirm(`Describe the characters from the video: ${est.label}. Gemini watches the video and writes words only; no picture of it goes to an image model. Start now? (paid, not retried by itself)`)) return;
    act.run('describe', () => api(`/episodes/${id}/cast-video/describe`, {body: {confirm_usd: est.usd_max, use_free_tier: free}}));
  };
  return (
    <div className="card stack" style={{padding: 12}}>
      <strong>1. Characters from the video</strong>
      <p className="small muted" style={{margin: 0}}>Gemini watches the reference video and writes, for each person: role, age,
        build, hair, clothing, one accessory that tells them apart, personality and what they must never have. Only words come
        back; the real people&rsquo;s faces are never described or copied.</p>
      {!d.key_set && <p className="small bad">Add the Gemini key in <Link href="/settings">Settings › Credentials</Link> first.</p>}
      {!d.reference_video && <p className="small muted">Upload the reference video in step 1 first.</p>}
      <label className="row small" style={{fontWeight: 400, color: 'inherit'}}>
        <input type="checkbox" style={{width: 'auto'}} checked={free} onChange={e => setFree(e.target.checked)} />
        Use the free tier if the paid model is busy ({(d.free_models || []).join(', ')}). The free tier may let Google use the video to train its models.</label>
      <div className="row">
        <button className="btn primary" disabled={!!act.busy || d.busy || !est || !d.key_set} onClick={go}>
          {d.busy ? 'Describing…' : (v.descriptions || []).length ? 'Describe again' : 'Describe the characters'}{est ? ` · up to ${money(est.usd_max)}` : ''}</button>
        {d.made && <span className="small muted">Last run: {d.model_used} · {money(d.usd)}</span>}
      </div>
      {d.job?.status === 'failed' && <p className="small bad">The last run failed: {d.job.error}</p>}
    </div>);
}

function Descriptions({v, id, act}: {v: any; id: string; act: Act}) {
  const chars: any[] = v.characters || [];
  return (
    <div className="card stack" style={{padding: 12}}>
      <strong>2. Check the descriptions</strong>
      <p className="small muted" style={{margin: 0}}>Change any word. Link each description to a character of the script, add a new
        one for this episode, or use a character you saved before (free).</p>
      {v.descriptions.map((d: any) => <DescriptionCard key={d.id} d={d} chars={chars} v={v} id={id} act={act} />)}
    </div>);
}

function DescriptionCard({d, chars, v, id, act}: {d: any; chars: any[]; v: any; id: string; act: Act}) {
  const [open, setOpen] = useState(false);
  const [f, setF] = useState<any>(null);
  useEffect(() => { setF(null); }, [d.edited_at]);
  const start = () => {
    setF({name: d.name, role: d.role, age: d.age, build: d.build, hair_style: d.hair?.style || '', hair_colour: d.hair?.colour || '',
      clothing: clothingToText(d.clothing), accessory: d.accessory, personality: d.personality, must_never: (d.must_never || []).join('\n')});
    setOpen(true);
  };
  const save = () => act.run(`d${d.id}`, () => api(`/episodes/${id}/cast-video/descriptions/${d.id}`, {method: 'PUT', body: {
    name: f.name, role: f.role, age: f.age, build: f.build, hair: {style: f.hair_style, colour: f.hair_colour},
    clothing: textToClothing(f.clothing), accessory: f.accessory, personality: f.personality, must_never: linesToList(f.must_never)}}))
    .then(ok => ok && setOpen(false));
  const link = (cid: string) => act.run(`l${d.id}`, () => api(`/episodes/${id}/cast-video/descriptions/${d.id}`, {method: 'PUT', body: {character_id: Number(cid)}}));
  const useSaved = (lid: string) => lid && act.run(`u${d.id}`, async () => {
    try { await api(`/episodes/${id}/cast-video/library/${lid}/use`, {body: {description_id: d.id}}); }
    catch (e: any) {
      if (e.status !== 409 || !window.confirm(`${e.message}. Use it anyway?`)) throw e;
      await api(`/episodes/${id}/cast-video/library/${lid}/use`, {body: {description_id: d.id, allow_mixed: true}});
    }
  });
  const field = (k: string, label: string, rows = 1) => (
    <div><label htmlFor={`${d.id}-${k}`}>{label}</label>
      {rows > 1 ? <textarea id={`${d.id}-${k}`} rows={rows} value={f[k]} onChange={e => setF({...f, [k]: e.target.value})} />
        : <input id={`${d.id}-${k}`} value={f[k]} onChange={e => setF({...f, [k]: e.target.value})} />}</div>);
  return (
    <div className="gd-prompt">
      <div className="spread small">
        <span><strong>{d.name}</strong> <span className="muted">{descriptionSummary(d)}</span>
          {d.personality_from && <span className="muted"> · personality from the acting analysis</span>}</span>
        <span className="row">
          <select aria-label={`Character for ${d.name}`} value={d.character_id || 0} disabled={!!act.busy} onChange={e => link(e.target.value)}>
            <option value={0}>Not linked</option>
            {chars.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
          {!d.character_id && <button className="btn sm" disabled={!!act.busy}
            onClick={() => act.run(`n${d.id}`, () => api(`/episodes/${id}/cast-video/descriptions/${d.id}/character`, {method: 'POST'}))}>Add as a new character</button>}
          {(v.library || []).length > 0 && <select aria-label={`Use a saved character for ${d.name}`} value="" disabled={!!act.busy}
            onChange={e => useSaved(e.target.value)}>
            <option value="">Use a saved character…</option>
            {v.library.map((l: any) => <option key={l.id} value={l.id}>{l.name} ({l.style_label})</option>)}</select>}
          <button className="btn sm" onClick={() => (open ? setOpen(false) : start())}>{open ? 'Close' : 'Edit'}</button></span>
      </div>
      {open && f && <div className="stack">
        <div className="grid cols-3">{field('name', 'Name')}{field('role', 'Role')}{field('age', 'Approximate age')}
          {field('build', 'Build')}{field('hair_style', 'Hair style')}{field('hair_colour', 'Hair colour')}</div>
        <div className="grid cols-3">{field('clothing', 'Clothing (one per line: garment - colour)', 3)}
          {field('accessory', 'ONE signature accessory')}{field('must_never', 'Must never (one per line)', 3)}</div>
        {field('personality', 'Personality')}
        <div className="row"><button className="btn sm primary" disabled={!!act.busy || !f.name.trim()} onClick={save}>Save (free)</button>
          <span className="small muted">An approved master never changes; new words only change new candidates.</span></div>
      </div>}
    </div>);
}

function Styles({v, id, act}: {v: any; id: string; act: Act}) {
  const linked = (v.characters || []).filter((c: any) => c.description_id || c.look);
  const [who, setWho] = useState<string>('');
  const [ticked, setTicked] = useState<Set<string>>(new Set(STYLE_ORDER));
  const cid = who || String(v.preview_character || linked[0]?.id || '');
  const sids = orderedStyles(ticked);
  const cost = imageCost(sids.length, v.usd_per_image || 0);
  const preview = () => {
    const name = linked.find((c: any) => String(c.id) === cid)?.name || 'the character';
    if (!sids.length || !window.confirm(`Preview ${name} in ${sids.length} style(s): ${cost.label}. Previews are not masters and do not choose the style. Start now? (paid, not retried by itself)`)) return;
    act.run('preview', () => api(`/episodes/${id}/cast-video/previews`, {body: {character_id: Number(cid), styles: sids, confirm_usd: cost.usd}}));
  };
  const choose = (sid: string) => act.run(`s${sid}`, async () => {
    try { await api(`/episodes/${id}/cast-video/style`, {method: 'PUT', body: {style: sid}}); }
    catch (e: any) {
      if (e.status !== 409 || !window.confirm(`${e.message}. Use a mixed cast anyway?`)) throw e;
      await api(`/episodes/${id}/cast-video/style`, {method: 'PUT', body: {style: sid, allow_mixed: true}});
    }
  });
  const items = v.previews?.items || {};
  return (
    <div className="card stack" style={{padding: 12}}>
      <strong>3. Choose the episode&rsquo;s style</strong>
      <p className="small muted" style={{margin: 0}}>Every character of this episode is drawn in the one style you choose, so they
        match. To see before you choose, preview one character in each style side by side ({money(v.usd_per_image)} per style).</p>
      <div className="row small" style={{flexWrap: 'wrap'}}>
        <label htmlFor="cast-preview-who" style={{margin: 0}}>Preview</label>
        <select id="cast-preview-who" value={cid} onChange={e => setWho(e.target.value)}>
          {linked.map((c: any) => <option key={c.id} value={c.id}>{c.name}{c.id === v.preview_character ? ' (main speaker)' : ''}</option>)}</select>
        {v.styles.map((s: any) => <label key={s.id} className="row" style={{fontWeight: 400, color: 'inherit', margin: 0}}>
          <input type="checkbox" style={{width: 'auto'}} checked={ticked.has(s.id)}
            onChange={e => { const n = new Set(ticked); e.target.checked ? n.add(s.id) : n.delete(s.id); setTicked(n); }} />{s.label}</label>)}
        <button className="btn sm primary" disabled={!!act.busy || !cid || !sids.length || !v.keys?.wavespeed} onClick={preview}>
          Make previews · {cost.label}</button>
      </div>
      {!v.keys?.wavespeed && <p className="small bad">Add the WaveSpeed key in <Link href="/settings">Settings › Credentials</Link> to draw pictures.</p>}
      <div className="row" style={{flexWrap: 'wrap', gap: 10, alignItems: 'stretch'}}>
        {v.styles.map((s: any) => {
          const p = items[s.id];
          const chosen = v.style === s.id;
          return (
            <div key={s.id} className="card stack" style={{padding: 8, width: 180, gap: 6, outline: chosen ? '3px solid var(--good)' : 'none'}}>
              <strong className="small">{s.label}</strong>
              {p ? <img src={p.url} alt={`Preview in ${s.label}`} style={{width: '100%', borderRadius: 4}} />
                : s.examples[0] ? <img src={s.examples[0]} alt={`${s.label} style example`} style={{width: '100%', borderRadius: 4, opacity: 0.85}} />
                : <div className="small muted" style={{minHeight: 80}}>{s.note}</div>}
              <span className="small muted">{p ? 'Preview' : s.examples[0] ? 'Style example' : 'No picture yet'}</span>
              <button className={`btn sm ${chosen ? 'good' : ''}`} disabled={!!act.busy || chosen} onClick={() => choose(s.id)}>
                {chosen ? 'Chosen' : 'Choose this style'}</button>
            </div>);
        })}
      </div>
      {!v.style && <p className="small muted">No style chosen yet. Nothing is chosen for you.</p>}
    </div>);
}

function CharacterCard({c, v, id, act}: {c: any; v: any; id: string; act: Act}) {
  const [text, setText] = useState(c.prompt?.text || '');
  useEffect(() => { setText(c.prompt?.text || ''); }, [c.prompt?.text]);
  const [count, setCount] = useState<number>(v.candidates_default || 2);
  const [newVersion, setNewVersion] = useState(false);
  const [keep, setKeep] = useState<Record<number, 'library' | 'episode' | ''>>({});
  const locked = !!c.master;
  const cost = imageCost(count, v.usd_per_image || 0);
  const pe = c.prompt_estimate;
  const gen = () => {
    if (!window.confirm(`${count} master candidate(s) for ${c.name}: ${cost.label}. Start now? (paid, not retried by itself)`)) return;
    act.run(`g${c.id}`, () => api(`/episodes/${id}/cast-video/characters/${c.id}/candidates`,
      {body: {count, confirm_usd: cost.usd, new_version: locked && newVersion, prompt: text !== c.prompt?.text ? text : undefined}}));
  };
  const gpt = () => {
    if (!pe || !window.confirm(`Write ${c.name}'s master prompt with ${pe.model}: at most $${pe.usd_max.toFixed(4)}. Send now? (paid, not retried by itself)`)) return;
    act.run(`w${c.id}`, () => api(`/episodes/${id}/cast-video/characters/${c.id}/prompt`, {body: {confirm_usd: pe.usd_max}}));
  };
  const approve = (a: any) => {
    const k = keep[a.id];
    if (!k) return;
    if (!window.confirm(`Approve this picture as ${c.name}'s master${locked ? ' (a NEW version: the current master is kept in history)' : ''}? ${keepText(k)}.`)) return;
    act.run(`a${a.id}`, () => api(`/episodes/${id}/cast-video/characters/${c.id}/approve`, {body: approveBody(a.id, k, locked)}));
  };
  const sheet = (s: 'expressions' | 'turnaround') => {
    const sc = imageCost(1, v.usd_per_image || 0);
    if (!window.confirm(`A ${s} sheet of ${c.name}, made from the approved master only: ${sc.label}. Start now?`)) return;
    act.run(`${s}${c.id}`, () => api(`/characters/${c.id}/stick/${s}`, {body: {confirm_usd: sc.usd}}));
  };
  return (
    <div className="card stack" style={{padding: 12}}>
      <div className="spread"><strong>{c.name}</strong>
        <span className="row">{c.in_library && <span className="badge">In your cast library</span>}
          <span className={`badge ${locked ? 'good' : c.candidates.length ? 'warn' : ''}`}>
            {locked ? 'Master approved · locked' : c.candidates.length ? 'Candidates to check' : 'No master yet'}</span></span></div>
      {c.locked_art && <p className="small muted">Uses approved repository artwork; it is not redrawn here.</p>}
      {c.master && <div className="row" style={{alignItems: 'flex-start', gap: 12}}>
        <img src={c.master.url} alt={`${c.name}: approved master`} style={{width: 160, borderRadius: 4}} />
        <div className="stack small" style={{gap: 6}}>
          <span>Approved master ({v.styles.find((s: any) => s.id === c.master_style)?.label || c.master_style}). Every later step uses it. It never changes: a change is a new version you approve.</span>
          <span className="row"><button className="btn sm" disabled={!!act.busy} onClick={() => sheet('expressions')}>Expression sheet · {money(v.usd_per_image)}</button>
            <button className="btn sm" disabled={!!act.busy} onClick={() => sheet('turnaround')}>Turnaround · {money(v.usd_per_image)}</button></span>
        </div></div>}
      {!c.locked_art && c.prompt && <div className="stack" style={{gap: 4}}>
        <label htmlFor={`cp-${c.id}`}>Master prompt <span className="muted small">({c.prompt.label})</span></label>
        <textarea id={`cp-${c.id}`} rows={5} value={text} onChange={e => setText(e.target.value)} />
        <div className="row">
          <button className="btn sm" disabled={!!act.busy || text === c.prompt.text || text.trim().length < 20}
            onClick={() => act.run(`p${c.id}`, () => api(`/episodes/${id}/cast-video/characters/${c.id}/prompt`, {method: 'PUT', body: {text}}))}>Save my text (free)</button>
          <button className="btn sm" disabled={!!act.busy || !pe || !v.keys?.openai} onClick={gpt}>
            Write with GPT{pe ? ` · up to $${pe.usd_max.toFixed(4)}` : ''}</button>
          {!v.keys?.openai && <span className="small muted">No OpenAI key: the template is used.</span>}
        </div></div>}
      {!c.locked_art && <div className="row small" style={{flexWrap: 'wrap'}}>
        <label htmlFor={`cn-${c.id}`} style={{margin: 0}}>Candidates</label>
        <select id={`cn-${c.id}`} value={count} onChange={e => setCount(Number(e.target.value))}>
          {[1, 2, 3, 4].map(n => <option key={n} value={n}>{n}</option>)}</select>
        {locked && <label className="row" style={{fontWeight: 400, color: 'inherit', margin: 0}}>
          <input type="checkbox" style={{width: 'auto'}} checked={newVersion} onChange={e => setNewVersion(e.target.checked)} />
          New version (the approved master stays until you approve another)</label>}
        <button className="btn sm primary" disabled={!!act.busy || c.busy || (locked && !newVersion) || !v.keys?.wavespeed} onClick={gen}>
          {c.busy ? 'Drawing…' : `Draw candidates · ${cost.label}`}</button>
      </div>}
      {c.candidates.length > 0 && <div className="row" style={{flexWrap: 'wrap', gap: 10, alignItems: 'flex-start'}}>
        {c.candidates.map((a: any) => (
          <div key={a.id} className="card stack" style={{padding: 8, width: 200, gap: 6}}>
            <img src={a.url} alt={`${c.name}: candidate`} style={{width: '100%', borderRadius: 4}} />
            <span className="small muted">{a.from_preview ? 'From the style preview' : 'Candidate'}</span>
            <fieldset className="small" style={{border: 0, padding: 0, margin: 0}}>
              <legend className="small">If approved:</legend>
              {(['library', 'episode'] as const).map(k => <label key={k} className="row" style={{fontWeight: 400, color: 'inherit', margin: 0}}>
                <input type="radio" style={{width: 'auto'}} name={`keep-${a.id}`} checked={keep[a.id] === k}
                  onChange={() => setKeep({...keep, [a.id]: k})} />{keepText(k)}</label>)}
            </fieldset>
            <span className="row">
              <button className="btn sm good" disabled={!!act.busy || !keep[a.id] || (locked && !newVersion)} onClick={() => approve(a)}>
                {locked ? 'Approve as new version' : 'Approve'}</button>
              <button className="btn sm" disabled={!!act.busy}
                onClick={() => act.run(`r${a.id}`, () => api(`/episodes/${id}/cast-video/characters/${c.id}/reject`, {body: {asset_id: a.id}}))}>Reject</button></span>
          </div>))}
      </div>}
      <ShotChat step="master" item={c.id} episodeId={id} onApplied={() => act.run(`c${c.id}`, async () => {})} />
    </div>);
}
