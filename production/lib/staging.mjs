// Staging resolver (AP-86 S3, approved 2026-11-16): blocking and props -> world placements, contacts and draw order.
// Deterministic: the same scene, registries and files always give the same result. Nothing is guessed: every missing
// mark, surface, prop, state, anchor, floor line or size is an error that names what is missing.
//
// Precedence (owner decisions, 2026-11-15):
//   O3  named marks and actions are the default placement; an explicit "placement" always wins (the member's placing
//       action is then reported as overridden and not executed; its attaching actions, such as "hold", still apply).
//   O4  depth-derived layering is the default; an explicit "z" wins.
//
// Actions (S3 executes any action in the library by its structure; the approved set is stand-at, sit-on, lean-on, hold):
//   placing action  ("align"): the FIRST align entry puts that pose anchor exactly on its target; the member's size
//       comes from the floor model at the action's "scaleFrom" line (a prop target: the prop's floor line). Every other
//       align entry, and every pose the member uses, is checked against its target (anchor-alignment QA).
//   attaching action ("attach", e.g. hold): the prop anchor is attached to the pose anchor in every pose segment, so a
//       held prop follows the hand; its size comes from the floor model at the holder's depth.
//   Poses are never chosen here: the lines name them (as face-to-face requires). Every pose a member uses under an
//   action must match the action's pose selector (tags) and have the anchors the action needs.
//
// Units. Plate coordinates are fractions (0–1); world coordinates are design units. Anchor alignment tolerance:
// ALIGN_TOLERANCE design units (1 unit is under one output pixel at 1080 wide).
//
// Props:
//   on a surface, at "at" along it: its "base" anchor sits on the surface line; size and depth from the surface floorY.
//   on a mark: its "floor" anchor sits on the mark's floor point (or its point when it has none); size and depth there.
//   explicit placement {x, y}: its "floor" anchor (else "base") sits on that plate point; size and depth there.
//   "height" is the prop's height as a plate fraction at the floor model's reference line, scaled by depth like a figure.
//   A prop that a member sits on is drawn just before that member (its "front" split just after); a held prop is drawn
//   just after its holder. Splits are extra layers aligned with the state image (same size), so the renderer is unchanged.
import fs from 'node:fs';
import path from 'node:path';
import {REPO_ROOT, canvas} from './runtime.mjs';
import {loadRegistry} from './character.mjs';
import {registryPathFor, resolvePoseForFacing} from './cast.mjs';
import {loadProp, verifyPropAssets} from './props.mjs';
import {actionKind, targetOf, requiredAnchors} from './actions.mjs';
import {worldPlacement, placementKind, layeringKey, drawOrder} from './depth.mjs';
import {fail} from './schema.mjs';

export const ALIGN_TOLERANCE = 1;
const r3 = v => +v.toFixed(3);
const pt = p => ({x: r3(p.x), y: r3(p.y)});

// Does a pose match an action's pose selector? Tags may hold one value or a list; hasAnchor names required anchors.
export function poseMatches(pose, selector = {}) {
  for (const [k, v] of Object.entries(selector)) {
    if (k === 'hasAnchor') continue;
    const tags = pose.tags?.[k];
    if (!(Array.isArray(tags) ? tags : tags === undefined ? [] : [tags]).includes(v)) return false;
  }
  return true;
}
const anchorOf = (pose, name) => (name === 'feet' ? pose.feet : pose.anchors?.[name]);

// Resolve a scene's staging. Returns {members, props, order, report}. stage: the resolved set plate (or null when the
// scene has no set, in which case only explicit placements exist).
export async function resolveStaging({scene, seq, stage = null, plane, library = null, repoRoot = REPO_ROOT, allowSynthetic = false}) {
  const where = `scene ${scene.id} staging`;
  const cast = scene.cast || [], blocking = scene.blocking || [], sceneProps = scene.props || [];
  if ((blocking.length || sceneProps.length) && !stage) fail(where, 'props and blocking need a "set"');
  if (blocking.length && !library) fail(where, 'blocking needs an action library ("actionLibrary")');
  const vOf = y => (y - stage.rect.y) / stage.rect.h;
  const floor = stage?.floor;
  const sizeAt = (v, what) => stage.heightAt(v, what);               // world height of a reference figure at plate y v

  // ---- characters: registries and the (facing-resolved) poses each member uses
  const regs = new Map(cast.map(m => [m.id, loadRegistry(registryPathFor(m, repoRoot))]));
  const used = new Map(cast.map(m => {
    const reg = regs.get(m.id);
    return [m.id, (seq.castPoses[m.id] || []).map(s => ({...s, poseId: resolvePoseForFacing(reg, s.pose, m.facing ?? 'native', m.character)}))];
  }));
  const poseOf = (m, id) => regs.get(m.id).poses[id];

  // ---- props: registry, state, verified files, image sizes
  const props = new Map();
  for (const [index, p] of sceneProps.entries()) {
    const w = `${where} prop ${p.id}`;
    const reg = loadProp(p.prop, {file: p.registry ?? null, allowSynthetic});
    const regFile = p.registry ? path.resolve(repoRoot, p.registry) : path.join(repoRoot, 'production', 'props', `${p.prop}.json`);
    const root = reg.assetRoot === 'registry' ? path.dirname(regFile) : repoRoot;
    await verifyPropAssets(reg, root);
    const stateId = p.state ?? reg.defaultState;
    if (!reg.states[stateId]) fail(w, `prop "${reg.prop}" has no state "${stateId}"`);
    const state = reg.states[stateId], file = path.resolve(root, state.file), img = await canvas.loadImage(file);
    const splits = {};
    for (const part of ['back', 'front']) {
      const sp = reg.splits?.[stateId]?.[part];
      if (!sp) continue;
      const f = path.resolve(root, sp.file), si = await canvas.loadImage(f);
      if (si.width !== img.width || si.height !== img.height) fail(w, `its "${part}" split is ${si.width}×${si.height} but state "${stateId}" is ${img.width}×${img.height}; splits must align with the state image`);
      splits[part] = f;
    }
    if (reg.height === undefined) fail(w, `prop "${reg.prop}" has no "height"; S3 sizes props from it`);
    props.set(p.id, {decl: p, reg, stateId, state, file, splits, img: {width: img.width, height: img.height}, index});
  }
  const propSize = (pr, v) => {
    if (!floor) fail(`${where} prop ${pr.decl.id}`, 'the plate has no floor model; props are sized by it');
    if (!(v > floor.horizonY + 1e-9)) fail(`${where} prop ${pr.decl.id}`, `its floor line (plate y ${r3(v)}) is on or above the horizon`);
    return pr.reg.height * (v - floor.horizonY) / (floor.refFeetY - floor.horizonY) * stage.rect.h;
  };
  // Place a prop so its anchor `name` lands on world point T, sized for plate depth v.
  const placeProp = (pr, name, T, v) => {
    const a = pr.state.anchors?.[name];
    if (!a) fail(`${where} prop ${pr.decl.id}`, `state "${pr.stateId}" of "${pr.reg.prop}" has no "${name}" anchor`);
    const h = propSize(pr, v), k = h / pr.img.height;
    return {x: T.x - a.x * k, y: T.y - a.y * k, w: pr.img.width * k, h, k};
  };
  const propAnchor = (rect, pr, name) => {
    const a = pr.state.anchors?.[name];
    if (!a) fail(`${where} prop ${pr.decl.id}`, `state "${pr.stateId}" of "${pr.reg.prop}" has no "${name}" anchor`);
    return {x: rect.x + a.x * rect.k, y: rect.y + a.y * rect.k};
  };

  // ---- blocking by member
  const placing = new Map(), attaching = new Map(cast.map(m => [m.id, []]));
  for (const b of blocking) {
    const action = library.actions[b.do];
    if (!action) fail(where, `unknown action "${b.do}"`);
    if (actionKind(action) === 'place') placing.set(b.who, {b, action});
    else attaching.get(b.who).push({b, action});
  }
  const heldProps = new Set(blocking.filter(b => actionKind(library.actions[b.do]) === 'attach').map(b => b.prop));

  // ---- free props first (members may sit on them)
  for (const pr of props.values()) {
    if (heldProps.has(pr.decl.id)) continue;
    const p = pr.decl, w = `${where} prop ${p.id}`;
    let T, v, anchor, how;
    if (p.on !== undefined) {
      const sf = stage.surfaces[p.on], plateSf = stage.plateData.surfaces[p.on];
      if (plateSf.floorY === undefined) fail(w, `surface "${p.on}" has no "floorY"; it sets the size and depth of what stands on it`);
      T = {x: sf.x0 + p.at * (sf.x1 - sf.x0), y: sf.y}; v = plateSf.floorY; anchor = 'base'; how = `surface:${p.on}@${p.at}`;
    } else if (p.mark !== undefined) {
      const mk = stage.marks[p.mark];
      T = mk.floor ?? mk.point; v = vOf(T.y); anchor = 'floor'; how = `mark:${p.mark}`;
    } else {
      T = stage.toWorld(p.placement); v = p.placement.y; how = 'explicit';
      anchor = pr.state.anchors?.floor ? 'floor' : pr.state.anchors?.base ? 'base' : fail(w, `explicit placement needs a "floor" or "base" anchor in state "${pr.stateId}"`);
    }
    pr.rect = placeProp(pr, anchor, T, v); pr.v = v; pr.how = how; pr.anchor = anchor; pr.target = T;
    pr.layering = p.z !== undefined ? 'explicit-z' : 'depth'; pr.key = p.z ?? v;
  }

  // ---- members
  const members = [];
  for (const [index, m] of cast.entries()) {
    const w = `${where} cast member "${m.id}"`, uses = used.get(m.id), pl = placing.get(m.id);
    if (!uses.length) fail(w, 'has no pose');
    // Pose checks for every action the member performs (placing and attaching).
    for (const {b, action} of [...(pl && m.placement === undefined ? [pl] : []), ...attaching.get(m.id)]) {
      const need = requiredAnchors(action);
      for (const u of uses) {
        const pose = poseOf(m, u.poseId);
        if (!poseMatches(pose, action.pose)) fail(w, `pose "${u.poseId}" does not match action "${b.do}" (needs ${JSON.stringify(Object.fromEntries(Object.entries(action.pose || {}).filter(([k]) => k !== 'hasAnchor')))})`);
        for (const a of need) if (!anchorOf(pose, a)) fail(w, `pose "${u.poseId}" has no "${a}" anchor, which action "${b.do}" needs`);
      }
    }
    let placement, source, contacts = [], action = null, target = null, overriddenAction = null, scaleV = null;
    if (m.placement !== undefined) {
      const kind = placementKind(m.placement, `${w} placement`);
      placement = worldPlacement(m.placement, stage, `${w} placement`);
      source = kind === 'plate' ? 'explicit-plate' : 'explicit-world';
      if (pl) overriddenAction = pl.b.do;
    } else if (pl) {
      const {b, action: act} = pl, aw = `${w} action "${b.do}"`, tk = targetOf(act);
      const targetPoint = (ref, anchorName) => {
        if (ref === 'mark.point') return stage.marks[b.mark].point;
        if (ref === 'mark.floor') return stage.marks[b.mark].floor ?? fail(aw, `mark "${b.mark}" has no floor point`);
        if (ref === 'surface.line') { const sf = stage.surfaces[b.surface]; return {x: sf.x0 + b.at * (sf.x1 - sf.x0), y: sf.y, line: sf}; }
        const pr = props.get(b.prop);
        return propAnchor(pr.rect, pr, ref.slice(5));
      };
      // Size: the floor line named by scaleFrom, or the prop's floor line.
      if (tk === 'prop') scaleV = props.get(b.prop).v;
      else if (act.scaleFrom === 'mark.point') scaleV = vOf(stage.marks[b.mark].point.y);
      else if (act.scaleFrom === 'mark.floor') scaleV = vOf(targetPoint('mark.floor').y);
      else { const fy = stage.plateData.surfaces[b.surface].floorY; if (fy === undefined) fail(aw, `surface "${b.surface}" has no "floorY"; it sets the size of a member placed there`); scaleV = fy; }
      const figureHeight = sizeAt(scaleV, `${aw} (floor model)`);
      const entries = Object.entries(act.align), [firstAnchor, firstRef] = entries[0];
      const ref0 = poseOf(m, uses[0].poseId), A = anchorOf(ref0, firstAnchor), T = targetPoint(firstRef, firstAnchor), k = figureHeight / ref0.figureHeight;
      placement = {feetX: T.x - (A.x - ref0.feet.x) * k, feetY: T.y - (A.y - ref0.feet.y) * k, figureHeight};
      // Anchor-alignment QA: every align entry, for every pose the member uses.
      for (const [an, ref] of entries) {
        const tp = targetPoint(ref, an), c = {anchor: an, target: ref === 'surface.line' ? `surface:${b.surface}@${b.at}` : ref.startsWith('prop.') ? `prop:${b.prop}.${ref.slice(5)}` : `mark:${b.mark}.${ref.slice(5)}`, targetWorld: pt(tp), poses: []};
        for (const u of uses) {
          const pose = poseOf(m, u.poseId), kp = figureHeight / pose.figureHeight, a = anchorOf(pose, an);
          const wpt = {x: placement.feetX + (a.x - pose.feet.x) * kp, y: placement.feetY + (a.y - pose.feet.y) * kp};
          // On a surface line only the height must match exactly; along the line it must stay on the surface.
          const err = tp.line && an !== firstAnchor ? Math.max(Math.abs(wpt.y - tp.y), Math.max(0, tp.line.x0 - wpt.x, wpt.x - tp.line.x1)) : Math.hypot(wpt.x - tp.x, wpt.y - tp.y);
          if (err > ALIGN_TOLERANCE) fail(aw, `anchor "${an}" of pose "${u.poseId}" lands ${err.toFixed(2)} units from ${c.target} (tolerance ${ALIGN_TOLERANCE}); its poses must share that anchor's position relative to the feet`);
          c.poses.push({pose: u.poseId, error: r3(err)});
        }
        contacts.push(c);
      }
      // The member must stand on the floor: feet below the horizon.
      if (floor && !(vOf(placement.feetY) > floor.horizonY)) fail(aw, `the feet would be at plate y ${r3(vOf(placement.feetY))}, on or above the horizon (${floor.horizonY})`);
      source = `action:${b.do}`; action = b.do; target = contacts[0].target;
      if (tk === 'prop') props.get(b.prop).seatOf = m.id;
    } else fail(w, 'has no placement: give it a placing action (stand-at, sit-on, lean-on, ...) or an explicit "placement"');
    // Depth: the nearer of the feet and the floor line the size came from (a seated member's feet may not reach the floor).
    const feetV = stage ? vOf(placement.feetY) : null;
    const depthPlacement = scaleV !== null && feetV < scaleV ? {...placement, feetY: stage.rect.y + scaleV * stage.rect.h} : placement;
    const lk = layeringKey(m, depthPlacement, {stage, plane});
    // A member whose feet do not reach its floor line (sitting) casts no feet shadow; otherwise the existing default.
    if (scaleV !== null && feetV < scaleV - 1e-6) placement = {...placement, shadow: false};
    members.push({id: m.id, index, placement, source, action, target, overriddenAction, contacts, layering: lk.mode, key: lk.key, depthV: stage ? vOf(depthPlacement.feetY) : null});
  }

  // ---- held props follow the holder's hand, segment by segment
  const memberById = new Map(members.map(x => [x.id, x]));
  for (const m of cast) for (const {b, action} of attaching.get(m.id)) {
    const pr = props.get(b.prop), mem = memberById.get(m.id), [propRef, poseRef] = Object.entries(action.attach)[0];
    const handName = poseRef.slice(5), gripName = propRef.slice(5), holderV = mem.depthV;   // sized at the holder's floor line
    pr.heldBy = m.id; pr.how = `held-by:${m.id}`; pr.v = holderV;
    pr.segments = used.get(m.id).map(u => {
      const pose = poseOf(m, u.poseId), kp = mem.placement.figureHeight / pose.figureHeight, a = anchorOf(pose, handName);
      const hand = {x: mem.placement.feetX + (a.x - pose.feet.x) * kp, y: mem.placement.feetY + (a.y - pose.feet.y) * kp};
      const rect = placeProp(pr, gripName, hand, holderV);
      const grip = propAnchor(rect, pr, gripName);
      if (Math.hypot(grip.x - hand.x, grip.y - hand.y) > ALIGN_TOLERANCE) fail(`${where} prop ${b.prop}`, 'grip does not meet the hand');
      return {from: u.start, to: u.end, pose: u.poseId, rect, hand};
    });
    mem.contacts.push({anchor: handName, target: `prop:${b.prop}.${gripName}`, attached: true, poses: pr.segments.map(sg => ({pose: sg.pose, error: 0}))});
  }

  // ---- draw order: occluders, members (with the props they use) and free props, by depth (see depth.mjs)
  const free = [...props.values()].filter(pr => !pr.heldBy && !pr.seatOf);
  const order = drawOrder(
    [...members.map(x => ({id: x.id, key: x.key, index: x.index})), ...free.map(pr => ({id: `prop:${pr.decl.id}`, key: pr.key, index: cast.length + pr.index}))],
    stage ? stage.layers.map((l, index) => ({...l, index})).filter(l => l.occluder).map(l => ({id: l.id, baselineY: l.occluder.baselineY, index: l.index})) : [],
  ).map(o => (o.kind === 'member' && o.id.startsWith('prop:') ? {kind: 'prop', id: o.id.slice(5)} : {kind: o.kind, id: o.id}));
  const expanded = [];
  for (const o of order) {
    if (o.kind !== 'member') { expanded.push(`${o.kind}:${o.id}`); continue; }
    for (const pr of props.values()) if (pr.seatOf === o.id) expanded.push(`prop:${pr.decl.id}`);
    expanded.push(`member:${o.id}`);
    for (const pr of props.values()) if (pr.seatOf === o.id && pr.splits.front) expanded.push(`prop-front:${pr.decl.id}`);
    for (const pr of props.values()) if (pr.heldBy === o.id) expanded.push(`prop:${pr.decl.id}`);
  }

  // ---- report (rounded; no file paths)
  const report = {
    layering: 'depth', ...(stage ? {set: stage.set, plate: stage.plate} : {}),
    members: members.map(x => {
      const base = {id: x.id, placement: x.source.startsWith('action:') ? 'action' : x.source, layering: x.layering, key: +x.key.toFixed(6), index: x.index,
        world: {feetX: r3(x.placement.feetX), feetY: r3(x.placement.feetY), figureHeight: r3(x.placement.figureHeight)}};
      return {...base, ...(x.action ? {action: x.action, target: x.target} : {}), ...(x.overriddenAction ? {overriddenAction: x.overriddenAction} : {}), ...(x.contacts.length ? {contacts: x.contacts} : {})};
    }),
    ...(props.size ? {props: [...props.values()].map(pr => ({id: pr.decl.id, prop: pr.reg.prop, state: pr.stateId, placement: pr.how,
      ...(pr.seatOf ? {usedBy: pr.seatOf} : {}), layering: pr.heldBy || pr.seatOf ? 'with-member' : pr.layering, ...(pr.key !== undefined && !pr.heldBy && !pr.seatOf ? {key: +pr.key.toFixed(6)} : {}),
      ...(pr.rect ? {rect: {x: r3(pr.rect.x), y: r3(pr.rect.y), w: r3(pr.rect.w), h: r3(pr.rect.h)}, anchor: pr.anchor, target: pt(pr.target)} : {}),
      ...(pr.segments ? {segments: pr.segments.map(sg => ({from: sg.from, to: sg.to, pose: sg.pose, hand: pt(sg.hand)}))} : {})}))} : {}),
    drawOrder: expanded,
  };
  return {members, props, order: expanded, report};
}

