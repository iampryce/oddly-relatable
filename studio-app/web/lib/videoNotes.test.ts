import {test} from 'node:test';
import assert from 'node:assert/strict';
import {describeRoles, forServer, setField} from './videoNotes.ts';

const ranges = [{start: 0, end: 5, shot: 'medium', roles: [{role: 'speaker', position: 'left', facing: 'reactor 1', emotion: 'annoyed'}], line_ids: ['l1']}];

test('roles read as plain words', () => {
  assert.equal(describeRoles(ranges[0].roles), 'speaker: left, facing reactor 1, annoyed');
  assert.equal(describeRoles([{role: 'reactor 2'}]), 'reactor 2');
});

test('a field is set or removed; line ids never go back to the server', () => {
  assert.equal(setField(ranges, 0, 'shot', 'close')[0].shot, 'close');
  assert.equal('shot' in setField(ranges, 0, 'shot', '')[0], false);
  assert.equal('line_ids' in forServer(ranges)[0], false);
});
