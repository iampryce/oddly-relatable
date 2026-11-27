// Read-only helper for Rivet AI Studio: when each dialogue line starts in the finished episode.
// Uses the production engine's public functions (compileStory for scene start times, each format's sequence() for line
// timing inside a scene). Writes only to the temporary folder given. Usage:
//   node line-timings.mjs STORY.json TMP_DIR   ->  prints [{scene, lines: [{start, duration}]}] as JSON
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const [storyFile, tmp] = process.argv.slice(2);
const repo = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')), '..', '..', '..', '..');
const imp = p => import(pathToFileURL(path.join(repo, p)).href);
const {compileStory} = await imp('production/lib/scene.mjs');
const {formatFor} = await imp('production/lib/formats/index.mjs');
const story = JSON.parse(fs.readFileSync(storyFile, 'utf8'));
const {report} = await compileStory(story, {outDir: tmp, allowIssues: true});
const out = story.scenes.map((s, i) => {
  const seq = formatFor(s.format).sequence(s);
  const start = report.scenes[i].start;
  // duration: the scene's own length on the frame grid (without the end card the engine adds to the last scene).
  const duration = Math.ceil(seq.duration * story.format.fps - 1e-6) / story.format.fps;
  return {scene: s.id, start: +start.toFixed(4), duration: +duration.toFixed(4),
    lines: seq.messages.map(m => ({start: +(start + m.start).toFixed(3), duration: m.duration}))};
});
process.stdout.write(JSON.stringify(out));
