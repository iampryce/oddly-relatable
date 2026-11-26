// node --test: steps 6-8 "Reactions and close-ups" helpers (picture clicks, crop and oval overlays, zoom, labels).
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {clickToPicture, cropStyle, moveKey, ovalStyle, poseBadge, poseButton, poseItem, segmentText, widthToZoom,
  zoomToWidth} from './reactionsGuide.ts';

test('clicks land in the picture\'s own pixels', () => {
  assert.deepEqual(clickToPicture(150, 75, 300, 150, 1920, 1080), {x: 960, y: 540});
  assert.deepEqual(clickToPicture(-5, 999, 300, 150, 1280, 720), {x: 0, y: 720});
});

test('crop and oval overlays in percent', () => {
  assert.deepEqual(cropStyle({x: 480, y: 270, w: 960, h: 540}, 1920, 1080), {left: '25.00%', top: '25.00%', width: '50.00%', height: '50.00%'});
  assert.deepEqual(ovalStyle({cx: 640, cy: 360, rx: 128, ry: 72}), {left: '40.00%', top: '40.00%', width: '20.00%', height: '20.00%'});
});

test('zoom slider and crop width round-trip', () => {
  assert.equal(zoomToWidth(100, 1920, 1080), 1920);
  assert.equal(zoomToWidth(50, 1920, 1080), 960);
  assert.equal(zoomToWidth(1, 1920, 1080), 96);              // at least 5%
  assert.equal(zoomToWidth(100, 900, 1600), 900);            // portrait master: limited by its width
  assert.equal(widthToZoom(960, 1920, 1080), 50);
});

test('labels', () => {
  assert.equal(poseItem(12, 3), '12:3');
  assert.equal(segmentText({kind: 'move', a: 0, b: 1, t0: 0.6, t1: 0.95}), '0.60–0.95 s move 0 → 1');
  assert.equal(segmentText({kind: 'live', a: 2, b: 2, t0: 1.55, t1: 2}), '1.55–2.00 s living hold on pose 2');
  assert.equal(segmentText({kind: 'hold', a: 1, b: 1, t0: 0.95, t1: 1.2}), '0.95–1.20 s still hold on pose 1');
  assert.equal(moveKey('mv-1-2'), '2');
  assert.equal(moveKey('hold-0'), 'hold-0');
  assert.deepEqual(poseBadge({as_is: true}, false), {text: 'Approve the crop first', tone: ''});
  assert.deepEqual(poseBadge({ready: true, takes: [{valid: true}]}, true), {text: 'Approved', tone: 'good'});
  assert.deepEqual(poseBadge({takes: [{valid: true}]}, true), {text: 'Needs your approval', tone: 'warn'});
  assert.deepEqual(poseBadge({takes: [{valid: false}]}, true), {text: 'Old crop: make it again', tone: 'warn'});
  assert.equal(poseButton({usd_max: 0.44}, 2), 'Make 2 poses · up to $0.44');
  assert.equal(poseButton({usd_max: 0}, 1), 'Make 1 pose (faces reused, free)');
  assert.equal(poseButton(null, 0), 'Nothing to make');
});
