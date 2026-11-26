// Chat under each shot: pure helpers for the ShotChat component (node --test). The server builds the context, checks
// every proposal and routes Apply to the step's own handler; these only shape what the page shows.
import {usd4} from './stickPipeline.ts';

export type Step = 'master' | 'still' | 'clip' | 'acting' | 'prompt';

export const STEP_NOUN: Record<Step, string> = {
  master: 'this master', still: 'this still', clip: 'this clip', acting: 'these acting notes', prompt: 'this prompt',
};

// GET /shot-chat/thread?... (episode_id is left out for a character master: those threads are studio-wide)
export function threadQuery(step: Step, item: string | number, episodeId?: string | number | null): string {
  const q = new URLSearchParams({step, item: String(item)});
  if (episodeId != null && episodeId !== '') q.set('episode_id', String(episodeId));
  return `/shot-chat/thread?${q}`;
}

export function refBody(step: Step, item: string | number, episodeId?: string | number | null): Record<string, unknown> {
  const b: Record<string, unknown> = {step, item: String(item)};
  if (episodeId != null && episodeId !== '') b.episode_id = Number(episodeId);
  return b;
}

// "/episodes/12/shot-frames" -> "12"
export function episodeIdFromBase(base: string): string | null {
  const m = /^\/episodes\/(\d+)\//.exec(base || '');
  return m ? m[1] : null;
}

export const PROPOSAL_STATUS: Record<string, {tone: string; text: string}> = {
  pending: {tone: 'warn', text: 'Waiting for your decision'},
  applied: {tone: 'good', text: 'Applied'},
  dismissed: {tone: '', text: 'Dismissed'},
  queued: {tone: 'busy', text: 'Queued for when this step exists'},
  note: {tone: '', text: 'Advice only'},
};

export const PROPOSAL_TITLE: Record<string, string> = {
  update_prompt: 'Change the prompt', edit_beat: 'Change an acting beat', redo_still: 'Make a new still',
  redo_master: 'Make new master candidates', rerender_shot: 'Make a new clip', note_only: 'Advice',
};

// the text shown in the proposal card besides "What will change" (the new prompt, if any)
export function proposalDetail(p: any): string {
  if (!p) return '';
  if (p.type === 'update_prompt' || p.type === 'redo_still') return p.prompt || '';
  if (p.type === 'rerender_shot') return p.settings?.prompt || '';
  return '';
}

// "Apply · $0.04" for a paid proposal, "Apply (free)" otherwise; null cost.usd means it cannot be priced (no button)
export function applyLabel(cost: any): string {
  if (!cost) return 'Apply (free)';
  return cost.usd == null ? 'Cannot apply' : `Apply · ${cost.label}`;
}

export function sendLabel(est: any, busy: boolean): string {
  if (busy) return 'Asking…';
  return est ? `Send · up to ${usd4(est.usd_max)}` : 'Send';
}

export function estimateText(est: any): string {
  return est ? `About ${usd4(est.usd_typical)}, at most ${usd4(est.usd_max)} for this message` : '';
}
