// Scene format strategy: text-message conversation (implemented).
// World layers (environment, cast) go through the camera; chat UI (header, bubbles, typing) stays in screen space.
import {sequenceConversation} from '../conversation.mjs';
import {renderBubble, renderTypingShell, renderDot, renderHeader, renderShadow, BUBBLE_DEFAULTS} from '../graphics.mjs';
import {stackLayout, bubbleX, dotKeys, checkLayout, LAYOUT_DEFAULTS} from '../layout.mjs';
import {resolveCast} from '../cast.mjs';
import {buildCameraTrack, cameraAt, applyCamera, CAMERA_DEFAULTS} from '../camera.mjs';
import {planPoseLayers, castLayers, worldLayer, poseRect, scaleAt, alphaAt} from '../timeline.mjs';

const r2 = v => +v.toFixed(2);

export const textChat = {
  id: 'text-chat',
  implemented: true,
  description: 'Text-message conversation: message bubbles, typing indicator, header, character reactions beneath.',

  // Timing only (no files written): lets the story compiler lay scenes end to end first.
  sequence(scene) {
    const reactionCast = scene.reactionCast ?? scene.cast?.[0]?.id ?? 'primary';
    const seq = sequenceConversation(scene, {defaultCast: reactionCast});
    return {...seq, reactionCast, duration: seq.conversationEnd};
  },

  async compile({scene, seq, shotDuration, plane, ppu, fps, env, writeGen, copySource, hookRect, repoRoot}) {
    const layout = {...LAYOUT_DEFAULTS, ...(scene.layout || {}), safe: {...LAYOUT_DEFAULTS.safe, ...(scene.layout?.safe || {})}};
    const bubbleOpts = {...BUBBLE_DEFAULTS, ...(scene.bubbles || {})};
    const world = [], screen = [], issues = [];

    // 1. Cast (resolved by character ID) and their pose segments for this shot.
    for (const list of Object.values(seq.castPoses)) for (const p of list) if (!Number.isFinite(p.end) || p.end > shotDuration) p.end = shotDuration;
    const cast = await resolveCast(scene.cast || [], seq.castPoses, repoRoot);

    // 2. Camera: zoom about the focus member's head top, so the face never rises into the chat zone.
    const camOpts = {...CAMERA_DEFAULTS, ...(scene.camera || {})};
    const track = buildCameraTrack(seq.camera, camOpts);
    const focus = cast.find(m => m.id === (scene.camera?.focus ?? seq.reactionCast)) || cast[0];
    const pivot = focus ? {x: focus.placement.feetX, y: focus.placement.feetY - focus.placement.figureHeight} : {x: plane.width / 2, y: plane.height / 2};
    const coverRect = env?.rect || null;
    const camCache = new Map();
    const cameraFor = t => { const key = Math.round(t * fps); if (!camCache.has(key)) camCache.set(key, cameraAt(track, key / fps, {pivot, plane, coverRect})); return camCache.get(key); };

    // 3. World layers: environment, then cast members in z order (shadow under each).
    if (env) world.push(worldLayer({path: copySource(env.file, 'background'), rect: env.rect, cameraFor, from: 0, to: shotDuration, fps}));
    const diagnostics = [], members = [];
    for (const m of cast) {
      if (m.placement.shadow) {
        const sw = m.placement.figureHeight * 0.36, sh = sw * 0.2;
        const img = renderShadow({width: sw, height: sh, ppu});
        world.push(worldLayer({path: writeGen('shadow', img), rect: {x: m.placement.feetX - sw / 2, y: m.placement.feetY - sh * 0.55, w: sw}, cameraFor, from: 0, to: shotDuration, fps}));
      }
      const plans = planPoseLayers(m.segments, scene.transitions || {});
      const copied = new Map();
      const assetFor = info => { if (!copied.has(info.id)) copied.set(info.id, copySource(info.file, `${m.character}-pose-${info.id}`)); return copied.get(info.id); };
      world.push(...castLayers({plans, infos: m.infos, placement: m.placement, cameraFor, fps, assetPathFor: assetFor}));
      members.push({m, plans});
      const zMax = Math.max(track.initialZoom, ...track.cuts.map(c => c.to), ...track.moves.map(v => v.to));
      for (const s of m.segments) {
        const info = m.infos.get(s.pose), k = m.placement.figureHeight / info.figureHeight;
        diagnostics.push({cast: m.id, character: m.character, pose: s.pose, from: s.start, to: s.end, transition: s.transition, upscale: +(k * ppu).toFixed(2), upscaleAtMaxZoom: +(k * ppu * zMax).toFixed(2), soft: k * ppu * zMax > m.placement.maxUpscale, status: info.status});
      }
    }

    // 4. Per-frame face check (camera + transitions applied): stays in frame; highest face sets the chat zone bottom.
    let minFaceTop = Infinity;
    const frames = Math.ceil(shotDuration * fps - 1e-6);
    for (let f = 0; f < frames; f++) {
      const t = f / fps, cam = cameraFor(t);
      for (const {m, plans} of members) for (const plan of plans) {
        if (t < plan.from || t >= plan.to || alphaAt(plan, t) <= 0) continue;
        const info = m.infos.get(plan.pose), s = scaleAt(plan, t), rect = poseRect(info, m.placement, s);
        const top = m.placement.feetY - m.placement.figureHeight * s;
        const face = applyCamera(cam, {x: rect.x, y: top, w: rect.w});
        const faceH = m.placement.figureHeight * (info.headFraction ?? 0.42) * s * cam.z;
        minFaceTop = Math.min(minFaceTop, face.y);
        if (face.x < -1 || face.x + face.w > plane.width + 1 || face.y < -1 || face.y + faceH > plane.height + 1) issues.push({t: +t.toFixed(3), id: m.id, problem: `face of pose ${plan.pose} is cropped by the camera`});
      }
    }
    if (Number.isFinite(minFaceTop)) layout.zoneBottom = Math.min(layout.zoneBottom, minFaceTop - 40);

    // 5. Screen-space chat UI (never transformed by the camera).
    let headerRect = null;
    if (scene.header) {
      const img = renderHeader({...scene.header, ppu});
      headerRect = {x: r2((plane.width - img.width) / 2), y: scene.header.y ?? 330, w: img.width, h: img.height};
      screen.push({type: 'image', path: writeGen('header', img), x: headerRect.x, y: headerRect.y, w: r2(img.width)});
    }
    const items = [], art = new Map();
    for (const msg of seq.messages) {
      const img = renderBubble({text: msg.text, side: msg.side, style: msg.style || (msg.side === 'left' ? 'her' : 'him'), ppu, ...bubbleOpts});
      art.set(msg.id, {path: writeGen(`msg-${msg.id}`, img), img});
      items.push({id: msg.id, order: msg.index, start: msg.start, end: Infinity, width: img.width, height: img.height, x: bubbleX(msg.side, img.width, plane, layout)});
    }
    const dot = renderDot({diameter: 20, ppu});
    const dotPath = seq.typing.length ? writeGen('typing-dot', dot) : null;
    for (const ty of seq.typing) {
      const img = renderTypingShell({side: ty.side, style: ty.style || (ty.side === 'left' ? 'her' : 'him'), ppu});
      art.set(ty.id, {path: writeGen(`typing-${ty.side}`, img), img});
      items.push({id: ty.id, order: ty.index, start: ty.start, end: ty.end, width: img.width, height: img.height, x: bubbleX(ty.side, img.width, plane, layout)});
    }
    const stack = stackLayout(items, layout);
    for (const l of stack.layers) {
      const a = art.get(l.id);
      screen.push({type: 'image', path: a.path, x: r2(l.x), w: r2(a.img.width), from: l.from, ...(l.to !== undefined ? {to: +l.to.toFixed(3)} : {}), keys: l.keys});
      if (l.id.startsWith('t')) {
        const ty = seq.typing.find(x => x.id === l.id);
        a.img.dots.forEach((d, i) => screen.push({type: 'image', path: dotPath, x: r2(l.x + d.x), w: r2(dot.width), from: l.from, to: +l.to.toFixed(3), keys: dotKeys(l.keys, d.y, ty.start, ty.end, i * 0.18)}));
      }
    }

    const checks = checkLayout({snapshots: stack.snapshots, plane, faceBoxes: [], hook: hookRect, header: headerRect, safe: layout.safe});
    return {
      world, screen, sfx: seq.sfx, art, stack, layout,
      checks: {ok: checks.ok && !issues.length, issues: [...checks.issues, ...dedupe(issues)], safeZone: checks.safeZone},
      diagnostics,
      camera: {pivot, notes: seq.camera.map(c => ({start: c.start, end: c.end, note: c.note})), cuts: track.cuts, moves: track.moves, shakes: track.shakes, drifts: track.drifts},
    };
  },
};

// Collapse per-frame issues into one entry per (id, problem) with first/last time.
function dedupe(issues) {
  const m = new Map();
  for (const i of issues) { const k = `${i.id}|${i.problem}`; const e = m.get(k); if (e) e.last = i.t; else m.set(k, {...i, last: i.t}); }
  return [...m.values()];
}
