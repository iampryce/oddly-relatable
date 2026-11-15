// AP-85 P1 test fixture: a SYNTHETIC PLACEHOLDER standing in for a second character in Track A tests.
//
// This is NOT Character 02 and NOT artwork. It is a deliberately crude, code-drawn figure in flat test colours that
// share no colour with Character 01 (no cream skin, no rust, no brown), labelled "SYNTHETIC PLACEHOLDER - NOT ARTWORK"
// on the figure itself. It exists only so the engine's composition can be tested pixel by pixel: any pixel of these
// colours inside Character 01's area (or of Character 01's colours inside the placeholder's area) is a swap or a blend.
//
// Rules: it is written only to a temporary folder at test time (never to production/characters or the bible); its
// registry is marked "synthetic": true, which the cast model refuses unless a test passes allowSynthetic; it never
// enters the studio, quarantine or promotion. It says nothing about Character 02's role, name, design or colours.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {canvas, ensureFonts, FONT} from '../../lib/runtime.mjs';

export const PLACEHOLDER_CHARACTER = 'character-02-placeholder';
// Flat test colours, far from Character 01's palette (skin #FCDEB4, rust #BC4C15, shoe #84563B).
export const PLACEHOLDER_COLOURS = Object.freeze({body: [0, 80, 255], head: [0, 200, 80], label: [255, 230, 0]});
const hex = c => `#${c.map(v => v.toString(16).padStart(2, '0')).join('')}`;
const W = 300, H = 620, FEET = {x: 150, y: 610}, FIGURE_HEIGHT = 600;

// Poses: arms differ per pose; a triangle on the head points the way the figure faces.
// p1/p2 are drawn facing left with right-facing variants; p3 faces left only (used to test the "no artwork" error).
const POSES = [
  {id: 'p1', arms: 'down', facing: 'left', variant: {right: 'p1-r'}},
  {id: 'p1-r', arms: 'down', facing: 'right'},
  {id: 'p2', arms: 'up', facing: 'left', variant: {right: 'p2-r'}},
  {id: 'p2-r', arms: 'up', facing: 'right'},
  {id: 'p3', arms: 'both-up', facing: 'left'},
];

function drawPose({arms, facing}) {
  ensureFonts();
  const c = canvas.createCanvas(W, H), ctx = c.getContext('2d');
  const body = hex(PLACEHOLDER_COLOURS.body), head = hex(PLACEHOLDER_COLOURS.head);
  ctx.fillStyle = body;
  ctx.fillRect(105, 190, 90, 240);                          // torso
  ctx.fillRect(110, 430, 26, 180); ctx.fillRect(164, 430, 26, 180);   // legs, feet at y = 610
  const arm = (x, up) => up ? ctx.fillRect(x, 120, 22, 110) : ctx.fillRect(x, 200, 22, 150);
  arm(78, arms === 'both-up'); arm(200, arms !== 'down');
  ctx.fillStyle = head;
  ctx.beginPath(); ctx.arc(150, 105, 85, 0, Math.PI * 2); ctx.fill();          // head (no face: it is not a character)
  const dir = facing === 'right' ? 1 : -1;                                     // facing marker
  ctx.beginPath(); ctx.moveTo(150 + dir * 82, 90); ctx.lineTo(150 + dir * 112, 105); ctx.lineTo(150 + dir * 82, 120); ctx.closePath(); ctx.fill();
  ctx.fillStyle = hex(PLACEHOLDER_COLOURS.label);
  ctx.fillRect(100, 270, 100, 76);                                            // label band
  ctx.fillStyle = '#000000'; ctx.textBaseline = 'top'; ctx.font = `700 15px "${FONT.sans}"`;
  ['SYNTHETIC', 'PLACEHOLDER', 'NOT ARTWORK'].forEach((t, i) => ctx.fillText(t, 104, 276 + i * 22));
  return c.toBuffer('image/png');
}

// Write the placeholder registry and its pose PNGs into `dir` (a temporary folder). Returns the registry path.
// mutate(registry) may alter the registry before it is written (used by tests of registry independence).
export function writePlaceholder(dir, {mutate = null, character = PLACEHOLDER_CHARACTER} = {}) {
  fs.mkdirSync(dir, {recursive: true});
  const poses = {};
  for (const p of POSES) {
    const buf = drawPose(p), file = path.join(dir, `${p.id}.png`);
    fs.writeFileSync(file, buf);
    poses[p.id] = {name: `placeholder-${p.id}`, file, sha256: crypto.createHash('sha256').update(buf).digest('hex'), feet: FEET, figureHeight: FIGURE_HEIGHT,
      headFraction: 0.3, facing: p.facing, ...(p.variant ? {facingVariants: p.variant} : {}), status: 'SYNTHETIC TEST PLACEHOLDER'};
  }
  const registry = {character, displayName: 'SYNTHETIC PLACEHOLDER (test fixture, not artwork)', synthetic: true,
    note: 'AP-85 P1 Track A test fixture. Not Character 02, not artwork, never promoted, never used in production.', poses};
  if (mutate) mutate(registry);
  const registryFile = path.join(dir, `${character}.json`);
  fs.writeFileSync(registryFile, JSON.stringify(registry, null, 1));
  return registryFile;
}
