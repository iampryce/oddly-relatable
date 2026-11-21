'use client';
// Delete = move to the Bin (restorable for 30 days). The studio checks first whether the item may go (anything another
// episode still uses, locked artwork and rendered or published episodes are refused, with the reason), then asks.
import {useState} from 'react';
import {api} from '@/lib/api';
import {formatBytes} from '@/lib/binView';

export function DeleteButton({kind, id, label, onDone, small = true}: {kind: string; id: string | number; label: string; onDone?: () => unknown; small?: boolean}) {
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      const c: any = await api(`/bin/check?kind=${kind}&ref=${encodeURIComponent(String(id))}`);
      if (!c.allowed) { window.alert(`${label} cannot be deleted: ${c.reason}.`); return; }
      if (!window.confirm(`Move ${label} to the Bin (${c.files} file(s), ${formatBytes(c.size_bytes)})? It is hidden everywhere and can be restored for 30 days.`)) return;
      await api('/bin/move', {body: {kind, ref: String(id)}});
      await onDone?.();
    } catch (e: any) { window.alert(e.message); } finally { setBusy(false); }
  };
  return <button type="button" className={`btn ${small ? 'sm' : ''} danger`} disabled={busy} onClick={go}>Delete</button>;
}

// A bulk action: shows the list and the count before anything moves to the Bin.
export function BulkDelete({what, label, onDone}: {what: 'poses' | 'sets' | 'episodes'; label: string; onDone?: () => unknown}) {
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      const p: any = await api(`/bin/bulk/${what}`, {body: {confirm: false}});
      const kept = p.kept?.length ? `\n\nKept (still in use):\n${p.kept.slice(0, 10).join('\n')}` : '';
      if (!p.count) { window.alert(`Nothing to delete.${kept}`); return; }
      const list = p.items.slice(0, 25).map((x: any) => `• ${x.label}`).join('\n') + (p.count > 25 ? `\n… and ${p.count - 25} more` : '');
      if (!window.confirm(`${label}: move these ${p.count} item(s) (${formatBytes(p.bytes)}) to the Bin? Restorable for 30 days.\n\n${list}${kept}`)) return;
      await api(`/bin/bulk/${what}`, {body: {confirm: true}});
      await onDone?.();
    } catch (e: any) { window.alert(e.message); } finally { setBusy(false); }
  };
  return <button type="button" className="btn sm" disabled={busy} onClick={go}>{label}</button>;
}
