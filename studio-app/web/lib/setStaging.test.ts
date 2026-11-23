// node --test: the staging summary shown on an approved set.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {spacingWarnings, stagingSummary} from './setStaging.ts';

test('seats, table front and floor line in words', () => {
  assert.equal(stagingSummary({floor_y: 1300}), 'Staging: 0 seat(s), no table front, floor line at 1300 px');
  assert.equal(stagingSummary({floor_y: 1300, seats: [{}, {}, {}, {}], table_front: {x0: 1}}), 'Staging: 4 seat(s), table front marked, floor line at 1300 px');
  assert.equal(stagingSummary({floor_y: 900, seat: {x: 1}}), 'Staging: 1 seat(s), no table front, floor line at 900 px', 'the older single seat');
});

test('close seats are named with the numbers; a desk seat and the row in front of it are not compared', () => {
  const ep14 = [{x: 269, hip_y: 968}, {x: 422, hip_y: 968}, {x: 561, hip_y: 968}, {x: 690, hip_y: 968}];
  assert.deepEqual(spacingWarnings(ep14, 134).map(w => w.text), ['seats 3 and 4 are 129 px apart; need 134 px']);
  assert.deepEqual(spacingWarnings(ep14, 172).map(w => w.seats), [[1, 2], [2, 3], [3, 4]]);
  const desk = [{x: 512, hip_y: 829}, {x: 236, hip_y: 1167}, {x: 512, hip_y: 1167}, {x: 788, hip_y: 1167}];
  assert.deepEqual(spacingWarnings(desk, 134), [], 'the speaker behind the desk is in another row');
  assert.deepEqual(spacingWarnings([{x: 500, hip_y: 900}, {x: 400, hip_y: 900}], 134)[0].seats, [2, 1], 'numbered as marked, left to right');
  assert.deepEqual(spacingWarnings([], 134), []);
});

test('seat facing: defaults, labels and the arrow on the picture', async () => {
  const {seatFacing, facingLabel, facingArrow} = await import('./setStaging.ts');
  const desk = [{x: 180}, {x: 530, facing: 'speaker'}, {x: 737, facing: 'seat:1'}, {x: 940, facing: 'away'}];
  assert.equal(seatFacing(desk, 0), '', 'no choice: decided by the scene (the reference plan)');
  assert.equal(facingArrow(desk, 0), null);
  assert.match(facingLabel(''), /reference plan/);
  assert.deepEqual(facingArrow(desk, 1), {x: -1, y: 0}, 'the speaker is to the left');
  assert.deepEqual(facingArrow(desk, 2), {x: -1, y: 0}, 'seat 2 is to the left of seat 3');
  assert.deepEqual(facingArrow(desk, 3), {x: 0, y: -1});
  assert.equal(facingLabel('seat:1'), 'toward seat 2');
  assert.equal(facingLabel('speaker'), 'toward the speaker');
});
