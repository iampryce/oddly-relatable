'use client';
// The chat thread under a talking-shot result: the studio's ShotChat on the thread "talk:<shot>" (one thread per
// shot, shared by all its results, so the conversation keeps its history across re-renders). Its proposals are
// "advice only" or "render the talking shot again" with a new prompt and/or the movement guide on or off; Apply goes
// through the talking-shot render route with its confirmed price (409 otherwise).
import ShotChat from '@/components/ShotChat';

export type ShotThreadItem = {
  episodeId: number | string;
  step: 'talk';             // the shot-chat step of the talking shots
  shot: number;             // the storyboard shot index (the thread is talk:<shot>)
  renderId: string;         // the result shown just above
  assetId: number | null;   // the result's video asset
};

export default function ShotThreadSlot({item, onApplied}: {item: ShotThreadItem; onApplied?: () => unknown}) {
  return <ShotChat step="talk" item={item.shot} episodeId={item.episodeId} onApplied={onApplied} />;
}
