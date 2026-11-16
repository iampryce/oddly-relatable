// AP-86 S1 test fixtures: a SYNTHETIC set, prop and action library, written to a temporary folder only.
//
// Not artwork, not a design and never a production asset: every image is a flat grey card labelled
// "SYNTHETIC TEST FIXTURE / NOT ARTWORK", the set and prop registries are marked "synthetic": true (refused by every
// production path unless a test passes allowSynthetic), and nothing here is written inside the repository.
// The numbers (plate fractions, anchors) are arbitrary test values, NOT set, pose or prop standards (O5–O7 are open).
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {canvas, ensureFonts, FONT} from '../../lib/runtime.mjs';

const sha = buf => crypto.createHash('sha256').update(buf).digest('hex');

function card(width, height, label, fill = '#9a9a9a') {
  ensureFonts();
  const c = canvas.createCanvas(width, height), ctx = c.getContext('2d');
  ctx.fillStyle = fill; ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = '#000000'; ctx.font = `700 ${Math.max(8, Math.round(width / 12))}px "${FONT.sans}"`; ctx.textBaseline = 'top';
  ['SYNTHETIC TEST FIXTURE', 'NOT ARTWORK', label].forEach((t, i) => ctx.fillText(t, 4, 4 + i * Math.round(width / 10)));
  return c.toBuffer('image/png');
}

// Writes the kit under dir and returns the file paths plus the parsed JSON (deep-copied, so tests can mutate it).
export function writeSyntheticKit(dir, {mutateSet, mutateProp, mutateActions} = {}) {
  fs.mkdirSync(path.join(dir, 'art'), {recursive: true});
  const art = {};
  for (const [name, w, h] of [['back', 240, 240], ['counter-front', 240, 80], ['stool', 60, 120], ['stool-front', 60, 40], ['glass', 20, 30]]) {
    const buf = card(w, h, name), rel = `art/ap86-synthetic-${name}.png`;
    fs.writeFileSync(path.join(dir, rel), buf);
    art[name] = {file: rel, sha256: sha(buf)};
  }
  const set = {
    set: 'synthetic-bar', schemaVersion: 2, kind: 'interior/bar', synthetic: true, assetRoot: 'registry',
    note: 'SYNTHETIC TEST FIXTURE, NOT ARTWORK. AP-86 S1 schema tests only; never promotable.',
    plates: {
      wide: {
        superframe: {width: 240, height: 240},
        layers: [
          {id: 'back', ...art.back, parallax: 0.9},
          {id: 'counter-front', ...art['counter-front'], rect: {x: 0, y: 0.62, w: 1}, parallax: 1, occluder: {baselineY: 0.74}},
        ],
        floor: {horizonY: 0.38, refFeetY: 0.86, refFigureHeight: 0.42},
        marks: {
          'stool-1': {kind: 'seat', point: {x: 0.36, y: 0.7}, floor: {x: 0.36, y: 0.86}, faces: 'right'},
          'counter-2': {kind: 'stand', point: {x: 0.66, y: 0.86}, faces: 'left'},
          door: {kind: 'entry', point: {x: 0.08, y: 0.84}},
        },
        surfaces: {'counter-top': {line: {x0: 0.2, x1: 0.85, y: 0.64}, floorY: 0.8}},
        actionSafe: {x: 0.22, y: 0.22, w: 0.56, h: 0.56},
        lighting: {key: 'upper-left'},
      },
    },
  };
  const prop = {
    prop: 'synthetic-stool', schemaVersion: 2, synthetic: true, note: 'SYNTHETIC TEST FIXTURE, NOT ARTWORK.',
    defaultState: 'default',
    states: {default: {...art.stool, facing: 'front', anchors: {floor: {x: 30, y: 118}, seat: {x: 30, y: 30}}}},
    affordances: ['seat'], height: 0.22,
    splits: {default: {front: art['stool-front']}},
  };
  const glass = {
    prop: 'synthetic-glass', schemaVersion: 2, synthetic: true, note: 'SYNTHETIC TEST FIXTURE, NOT ARTWORK.',
    defaultState: 'full',
    states: {full: {...art.glass, anchors: {base: {x: 10, y: 29}, grip: {x: 10, y: 15}}}, empty: {...art.glass, anchors: {base: {x: 10, y: 29}, grip: {x: 10, y: 15}}}},
    affordances: ['grip', 'rest'],
  };
  const actions = {
    schemaVersion: 2, note: 'SYNTHETIC TEST FIXTURE: action definitions for AP-86 S1 schema tests only (not a production action library).',
    actions: {
      'stand-at': {needs: {mark: 'stand'}, pose: {stance: 'stand'}, align: {feet: 'mark.point'}, scaleFrom: 'mark.point'},
      'sit-on': {needs: {mark: 'seat'}, pose: {stance: 'sit'}, align: {seat: 'mark.point'}, scaleFrom: 'mark.floor'},
      'sit-on-prop': {needs: {prop: 'seat'}, pose: {stance: 'sit'}, align: {seat: 'prop.seat'}},
      'lean-on': {needs: {surface: true}, pose: {stance: 'lean'}, align: {handLeft: 'surface.line'}, scaleFrom: 'surface.line'},
      hold: {needs: {prop: 'grip'}, pose: {hasAnchor: 'handRight'}, attach: {'prop.grip': 'pose.handRight'}},
      shrug: {needs: {}, pose: {action: 'shrug'}},
    },
  };
  mutateSet?.(set); mutateProp?.(prop); mutateActions?.(actions);
  const write = (name, data) => { const f = path.join(dir, name); fs.writeFileSync(f, JSON.stringify(data, null, 2)); return f; };
  return {
    dir, art,
    setFile: write('synthetic-bar.json', set), propFile: write('synthetic-stool.json', prop), glassFile: write('synthetic-glass.json', glass),
    actionsFile: write('actions.json', actions),
    data: structuredClone({set, prop, glass, actions}),
  };
}

// AP-86 S2 test set: flat, distinctive colours so rendered frames can be checked pixel by pixel.
//   backdrop  480×480 grey (128,128,128): the whole plate
//   counter   480×96 red (220,30,30): an occluder cut-out at plate y 0.62–0.82, baseline 0.74
//   fore      480×48 green (30,160,60): an occluder cut-out at the very bottom, baseline 1 (in front of everyone)
// The floor model and every number are arbitrary test values, NOT a set standard (O5 is open).
export const S2_COLOURS = Object.freeze({backdrop: [128, 128, 128], counter: [220, 30, 30], fore: [30, 160, 60]});
export function writeS2Set(dir, {mutate} = {}) {
  fs.mkdirSync(path.join(dir, 'art'), {recursive: true});
  const hex = c => '#' + c.map(v => v.toString(16).padStart(2, '0')).join('');
  const art = {};
  for (const [name, w, h, colour] of [['backdrop', 480, 480, S2_COLOURS.backdrop], ['counter', 480, 96, S2_COLOURS.counter], ['fore', 480, 48, S2_COLOURS.fore]]) {
    const buf = card(w, h, name, hex(colour)), rel = `art/ap86-s2-${name}.png`;
    fs.writeFileSync(path.join(dir, rel), buf);
    art[name] = {file: rel, sha256: sha(buf)};
  }
  const set = {
    set: 'synthetic-s2', schemaVersion: 2, kind: 'interior/test', synthetic: true, assetRoot: 'registry',
    note: 'SYNTHETIC TEST FIXTURE, NOT ARTWORK. AP-86 S2 depth tests only; never promotable.',
    plates: {
      wide: {
        superframe: {width: 480, height: 480},
        layers: [
          {id: 'backdrop', ...art.backdrop},
          {id: 'counter', ...art.counter, rect: {x: 0, y: 0.62, w: 1}, occluder: {baselineY: 0.74}},
          {id: 'fore', ...art.fore, rect: {x: 0, y: 0.9, w: 1}, occluder: {baselineY: 1}},
        ],
        floor: {horizonY: 0.38, refFeetY: 0.86, refFigureHeight: 0.42},
        marks: {spot: {kind: 'stand', point: {x: 0.5, y: 0.8}}},
        surfaces: {top: {line: {x0: 0.1, x1: 0.9, y: 0.62}}},
      },
    },
  };
  mutate?.(set);
  const file = path.join(dir, 'synthetic-s2.json');
  fs.writeFileSync(file, JSON.stringify(set, null, 2));
  return {file, set: structuredClone(set), art};
}
