// Audio assembly (AP-82). Builds the episode's audio "bed" (optional voice clips + optional music) as one WAV of the
// exact episode length, which the renderer uses as its voice track; the renderer then mixes in its built-in
// synthesized SFX (chime/pop/...) at the cue times. Nothing here invents, downloads or generates audio content:
// voice and music are OPTIONAL inputs that must be existing local files with a recorded SHA-256 and licence.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {REPO_ROOT} from './runtime.mjs';
import {silentWav} from './wav.mjs';

export const AUDIO_DEFAULTS = Object.freeze({sampleRate: 48000, limit: 0.89, musicGain: 0.15, voiceGain: 1.0});
const sha = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');

export function tools() {
  const ffmpeg = process.env.FFMPEG, ffprobe = process.env.FFPROBE;
  if (!ffmpeg || !ffprobe) throw new Error('Set the FFMPEG and FFPROBE environment variables (paths to ffmpeg and ffprobe) before producing');
  return {ffmpeg, ffprobe};
}
export function run(exe, args) {
  const r = spawnSync(exe, args, {encoding: 'utf8', maxBuffer: 64 * 1024 * 1024});
  if (r.error || r.status !== 0) throw new Error(`${path.basename(exe)} failed: ${(r.error?.message || r.stderr || '').slice(-1500)}`);
  return {stdout: r.stdout, stderr: r.stderr};
}
export function probe(file) {
  const {ffprobe} = tools();
  return JSON.parse(run(ffprobe, ['-v', 'error', '-show_format', '-show_streams', '-of', 'json', file]).stdout);
}

// Validate one optional source: local file, recorded hash, licence note, sane gain.
function source(entry, where, repoRoot) {
  if (!entry || typeof entry !== 'object') throw new Error(`${where}: must be an object`);
  if (typeof entry.source !== 'string') throw new Error(`${where}: "source" (local file path) is required`);
  if (/^[a-z]+:\/\//i.test(entry.source)) throw new Error(`${where}: remote sources are not allowed; use an approved local file`);
  if (typeof entry.licence !== 'string' || !entry.licence.trim()) throw new Error(`${where}: "licence" is required (record where the audio comes from and that its use is approved)`);
  if (!/^[0-9a-f]{64}$/.test(entry.sha256 || '')) throw new Error(`${where}: "sha256" of the approved file is required`);
  const file = path.resolve(repoRoot, entry.source);
  if (!fs.existsSync(file)) throw new Error(`${where}: missing audio file ${entry.source}`);
  if (sha(file) !== entry.sha256) throw new Error(`${where}: ${entry.source} does not match its recorded SHA-256`);
  const info = probe(file);
  if (!info.streams.some(s => s.codec_type === 'audio')) throw new Error(`${where}: ${entry.source} has no audio stream`);
  return {file, rel: entry.source, sha256: entry.sha256, licence: entry.licence, duration: Number(info.format.duration)};
}

// Turn story.audio into a checked plan. Absent sections are simply empty (silent bed).
export function audioPlan(storyAudio, duration, repoRoot = REPO_ROOT) {
  const a = storyAudio || {}, plan = {duration, voice: [], music: null};
  for (const [i, v] of (a.voice || []).entries()) {
    const s = source(v, `audio.voice[${i}]`, repoRoot);
    const start = Number(v.start ?? 0), gain = Number(v.gain ?? AUDIO_DEFAULTS.voiceGain);
    if (!(start >= 0) || start >= duration) throw new Error(`audio.voice[${i}]: start ${v.start} is outside the episode (0–${duration} s)`);
    if (!(gain > 0 && gain <= 2)) throw new Error(`audio.voice[${i}]: gain must be in (0, 2]`);
    if (start + s.duration > duration + 0.05) throw new Error(`audio.voice[${i}]: clip ends at ${(start + s.duration).toFixed(2)} s, after the episode ends (${duration} s)`);
    plan.voice.push({...s, start, gain});
  }
  if (a.music) {
    const s = source(a.music, 'audio.music', repoRoot), gain = Number(a.music.gain ?? AUDIO_DEFAULTS.musicGain);
    if (!(gain > 0 && gain <= 0.5)) throw new Error('audio.music: gain must be in (0, 0.5]');
    plan.music = {...s, gain, fadeIn: Number(a.music.fadeIn ?? 1), fadeOut: Number(a.music.fadeOut ?? 2), loop: a.music.loop !== false};
  }
  return plan;
}

// Write the bed WAV (48 kHz, 16-bit) of EXACTLY `duration` seconds. Silence when there is nothing to mix.
export function buildAudioBed(plan, outFile) {
  if (!plan.voice.length && !plan.music) {
    silentWav(outFile, plan.duration, AUDIO_DEFAULTS.sampleRate);
    return {file: outFile, kind: 'silent', tracks: 0};
  }
  const {ffmpeg} = tools(), D = plan.duration.toFixed(4);
  const args = ['-v', 'error', '-y', '-f', 'lavfi', '-i', `anullsrc=r=${AUDIO_DEFAULTS.sampleRate}:cl=stereo`];
  const labels = ['[0:a]'], filters = [`[0:a]atrim=0:${D}[base]`];
  labels[0] = '[base]';
  let idx = 1;
  for (const v of plan.voice) {
    args.push('-i', v.file);
    const ms = Math.round(v.start * 1000);
    filters.push(`[${idx}:a]aformat=sample_rates=${AUDIO_DEFAULTS.sampleRate}:channel_layouts=stereo,volume=${v.gain},adelay=${ms}|${ms}[v${idx}]`);
    labels.push(`[v${idx}]`); idx++;
  }
  if (plan.music) {
    if (plan.music.loop) args.push('-stream_loop', '-1');
    args.push('-i', plan.music.file);
    const fadeOutStart = Math.max(0, plan.duration - plan.music.fadeOut).toFixed(3);
    filters.push(`[${idx}:a]aformat=sample_rates=${AUDIO_DEFAULTS.sampleRate}:channel_layouts=stereo,atrim=0:${D},volume=${plan.music.gain},afade=t=in:d=${plan.music.fadeIn},afade=t=out:st=${fadeOutStart}:d=${plan.music.fadeOut}[m]`);
    labels.push('[m]');
  }
  // Sum without normalisation, then a limiter keeps peaks below -1 dBFS (no clipping).
  filters.push(`${labels.join('')}amix=inputs=${labels.length}:normalize=0:duration=first,alimiter=limit=${AUDIO_DEFAULTS.limit}:level=false,atrim=0:${D}[out]`);
  args.push('-filter_complex', filters.join(';'), '-map', '[out]', '-ar', String(AUDIO_DEFAULTS.sampleRate), '-c:a', 'pcm_s16le', '-t', D, outFile);
  run(ffmpeg, args);
  return {file: outFile, kind: 'mixed', tracks: plan.voice.length + (plan.music ? 1 : 0)};
}

// Measure an audio file: duration, channels, sample rate and peak level (dBFS) via ffmpeg's volumedetect.
export function measureAudio(file) {
  const {ffmpeg} = tools(), info = probe(file);
  const a = info.streams.find(s => s.codec_type === 'audio');
  if (!a) return {hasAudio: false};
  const {stderr} = run(ffmpeg, ['-v', 'info', '-i', file, '-map', '0:a:0', '-af', 'volumedetect', '-f', 'null', '-']);
  const max = stderr.match(/max_volume:\s*(-?[\d.]+|-inf) dB/), mean = stderr.match(/mean_volume:\s*(-?[\d.]+|-inf) dB/);
  const db = m => (!m || m[1] === '-inf' ? -Infinity : Number(m[1]));
  return {hasAudio: true, codec: a.codec_name, sampleRate: Number(a.sample_rate), channels: a.channels, duration: Number(a.duration ?? info.format.duration), peakDb: db(max), meanDb: db(mean)};
}
