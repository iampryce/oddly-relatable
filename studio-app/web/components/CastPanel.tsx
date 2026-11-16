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
  const missing = data.filter(c => !c.locked && (c.missing_expressions?.length || c.art_status !== 'approved'));
  return (
    <div className="card stack">
      <div className="spread"><h2 style={{margin: 0}}>Cast</h2>
        {missing.length > 0 && <button className="btn primary" disabled={!!act.busy} onClick={() => act.run('gen', () => api(`/episodes/${episodeId}/cast/generate`, {method: 'POST'}))}>Generate missing pose sheets</button>}</div>
      <ErrorBox error={act.error} />
      <div className="table-wrap"><table>
        <thead><tr><th>Character</th><th>Art</th><th>Expressions needed</th><th>Voice</th></tr></thead>
        <tbody>{data.map(c => (
          <tr key={c.key}>
            <td>{c.missing ? <span className="badge bad">{c.key}: not in the studio</span> : <Link href="/characters">{c.name}</Link>}
              {c.scope === 'episode' && <span className="badge" style={{marginLeft: 6}}>new in this story</span>}</td>
            <td><span className={`badge ${c.art_status === 'approved' ? 'good' : c.art_status === 'none' ? 'bad' : 'warn'}`}>{c.locked ? 'approved (locked)' : c.art_status}</span>
              {c.awaiting_review > 0 && <span className="muted small"> · {c.awaiting_review} to review</span>}</td>
            <td className="small">{(c.needed || []).map((e: string) => <span key={e} className={`badge ${c.missing_expressions?.includes(e) ? 'warn' : 'good'}`} style={{marginRight: 4}}>{e}</span>)}</td>
            <td className="small">{c.voice || <span className="muted">default</span>}</td>
          </tr>))}</tbody>
      </table></div>
      {missing.length > 0 && <p className="muted small">Production stays blocked until every character on screen has approved poses. Expressions without their own pose fall back to the closest approved one.</p>}
    </div>
  );
}
