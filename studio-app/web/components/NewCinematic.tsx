'use client';
// New cinematic episode (API: POST /cinematic-episodes): a title and where the story comes from (an idea, a Bible
// passage with the owner's angle, or the owner's script). Scripture text is only accepted from a public-domain
// translation; the server's guard refuses or flags anything else (checked here first, free). Creating is free.
import {useEffect, useState} from 'react';
import {useRouter} from 'next/navigation';
import {api} from '@/lib/api';
import {useAction} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import {guardText, SOURCES, storyBody, storyReady, TRANSLATIONS, type Source} from '@/lib/cinematic';

export default function NewCinematic() {
  const router = useRouter();
  const [title, setTitle] = useState('');
  const [src, setSrc] = useState<Source>('idea');
  const [f, setF] = useState({idea: '', passage: '', translation: 'KJV', text: '', angle: '', script: '', confirm: false});
  const [guard, setGuard] = useState<any>(null);
  const {busy, error, run} = useAction();
  const set = (k: string, val: any) => setF({...f, [k]: val});
  useEffect(() => {
    setGuard(null);
    if (src !== 'bible' || (!f.text.trim() && !f.passage.trim())) return;
    const t = setTimeout(() => api('/cinematic/scripture/check', {body: {translation: f.translation, text: f.text, passage: f.passage}})
      .then(setGuard, () => setGuard(null)), 500);
    return () => clearTimeout(t);
  }, [src, f.text, f.translation, f.passage]);
  const g = guardText(f.text.trim() ? guard : null);
  const blocked = src === 'bible' && (guard?.status === 'refused' || (guard?.status === 'flagged' && !f.confirm) || !!guard?.passage_error);
  const ready = !!title.trim() && storyReady(src, f) && !blocked;
  const create = () => run('create', async () => {
    const v = await api('/cinematic-episodes', {body: {title: title.trim(), story: storyBody(src, f)}});
    router.push(`/episodes/${v.episode.id}/cinematic`);
  });
  return (
    <section className="card new-ep stack" aria-label="New cinematic episode">
      <h2 style={{margin: 0}}>+ New cinematic episode</h2>
      <ErrorBox error={error} />
      <div><label htmlFor="nc-title">Title</label><input id="nc-title" value={title} maxLength={200} onChange={e => setTitle(e.target.value)} /></div>
      <div role="radiogroup" aria-label="Where the story comes from" className="seg">
        {SOURCES.map(s => <button key={s.id} type="button" role="radio" aria-checked={src === s.id} className={src === s.id ? 'on' : ''}
          onClick={() => setSrc(s.id)}>{s.label}</button>)}
      </div>
      {src === 'idea' && <div><label htmlFor="nc-idea">The idea or logline</label>
        <textarea id="nc-idea" rows={3} maxLength={4000} value={f.idea} onChange={e => set('idea', e.target.value)}
          placeholder="e.g. An ageing king is challenged in his throne room by the queen, who reveals she commands fire." /></div>}
      {src === 'script' && <div><label htmlFor="nc-script">Your script</label>
        <textarea id="nc-script" rows={8} maxLength={30000} value={f.script} onChange={e => set('script', e.target.value)}
          placeholder={'INT. THRONE ROOM - NIGHT\nThe torches flicker.\nKING (angry): Kneel before your king.\n[VFX: fire blooms in her palm]'} />
        <p className="small muted">Scene headings (INT./EXT.), “NAME (emotion): line”, and [VFX: …] notes are understood.</p></div>}
      {src === 'bible' && <div className="stack">
        <div className="grid cols-3">
          <div><label htmlFor="nc-passage">Passage</label><input id="nc-passage" value={f.passage} maxLength={80}
            placeholder="Daniel 3:1-30" onChange={e => set('passage', e.target.value)} /></div>
          <div><label htmlFor="nc-tr">Translation</label>
            <select id="nc-tr" value={f.translation} onChange={e => set('translation', e.target.value)}>
              {TRANSLATIONS.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}</select></div>
        </div>
        {guard?.passage_error && <p className="small bad">{guard.passage_error}</p>}
        <div><label htmlFor="nc-angle">Your angle (what the film is about for you)</label>
          <textarea id="nc-angle" rows={2} maxLength={2000} value={f.angle} onChange={e => set('angle', e.target.value)} /></div>
        <div><label htmlFor="nc-text">The passage text (optional; public-domain translations only)</label>
          <textarea id="nc-text" rows={4} maxLength={20000} value={f.text} onChange={e => set('text', e.target.value)}
            placeholder="Paste from a KJV, WEB or ASV source only. Never paste NIV, ESV, NLT or other copyrighted translations." /></div>
        {g.text && <p className={`small ${g.tone}`} role="status">{g.text}</p>}
        {guard?.status === 'flagged' && <label className="check"><input type="checkbox" checked={f.confirm}
          onChange={e => set('confirm', e.target.checked)} />I copied it from a public-domain {f.translation} source</label>}
      </div>}
      <div className="spread">
        <span className="muted small">Free. Next the studio writes a screenplay for you to edit and approve (its cost is shown first).</span>
        <button className="btn primary" disabled={!ready || !!busy} onClick={create}>{busy ? 'Creating…' : 'Create'}</button>
      </div>
    </section>);
}
