import {test} from 'node:test';
import assert from 'node:assert/strict';
import {DISCLOSURE, guardText, MODES, progress, shotLine, shotStatus, storyBody, storyReady} from './cinematic.ts';

test('two clear mode cards', () => {
  assert.deepEqual(MODES.map(m => m.id), ['cartoon', 'cinematic']);
  assert.match(MODES[1].title, /realistic actors, real acting/);
});

test('story body carries only the chosen source', () => {
  assert.deepEqual(storyBody('idea', {idea: '  A queen with fire.  ', script: 'x'}), {source: 'idea', idea: 'A queen with fire.'});
  const b = storyBody('bible', {passage: 'Daniel 3', text: ' unto ', confirm: true});
  assert.equal(b.translation, 'KJV');
  assert.equal(b.confirm_public_domain, true);
  assert.equal(storyReady('bible', {passage: 'Daniel'}), false);
  assert.equal(storyReady('bible', {passage: 'Daniel 3'}), true);
  assert.equal(storyReady('idea', {idea: 'short'}), false);
});

test('guard and shot texts', () => {
  assert.equal(guardText({status: 'refused', reasons: ['NIV']}).tone, 'bad');
  assert.equal(guardText({status: 'flagged', reasons: ['x']}).tone, 'warn');
  assert.equal(guardText({status: 'ok'}).tone, 'good');
  assert.match(shotLine({size: 'close', camera: 'push in', characters: ['King'], action: 'He rises.',
    line: {speaker: 'King', emotion: 'angry', text: 'Kneel.'}}), /Close-up, push in · King: He rises\. — King \(angry\): “Kneel\.”/);
  assert.equal(shotStatus({stills: [{}], approved: null}).text, 'Approve a still');
  assert.equal(shotStatus({renders: [{}], approved_render: null}).tone, 'warn');
  assert.match(DISCLOSURE, /Altered or synthetic content/);
});

test('the final step needs the cut approved and the notice ticked', () => {
  const v = {story: {}, screenplay: {approved: true}, cast_made: true, cast: [{master: {}}], locations_made: true,
    locations: [{approved: 'a'}], shots: [{approved: 's', approved_render: 'r'}], lines: [], approved_cut: 'c',
    disclosure: {acknowledged: false}};
  assert.equal(progress(v).at(-1)!.done, false);
  assert.equal(progress({...v, disclosure: {acknowledged: true}}).every(s => s.done), true);
});
