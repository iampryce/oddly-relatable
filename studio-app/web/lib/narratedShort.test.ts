import {test} from 'node:test';
import assert from 'node:assert/strict';
import {captionsText, HELP, lengthLabel, paidConfirm, paidLabel, picturesSummary, sceneTime, scriptLength, STEPS,
  stepStates, targetWords, voiceCostText} from './narratedShort.ts';

test('every step has plain-English help', () => {
  assert.equal(STEPS.length, 9);
  for (const s of STEPS) assert.ok(HELP[s.key] && HELP[s.key].length > 40, s.key);
  assert.match(HELP.assembly, /never sped up/);
  assert.match(HELP.voice, /free tier/);
});

test('lengths and word targets', () => {
  assert.equal(lengthLabel(30), '30 s');
  assert.equal(lengthLabel(90), '1 min 30 s');
  assert.equal(lengthLabel(600), '10 min');
  assert.equal(targetWords(30), 111);
  assert.match(scriptLength('one two three four', 30), /^4 words, about 1 s \(target about 111 words\)$/);
});

test('paid buttons show the price and the question repeats it', () => {
  const est = {usd_max: 0.0123, label: 'gpt-5.5: about $0.0050, at most $0.0123'};
  assert.equal(paidLabel('Write 10 ideas', est), 'Write 10 ideas · up to $0.0123');
  assert.equal(paidLabel('Make the narration', {usd_max: 0}), 'Make the narration · free');
  assert.equal(paidLabel('X', {usd_max: null}), 'X (cost unknown)');
  assert.match(paidConfirm('Write 10 ideas', est), /at most \$0\.0123\. Start now\?/);
  assert.match(paidConfirm('X', null), /cannot start/);
});

test('voice cost text carries the free-tier warning or the reason it cannot start', () => {
  assert.equal(voiceCostText(null), 'Approve the script first.');
  assert.equal(voiceCostText({blocked: 'tick a tier'}), 'tick a tier');
  assert.match(voiceCostText({label: 'free (free tier)', warning: 'Google may use the text'}), /Google may use/);
});

test('step states never claim an approval the API did not record', () => {
  const v = {choose: {characters: [1]}, ideas: {items: [{id: 'a'}]}, idea: null, script: {versions: [{v: 1}], approved: null},
    scenes: {items: [{n: 1, picture_prompt: 'p', pictures: [{asset_id: 5}], picture_approved: false, clips: []}]},
    voice: {takes: [{id: 't', fits: true}], approved: null}, final: {cuts: [{id: 'c'}], approved: null}, publish: {}, jobs: []};
  const s = stepStates(v);
  assert.equal(s.choose, 'done');
  assert.equal(s.ideas, 'waiting');
  assert.equal(s.script, 'waiting');
  assert.equal(s.voice, 'waiting');
  assert.equal(s.pictures, 'waiting');
  assert.equal(s.assembly, 'waiting');
  const done = stepStates({...v, voice: {takes: [{id: 't', fits: true}], approved: 't'}, final: {cuts: [{id: 'c'}], approved: 'c'}});
  assert.equal(done.voice, 'done');
  assert.equal(done.assembly, 'done');
  const stale = stepStates({...v, voice: {takes: [{id: 't', fits: false}], approved: 't'}});
  assert.equal(stale.voice, 'todo');                         // an approved take for an older script is not done
  assert.equal(stepStates({...v, jobs: [{kind: 'short_motion', status: 'running'}]}).motion, 'busy');
});

test('scene timing and summaries', () => {
  assert.equal(sceneTime({timed: {start: 1.2, seconds: 3.24, frames: 81}}), '1.20-4.44 s (81 frames)');
  assert.equal(sceneTime({estimated_seconds: 3.04}), 'about 3.0 s (estimated from the words)');
  assert.equal(picturesSummary([{picture_approved: true}, {picture_approved: false}]), '1 of 2 pictures approved');
  assert.match(captionsText(true), /upper middle/);
  assert.equal(captionsText(false), 'Captions off');
});
