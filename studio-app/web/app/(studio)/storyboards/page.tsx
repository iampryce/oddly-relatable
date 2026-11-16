'use client';
import StageList from '@/components/StageList';

export default function Storyboards() {
  return <StageList title="Storyboards" sub="Review each scene, its stills, dialogue, camera and action, then approve before animation." groups={[
    ['Awaiting your approval', 'storyboard_review', 'No storyboards are waiting for approval.'],
    ['Ready to build', 'script_approved,storyboard_generating', 'No approved scripts waiting for a storyboard.'],
    ['Approved, ready for production', 'storyboard_approved', 'Nothing is waiting to start production.'],
  ]} />;
}
