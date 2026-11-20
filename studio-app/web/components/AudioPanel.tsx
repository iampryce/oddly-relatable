'use client';
import {useEffect, useRef, useState} from 'react';
import {api, uploadAudio} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from './ui';

// Audio-first episode, stage 1: the uploaded audio (the voice track), its timed lines, a speaker per line, and the cast.
// The server validates every change (timing inside the audio, in order, no overlaps); this page only prepares it.

type Word = {start: number; end: number; word: string};
type Line = {id: string; start: number; end: number; text: string; speaker: string; words: Word[]};
type NewChar = {key: string; name: string; description: string; visual_description: string; voice_style: string; bubble_style: string};
type CastChoice = {mode: 'existing' | 'new'; character_key: string; new: NewChar};

const RIGHTS: Record<string, string> = {own_recording: 'Own recording', licensed: 'Licensed', voice_actor: 'Voice actor', other: 'Other'};
const fmt = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`;
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').replace(/^[^a-z]+/, '').slice(0, 41);

export default function AudioPanel({episodeId, onChange}: {episodeId: number; onChange?: () => unknown}) {
  const [poll, setPoll] = useState(4000);
  const {data: st, error, reload} = useApi<any>(`/episodes/${episodeId}/audio`, poll);
  const act = useAction(async () => { await reload(); await onChange?.(); });
  const [lines, setLines] = useState<Line[] | null>(null);
  const [dirty, setDirty] = useState(false);
  const [splitting, setSplitting] = useState<number | null>(null);
  const player = useRef<HTMLAudioElement>(null);
  const stopAt = useRef<number | null>(null);

  useEffect(() => {
    if (!st) return;
    setPoll(st.stage === 'audio_transcribing' ? 2500 : 15000);
    if (!dirty) setLines(st.lines || []);
  }, [st, dirty]);

  if (!st) return error ? <ErrorBox error={error} /> : <p className="muted">Loading…</p>;
  const editable = st.allowed_actions.includes('label_audio');
  const update = (next: Line[]) => { setLines(next); setDirty(true); };
  const setLine = (i: number, patch: Partial<Line>) => update(lines!.map((l, k) => (k === i ? {...l, ...patch} : l)));
  const play = (l: Line) => {
    const a = player.current;
    if (!a) return;
    a.currentTime = l.start; stopAt.current = l.end; a.play();
  };
  const merge = (i: number) => {
    const a = lines![i], b = lines![i + 1];
    const speaker = a.speaker || b.speaker;
    update([...lines!.slice(0, i), {...a, end: b.end, text: `${a.text} ${b.text}`.trim(), speaker, words: [...a.words, ...b.words]}, ...lines!.slice(i + 2)]);
  };
  const split = (i: number, w: number) => {   // split before word w
    const l = lines![i];
    const first = l.words.slice(0, w), second = l.words.slice(w);
    if (!first.length || !second.length) return;
    const text = (ws: Word[]) => ws.map(x => x.word).join(' ');
    update([...lines!.slice(0, i), {...l, end: first[first.length - 1].end, text: text(first), words: first},
            {...l, id: `${l.id}b`, start: second[0].start, text: text(second), words: second}, ...lines!.slice(i + 1)]);
    setSplitting(null);
  };
  const save = () => act.run('save', async () => {
    await api(`/episodes/${episodeId}/audio/lines`, {method: 'PUT', body: {lines: lines!.map(({start, end, text, speaker, words}) => ({start, end, text, speaker, words}))}});
    setDirty(false);
  });
  const applySuggestedLabels = () => {
    const ls = st.cast_suggestion?.line_speakers || {};
    update(lines!.map(l => (ls[l.id] && !l.speaker ? {...l, speaker: ls[l.id]} : l)));
  };
  const speakerOptions = [...new Set([...(lines || []).map(l => l.speaker).filter(Boolean), ...st.characters.map((c: any) => c.key)])];

  return (
    <div className="stack">
      <div className="card stack">
        <div className="spread"><h2 style={{margin: 0}}>Audio</h2>
          <span className="badge good">Rights confirmed · {RIGHTS[st.rights.source] || st.rights.source}</span></div>
        <ErrorBox error={act.error || st.last_error} />
        {st.audio ? <audio ref={player} controls src={st.audio.url} style={{width: '100%'}}
                           onTimeUpdate={e => { if (stopAt.current !== null && e.currentTarget.currentTime >= stopAt.current) { e.currentTarget.pause(); stopAt.current = null; } }} />
          : <p className="muted">No audio uploaded yet.</p>}
        {st.allowed_actions.includes('upload_audio') && <div className="field">
          <label htmlFor="audio-file">{st.audio ? 'Replace the audio (the lines are transcribed again)' : 'Upload the audio file'}</label>
          <input id="audio-file" type="file" accept="audio/*" disabled={!!act.busy}
                 onChange={e => { const f = e.target.files?.[0]; if (f) act.run('upload', async () => { await uploadAudio(`/episodes/${episodeId}/audio`, f); setDirty(false); }); }} />
        </div>}
        {st.stage === 'audio_transcribing' && <div className="alert">Transcribing the audio into timed lines…</div>}
        {st.transcript && <p className="muted small">Transcribed by {st.transcript.provider}{st.transcript.model ? ` (${st.transcript.model})` : ''} · {st.transcript.duration?.toFixed(1)} s ·
          {st.transcript.words_available ? ' word timings' : ' segment timings only (no word-level split)'}
          {st.allowed_actions.includes('transcribe_audio') && st.audio && <> · <button className="btn sm" disabled={!!act.busy} onClick={() => act.run('tr', async () => { await api(`/episodes/${episodeId}/audio/transcribe`, {method: 'POST'}); setDirty(false); })}>Transcribe again</button></>}</p>}
      </div>

      {lines && lines.length > 0 && <div className="card stack">
        <div className="spread"><h2 style={{margin: 0}}>Lines and speakers</h2>
          <div className="row">
            {st.cast_suggestion?.line_speakers && Object.keys(st.cast_suggestion.line_speakers).length > 0 && editable &&
              <button className="btn sm" onClick={applySuggestedLabels}>Fill empty speakers from the AI suggestion</button>}
            {editable && <button className="btn primary" disabled={!dirty || !!act.busy} onClick={save}>{dirty ? 'Save lines' : 'Saved'}</button>}
          </div></div>
        <p className="muted small">Give each line a speaker (any label, or a character key). Split a line where the speaker changes; merge lines one speaker says together. Timing always comes from the audio.</p>
        <datalist id="speaker-options">{speakerOptions.map(s => <option key={s} value={s} />)}</datalist>
        <div className="table-wrap"><table>
          <thead><tr><th>Time</th><th>Speaker</th><th>Line</th><th></th></tr></thead>
          <tbody>{lines.map((l, i) => (
            <tr key={`${l.id}-${i}`}>
              <td className="small" style={{whiteSpace: 'nowrap'}}><button className="btn sm" aria-label={`Play line ${i + 1}`} onClick={() => play(l)}>▶</button> {fmt(l.start)}–{fmt(l.end)}</td>
              <td style={{minWidth: 140}}><input list="speaker-options" value={l.speaker} disabled={!editable} placeholder="who says it" onChange={e => setLine(i, {speaker: e.target.value.slice(0, 40)})} /></td>
              <td>{splitting === i
                ? <div className="small">Split before: {l.words.map((w, k) => <button key={k} className="btn sm" style={{margin: 2}} disabled={k === 0} onClick={() => split(i, k)}>{w.word}</button>)}
                    <button className="btn sm" onClick={() => setSplitting(null)}>Cancel</button></div>
                : <input value={l.text} disabled={!editable} onChange={e => setLine(i, {text: e.target.value})} />}</td>
              <td><div className="row" style={{justifyContent: 'flex-end', flexWrap: 'nowrap'}}>
                {editable && l.words.length > 1 && splitting !== i && <button className="btn sm" onClick={() => setSplitting(i)}>Split</button>}
                {editable && i < lines.length - 1 && <button className="btn sm" onClick={() => merge(i)}>Merge with next</button>}
              </div></td>
            </tr>))}</tbody>
        </table></div>
        {!dirty && st.unlabelled_lines > 0 && <p className="muted small">{st.unlabelled_lines} line(s) have no speaker yet.</p>}
      </div>}

      {st.stage === 'audio_labelling' && <CastCard st={st} episodeId={episodeId} act={act} dirty={dirty} onApplied={() => setDirty(false)} />}
    </div>
  );
}

function CastCard({st, episodeId, act, dirty, onApplied}: {st: any; episodeId: number; act: ReturnType<typeof useAction>; dirty: boolean; onApplied: () => void}) {
  const pending: string[] = st.speakers_without_character;
  const [choices, setChoices] = useState<Record<string, CastChoice>>({});
  const blank = (label: string): CastChoice => ({mode: 'new', character_key: '', new: {key: slug(label), name: label, description: '', visual_description: '', voice_style: '', bubble_style: 'neutral'}});
  const get = (label: string) => choices[label] || blank(label);
  const set = (label: string, c: CastChoice) => setChoices(x => ({...x, [label]: c}));
  const useSuggestion = () => {
    const next: Record<string, CastChoice> = {};
    for (const s of st.cast_suggestion?.speakers || []) {
      if (!pending.includes(s.label)) continue;
      next[s.label] = s.reuse_key ? {mode: 'existing', character_key: s.reuse_key, new: blank(s.label).new}
        : {mode: 'new', character_key: '', new: {key: s.key || slug(s.name || s.label), name: s.name || s.label, description: s.description, visual_description: s.visual_description, voice_style: s.voice_style, bubble_style: s.bubble_style}};
    }
    setChoices(x => ({...x, ...next}));
  };
  const apply = () => act.run('cast', async () => {
    const speakers = pending.map(label => { const c = get(label); return c.mode === 'existing' ? {label, character_key: c.character_key} : {label, new: c.new}; });
    await api(`/episodes/${episodeId}/audio/cast`, {body: {speakers}});
    setChoices({}); onApplied();
  });
  const suggestionBusy = (st.cast_suggestion === undefined || st.cast_suggestion === null) && act.busy === 'suggest';
  return (
    <div className="card stack">
      <div className="spread"><h2 style={{margin: 0}}>Cast</h2>
        <button className="btn" disabled={!!act.busy || suggestionBusy} onClick={() => act.run('suggest', () => api(`/episodes/${episodeId}/audio/suggest-cast`, {method: 'POST'}))}>Suggest the cast (AI writer)</button></div>
      {st.cast_suggestion && <div className="small">
        <strong>AI suggestion</strong> (nothing changes until you apply it):
        <ul>{st.cast_suggestion.speakers.map((s: any) => <li key={s.label}><strong>{s.label}</strong> → {s.reuse_key ? `reuse ${s.reuse_key}` : `${s.name} (${s.key || 'no key'})`}{s.voice_style && <span className="muted"> · voice: {s.voice_style}</span>}{s.description && <span className="muted"> · {s.description}</span>}</li>)}</ul>
        {pending.length > 0 && <button className="btn sm" onClick={useSuggestion}>Use the suggestion below</button>}
      </div>}
      {dirty && <div className="alert">Save the lines first: the cast is built from the saved speaker labels.</div>}
      {!pending.length ? <p className="muted">{st.speakers.length ? 'Every speaker is a character.' : 'Label the lines with speakers first.'}</p> : <>
        <p className="muted small">Each speaker label becomes a character: an existing one, or a new character for this episode (its pose sheet is generated and approved as usual). The uploaded audio is their voice.</p>
        {pending.map(label => { const c = get(label); return (
          <div key={label} className="card stack" style={{padding: 12}}>
            <div className="row"><strong>{label}</strong>
              <select value={c.mode} onChange={e => set(label, {...c, mode: e.target.value as CastChoice['mode']})} style={{width: 'auto'}}>
                <option value="new">New character</option><option value="existing">Existing character</option></select></div>
            {c.mode === 'existing'
              ? <select aria-label={`Character for ${label}`} value={c.character_key} onChange={e => set(label, {...c, character_key: e.target.value})}>
                  <option value="">Choose…</option>{st.characters.map((x: any) => <option key={x.key} value={x.key}>{x.name} ({x.key})</option>)}</select>
              : <div className="grid cols-3">
                  <div><label>Name</label><input value={c.new.name} onChange={e => set(label, {...c, new: {...c.new, name: e.target.value}})} /></div>
                  <div><label>Key</label><input value={c.new.key} onChange={e => set(label, {...c, new: {...c.new, key: slug(e.target.value)}})} /></div>
                  <div><label>Bubble</label><select value={c.new.bubble_style} onChange={e => set(label, {...c, new: {...c.new, bubble_style: e.target.value}})}>
                    <option value="neutral">Neutral</option><option value="him">Rust</option><option value="her">Cream</option></select></div>
                  <div><label>Who they are</label><textarea value={c.new.description} onChange={e => set(label, {...c, new: {...c.new, description: e.target.value}})} /></div>
                  <div><label>How they look</label><textarea value={c.new.visual_description} onChange={e => set(label, {...c, new: {...c.new, visual_description: e.target.value}})} /></div>
                  <div><label>How they sound</label><textarea value={c.new.voice_style} onChange={e => set(label, {...c, new: {...c.new, voice_style: e.target.value}})} /></div>
                </div>}
          </div>); })}
        <div className="row"><button className="btn primary" disabled={dirty || !!act.busy || pending.some(l => { const c = get(l); return c.mode === 'existing' ? !c.character_key : !c.new.key || !c.new.name; })} onClick={apply}>Apply the cast</button></div>
      </>}
    </div>
  );
}
