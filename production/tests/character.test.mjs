import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {loadRegistry, poseInfo, placePose, reactionLayers} from '../lib/character.mjs';
import {PRODUCTION_ROOT} from '../lib/runtime.mjs';

const REGISTRY = path.join(PRODUCTION_ROOT, 'characters', 'character-01.json');

test('every registered pose points at an existing file whose size matches the anchors', async () => {
  const reg = loadRegistry(REGISTRY);
  for (const id of Object.keys(reg.poses)) {
    const info = await poseInfo(reg, id);
    assert.ok(info.width > 200 && info.height > 500, `${id} size`);
    assert.ok(info.feet.x < info.width && info.feet.y < info.height, `${id} feet anchor inside image`);
    assert.ok(info.figureHeight <= info.feet.y, `${id} figure height above the feet`);
  }
  await assert.rejects(poseInfo(reg, '99'), /Unknown pose "99"/);
});

test('placement puts the feet anchor exactly on the requested point at the requested height', () => {
  const info = {width: 274, height: 596, feet: {x: 139, y: 585}, figureHeight: 575, headFraction: 0.42};
  const pl = placePose(info, {feetX: 640, feetY: 2070, figureHeight: 880});
  const k = 880 / 575;
  assert.ok(Math.abs(pl.x + 139 * k - 640) < 0.02 && Math.abs(pl.y + 585 * k - 2070) < 0.02);
  assert.ok(Math.abs(pl.w - 274 * k) < 0.02);
  assert.ok(Math.abs(pl.faceBox.y - (2070 - 880)) < 0.02 && Math.abs(pl.faceBox.h - 880 * 0.42) < 0.02);
});

test('enlargement beyond the softness limit is flagged', () => {
  const info = {width: 274, height: 596, feet: {x: 139, y: 585}, figureHeight: 575};
  assert.equal(placePose(info, {figureHeight: 880}, 0.84375).soft, false);
  assert.equal(placePose(info, {figureHeight: 1400}, 0.84375).soft, true);
});

test('pose segments become hard-cut image layers with matching face boxes', () => {
  const info = {id: '03', width: 274, height: 596, feet: {x: 139, y: 585}, figureHeight: 575, headFraction: 0.42};
  const out = reactionLayers([{pose: '03', start: 0, end: 2}, {pose: '03', start: 2, end: 5}], new Map([['03', info]]), {}, () => 'assets/src/p.png');
  assert.deepEqual(out.layers.map(l => [l.from, l.to]), [[0, 2], [2, 5]]);
  assert.equal(out.faceBoxes.length, 2);
});

test('registry validation rejects incomplete entries', () => {
  const f = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'or-reg-')), 'r.json');
  fs.writeFileSync(f, JSON.stringify({poses: {a: {file: 'x.png'}}}));
  assert.throws(() => loadRegistry(f), /feet anchor/);
});
