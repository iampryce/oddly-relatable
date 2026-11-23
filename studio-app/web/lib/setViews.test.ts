// node --test: the set views' words.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {planLine, viewStatusText, VIEW_LABEL} from './setViews.ts';

test('views in words: missing views fall back to wide; seats per view; the plan per shot', () => {
  assert.equal(viewStatusText({status: 'missing'}), 'not made: shots that want it use the wide view');
  assert.equal(viewStatusText({status: 'approved', seats: 3, seats_needed: 3}), 'approved · 3 seat(s) for 3');
  assert.equal(planLine({scene: 4, line: 'L12', shot: 'medium', view: 'wide', note: 'two-shot view missing: wide is used'}),
    'Scene 4, L12 (medium): wide view (two-shot view missing: wide is used)');
  assert.match(VIEW_LABEL.audience, /from the speaker's side/);
});
