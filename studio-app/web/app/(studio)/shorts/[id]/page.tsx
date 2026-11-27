'use client';
// The New short wizard (API: narrated_short.py): one page, nine steps in plain English, for a narrated stick-man short.
// Every paid button shows its price and asks first; the request carries that price (the API refuses any other with
// 409 and starts nothing). Nothing approves itself: script, narration, pictures and the final video each wait for the
// owner's click. "Make this short" (the autopilot) sits on top: one budget, then it runs the steps and stops at every
// approval. The chat under the script, the narration and each scene's picture and clip proposes one change at a time.
import Link from 'next/link';
import {use, useEffect, useState} from 'react';
import {api, uploadFile} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import Autopilot from '@/components/Autopilot';
import ShotChat from '@/components/ShotChat';
import {approvedScript, captionsText, chosenClip, chosenPicture, HELP, latestScript, lengthLabel, NICHE_HINT, paidConfirm,
  paidLabel, picturesSummary, sceneTime, scriptLength, STATE_TEXT, stepStates, STEPS, usd, voiceCostText,
  type StepKey} from '@/lib/narratedShort';

type Act = ReturnType<typeof useAction>;

export default function ShortPage({params}: {params: Promise<{id: string}>}) {
  const {id} = use(params);
  const [poll, setPoll] = useState(15000);
  const {data: v, error, reload} = useApi<any>(`/shorts/${id}`, poll);
  const act = useAction(reload);
  useEffect(() => { setPoll(v?.busy ? 4000 : 15000); }, [v?.busy]);
  if (!v) return error ? <ErrorBox error={error} /> : <p className="muted">Loading…</p>;
  const states = stepStates(v);
  return (
    <>
      <div className="ep-head">
        <div>
          <p className="small" style={{margin: '0 0 4px'}}><Link href="/">← Episodes</Link></p>
          <h1 style={{margin: 0}}>{v.title}</h1>
          <p className="sub">Narrated short · {v.choose.format} · {lengthLabel(v.choose.seconds)} · spent so far {usd(v.usd)}</p>
        </div>
      </div>
      <Autopilot id={id} onChange={reload} title="Make this short"
        blurb="Set one budget for the whole short. The autopilot runs steps 2 to 9 in order, starts paid work only while it fits in the budget and the monthly GPU cap, and stops to wait for you at every choice and approval (the idea, the script, the narration, each picture and the final video). It never approves anything for you."
        freeTierText="Let the narration use Gemini's free tier (Google may use the text to improve its products)." />
      <nav className="card" aria-label="Steps" style={{padding: 10, display: 'flex', flexWrap: 'wrap', gap: 8}}>
        {STEPS.map(s => <a key={s.key} href={`#step-${s.key}`} className="small">
          {s.n}. {s.title} <span className={`badge ${STATE_TEXT[states[s.key]].tone}`}>{STATE_TEXT[states[s.key]].text}</span></a>)}
      </nav>
      <ErrorBox error={act.error} />
      <Choose v={v} act={act} id={id} />
      <Ideas v={v} act={act} id={id} />
      <Script v={v} act={act} id={id} reload={reload} />
      <Scenes v={v} act={act} id={id} />
      <Voice v={v} act={act} id={id} reload={reload} />
      <Pictures v={v} act={act} id={id} reload={reload} />
      <Motion v={v} act={act} id={id} reload={reload} />
      <Assembly v={v} act={act} id={id} />
      <Publish v={v} act={act} id={id} />
    </>);
}

function Step({k, state, children}: {k: StepKey; state: string; children: React.ReactNode}) {
  const s = STEPS.find(x => x.key === k)!;
  const st = (STATE_TEXT as any)[state];
  return (
    <section id={`step-${k}`} className="card stack" style={{padding: 14, marginTop: 12}} aria-label={`Step ${s.n}: ${s.title}`}>
      <div className="spread"><h2 style={{margin: 0}}>{s.n}. {s.title}</h2><span className={`badge ${st.tone}`}>{st.text}</span></div>
      <p className="small muted" style={{margin: 0, maxWidth: 820}}>{HELP[k]}</p>
      {children}
    </section>);
}

// a paid button: shows the price, asks first, sends the same price as confirm_usd
function Paid({label, est, act, name, run, disabled}: {label: string; est: any; act: Act; name: string;
  run: (confirm: number) => Promise<unknown>; disabled?: boolean}) {
  const go = () => {
    if (!est || est.usd_max == null || !window.confirm(paidConfirm(label, est))) return;
    act.run(name, () => run(est.usd_max));
  };
  return <button className="btn primary" disabled={!!act.busy || disabled || !est || est.usd_max == null} onClick={go}>
    {paidLabel(label, est, act.busy === name)}</button>;
}

// ------------------------------------------------------------------ 1. choose
function Choose({v, act, id}: {v: any; act: Act; id: string}) {
  const [c, setC] = useState<any>(v.choose);
  useEffect(() => setC(v.choose), [JSON.stringify(v.choose)]);   // eslint-disable-line react-hooks/exhaustive-deps
  const toggle = (cid: number) => {
    const has = c.characters.includes(cid);
    const next = has ? c.characters.filter((x: number) => x !== cid) : [...c.characters, cid].slice(-v.options.max_characters);
    setC({...c, characters: next});
  };
  const save = () => act.run('choose', () => api(`/shorts/${id}/choose`, {method: 'PUT', body: c}));
  return (
    <Step k="choose" state={stepStates(v).choose}>
      <div className="row" style={{flexWrap: 'wrap', gap: 12}}>
        <div><label htmlFor="ns-niche">Niche</label>
          <select id="ns-niche" value={c.niche} onChange={e => setC({...c, niche: e.target.value})}>
            {Object.entries(v.options.niches).map(([k, l]) => <option key={k} value={k}>{l as string}</option>)}</select>
          <div className="small muted">{NICHE_HINT[c.niche]}</div></div>
        {c.niche === 'custom' && <div><label htmlFor="ns-custom">Your niche</label>
          <input id="ns-custom" value={c.custom_niche} maxLength={200} onChange={e => setC({...c, custom_niche: e.target.value})} /></div>}
        <div role="radiogroup" aria-label="Format" className="seg">
          {v.options.formats.map((f: string) => <button key={f} type="button" role="radio" aria-checked={c.format === f}
            className={c.format === f ? 'on' : ''} onClick={() => setC({...c, format: f})}>{f}</button>)}</div>
        <div><label htmlFor="ns-len">Length</label>
          <select id="ns-len" value={c.seconds} onChange={e => setC({...c, seconds: Number(e.target.value)})}>
            {v.options.lengths.map((s: number) => <option key={s} value={s}>{lengthLabel(s)}</option>)}</select></div>
      </div>
      <div className="small"><strong>Characters</strong> (one or two house characters; their approved master is used as it is)</div>
      <div className="row" style={{flexWrap: 'wrap', gap: 10}}>
        {v.cast.length === 0 && <p className="small muted">No character with an approved master yet. Make one in <Link href="/characters">Characters</Link> (the Cast flow).</p>}
        {v.cast.map((o: any) => {
          const on = c.characters.includes(o.character_id);
          return <button key={o.character_id} type="button" className={`card stack${on ? ' on' : ''}`} aria-pressed={on}
            onClick={() => toggle(o.character_id)} style={{padding: 8, width: 140, gap: 4, outline: on ? '2px solid var(--accent, #2563eb)' : undefined}}>
            {o.master_url && <img src={o.master_url} alt={`${o.name}: approved master`} style={{width: '100%', borderRadius: 4}} />}
            <strong className="small">{o.name}</strong><span className="small muted">{o.from}</span></button>;
        })}
      </div>
      {v.missing_masters.length > 0 && <p className="small bad">No approved master yet for {v.missing_masters.join(', ')}: approve one first.</p>}
      <div><button className="btn" disabled={!!act.busy} onClick={save}>{act.busy === 'choose' ? 'Saving…' : 'Save (free)'}</button></div>
    </Step>);
}

// ------------------------------------------------------------------ 2. ideas
function Ideas({v, act, id}: {v: any; act: Act; id: string}) {
  const [own, setOwn] = useState({title: '', hook: '', twist: '', label: 'fiction'});
  const items: any[] = v.ideas?.items || [];
  return (
    <Step k="ideas" state={stepStates(v).ideas}>
      {v.idea && <div className="small"><strong>Chosen:</strong> {v.idea.title} {v.idea.check && <span className="badge warn">check before publishing</span>}
        <span className="muted"> · {v.idea.label}</span></div>}
      <div className="row"><Paid label={items.length ? 'Write 10 new ideas' : 'Write 10 ideas'} est={v.estimates.ideas} act={act} name="ideas"
        disabled={!v.estimates.ideas?.key_set}
        run={c => api(`/shorts/${id}/ideas`, {body: {confirm_usd: c}})} />
        {!v.estimates.ideas?.key_set && <span className="small muted">No OpenAI key: type your own idea below.</span>}</div>
      {items.length > 0 && <div className="stack" style={{gap: 6}}>
        {items.map(i => <div key={i.id} className="card" style={{padding: 8}}>
          <div className="spread"><strong>{i.title}</strong>
            <span className="row">{i.check && <span className="badge warn">check before publishing</span>}<span className="badge">{i.label}</span>
              <button className="btn sm" disabled={!!act.busy || v.idea?.id === i.id}
                onClick={() => act.run(`pick${i.id}`, () => api(`/shorts/${id}/idea`, {method: 'PUT', body: {idea_id: i.id}}))}>
                {v.idea?.id === i.id ? 'Chosen' : 'Use this idea'}</button></span></div>
          <div className="small">Hook: {i.hook}</div><div className="small">Twist: {i.twist}</div>
          <div className="small muted">{i.why_it_animates}</div></div>)}
      </div>}
      <details><summary className="small">Or type your own idea (free)</summary>
        <div className="stack" style={{marginTop: 8}}>
          <input aria-label="Title" placeholder="Title" value={own.title} maxLength={120} onChange={e => setOwn({...own, title: e.target.value})} />
          <input aria-label="Hook line" placeholder="Hook line (the first words)" value={own.hook} maxLength={300} onChange={e => setOwn({...own, hook: e.target.value})} />
          <input aria-label="Twist" placeholder="Twist / payoff" value={own.twist} maxLength={300} onChange={e => setOwn({...own, twist: e.target.value})} />
          <select aria-label="Label" value={own.label} onChange={e => setOwn({...own, label: e.target.value})}>
            <option value="fiction">Fiction (invented)</option><option value="legend">Legend ("legend says")</option>
            <option value="true">True (facts: check before publishing)</option></select>
          <div><button className="btn" disabled={!!act.busy || !own.title.trim()}
            onClick={() => act.run('own', () => api(`/shorts/${id}/idea`, {method: 'PUT', body: own}))}>Use my idea</button></div>
        </div></details>
    </Step>);
}

// ------------------------------------------------------------------ 3. script
function Script({v, act, id, reload}: {v: any; act: Act; id: string; reload: () => unknown}) {
  const cur = latestScript(v);
  const ok = approvedScript(v);
  const [text, setText] = useState(cur?.text || '');
  const [notes, setNotes] = useState('');
  useEffect(() => setText(cur?.text || ''), [cur?.v]);   // eslint-disable-line react-hooks/exhaustive-deps
  const dirty = text.trim() && text !== (cur?.text || '');
  return (
    <Step k="script" state={stepStates(v).script}>
      <div className="row" style={{flexWrap: 'wrap'}}>
        <input aria-label="Notes for the writer" placeholder="Notes for the writer (optional)" value={notes} maxLength={2000}
          style={{minWidth: 260}} onChange={e => setNotes(e.target.value)} />
        <Paid label={cur ? 'Write it again' : 'Write the script'} est={v.estimates.script} act={act} name="script"
          disabled={!v.idea || !v.estimates.script?.key_set}
          run={c => api(`/shorts/${id}/script/write`, {body: {confirm_usd: c, notes}})} />
        {!v.idea && <span className="small muted">Pick an idea first.</span>}
      </div>
      <textarea aria-label="Narration" rows={8} value={text} maxLength={20000} onChange={e => setText(e.target.value)}
        placeholder="The narration, words to be read aloud only. Type it yourself or let GPT write it." />
      <div className="spread small">
        <span className="muted">{scriptLength(text, v.choose.seconds, v.options.words_per_second)}{cur ? ` · version ${cur.v} (${cur.source})` : ''}
          {ok ? ` · approved: version ${ok.v}` : ' · not approved yet'}</span>
        <span className="row">
          <button className="btn" disabled={!!act.busy || !dirty}
            onClick={() => act.run('save', () => api(`/shorts/${id}/script`, {method: 'PUT', body: {text}}))}>Save my edit (free)</button>
          <button className="btn good" disabled={!!act.busy || !cur || !!dirty || ok?.v === cur?.v}
            onClick={() => act.run('approve', () => api(`/shorts/${id}/script/approve`, {body: {version: cur.v}}))}>Approve this script</button>
          {ok && <button className="btn sm" disabled={!!act.busy}
            onClick={() => act.run('unapprove', () => api(`/shorts/${id}/script/unapprove`, {method: 'POST'}))}>Withdraw approval</button>}
        </span>
      </div>
      <ShotChat step="short_script" item={id} episodeId={id} onApplied={reload} />
    </Step>);
}

// ------------------------------------------------------------------ 4. scenes
function Scenes({v, act, id}: {v: any; act: Act; id: string}) {
  const scenes: any[] = v.scenes.items || [];
  return (
    <Step k="scenes" state={stepStates(v).scenes}>
      {!scenes.length && <p className="small muted">The scenes appear when the script is approved.</p>}
      {scenes.length > 0 && <div className="row" style={{flexWrap: 'wrap'}}>
        <Paid label="GPT writes every prompt" est={v.estimates.prompts} act={act} name="prompts" disabled={!v.estimates.prompts?.key_set}
          run={c => api(`/shorts/${id}/scenes/prompts`, {body: {confirm_usd: c}})} />
        <button className="btn" disabled={!!act.busy}
          onClick={() => act.run('tpl', () => api(`/shorts/${id}/scenes/prompts`, {body: {use_template: true}}))}>Use the templates (free)</button>
        <button className="btn sm" disabled={!!act.busy}
          onClick={() => window.confirm('Split the approved script into scenes again? Pictures and clips of the current scenes are no longer used.')
            && act.run('split', () => api(`/shorts/${id}/scenes/split`, {method: 'POST'}))}>Split again</button>
        <span className="small muted">{scenes.length} scenes</span></div>}
      {scenes.map(s => <SceneEditor key={`${v.scenes.version}-${s.n}`} s={s} act={act} id={id} />)}
    </Step>);
}

function SceneEditor({s, act, id}: {s: any; act: Act; id: string}) {
  const [pp, setPp] = useState(s.picture_prompt || '');
  const [ap, setAp] = useState(s.animation_prompt || '');
  const [line, setLine] = useState(s.text);
  useEffect(() => { setPp(s.picture_prompt || ''); setAp(s.animation_prompt || ''); setLine(s.text); }, [s.picture_prompt, s.animation_prompt, s.text]);
  const dirty = pp !== (s.picture_prompt || '') || ap !== (s.animation_prompt || '') || line !== s.text;
  return (
    <details className="card" style={{padding: 8}}>
      <summary className="small"><strong>Scene {s.n}</strong> · {sceneTime(s)} · {s.text}</summary>
      <div className="stack" style={{marginTop: 8}}>
        <label className="small">Line (changing it makes the script wait for approval again)
          <input value={line} maxLength={1000} onChange={e => setLine(e.target.value)} /></label>
        <label className="small">Picture prompt {s.prompt_source && <span className="muted">({s.prompt_source})</span>}
          <textarea rows={3} value={pp} maxLength={4000} onChange={e => setPp(e.target.value)} /></label>
        <label className="small">Animation prompt<textarea rows={2} value={ap} maxLength={1500} onChange={e => setAp(e.target.value)} /></label>
        <div><button className="btn sm" disabled={!!act.busy || !dirty}
          onClick={() => act.run(`scene${s.n}`, () => api(`/shorts/${id}/scenes/${s.n}`, {method: 'PUT', body: {
            ...(line !== s.text ? {text: line} : {}), picture_prompt: pp, animation_prompt: ap}}))}>Save (free)</button></div>
      </div>
    </details>);
}

// ------------------------------------------------------------------ 5. voice
function Voice({v, act, id, reload}: {v: any; act: Act; id: string; reload: () => unknown}) {
  const [voice, setVoice] = useState(v.voice.voice || v.options.default_voice);
  const [style, setStyle] = useState(v.voice.style || v.options.default_style);
  const free = !!v.voice.use_free_tier, paid = !!v.options.tts_paid_tier;
  const est = v.estimates.voice;
  // the ticks are saved at once (free) and the server prices the narration for them; the button carries that price
  const settings = (patch: any) => act.run('vs', () => api(`/shorts/${id}/voice/settings`, {method: 'PUT',
    body: {voice, style, use_free_tier: free, ...patch}}));
  const setPaidTier = (on: boolean) => act.run('tier', () => api('/settings/short', {method: 'PUT', body: {tts_paid_tier: on}}));
  const takes: any[] = v.voice.takes || [];
  const upload = (f: File | undefined) => {
    if (!f) return;
    const tr = v.estimates.voice?.transcription;
    const q: Record<string, string> = {};
    if (tr && tr.usd > 0) {
      if (!window.confirm(`Upload your narration: ${tr.label}. Go on?`)) return;
      q.confirm_usd = String(tr.usd);
    }
    act.run('upload', () => uploadFile(`/shorts/${id}/voice/upload`, f, q));
  };
  return (
    <Step k="voice" state={stepStates(v).voice}>
      <div className="row" style={{flexWrap: 'wrap'}}>
        <div><label htmlFor="ns-voice">Voice</label>
          <select id="ns-voice" value={voice} onChange={e => { setVoice(e.target.value); settings({voice: e.target.value}); }}>
            {v.options.voices.map((x: string) => <option key={x} value={x}>{x}</option>)}</select></div>
        <div style={{flex: 1, minWidth: 220}}><label htmlFor="ns-style">Style</label>
          <input id="ns-style" value={style} maxLength={200} onChange={e => setStyle(e.target.value)}
            onBlur={() => settings({})} placeholder="warm, calm narrator" /></div>
      </div>
      <label className="check"><input type="checkbox" checked={paid} onChange={e => setPaidTier(e.target.checked)} />My Gemini key is on a paid tier</label>
      <label className="check"><input type="checkbox" checked={free} onChange={e => settings({use_free_tier: e.target.checked})} />
        Use the free tier ({v.options.free_warning})</label>
      <div className="small muted">{voiceCostText(est)}</div>
      <div className="row">
        <Paid label="Make the narration" est={est && !est.blocked ? est : null} act={act} name="voice"
          disabled={!approvedScript(v) || (!free && !paid)}
          run={c => api(`/shorts/${id}/voice`, {body: {voice, style, use_free_tier: free, confirm_usd: c}})} />
        <label className="btn" style={{cursor: 'pointer'}}>Upload my own voice
          <input type="file" accept="audio/*" hidden onChange={e => upload(e.target.files?.[0])} /></label>
      </div>
      {takes.length > 0 && <div className="stack" style={{gap: 6}}>
        {takes.slice().reverse().map(t => <div key={t.id} className="card" style={{padding: 8}}>
          <div className="spread small"><span>{t.source === 'upload' ? 'Your recording' : `${t.voice} · "${t.style}"`} · {t.seconds.toFixed(1)} s
            · {t.words} timed words · {t.free_tier ? 'free tier' : usd(t.usd)}{!t.fits && <span className="bad"> · reads an older script</span>}</span>
            <span>{v.voice.approved === t.id ? <span className="badge good">Approved</span>
              : <button className="btn sm good" disabled={!!act.busy || !t.fits}
                onClick={() => act.run(`take${t.id}`, () => api(`/shorts/${id}/voice/approve`, {body: {take_id: t.id}}))}>Approve this take</button>}</span></div>
          {t.url && <audio controls src={t.url} style={{width: '100%'}} />}
          {t.warning && <div className="small muted">{t.warning}</div>}
        </div>)}
      </div>}
      <ShotChat step="short_voice" item={id} episodeId={id} onApplied={reload} />
    </Step>);
}

// ------------------------------------------------------------------ 6. pictures
function Pictures({v, act, id, reload}: {v: any; act: Act; id: string; reload: () => unknown}) {
  const scenes: any[] = v.scenes.items || [];
  return (
    <Step k="pictures" state={stepStates(v).pictures}>
      <div className="row">
        {v.estimates.pictures_all && <Paid label="Draw every missing picture" est={v.estimates.pictures_all ? {...v.estimates.pictures_all, usd_max: v.estimates.pictures_all.usd}
          : null} act={act} name="all" run={c => api(`/shorts/${id}/pictures/all`, {body: {confirm_usd: c}})} />}
        <span className="small muted">{picturesSummary(scenes)} · {v.estimates.picture?.label}</span></div>
      <div className="row" style={{flexWrap: 'wrap', gap: 12, alignItems: 'stretch'}}>
        {scenes.map(s => {
          const p = chosenPicture(s);
          return <div key={s.n} className="card stack" style={{padding: 8, width: 230, gap: 6}}>
            <div className="spread small"><strong>Scene {s.n}</strong>{s.picture_approved ? <span className="badge good">Approved</span>
              : s.busy ? <span className="badge busy">Drawing</span> : p ? <span className="badge warn">Waiting for you</span> : null}</div>
            <div className="small muted">{s.text}</div>
            {p ? <img src={p.url} alt={`Scene ${s.n} picture`} style={{width: '100%', borderRadius: 4}} /> : <div className="frame-ph small muted">No picture yet</div>}
            {s.pictures.length > 1 && <div className="row small" style={{flexWrap: 'wrap'}}>{s.pictures.map((x: any, i: number) =>
              <button key={x.asset_id} className={`btn sm${x.asset_id === s.picture_chosen ? ' on' : ''}`} disabled={!!act.busy}
                onClick={() => act.run(`c${x.asset_id}`, () => api(`/shorts/${id}/scenes/${s.n}/picture/choose`, {body: {asset_id: x.asset_id}}))}>Take {i + 1}</button>)}</div>}
            <div className="row">
              <Paid label={p ? 'Redo' : 'Draw'} est={v.estimates.picture ? {...v.estimates.picture, usd_max: v.estimates.picture.usd} : null}
                act={act} name={`pic${s.n}`} disabled={s.busy}
                run={c => api(`/shorts/${id}/scenes/${s.n}/picture`, {body: {confirm_usd: c}})} />
              {p && !s.picture_approved && <button className="btn sm good" disabled={!!act.busy}
                onClick={() => act.run(`ok${s.n}`, () => api(`/shorts/${id}/scenes/${s.n}/picture/approve`, {body: {asset_id: p.asset_id}}))}>Approve</button>}
              {p && s.picture_approved && <button className="btn sm" disabled={!!act.busy}
                onClick={() => act.run(`un${s.n}`, () => api(`/shorts/${id}/scenes/${s.n}/picture/unapprove`, {body: {asset_id: p.asset_id}}))}>Withdraw</button>}
            </div>
            <ShotChat step="short_picture" item={s.n} episodeId={id} onApplied={reload} />
          </div>;
        })}
      </div>
    </Step>);
}

// ------------------------------------------------------------------ 7. motion
function Motion({v, act, id, reload}: {v: any; act: Act; id: string; reload: () => unknown}) {
  const scenes: any[] = v.scenes.items || [];
  const est = v.estimates.motion;
  const gpu = (v.providers || []).find((p: any) => p.step === 'motion');
  return (
    <Step k="motion" state={stepStates(v).motion}>
      <div role="radiogroup" aria-label="Motion engine" className="stack" style={{gap: 4}}>
        {Object.entries(v.motion.engines).map(([k, e]: [string, any]) => <label key={k} className="check" style={{opacity: e.ready ? 1 : 0.6}}>
          <input type="radio" name="engine" checked={k === 'wan_gpu'} disabled={!e.ready} readOnly />{e.label}
          {!e.ready && <span className="badge">coming soon</span>} <span className="small muted">{e.note}</span></label>)}
      </div>
      {gpu && !gpu.ready && <p className="small bad">{gpu.note} <Link href="/settings">Open Settings</Link></p>}
      <div className="row">
        <Paid label={`Animate ${est.scenes.length} scene(s)`} est={est.scenes.length ? est : null} act={act} name="motion"
          disabled={!gpu?.ready || !est.scenes.length} run={c => api(`/shorts/${id}/motion`, {body: {engine: 'wan_gpu', confirm_usd: c}})} />
        <span className="small muted">{est.scenes.length ? est.label : 'Every approved picture has a clip (or none is approved yet).'}</span></div>
      <div className="row" style={{flexWrap: 'wrap', gap: 12, alignItems: 'stretch'}}>
        {scenes.filter(s => (s.clips || []).length).map(s => {
          const c = chosenClip(s);
          return <div key={s.n} className="card stack" style={{padding: 8, width: 230, gap: 6}}>
            <div className="spread small"><strong>Scene {s.n}</strong>{s.clip_approved && <span className="badge good">Approved</span>}</div>
            {c && <video src={c.url} controls muted loop playsInline style={{width: '100%', borderRadius: 4}} />}
            {s.clips.length > 1 && <div className="row small" style={{flexWrap: 'wrap'}}>{s.clips.map((x: any, i: number) =>
              <button key={x.asset_id} className={`btn sm${x.asset_id === s.clip_chosen ? ' on' : ''}`} disabled={!!act.busy}
                onClick={() => act.run(`cc${x.asset_id}`, () => api(`/shorts/${id}/scenes/${s.n}/clip/choose`, {body: {asset_id: x.asset_id}}))}>Clip {i + 1}</button>)}</div>}
            {c && !s.clip_approved && <button className="btn sm good" disabled={!!act.busy}
              onClick={() => act.run(`ca${s.n}`, () => api(`/shorts/${id}/scenes/${s.n}/clip/approve`, {body: {asset_id: c.asset_id}}))}>Approve this clip</button>}
            <ShotChat step="short_clip" item={s.n} episodeId={id} onApplied={reload} />
          </div>;
        })}
      </div>
    </Step>);
}

// ------------------------------------------------------------------ 8. timing + assembly
function Assembly({v, act, id}: {v: any; act: Act; id: string}) {
  const cuts: any[] = v.final.cuts || [];
  const a = v.assembly;
  const music = v.music || {};
  return (
    <Step k="assembly" state={stepStates(v).assembly}>
      <label className="check"><input type="checkbox" checked={v.captions}
        onChange={e => act.run('cap', () => api(`/shorts/${id}/options`, {method: 'PUT', body: {captions: e.target.checked}}))} />{captionsText(v.captions)}</label>
      <div className="row small">
        <label className="btn sm" style={{cursor: 'pointer'}}>{music.asset_id ? 'Replace the music' : 'Add music (optional)'}
          <input type="file" accept="audio/*" hidden onChange={e => { const f = e.target.files?.[0]; if (f) act.run('music', () => uploadFile(`/shorts/${id}/music`, f)); }} /></label>
        {music.asset_id && <label className="check"><input type="checkbox" checked={!!music.enabled}
          onChange={e => act.run('mus', () => api(`/shorts/${id}/options`, {method: 'PUT', body: {music_enabled: e.target.checked}}))} />
          Use the music (levelled 6 dB under the voice)</label>}
        {music.url && <audio controls src={music.url} />}
        <span className="muted">Only use music you have the right to use.</span>
      </div>
      {!a.voice_ok && <p className="small muted">Approve a narration take first: the scenes are timed on its words.</p>}
      {a.missing.length > 0 && <p className="small muted">Scene(s) {a.missing.join(', ')} still need an approved picture or a clip.</p>}
      <div className="row"><button className="btn primary" disabled={!!act.busy || !v.ffmpeg || !a.voice_ok || a.missing.length > 0}
        onClick={() => act.run('assemble', () => api(`/shorts/${id}/assemble`, {method: 'POST'}))}>
        {act.busy === 'assemble' ? 'Starting…' : 'Put the short together (free)'}</button></div>
      {cuts.map(c => <div key={c.id} className="card stack" style={{padding: 8}}>
        <div className="spread small"><span>{c.seconds.toFixed(2)} s · {c.frames} frames · {c.captions ? 'captions' : 'no captions'}
          {c.music_gain_db != null ? ` · music ${c.music_gain_db.toFixed(1)} dB` : ''}{c.stills ? ` · ${c.stills} still(s), not animated` : ''}
          {!c.current && <span className="muted"> · older inputs</span>}</span>
          {v.final.approved === c.id ? <span className="row"><span className="badge good">Approved</span>
            <button className="btn sm" disabled={!!act.busy} onClick={() => act.run('fu', () => api(`/shorts/${id}/final/approve`, {body: {cut_id: null}}))}>Withdraw</button></span>
            : <button className="btn sm good" disabled={!!act.busy || !c.current}
              onClick={() => act.run(`f${c.id}`, () => api(`/shorts/${id}/final/approve`, {body: {cut_id: c.id}}))}>Approve the final video</button>}</div>
        {c.url && <video src={c.url} controls playsInline style={{maxWidth: 360, width: '100%', borderRadius: 4}} />}
        {c.warnings?.length > 0 && <ul className="small muted">{c.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}</ul>}
      </div>)}
    </Step>);
}

// ------------------------------------------------------------------ 9. publish
function Publish({v, act, id}: {v: any; act: Act; id: string}) {
  const pub = v.publish || {};
  const [desc, setDesc] = useState(pub.description || '');
  const [prompt, setPrompt] = useState(pub.thumbnail_prompt || '');
  useEffect(() => { setDesc(pub.description || ''); setPrompt(pub.thumbnail_prompt || ''); }, [pub.at]);   // eslint-disable-line react-hooks/exhaustive-deps
  const thumbs: any[] = pub.thumbnails || [];
  return (
    <Step k="publish" state={stepStates(v).publish}>
      {(v.idea?.check || pub.check) && <p className="small bad">This story presents facts as true: check them before publishing.</p>}
      <div className="row"><Paid label={pub.titles?.length ? 'Write the pack again' : 'Write the publish pack'} est={v.estimates.publish}
        act={act} name="pub" disabled={!v.estimates.publish?.key_set} run={c => api(`/shorts/${id}/publish/write`, {body: {confirm_usd: c}})} /></div>
      {(pub.titles || []).length > 0 && <div className="stack" style={{gap: 4}}>
        <strong className="small">Titles (pick one)</strong>
        {pub.titles.map((t: string) => <label key={t} className="check"><input type="radio" name="title" checked={pub.title === t}
          onChange={() => act.run('t', () => api(`/shorts/${id}/publish`, {method: 'PUT', body: {title: t}}))} />{t}</label>)}
        <label className="small">Description<textarea rows={3} value={desc} maxLength={4000} onChange={e => setDesc(e.target.value)} /></label>
        <div className="small">{(pub.hashtags || []).join(' ')}</div>
        <div><button className="btn sm" disabled={!!act.busy || desc === (pub.description || '')}
          onClick={() => act.run('d', () => api(`/shorts/${id}/publish`, {method: 'PUT', body: {description: desc}}))}>Save (free)</button></div>
      </div>}
      <label className="small">Thumbnail prompt<textarea rows={2} value={prompt} maxLength={2000} onChange={e => setPrompt(e.target.value)}
        placeholder="Your character plus the one visual idea, 3-5 words of text" /></label>
      <div className="row">
        <button className="btn sm" disabled={!!act.busy || prompt === (pub.thumbnail_prompt || '')}
          onClick={() => act.run('tp', () => api(`/shorts/${id}/publish`, {method: 'PUT', body: {thumbnail_prompt: prompt}}))}>Save the prompt (free)</button>
        <Paid label="Make the thumbnail" est={v.estimates.thumbnail ? {...v.estimates.thumbnail, usd_max: v.estimates.thumbnail.usd} : null}
          act={act} name="thumb" disabled={prompt !== (pub.thumbnail_prompt || '')} run={c => api(`/shorts/${id}/publish/thumbnail`, {body: {confirm_usd: c}})} /></div>
      <div className="row" style={{flexWrap: 'wrap', gap: 10}}>
        {thumbs.map(t => <div key={t.asset_id} className="card stack" style={{padding: 6, width: 200}}>
          {t.url && <img src={t.url} alt="Thumbnail" style={{width: '100%', borderRadius: 4}} />}
          {pub.thumbnail_approved === t.asset_id ? <span className="badge good">Approved</span>
            : <button className="btn sm good" disabled={!!act.busy}
              onClick={() => act.run(`th${t.asset_id}`, () => api(`/shorts/${id}/publish/thumbnail/approve`, {body: {asset_id: t.asset_id}}))}>Use this thumbnail</button>}
        </div>)}
      </div>
      <p className="small muted">The chosen title, description, hashtags and thumbnail go to the episode&apos;s publishing draft. Nothing is uploaded from here.</p>
    </Step>);
}
