// node --test: the collapsed Characters page groups, searches and hides extra poses without losing any character.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {groupCharacters, removable, rigStatus, visiblePoses} from './characterView.ts';

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

test('only approved poses and unanswered reviews show until "show all poses"', () => {
  const assets = [pose(1, 'neutral', 'superseded'), pose(2, 'neutral', 'approved'), pose(3, 'neutral', 'review'), pose(4, 'happy', 'review'), pose(5, 'sad', 'rejected')];
  assert.deepEqual(visiblePoses(assets, false).map(p => p.id), [2, 4]);
  assert.equal(visiblePoses(assets, true).length, 5);
});

test('rig status of the body pose and who may be removed', () => {
  assert.equal(rigStatus(ch(1, 'a', 'episode', {assets: [pose(1, 'neutral', 'approved', {ok: false, role: 'body'})]})).label, 'rig: failed');
  assert.equal(rigStatus(ch(1, 'a', 'episode', {assets: [pose(1, 'neutral', 'approved')]})).label, 'rig: not checked');
  const usage = {a: [{id: 1, title: 'x', stage: 'published', live: false}], b: [{id: 2, title: 'y', stage: 'producing', live: true}]};
  assert.equal(removable(ch(1, 'a', 'episode'), usage), true, 'only a published episode uses it');
  assert.equal(removable(ch(2, 'b', 'episode'), usage), false);
  assert.equal(removable(ch(3, 'c', 'recurring', {locked: true}), usage), false);
});
