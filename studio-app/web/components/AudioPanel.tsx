'use client';
import {useEffect, useRef, useState} from 'react';
import {api, isVideoFile, uploadAudio} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from './ui';
import {applyEdit, type Line, type LineEdit} from '@/lib/audioLines';
import {round1, windowError, windowFrom} from '@/lib/trimWindow';

// Audio-first episode, stage 1: the uploaded audio (the voice track), its timed lines, a speaker per line, and the cast.
// The server validates every change (timing inside the audio, in order, no overlaps); this page only prepares it.

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
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [anchor, setAnchor] = useState<number | null>(null);
  const [bulkSpeaker, setBulkSpeaker] = useState('');
  const [hints, setHints] = useState(false);
  const player = useRef<HTMLAudioElement>(null);
  const stopAt = useRef<number | null>(null);

  useEffect(() => {
    if (!st) return;
    setPoll(st.stage === 'audio_transcribing' || st.stage === 'audio_preparing' ? 2500 : 15000);
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
  // split, merge and bulk speaker: a split or merge shifts the rows, so it also clears the selection (lib/audioLines.ts)
  const edit = (e: LineEdit) => {
    const next = applyEdit({lines: lines!, selected}, e);
    if (next.lines !== lines) update(next.lines);
    setSelected(next.selected); setAnchor(null);
  };
  const merge = (i: number) => edit({kind: 'merge', index: i});
  const split = (i: number, w: number) => { edit({kind: 'split', index: i, word: w}); setSplitting(null); };
  // bulk speaker (Stage 1c): click a checkbox, shift-click another to select the range between them
  const toggle = (i: number, shift: boolean) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (shift && anchor !== null) {
        const [a, b] = anchor < i ? [anchor, i] : [i, anchor];
        for (let k = a; k <= b; k++) next.add(k);
      } else if (next.has(i)) next.delete(i); else next.add(i);
      return next;
    });
    setAnchor(i);
  };
  const applyBulk = () => edit({kind: 'speaker', speaker: bulkSpeaker});
  const save = () => act.run('save', async () => {
    await api(`/episodes/${episodeId}/audio/lines`, {method: 'PUT', body: {lines: lines!.map(({start, end, text, speaker, words}) => ({start, end, text, speaker, words}))}});
    setDirty(false); setSelected(new Set());
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
          <label htmlFor="audio-file">{st.audio || st.full_audio ? 'Replace the recording (the lines are transcribed again)' : 'Upload the recording'} (audio up to {st.limits?.audio_mb} MB, or a video up to {st.limits?.video_mb} MB: only its sound is used, the video file is deleted)</label>
          <label className="row" style={{fontWeight: 400, color: 'inherit'}}>
            <input type="checkbox" style={{width: 'auto'}} checked={hints} onChange={e => setHints(e.target.checked)} />
            For a video: use it for casting and setting hints (how many people, the kind of place, the mood; nobody is described; the frames are deleted after)
          </label>
          <input id="audio-file" type="file" accept="audio/*,video/*" disabled={!!act.busy}
                 onChange={e => { const f = e.target.files?.[0]; if (f) act.run('upload', async () => { await uploadAudio(`/episodes/${episodeId}/audio`, f, {hints: hints && isVideoFile(f)}); setDirty(false); setSelected(new Set()); }); }} />
        </div>}
        {!st.transcript && st.audio && st.allowed_actions.includes('transcribe_audio') && st.stage !== 'audio_transcribing' &&
          <p className="small">The audio is ready but not transcribed{st.last_error ? ' (the last attempt failed)' : ''}. <button className="btn sm" disabled={!!act.busy}
            onClick={() => act.run('tr', async () => { await api(`/episodes/${episodeId}/audio/transcribe`, {method: 'POST'}); setDirty(false); setSelected(new Set()); })}>Transcribe</button></p>}
        {st.stage === 'audio_preparing' && <div className="alert">Extracting the audio from the video (the video file is deleted afterwards)…</div>}
        {st.stage === 'audio_transcribing' && <div className="alert">Transcribing the audio into timed lines…</div>}
        {st.source_media && !st.source_media.preparing && <p className="muted small">
          Source: {st.source_media.type === 'video' ? 'the audio track of a video (the video file was deleted; its picture is never used)' : 'an audio file'}
          {st.source_media.duration ? ` · ${round1(st.source_media.duration)} s recorded` : ''}
          {st.trim ? ` · Short window ${round1(st.trim.start)}-${round1(st.trim.end)} s` : ''}</p>}
        {st.media_hints && <p className="small"><b>Hints from the video</b> (frames deleted): {st.media_hints.people_count ?? '?'} people · {st.media_hints.setting || 'place unknown'} · {st.media_hints.mood || 'mood unknown'}</p>}
        {st.source_media?.hints_requested && !st.media_hints && !st.source_media?.preparing && <p className="muted small">Hints from the video: being made…</p>}
        {st.transcript && <p className="muted small">Transcribed by {st.transcript.provider}{st.transcript.model ? ` (${st.transcript.model})` : ''} · {st.transcript.duration?.toFixed(1)} s ·
          {st.transcript.words_available ? ' word timings' : ' segment timings only (no word-level split)'}
          {st.allowed_actions.includes('transcribe_audio') && st.audio && <> · <button className="btn sm" disabled={!!act.busy} onClick={() => act.run('tr', async () => { await api(`/episodes/${episodeId}/audio/transcribe`, {method: 'POST'}); setDirty(false); setSelected(new Set()); })}>Transcribe again</button></>}</p>}
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
        {editable && <div className="row" style={{flexWrap: 'wrap'}}>
          <button className="btn sm" onClick={() => setSelected(new Set(lines.map((_, k) => k)))}>Select all</button>
          <button className="btn sm" disabled={!selected.size} onClick={() => setSelected(new Set())}>Clear selection</button>
          <span className="muted small">{selected.size} selected (shift-click selects a range)</span>
          <input list="speaker-options" aria-label="Speaker for the selected lines" style={{width: 180}} value={bulkSpeaker} placeholder="speaker" onChange={e => setBulkSpeaker(e.target.value)} />
          <button className="btn sm" disabled={!selected.size || !bulkSpeaker.trim()} onClick={applyBulk}>Set speaker for selected</button>
        </div>}
        <div className="table-wrap"><table>
          <thead><tr>{editable && <th></th>}<th>Time</th><th>Speaker</th><th>Line</th><th></th></tr></thead>
          <tbody>{lines.map((l, i) => (
            <tr key={`${l.id}-${i}`}>
              {editable && <td><input type="checkbox" style={{width: 'auto'}} aria-label={`Select line ${i + 1}`} checked={selected.has(i)}
                                      onChange={() => {}} onClick={e => toggle(i, (e as any).shiftKey)} /></td>}
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

      {st.format === 'short' && st.full_audio && (st.needs_trim || st.allowed_actions.includes('trim_audio')) &&
        <TrimCard st={st} episodeId={episodeId} act={act} hasLines={!!lines?.length} onApplied={() => { setDirty(false); setSelected(new Set()); }} />}
      {st.stage === 'audio_labelling' && <LineQuality st={st} episodeId={episodeId} act={act} dirty={dirty} onApplied={() => { setDirty(false); setSelected(new Set()); }} />}

      {st.stage === 'audio_labelling' && <CastCard st={st} episodeId={episodeId} act={act} dirty={dirty} onApplied={() => setDirty(false)} />}
    </div>
  );
}

// A Short uses at most 60 s of the recording: the owner picks the window on the whole recording (kept for this).
function TrimCard({st, episodeId, act, hasLines, onApplied}: {st: any; episodeId: number; act: ReturnType<typeof useAction>; hasLines: boolean; onApplied: () => void}) {
  const max = st.window_seconds || 60, duration: number | null = st.source_media?.duration ?? null;
  const [start, setStart] = useState<number>(st.trim?.start ?? 0);
  const [end, setEnd] = useState<number>(st.trim?.end ?? windowFrom(0, duration, max).end);
  const player = useRef<HTMLAudioElement>(null);
  const err = windowError(start, end, duration, max);
  const here = () => round1(player.current?.currentTime ?? 0);
  const apply = () => {
    if (hasLines && !window.confirm('A new window is transcribed again: the current lines and speaker labels start over. Continue?')) return;
    act.run('trim', async () => { await api(`/episodes/${episodeId}/audio/trim`, {body: {start, end}}); onApplied(); });
  };
  return (
    <div className="card stack">
      <h2 style={{margin: 0}}>The Short's {max} s window</h2>
      {st.needs_trim && <div className="alert">The recording runs {round1(duration ?? 0)} s. A Short uses at most {max} s: choose the window, then it is transcribed.</div>}
      <audio ref={player} controls src={st.full_audio.url} style={{width: '100%'}} />
      <div className="row" style={{flexWrap: 'wrap'}}>
        <label className="row small">Start (s) <input type="number" min={0} step={0.1} style={{width: 90}} value={start} onChange={e => setStart(Number(e.target.value))} /></label>
        <button className="btn sm" onClick={() => { const w = windowFrom(here(), duration, max); setStart(w.start); setEnd(w.end); }}>Start here</button>
        <label className="row small">End (s) <input type="number" min={0} step={0.1} style={{width: 90}} value={end} onChange={e => setEnd(Number(e.target.value))} /></label>
        <button className="btn sm" onClick={() => setEnd(here())}>End here</button>
        <span className="muted small">{Number.isFinite(end - start) ? `${round1(end - start)} s` : ''}</span>
        <button className="btn primary" disabled={!!err || !!act.busy} onClick={apply}>Use this window</button>
      </div>
      {err && <p className="small" style={{color: 'var(--bad, #b00)'}}>{err}</p>}
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

// Stage 1c: re-split lines at natural beats (proposal only until applied; one-click Undo), and a cut-off last line.
function LineQuality({st, episodeId, act, dirty, onApplied}: {st: any; episodeId: number; act: ReturnType<typeof useAction>; dirty: boolean; onApplied: () => void}) {
  const [cues, setCues] = useState<string>((st.cues || []).join(', '));
  const [prop, setProp] = useState<any | null>(null);
  const [edit, setEdit] = useState<Line[]>([]);
  useEffect(() => { if (!prop) setCues((st.cues || []).join(', ')); }, [st.cues, prop]);
  const propose = () => act.run('propose', async () => {
    const p = await api(`/episodes/${episodeId}/audio/normalise`, {body: {cues: cues.split(',').map(c => c.trim()).filter(Boolean)}});
    setProp(p); setEdit(p.proposal);
  });
  const apply = () => act.run('apply', async () => {
    await api(`/episodes/${episodeId}/audio/lines`, {method: 'PUT', body: {keep_previous: true,
      lines: edit.map(({start, end, text, speaker, words}) => ({start, end, text, speaker, words}))}});
    setProp(null); onApplied();
  });
  const undo = () => act.run('undo', async () => { await api(`/episodes/${episodeId}/audio/lines/undo`, {method: 'POST'}); onApplied(); });
  const fragment = (action: 'end_before' | 'keep') => act.run('fragment', async () => {
    await api(`/episodes/${episodeId}/audio/fragment`, {body: {action}}); onApplied();
  });
  const mergeNext = (i: number) => {
    const a = edit[i], b = edit[i + 1];
    if (!b || a.speaker !== b.speaker) return;
    setEdit([...edit.slice(0, i), {...a, end: b.end, text: `${a.text} ${b.text}`.trim(), words: [...a.words, ...b.words]}, ...edit.slice(i + 2)]);
  };
  const before = new Set((prop?.current || []).map((l: Line) => l.text));
  return (
    <div className="card stack">
      <div className="spread"><h2 style={{margin: 0}}>Tidy lines</h2>
        {st.can_undo && <button className="btn sm" disabled={!!act.busy} onClick={undo}>Undo last tidy</button>}</div>
      {st.fragment && <div className="alert">
        The last line looks cut off: <strong>“{st.fragment.text}”</strong> ({st.fragment.reasons.join('; ')}).
        <div className="row" style={{marginTop: 8}}>
          <button className="btn sm" disabled={!!act.busy || dirty} onClick={() => fragment('end_before')}>End the episode before this line</button>
          <button className="btn sm" disabled={!!act.busy || dirty} onClick={() => fragment('keep')}>Keep it</button>
        </div></div>}
      <p className="muted small">Re-splits the lines at natural beats: sentence ends, the cue phrases below, and pauses (0.4 s at punctuation, 1 s anywhere). Nothing changes until you apply the proposal.</p>
      <div className="row">
        <input aria-label="Cue phrases" value={cues} onChange={e => setCues(e.target.value)} placeholder="cue phrases, comma separated (e.g. To my, I leave)" />
        <button className="btn" disabled={!!act.busy || dirty} onClick={propose}>Propose</button>
      </div>
      {dirty && <p className="muted small">Save your line edits first: the proposal starts from the saved lines.</p>}
      {prop && <>
        {!prop.changed && <p className="muted">The lines already follow these beats.</p>}
        <div className="grid cols-2">
          <div><h3>Before ({prop.current.length} lines)</h3>
            <ol className="small">{prop.current.map((l: Line) => <li key={l.id}>{l.text}</li>)}</ol></div>
          <div><h3>After ({edit.length} lines)</h3>
            <ol className="small">{edit.map((l, i) => (
              <li key={`${l.id}-${i}`} style={{marginBottom: 4}}>
                <input value={l.text} aria-label={`Proposed line ${i + 1}`} style={before.has(l.text) ? undefined : {borderColor: '#c2531b'}}
                       onChange={e => setEdit(edit.map((x, k) => (k === i ? {...x, text: e.target.value} : x)))} />
                <span className="muted"> {l.speaker || 'no speaker'}</span>
                {i < edit.length - 1 && edit[i + 1].speaker === l.speaker && <button className="btn sm" style={{marginLeft: 6}} onClick={() => mergeNext(i)}>Merge with next</button>}
              </li>))}</ol></div>
        </div>
        <p className="muted small">Changed lines are outlined. Edit the text or merge lines here; speakers and timing come from the audio.</p>
        <div className="row">
          <button className="btn primary" disabled={!!act.busy} onClick={apply}>Apply</button>
          <button className="btn" onClick={() => setProp(null)}>Discard</button>
        </div>
      </>}
    </div>
  );
}
