// Automated QA for a produced episode (AP-82). Every check returns pass / fail / warn with an actionable message;
// the report is machine-readable. A passing QA is technical acceptance only, never publication approval.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {tools, run, probe, measureAudio} from './audio.mjs';

const sha = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');

// expect: {width, height, fps, duration, expectAudioActivity}
export function qaVideo(file, expect, {blackMinSeconds = 0.5, blackPixelThreshold = 0.06} = {}) {
  const checks = [];
  const add = (id, status, detail, fix) => checks.push({id, status, detail, ...(fix ? {fix} : {})});
  if (!fs.existsSync(file)) { add('file-exists', 'fail', `missing ${file}`, 'render the episode first'); return finish(checks); }
  add('file-exists', 'pass', `${fs.statSync(file).size} bytes`);
  let info;
  try { info = probe(file); } catch (e) { add('probe', 'fail', e.message, 'the file is not a readable video; re-render'); return finish(checks); }
  const v = info.streams.find(s => s.codec_type === 'video'), a = info.streams.find(s => s.codec_type === 'audio');
  if (!v) add('video-stream', 'fail', 'no video stream', 're-render'); else {
    add('video-codec', v.codec_name === 'h264' ? 'pass' : 'fail', v.codec_name);
    add('resolution', v.width === expect.width && v.height === expect.height ? 'pass' : 'fail', `${v.width}x${v.height} (expected ${expect.width}x${expect.height})`);
    const [n, d] = String(v.r_frame_rate).split('/').map(Number), fps = n / (d || 1);
    add('frame-rate', Math.abs(fps - expect.fps) < 1e-6 ? 'pass' : 'fail', `${fps} fps (expected ${expect.fps})`);
  }
  if (!a) add('audio-stream', 'fail', 'no audio stream', 'the renderer always muxes audio; re-render'); else add('audio-stream', 'pass', `${a.codec_name}, ${a.sample_rate} Hz, ${a.channels} ch`);
  const duration = Number(info.format.duration);
  add('duration', Math.abs(duration - expect.duration) <= 1 / expect.fps + 1e-6 ? 'pass' : 'fail', `${duration.toFixed(3)} s (expected ${expect.duration} s)`, 'check the voice/bed track length and shot coverage');

  // Exact frame count by reading every packet, then a full decode.
  const {ffmpeg, ffprobe} = tools();
  try {
    const out = JSON.parse(run(ffprobe, ['-v', 'error', '-count_packets', '-select_streams', 'v:0', '-show_entries', 'stream=nb_read_packets', '-of', 'json', file]).stdout);
    const frames = Number(out.streams[0].nb_read_packets), want = Math.round(expect.duration * expect.fps);
    add('frame-count', frames === want ? 'pass' : 'fail', `${frames} frames (expected ${want})`, 'missing or extra frames; re-render');
  } catch (e) { add('frame-count', 'fail', e.message); }
  try { run(ffmpeg, ['-v', 'error', '-i', file, '-f', 'null', '-']); add('full-decode', 'pass', 'every frame and audio packet decoded without errors'); }
  catch (e) { add('full-decode', 'fail', e.message, 'the file is corrupt or truncated; re-render'); }

  // Black frames: any run of near-black frames longer than blackMinSeconds fails.
  try {
    const {stderr} = run(ffmpeg, ['-v', 'info', '-i', file, '-vf', `blackdetect=d=${blackMinSeconds}:pix_th=${blackPixelThreshold}`, '-an', '-f', 'null', '-']);
    const spans = [...stderr.matchAll(/black_start:([\d.]+) black_end:([\d.]+)/g)].map(m => [Number(m[1]), Number(m[2])]);
    add('black-frames', spans.length ? 'fail' : 'pass', spans.length ? `black segments: ${spans.map(s => `${s[0]}–${s[1]} s`).join(', ')}` : `no black run ≥ ${blackMinSeconds} s`, spans.length ? 'check for missing layers or a missing background in those ranges' : null);
  } catch (e) { add('black-frames', 'fail', e.message); }

  // Audio level: no clipping; silence only allowed when the episode has no sound at all.
  if (a) {
    const m = measureAudio(file);
    add('audio-clipping', m.peakDb < -0.1 ? 'pass' : 'fail', `peak ${m.peakDb.toFixed(2)} dBFS`, 'lower music/voice gain');
    if (expect.expectAudioActivity) add('audio-activity', m.peakDb > -60 ? 'pass' : 'fail', `peak ${m.peakDb === -Infinity ? '-inf' : m.peakDb.toFixed(1)} dBFS`, 'SFX or bed expected but the track is silent');
  }
  return finish(checks);
}

// Every image/audio input referenced by the renderer project exists and matches the compile manifest.
export function qaProjectInputs(projectDir) {
  const checks = [];
  const project = JSON.parse(fs.readFileSync(path.join(projectDir, 'project.json'), 'utf8'));
  const manifest = JSON.parse(fs.readFileSync(path.join(projectDir, 'production-manifest.json'), 'utf8'));
  const known = new Map([...manifest.sources, ...manifest.generated].map(x => [x.path, x.sha256]));
  const paths = new Set([project.voice.path]);
  for (const s of project.shots) for (const l of s.layers) if (l.type === 'image') paths.add(l.path);
  const missing = [], mismatched = [];
  for (const p of paths) {
    const f = path.join(projectDir, p);
    if (!fs.existsSync(f)) { missing.push(p); continue; }
    if (known.has(p) && sha(f) !== known.get(p)) mismatched.push(p);
  }
  checks.push({id: 'assets-present', status: missing.length ? 'fail' : 'pass', detail: missing.length ? `missing: ${missing.join(', ')}` : `${paths.size} referenced files present`, ...(missing.length ? {fix: 'rebuild the project'} : {})});
  checks.push({id: 'assets-match-manifest', status: mismatched.length ? 'fail' : 'pass', detail: mismatched.length ? `changed after build: ${mismatched.join(', ')}` : 'all hashed inputs unchanged since build'});
  return finish(checks);
}

function finish(checks) {
  const failed = checks.filter(c => c.status === 'fail');
  return {status: failed.length ? 'fail' : 'pass', failed: failed.length, checks};
}
