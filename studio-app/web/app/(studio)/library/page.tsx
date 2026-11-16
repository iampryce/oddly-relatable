'use client';
import Link from 'next/link';
import {useState} from 'react';
import {when} from '@/lib/api';
import {useApi} from '@/lib/hooks';
import {Empty, ErrorBox, Stage} from '@/components/ui';

export default function Library() {
  const {data, error} = useApi<any[]>('/library', 15000);
  const [open, setOpen] = useState<number | null>(null);
  return (
    <>
      <h1>Video Library</h1><p className="sub">Every rendered video, by episode and revision, with its approval status.</p>
      <ErrorBox error={error} />
      {data && !data.length && <Empty>No videos have been rendered yet.</Empty>}
      <div className="grid cols-2">
        {(data || []).map(ep => (
          <div key={ep.id} className="card stack">
            <div className="spread"><Link href={`/episodes/${ep.id}`}><strong>{ep.title}</strong></Link><Stage stage={ep.stage} /></div>
            {open === ep.id ? <video src={ep.videos[0].url} controls autoPlay preload="metadata" />
              : <button className="btn" onClick={() => setOpen(ep.id)}>Preview latest video</button>}
            <div className="small">
              <strong>Revisions</strong>
              <ul>{ep.videos.map((v: any) => (
                <li key={v.id}><a href={v.url} target="_blank" rel="noreferrer">Revision {v.revision}</a>
                  <span className="muted"> · {when(v.created_at)} · {(v.size / 1e6).toFixed(1)} MB{v.id === ep.video_asset_id ? ' · current' : ''}</span></li>))}</ul>
            </div>
          </div>))}
      </div>
    </>
  );
}
