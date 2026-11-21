'use client';
// The Bin: deleted items, hidden everywhere, restorable for 30 days. "Delete forever" and "Empty Bin" remove the
// database records and files after a confirm listing exactly what goes and the space freed. Items older than 30 days
// are purged by the weekly maintenance.
import {api, when} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import {foreverText, formatBytes} from '@/lib/binView';

export default function Bin() {
  const {data, error, reload} = useApi<any>('/bin', 10000);
  const act = useAction(reload);
  const items: any[] = data?.items || [];
  const forever = (ids: number[] | null) => act.run('forever', async () => {
    const p: any = await api('/bin/forever', {body: ids ? {ids, confirm: false} : {all: true, confirm: false}});
    if (!p.count) return;
    if (window.confirm(foreverText(p.items, p.bytes))) await api('/bin/forever', {body: ids ? {ids, confirm: true} : {all: true, confirm: true}});
  });
  return (
    <>
      <div className="spread"><div><h1>Bin</h1><p className="sub">Deleted characters, poses, sets, episodes and comparison clips. They are hidden everywhere and can be restored for {data?.keep_days ?? 30} days; after that the weekly maintenance removes them for good.</p></div>
        {items.length > 0 && <button className="btn danger" disabled={!!act.busy} onClick={() => forever(null)}>Empty Bin ({formatBytes(data.total_bytes)})</button>}</div>
      <ErrorBox error={error || act.error} />
      {!items.length && <p className="muted">The Bin is empty.</p>}
      {items.length > 0 && <div className="table-wrap"><table>
        <thead><tr><th>Item</th><th>Kind</th><th>Size</th><th>Deleted</th><th>Purged in</th><th></th></tr></thead>
        <tbody>{items.map(b => (
          <tr key={b.id}>
            <td>{b.label}</td><td>{b.kind}</td><td>{formatBytes(b.size_bytes)} ({b.files} file(s))</td>
            <td className="small">{when(b.deleted_at)} by {b.deleted_by}</td><td className="small">{b.days_left} day(s)</td>
            <td className="row" style={{gap: 4}}>
              <button className="btn sm" disabled={!!act.busy} onClick={() => act.run('restore', async () => {
                const r: any = await api(`/bin/${b.id}/restore`, {method: 'POST'});
                if (r.warning) window.alert(`Restored ${r.restored}. Note: ${r.warning}.`);
              })}>Restore</button>
              <button className="btn sm danger" disabled={!!act.busy} onClick={() => forever([b.id])}>Delete forever</button></td>
          </tr>))}</tbody></table></div>}
    </>);
}
