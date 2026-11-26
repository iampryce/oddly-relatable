import {test} from 'node:test';
import assert from 'node:assert/strict';
import {boxStyle, checkBadge, dragBox, eyelineText, makeLabel, ovalBox, pictureBadge, repairBadge, targetLabel} from './setsGuide.ts';

test('a dragged box stays inside the picture, either direction, at least 8 px', () => {
  assert.deepEqual(dragBox({x: 300, y: 200}, {x: 100, y: 50}, 1920, 1080), {x: 100, y: 50, w: 200, h: 150});
  assert.deepEqual(dragBox({x: -50, y: -10}, {x: 5000, y: 300}, 1920, 1080), {x: 0, y: 0, w: 1920, h: 300});
  assert.deepEqual(dragBox({x: 1919, y: 10}, {x: 1919, y: 12}, 1920, 1080), {x: 1912, y: 10, w: 8, h: 8});
});

test('boxes and ovals drawn in percent of the picture', () => {
  assert.deepEqual(boxStyle({x: 0, y: 540, w: 960, h: 270}, 1920, 1080), {left: '0.00%', top: '50.00%', width: '50.00%', height: '25.00%'});
  assert.deepEqual(ovalBox({cx: 100, cy: 50, rx: 10, ry: 20}), {x: 90, y: 30, w: 20, h: 40});
});

test('badges and labels in plain words', () => {
  assert.equal(pictureBadge({takes: [{}], approved: null}).text, 'Needs your approval');
  assert.equal(pictureBadge({takes: [], busy: true}).tone, 'busy');
  assert.equal(pictureBadge({takes: [{}], approved: 'a'}).tone, 'good');
  assert.equal(checkBadge({flags: ['x'], names: ['A']}).tone, 'bad');
  assert.equal(checkBadge({flags: [], heads: 5, names: ['A', 'B', 'C', 'D', 'E']}).text, '5 head(s) for 5 character(s)');
  assert.equal(repairBadge({status: 'done', approved: null}).text, 'Needs your decision');
  assert.equal(makeLabel({usd: 0.04}, false), 'Make the picture · $0.04');
  assert.equal(makeLabel(null, true), 'Make another picture');
  assert.ok(eyelineText({direction: 'left', toward: 'Mortimer', owner: null}).startsWith('Slightly screen-left, toward Mortimer'));
  assert.ok(eyelineText({direction: 'right', toward: 'x', owner: 'right'}).endsWith('(your choice)'));
  const v = {walls: [{id: 'ab12', name: 'back wall'}], seating: [{side: 'family', label: 'Family side'}]};
  assert.equal(targetLabel('wall:ab12', v), 'Wall: back wall');
  assert.equal(targetLabel('seating:family', v), 'Seating: Family side');
  assert.equal(targetLabel('still:3', v), 'Shot 3 still');
});
