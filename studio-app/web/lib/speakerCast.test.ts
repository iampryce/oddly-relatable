// node --test: the episode page's Characters choices (a proposal per speaker label; the owner's pick wins).
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {choiceValue, choicesBody, type SpeakerRow} from './speakerCast.ts';

test('proposals become select values and the body keeps the owner picks', () => {
  const rows: SpeakerRow[] = [
    {label: 'Doctor', lines: 4, proposal: {kind: 'new', name: 'Doctor'}},
    {label: 'Jim', lines: 2, proposal: {kind: 'library', library_id: 'ab12', name: 'Jim'}},
    {label: 'ann', lines: 1, proposal: {kind: 'existing', character_key: 'ann', name: 'Ann'}},
  ];
  assert.deepEqual(rows.map(r => choiceValue(r.proposal)), ['new', 'library:ab12', 'existing:ann']);
  assert.deepEqual(choicesBody(rows, {Doctor: 'existing:bob'}), [
    {label: 'Doctor', kind: 'existing', character_key: 'bob'},
    {label: 'Jim', kind: 'library', library_id: 'ab12'},
    {label: 'ann', kind: 'existing', character_key: 'ann'},
  ]);
  assert.deepEqual(choicesBody([rows[0]], {}), [{label: 'Doctor', kind: 'new', name: 'Doctor'}]);
});
