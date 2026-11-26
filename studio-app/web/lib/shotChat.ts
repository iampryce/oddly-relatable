// Chat under each shot: pure helpers for the ShotChat component (node --test). The server builds the context, checks
// every proposal and routes Apply to the step's own handler; these only shape what the page shows.
import {usd4} from './stickPipeline.ts';

export type Step = 'master' | 'still' | 'clip' | 'acting' | 'prompt' | 'talk' | 'pose' | 'wall' | 'seating' | 'repair';

export const STEP_NOUN: Record<Step, string> = {
  master: 'this master', still: 'this still', clip: 'this clip', acting: 'these acting notes', prompt: 'this prompt',
  talk: 'this talking shot', pose: 'this pose', wall: 'this wall', seating: 'this seating picture',
  repair: 'this repair',
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
  rerender_talking_shot: 'Render the talking shot again',
  redo_pose: 'Redraw this face', reanimate_shot: 'Animate the shot again',
  remake_wall: 'Draw this wall again', repaint_background: 'Repaint the background behind the people',
};

// the text shown in the proposal card besides "What will change" (the new prompt, if any)
export function proposalDetail(p: any): string {
  if (!p) return '';
  if (p.type === 'update_prompt' || p.type === 'redo_still' || p.type === 'rerender_talking_shot' || p.type === 'redo_pose'
    || p.type === 'remake_wall') return p.prompt || '';
  if (p.type === 'repaint_background') return (p.prompt || '') + (p.box ? `\nBox: ${Math.round(p.box.w)} x ${Math.round(p.box.h)} px at ${Math.round(p.box.x)}, ${Math.round(p.box.y)}` : '');
  if (p.type === 'reanimate_shot') return Object.entries(p.move_prompts || {})
    .map(([k, v]) => `${k.startsWith('hold-') ? `Hold of pose ${k.slice(5)}` : `Move into pose ${k}`}: ${v}`).join('\n');
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
