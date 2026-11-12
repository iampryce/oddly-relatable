#!/usr/bin/env node
// Oddly Relatable production toolkit CLI.
//   build      STORY.json|EPISODE.json OUT_DIR [--allow-issues]   compile a story (or AP-78 episode) into a renderer project
//   storyboard OUT_DIR/project.json [--out FILE]      renderer-exact stills at key moments, as one sheet
//   video      OUT_DIR/project.json [--seconds N] [--replace]   MP4 preview via the unmodified renderer CLI
//   produce    STORY.json OUT_DIR [--replace] [--allow-issues] [--skip-render] [--approval-note TEXT]
//              full run: compile, audio bed, storyboard, MP4, audio export, QA, reports, manifest
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {compileProject} from './lib/scene.mjs';
import {storyboardSheet} from './lib/preview.mjs';
import {SKILL_ROOT} from './lib/runtime.mjs';
import {produceEpisode} from './lib/produce.mjs';

const [cmd, ...args] = process.argv.slice(2);
const opt = (flag, fallback) => (args.includes(flag) ? args[args.indexOf(flag) + 1] : fallback);

async function main() {
  if (cmd === 'build') {
    if (!args[0] || !args[1]) throw new Error('Usage: build STORY.json|EPISODE.json OUT_DIR [--allow-issues]');
    const {projectFile, report} = await compileProject(args[0], {outDir: args[1], allowIssues: args.includes('--allow-issues')});
    console.log(JSON.stringify({project: projectFile, duration: report.duration, messages: report.messages.length, typing: report.typing.length,
      poses: report.poses.map(p => p.pose), scenes: report.scenes.length, camera_cuts: report.camera.reduce((a, c) => a + c.cuts.length, 0), camera_moves: report.camera.reduce((a, c) => a + c.moves.length, 0), checks_ok: report.checks.ok, issues: report.checks.issues, warnings: report.checks.warnings}, null, 2));
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
  } else if (cmd === 'produce') {
    if (!args[0] || !args[1]) throw new Error('Usage: produce STORY.json OUT_DIR [--replace] [--allow-issues] [--skip-render] [--approval-note TEXT]');
    const r = await produceEpisode(args[0], {outDir: args[1], replace: args.includes('--replace'), allowIssues: args.includes('--allow-issues'), skipRender: args.includes('--skip-render'), approvalNote: opt('--approval-note', null)});
    console.log(JSON.stringify({status: r.status, output: r.dir, seconds: r.report.seconds, stages: r.report.stages, render: r.report.render, audio: r.report.audio, qa: r.report.qa, layoutWarnings: r.report.layout?.warnings, awaiting: r.report.awaiting}, null, 2));
    if (!['produced', 'built'].includes(r.status)) process.exitCode = 2;
  } else {
    throw new Error('Commands: produce STORY.json OUT_DIR | build STORY.json|EPISODE.json OUT_DIR | storyboard PROJECT.json [--out FILE] | video PROJECT.json [--seconds N] [--replace]');
  }
}
main().catch(e => { console.error(e.message); process.exitCode = 1; });
