'use client';
// The reaction sheet and the shot list of a storyboard scene (2026-11-24), beside "Expressions per line": per line, each
// listener's reaction beats (the word they react to, an approved expression, the head move and its strength, the
// reason); per scene, the shots (start and end on the recording, the type, the camera in words, who is on screen,
// whose shoulder). Plain data, the same for every renderer; only the storyboard changes, never the script or its
// approval. Audio episodes only: everything is timed on the recording's words.
import {useEffect, useMemo, useState} from 'react';
import {api} from '@/lib/api';
import {useApi} from '@/lib/hooks';
import {usableExpressions} from '@/lib/lineExpressions';
import {MOVES, SHOT_TYPES, STRENGTHS, beatForServer, beatTime, newBeat, newShot, sceneSpan, shotsProblem, wordLabel, wordsOf,
  type Beat, type Shot, type Word} from '@/lib/reactionSheet';

const STAGES = ['storyboard_review', 'storyboard_approved', 'production_failed', 'video_review'];

export default function ReactionSheet({ep, scene, characters, act}: {ep: any; scene: any; characters: any[]; act: any}) {
  const audio = ep.source === 'audio';
  const {data: st} = useApi<any>(audio ? `/episodes/${ep.id}/audio` : null);
  if (!audio || !(scene.lines || []).length) return null;
  const editable = STAGES.includes(ep.stage) && !act.busy;
  const index = ep.scenes.findIndex((s: any) => s.id === scene.id);
  const span = sceneSpan(ep.scenes, index, st?.transcript?.duration);
  const everyone: string[] = ep.scenes.flatMap((s: any) => [...(s.characters || []),
    ...(s.lines || []).flatMap((l: any) => [l.speaker, ...(l.reactions || []).map((r: any) => r.character)])]);
  const cast = Array.from(new Set(everyone)).filter(Boolean);
  const name = (k: string) => characters.find(c => c.key === k)?.name || k;
  return (
    <>
      <details className="small"><summary>Reactions per line (the reaction sheet)</summary>
        <div className="stack" style={{marginTop: 6}}>
          <span className="muted">Each listener's beats: the word they react to, an approved expression, the head move and why.
            Saved on the storyboard only; the script and its approval stay as they are.</span>
          {!st && <span className="muted">Loading the recording's word timings…</span>}
          {st && scene.lines.map((ln: any, li: number) => (
            <LineReactions key={li} ep={ep} scene={scene} line={ln} li={li} words={wordsOf(st.lines, ln.line_id)}
              listeners={cast.filter(k => k !== ln.speaker)} characters={characters} name={name} editable={editable} act={act} />))}
        </div></details>
      <details className="small"><summary>Shots ({(scene.shots || []).length || 'none yet'})</summary>
        <ShotList ep={ep} scene={scene} span={span} cast={cast} name={name} editable={editable} act={act} />
      </details>
    </>);
}

function LineReactions({ep, scene, line, li, words, listeners, characters, name, editable, act}: {ep: any; scene: any; line: any; li: number;
  words: Word[]; listeners: string[]; characters: any[]; name: (k: string) => string; editable: boolean; act: any}) {
  const reacting = (line.reactions || []).map((r: any) => r.character);
  const [adding, setAdding] = useState('');
  const others = listeners.filter(k => !reacting.includes(k));
  const label = `${li + 1}. “${String(line.text || '').slice(0, 48)}${String(line.text || '').length > 48 ? '…' : ''}”`;
  return (
    <div className="card" style={{padding: 8}}>
      <div className="spread"><b>{label}</b>
        <span className="muted">{name(line.speaker)} speaks{typeof line.start === 'number' ? ` · ${line.start.toFixed(2)}-${line.end.toFixed(2)} s` : ''}</span></div>
      {!words.length && <span className="muted">No word timings for this line: beats need the recording's words.</span>}
      {words.length > 0 && (line.reactions || []).map((r: any) => (
        <BeatRows key={r.character} ep={ep} scene={scene} li={li} character={r.character} saved={r.beats || []} words={words}
          usable={usableExpressions(characters.find(c => c.key === r.character))} name={name} editable={editable} act={act} />))}
      {words.length > 0 && others.length > 0 && (line.reactions || []).length < 3 && (
        <div className="row" style={{gap: 6, marginTop: 4}}>
          <select aria-label={`line ${li + 1} add a listener`} style={{width: 'auto'}} value={adding} disabled={!editable}
            onChange={e => setAdding(e.target.value)}>
            <option value="">Add a listener…</option>{others.map(k => <option key={k} value={k}>{name(k)}</option>)}
          </select>
          <button className="btn sm" disabled={!editable || !adding} onClick={() => act.run(`rx-${li}`, () =>
            api(`/episodes/${ep.id}/scenes/${scene.id}/lines/${li}/reactions`, {method: 'PUT', body: {character: adding, beats: [newBeat(words)]}})
              .then(() => setAdding('')))}>Add</button>
        </div>)}
    </div>);
}

function BeatRows({ep, scene, li, character, saved, words, usable, name, editable, act}: {ep: any; scene: any; li: number; character: string;
  saved: Beat[]; words: Word[]; usable: string[]; name: (k: string) => string; editable: boolean; act: any}) {
  const key = JSON.stringify(saved);
  const [beats, setBeats] = useState<Beat[]>(saved);
  useEffect(() => { setBeats(saved); }, [key]);   // eslint-disable-line react-hooks/exhaustive-deps
  const changed = JSON.stringify(beats) !== key;
  const put = (i: number, patch: Partial<Beat>) => setBeats(beats.map((b, j) => (j === i ? {...b, ...patch} : b)));
  const save = () => act.run(`rx-${li}-${character}`, () => api(`/episodes/${ep.id}/scenes/${scene.id}/lines/${li}/reactions`,
    {method: 'PUT', body: {character, beats: beats.map(beatForServer)}}));
  return (
    <div className="stack" style={{gap: 4, marginTop: 6}}>
      <div className="row" style={{gap: 8}}><b>{name(character)}</b>
        <span className="muted">{beats.length ? `${beats.length} beat(s)` : 'no beats: the line\'s own reaction only'}</span></div>
      {beats.map((b, i) => {
        const t = beatTime(b, words);
        return (
          <div key={i} className="row" style={{gap: 6, flexWrap: 'wrap'}}>
            <select aria-label={`${name(character)} beat ${i + 1} word`} style={{width: 'auto'}} value={b.word} disabled={!editable}
              onChange={e => put(i, {word: Number(e.target.value), t: undefined, estimated: undefined})}>
              {words.map((w, wi) => <option key={wi} value={wi}>{wordLabel(w, wi)}</option>)}
            </select>
            <label className="row small" style={{gap: 4}}>at
              <input aria-label={`${name(character)} beat ${i + 1} time`} type="number" step="0.01" style={{width: 80}} disabled={!editable}
                value={t ?? ''} onChange={e => put(i, {t: e.target.value === '' ? undefined : Number(e.target.value)})} /> s</label>
            <select aria-label={`${name(character)} beat ${i + 1} expression`} style={{width: 'auto'}} value={b.expression} disabled={!editable}
              onChange={e => put(i, {expression: e.target.value})}>
              {!usable.includes(b.expression) && <option value={b.expression}>{b.expression} (not approved)</option>}
              {usable.map(x => <option key={x} value={x}>{x}</option>)}
            </select>
            <select aria-label={`${name(character)} beat ${i + 1} move`} style={{width: 'auto'}} value={b.move} disabled={!editable}
              onChange={e => put(i, {move: e.target.value})}>{MOVES.map(m => <option key={m} value={m}>{m.replace('_', ' ')}</option>)}</select>
            <select aria-label={`${name(character)} beat ${i + 1} strength`} style={{width: 'auto'}} value={b.strength} disabled={!editable}
              onChange={e => put(i, {strength: e.target.value})}>{STRENGTHS.map(m => <option key={m} value={m}>{m}</option>)}</select>
            <input aria-label={`${name(character)} beat ${i + 1} reason`} placeholder="why (from what is said)" maxLength={160}
              style={{flex: 1, minWidth: 180}} value={b.reason} disabled={!editable} onChange={e => put(i, {reason: e.target.value})} />
            {b.estimated && <span className="badge warn" title="the transcript timed this word badly: the time was set by hand">estimated</span>}
            <button className="btn sm" disabled={!editable} onClick={() => setBeats(beats.filter((_, j) => j !== i))}>Remove</button>
          </div>);
      })}
      <div className="row" style={{gap: 6}}>
        <button className="btn sm" disabled={!editable || beats.length >= 12} onClick={() => setBeats([...beats, newBeat(words, beats[beats.length - 1])])}>Add a beat</button>
        <button className="btn sm primary" disabled={!editable || !changed} onClick={save}>Save {name(character)}'s beats</button>
        {changed && <button className="btn sm" onClick={() => setBeats(saved)}>Undo changes</button>}
      </div>
    </div>);
}

function ShotList({ep, scene, span, cast, name, editable, act}: {ep: any; scene: any; span: [number, number]; cast: string[];
  name: (k: string) => string; editable: boolean; act: any}) {
  const saved: Shot[] = useMemo(() => scene.shots || [], [scene.shots]);
  const key = JSON.stringify(saved);
  const [shots, setShots] = useState<Shot[]>(saved);
  useEffect(() => { setShots(saved); }, [key]);   // eslint-disable-line react-hooks/exhaustive-deps
  const changed = JSON.stringify(shots) !== key;
  const problem = shotsProblem(shots);
  const put = (i: number, patch: Partial<Shot>) => setShots(shots.map((s, j) => (j === i ? {...s, ...patch} : s)));
  const save = () => act.run(`shots-${scene.id}`, () => api(`/episodes/${ep.id}/scenes/${scene.id}/shots`, {method: 'PUT', body: {shots}}));
  return (
    <div className="stack" style={{gap: 6, marginTop: 6}}>
      <span className="muted">This scene runs {span[0].toFixed(2)}-{span[1].toFixed(2)} s on the recording. Shots run in order and do not
        overlap; the camera is described in words.</span>
      {shots.length > 0 && <div className="table-wrap"><table><thead><tr>
        <th>#</th><th>Start (s)</th><th>End (s)</th><th>Shot</th><th>Camera</th><th>On screen</th><th>Over the shoulder of</th><th /></tr></thead>
        <tbody>{shots.map((s, i) => (
          <tr key={i}>
            <td>{i + 1}</td>
            <td><input aria-label={`shot ${i + 1} start`} type="number" step="0.01" style={{width: 80}} value={s.start} disabled={!editable}
              onChange={e => put(i, {start: Number(e.target.value)})} /></td>
            <td><input aria-label={`shot ${i + 1} end`} type="number" step="0.01" style={{width: 80}} value={s.end} disabled={!editable}
              onChange={e => put(i, {end: Number(e.target.value)})} /></td>
            <td><select aria-label={`shot ${i + 1} type`} style={{width: 'auto'}} value={s.type} disabled={!editable}
              onChange={e => put(i, {type: e.target.value})}>{SHOT_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></td>
            <td><input aria-label={`shot ${i + 1} camera`} maxLength={120} placeholder="e.g. from Mortimer's side" value={s.camera} disabled={!editable}
              onChange={e => put(i, {camera: e.target.value})} /></td>
            <td><div className="row" style={{gap: 6, flexWrap: 'wrap'}}>{cast.map(k => (
              <label key={k} className="row small" style={{gap: 3}}><input type="checkbox" disabled={!editable} checked={s.on_screen.includes(k)}
                onChange={e => put(i, {on_screen: e.target.checked ? [...s.on_screen, k] : s.on_screen.filter(x => x !== k)})} />{name(k)}</label>))}
            </div></td>
            <td><select aria-label={`shot ${i + 1} over the shoulder of`} style={{width: 'auto'}} value={s.over_shoulder_of || ''} disabled={!editable}
              onChange={e => put(i, {over_shoulder_of: e.target.value || undefined})}>
              <option value="">—</option>{cast.map(k => <option key={k} value={k}>{name(k)}</option>)}</select></td>
            <td><button className="btn sm" disabled={!editable} onClick={() => setShots(shots.filter((_, j) => j !== i))}>Remove</button></td>
          </tr>))}</tbody></table></div>}
      {problem && <div className="alert warn small">{problem}</div>}
      <div className="row" style={{gap: 6}}>
        <button className="btn sm" disabled={!editable || shots.length >= 40} onClick={() => setShots([...shots, newShot(shots[shots.length - 1], span[0], cast)])}>Add a shot</button>
        <button className="btn sm primary" disabled={!editable || !changed || !!problem} onClick={save}>Save shots</button>
        {changed && <button className="btn sm" onClick={() => setShots(saved)}>Undo changes</button>}
      </div>
    </div>);
}
