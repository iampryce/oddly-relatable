// End-to-end production run (AP-82): story -> compiled renderer project -> audio bed -> storyboard -> MP4 (unmodified
// renderer) -> exported audio -> QA -> reports + manifest. Deterministic inputs, organised outputs, overwrite
// protection, clear stage-by-stage failure. A passing run is technical acceptance only; publication stays a human gate.
//
// Renderer gate (verified in autopilot.mjs): `preview` renders up to 60 s with no approval, so episodes <= 60 s are
// rendered in full by preview. Longer episodes need the renderer's human approval (`approve --note`) before `render`;
// this tool only passes on a note the owner supplies (--approval-note) and never writes approval itself.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {REPO_ROOT, SKILL_ROOT, assertWritableOutput} from './runtime.mjs';
import {compileProject, TOOLKIT_VERSION} from './scene.mjs';
import {storyboardSheet} from './preview.mjs';
import {audioPlan, buildAudioBed, measureAudio, tools, run} from './audio.mjs';
import {qaVideo, qaProjectInputs} from './qa.mjs';

const MARKER = 'production-run.json';
const PREVIEW_LIMIT = 60;
const sha = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const fileEntry = (f, base) => ({path: path.relative(base, f).split(path.sep).join('/'), bytes: fs.statSync(f).size, sha256: sha(f)});

function renderer(args) {
  const r = spawnSync(process.execPath, [path.join(SKILL_ROOT, 'scripts', 'autopilot.mjs'), ...args], {encoding: 'utf8', env: process.env, maxBuffer: 64 * 1024 * 1024});
  if (r.status !== 0) throw new Error(`renderer ${args[0]} failed: ${(r.stderr || r.stdout || '').trim().slice(-1500)}`);
  const out = r.stdout.trim().split('\n'), start = out.findIndex(l => l.startsWith('{') && !l.startsWith('{"shot"'));
  return start >= 0 ? JSON.parse(out.slice(start).join('\n')) : {};
}
function gitState() {
  const g = a => spawnSync('git', a, {cwd: REPO_ROOT, encoding: 'utf8'});
  const head = g(['rev-parse', 'HEAD']), dirty = g(['status', '--porcelain', '--', 'production', 'skills']);
  return head.status === 0 ? {head: head.stdout.trim(), toolkitOrRendererDirty: Boolean(dirty.stdout.trim())} : {head: null};
}

// Output folder policy: new or empty folder; an earlier run of this tool only with replace; anything else refused.
function prepareOut(outDir, replace) {
  const dir = assertWritableOutput(outDir);
  if (fs.existsSync(dir) && fs.readdirSync(dir).length) {
    if (!fs.existsSync(path.join(dir, MARKER))) throw new Error(`${dir} is not empty and was not created by "produce"; choose a new folder`);
    if (!replace) throw new Error(`${dir} already holds a production run; pass --replace to overwrite it`);
  }
  for (const d of ['project', 'storyboard', 'render', 'audio', 'reports']) fs.mkdirSync(path.join(dir, d), {recursive: true});
  return dir;
}

export async function produceEpisode(storyFile, {outDir, replace = false, allowIssues = false, skipRender = false, skipStoryboard = false, approvalNote = null} = {}) {
  const t0 = Date.now(), stages = [];
  // Each stage is recorded as "running" when it starts and saved, so a watcher (the studio) can show live progress.
  const stage = async (name, fn) => {
    const s = Date.now(), entry = {stage: name, status: 'running'};
    stages.push(entry); save();
    try { const r = await fn(); entry.status = 'done'; entry.seconds = +((Date.now() - s) / 1000).toFixed(1); save(); return r; }
    catch (e) { entry.status = 'failed'; entry.error = e.message; e.stage = name; throw e; }
  };
  const storyPath = path.resolve(storyFile);
  if (!fs.existsSync(storyPath)) throw new Error(`Story file not found: ${storyFile}`);
  const story = JSON.parse(fs.readFileSync(storyPath, 'utf8'));
  const dir = prepareOut(outDir, replace);
  const id = String(story.id || 'episode').replace(/[^a-z0-9-]/gi, '-');
  const projectDir = path.join(dir, 'project');
  const report = {tool: 'oddly-relatable produce', version: TOOLKIT_VERSION, story: path.relative(REPO_ROOT, storyPath).split(path.sep).join('/'), id, status: 'running', startedAt: new Date().toISOString(), stages};
  const save = () => fs.writeFileSync(path.join(dir, MARKER), JSON.stringify(report, null, 1) + '\n');
  save();
  try {
    if (!skipRender) await stage('environment', () => tools());

    // 1. Compile (validates the story, resolves characters and environments by ID, verifies their hashes).
    const built = await stage('compile', () => compileProject(storyPath, {outDir: projectDir, allowIssues}));
    const duration = built.report.duration, fmt = JSON.parse(fs.readFileSync(built.projectFile, 'utf8'));

    // 2. Audio bed: optional approved voice/music, else silence; the renderer adds its built-in SFX on top.
    const audio = await stage('audio', () => {
      const plan = audioPlan(story.audio, duration);
      if (!plan.voice.length && !plan.music) return {kind: 'silent', plan, bed: fmt.voice.path};
      const bed = buildAudioBed(plan, path.join(projectDir, 'audio-bed.wav'));
      fmt.voice = {...fmt.voice, path: 'audio-bed.wav'};
      fs.writeFileSync(built.projectFile, JSON.stringify(fmt, null, 1) + '\n');
      return {kind: bed.kind, plan, bed: 'audio-bed.wav'};
    });

    // 3. Storyboard (renderer-exact stills).
    if (!skipStoryboard) await stage('storyboard', () => storyboardSheet(built.projectFile, built.report.storyboardTimes, {outFile: path.join(dir, 'storyboard', 'storyboard-sheet.png'), framesDir: path.join(dir, 'storyboard', 'frames')}));

    report.layout = {ok: built.report.checks.ok, issues: built.report.checks.issues, warnings: built.report.checks.warnings};
    fs.copyFileSync(path.join(projectDir, 'layout-report.json'), path.join(dir, 'reports', 'layout-report.json'));
    if (skipRender) { report.status = 'built'; return finishRun(); }

    // 4. Render with the UNMODIFIED renderer.
    const video = await stage('render', () => {
      const full = duration <= PREVIEW_LIMIT + 1e-9;
      if (full) {
        const r = renderer(['preview', built.projectFile, '--seconds', String(duration), '--replace']);
        return {mode: `renderer preview covering the full ${duration} s`, file: r.output, renderer: r};
      }
      renderer(['preview', built.projectFile, '--seconds', String(PREVIEW_LIMIT), '--replace']);
      if (!approvalNote) { report.awaiting = 'Episode is longer than 60 s: the renderer requires the owner\'s approval of the 60 s preview. Re-run with --approval-note "<owner\'s words>" after review.'; return null; }
      renderer(['approve', built.projectFile, '--note', approvalNote]);
      const r = renderer(['render', built.projectFile, '--replace']);
      return {mode: 'renderer full render after owner approval of the preview', file: r.output, renderer: r};
    });
    if (!video) { report.status = 'awaiting-approval'; return finishRun(); }
    const mp4 = path.join(dir, 'render', `${id}.mp4`);
    fs.copyFileSync(video.file, mp4);

    // 5. Export the final mixed audio exactly as it is in the MP4.
    const wav = path.join(dir, 'audio', `${id}.wav`);
    await stage('audio-export', () => run(tools().ffmpeg, ['-v', 'error', '-y', '-i', mp4, '-vn', '-c:a', 'pcm_s16le', wav]));

    // 6. QA.
    const qa = await stage('qa', () => {
      const v = qaVideo(mp4, {width: fmt.width, height: fmt.height, fps: fmt.fps, duration, expectAudioActivity: (fmt.sfx?.length || 0) > 0 || audio.kind !== 'silent'});
      const inputs = qaProjectInputs(projectDir);
      const m = measureAudio(wav);
      const audioChecks = [
        {id: 'audio-file', status: m.hasAudio ? 'pass' : 'fail', detail: m.hasAudio ? `${m.codec}, ${m.sampleRate} Hz, ${m.channels} ch` : 'no audio'},
        {id: 'audio-duration', status: m.hasAudio && Math.abs(m.duration - duration) <= 1 / fmt.fps + 0.05 ? 'pass' : 'fail', detail: `${m.duration?.toFixed?.(3)} s (expected ${duration} s)`},
      ];
      const layout = [
        {id: 'layout', status: built.report.checks.ok ? 'pass' : 'fail', detail: built.report.checks.ok ? 'no layout issues' : `${built.report.checks.issues.length} issue(s)`},
        ...built.report.checks.warnings.map((w, i) => ({id: `quality-warning-${i + 1}`, status: 'warn', detail: w})),
      ];
      const checks = [...inputs.checks, ...v.checks, ...audioChecks, ...layout];
      const failed = checks.filter(c => c.status === 'fail').length;
      return {status: failed ? 'fail' : 'pass', failed, warnings: checks.filter(c => c.status === 'warn').length, checks,
        note: 'Technical QA only. Publication requires the owner\'s review and approval.'};
    });
    fs.writeFileSync(path.join(dir, 'reports', 'qa-report.json'), JSON.stringify(qa, null, 1) + '\n');
    report.render = {mode: video.mode, frames: video.renderer.frames, rendererDecode: video.renderer.full_decode};
    report.qa = {status: qa.status, failed: qa.failed, warnings: qa.warnings};
    report.audio = {bed: audio.kind, voiceClips: audio.plan.voice.length, music: Boolean(audio.plan.music), sfxCues: fmt.sfx?.length || 0};
    report.status = qa.status === 'pass' ? 'produced' : 'qa-failed';
    return finishRun();
  } catch (e) {
    report.status = 'failed'; report.error = {stage: e.stage || 'setup', message: e.message};
    save();
    throw new Error(`produce failed at stage "${e.stage || 'setup'}": ${e.message}`);
  }

  function finishRun() {
    report.finishedAt = new Date().toISOString();
    report.seconds = +((Date.now() - t0) / 1000).toFixed(1);
    report.humanApproval = 'required before any publication; not granted by this run';
    // Manifest: inputs (story, registries, environments, audio sources, copied artwork) and every output, with hashes.
    const compiled = JSON.parse(fs.readFileSync(path.join(projectDir, 'production-manifest.json'), 'utf8'));
    const regs = new Set(), envs = path.join(REPO_ROOT, 'production', 'environments', 'environments.json');
    for (const sc of story.scenes || []) for (const m of sc.cast || []) regs.add(m.registry ? path.resolve(REPO_ROOT, m.registry) : path.join(REPO_ROOT, 'production', 'characters', `${m.character}.json`));
    const outputs = [];
    for (const sub of ['render', 'audio', 'storyboard', 'reports']) {
      const d = path.join(dir, sub);
      if (fs.existsSync(d)) for (const f of fs.readdirSync(d)) { const p = path.join(d, f); if (fs.statSync(p).isFile()) outputs.push(fileEntry(p, dir)); }
    }
    outputs.push(fileEntry(path.join(projectDir, 'project.json'), dir));
    const rendererScripts = Object.fromEntries(fs.readdirSync(path.join(SKILL_ROOT, 'scripts')).filter(f => f.endsWith('.mjs')).map(f => [f, sha(path.join(SKILL_ROOT, 'scripts', f))]));
    let ffmpegVersion = null;
    try { ffmpegVersion = run(tools().ffmpeg, ['-version']).stdout.split('\n')[0]; } catch {}
    const manifest = {
      tool: report.tool, version: TOOLKIT_VERSION, id, status: report.status, git: gitState(), node: process.version, ffmpeg: ffmpegVersion,
      inputs: {
        story: fileEntry(storyPath, REPO_ROOT),
        characterRegistries: [...regs].filter(f => fs.existsSync(f)).map(f => fileEntry(f, REPO_ROOT)),
        environmentRegistry: fs.existsSync(envs) ? fileEntry(envs, REPO_ROOT) : null,
        artwork: compiled.sources, audio: (story.audio ? [...(story.audio.voice || []), ...(story.audio.music ? [story.audio.music] : [])].map(a => ({source: a.source, sha256: a.sha256, licence: a.licence})) : []),
      },
      generatedGraphics: compiled.generated, outputs, rendererScripts,
    };
    fs.writeFileSync(path.join(dir, 'production-manifest.json'), JSON.stringify(manifest, null, 1) + '\n');
    save();
    return {status: report.status, dir, report, manifest};
  }
}
