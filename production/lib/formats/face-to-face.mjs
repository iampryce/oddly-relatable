// Scene format strategy: face-to-face dialogue (AP-85 P1).
// Several cast members share one environment and talk to each other. Each line is spoken by a cast member, shown as a
// screen-space speech bubble styled from THAT member's speech configuration, and framed by an explicit shot: wide, or
// medium / close on a named cast member (shot / reverse-shot). World layers (environment, shadows, cast) go through the
// camera; bubbles never do.
//
// Scene fields:
//   cast:  [{id, character, registry?, placement, z, facing?, speech: {style, side}}]   (speech is required to speak)
//   lines: [{speaker: castId, text, duration?, pose?: poseId (the speaker's), poses?: {castId: poseId},
//            transition?: cut|pop|crossfade, shot: {camera: 'Wide' | 'Medium N×' | 'Close' | 'Hold', focus?: castId}}]
//   camera?: {maxZoom, mediumZoom}, bubbles?, timing?, layout?: {bubbleY, marginX, safe}
// Every cast member needs a pose on the first line. Medium and close shots need a focus. Camera moves, shake and drift
// are not part of this format yet and are refused, not approximated.
import {sequenceConversation} from '../conversation.mjs';
import {renderBubble, renderShadow, BUBBLE_DEFAULTS} from '../graphics.mjs';
import {bubbleX, LAYOUT_DEFAULTS} from '../layout.mjs';
import {resolveCast, validateCast} from '../cast.mjs';
import {cameraAt, applyCamera, parseCameraNote, CAMERA_DEFAULTS} from '../camera.mjs';
import {planPoseLayers, castLayers, worldLayer, poseRect, scaleAt, alphaAt} from '../timeline.mjs';

export const FACE_TO_FACE_DEFAULTS = Object.freeze({bubbleY: 300, marginX: LAYOUT_DEFAULTS.marginX, safe: LAYOUT_DEFAULTS.safe});
const r2 = v => +v.toFixed(2);
const EPS = 1e-9;
const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

export const faceToFace = {
  id: 'face-to-face',
  implemented: true,
  description: 'Face-to-face dialogue: several characters in one environment, speech bubbles per speaker, shot/reverse-shot camera.',

  // Timing and validation only (no files written).
  sequence(scene) {
    const cast = validateCast(scene.cast || []);
    if (!cast.length) throw new Error('face-to-face: at least one cast member is required');
    if (!Array.isArray(scene.lines) || !scene.lines.length) throw new Error('face-to-face: lines[] is required');
    const byId = new Map(cast.map(m => [m.id, m]));
    const camOpts = {...CAMERA_DEFAULTS, ...(scene.camera || {})};
    const speakers = {};
    for (const m of cast) if (m.speech) speakers[m.id] = {side: m.speech.side, cast: m.id};
    let zoom = null;
    const shots = [];
    const events = scene.lines.map((l, i) => {
      const where = `line ${i + 1}`;
      if (!l || typeof l !== 'object') throw new Error(`${where}: must be an object`);
      if (!byId.has(l.speaker)) throw new Error(`${where}: speaker "${l.speaker}" is not a cast member of this scene`);
      if (!speakers[l.speaker]) throw new Error(`${where}: cast member "${l.speaker}" has no "speech" configuration ({style, side})`);
      if (!l.shot || typeof l.shot.camera !== 'string') throw new Error(`${where}: "shot" with a camera framing is required (e.g. {camera: "Wide"})`);
      const a = parseCameraNote(l.shot.camera, camOpts);
      if (a.move || a.shake || a.drift) throw new Error(`${where}: face-to-face shots support wide / medium N× / close / hold framings only (no moves, shake or drift)`);
      if (a.framing) zoom = a.framing.zoom;
      else if (zoom === null) throw new Error(`${where}: the first shot needs a framing (wide, medium or close)`);
      if (l.shot.focus !== undefined && !byId.has(l.shot.focus)) throw new Error(`${where}: shot focus "${l.shot.focus}" is not a cast member of this scene`);
      if (zoom > 1 + EPS && l.shot.focus === undefined) throw new Error(`${where}: a medium or close shot needs a "focus" cast member`);
      const poses = {...(l.poses || {})};
      if (l.pose !== undefined) poses[l.speaker] = l.pose;
      for (const id of Object.keys(poses)) if (!byId.has(id)) throw new Error(`${where}: pose for "${id}", which is not a cast member of this scene`);
      shots.push({line: i + 1, speaker: l.speaker, focus: l.shot.focus ?? null, zoom, note: l.shot.camera});
      return {type: 'message', speaker: l.speaker, text: l.text, ...(l.duration !== undefined ? {duration: l.duration} : {}), ...(Object.keys(poses).length ? {poses} : {}), ...(l.transition ? {transition: l.transition} : {})};
    });
    const seq = sequenceConversation({speakers, cast, timing: scene.timing, events}, {defaultCast: null});
    for (const m of cast) if (!seq.castPoses[m.id]) throw new Error(`cast member "${m.id}" has no pose: give every cast member a pose on the first line`);
    seq.messages.forEach((msg, i) => { shots[i].start = msg.start; shots[i].end = msg.start + msg.duration; });
    return {...seq, shots, reactionCast: null, duration: seq.conversationEnd};
  },

  async compile({scene, seq, shotDuration, plane, ppu, fps, env, writeGen, copySource, hookRect, repoRoot, allowSynthetic = false}) {
    const o = {...FACE_TO_FACE_DEFAULTS, ...(scene.layout || {}), safe: {...FACE_TO_FACE_DEFAULTS.safe, ...(scene.layout?.safe || {})}};
    const bubbleOpts = {...BUBBLE_DEFAULTS, ...(scene.bubbles || {})};
    const world = [], screen = [], issues = [];

    // 1. Cast (resolved by character ID, facing resolved to declared artwork) and their pose segments.
    for (const list of Object.values(seq.castPoses)) for (const p of list) if (!Number.isFinite(p.end) || p.end > shotDuration) p.end = shotDuration;
    const cast = await resolveCast(scene.cast, seq.castPoses, repoRoot, {allowSynthetic});
    const byId = new Map(cast.map(m => [m.id, m]));

    // 2. Camera: one shot per line, zoomed about the focus member's head top (wide shots: the frame centre).
    const headTop = m => ({x: m.placement.feetX, y: m.placement.feetY - m.placement.figureHeight});
    const shots = seq.shots.map((s, i) => ({...s, end: i === seq.shots.length - 1 ? shotDuration : s.end,
      pivot: s.focus ? headTop(byId.get(s.focus)) : {x: plane.width / 2, y: plane.height / 2}}));
    const shotAt = t => shots.find(s => t >= s.start - EPS && t < s.end - EPS) || shots.at(-1);
    const coverRect = env?.rect || null, camCache = new Map();
    const cameraFor = t => {
      const key = Math.round(t * fps);
      if (!camCache.has(key)) {
        const s = shotAt(key / fps);
        camCache.set(key, cameraAt({cuts: [], moves: [], shakes: [], drifts: [], initialZoom: s.zoom}, key / fps, {pivot: s.pivot, plane, coverRect}));
      }
      return camCache.get(key);
    };

    // 3. World layers: environment, then cast members in z order (shadow under each).
    if (env) world.push(worldLayer({path: copySource(env.file, 'background'), rect: env.rect, cameraFor, from: 0, to: shotDuration, fps}));
    const diagnostics = [], members = [];
    const zMax = Math.max(...shots.map(s => s.zoom));
    for (const m of cast) {
      if (m.placement.shadow) {
        const sw = m.placement.figureHeight * 0.36, sh = sw * 0.2;
        world.push(worldLayer({path: writeGen('shadow', renderShadow({width: sw, height: sh, ppu})), rect: {x: m.placement.feetX - sw / 2, y: m.placement.feetY - sh * 0.55, w: sw}, cameraFor, from: 0, to: shotDuration, fps}));
      }
      const plans = planPoseLayers(m.segments, scene.transitions || {});
      const copied = new Map();
      const assetFor = info => { if (!copied.has(info.id)) copied.set(info.id, copySource(info.file, `${m.character}-pose-${info.id}`)); return copied.get(info.id); };
      world.push(...castLayers({plans, infos: m.infos, placement: m.placement, cameraFor, fps, assetPathFor: assetFor}));
      members.push({m, plans});
      for (const s of m.segments) {
        const info = m.infos.get(s.pose), k = m.placement.figureHeight / info.figureHeight;
        diagnostics.push({cast: m.id, character: m.character, ...(m.synthetic ? {synthetic: true} : {}), facing: m.facing, pose: s.pose, requestedPose: s.requestedPose, from: s.start, to: s.end, transition: s.transition,
          upscale: +(k * ppu).toFixed(2), upscaleAtMaxZoom: +(k * ppu * zMax).toFixed(2), soft: k * ppu * zMax > m.placement.maxUpscale, status: info.status});
      }
    }

    // 4. Screen-space speech bubbles: one per line, visible for the line, styled from the speaker's speech config.
    const art = new Map(), bubbles = [];
    for (const [i, msg] of seq.messages.entries()) {
      const img = renderBubble({text: msg.text, side: msg.side, style: msg.style, ppu, ...bubbleOpts});
      const rect = {x: r2(bubbleX(msg.side, img.width, plane, o)), y: o.bubbleY, w: img.width, h: img.height};
      const from = +msg.start.toFixed(4), to = +(i === seq.messages.length - 1 ? Math.min(msg.start + msg.duration, shotDuration) : msg.start + msg.duration).toFixed(4);
      art.set(msg.id, {path: writeGen(`line-${msg.id}`, img), img});
      bubbles.push({id: msg.id, rect, from, to});
      screen.push({type: 'image', path: art.get(msg.id).path, x: rect.x, y: rect.y, w: r2(img.width), from, to});
    }

    // 5. Per-frame checks (camera and transitions applied): faces of the members a shot frames stay in frame, and no
    //    bubble covers a visible face. Wide shots frame everyone; medium and close shots frame their focus member.
    const safe = {x: plane.width * o.safe.left, y: plane.height * o.safe.top, w: plane.width * (1 - o.safe.left - o.safe.right), h: plane.height * (1 - o.safe.top - o.safe.bottom)};
    for (const b of bubbles) {
      const r = b.rect;
      if (r.x < safe.x - 0.5 || r.y < safe.y - 0.5 || r.x + r.w > safe.x + safe.w + 0.5 || r.y + r.h > safe.y + safe.h + 0.5) issues.push({t: b.from, id: b.id, problem: 'outside safe zone'});
      if (hookRect && b.from < hookRect.to - EPS && hookRect.from < b.to - EPS && overlap(r, hookRect)) issues.push({t: b.from, id: b.id, problem: 'overlaps the hook'});
    }
    const frames = Math.ceil(shotDuration * fps - 1e-6);
    for (let f = 0; f < frames; f++) {
      const t = f / fps, cam = cameraFor(t), shot = shotAt(t);
      for (const {m, plans} of members) for (const plan of plans) {
        if (t < plan.from || t >= plan.to || alphaAt(plan, t) <= 0) continue;
        const info = m.infos.get(plan.pose), s = scaleAt(plan, t), rect = poseRect(info, m.placement, s);
        const top = m.placement.feetY - m.placement.figureHeight * s;
        const face = applyCamera(cam, {x: rect.x, y: top, w: rect.w});
        const faceH = m.placement.figureHeight * (info.headFraction ?? 0.42) * s * cam.z, faceBox = {x: face.x, y: face.y, w: face.w, h: faceH};
        const framed = shot.focus === null || shot.focus === m.id;
        if (framed && (face.x < -1 || face.x + face.w > plane.width + 1 || face.y < -1 || face.y + faceH > plane.height + 1)) issues.push({t: +t.toFixed(3), id: m.id, problem: `face of pose ${plan.pose} is cropped by the camera`});
        for (const b of bubbles) if (t >= b.from - EPS && t < b.to - EPS && overlap(b.rect, faceBox)) issues.push({t: +t.toFixed(3), id: b.id, problem: `covers the face of cast member ${m.id}`});
      }
    }

    const lines = seq.messages.map((msg, i) => ({id: msg.id, speaker: msg.speaker, character: byId.get(msg.speaker).character, style: msg.style, side: msg.side,
      start: msg.start, end: +(msg.start + msg.duration).toFixed(4), shot: {camera: shots[i].note, focus: shots[i].focus, zoom: shots[i].zoom}}));
    const cuts = shots.slice(1).filter((s, i) => s.zoom !== shots[i].zoom || s.focus !== shots[i].focus).map(s => ({t: s.start, to: s.zoom, focus: s.focus}));
    return {
      world, screen, sfx: seq.sfx, art, lines,
      layout: {zoneTop: o.bubbleY, zoneBottom: Math.max(o.bubbleY, ...bubbles.map(b => b.rect.y + b.rect.h))},
      checks: {ok: !issues.length, issues: dedupe(issues), safeZone: safe},
      diagnostics,
      camera: {shots: shots.map(s => ({line: s.line, start: s.start, end: s.end, speaker: s.speaker, focus: s.focus, zoom: s.zoom, note: s.note, pivot: s.pivot})),
        cuts, moves: [], shakes: [], drifts: [], notes: shots.map(s => ({start: s.start, end: s.end, note: s.note}))},
    };
  },
};

// Collapse per-frame issues into one entry per (id, problem) with first/last time.
function dedupe(issues) {
  const m = new Map();
  for (const i of issues) { const k = `${i.id}|${i.problem}`; const e = m.get(k); if (e) e.last = i.t; else m.set(k, {...i, last: i.t}); }
  return [...m.values()];
}
