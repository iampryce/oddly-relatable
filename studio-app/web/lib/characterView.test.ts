// node --test: the collapsed Characters page groups, searches and hides extra poses without losing any character.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {groupCharacters, isCandidate, jobFinished, jobText, needsRigCheck, poseRigText, removable, rigStatus, visiblePoses} from './characterView.ts';

const pose = (id: number, expression: string, status: string, rig?: any) => ({id, kind: 'pose', expression, status, rig_check: rig});
const ch = (id: number, key: string, scope: string, extra: any = {}) => ({id, key, name: key[0].toUpperCase() + key.slice(1), scope, episode_id: null, locked: false, assets: [], ...extra});

test('groups: recurring, this story, everyone else, archived; search by name or key', () => {
  const chars = [ch(1, 'leo', 'recurring'), ch(2, 'ralph', 'episode', {episode_id: 7}), ch(3, 'nia', 'episode', {episode_id: 8}), ch(4, 'gus', 'episode')];
  const usage = {leo: [{id: 7, title: 'Will', stage: 'storyboard_review', live: true}]};
  const g = groupCharacters(chars, usage, [4], 7, '');
  assert.deepEqual(g.story.map(c => c.key), ['leo', 'ralph']);
  assert.deepEqual(g.others.map(c => c.key), ['nia']);
  assert.deepEqual(g.archived.map(c => c.key), ['gus']);
  const all = groupCharacters(chars, usage, [], null, '');
  assert.equal(all.recurring.length + all.others.length, 4, 'without a story nobody is lost');
  assert.deepEqual(groupCharacters(chars, usage, [], null, 'RAL').others.map(c => c.key), ['ralph']);
});

test('approved poses and every pose awaiting review show (candidates too); rig-failed ones stay hidden', () => {
  const assets = [pose(1, 'neutral', 'superseded'), pose(2, 'neutral', 'approved'), pose(3, 'neutral', 'review', {ok: true, role: 'body'}),
    pose(4, 'happy', 'review'), pose(5, 'sad', 'rejected'), pose(6, 'neutral', 'rig_failed', {ok: false, role: 'body'})];
  const shown = visiblePoses(assets, false);
  assert.deepEqual(shown.map(p => p.id), [2, 3, 4], 'the neutral candidate shows although a neutral is approved');
  assert.equal(shown.filter(p => p.status === 'review').length, 2, 'the "to review" count includes the candidate');
  assert.equal(isCandidate(assets[2], assets), true);
  assert.equal(isCandidate(assets[3], assets), false, 'a review pose for a new expression is not a candidate');
  assert.equal(visiblePoses(assets, true).length, 6);
});

test('rig check text: result, candidate result, queued, running, not checked yet', () => {
  const ok = pose(3, 'neutral', 'review', {ok: true, role: 'body', message: 'the rig can be built from this pose'});
  assert.equal(poseRigText(ok, null)!.text, 'Rig check: OK (body pose: body and face)', 'a candidate shows its own check');
  const approved = pose(2, 'neutral', 'approved');
  assert.equal(poseRigText(approved, null)!.text, 'Rig check: not checked yet', 'no job: never "waiting for the worker"');
  assert.equal(poseRigText(approved, {id: 9, status: 'queued'})!.text, 'Rig check: queued, waiting for the worker (job 9)');
  assert.equal(poseRigText(approved, {id: 9, status: 'running'})!.text, 'Rig check: running (job 9)');
  assert.match(poseRigText(pose(2, 'neutral', 'approved', {ok: false, role: 'body', message: 'hands hidden'}), null)!.text, /failed \(body pose\): hands hidden/);
  assert.equal(poseRigText(pose(4, 'happy', 'review'), null), null, 'an unchecked sheet pose says nothing yet');
  const c = ch(1, 'ralph', 'episode', {assets: [approved, ok]});
  assert.equal(needsRigCheck(c), true);
  assert.equal(needsRigCheck({...c, rig_check_job: {id: 9, status: 'queued'}}), false, 'no second check while one is queued');
  assert.equal(rigStatus({...c, rig_check_job: {id: 9, status: 'running'}}).label, 'rig: check running');
  assert.equal(needsRigCheck({...c, locked: true}), false);
});

test('a followed job: queued, running with progress, the result or the error', () => {
  assert.equal(jobText({id: 310, kind: 'body_candidates', status: 'queued'}), 'Queued job 310…');
  assert.equal(jobText({id: 310, kind: 'body_candidates', status: 'running', progress: {done: 1, total: 3}}), 'Running job 310… (1 of 3 done)');
  assert.equal(jobText({id: 310, kind: 'body_candidates', status: 'succeeded', result: {passed: [1, 2], failed: [3]}}),
    '3 done: 2 passed, 1 failed the rig check (shown below as candidates)');
  assert.equal(jobText({id: 311, kind: 'body_candidates', status: 'succeeded', result: {passed: [], failed: [4]}}), '1 done: 0 passed, 1 failed the rig check');
  assert.equal(jobText({id: 312, kind: 'body_candidates', status: 'failed', error: 'Not configured: OpenAI: save the API key'}),
    'Job 312 failed: Not configured: OpenAI: save the API key');
  assert.equal(jobText({id: 313, kind: 'rig_check', status: 'succeeded', result: {checked: 4, failed: 1}}), 'Rig check done: 4 pose(s) checked, 1 failed');
  assert.equal(jobFinished({status: 'running'}), false);
  assert.equal(jobFinished({status: 'failed'}), true);
});

test('rig status of the body pose and who may be removed', () => {
  assert.equal(rigStatus(ch(1, 'a', 'episode', {assets: [pose(1, 'neutral', 'approved', {ok: false, role: 'body'})]})).label, 'rig: failed');
  assert.equal(rigStatus(ch(1, 'a', 'episode', {assets: [pose(1, 'neutral', 'approved')]})).label, 'rig: not checked');
  const usage = {a: [{id: 1, title: 'x', stage: 'published', live: false}], b: [{id: 2, title: 'y', stage: 'producing', live: true}]};
  assert.equal(removable(ch(1, 'a', 'episode'), usage), true, 'only a published episode uses it');
  assert.equal(removable(ch(2, 'b', 'episode'), usage), false);
  assert.equal(removable(ch(3, 'c', 'recurring', {locked: true}), usage), false);
});
