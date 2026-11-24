'use client';
// Lab (owner decision 2026-11-23): the experiments, away from the episode's normal path. The shot comparison (every
// provider column: InfiniteTalk, Kling, the fal.ai models, the rig render, the self-hosted GPU) and the Motion Model
// Comparison. Nothing here is needed to make an episode: talking shots, their keying and Key again are in each
// episode's Talking shots section. Every paid run here still shows its cost first and starts only on your click.
import {MotionComparison} from '@/components/MotionComparison';
import {ShotComparison} from '@/components/ShotComparison';

export default function Lab() {
  return (
    <>
      <h1>Lab</h1>
      <p className="sub">Experiments: compare providers and models line by line. An episode does not need anything here.</p>
      <ShotComparison />
      <MotionComparison />
    </>
  );
}
