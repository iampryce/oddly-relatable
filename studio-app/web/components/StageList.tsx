'use client';
import {useApi} from '@/lib/hooks';
import {EpisodeTable, ErrorBox} from './ui';

// Section pages list the episodes in their part of the workflow; the work itself happens on the episode page.
export default function StageList({title, sub, groups}: {title: string; sub: string; groups: [string, string, string][]}) {
  return (
    <>
      <h1>{title}</h1><p className="sub">{sub}</p>
      {groups.map(([heading, stages, empty]) => <Group key={heading} heading={heading} stages={stages} empty={empty} />)}
    </>
  );
}

function Group({heading, stages, empty}: {heading: string; stages: string; empty: string}) {
  const {data, error} = useApi<any[]>(`/episodes?stage=${stages}`, 10000);
  return (
    <div style={{marginBottom: 20}}>
      <h2>{heading}</h2>
      <ErrorBox error={error} />
      {data && <EpisodeTable episodes={data} empty={empty} />}
    </div>
  );
}
