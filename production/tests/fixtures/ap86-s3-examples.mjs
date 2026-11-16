// AP-86 S3 test fixtures: two SYNTHETIC actors, a SYNTHETIC bar and office, SYNTHETIC props and an action library,
// plus the two worked examples of the AP-86 proposal (§6 bar conversation, §7 office desk) built from them.
//
// Not artwork, not a design, never a production asset. The actors are flat shapes labelled "SYNTHETIC / NOT ARTWORK"
// (no Character 02 is created or implied); every registry is marked "synthetic": true and is refused by every
// production path unless a test passes allowSynthetic; everything is written to a temporary folder only.
// All sizes, anchors and floor values are arbitrary test numbers, NOT set, pose or prop standards (O5 to O7 are open).
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {canvas, ensureFonts, FONT} from '../../lib/runtime.mjs';

const sha = buf => crypto.createHash('sha256').update(buf).digest('hex');
const hex = c => '#' + c.map(v => v.toString(16).padStart(2, '0')).join('');
export const ACTOR_COLOURS = Object.freeze({
  'synthetic-actor-a': {body: [0, 80, 255], head: [0, 200, 80]},
  'synthetic-actor-b': {body: [230, 120, 20], head: [140, 60, 200]},
});
export const PROP_COLOURS = Object.freeze({stool: [70, 40, 20], stoolFront: [250, 220, 0], glass: [120, 230, 255], mug: [255, 255, 255]});

// Pose geometry in image pixels (300×620 canvas). Every pose shares the character scale (figureHeight 600).
// Rectangles are [x0, y0, x1, y1]; anchors are what the actions use.
const POSES = {
  stand: {tags: {stance: 'stand'}, feet: {x: 150, y: 610}, anchors: {handRight: {x: 207, y: 340}},
    head: [150, 70], body: [105, 130, 195, 400], limbs: [[115, 400, 140, 610], [160, 400, 185, 610], [80, 140, 105, 330], [195, 140, 220, 330]]},
  sit: {tags: {stance: 'sit'}, feet: {x: 270, y: 610}, anchors: {seat: {x: 150, y: 470}, handRight: {x: 230, y: 400}},
    head: [150, 170], body: [105, 230, 195, 470], limbs: [[105, 440, 285, 480], [255, 480, 285, 610], [195, 250, 220, 400]]},
  'sit-raise': {tags: {stance: 'sit'}, feet: {x: 270, y: 610}, anchors: {seat: {x: 150, y: 470}, handRight: {x: 235, y: 300}},
    head: [150, 170], body: [105, 230, 195, 470], limbs: [[105, 440, 285, 480], [255, 480, 285, 610], [195, 290, 240, 315]]},
  lean: {tags: {stance: 'lean'}, feet: {x: 170, y: 610}, anchors: {handLeft: {x: 20, y: 290}},
    head: [170, 70], body: [125, 130, 215, 400], limbs: [[135, 400, 160, 610], [180, 400, 205, 610], [20, 280, 125, 300]]},
  // Within tolerance: the seat is 0.5 px off (under 1 design unit at this scale), for the QA tolerance tests.
  'sit-near': {tags: {stance: 'sit'}, feet: {x: 270, y: 610}, anchors: {seat: {x: 150, y: 470.5}, handRight: {x: 230, y: 400}},
    head: [150, 170], body: [105, 230, 195, 470], limbs: [[105, 440, 285, 480], [255, 480, 285, 610], [195, 250, 220, 400]]},
  // A deliberately inconsistent sitting pose: its seat sits 50 px lower relative to its feet (for the QA tests).
  'sit-bad': {tags: {stance: 'sit'}, feet: {x: 270, y: 610}, anchors: {seat: {x: 150, y: 520}, handRight: {x: 230, y: 400}},
    head: [150, 170], body: [105, 230, 195, 520], limbs: [[105, 490, 285, 530], [255, 530, 285, 610], [195, 250, 220, 400]]},
};

function drawPose(spec, colours, label) {
  ensureFonts();
  const c = canvas.createCanvas(300, 620), ctx = c.getContext('2d');
  ctx.fillStyle = hex(colours.body);
  for (const [x0, y0, x1, y1] of [spec.body, ...spec.limbs]) ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
  ctx.fillStyle = hex(colours.head); ctx.beginPath(); ctx.arc(spec.head[0], spec.head[1], 55, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#ffe600'; ctx.fillRect(spec.body[0] + 4, spec.body[1] + 20, 82, 46);
  ctx.fillStyle = '#000000'; ctx.font = `700 11px "${FONT.sans}"`; ctx.textBaseline = 'top';
  ['SYNTHETIC', 'NOT ARTWORK', label].forEach((t, i) => ctx.fillText(t, spec.body[0] + 7, spec.body[1] + 23 + i * 13));
  return c.toBuffer('image/png');
}
function card(w, h, colour, label, draw) {
  ensureFonts();
  const c = canvas.createCanvas(w, h), ctx = c.getContext('2d');
  if (draw) draw(ctx); else { ctx.fillStyle = hex(colour); ctx.fillRect(0, 0, w, h); }
  if (label) { ctx.fillStyle = '#000000'; ctx.font = `700 ${Math.max(8, Math.round(w / 20))}px "${FONT.sans}"`; ctx.textBaseline = 'top'; ctx.fillText(`SYNTHETIC ${label} NOT ARTWORK`, 4, 4); }
  return c.toBuffer('image/png');
}

export function writeS3Examples(dir) {
  fs.mkdirSync(path.join(dir, 'art'), {recursive: true});
  const put = (name, buf) => { const rel = `art/${name}.png`; fs.writeFileSync(path.join(dir, rel), buf); return {file: rel, sha256: sha(buf)}; };
  const writeJson = (name, data) => { const f = path.join(dir, name); fs.writeFileSync(f, JSON.stringify(data, null, 2)); return f; };

  // ---- actors (character registries v2, synthetic)
  const actors = {};
  for (const [character, colours] of Object.entries(ACTOR_COLOURS)) {
    const poses = {};
    for (const [id, spec] of Object.entries(POSES)) {
      const a = put(`${character}-${id}`, drawPose(spec, colours, character.slice(-7)));
      poses[id] = {file: path.join(dir, a.file), sha256: a.sha256, feet: spec.feet, figureHeight: 600, headFraction: 0.2, tags: spec.tags, anchors: spec.anchors, status: 'SYNTHETIC TEST FIXTURE'};
    }
    actors[character] = writeJson(`${character}.json`, {character, schemaVersion: 2, synthetic: true, displayName: `${character} (SYNTHETIC, NOT ARTWORK)`,
      note: 'SYNTHETIC TEST FIXTURE for AP-86 S3 only. Not a character, not Character 02, not artwork; never promotable.', poses});
  }

  // ---- props (synthetic)
  const stool = put('prop-stool', card(120, 200, null, null, ctx => { ctx.fillStyle = hex(PROP_COLOURS.stool); ctx.fillRect(10, 10, 100, 24); ctx.fillRect(20, 34, 14, 166); ctx.fillRect(86, 34, 14, 166); }));
  const stoolFront = put('prop-stool-front', card(120, 200, null, null, ctx => { ctx.fillStyle = hex(PROP_COLOURS.stoolFront); ctx.fillRect(10, 10, 100, 12); }));
  const glass = put('prop-glass', card(20, 40, PROP_COLOURS.glass));
  const mug = put('prop-mug', card(30, 30, PROP_COLOURS.mug));
  const prop = (id, data) => writeJson(`${id}.json`, {prop: id, schemaVersion: 2, synthetic: true, assetRoot: 'registry', note: 'SYNTHETIC TEST FIXTURE, NOT ARTWORK.', ...data});
  const props = {
    stool: prop('synthetic-stool', {defaultState: 'default', states: {default: {...stool, anchors: {floor: {x: 60, y: 198}, seat: {x: 60, y: 22}}}}, affordances: ['seat'], height: 0.2, splits: {default: {front: stoolFront}}}),
    glass: prop('synthetic-glass', {defaultState: 'full', states: {full: {...glass, anchors: {base: {x: 10, y: 38}, grip: {x: 10, y: 15}}}, empty: {...glass, anchors: {base: {x: 10, y: 38}, grip: {x: 10, y: 15}}}}, affordances: ['grip', 'rest'], height: 0.035}),
    mug: prop('synthetic-mug', {defaultState: 'default', states: {default: {...mug, anchors: {base: {x: 15, y: 29}, grip: {x: 28, y: 15}}}}, affordances: ['rest', 'grip'], height: 0.03}),
  };

  // ---- sets (synthetic)
  const floor = {horizonY: 0.38, refFeetY: 0.86, refFigureHeight: 0.42};
  const barBack = put('bar-backdrop', card(480, 480, [150, 110, 80], 'BAR')), counter = put('bar-counter', card(480, 110, [110, 60, 30], 'COUNTER'));
  const officeBack = put('office-backdrop', card(480, 480, [180, 190, 200], 'OFFICE')), desk = put('office-desk-front', card(480, 80, [90, 90, 100], 'DESK'));
  const set = (id, data) => writeJson(`${id}.json`, {set: id, schemaVersion: 2, synthetic: true, assetRoot: 'registry', note: 'SYNTHETIC TEST FIXTURE, NOT ARTWORK.', ...data});
  const sets = {
    bar: set('synthetic-bar', {kind: 'interior/bar', plates: {wide: {superframe: {width: 480, height: 480}, floor,
      layers: [{id: 'backdrop', ...barBack}, {id: 'counter', ...counter, rect: {x: 0, y: 0.6, w: 1}, occluder: {baselineY: 0.7}}],
      marks: {'stool-1': {kind: 'seat', point: {x: 0.38, y: 0.72}, floor: {x: 0.38, y: 0.8}}, 'bar-end': {kind: 'stand', point: {x: 0.62, y: 0.88}}},
      surfaces: {'counter-top': {line: {x0: 0.05, x1: 0.95, y: 0.6}, floorY: 0.7}}}}}),
    office: set('synthetic-office', {kind: 'interior/office', plates: {desk: {superframe: {width: 480, height: 480}, floor,
      layers: [{id: 'backdrop', ...officeBack}, {id: 'desk-front', ...desk, rect: {x: 0.15, y: 0.66, w: 0.55}, occluder: {baselineY: 0.8}}],
      marks: {'desk-chair': {kind: 'seat', point: {x: 0.42, y: 0.7}, floor: {x: 0.42, y: 0.76}}, visitor: {kind: 'stand', point: {x: 0.66, y: 0.9}}},
      surfaces: {'desk-top': {line: {x0: 0.15, x1: 0.7, y: 0.66}, floorY: 0.8}}}}}),
  };

  // ---- action library (synthetic test data, not a production library)
  const actions = writeJson('actions.json', {schemaVersion: 2, note: 'SYNTHETIC TEST FIXTURE: AP-86 S3 action definitions for tests only.', actions: {
    'stand-at': {needs: {mark: 'stand'}, pose: {stance: 'stand'}, align: {feet: 'mark.point'}, scaleFrom: 'mark.point'},
    'sit-on': {needs: {mark: 'seat'}, pose: {stance: 'sit'}, align: {seat: 'mark.point'}, scaleFrom: 'mark.floor'},
    'sit-on-prop': {needs: {prop: 'seat'}, pose: {stance: 'sit'}, align: {seat: 'prop.seat'}},
    'lean-on': {needs: {surface: true}, pose: {stance: 'lean'}, align: {handLeft: 'surface.line'}, scaleFrom: 'surface.line'},
    hold: {needs: {prop: 'grip'}, pose: {hasAnchor: 'handRight'}, attach: {'prop.grip': 'pose.handRight'}},
  }});

  const member = (id, character, style) => ({id, character, registry: actors[character], speech: {style}});
  const base = (id, setKey, plate, extra) => ({schema: 'oddly-relatable/story@2', id, actionLibrary: actions, endCard: {duration: 1, caption: 'Technical test'},
    scenes: [{id, format: 'face-to-face', set: sets[setKey] === sets.bar ? 'synthetic-bar' : 'synthetic-office', plate, setRegistry: sets[setKey], ...extra}]});
  // §6: A sits on a stool and holds a glass; B leans on the counter; a second glass stands on the counter.
  const barConversation = () => base('bar-conversation', 'bar', 'wide', {
    cast: [member('a', 'synthetic-actor-a', 'him'), member('b', 'synthetic-actor-b', 'neutral')],
    props: [{id: 'stool-a', prop: 'synthetic-stool', registry: props.stool, mark: 'stool-1'},
      {id: 'glass-a', prop: 'synthetic-glass', registry: props.glass},
      {id: 'glass-b', prop: 'synthetic-glass', registry: props.glass, state: 'empty', on: 'counter-top', at: 0.3}],
    blocking: [{who: 'a', do: 'sit-on-prop', prop: 'stool-a'}, {who: 'a', do: 'hold', prop: 'glass-a'}, {who: 'b', do: 'lean-on', surface: 'counter-top', at: 0.62}],
    lines: [
      {speaker: 'a', text: 'Sitting, holding a glass.', duration: 1.5, poses: {a: 'sit', b: 'lean'}, shot: {camera: 'Wide'}},
      {speaker: 'b', text: 'Leaning on the counter.', duration: 1.5, shot: {camera: 'Wide'}},
      {speaker: 'a', text: 'Raising the glass.', duration: 1.5, pose: 'sit-raise', shot: {camera: 'Wide'}},
    ]});
  // §7: A sits at the desk (on a seat mark) with a mug on the desk; B stands at the visitor mark.
  const officeDesk = () => base('office-desk', 'office', 'desk', {
    cast: [member('a', 'synthetic-actor-a', 'him'), member('b', 'synthetic-actor-b', 'neutral')],
    props: [{id: 'mug', prop: 'synthetic-mug', registry: props.mug, on: 'desk-top', at: 0.25}],
    blocking: [{who: 'a', do: 'sit-on', mark: 'desk-chair'}, {who: 'b', do: 'stand-at', mark: 'visitor'}],
    lines: [
      {speaker: 'a', text: 'At my desk.', duration: 1.5, poses: {a: 'sit', b: 'stand'}, shot: {camera: 'Wide'}},
      {speaker: 'b', text: 'Visiting.', duration: 1.5, shot: {camera: 'Wide'}},
      {speaker: 'a', text: 'Hand up.', duration: 1.5, pose: 'sit-raise', shot: {camera: 'Wide'}},
    ]});
  return {dir, actors, props, sets, actions, POSES, barConversation, officeDesk};
}
