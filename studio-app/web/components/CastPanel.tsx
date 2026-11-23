'use client';
import Link from 'next/link';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from './ui';

// Who this episode's script needs and whether each character can be animated. Story-introduced characters get their
// expression sheets generated here (owner-started) and approved under Characters.
export default function CastPanel({episodeId, onChange}: {episodeId: number; onChange?: () => unknown}) {
  const {data, error, reload} = useApi<any[]>(`/episodes/${episodeId}/cast`, 6000);
  const act = useAction(async () => { await reload(); await onChange?.(); });
  if (!data) return error ? <ErrorBox error={error} /> : null;
  // only a character without approved art blocks; an expression without its own pose uses the nearest approved one
  const missing = data.filter(c => c.missing || (!c.locked && c.art_status !== 'approved'));
  const optional = data.filter(c => !c.locked && !c.missing && c.art_status === 'approved' && c.missing_expressions?.length);
  return (
    <div className="card stack">
      <div className="spread"><h2 style={{margin: 0}}>Cast</h2>
        {(missing.length > 0 || optional.length > 0) && <button className={`btn ${missing.length ? 'primary' : ''}`} disabled={!!act.busy}
          onClick={() => act.run('gen', () => api(`/episodes/${episodeId}/cast/generate`, {method: 'POST'}))}>{missing.length ? 'Generate missing pose sheets' : 'Draw the missing expressions (optional)'}</button>}</div>
      <ErrorBox error={act.error} />
      <div className="table-wrap"><table>
        <thead><tr><th>Character</th><th>Art</th><th>Expressions used</th><th>Voice</th></tr></thead>
        <tbody>{data.map(c => (
          <tr key={c.key}>
            <td>{c.missing ? <span className="badge bad">{c.key}: not in the studio</span> : <Link href="/characters">{c.name}</Link>}
              {c.scope === 'episode' && <span className="badge" style={{marginLeft: 6}}>new in this story</span>}</td>
            <td><span className={`badge ${c.art_status === 'approved' ? 'good' : c.art_status === 'none' ? 'bad' : 'warn'}`}>{c.locked ? 'approved (locked)' : c.art_status}</span>
              {c.awaiting_review > 0 && <span className="muted small"> · {c.awaiting_review} to review</span>}</td>
            <td className="small">{(c.needed || []).map((e: string) => <span key={e} className={`badge ${c.missing_expressions?.includes(e) ? '' : 'good'}`} style={{marginRight: 4}}
              title={c.fallbacks?.[e] ? `no ${e} pose: the ${c.fallbacks[e]} pose is used` : ''}>{c.fallbacks?.[e] ? `${e} → ${c.fallbacks[e]}` : e}</span>)}</td>
            <td className="small">{c.voice || <span className="muted">default</span>}</td>
          </tr>))}</tbody>
      </table></div>
      {missing.length > 0 && <p className="muted small">Production stays blocked until every character on screen has approved art.</p>}
      {optional.length > 0 && <p className="muted small">Expressions without their own pose use the nearest approved one (shown as "wanted → used"); this never blocks the episode. Change a line's expression in the Storyboard (Expressions per line).</p>}
    </div>
  );
}
