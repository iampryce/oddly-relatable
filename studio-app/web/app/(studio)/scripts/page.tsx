'use client';
import StageList from '@/components/StageList';

export default function Scripts() {
  return <StageList title="Scripts" sub="Generate, edit, regenerate sections, and approve or reject scripts." groups={[
    ['Awaiting your approval', 'script_review', 'No scripts are waiting for approval.'],
    ['Being written', 'script_pending,script_generating', 'No scripts in progress.'],
    ['Approved', 'script_approved', 'No approved scripts waiting for a storyboard.'],
  ]} />;
}
