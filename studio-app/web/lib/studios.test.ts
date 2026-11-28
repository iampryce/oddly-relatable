// node --test (Node strips the types): three studios, only Stick Man is open.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ACTIVE_STUDIO, LOCKED_NOTE, STUDIOS, studioOf} from './studios.ts';

test('there are three studios, in the documented order', () => {
  assert.deepEqual(STUDIOS.map(s => s.id), ['stick-man', 'cinematic', 'kids-stories']);
});

test('only Stick Man Studio is unlocked, and it is the active one', () => {
  assert.deepEqual(STUDIOS.filter(s => !s.locked).map(s => s.id), ['stick-man']);
  assert.equal(ACTIVE_STUDIO, 'stick-man');
  assert.equal(studioOf(ACTIVE_STUDIO)?.locked, false);
});

test('Cinematic and Kids Stories are locked, and the note says why', () => {
  for (const id of ['cinematic', 'kids-stories']) assert.equal(studioOf(id)?.locked, true);
  assert.match(LOCKED_NOTE, /unlock gates/);
});

test('an unknown studio id is not found', () => {
  assert.equal(studioOf('nope'), undefined);
});
