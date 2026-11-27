'use client';
// Characters on the episode page, right after Lines and speakers (2026-11-27): each speaker label becomes a character
// (a saved one from your cast library for free, an existing character, or a new one for this episode), then the Cast
// step (the same component as guided step 4: descriptions from the video in words, style previews, candidates,
// approval, "save to my cast library" or "this episode only") makes each master. Nothing is chosen or approved for you.
import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from './ui';
import GuideCast from './GuideCast';
import {choiceValue, choicesBody, type SpeakerRow} from '@/lib/speakerCast';

export default function EpisodeCharacters({id, onChange}: {id: string | number; onChange?: () => unknown}) {
  const {data: v, reload} = useApi<any>(`/episodes/${id}/speaker-cast`, 15000);
  const act = useAction(async () => { await reload(); await onChange?.(); });
  const [pick, setPick] = useState<Record<string, string>>({});
  const rows: SpeakerRow[] = v?.speakers || [];
  useEffect(() => { setPick({}); }, [JSON.stringify(rows.map(r => r.label))]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!v) return <p className="small muted">Loading…</p>;
  const apply = () => act.run('speaker-cast', () => api(`/episodes/${id}/speaker-cast`, {body: {choices: choicesBody(rows, pick)}}));
  return (
    <div className="stack">
      <ErrorBox error={act.error} />
      {v.unlabelled_lines > 0 && <p className="small">{v.unlabelled_lines} line(s) still have no speaker. Give them one in Lines and speakers (try &ldquo;Suggest speakers&rdquo;).</p>}
      {rows.length > 0 && <div className="card stack">
        <strong>Make the speakers characters (free)</strong>
        <p className="small muted">Each speaker label becomes a character. A saved character from your cast library is used as it is, with its approved master (free).</p>
        <div className="table-wrap"><table>
          <thead><tr><th>Speaker</th><th>Lines</th><th>Character</th></tr></thead>
          <tbody>{rows.map(r => (
            <tr key={r.label}>
              <td>{r.label}</td><td className="small">{r.lines}</td>
              <td><select aria-label={`Character for ${r.label}`} value={pick[r.label] ?? choiceValue(r.proposal)}
                onChange={e => setPick(p => ({...p, [r.label]: e.target.value}))}>
                <option value="new">New character for this episode: {r.label}</option>
                {(v.library || []).map((e: any) => <option key={e.id} value={`library:${e.id}`}>From my cast library: {e.name} ({e.style_label}, free)</option>)}
                {(v.characters || []).map((c: any) => <option key={c.key} value={`existing:${c.key}`}>Existing character: {c.name}</option>)}
              </select></td>
            </tr>))}</tbody>
        </table></div>
        <div className="row"><button className="btn primary" disabled={!!act.busy || !v.can_apply} onClick={apply}>Make these characters</button>
          {!v.can_apply && <span className="small muted">Possible while the lines are being labelled.</span>}</div>
      </div>}
      <GuideCast id={String(id)} onChange={async () => { await reload(); await onChange?.(); }} />
    </div>);
}
