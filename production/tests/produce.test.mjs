// End-to-end production runs on small stories (real renderer, real QA). Needs FFMPEG/FFPROBE.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {produceEpisode} from '../lib/produce.mjs';
import {qaVideo, qaProjectInputs} from '../lib/qa.mjs';

const needs = {skip: process.env.FFMPEG && process.env.FFPROBE ? false : 'set FFMPEG/FFPROBE to run production tests'};
const tmp = n => fs.mkdtempSync(path.join(os.tmpdir(), `or82-${n}-`));
const sha = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const json = f => JSON.parse(fs.readFileSync(f, 'utf8'));

function storyFile(overrides = {}, scene = {}) {
  const story = {
    schema: 'oddly-relatable/story@1', id: 'tiny', title: 'Tiny', format: {width: 1080, height: 1920, fps: 30},
    endCard: {duration: 1, caption: 'Oddly Relatable'},
    scenes: [{id: 's1', format: 'text-chat', environment: 'living-room-empty-03', cast: [{id: 'him', character: 'character-01'}], reactionCast: 'him',
      speakers: {her: {side: 'left', style: 'her'}, him: {side: 'right', style: 'him'}},
      events: [{type: 'message', speaker: 'her', text: 'We need to talk.', duration: 1, pose: '02', sfx: 'chime', camera: 'Wide'},
        {type: 'message', speaker: 'him', text: 'Define March.', duration: 1, pose: '03', sfx: 'pop', camera: 'Medium 1.3×'}], ...scene}],
    ...overrides};
  const f = path.join(tmp('story'), 'story.json'); fs.writeFileSync(f, JSON.stringify(story)); return f;
}

test('invalid inputs fail at a named stage with a clear message, and the run report records it', needs, async () => {
  const out = tmp('bad');
  await assert.rejects(produceEpisode(storyFile({schema: 'wrong'}), {outDir: out}), /stage "compile": Story schema must be/);
  assert.equal(json(path.join(out, 'production-run.json')).status, 'failed');
  await assert.rejects(produceEpisode(storyFile({}, {environment: 'no-such-room'}), {outDir: tmp('env')}), /Unknown environment "no-such-room"/);
  await assert.rejects(produceEpisode(storyFile({}, {cast: [{id: 'him', character: 'character-99'}]}), {outDir: tmp('chr')}), /no registry for character "character-99"/);
  await assert.rejects(produceEpisode(path.join(tmp('none'), 'missing.json'), {outDir: tmp('m')}), /Story file not found/);
});

test('one command produces project, storyboard, MP4, audio, reports and a hashed manifest; QA passes', needs, async () => {
  const out = tmp('full');
  const r = await produceEpisode(storyFile(), {outDir: out});
  assert.equal(r.status, 'produced', JSON.stringify(r.report.stages));
  for (const f of ['project/project.json', 'storyboard/storyboard-sheet.png', 'render/tiny.mp4', 'audio/tiny.wav', 'reports/layout-report.json', 'reports/qa-report.json', 'production-manifest.json', 'production-run.json'])
    assert.ok(fs.existsSync(path.join(out, f)), f);
  const qa = json(path.join(out, 'reports', 'qa-report.json'));
  assert.equal(qa.status, 'pass', JSON.stringify(qa.checks.filter(c => c.status === 'fail')));
  assert.equal(qa.checks.find(c => c.id === 'frame-count').detail.startsWith('90 frames'), true);
  const m = json(path.join(out, 'production-manifest.json'));
  assert.equal(m.outputs.find(o => o.path === 'render/tiny.mp4').sha256, sha(path.join(out, 'render', 'tiny.mp4')));
  assert.ok(m.inputs.artwork.length >= 3 && m.inputs.characterRegistries.length === 1 && m.inputs.environmentRegistry);
  assert.match(r.report.humanApproval, /required before any publication/);
});

test('approved voice and music sources are mixed into the episode audio and recorded in the manifest', needs, async () => {
  const d = tmp('src'), f = path.join(d, 'line.wav'), n = 48000;
  const b = Buffer.alloc(44 + n * 2); b.write('RIFF', 0); b.writeUInt32LE(b.length - 8, 4); b.write('WAVEfmt ', 8); b.writeUInt32LE(16, 16); b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22);
  b.writeUInt32LE(48000, 24); b.writeUInt32LE(96000, 28); b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34); b.write('data', 36); b.writeUInt32LE(n * 2, 40);
  for (let i = 0; i < n; i++) b.writeInt16LE(Math.round(Math.sin(2 * Math.PI * 330 * i / 48000) * 0.5 * 32767), 44 + i * 2);
  fs.writeFileSync(f, b);
  const out = tmp('voiced');
  const r = await produceEpisode(storyFile({audio: {voice: [{source: f, sha256: sha(f), licence: 'test fixture', start: 0.5}]}}), {outDir: out, skipStoryboard: true});
  assert.equal(r.status, 'produced');
  assert.equal(r.report.audio.bed, 'mixed');
  assert.equal(json(path.join(out, 'project', 'project.json')).voice.path, 'audio-bed.wav');
  assert.equal(json(path.join(out, 'production-manifest.json')).inputs.audio[0].sha256, sha(f));
});

test('QA catches black frames, wrong format, truncated video and changed or missing inputs', needs, async () => {
  const out = tmp('black');
  const r = await produceEpisode(storyFile({captions: [{start: 0.1, end: 0.9, text: 'Test'}], endCard: {duration: 1.5, lines: [{text: '.', size: 20}], background: {type: 'solid', color: '#000000'}}}), {outDir: out, skipStoryboard: true});
  assert.equal(r.status, 'qa-failed');
  const black = json(path.join(out, 'reports', 'qa-report.json')).checks.find(c => c.id === 'black-frames');
  assert.equal(black.status, 'fail'); assert.ok(black.fix);
  const mp4 = path.join(out, 'render', 'tiny.mp4');
  assert.equal(qaVideo(mp4, {width: 720, height: 1280, fps: 30, duration: 3.5}).checks.find(c => c.id === 'resolution').status, 'fail');
  const cut = path.join(out, 'truncated.mp4'); fs.writeFileSync(cut, fs.readFileSync(mp4).subarray(0, Math.floor(fs.statSync(mp4).size / 2)));
  assert.equal(qaVideo(cut, {width: 1080, height: 1920, fps: 30, duration: 3.5}).status, 'fail');
  const proj = path.join(out, 'project'), asset = json(path.join(proj, 'project.json')).shots[0].layers.find(l => l.path.includes('assets/gen/')).path;
  fs.appendFileSync(path.join(proj, asset), Buffer.from([0]));
  assert.equal(qaProjectInputs(proj).checks.find(c => c.id === 'assets-match-manifest').status, 'fail');
  fs.unlinkSync(path.join(proj, asset));
  assert.equal(qaProjectInputs(proj).checks.find(c => c.id === 'assets-present').status, 'fail');
});

test('overwrite protection: existing runs need --replace; foreign folders are refused', needs, async () => {
  const out = tmp('ow'), story = storyFile();
  assert.equal((await produceEpisode(story, {outDir: out, skipRender: true, skipStoryboard: true})).status, 'built');
  await assert.rejects(produceEpisode(story, {outDir: out, skipRender: true}), /pass --replace/);
  assert.equal((await produceEpisode(story, {outDir: out, skipRender: true, skipStoryboard: true, replace: true})).status, 'built');
  const foreign = tmp('foreign'); fs.writeFileSync(path.join(foreign, 'keep.txt'), 'user file');
  await assert.rejects(produceEpisode(story, {outDir: foreign, replace: true}), /not created by "produce"/);
  assert.equal(fs.readFileSync(path.join(foreign, 'keep.txt'), 'utf8'), 'user file');
});
