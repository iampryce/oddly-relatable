// node --test: the staging summary shown on an approved set.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {stagingSummary} from './setStaging.ts';

test('seats, table front and floor line in words', () => {
  assert.equal(stagingSummary({floor_y: 1300}), 'Staging: 0 seat(s), no table front, floor line at 1300 px');
  assert.equal(stagingSummary({floor_y: 1300, seats: [{}, {}, {}, {}], table_front: {x0: 1}}), 'Staging: 4 seat(s), table front marked, floor line at 1300 px');
  assert.equal(stagingSummary({floor_y: 900, seat: {x: 1}}), 'Staging: 1 seat(s), no table front, floor line at 900 px', 'the older single seat');
});
