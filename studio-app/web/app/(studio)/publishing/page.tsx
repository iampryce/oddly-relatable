'use client';
import StageList from '@/components/StageList';
import {useApi} from '@/lib/hooks';

export default function Publishing() {
  const {data: s} = useApi<any>('/settings');
  return (
    <>
      {s && !s.integrations.youtube && (
        <div className="alert warn">YouTube is not connected on the server. Publishing stays disabled until the owner adds the channel credentials (see Settings &gt; YouTube).</div>)}
      <StageList title="Publishing" sub="Nothing is published without your explicit approval of the exact video and details." groups={[
        ['Ready to publish (approved videos)', 'final_approved,publish_failed', 'No approved videos are waiting.'],
        ['Publishing', 'publishing', 'Nothing is uploading.'],
        ['Published', 'published', 'Nothing has been published yet.'],
      ]} />
    </>
  );
}
