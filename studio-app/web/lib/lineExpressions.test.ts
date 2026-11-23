// node --test: the expressions a line can use and the one it gets.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {usableExpressions, usedExpression} from './lineExpressions.ts';

test('only approved expressions are offered; a missing one uses the nearest approved one', () => {
  const mortimer = {expressions: {neutral: 'p1', smug: 'p2', angry: 'p3'}};
  assert.deepEqual(usableExpressions(mortimer), ['angry', 'neutral', 'smug']);
  assert.equal(usedExpression(mortimer, 'smug'), 'smug');
  assert.equal(usedExpression(mortimer, 'furious'), 'angry', 'same family');
  assert.equal(usedExpression(mortimer, 'very smug'), 'smug', 'loose name');
  assert.equal(usedExpression(mortimer, 'proud'), 'smug');
  assert.equal(usedExpression(mortimer, 'serious'), 'neutral', 'deadpan family: neutral');
  assert.equal(usedExpression(mortimer, 'amused'), 'neutral', 'no happy pose: neutral');
  assert.deepEqual(usableExpressions({}), ['neutral']);
});
