// Shared runtime for the Oddly Relatable production toolkit.
// The toolkit adds NO dependencies: it borrows the renderer's already-installed packages
// (@napi-rs/canvas) and bundled fonts read-only, and never writes inside the renderer's folder.
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath, pathToFileURL} from 'node:url';

export const PRODUCTION_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const REPO_ROOT = path.resolve(PRODUCTION_ROOT, '..');
export const SKILL_ROOT = path.join(REPO_ROOT, 'skills', 'directing-stickman-videos');

const skillRequire = createRequire(path.join(SKILL_ROOT, 'package.json'));
export const canvas = skillRequire('@napi-rs/canvas');

export const FONT_FILES = {
  sans: path.join(SKILL_ROOT, 'assets', 'fonts', 'NotoSans.ttf'),
  hand: path.join(SKILL_ROOT, 'assets', 'fonts', 'Caveat.ttf'),
};
export const FONT = {sans: 'OR Sans', hand: 'OR Hand'};

let fontsReady = false;
export function ensureFonts() {
  if (fontsReady) return;
  for (const [key, file] of Object.entries(FONT_FILES)) {
    if (!fs.existsSync(file)) throw new Error(`Missing bundled font: ${file}`);
    if (!canvas.GlobalFonts.registerFromPath(file, FONT[key])) throw new Error(`Font registration failed: ${file}`);
  }
  fontsReady = true;
}

// Import the renderer's own modules (read-only use of its public functions).
export async function rendererModules() {
  const core = await import(pathToFileURL(path.join(SKILL_ROOT, 'scripts', 'autopilot-core.mjs')).href);
  const render = await import(pathToFileURL(path.join(SKILL_ROOT, 'scripts', 'autopilot-render.mjs')).href);
  return {core, render};
}

// The renderer draws on a 1280-unit-wide design plane, scaled uniformly to the output size.
export function designPlane(width, height) {
  return {width: 1280, height: 1280 * height / width};
}

// Refuse to write into protected locations (renderer folder, canonical artwork folder).
export function assertWritableOutput(dir) {
  const target = path.resolve(dir);
  const protectedDirs = [SKILL_ROOT, path.join(REPO_ROOT, 'bible')];
  for (const p of protectedDirs) {
    if (target === p || target.startsWith(p + path.sep)) throw new Error(`Refusing to write into protected folder: ${p}`);
  }
  return target;
}
