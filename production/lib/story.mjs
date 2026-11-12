// Story layer (AP-79): a story is a title, a format, optional hook / end card, and an ordered list of scenes.
// Each scene names its storytelling format, its environment (by ID) and its cast (by character ID).
// The older single-file AP-78 "conversation episode" is converted to a one-scene story by episodeToStory().
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {canvas, PRODUCTION_ROOT, REPO_ROOT} from './runtime.mjs';
import {formatFor} from './formats/index.mjs';

export const STORY_SCHEMA = 'oddly-relatable/story@1';
export const EPISODE_SCHEMA = 'oddly-relatable/conversation-episode@1';
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');

export function validateStory(story) {
  if (story?.schema !== STORY_SCHEMA) throw new Error(`Story schema must be "${STORY_SCHEMA}"`);
  if (!Array.isArray(story.scenes) || !story.scenes.length) throw new Error('story: at least one scene is required');
  const ids = new Set();
  for (const [i, s] of story.scenes.entries()) {
    if (!s.id || ids.has(s.id)) throw new Error(`scene ${i + 1}: a unique id is required`);
    ids.add(s.id);
    formatFor(s.format);                       // unknown formats fail here; planned ones fail when compiled
  }
  return story;
}

// AP-78 episode -> one-scene story. Keeps the legacy direct background path and registry path.
export function episodeToStory(ep) {
  if (ep.schema !== EPISODE_SCHEMA) throw new Error(`Episode schema must be "${EPISODE_SCHEMA}"`);
  const cast = ep.character ? [{id: 'primary', character: characterIdFromRegistry(ep.character.registry), registry: ep.character.registry, placement: ep.character.placement, z: 0}] : [];
  return {
    schema: STORY_SCHEMA, id: ep.id, title: ep.title, format: ep.format, hook: ep.hook, endCard: ep.endCard, captions: ep.captions,
    scenes: [{
      id: 'scene-1', format: 'text-chat',
      environment: ep.background?.path ? {file: ep.background.path, focusX: ep.background.focusX, focusY: ep.background.focusY} : null,
      cast, reactionCast: 'primary', header: ep.header, speakers: ep.speakers, timing: ep.timing, events: ep.events,
      layout: ep.layout, bubbles: ep.bubbles, camera: ep.camera, transitions: ep.transitions,
    }],
  };
}
function characterIdFromRegistry(registry) {
  try { return JSON.parse(fs.readFileSync(path.resolve(REPO_ROOT, registry), 'utf8')).character || 'character-01'; } catch { return 'character-01'; }
}

// Environment by registry ID (preferred) or legacy {file}; returns the file and a world rect covering the frame.
export async function resolveEnvironment(env, plane, repoRoot = REPO_ROOT) {
  if (!env) return null;
  let file, focusX = env.focusX ?? 0.5, focusY = env.focusY ?? 0.5;
  if (typeof env === 'string' || env.id) {
    const id = typeof env === 'string' ? env : env.id;
    const reg = JSON.parse(fs.readFileSync(path.join(PRODUCTION_ROOT, 'environments', 'environments.json'), 'utf8'));
    const e = reg.environments[id];
    if (!e) throw new Error(`Unknown environment "${id}" (registry has: ${Object.keys(reg.environments).join(', ')})`);
    file = path.resolve(repoRoot, e.file);
    if (e.sha256 && sha(file) !== e.sha256) throw new Error(`environment "${id}": file hash does not match the registry`);
  } else file = path.resolve(repoRoot, env.file);
  const img = await canvas.loadImage(file);
  const s = Math.max(plane.width / img.width, plane.height / img.height), w = img.width * s, h = img.height * s;
  return {file, rect: {x: (plane.width - w) * focusX, y: (plane.height - h) * focusY, w, h}};
}
