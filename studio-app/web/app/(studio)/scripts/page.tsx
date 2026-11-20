'use client';
import StageList from '@/components/StageList';

export default function Scripts() {
  return <StageList title="Scripts" sub="Generate, edit, regenerate sections, and approve or reject scripts." groups={[
    ['From audio: upload, transcription and speaker labels', 'audio_upload,audio_transcribing,audio_labelling', 'No audio-first episodes in progress.'],
    ['Awaiting your approval', 'script_review,outline_review', 'No scripts or outlines are waiting for approval.'],
    ['Being written', 'script_pending,outline_generating,outline_approved,script_generating', 'No scripts in progress.'],
    ['Approved', 'script_approved', 'No approved scripts waiting for a storyboard.'],
  ]} />;
}
