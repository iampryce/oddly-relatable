// node --test: the storyboard step's shot frames (times, people, status, the retake form, jobs).
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {activeJobs, clock, lastFailure, makingText, peopleText, retakeBody, retakeForm, retakeRunning, shotStatus,
  sideMembers, summary, timeRange} from './shotFrames.ts';

const shot = {index: 2, t0: 12.4, t1: 14.9, side: 'fam', people: ['ralph', 'sidney'], shot: 'medium', emotions: {ralph: 'happy'}, approved: false};

test('time range, people and status', () => {
  assert.equal(clock(75.4), '1:15');
  assert.equal(clock(-3), '0:00');
  assert.equal(timeRange(shot), '0:12–0:14');
  assert.equal(peopleText(shot.people, {ralph: 'Ralph'}), 'Ralph, sidney');
  assert.equal(peopleText([]), 'the room');
  assert.deepEqual(shotStatus(shot), {tone: '', text: 'draft'});
  assert.deepEqual(shotStatus({approved: true}), {tone: 'good', text: 'approved'});
  assert.equal(summary({shots: [shot, {approved: true}]}), '2 shots · 1 approved');
  assert.deepEqual(sideMembers({sides: {fam: ['ralph', 'sidney', 'win']}}, 'fam'), ['ralph', 'sidney', 'win']);
  assert.deepEqual(sideMembers(null, 'x'), []);
});

test('the retake sends only what changed', () => {
  const f = retakeForm(shot);
  assert.deepEqual(retakeBody(shot, f), {body: {}});
  assert.deepEqual(retakeBody(shot, {...f, shot: 'wide'}).body, {shot: 'wide'});
  assert.deepEqual(retakeBody(shot, {...f, people: ['sidney'], emotions: {ralph: 'sad', sidney: 'shocked'}}).body,
    {people: ['sidney'], emotions: {sidney: 'shocked'}});
  assert.deepEqual(retakeBody(shot, {...f, emotions: {ralph: 'happy', sidney: ''}}).body, {}, 'same face, no face: nothing');
  assert.deepEqual(retakeBody(shot, {...f, side: 'desk', people: ['mort']}).body, {side: 'desk', people: ['mort']});
  assert.ok(retakeBody(shot, {...f, shot: 'close'}).error);
  assert.equal(retakeBody(shot, {...f, shot: 'close', people: ['ralph']}).error, undefined);
  f.people.push('x');
  assert.deepEqual(shot.people, ['ralph', 'sidney'], 'the form is a copy');
});

test('jobs: progress, retakes in flight, the last failure', () => {
  const v = {jobs: [{id: 3, kind: 'shot_frame_retake', status: 'running', payload: {index: 2}},
    {id: 2, kind: 'shot_frames', status: 'running', progress: {done: 3, total: 12}},
    {id: 1, kind: 'shot_animatic', status: 'failed', error: 'no ffmpeg'}]};
  assert.equal(activeJobs(v).length, 2);
  assert.ok(retakeRunning(v, 2));
  assert.ok(!retakeRunning(v, 1));
  assert.equal(makingText(v), 'Drawing frames: 3 of 12');
  assert.equal(makingText({jobs: [{kind: 'shot_frames', status: 'queued'}]}), 'Queued…');
  assert.equal(makingText({jobs: []}), '');
  assert.equal(lastFailure(v), 'Animatic: no ffmpeg');
  assert.equal(lastFailure({jobs: [{id: 5, kind: 'shot_animatic', status: 'succeeded'}, ...v.jobs]}), '');
});
