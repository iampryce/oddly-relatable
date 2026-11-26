'use client';
// Mount point for the per-shot chat thread (built on the feat/shot-chat branch). Every talking-shot result renders
// <ShotThreadSlot item={...} /> directly under its video; until the chat lands this renders nothing. To connect it,
// replace the body of this component (or re-export the chat thread component from here); the item says which shot
// and which result the thread belongs to.
export type ShotThreadItem = {
  episodeId: number | string;
  step: 'talking';          // which guided step the preview belongs to
  shot: number;             // the storyboard shot index
  renderId: string;         // the result (take) under discussion
  assetId: number | null;   // the result's video asset
};

export default function ShotThreadSlot(_props: {item: ShotThreadItem}) {
  return null;
}
