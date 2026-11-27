'use client';
// For an episode whose style is not the stick man: automatic head finding looks for white round stick heads, so the
// owner clicks each head once on the picture (left to right as seated). Free; saved with PUT /owner-heads/<asset>.
import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {useApi} from '@/lib/hooks';

type Head = {x: number; y: number; r: number};

export default function HeadClicker({episodeId, assetId, url, onSaved}: {episodeId: string; assetId: number; url?: string | null;
  onSaved?: () => unknown}) {
  const {data, reload} = useApi<any>(`/episodes/${episodeId}/owner-heads/${assetId}`);
  const [heads, setHeads] = useState<Head[]>([]);
  const [size, setSize] = useState<[number, number] | null>(null);
  const [msg, setMsg] = useState('');
  useEffect(() => { setHeads(data?.heads || []); }, [data]);
  if (!url) return null;
  const click = (e: React.MouseEvent<HTMLImageElement>) => {
    if (!size) return;
    const b = e.currentTarget.getBoundingClientRect();
    const x = Math.round(((e.clientX - b.left) / b.width) * size[0]);
    const y = Math.round(((e.clientY - b.top) / b.height) * size[1]);
    setHeads([...heads, {x, y, r: Math.round(size[0] / 25)}].slice(0, 16));
  };
  const save = async () => {
    setMsg('');
    try { await api(`/episodes/${episodeId}/owner-heads/${assetId}`, {method: 'PUT', body: {heads}}); await reload(); await onSaved?.(); setMsg('Saved.'); }
    catch (e: any) { setMsg(e.message); }
  };
  return (
    <div className="stack" style={{gap: 4}}>
      <span className="small">Click each head once ({heads.length} marked):</span>
      <div style={{position: 'relative', width: 320, maxWidth: '100%'}}>
        <img src={url} alt="Click each head" style={{width: '100%', display: 'block', borderRadius: 4, cursor: 'crosshair'}}
          onLoad={e => setSize([e.currentTarget.naturalWidth, e.currentTarget.naturalHeight])} onClick={click} />
        {size && heads.map((h, i) => <span key={i} aria-hidden style={{position: 'absolute', left: `${(h.x / size[0]) * 100}%`,
          top: `${(h.y / size[1]) * 100}%`, width: 12, height: 12, marginLeft: -6, marginTop: -6, borderRadius: '50%',
          background: 'var(--bad, #c0392b)', border: '2px solid #fff'}} />)}
      </div>
      <span className="row">
        <button className="btn sm primary" type="button" onClick={save}>Save heads (free)</button>
        <button className="btn sm" type="button" onClick={() => setHeads([])}>Clear</button>
        {msg && <span className="small muted" role="status">{msg}</span>}</span>
    </div>);
}
