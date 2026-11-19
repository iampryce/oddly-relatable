// Scene format strategy: face-to-face dialogue (AP-85 P1, corrected after the Track A owner review).
// Several cast members share one environment and talk to each other. Each line is spoken by a cast member, shown as a
// screen-space speech bubble styled from THAT member's speech configuration, and framed by an explicit shot: wide, or
// medium / close on a named cast member (shot / reverse-shot). World layers (environment, shadows, cast) go through the
// camera; bubbles never do.
//
// Scene fields:
//   cast:  [{id, character, registry?, placement, z, facing?, speech: {style, side?}}]   (speech is required to speak)
//   lines: [{speaker: castId, text, duration?, pose?: poseId (the speaker's), poses?: {castId: poseId},
//            transition?: cut|pop|crossfade,
//            shot: {camera: 'Wide' | 'Medium N×' | 'Close' | 'Hold', focus?: castId, single?: true}}]
//   camera?: {maxZoom, mediumZoom}, bubbles?, timing?, layout?: {bubbleY, marginX, safe}, framing?: {edgeMargin, subjectMargin}
// Every cast member needs a pose on the first line. Medium and close shots need a focus. Camera moves, shake and drift
// are not part of this format yet and are refused, not approximated.
//
// Bubble side (owner review, A2): each bubble goes on the side of the screen where its SPEAKER stands in that line's
// shot (left of the frame centre: left; otherwise right), with the tail on that side. Style still comes only from the
// speaker's speech configuration. A declared speech.side is a constraint, never a silent override: if the speaker
// stands on the other side, the build fails.
//
// Framing (owner review, A4): shot zoom levels keep their meaning (wide 1x, medium Nx, close = maxZoom), and character
// positions and scale are never changed. A medium or close shot is COMPOSED, not just zoomed about a head:
//   - the camera pans to centre its focus member as far as the background allows, keeping it fully in frame;
//   - every other member is either fully in frame or fully out of it, never cut by the left or right frame edge;
//   - when other members are visible, the focus member must be clearly the most central figure;
//   - "single": true asks for a single: only the focus member is shown for that shot (the others are off camera).
// If a shot cannot meet these rules, the build fails with an explanation; nothing is silently reframed or restaged.
import {sequenceConversation} from '../conversation.mjs';
import {renderBubble, renderShadow, BUBBLE_DEFAULTS} from '../graphics.mjs';
import {bubbleX, LAYOUT_DEFAULTS} from '../layout.mjs';
import {resolveCast, validateCast} from '../cast.mjs';
import {cameraAt, applyCamera, parseCameraNote, CAMERA_DEFAULTS} from '../camera.mjs';
import {planPoseLayers, castLayers, worldLayer, poseRect, scaleAt, alphaAt} from '../timeline.mjs';
import {parallaxCamera} from '../depth.mjs';
import {resolveStaging} from '../staging.mjs';
import {composeWindow, continuityReport, moveSpan, MOVE_DEFAULTS, windowAt, windowCamera} from '../framing.mjs';

export const FACE_TO_FACE_DEFAULTS = Object.freeze({bubbleY: 300, marginX: LAYOUT_DEFAULTS.marginX, safe: LAYOUT_DEFAULTS.safe});
// edgeMargin: design units kept between a framed member and the frame edge. subjectMargin: when several members are in
// frame, how much closer (as a fraction of the frame width) the focus member must be to the frame centre than any other.
export const FRAMING_DEFAULTS = Object.freeze({edgeMargin: 24, subjectMargin: 0.1});
const r2 = v => +v.toFixed(2);
const EPS = 1e-9;
const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

export const faceToFace = {
  id: 'face-to-face',
  implemented: true,
  description: 'Face-to-face dialogue: several characters in one environment, speech bubbles per speaker, shot/reverse-shot camera.',

  // Timing and validation only (no files written).
  // ctx.profile (AP-86 S4, opt-in): camera moves (push-in, pull back, pan) are allowed; without it, exactly as before.
  sequence(scene, ctx = {}) {
    const cast = validateCast(scene.cast || []);
    if (!cast.length) throw new Error('face-to-face: at least one cast member is required');
    if (!Array.isArray(scene.lines) || !scene.lines.length) throw new Error('face-to-face: lines[] is required');
    const byId = new Map(cast.map(m => [m.id, m]));
    const camOpts = {...CAMERA_DEFAULTS, ...(scene.camera || {})};
    const speakers = {};
    // The side given here is provisional: compile() sets each bubble's side from where its speaker stands on screen.
    for (const m of cast) if (m.speech) speakers[m.id] = {side: m.speech.side ?? 'left', cast: m.id};
    let zoom = null;
    const shots = [];
    const events = scene.lines.map((l, i) => {
      const where = `line ${i + 1}`;
      if (!l || typeof l !== 'object') throw new Error(`${where}: must be an object`);
      if (!byId.has(l.speaker)) throw new Error(`${where}: speaker "${l.speaker}" is not a cast member of this scene`);
      if (!speakers[l.speaker]) throw new Error(`${where}: cast member "${l.speaker}" has no "speech" configuration ({style})`);
      if (!l.shot || typeof l.shot.camera !== 'string') throw new Error(`${where}: "shot" with a camera framing is required (e.g. {camera: "Wide"})`);
      let move = null;
      const pan = ctx.profile && /^\s*(slow\s+)?pan\b/i.test(l.shot.camera);
      const a = pan ? {framing: null, move: null, shake: false, drift: false} : parseCameraNote(l.shot.camera, camOpts);
      if (!ctx.profile && (a.move || a.shake || a.drift)) throw new Error(`${where}: face-to-face shots support wide / medium N× / close / hold framings only (no moves, shake or drift)`);
      if (a.shake || a.drift) throw new Error(`${where}: shake and drift are not part of face-to-face framing profiles`);
      if ((a.move || pan) && zoom === null) throw new Error(`${where}: the first shot needs a framing (wide, medium or close), not a camera move`);
      if (pan) {
        if (!(zoom > 1 + EPS)) throw new Error(`${where}: a pan moves a medium or close framing to another member; frame a medium or close shot first`);
        move = {kind: 'pan', slow: /slow/i.test(l.shot.camera)};
      } else if (a.move) {
        move = {kind: a.move.zoom > zoom + EPS ? 'push' : 'pull', slow: a.move.duration === 'beat'};
        if (Math.abs(a.move.zoom - zoom) <= EPS) throw new Error(`${where}: "${l.shot.camera}" does not change the zoom (already ${zoom}x)`);
        zoom = a.move.zoom;
      } else if (a.framing) zoom = a.framing.zoom;
      else if (zoom === null) throw new Error(`${where}: the first shot needs a framing (wide, medium or close)`);
      if (l.shot.focus !== undefined && !byId.has(l.shot.focus)) throw new Error(`${where}: shot focus "${l.shot.focus}" is not a cast member of this scene`);
      if (zoom > 1 + EPS && l.shot.focus === undefined) throw new Error(`${where}: a medium or close shot needs a "focus" cast member`);
      if (l.shot.single !== undefined && typeof l.shot.single !== 'boolean') throw new Error(`${where}: shot "single" must be true or false`);
      if (l.shot.single && !(zoom > 1 + EPS)) throw new Error(`${where}: "single" applies to medium and close shots only`);
      const poses = {...(l.poses || {})};
      if (l.pose !== undefined) poses[l.speaker] = l.pose;
      for (const id of Object.keys(poses)) if (!byId.has(id)) throw new Error(`${where}: pose for "${id}", which is not a cast member of this scene`);
      shots.push({line: i + 1, speaker: l.speaker, focus: l.shot.focus ?? null, zoom, single: l.shot.single === true, note: l.shot.camera, ...(move ? {move} : {})});
      return {type: 'message', speaker: l.speaker, text: l.text, ...(l.duration !== undefined ? {duration: l.duration} : {}), ...(Object.keys(poses).length ? {poses} : {}), ...(l.transition ? {transition: l.transition} : {})};
    });
    const seq = sequenceConversation({speakers, cast, timing: scene.timing, events}, {defaultCast: null});
    for (const m of cast) if (!seq.castPoses[m.id]) throw new Error(`cast member "${m.id}" has no pose: give every cast member a pose on the first line`);
    seq.messages.forEach((msg, i) => { shots[i].start = msg.start; shots[i].end = msg.start + msg.duration; });
    return {...seq, shots, reactionCast: null, duration: seq.conversationEnd};
  },

  // stage: a resolved set plate (AP-86 S2) instead of env. layering: 'legacy' (story@1: z, default 0, declaration order,
  // exactly as before) or 'depth' (story@2: O4, depth-derived with explicit z winning; see depth.mjs).
  // profile (AP-86 S4, opt-in): a framing profile from framing.mjs. Without it, compilation is exactly as before.
  async compile({scene, seq, shotDuration, plane, ppu, fps, env, stage = null, layering = 'legacy', actionLibrary = null, writeGen, copySource, hookRect, repoRoot, allowSynthetic = false, profile = null}) {
    const base = profile ? {...FACE_TO_FACE_DEFAULTS, bubbleY: profile.bubbleY, safe: profile.safe} : FACE_TO_FACE_DEFAULTS;
    const o = {...base, ...(scene.layout || {}), safe: {...base.safe, ...(scene.layout?.safe || {})}};
    const bubbleOpts = {...BUBBLE_DEFAULTS, ...(profile?.bubbles || {}), ...(scene.bubbles || {})};
    const world = [], screen = [], issues = [];

    // 1. Cast (resolved by character ID, facing resolved to declared artwork) and their pose segments.
    for (const list of Object.values(seq.castPoses)) for (const p of list) if (!Number.isFinite(p.end) || p.end > shotDuration) p.end = shotDuration;
    // story@2 (AP-86 S2/S3): the staging resolver turns explicit placements and blocking (marks, surfaces, props,
    // actions) into world placements, contacts and a depth-derived draw order (explicit placement and z win). The depth
    // key is handed to the existing z sort, which is stable, so ties keep declaration order.
    let castInput = scene.cast, staging = null, staged = null;
    if (layering === 'depth') {
      staged = await resolveStaging({scene, seq, stage, plane, library: actionLibrary, repoRoot, allowSynthetic});
      staging = staged.report;
      const byMember = new Map(staged.members.map(x => [x.id, x]));
      castInput = scene.cast.map(m => ({...m, placement: byMember.get(m.id).placement, z: byMember.get(m.id).key}));
    } else if (stage) throw new Error('a set needs depth layering (story@2)');
    const cast = await resolveCast(castInput, seq.castPoses, repoRoot, {allowSynthetic});
    const byId = new Map(cast.map(m => [m.id, m]));

    // 2. Camera: one shot per line. Wide shots: zoom 1 about the frame centre (unchanged). Medium and close shots are
    //    composed (see the header): the window is panned to centre the focus member within the background, and the
    //    vertical framing keeps the focus member's head top where it is in the wide shot.
    const coverRect = stage ? stage.rect : (env?.rect || null), camCache = new Map();
    const fr = {...FRAMING_DEFAULTS, ...(scene.framing || {})};
    let shots, cameraFor, moving = () => false, continuity = [];
    if (!profile) {
      shots = seq.shots.map((s, i) => composeShot({...s, end: i === seq.shots.length - 1 ? shotDuration : s.end}, {cast, byId, plane, coverRect, fr}));
      cameraFor = t => {
        const key = Math.round(t * fps);
        if (!camCache.has(key)) {
          const s = shots.find(x => key / fps >= x.start - EPS && key / fps < x.end - EPS) || shots.at(-1);
          camCache.set(key, cameraAt({cuts: [], moves: [], shakes: [], drifts: [], initialZoom: s.zoom}, key / fps, {pivot: s.pivot, plane, coverRect}));
        }
        return camCache.get(key);
      };
    } else {
      // AP-86 S4: every shot is a window on the set plate (framing.mjs); moves interpolate between two windows.
      if (!stage) throw new Error(`framing profile ${profile.id}: face-to-face profiles compose shots on a set plate; give the scene a "set"`);
      const ctx = {cast, byId, plane, plate: stage.rect, fr, profile, poseRect};
      shots = seq.shots.map((s, i) => composeWindow({...s, end: i === seq.shots.length - 1 ? shotDuration : s.end}, ctx));
      for (const [i, s] of shots.entries()) {
        if (!s.move) continue;
        s.from = shots[i - 1].window;
        s.span = moveSpan(s);
        const travel = Math.abs((s.window.L + s.window.W / 2) - (s.from.L + s.from.W / 2)) / s.window.W, secs = s.span.end - s.span.start;
        if (s.move.kind === 'pan' && travel / secs > MOVE_DEFAULTS.maxPanSpeed) {
          throw new Error(`line ${s.line} (${s.note}): this pan covers ${travel.toFixed(2)} frame widths in ${secs.toFixed(2)} s, too fast to read; use "slow pan", a longer line, or a cut`);
        }
      }
      moving = t => shots.some(s => s.span && t >= s.span.start - EPS && t < s.span.end - EPS);
      cameraFor = t => {
        const key = Math.round(t * fps);
        if (!camCache.has(key)) camCache.set(key, windowCamera(windowAt(shots, key / fps), plane, key / fps));
        return camCache.get(key);
      };
      const screenX = (shot, id) => (byId.get(id).placement.feetX - shot.window.L) * shot.window.z;
      continuity = continuityReport(shots, cast, plane, screenX);
      for (const s of shots) s.pivot = {window: {left: r2(s.window.L), top: r2(s.window.T), width: r2(s.window.W), zoom: +s.window.z.toFixed(4)}};
    }
    const shotAt = t => shots.find(s => t >= s.start - EPS && t < s.end - EPS) || shots.at(-1);

    // 3. World layers: environment (or the set's backdrop layers), then cast members in draw order (shadow under each).
    //    In a set, occluder layers are drawn between members by depth: a member standing behind an occluder's baseline
    //    is drawn before it, so the occluder covers it. Each set layer moves with its own parallax factor.
    const layerCam = p => (p === 1 ? cameraFor : t => parallaxCamera(cameraFor(t), p));
    const pushSetLayer = l => world.push(worldLayer({path: copySource(l.file, `set-${stage.set}-${stage.plate}-${l.id}`), rect: l.rect, cameraFor: layerCam(l.parallax), from: 0, to: shotDuration, fps}));
    if (env) world.push(worldLayer({path: copySource(env.file, 'background'), rect: env.rect, cameraFor, from: 0, to: shotDuration, fps}));
    if (stage) for (const l of stage.layers) if (!l.occluder) pushSetLayer(l);
    const diagnostics = [], members = [];
    const zMax = Math.max(...shots.map(s => s.zoom));
    // Props (S3): drawn as world layers at their resolved rectangles; splits are extra layers aligned with the state
    // image. A held prop follows its holder's hand pose by pose and is off camera whenever its holder is.
    const propOf = id => staged.props.get(id);
    // worldLayer samples keys only inside [from, to); the visibility window is set here so a prop shows only then.
    const propLayer = (file, label, rect, from, to) => world.push({...worldLayer({path: copySource(file, label), rect: {x: rect.x, y: rect.y, w: rect.w}, cameraFor, from, to, fps}), from: +from.toFixed(4), to: +to.toFixed(4)});
    const pushProp = (id, part = 'main') => {
      const pr = propOf(id), label = `prop-${pr.reg.prop}-${pr.stateId}`;
      if (pr.segments) {
        const visible = visibleIntervals(pr.heldBy, shots, shotDuration);
        for (const sg of pr.segments) for (const [a, b] of visible) {
          const from = Math.max(a, sg.from), to = Math.min(b, Math.min(sg.to, shotDuration));
          if (to <= from + EPS) continue;
          propLayer(pr.file, label, sg.rect, from, to);
          if (pr.splits.front) propLayer(pr.splits.front, `${label}-front`, sg.rect, from, to);
        }
        return;
      }
      if (part === 'front') { propLayer(pr.splits.front, `${label}-front`, pr.rect, 0, shotDuration); return; }
      if (pr.splits.back) propLayer(pr.splits.back, `${label}-back`, pr.rect, 0, shotDuration);
      propLayer(pr.file, label, pr.rect, 0, shotDuration);
      if (pr.splits.front && !pr.seatOf) propLayer(pr.splits.front, `${label}-front`, pr.rect, 0, shotDuration);
    };
    const order = staged ? staged.order.map(o => { const i = o.indexOf(':'); return {kind: o.slice(0, i), id: o.slice(i + 1)}; }) : cast.map(m => ({kind: 'member', id: m.id}));
    for (const item of order) {
      if (item.kind === 'occluder') { pushSetLayer(stage.layers.find(l => l.id === item.id)); continue; }
      if (item.kind === 'prop') { pushProp(item.id); continue; }
      if (item.kind === 'prop-front') { pushProp(item.id, 'front'); continue; }
      const m = byId.get(item.id);
      // A member is off camera during single shots on someone else; otherwise it is visible for the whole scene.
      const visible = visibleIntervals(m.id, shots, shotDuration);
      if (m.placement.shadow) {
        const sw = m.placement.figureHeight * 0.36, sh = sw * 0.2, shadowPath = writeGen('shadow', renderShadow({width: sw, height: sh, ppu}));
        // One shadow layer per visible interval, shown only during that interval (AP-85 shadow correction, 2026-11-16).
        // worldLayer sets no visibility window, so without one the renderer showed every interval's layer for the whole
        // shot: an off-camera member's shadow stayed visible in other members' singles, and shadows were duplicated.
        // A shadow visible for the whole shot keeps its exact previous form (no window), so scenes without singles are
        // unchanged byte for byte.
        for (const [from, to] of visible) {
          const layer = worldLayer({path: shadowPath, rect: {x: m.placement.feetX - sw / 2, y: m.placement.feetY - sh * 0.55, w: sw}, cameraFor, from, to, fps});
          const whole = from <= EPS && to >= shotDuration - EPS;
          world.push(whole ? layer : {type: layer.type, path: layer.path, x: layer.x, y: layer.y, w: layer.w, from: +from.toFixed(4), to: +to.toFixed(4), keys: layer.keys});
        }
      }
      const plans = splitPlans(planPoseLayers(m.segments, scene.transitions || {}), visible);
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

    // 4. Screen-space speech bubbles: one per line, visible for the line, styled from the speaker's speech config and
    //    placed on the side of the screen where the speaker stands in that line's shot (tail on the same side).
    //    The speaker's position is its feet point through that shot's camera; an off-camera speaker (a single on someone
    //    else) still has a side: the side of the frame it is beyond.
    const art = new Map(), bubbles = [], sides = [];
    for (const [i, msg] of seq.messages.entries()) {
      const speaker = byId.get(msg.speaker), shot = shotAt(msg.start);
      const screenX = applyCamera(cameraFor(msg.start), {x: speaker.placement.feetX, y: speaker.placement.feetY, w: 0}).x;
      const side = screenX < plane.width / 2 ? 'left' : 'right';
      const declared = speaker.speech?.side;
      if (declared !== undefined && declared !== side) throw new Error(`line ${i + 1}: speaker "${speaker.id}" stands on the ${side} of the frame, but its speech.side is "${declared}". Bubbles go on the side where the speaker stands: remove speech.side or restage`);
      sides.push({side, screenX: r2(screenX), onScreen: !shot.hidden.includes(speaker.id) && screenX >= 0 && screenX <= plane.width});
      const img = renderBubble({text: msg.text, side, style: msg.style, ppu, ...bubbleOpts});
      const rect = {x: r2(bubbleX(side, img.width, plane, o)), y: o.bubbleY, w: img.width, h: img.height};
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
    const backdrop = stage?.layers[0];
    for (let f = 0; f < frames; f++) {
      const t = f / fps, cam = cameraFor(t), shot = shotAt(t);
      if (profile) {
        // S4: the window (moving or not) never leaves the plate, so the background always covers the frame.
        const w = windowAt(shots, Math.round(t * fps) / fps), p = stage.rect;
        if (w.L < p.x - 0.5 || w.T < p.y - 0.5 || w.L + w.W > p.x + p.w + 0.5 || w.T + w.H > p.y + p.h + 0.5) issues.push({t: +t.toFixed(3), id: 'camera', problem: 'the camera window leaves the set plate'});
      }
      if (backdrop && backdrop.parallax !== 1) {
        const b = applyCamera(parallaxCamera(cam, backdrop.parallax), backdrop.rect), bh = backdrop.rect.h * b.w / backdrop.rect.w;
        if (b.x > 0.5 || b.y > 0.5 || b.x + b.w < plane.width - 0.5 || b.y + bh < plane.height - 0.5) issues.push({t: +t.toFixed(3), id: backdrop.id, problem: `with parallax ${backdrop.parallax} the backdrop layer no longer covers the frame`});
      }
      for (const {m, plans} of members) for (const plan of plans) {
        // EPS: a frame time (472/30 = 15.733333...333) can sit a float hair below a layer end at the same instant
        // (15.733333...334); the renderer does not draw the layer on that frame, so the check must not either.
        if (t < plan.from - EPS || t >= plan.to - EPS || alphaAt(plan, t) <= 0) continue;
        const info = m.infos.get(plan.pose), s = scaleAt(plan, t), rect = poseRect(info, m.placement, s);
        const top = m.placement.feetY - m.placement.figureHeight * s;
        const face = applyCamera(cam, {x: rect.x, y: top, w: rect.w});
        const faceH = m.placement.figureHeight * (info.headFraction ?? 0.42) * s * cam.z, faceBox = {x: face.x, y: face.y, w: face.w, h: faceH};
        const framed = shot.focus === null || shot.focus === m.id;
        // While the camera moves (S4 profiles only), members may cross the frame edge; the rules apply again from the
        // move's last frame. Without a profile nothing moves, so these checks run on every frame exactly as before.
        const settled = !moving(t);
        if (settled && framed && (face.x < -1 || face.x + face.w > plane.width + 1 || face.y < -1 || face.y + faceH > plane.height + 1)) issues.push({t: +t.toFixed(3), id: m.id, problem: `face of pose ${plan.pose} is cropped by the camera`});
        // No member may be cut by the left or right frame edge: fully in frame or fully out of it.
        const body = applyCamera(cam, rect);
        if (settled && body.x < plane.width - 1 && body.x + body.w > 1 && (body.x < -1 || body.x + body.w > plane.width + 1)) issues.push({t: +t.toFixed(3), id: m.id, problem: `pose ${plan.pose} is cut by the ${body.x < -1 ? 'left' : 'right'} frame edge`});
        for (const b of bubbles) if (t >= b.from - EPS && t < b.to - EPS && overlap(b.rect, faceBox)) issues.push({t: +t.toFixed(3), id: b.id, problem: `covers the face of cast member ${m.id}`});
      }
    }

    const lines = seq.messages.map((msg, i) => ({id: msg.id, speaker: msg.speaker, character: byId.get(msg.speaker).character, style: msg.style, side: sides[i].side,
      sideFrom: 'speaker screen position', speakerScreenX: sides[i].screenX, speakerOnScreen: sides[i].onScreen,
      start: msg.start, end: +(msg.start + msg.duration).toFixed(4), shot: {camera: shots[i].note, focus: shots[i].focus, zoom: shots[i].zoom, single: shots[i].single}}));
    const cuts = shots.slice(1).filter((s, i) => s.zoom !== shots[i].zoom || s.focus !== shots[i].focus || s.single !== shots[i].single).map(s => ({t: s.start, to: s.zoom, focus: s.focus}));
    return {
      world, screen, sfx: seq.sfx, art, lines,
      layout: {zoneTop: o.bubbleY, zoneBottom: Math.max(o.bubbleY, ...bubbles.map(b => b.rect.y + b.rect.h))},
      checks: {ok: !issues.length, issues: dedupe(issues), safeZone: safe},
      ...(staging ? {staging} : {}),
      diagnostics,
      camera: {shots: shots.map(s => ({line: s.line, start: s.start, end: s.end, speaker: s.speaker, focus: s.focus, zoom: s.zoom, single: s.single, note: s.note, pivot: s.pivot,
        window: s.window, visible: s.visible, hidden: s.hidden, ...(profile ? {out: s.out, ...(s.move ? {move: s.move.kind} : {})} : {})})),
        cuts: profile ? cuts.filter(c => !shots.find(s => Math.abs(s.start - c.t) < EPS)?.move) : cuts,
        moves: profile ? shots.filter(s => s.move).map(s => ({line: s.line, kind: s.move.kind, start: r2(s.span.start), end: r2(s.span.end), from: +(plane.width / s.from.W).toFixed(4), to: +s.window.z.toFixed(4)})) : [],
        shakes: [], drifts: [], notes: shots.map(s => ({start: s.start, end: s.end, note: s.note})),
        ...(profile ? {profile: profile.id, continuity} : {})},
    };
  },
};

// ------------------------------------------------------------------------------------------------ framing (owner review, A4)
// Horizontal world extent of a member over [from, to): the union of the pose rectangles it shows in that interval.
function extentX(m, from, to) {
  let x0 = Infinity, x1 = -Infinity;
  for (const seg of m.segments) {
    if (seg.end <= from + EPS || seg.start >= to - EPS) continue;
    const r = poseRect(m.infos.get(seg.pose), m.placement);
    x0 = Math.min(x0, r.x); x1 = Math.max(x1, r.x + r.w);
  }
  return Number.isFinite(x0) ? {x0, x1} : null;
}
// Interval sets are sorted arrays of [lo, hi].
const intersect = (A, B) => A.flatMap(([a0, a1]) => B.map(([b0, b1]) => [Math.max(a0, b0), Math.min(a1, b1)])).filter(([lo, hi]) => lo <= hi + EPS).sort((p, q) => p[0] - q[0]);
function nearest(set, x) {                       // the point of the set closest to x (ties: the smaller value)
  let best = null;
  for (const [lo, hi] of set) { const c = Math.min(Math.max(x, lo), hi); if (best === null || Math.abs(c - x) < Math.abs(best - x) - EPS) best = c; }
  return best;
}

// Compose one shot. Wide shots keep the AP-85 P1 camera exactly (zoom 1 about the frame centre). Medium and close shots:
// choose the left edge L of the window (world units; width W = plane width / zoom) inside the background so that the
// focus member is fully in frame, every other member is fully in or fully out (single: the others are off camera), and
// the focus member is as close to the frame centre as those rules allow. The pivot is then derived so that the existing
// camera maths (zoom about a pivot, offsets clamped to the background) produces exactly that window.
export function composeShot(s, {cast, byId, plane, coverRect, fr}) {
  const where = `line ${s.line} (${s.note}${s.focus ? ` on ${s.focus}` : ''})`;
  if (!(s.zoom > 1 + EPS)) return {...s, pivot: {x: plane.width / 2, y: plane.height / 2}, window: {left: 0, right: plane.width}, visible: cast.map(m => m.id), hidden: []};
  const focus = byId.get(s.focus), z = s.zoom, W = plane.width / z, m = fr.edgeMargin;
  const bg = coverRect ? [coverRect.x, coverRect.x + coverRect.w] : [0, plane.width];
  const f = extentX(focus, s.start, s.end);
  let set = intersect([[bg[0], bg[1] - W]], [[f.x1 + m - W, f.x0 - m]]);
  if (!set.length) throw new Error(`${where}: "${focus.id}" does not fit inside this frame with a ${m}-unit margin. Use a wider shot or a smaller figure`);
  const others = cast.filter(c => c.id !== focus.id), hidden = s.single ? others.map(c => c.id) : [];
  for (const o of s.single ? [] : others) {
    const e = extentX(o, s.start, s.end);
    if (!e) continue;
    // Fully out on the left, fully in, or fully out on the right.
    const allowed = intersect(set, [[-Infinity, e.x0 - m - W], [e.x1 + m - W, e.x0 - m], [e.x1 + m, Infinity]]);
    if (!allowed.length) throw new Error(`${where}: every framing that keeps "${focus.id}" in frame would cut "${o.id}" at the frame edge. Restage the members, or make this a single ("single": true)`);
    set = allowed;
  }
  const fc = (f.x0 + f.x1) / 2, L = nearest(set, fc - W / 2), centre = L + W / 2;   // exact: rounding could leave the background
  const visible = [focus.id];
  for (const o of s.single ? [] : others) {
    const e = extentX(o, s.start, s.end);
    if (!e || e.x1 <= L + EPS || e.x0 >= L + W - EPS) continue;          // out of frame
    visible.push(o.id);
    // The focus member must be clearly the most central figure.
    if (Math.abs(fc - centre) + fr.subjectMargin * W > Math.abs((e.x0 + e.x1) / 2 - centre)) {
      throw new Error(`${where}: "${focus.id}" would not be the clear subject ("${o.id}" is about as central in the frame). Restage the members, or make this a single ("single": true)`);
    }
  }
  return {...s, pivot: {x: L * z / (z - 1), y: focus.placement.feetY - focus.placement.figureHeight}, window: {left: r2(L), right: r2(L + W)}, visible, hidden};
}

// Time intervals in which a member is on camera: the whole scene except single shots on someone else.
function visibleIntervals(id, shots, duration) {
  const out = []; let from = 0;
  for (const s of shots) {
    if (!s.hidden.includes(id)) continue;
    if (s.start > from + EPS) out.push([from, s.start]);
    from = s.end;
  }
  if (duration > from + EPS) out.push([from, duration]);
  return out;
}
// Cut pose layer plans to the visible intervals (a plan that lies inside one interval is kept unchanged).
function splitPlans(plans, visible) {
  return plans.flatMap(p => visible.flatMap(([a, b]) => {
    const from = Math.max(p.from, a), to = Math.min(p.to, b);
    if (to <= from + EPS) return [];
    return from === p.from && to === p.to ? [p] : [{...p, from, to}];
  }));
}

// Collapse per-frame issues into one entry per (id, problem) with first/last time.
function dedupe(issues) {
  const m = new Map();
  for (const i of issues) { const k = `${i.id}|${i.problem}`; const e = m.get(k); if (e) e.last = i.t; else m.set(k, {...i, last: i.t}); }
  return [...m.values()];
}
