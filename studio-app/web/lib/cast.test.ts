// node --test: the cast step's helpers (costs, style order, the description editor's text fields, the approval body).
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {approveBody, clothingToText, descriptionSummary, headNote, HEAD_NOTE, imageCost, keepText, linesToList,
  orderedStyles, STYLE_ORDER, textToClothing} from './cast.ts';

test('five styles in order; ticked styles keep that order', () => {
  assert.deepEqual([...STYLE_ORDER], ['stick', 'flat2d', '3d', 'anime', 'clay']);
  assert.deepEqual(orderedStyles(['clay', 'stick', 'x']), ['stick', 'clay']);
});

test('pictures are priced per picture', () => {
  assert.deepEqual(imageCost(5, 0.04), {usd: 0.2, label: '5 pictures x $0.04 = $0.20'});
  assert.equal(imageCost(1, 0.04).label, '1 picture x $0.04 = $0.04');
});

test('clothing and lists round-trip through the text boxes', () => {
  const c = [{garment: 'cardigan', colour: 'green'}, {garment: 'jeans', colour: ''}];
  assert.equal(clothingToText(c), 'cardigan - green\njeans');
  assert.deepEqual(textToClothing('cardigan - green\n\n jeans \n'), c);
  assert.deepEqual(linesToList('no hat\n\nno beard\n'), ['no hat', 'no beard']);
});

test('summary, approval body and head note', () => {
  assert.equal(descriptionSummary({role: 'wife', age: 'about 40', hair: {style: 'bun', colour: 'auburn'}, accessory: 'pearls'}),
    'wife · about 40 · hair: bun, auburn · accessory: pearls');
  assert.deepEqual(approveBody(7, 'library', false), {asset_id: 7, keep: 'library', new_version: false});
  assert.ok(keepText('library').includes('cast library'));
  assert.equal(headNote({auto: true}), '');
  assert.equal(headNote({auto: false}), HEAD_NOTE);
});
