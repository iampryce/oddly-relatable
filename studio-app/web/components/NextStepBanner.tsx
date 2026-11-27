'use client';
// The top of the episode page (simple and advanced views): the next guided step in plain English and a button to the
// guided steps page, so an episode made from a video leads straight into the guided flow (Cast from video is step 4).
import Link from 'next/link';
import {useApi} from '@/lib/hooks';
import {nextStep, nextStepText} from '@/lib/guide';

export default function NextStepBanner({id}: {id: string | number}) {
  const {data: g} = useApi<any>(`/episodes/${id}/guide`, 30000);
  const ns = nextStep(g);
  if (!ns) return null;
  const ref = g?.steps?.upload?.items?.reference_video;
  return (
    <div className={`alert ${ns.done ? 'good' : 'info'}`} role="status">
      <div className="spread">
        <div>
          <strong>{nextStepText(ns)}</strong>
          {!ns.done && <div className="small">{ns.what}</div>}
          <div className="small">
            {ref ? 'Your reference video is in place (private).' : 'No reference video yet: add it in step 1 for the character descriptions and acting notes.'}
            {!ns.done && ns.key !== 'masters' ? ' Cast from video is step 4.' : ''}</div>
        </div>
        <Link className="btn primary" href={`/episodes/${id}/guide`}>Open the guided steps</Link>
      </div>
    </div>);
}
