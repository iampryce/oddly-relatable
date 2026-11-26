// node --test: step 9 "Talking shots" helpers (cost text, live progress, guide badge, head click, pieces).
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {clickToStill, guideBadge, isActive, piecesText, progress, renderCost, usd} from './talkingGuide.ts';

test('cost text', () => {
  assert.equal(renderCost({minutes: 21.6, usd_typical: 0.39, usd_max: 0.98}), 'about $0.39, at most $0.98 (about 22 GPU min)');
  assert.equal(renderCost({minutes: 0}), '');
  assert.equal(usd(null), '—');
  assert.equal(usd(0.0042), '$0.0042');
});

test('progress while rendering is capped at 95% and counts down', () => {
  const run = {status: 'rendering', started: 1000, est_s: 600, stage: 'Rendering on NVIDIA L40S'};
  assert.deepEqual(progress(run, 1300), {label: 'Rendering on NVIDIA L40S · 50% · about 5 min left', pct: 50});
  assert.equal(progress(run, 5000).pct, 95);
  assert.equal(progress({status: 'queued', stage: 'Starting the rented GPU'}, 0).label, 'Starting the rented GPU');
  assert.equal(progress({status: 'failed', error: 'boom'}, 0).label, 'Failed: boom');
  assert.equal(progress(null, 0).pct, null);
  assert.ok(isActive({status: 'queued'}) && isActive({status: 'rendering'}) && !isActive({status: 'done'}));
});

test('guide badge tone', () => {
  assert.deepEqual(guideBadge({state: 'ok', text: 'follows the actor 84% of the shot'}), {text: 'follows the actor 84% of the shot', tone: 'good'});
  assert.equal(guideBadge({state: 'low', text: 'x'}).tone, 'warn');
  assert.equal(guideBadge({state: 'not_read', text: 'x'}).tone, 'busy');
});

test('a click on the thumbnail maps to the 1024x576 still', () => {
  assert.deepEqual(clickToStill(128, 72, 256, 144), {x: 512, y: 288});
  assert.deepEqual(clickToStill(-5, 999, 256, 144), {x: 0, y: 576});
});

test('pieces text', () => {
  assert.equal(piecesText([33]), '1 piece (33 frames)');
  assert.equal(piecesText([77, 37]), '2 pieces (77 + 37 frames)');
  assert.equal(piecesText([]), '');
});
