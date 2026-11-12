// Story compiler: story (or AP-78 conversation episode) -> renderer project folder.
// One renderer shot per scene; each scene is compiled by its format strategy (see formats/). The hook overlays the
// first shot and the end card extends the last one. Output is a normal renderer project (project.json + assets +
// silent track) that the UNMODIFIED renderer validates, previews and renders. Source artwork is copied, never
// modified; every file is hashed in production-manifest.json.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {REPO_ROOT, designPlane, assertWritableOutput} from './runtime.mjs';
import {renderTitleCard} from './graphics.mjs';
import {PALETTE} from './palette.mjs';
import {silentWav} from './wav.mjs';
import {STORY_SCHEMA, EPISODE_SCHEMA, validateStory, episodeToStory, resolveEnvironment} from './story.mjs';
import {formatFor} from './formats/index.mjs';
import {assertRenderable} from './text.mjs';

export {EPISODE_SCHEMA, STORY_SCHEMA};
export const TOOLKIT_VERSION = '1.1.0';
const MARKER = 'production-manifest.json';
const sha = buf => crypto.createHash('sha256').update(buf).digest('hex');
const r2 = v => +v.toFixed(2);
const num = (v, name, min = 0, max = 600) => { if (!Number.isFinite(v) || v < min || v > max) throw new Error(`Invalid ${name}: ${v}`); return v; };

// Accepts a story file/object or an AP-78 conversation-episode file/object.
export async function compileProject(input, opts = {}) {
  const file = typeof input === 'string' ? path.resolve(input) : null;
  const data = file ? JSON.parse(fs.readFileSync(file, 'utf8')) : input;
  if (data.schema === EPISODE_SCHEMA) return compileStory(episodeToStory(data), {...opts, sourceFile: file, sourceData: data});
  return compileStory(data, {...opts, sourceFile: file, sourceData: data});
}
export const compileEpisode = compileProject;   // AP-78 name, kept for compatibility

export async function compileStory(story, {outDir, repoRoot = REPO_ROOT, allowIssues = false, sourceFile = null, sourceData = story} = {}) {
  validateStory(story);
  if (!outDir) throw new Error('outDir is required');
  const dir = assertWritableOutput(outDir);
  if (fs.existsSync(path.join(dir, 'project.json')) && !fs.existsSync(path.join(dir, MARKER))) throw new Error(`${dir} holds a project not created by this toolkit; refusing to overwrite`);

  const fmt = {width: 1080, height: 1920, fps: 30, ...(story.format || {})};
  const fps = fmt.fps, plane = designPlane(fmt.width, fmt.height), ppu = fmt.width / plane.width;
  const frame = t => Math.ceil(t * fps - 1e-6) / fps;   // round a time up to the frame grid

  // 1. Sequence every scene first (timing only), then lay scenes end to end as shots.
  const scenes = story.scenes.map(s => ({scene: s, strategy: formatFor(s.format)}));
  for (const x of scenes) { x.seq = x.strategy.sequence(x.scene); x.duration = frame(x.seq.duration); }
  const endCard = story.endCard ? {...story.endCard, hold: num(story.endCard.hold ?? 0, 'end card hold', 0, 10), duration: num(story.endCard.duration ?? 3, 'end card duration', 0.5, 15)} : null;
  let t0 = 0;
  scenes.forEach((x, i) => {
    x.start = t0;
    x.shotDuration = i === scenes.length - 1 && endCard ? frame(x.seq.duration + endCard.hold + endCard.duration) : x.duration;
    t0 += x.shotDuration;
  });
  const duration = t0, last = scenes.at(-1);
  if (endCard) endCard.start = +(last.start + last.seq.duration + endCard.hold).toFixed(3);

  fs.mkdirSync(path.join(dir, 'assets', 'gen'), {recursive: true});
  fs.mkdirSync(path.join(dir, 'assets', 'src'), {recursive: true});
  const generated = [], sources = [];
  const writeGen = (kind, img) => {
    const name = `${kind}-${sha(img.png).slice(0, 12)}.png`, rel = `assets/gen/${name}`;
    fs.writeFileSync(path.join(dir, rel), img.png);
    if (!generated.some(g => g.path === rel)) generated.push({path: rel, kind, sha256: sha(img.png)});
    return rel;
  };
  const copySource = (absFile, label) => {
    const buf = fs.readFileSync(absFile), rel = `assets/src/${label}-${path.basename(absFile)}`;
    fs.writeFileSync(path.join(dir, rel), buf);
    if (!sources.some(s => s.path === rel)) sources.push({path: rel, source: path.relative(repoRoot, absFile).split(path.sep).join('/'), sha256: sha(buf)});
    return rel;
  };

  // 2. Hook (story level, overlays the first shot).
  let hook = null, hookLayer = null;
  if (story.hook) {
    hook = {text: assertRenderable(story.hook.text, 'hook'), start: num(story.hook.start ?? 0, 'hook start'), duration: num(story.hook.duration ?? 2.5, 'hook duration', 0.5, 10)};
    if (hook.start + hook.duration > scenes[0].shotDuration + 1e-6) throw new Error('hook runs past the end of the first scene');
    const hs = story.hook.style || {};
    const img = renderTitleCard({lines: [{text: hook.text, size: hs.size || 64, weight: 800, color: hs.color || PALETTE.cardInk}], width: hs.width || 1000, padding: hs.padding ?? 30, background: hs.background || {type: 'panel', color: PALETTE.card, outline: 5}, ppu});
    hook.rect = {x: r2((plane.width - img.width) / 2), y: story.hook.y ?? 150, w: img.width, h: img.height, from: hook.start, to: hook.start + hook.duration};
    const fade = Math.min(0.25, hook.duration / 4);
    hookLayer = {type: 'image', path: writeGen('hook', img), x: hook.rect.x, y: hook.rect.y, w: r2(img.width), from: hook.start, to: +hook.rect.to.toFixed(3),
      keys: [{t: hook.start, alpha: 0}, {t: +(hook.start + fade).toFixed(3), alpha: 1}, {t: +(hook.rect.to - fade).toFixed(3), alpha: 1}, {t: +(hook.rect.to - 0.001).toFixed(3), alpha: 0}]};
  }

  // 3. Compile each scene with its strategy; layers are shot-relative, SFX absolute.
  const shots = [], sfx = [], sceneReports = [];
  for (const [i, x] of scenes.entries()) {
    const env = await resolveEnvironment(x.scene.environment, plane, repoRoot);
    const out = await x.strategy.compile({scene: x.scene, seq: x.seq, shotDuration: x.shotDuration, plane, ppu, fps, env, writeGen, copySource, hookRect: i === 0 && hook ? hook.rect : null, repoRoot});
    const layers = [...out.world, ...out.screen];
    if (i === 0 && hookLayer) layers.push(hookLayer);
    if (i === scenes.length - 1 && endCard) {
      // When the end card carries the caption, give it a light footer band: the renderer draws B1 captions as dark text.
      const footer = endCard.caption && !story.captions?.length ? {height: 150, color: PALETTE.cream} : null;
      const img = renderTitleCard({lines: endCard.lines || [{text: story.title || 'The End', size: 84}], width: plane.width, height: plane.height, padding: 90, gap: 26, background: endCard.background || {type: 'solid', color: PALETTE.card}, footer, ppu});
      const local = +(endCard.start - x.start).toFixed(3);
      layers.push({type: 'image', path: writeGen('endcard', img), x: 0, y: 0, w: plane.width, from: local, keys: [{t: local, alpha: 0}, {t: +(local + 0.35).toFixed(3), alpha: 1}]});
    }
    shots.push({start: +x.start.toFixed(4), end: +(x.start + x.shotDuration).toFixed(4), layers});
    sfx.push(...out.sfx.map(c => ({...c, time: +(c.time + x.start).toFixed(3)})));
    sceneReports.push({id: x.scene.id, format: x.scene.format, start: x.start, duration: x.shotDuration, seq: x.seq, out});
  }

  // 4. Captions (the renderer requires at least one; single line each).
  const captions = story.captions?.length ? story.captions : (endCard?.caption ? [{start: +(endCard.start + 0.3).toFixed(3), end: +(duration - 0.05).toFixed(3), text: endCard.caption}] : null);
  if (!captions) throw new Error('The renderer requires at least one caption: set "captions" or "endCard.caption"');

  // 5. Silent track of the exact duration, then the renderer project.
  silentWav(path.join(dir, 'silent.wav'), duration);
  const project = {version: 1, style: 'B1', grid: false, width: fmt.width, height: fmt.height, fps, voice: {path: 'silent.wav', lead: 0, tail: 0}, captions, shots, sfx: sfx.sort((a, b) => a.time - b.time)};
  fs.writeFileSync(path.join(dir, 'project.json'), JSON.stringify(project, null, 1) + '\n');

  // 6. Reports and provenance. Top-level fields describe the first scene (AP-78 compatible); all scenes are listed too.
  const first = sceneReports[0];
  const issues = sceneReports.flatMap(r => r.out.checks.issues.map(i => ({...i, scene: r.id})));
  const diagnostics = sceneReports.flatMap(r => r.out.diagnostics.map(d => ({...d, scene: r.id})));
  const warnings = [...new Set(diagnostics.filter(d => d.soft).map(d => `pose ${d.pose} (${d.cast}) is enlarged ${d.upscaleAtMaxZoom}x at the scene's largest zoom (above the 1.7x softness limit)`))];
  const report = {
    story: story.id, episode: story.id, title: story.title, duration, fps, plane,
    layout: {zoneTop: first.out.layout.zoneTop, zoneBottom: r2(first.out.layout.zoneBottom)},
    messages: first.seq.messages.map(m => ({id: m.id, speaker: m.speaker, start: m.start, text: m.text, lines: first.out.art.get(m.id).img.lines.length})),
    typing: first.seq.typing.map(t => ({id: t.id, speaker: t.speaker, start: t.start, end: t.end})),
    poses: first.seq.poses, sfx: project.sfx, hook: hook && {text: hook.text, start: hook.start, duration: hook.duration},
    endCard: endCard && {start: endCard.start, duration: endCard.duration},
    character: diagnostics,
    camera: sceneReports.map(r => ({scene: r.id, ...r.out.camera})),
    scenes: sceneReports.map(r => ({id: r.id, format: r.format, start: r.start, duration: r.duration, messages: r.seq.messages.length, typing: r.seq.typing.length, cast: Object.keys(r.seq.castPoses)})),
    checks: {ok: issues.length === 0, issues, warnings},
    storyboardTimes: storyboardTimes(sceneReports, hook, endCard, duration),
  };
  fs.writeFileSync(path.join(dir, 'layout-report.json'), JSON.stringify(report, null, 1) + '\n');
  const manifest = {toolkit: 'oddly-relatable-production', version: TOOLKIT_VERSION, schema: sourceData?.schema, story: story.id, episode: story.id,
    episodeFile: sourceFile ? path.relative(repoRoot, sourceFile).split(path.sep).join('/') : null, episodeSha256: sha(JSON.stringify(sourceData)),
    sources, generated, project: 'project.json', note: 'Sources are copies; originals are never modified.'};
  fs.writeFileSync(path.join(dir, MARKER), JSON.stringify(manifest, null, 1) + '\n');
  if (issues.length && !allowIssues) throw new Error(`Layout check failed: ${issues.map(i => `${i.id}@${i.t}s ${i.problem}`).join('; ')}`);
  return {projectFile: path.join(dir, 'project.json'), report, manifest, sequence: first.seq};
}

// Good moments to inspect: mid-hook, each message once settled, mid-typing, each camera cut/move, mid end card.
export function storyboardTimes(sceneReports, hook, endCard, duration) {
  const t = [];
  if (hook) t.push({t: hook.start + hook.duration / 2, label: 'hook'});
  for (const r of sceneReports) {
    const o = r.start, seq = r.seq;
    for (const m of seq.messages) t.push({t: o + m.start + Math.min(0.7, m.duration * 0.6), label: `${m.speaker}: ${m.text.slice(0, 28)}`});
    for (const ty of seq.typing) t.push({t: o + (ty.start + ty.end) / 2, label: `${ty.speaker} typing`});
    for (const mv of r.out.camera.moves) t.push({t: o + (mv.start + mv.end) / 2, label: `camera ${mv.from}x to ${mv.to}x (move)`});
  }
  if (endCard) t.push({t: endCard.start + endCard.duration / 2, label: 'end card'});
  const out = t.map(x => ({...x, t: +Math.min(x.t, duration - 0.05).toFixed(3)})).sort((a, b) => a.t - b.t);
  return out.filter((x, i) => i === 0 || Math.abs(x.t - out[i - 1].t) > 0.05);
}
