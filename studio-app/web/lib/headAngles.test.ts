// node --test: the head angle words.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {angleLabel, angleStatusText} from './headAngles.ts';

test('until an angle is approved the mock is in use', () => {
  assert.equal(angleStatusText({status: 'mock'}), 'mock in use');
  assert.equal(angleStatusText({status: 'review', review: [{}, {}]}), '2 to review; mock in use');
  assert.equal(angleStatusText({status: 'approved'}), 'approved (used by the 3D rig)');
  assert.equal(angleLabel('three-quarter'), 'three-quarter');
});
