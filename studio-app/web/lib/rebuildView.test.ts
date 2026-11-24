// node --test: the "Rebuild scenes from audio" confirmation lists what is discarded and kept, and the cost.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {rebuildConfirmText, rebuildCost, sheetLoss} from './rebuildView.ts';

const preview = {discards: {storyboard_scenes: 5, stills_unlinked: 5, script_approval: 'the approval of script v1', scene_edits: 'per-scene edits'},
  keeps: ['poses and their approvals', 'the Reference plan and its acceptance'], after: 'approve the script, then generate the storyboard',
  cost: {writer: {provider: 'anthropic', usd: 0.0312, note: ''}, simple: {usd: 0}}};

test('the confirmation says what is discarded, what is kept and what it costs', () => {
  const t = rebuildConfirmText(preview, 'writer');
  assert.match(t, /AI writer: about \$0\.0312 \(anthropic\)/);
  assert.match(t, /- 5 storyboard scene\(s\) and their stills \(5; the images stay in storage\)/);
  assert.match(t, /- the approval of script v1/);
  assert.match(t, /This keeps:\n- poses and their approvals\n- the Reference plan and its acceptance/);
  assert.match(rebuildConfirmText(preview, 'simple'), /simple split: free \(simple split\)/);
});

test('without a text provider the writer path is free (the simple split is used)', () => {
  assert.equal(rebuildCost({cost: {writer: {provider: 'none', usd: 0, note: 'no text provider in Settings: the simple split is used (free)'}}}, 'writer'),
    'free: no text provider in Settings: the simple split is used (free)');
});

test('reaction beats and shot lists are named in the confirmation and asked about separately', () => {
  assert.equal(sheetLoss(preview), '', 'none: no second question');
  const p = {...preview, discards: {...preview.discards, reaction_beats: 8, shot_lists: 1}};
  assert.match(rebuildConfirmText(p, 'simple'), /- 8 reaction beat\(s\) and 1 shot list\(s\) on the storyboard/);
  assert.match(sheetLoss(p), /^The storyboard has 8 reaction beat\(s\) and 1 shot list\(s\)\. .*cannot be restored/);
  assert.match(sheetLoss({discards: {reaction_beats: 0, shot_lists: 2}}), /has 2 shot list\(s\)\./);
});
