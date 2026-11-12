// Story catalogue: only approved story files inside production/stories/ can be produced from the studio.
// Validation and timing reuse the production engine's own story layer and format strategies (no re-implementation).
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {PRODUCTION_ROOT} from '../../production/lib/runtime.mjs';
import {validateStory} from '../../production/lib/story.mjs';
import {formatFor} from '../../production/lib/formats/index.mjs';

export const STORIES_DIR = path.join(PRODUCTION_ROOT, 'stories');
const NAME = /^[a-z0-9][a-z0-9-]{0,80}\.story\.json$/;
const sha = buf => crypto.createHash('sha256').update(buf).digest('hex');

export function storyPath(file) {
  if (typeof file !== 'string' || !NAME.test(file)) throw Object.assign(new Error('storyFile must be the name of a *.story.json file in production/stories/'), {status: 400});
  const p = path.join(STORIES_DIR, file);
  if (!fs.existsSync(p)) throw Object.assign(new Error(`story not found: ${file}`), {status: 404});
  return p;
}

// Read-only summary of a story: identity, duration, scenes, formats, hash, validity.
export function storyInfo(file) {
  const p = storyPath(file), buf = fs.readFileSync(p);
  const info = {file, sha256: sha(buf)};
  try {
    const story = JSON.parse(buf.toString('utf8'));
    validateStory(story);
    const fps = story.format?.fps ?? 30, frame = t => Math.ceil(t * fps - 1e-6) / fps;
    let duration = 0;
    for (const sc of story.scenes) {
      const f = formatFor(sc.format);
      if (!f.implemented) throw new Error(`scene "${sc.id}" uses format "${sc.format}", which is not implemented yet`);
      duration += frame(f.sequence(sc).duration);
    }
    if (story.endCard) duration = frame(duration + (story.endCard.hold ?? 0) + (story.endCard.duration ?? 3));
    Object.assign(info, {valid: true, id: story.id, title: story.title || story.id, duration: +duration.toFixed(3), fps,
      size: `${story.format?.width ?? 1080}x${story.format?.height ?? 1920}`, scenes: story.scenes.length,
      formats: [...new Set(story.scenes.map(s => s.format))], cast: [...new Set(story.scenes.flatMap(s => (s.cast || []).map(m => m.character)))]});
  } catch (e) { Object.assign(info, {valid: false, error: e.message}); }
  return info;
}

export function listStories() {
  if (!fs.existsSync(STORIES_DIR)) return [];
  return fs.readdirSync(STORIES_DIR).filter(f => NAME.test(f)).sort().map(storyInfo);
}
