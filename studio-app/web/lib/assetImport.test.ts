// node --test: the import panel's check before upload, the pose dimension label, the imported list and the provenance
// panel's rows. Imported and non-default poses stay out of the studio's own pose grid.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {base64Of, dimensionLabel, importPreview, importedAssets, provenanceRows, recordedDecision, sha256Hex} from './assetImport.ts';
import {isCandidate, isStandardPose, needsRigCheck, visiblePoses} from './characterView.ts';

const SHA = 'ab'.repeat(32);
const manifest = (x: any = {}) => ({kind: 'pose', sha256: SHA, width: 10, height: 20, expression: 'neutral', posture: 'seated', body_turn: 'left',
  generated: {at: '2026-11-24', by: 'codex-cli 0.165.0, ChatGPT sign-in', original_path: '~/.codex/x.png', references: [{sha256: SHA}]}, ...x});
const file = (x: any = {}) => ({name: 'a.png', size: 2048, sha256: SHA, width: 10, height: 20, ...x});

test('the pose dimension reads plainly; empty is the default', () => {
  assert.equal(dimensionLabel({}), 'standing · front (default)');
  assert.equal(dimensionLabel({posture: 'seated', body_turn: 'right', framing: 'chest_up'}), 'seated · turned right · chest-up');
  assert.equal(dimensionLabel({posture: 'seated', view: 'back', framing: 'bust'}), 'seated · front · seen from the back · bust');
});

test('the preview shows what will be stored and has no problem when file and manifest agree', () => {
  const p = importPreview(manifest(), file(), 'character');
  assert.deepEqual(p.problems, []);
  const rows = Object.fromEntries(p.rows);
  assert.equal(rows['Pose dimension'], 'seated · turned left');
  assert.equal(rows['sha256'], SHA);
  assert.equal(rows['Original path'], '~/.codex/x.png');
  assert.match(rows['Stored as'], /candidate/);
});

test('the preview refuses what the server would refuse', () => {
  assert.match(importPreview(manifest(), file({sha256: 'cd'.repeat(32)}), 'character').problems.join(), /sha256/);
  assert.match(importPreview(manifest(), file({width: 11}), 'character').problems.join(), /11×20/);
  assert.match(importPreview(manifest({kind: 'set-plate'}), file(), 'character').problems.join(), /kind must be/);
  assert.match(importPreview(manifest({generated: {at: '2026-11-24'}}), file(), 'character').problems.join(), /generated\.by/);
  assert.match(importPreview(manifest({approved: {by: 'o', at: 'd'}, rejected: {by: 'o', at: 'd'}}), file(), 'character').problems.join(), /at most one/);
  assert.match(importPreview(manifest({kind: 'mask'}), file(), 'character').problems.join(), /parent/);
  assert.match(importPreview(manifest({posture: 'lying'}), file(), 'character').problems.join(), /posture/);
  assert.match(importPreview(manifest({kind: 'set-plate', label: ''}), file(), 'set').problems.join(), /label/);
  assert.match(importPreview(manifest(), null, 'character').problems.join(), /image file/);
  assert.deepEqual(importPreview(manifest({kind: 'set-plate', label: 'Room', reverse_of: 'room-wide'}), file(), 'set').problems, []);
});

test('a decision recorded in the manifest is shown as information', () => {
  assert.equal(recordedDecision({approved: {by: 'owner', at: '2026-11-24', note: 'chest-up only'}}), 'approved by owner, 2026-11-24 (chest-up only)');
  assert.equal(recordedDecision({}), '');
  const rows = Object.fromEntries(provenanceRows({sha256: SHA, generated: {by: 'route', at: '2026-11-24'}, rejected: {by: 'owner', at: 'd'}}));
  assert.equal(rows['Route'], 'route');
  assert.equal(rows['Decision (manifest)'], 'rejected by owner, d');
  assert.deepEqual(provenanceRows(null), []);
});

test('imported assets list each mask under its pose', () => {
  const assets = [{id: 5, imported: true, kind: 'mask', parent_asset_id: 3}, {id: 4, imported: true, kind: 'back-view'},
    {id: 3, imported: true, kind: 'pose'}, {id: 2, kind: 'pose'}];
  assert.deepEqual(importedAssets(assets).map(a => a.id), [4, 3, 5]);
});

test('imported and non-default poses stay out of the studio pose grid; old poses (no dimension) are unchanged', () => {
  const old = {id: 1, kind: 'pose', expression: 'neutral', status: 'approved', rig_check: {ok: true}};
  const seated = {id: 2, kind: 'pose', expression: 'neutral', status: 'approved', posture: 'seated', imported: true};
  const cand = {id: 3, kind: 'pose', expression: 'neutral', status: 'review', posture: 'seated', imported: true};
  assert.equal(isStandardPose(old), true);
  assert.equal(isStandardPose({...old, posture: 'standing', body_turn: 'front'}), true);
  assert.equal(isStandardPose(seated), false);
  assert.deepEqual(visiblePoses([old, seated, cand], true).map(p => p.id), [1]);
  assert.equal(isCandidate(cand, [old, seated, cand]), false);
  assert.equal(needsRigCheck({assets: [old, seated]}), false, 'an approved seated pose is not rig-checked');
});

test('sha256 and base64 of the bytes', async () => {
  const buf = new TextEncoder().encode('abc').buffer as ArrayBuffer;
  assert.equal(await sha256Hex(buf), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  assert.equal(base64Of(buf), 'YWJj');
});
