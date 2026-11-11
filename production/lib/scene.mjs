// Scene compiler: conversation episode (structured data) -> renderer project folder.
// Output is a normal renderer project (project.json + assets + silent track) that the UNMODIFIED renderer
// validates, previews and renders. Source artwork is copied, never modified; every file is hashed.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {canvas, REPO_ROOT, designPlane, assertWritableOutput} from './runtime.mjs';
import {sequenceEpisode} from './conversation.mjs';
import {renderBubble, renderTypingShell, renderDot, renderHeader, renderTitleCard, renderShadow, BUBBLE_DEFAULTS} from './graphics.mjs';
import {stackLayout, bubbleX, dotKeys, checkLayout, LAYOUT_DEFAULTS} from './layout.mjs';
import {loadRegistry, poseInfo, reactionLayers, PLACEMENT_DEFAULTS} from './character.mjs';
import {PALETTE} from './palette.mjs';
import {silentWav} from './wav.mjs';

export const EPISODE_SCHEMA = 'oddly-relatable/conversation-episode@1';
export const TOOLKIT_VERSION = '1.0.0';
const MARKER = 'production-manifest.json';
const sha = buf => crypto.createHash('sha256').update(buf).digest('hex');
const r2 = v => +v.toFixed(2);

export async function compileEpisode(episodeOrFile, {outDir, repoRoot = REPO_ROOT, allowIssues = false} = {}) {
  const episodeFile = typeof episodeOrFile === 'string' ? path.resolve(episodeOrFile) : null;
  const ep = episodeFile ? JSON.parse(fs.readFileSync(episodeFile, 'utf8')) : episodeOrFile;
  if (ep.schema !== EPISODE_SCHEMA) throw new Error(`Episode schema must be "${EPISODE_SCHEMA}"`);
  if (!outDir) throw new Error('outDir is required');
  const dir = assertWritableOutput(outDir);
  if (fs.existsSync(path.join(dir, 'project.json')) && !fs.existsSync(path.join(dir, MARKER))) throw new Error(`${dir} holds a project not created by this toolkit; refusing to overwrite`);

  const fmt = {width: 1080, height: 1920, fps: 30, ...(ep.format || {})};
  const plane = designPlane(fmt.width, fmt.height), ppu = fmt.width / plane.width;
  const seq = sequenceEpisode({...ep, format: fmt});
  const layout = {...LAYOUT_DEFAULTS, ...(ep.layout || {}), safe: {...LAYOUT_DEFAULTS.safe, ...(ep.layout?.safe || {})}};
  const bubbleOpts = {...BUBBLE_DEFAULTS, ...(ep.bubbles || {})};

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
    sources.push({path: rel, source: path.relative(repoRoot, absFile).split(path.sep).join('/'), sha256: sha(buf)});
    return rel;
  };

  const layers = [];
  // 1. Background plate, scaled to cover the frame.
  if (ep.background?.path) {
    const abs = path.resolve(repoRoot, ep.background.path), img = await canvas.loadImage(abs);
    const s = Math.max(plane.width / img.width, plane.height / img.height), w = img.width * s, h = img.height * s;
    layers.push({type: 'image', path: copySource(abs, 'background'), x: r2((plane.width - w) * (ep.background.focusX ?? 0.5)), y: r2((plane.height - h) * (ep.background.focusY ?? 0.5)), w: r2(w)});
  }

  // 2. Character reactions beneath the conversation.
  let faceBoxes = [], characterDiagnostics = [];
  if (seq.poses.length) {
    if (!ep.character?.registry) throw new Error('Events reference poses but no character.registry is set');
    const registry = loadRegistry(path.resolve(repoRoot, ep.character.registry));
    const infos = new Map(), copied = new Map();
    for (const seg of seq.poses) if (!infos.has(seg.pose)) infos.set(seg.pose, await poseInfo(registry, seg.pose, repoRoot));
    const placement = {...PLACEMENT_DEFAULTS, ...(ep.character.placement || {})};
    if (placement.shadow) {
      const sw = placement.figureHeight * 0.36, sh = sw * 0.2;
      layers.push({type: 'image', path: writeGen('shadow', renderShadow({width: sw, height: sh, ppu})), x: r2(placement.feetX - sw / 2), y: r2(placement.feetY - sh * 0.55), w: r2(sw)});
    }
    const assetFor = info => { if (!copied.has(info.id)) copied.set(info.id, copySource(info.file, `pose-${info.id}`)); return copied.get(info.id); };
    const comp = reactionLayers(seq.poses, infos, placement, assetFor, ppu);
    layers.push(...comp.layers); faceBoxes = comp.faceBoxes; characterDiagnostics = comp.diagnostics;
    // Keep the chat zone clear of the highest face on screen.
    const faceTop = Math.min(...faceBoxes.map(f => f.y));
    layout.zoneBottom = Math.min(layout.zoneBottom, faceTop - 40);
  }

  // 3. Conversation header.
  let headerRect = null;
  if (ep.header) {
    const img = renderHeader({...ep.header, ppu});
    headerRect = {x: r2((plane.width - img.width) / 2), y: ep.header.y ?? 330, w: img.width, h: img.height};
    layers.push({type: 'image', path: writeGen('header', img), x: headerRect.x, y: headerRect.y, w: r2(img.width)});
  }

  // 4. Message bubbles and typing indicators, laid out as one stack.
  const items = [], art = new Map();
  for (const m of seq.messages) {
    const img = renderBubble({text: m.text, side: m.side, style: m.style || (m.side === 'left' ? 'her' : 'him'), ppu, ...bubbleOpts});
    art.set(m.id, {path: writeGen(`msg-${m.id}`, img), img});
    items.push({id: m.id, order: m.index, start: m.start, end: Infinity, width: img.width, height: img.height, x: bubbleX(m.side, img.width, plane, layout)});
  }
  const dot = renderDot({diameter: 20, ppu});
  const dotPath = writeGen('typing-dot', dot);
  for (const t of seq.typing) {
    const img = renderTypingShell({side: t.side, style: t.style || (t.side === 'left' ? 'her' : 'him'), ppu});
    art.set(t.id, {path: writeGen(`typing-${t.side}`, img), img});
    items.push({id: t.id, order: t.index, start: t.start, end: t.end, width: img.width, height: img.height, x: bubbleX(t.side, img.width, plane, layout)});
  }
  const stack = stackLayout(items, layout);
  for (const l of stack.layers) {
    const a = art.get(l.id);
    layers.push({type: 'image', path: a.path, x: r2(l.x), w: r2(a.img.width), from: l.from, ...(l.to !== undefined ? {to: +l.to.toFixed(3)} : {}), keys: l.keys});
    if (l.id.startsWith('t')) {
      const t = seq.typing.find(x => x.id === l.id);
      a.img.dots.forEach((d, i) => layers.push({type: 'image', path: dotPath, x: r2(l.x + d.x), w: r2(dot.width), from: l.from, to: +l.to.toFixed(3), keys: dotKeys(l.keys, d.y, t.start, t.end, i * 0.18)}));
    }
  }

  // 5. Hook text.
  let hookRect = null;
  if (seq.hook) {
    const hs = ep.hook.style || {};
    const img = renderTitleCard({lines: [{text: seq.hook.text, size: hs.size || 64, weight: 800, color: hs.color || PALETTE.cardInk}], width: hs.width || 1000, padding: hs.padding ?? 30, background: hs.background || {type: 'panel', color: PALETTE.card, outline: 5}, ppu});
    hookRect = {x: r2((plane.width - img.width) / 2), y: ep.hook.y ?? 150, w: img.width, h: img.height, from: seq.hook.start, to: seq.hook.start + seq.hook.duration};
    const fade = Math.min(0.25, seq.hook.duration / 4);
    layers.push({type: 'image', path: writeGen('hook', img), x: hookRect.x, y: hookRect.y, w: r2(img.width), from: seq.hook.start, to: +hookRect.to.toFixed(3),
      keys: [{t: seq.hook.start, alpha: 0}, {t: +(seq.hook.start + fade).toFixed(3), alpha: 1}, {t: +(hookRect.to - fade).toFixed(3), alpha: 1}, {t: +(hookRect.to - 0.001).toFixed(3), alpha: 0}]});
  }

  // 6. End card (full frame).
  if (seq.endCard) {
    const ec = seq.endCard;
    // When the end card carries the caption, give it a light footer band: the renderer draws B1 captions as dark text.
    const footer = ec.caption && !ep.captions?.length ? {height: 150, color: PALETTE.cream} : null;
    const img = renderTitleCard({lines: ec.lines || [{text: ep.title || 'The End', size: 84}], width: plane.width, height: plane.height, padding: 90, gap: 26, background: ec.background || {type: 'solid', color: PALETTE.card}, footer, ppu});
    layers.push({type: 'image', path: writeGen('endcard', img), x: 0, y: 0, w: plane.width, from: ec.start, keys: [{t: ec.start, alpha: 0}, {t: +(ec.start + 0.35).toFixed(3), alpha: 1}]});
  }

  // 7. Captions (the renderer requires at least one; single line each).
  const captions = ep.captions?.length ? ep.captions : (seq.endCard?.caption ? [{start: +(seq.endCard.start + 0.3).toFixed(3), end: +(seq.duration - 0.05).toFixed(3), text: seq.endCard.caption}] : null);
  if (!captions) throw new Error('The renderer requires at least one caption: set "captions" or "endCard.caption"');

  // 8. Silent track of the exact duration, then the renderer project.
  silentWav(path.join(dir, 'silent.wav'), seq.duration);
  const project = {version: 1, style: 'B1', grid: false, width: fmt.width, height: fmt.height, fps: fmt.fps,
    voice: {path: 'silent.wav', lead: 0, tail: 0}, captions, shots: [{start: 0, end: seq.duration, layers}], sfx: seq.sfx};
  fs.writeFileSync(path.join(dir, 'project.json'), JSON.stringify(project, null, 1) + '\n');

  // 9. Composition checks and provenance.
  const checks = checkLayout({snapshots: stack.snapshots, plane, faceBoxes, hook: hookRect, header: headerRect, safe: layout.safe});
  const soft = characterDiagnostics.filter(d => d.soft);
  const report = {
    episode: ep.id, title: ep.title, duration: seq.duration, fps: fmt.fps, plane, layout: {zoneTop: layout.zoneTop, zoneBottom: r2(layout.zoneBottom)},
    messages: seq.messages.map(m => ({id: m.id, speaker: m.speaker, start: m.start, text: m.text, lines: art.get(m.id).img.lines.length})),
    typing: seq.typing.map(t => ({id: t.id, speaker: t.speaker, start: t.start, end: t.end})),
    poses: seq.poses, sfx: seq.sfx, hook: seq.hook, endCard: seq.endCard && {start: seq.endCard.start, duration: seq.endCard.duration},
    character: characterDiagnostics,
    checks: {...checks, warnings: soft.map(d => `pose ${d.pose} is enlarged ${d.upscale}x (above the 1.7x softness limit)`)},
    storyboardTimes: storyboardTimes(seq),
  };
  fs.writeFileSync(path.join(dir, 'layout-report.json'), JSON.stringify(report, null, 1) + '\n');
  const manifest = {toolkit: 'oddly-relatable-production', version: TOOLKIT_VERSION, schema: EPISODE_SCHEMA, episode: ep.id,
    episodeFile: episodeFile ? path.relative(repoRoot, episodeFile).split(path.sep).join('/') : null, episodeSha256: sha(JSON.stringify(ep)),
    sources, generated, project: 'project.json', note: 'Sources are copies; originals are never modified.'};
  fs.writeFileSync(path.join(dir, MARKER), JSON.stringify(manifest, null, 1) + '\n');
  if (!checks.ok && !allowIssues) throw new Error(`Layout check failed: ${checks.issues.map(i => `${i.id}@${i.t}s ${i.problem}`).join('; ')}`);
  return {projectFile: path.join(dir, 'project.json'), report, manifest, sequence: seq};
}

// Good moments to inspect: mid-hook, each message once settled, mid-typing, mid end card.
export function storyboardTimes(seq) {
  const t = [];
  if (seq.hook) t.push({t: seq.hook.start + seq.hook.duration / 2, label: 'hook'});
  for (const m of seq.messages) t.push({t: m.start + Math.min(0.7, m.duration * 0.6), label: `${m.speaker}: ${m.text.slice(0, 28)}`});
  for (const ty of seq.typing) t.push({t: (ty.start + ty.end) / 2, label: `${ty.speaker} typing`});
  if (seq.endCard) t.push({t: seq.endCard.start + seq.endCard.duration / 2, label: 'end card'});
  return t.map(x => ({...x, t: +Math.min(x.t, seq.duration - 0.05).toFixed(3)})).sort((a, b) => a.t - b.t);
}
