'use client';
// The owner's cast library: characters saved when their master was approved ("Save to my cast library"). Each shows
// its style and locked master; it can be renamed or removed. Removing only takes it out of the library: the character
// and every master version stay, so an episode that uses it keeps working. Reuse happens in an episode's Cast step (free).
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';

export default function CastLibrary() {
  const {data, error, reload} = useApi<any>('/cast/library');
  const act = useAction(reload);
  if (!data) return error ? <ErrorBox error={error} /> : null;
  const entries: any[] = data.entries || [];
  const rename = (e: any) => {
    const name = window.prompt('New name', e.name);
    if (name && name.trim() && name !== e.name) act.run(`n${e.id}`, () => api(`/cast/library/${e.id}`, {method: 'PUT', body: {name: name.trim()}}));
  };
  const remove = (e: any) => {
    const used = e.used_by?.length ? ` It is used by episode(s) ${e.used_by.join(', ')}; they keep it.` : '';
    if (window.confirm(`Remove ${e.name} from your cast library? The character and its masters are kept.${used}`))
      act.run(`d${e.id}`, () => api(`/cast/library/${e.id}`, {method: 'DELETE'}));
  };
  return (
    <section className="card stack" style={{padding: 12}} aria-label="Cast library">
      <h2 style={{margin: 0}}>Cast library</h2>
      <p className="small muted" style={{margin: 0}}>Characters you saved when approving their master. Use them in a new episode from
        its guided step 4 (Cast) at no cost: their locked master is used as it is.</p>
      <ErrorBox error={act.error} />
      {entries.length === 0 && <p className="small muted">No saved characters yet.</p>}
      <div className="row" style={{flexWrap: 'wrap', gap: 10, alignItems: 'stretch'}}>
        {entries.map(e => (
          <div key={e.id} className="card stack" style={{padding: 8, width: 180, gap: 6}}>
            {e.master_url && <img src={e.master_url} alt={`${e.name}: master`} style={{width: '100%', borderRadius: 4}} />}
            <strong>{e.name}</strong>
            <span className="small muted">{e.style_label} · {e.versions} version{e.versions === 1 ? '' : 's'}
              {e.used_by?.length ? ` · episode ${e.used_by.join(', ')}` : ''}</span>
            <span className="row">
              <button className="btn sm" disabled={!!act.busy} onClick={() => rename(e)}>Rename</button>
              <button className="btn sm danger" disabled={!!act.busy} onClick={() => remove(e)}>Remove</button></span>
          </div>))}
      </div>
    </section>);
}
