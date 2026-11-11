#!/usr/bin/env node
// Oddly Relatable production toolkit CLI.
//   build      EPISODE.json OUT_DIR [--allow-issues]   compile a conversation episode into a renderer project
//   storyboard OUT_DIR/project.json [--out FILE]      renderer-exact stills at key moments, as one sheet
//   video      OUT_DIR/project.json [--seconds N] [--replace]   MP4 preview via the unmodified renderer CLI
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {compileEpisode} from './lib/scene.mjs';
import {storyboardSheet} from './lib/preview.mjs';
import {SKILL_ROOT} from './lib/runtime.mjs';

const [cmd, ...args] = process.argv.slice(2);
const opt = (flag, fallback) => (args.includes(flag) ? args[args.indexOf(flag) + 1] : fallback);

async function main() {
  if (cmd === 'build') {
    if (!args[0] || !args[1]) throw new Error('Usage: build EPISODE.json OUT_DIR [--allow-issues]');
    const {projectFile, report} = await compileEpisode(args[0], {outDir: args[1], allowIssues: args.includes('--allow-issues')});
    console.log(JSON.stringify({project: projectFile, duration: report.duration, messages: report.messages.length, typing: report.typing.length,
      poses: report.poses.map(p => p.pose), checks_ok: report.checks.ok, issues: report.checks.issues, warnings: report.checks.warnings}, null, 2));
  } else if (cmd === 'storyboard') {
    if (!args[0]) throw new Error('Usage: storyboard PROJECT.json [--out FILE]');
    const dir = path.dirname(path.resolve(args[0]));
    const report = JSON.parse(fs.readFileSync(path.join(dir, 'layout-report.json'), 'utf8'));
    const out = path.resolve(opt('--out', path.join(dir, 'storyboard', 'storyboard-sheet.png')));
    await storyboardSheet(args[0], report.storyboardTimes, {outFile: out, framesDir: path.join(path.dirname(out), 'frames')});
    console.log(JSON.stringify({storyboard: out, frames: report.storyboardTimes.length}));
  } else if (cmd === 'video') {
    if (!args[0]) throw new Error('Usage: video PROJECT.json [--seconds N] [--replace]');
    const seconds = opt('--seconds', '60');
    const extra = args.includes('--replace') ? ['--replace'] : [];
    const r = spawnSync(process.execPath, [path.join(SKILL_ROOT, 'scripts', 'autopilot.mjs'), 'preview', path.resolve(args[0]), '--seconds', seconds, ...extra], {stdio: 'inherit'});
    process.exitCode = r.status ?? 1;
  } else {
    throw new Error('Commands: build EPISODE.json OUT_DIR | storyboard PROJECT.json [--out FILE] | video PROJECT.json [--seconds N] [--replace]');
  }
}
main().catch(e => { console.error(e.message); process.exitCode = 1; });
