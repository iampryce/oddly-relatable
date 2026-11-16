'use client';
import Link from 'next/link';
import {STAGE_LABEL, stageTone} from '@/lib/api';

export function Stage({stage}: {stage: string}) {
  return <span className={`badge ${stageTone(stage)}`}>{STAGE_LABEL[stage] || stage}</span>;
}

export function JobStatus({status}: {status: string}) {
  const tone = ({succeeded: 'good', failed: 'bad', running: 'busy', queued: 'warn'} as Record<string, string>)[status] || 'muted';
  return <span className={`badge ${tone}`}>{status}</span>;
}

export function ErrorBox({error}: {error?: string}) {
  return error ? <div className="alert bad" role="alert">{error}</div> : null;
}

export function Empty({children}: {children: React.ReactNode}) {
  return <div className="card empty">{children}</div>;
}

export function EpisodeTable({episodes, empty}: {episodes: any[]; empty: string}) {
  if (!episodes.length) return <Empty>{empty}</Empty>;
  return (
    <div className="card table-wrap">
      <table>
        <thead><tr><th>Episode</th><th>Stage</th><th>Next step</th><th>Revision</th><th>Updated</th></tr></thead>
        <tbody>{episodes.map(e => (
          <tr key={e.id}>
            <td><Link href={`/episodes/${e.id}`}>{e.title}</Link></td>
            <td><Stage stage={e.stage} /></td>
            <td className="muted">{e.next_step}</td>
            <td>{e.revision}</td>
            <td className="muted small">{new Date(e.updated_at).toLocaleString()}</td>
          </tr>))}
        </tbody>
      </table>
    </div>
  );
}

export const PIPELINE: [string, string[]][] = [
  ['script', ['script_pending', 'script_generating', 'script_review']],
  ['storyboard', ['script_approved', 'storyboard_generating', 'storyboard_review']],
  ['production', ['storyboard_approved', 'producing', 'production_failed']],
  ['review', ['video_review']],
  ['publish', ['final_approved', 'publishing', 'publish_failed', 'published']],
];

export function Pipeline({stage}: {stage: string}) {
  const at = PIPELINE.findIndex(([, s]) => s.includes(stage));
  return (
    <div className="steps">{PIPELINE.map(([name], i) => (
      <span key={name} className={`step ${i < at || stage === 'published' ? 'done' : i === at ? 'now' : ''}`}>{i + 1}. {name}</span>
    ))}</div>
  );
}
