import test from 'node:test';
import assert from 'node:assert/strict';
import {sequenceConversation, sequenceEpisode, readingTime, TIMING_DEFAULTS} from '../lib/conversation.mjs';

const speakers = {a: {side: 'left'}, b: {side: 'right'}};

test('events run back to back from explicit durations', () => {
  const s = sequenceConversation({speakers, events: [
    {type: 'message', speaker: 'a', text: 'Hi.', duration: 2, pose: 'p1'},
    {type: 'message', speaker: 'b', text: 'Hello.', duration: 3},
    {type: 'pause', duration: 1},
    {type: 'message', speaker: 'a', text: 'Bye.', duration: 2},
  ]});
  assert.deepEqual(s.messages.map(m => [m.speaker, m.side, m.start]), [['a', 'left', 0], ['b', 'right', 2], ['a', 'left', 6]]);
  assert.equal(s.conversationEnd, 8);
});

test('missing durations use the reading-time estimate, clamped', () => {
  assert.equal(readingTime('ok'), TIMING_DEFAULTS.minMessage);
  assert.equal(readingTime('x'.repeat(500)), TIMING_DEFAULTS.maxMessage);
  const s = sequenceConversation({speakers, events: [{type: 'message', speaker: 'a', text: 'A medium length line of text.'}]});
  assert.equal(s.messages[0].duration, readingTime('A medium length line of text.'));
});

test('typing indicator can be shorter than its beat; the next event starts after the beat', () => {
  const s = sequenceConversation({speakers, events: [
    {type: 'typing', speaker: 'a', duration: 3, visible: 2.4},
    {type: 'message', speaker: 'b', text: 'Why did the dots stop', duration: 2},
  ]});
  assert.deepEqual([s.typing[0].start, s.typing[0].end], [0, 2.4]);
  assert.equal(s.messages[0].start, 3);
});

test('explicit start may jump forward but never backward or into the previous beat', () => {
  const ok = sequenceConversation({speakers, events: [{type: 'message', speaker: 'a', text: 'One', duration: 2}, {type: 'message', speaker: 'b', text: 'Two', start: 5, duration: 1}]});
  assert.equal(ok.messages[1].start, 5);
  assert.throws(() => sequenceConversation({speakers, events: [{type: 'message', speaker: 'a', text: 'One', duration: 2}, {type: 'message', speaker: 'b', text: 'Two', start: 1}]}), /overlaps the previous beat/);
});

test('pose marks become a hold-until-next timeline that must start at 0', () => {
  const s = sequenceConversation({speakers, events: [
    {type: 'message', speaker: 'a', text: 'One', duration: 2, pose: 'x'},
    {type: 'message', speaker: 'b', text: 'Two', duration: 2, pose: 'x'},
    {type: 'message', speaker: 'a', text: 'Three', duration: 2, pose: 'y'},
  ]});
  assert.deepEqual(s.poses.map(p => [p.pose, p.start]), [['x', 0], ['y', 4]]);
  assert.throws(() => sequenceConversation({speakers, events: [{type: 'message', speaker: 'a', text: 'One', duration: 2}, {type: 'message', speaker: 'b', text: 'Two', pose: 'y'}]}), /must start at 0/);
});

test('sfx cues use only the renderer built-in kinds and its gain cap', () => {
  const s = sequenceConversation({speakers, events: [{type: 'message', speaker: 'a', text: 'Ding', duration: 2, sfx: 'chime'}]});
  assert.deepEqual(s.sfx, [{time: 0, kind: 'chime', gain: TIMING_DEFAULTS.sfxGain}]);
  assert.throws(() => sequenceConversation({speakers, events: [{type: 'message', speaker: 'a', text: 'x', sfx: 'airhorn'}]}), /unknown sfx/);
  assert.throws(() => sequenceConversation({speakers, events: [{type: 'message', speaker: 'a', text: 'x', sfx: {kind: 'pop', gain: 0.9}}]}), /sfx gain/);
});

test('invalid input fails with a clear message', () => {
  assert.throws(() => sequenceConversation({speakers, events: []}), /events/);
  assert.throws(() => sequenceConversation({speakers: {a: {side: 'middle'}}, events: [{type: 'pause', duration: 1}]}), /side must be/);
  assert.throws(() => sequenceConversation({speakers, events: [{type: 'message', speaker: 'zz', text: 'x'}]}), /unknown speaker/);
  assert.throws(() => sequenceConversation({speakers, events: [{type: 'message', speaker: 'a', text: 'love ❤️'}]}), /emoji/);
  assert.throws(() => sequenceConversation({speakers, events: [{type: 'dance'}]}), /unknown event type/);
});

test('episode adds hook and end card and rounds the duration up to whole frames', () => {
  const e = sequenceEpisode({format: {fps: 30}, speakers, hook: {text: 'Hook', duration: 2}, endCard: {duration: 3},
    events: [{type: 'message', speaker: 'a', text: 'One', duration: 2.01, pose: 'p'}]});
  assert.equal(e.endCard.start, 2.01);
  assert.equal(e.duration, Math.ceil(5.01 * 30) / 30);
  assert.equal(e.poses[0].end, e.duration);
  assert.throws(() => sequenceEpisode({speakers, hook: {text: 'Too long', duration: 9}, events: [{type: 'message', speaker: 'a', text: 'x', duration: 1}]}), /hook runs past/);
});
