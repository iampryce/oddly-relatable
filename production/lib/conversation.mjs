// Conversation data: validation and sequencing.
// A conversation file is generic structured data (speakers + ordered events); nothing here knows about a specific episode.
//
// Event types:
//   {type:'message', speaker, text, start?, duration?, pose?, sfx?}
//   {type:'typing',  speaker, start?, duration, pose?, sfx?}   (dots shown for `duration`, then removed)
//   {type:'pause',   duration, pose?}                           (empty beat, nothing new appears)
//   {type:'pose',    pose, start?}                              (change reaction pose without a message)
// `start` is optional: events run back to back from a cursor. An explicit start may jump forward but never back.
// A message's `duration` is its beat length (time until the next event); messages stay in the chat afterwards.
import {assertRenderable} from './text.mjs';

export const SFX_KINDS = Object.freeze(['tap', 'paper', 'pop', 'chime', 'jingle']); // renderer's built-in synthesized B1 SFX
export const TIMING_DEFAULTS = Object.freeze({readingCps: 15, readingLead: 1.0, minMessage: 2.0, maxMessage: 4.5, sfxGain: 0.16});

const EPS = 1e-6;
const num = (v, name, min = 0, max = 600) => {
  if (!Number.isFinite(v) || v < min || v > max) throw new Error(`Invalid ${name}: ${v}`);
  return v;
};

// Reading-time estimate: lead time + characters / reading speed, clamped.
export function readingTime(text, timing = TIMING_DEFAULTS) {
  const t = {...TIMING_DEFAULTS, ...timing};
  return Math.min(t.maxMessage, Math.max(t.minMessage, t.readingLead + text.length / t.readingCps));
}

function sfxCue(raw, time, timing, where) {
  if (raw === undefined || raw === null) return null;
  const cue = typeof raw === 'string' ? {kind: raw} : raw;
  if (!SFX_KINDS.includes(cue.kind)) throw new Error(`${where}: unknown sfx "${cue.kind}" (allowed: ${SFX_KINDS.join(', ')})`);
  const gain = num(cue.gain ?? timing.sfxGain, `${where} sfx gain`, 0, 0.3); // renderer caps B1 SFX gain at 0.3
  return {time: +(time + (cue.offset ?? 0)).toFixed(3), kind: cue.kind, gain};
}

export function validateSpeakers(speakers) {
  if (!speakers || typeof speakers !== 'object' || !Object.keys(speakers).length) throw new Error('speakers: at least one speaker is required');
  for (const [id, s] of Object.entries(speakers)) {
    if (!['left', 'right'].includes(s.side)) throw new Error(`speaker ${id}: side must be "left" or "right"`);
  }
  return speakers;
}

// Turn a conversation into an absolute timeline.
export function sequenceConversation(conv) {
  if (!conv || !Array.isArray(conv.events) || !conv.events.length) throw new Error('conversation: events[] is required');
  const speakers = validateSpeakers(conv.speakers);
  const timing = {...TIMING_DEFAULTS, ...(conv.timing || {})};
  const messages = [], typing = [], poseMarks = [], sfx = [];
  let cursor = 0, lastStart = 0;

  conv.events.forEach((ev, i) => {
    const where = `event ${i + 1} (${ev?.type})`;
    if (!ev || typeof ev !== 'object') throw new Error(`event ${i + 1}: must be an object`);
    const start = ev.start !== undefined ? num(ev.start, `${where} start`) : cursor;
    if (start < lastStart - EPS) throw new Error(`${where}: start ${start} is earlier than the previous event (${lastStart})`);
    if (start < cursor - EPS && ev.start !== undefined) throw new Error(`${where}: start ${start} overlaps the previous beat (ends ${cursor.toFixed(3)})`);
    lastStart = start;
    if (ev.pose !== undefined) poseMarks.push({pose: String(ev.pose), start});

    if (ev.type === 'message') {
      if (!speakers[ev.speaker]) throw new Error(`${where}: unknown speaker "${ev.speaker}"`);
      assertRenderable(ev.text, where);
      const duration = ev.duration !== undefined ? num(ev.duration, `${where} duration`, 0.3, 30) : readingTime(ev.text, timing);
      messages.push({id: `m${messages.length + 1}`, index: i, speaker: ev.speaker, side: speakers[ev.speaker].side, style: speakers[ev.speaker].style, text: ev.text, start, duration});
      const cue = sfxCue(ev.sfx, start, timing, where); if (cue) sfx.push(cue);
      cursor = start + duration;
    } else if (ev.type === 'typing') {
      if (!speakers[ev.speaker]) throw new Error(`${where}: unknown speaker "${ev.speaker}"`);
      const duration = num(ev.duration, `${where} duration`, 0.3, 30);
      // The indicator may be shorter than its beat (it "appears, then disappears" before the next event).
      const visible = ev.visible !== undefined ? num(ev.visible, `${where} visible`, 0.2, duration) : duration;
      typing.push({id: `t${typing.length + 1}`, index: i, speaker: ev.speaker, side: speakers[ev.speaker].side, style: speakers[ev.speaker].style, start, end: start + visible});
      const cue = sfxCue(ev.sfx, start, timing, where); if (cue) sfx.push(cue);
      cursor = start + duration;
    } else if (ev.type === 'pause') {
      cursor = start + num(ev.duration, `${where} duration`, 0.05, 30);
    } else if (ev.type === 'pose') {
      if (ev.pose === undefined) throw new Error(`${where}: pose is required`);
      cursor = start;
    } else throw new Error(`${where}: unknown event type`);
  });

  const conversationEnd = cursor;
  // Pose timeline: each mark holds until the next one. The first pose must be set at time 0.
  const poses = [];
  for (const mark of poseMarks) {
    const last = poses.at(-1);
    if (last && Math.abs(last.start - mark.start) < EPS) { last.pose = mark.pose; continue; }
    if (last && last.pose === mark.pose) continue;
    poses.push({...mark});
  }
  if (poses.length && poses[0].start > EPS) throw new Error('pose: the first reaction pose must start at 0 (set "pose" on the first event)');
  poses.forEach((p, i) => { p.end = i + 1 < poses.length ? poses[i + 1].start : Infinity; });

  return {messages, typing, poses, sfx: sfx.sort((a, b) => a.time - b.time), conversationEnd, timing};
}

// Full episode timing: hook overlay, conversation, then end card. Duration is rounded up to whole frames.
export function sequenceEpisode(ep) {
  const fps = ep.format?.fps ?? 30;
  const seq = sequenceConversation(ep);
  const hook = ep.hook ? {
    text: assertRenderable(ep.hook.text, 'hook'),
    start: num(ep.hook.start ?? 0, 'hook start'),
    duration: num(ep.hook.duration ?? 2.5, 'hook duration', 0.5, 10),
  } : null;
  const endHold = num(ep.endCard?.hold ?? 0, 'end card hold', 0, 10);
  const endCard = ep.endCard ? {
    ...ep.endCard,
    start: +(seq.conversationEnd + endHold).toFixed(3),
    duration: num(ep.endCard.duration ?? 3, 'end card duration', 0.5, 15),
  } : null;
  const rawEnd = endCard ? endCard.start + endCard.duration : seq.conversationEnd;
  const duration = Math.ceil(rawEnd * fps - EPS) / fps;
  for (const p of seq.poses) if (!Number.isFinite(p.end)) p.end = duration;
  if (hook && hook.start + hook.duration > duration + EPS) throw new Error('hook runs past the end of the episode');
  return {...seq, hook, endCard, duration, fps};
}
