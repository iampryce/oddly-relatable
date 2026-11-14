#!/usr/bin/env node
// AP-84B3 local reference padding (lock amendment, owner decision L10).
//
// The SDXL + IP-Adapter baseline needs the reference "padded to a square (grey)" so the whole figure reaches the
// image encoder. The IP-Adapter node's own "pad" mode fills with black, so the padding is done here, locally and
// deterministically, before upload: master v3 is centred on a 1536x1536 canvas and the new borders are filled
// with RGB (203, 203, 203). Nothing is redrawn or resized; every original pixel is copied unchanged. The input
// is never modified. The output is write-once and must be outside the repository.
//
//   node studio/tools/ap84b3/pad-reference.mjs --out <padded.png>
//
// The command-line tool refuses to run unless the experiment lock is owner-approved, takes every value from the
// lock, and fails if the result's SHA-256 differs from the one recorded in the lock.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {loadLock, isInside, REPO_ROOT} from '../../lib/experiment-spec.mjs';

const sharp = createRequire(path.join(REPO_ROOT, 'skills', 'directing-stickman-videos', 'package.json'))('sharp');
const sha = b => crypto.createHash('sha256').update(b).digest('hex');

// Pad `input` onto a canvasWidth x canvasHeight canvas filled with padColourRGB, centred. Returns {buffer, meta}.
export async function padReference({input, canvasWidth, canvasHeight, padColourRGB}) {
  if (!Array.isArray(padColourRGB) || padColourRGB.length !== 3 || !padColourRGB.every(v => Number.isInteger(v) && v >= 0 && v <= 255)) throw new Error('padColourRGB must be three integers from 0 to 255');
  const src = fs.readFileSync(input), before = sha(src);
  const [r, g, b] = padColourRGB, background = {r, g, b};
  // Flatten any transparency onto the pad colour first, so the result is plain opaque RGB.
  const {data, info} = await sharp(src).flatten({background}).removeAlpha().raw().toBuffer({resolveWithObject: true});
  const {width: w, height: h} = info;
  if (w > canvasWidth || h > canvasHeight) throw new Error(`the input (${w}x${h}) is larger than the canvas (${canvasWidth}x${canvasHeight})`);
  if ((canvasWidth - w) % 2 || (canvasHeight - h) % 2) throw new Error('the input cannot be centred exactly on this canvas (odd margin)');
  const left = (canvasWidth - w) / 2, top = (canvasHeight - h) / 2;
  const buffer = await sharp({create: {width: canvasWidth, height: canvasHeight, channels: 3, background}})
    .composite([{input: data, raw: {width: w, height: h, channels: 3}, left, top}]).png().toBuffer();
  if (sha(fs.readFileSync(input)) !== before) throw new Error('the input changed while it was being read');
  return {buffer, meta: {tool: 'studio/tools/ap84b3/pad-reference.mjs', source_sha256: before, source_unchanged: true, source_size: {width: w, height: h},
    canvas: {width: canvasWidth, height: canvasHeight}, pad_colour_rgb: padColourRGB, placement: {left, top}, output_sha256: sha(buffer), output_bytes: buffer.length,
    // The PNG encoder is part of the result: a different sharp/libvips version may encode different bytes. Recorded so a mismatch can be explained.
    library: {sharp: sharp.versions?.sharp ?? null, vips: sharp.versions?.vips ?? null},
    method: 'centred on a solid-colour canvas; original pixels copied unchanged; no resizing or redrawing'}};
}

// Build the padded reference exactly as the lock defines it and check it against the lock's recorded hash.
export async function padFromLock({lock, outFile}) {
  const ref = lock.workflows.S.reference, input = lock.inputs.editInput;
  if (ref.source !== input.id || ref.placement !== 'centred' || ref.preparedLocally !== true) throw new Error('the lock does not describe a locally prepared, centred reference');
  const out = path.resolve(outFile);
  if (isInside(path.dirname(out), REPO_ROOT)) throw new Error('the padded reference must be written outside the repository');
  const {buffer, meta} = await padReference({input: path.join(REPO_ROOT, input.file), canvasWidth: ref.canvasWidth, canvasHeight: ref.canvasHeight, padColourRGB: ref.padColourRGB});
  if (meta.source_sha256 !== input.sha256) throw new Error('master v3 does not match the hash in the lock');
  if (meta.output_sha256 !== ref.sha256) throw new Error(`the padded reference's SHA-256 (${meta.output_sha256}) differs from the lock (${ref.sha256}). Nothing was written.`);
  fs.writeFileSync(out, buffer, {flag: 'wx'});
  return meta;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  (async () => {
    const i = process.argv.indexOf('--out');
    if (i < 0 || !process.argv[i + 1]) throw new Error('usage: pad-reference.mjs --out <padded.png, outside the repository>');
    const {lock} = loadLock();                                    // refuses unless the lock is owner-approved
    console.log(JSON.stringify(await padFromLock({lock, outFile: process.argv[i + 1]}), null, 1));
  })().catch(e => { console.error(`pad-reference: ${e.message}`); process.exit(1); });
}
