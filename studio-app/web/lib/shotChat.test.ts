// node --test: chat under each shot (thread addresses, proposal labels, cost text).
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {applyLabel, episodeIdFromBase, estimateText, proposalDetail, refBody, sendLabel, threadQuery} from './shotChat.ts';

test('thread address: episode items carry the episode, masters do not', () => {
  assert.equal(threadQuery('still', 3, '12'), '/shot-chat/thread?step=still&item=3&episode_id=12');
  assert.equal(threadQuery('master', 7, null), '/shot-chat/thread?step=master&item=7');
  assert.deepEqual(refBody('prompt', 'ab12', 5), {step: 'prompt', item: 'ab12', episode_id: 5});
  assert.deepEqual(refBody('master', 7), {step: 'master', item: '7'});
  assert.equal(episodeIdFromBase('/episodes/12/shot-frames'), '12');
  assert.equal(episodeIdFromBase('/characters/1'), null);
});

test('apply labels show the price, free changes say free, unpriced ones cannot apply', () => {
  assert.equal(applyLabel(null), 'Apply (free)');
  assert.equal(applyLabel({usd: 0.04, label: '1 image x $0.04 = $0.04'}), 'Apply · 1 image x $0.04 = $0.04');
  assert.equal(applyLabel({usd: null, label: 'no video service connected'}), 'Cannot apply');
});

test('send button and estimate show cents with four decimals', () => {
  assert.equal(sendLabel({usd_max: 0.0712}, false), 'Send · up to $0.0712');
  assert.equal(sendLabel(null, true), 'Asking…');
  assert.equal(estimateText({usd_typical: 0.02, usd_max: 0.07}), 'About $0.0200, at most $0.0700 for this message');
  assert.equal(estimateText(null), '');
});

test('proposal detail is the new prompt when there is one', () => {
  assert.equal(proposalDetail({type: 'update_prompt', prompt: 'P'}), 'P');
  assert.equal(proposalDetail({type: 'rerender_shot', settings: {prompt: 'slow'}}), 'slow');
  assert.equal(proposalDetail({type: 'edit_beat'}), '');
});
