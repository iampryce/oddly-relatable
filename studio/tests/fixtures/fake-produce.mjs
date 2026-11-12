// Test double for `production/cli.mjs produce` (studio tests only). Usage: fake-produce.mjs <story> <outDir> <mode>
// Writes the same run-file / artifact layout as the real engine so the job runner can be tested in seconds.
import fs from 'node:fs';
import path from 'node:path';

const [, , story, out, mode = 'ok'] = process.argv;
const sleep = ms => new Promise(r => setTimeout(r, ms));
for (const d of ['render', 'reports', 'storyboard/frames', 'audio']) fs.mkdirSync(path.join(out, d), {recursive: true});
const run = {tool: 'fake', status: 'running', stages: []};
const save = () => fs.writeFileSync(path.join(out, 'production-run.json'), JSON.stringify(run));
save();
console.log(`fake produce ${path.basename(story)} mode=${mode}`);
for (const s of ['environment', 'compile', 'audio']) { run.stages.push({stage: s, status: 'done', seconds: 0.1}); save(); await sleep(60); }

if (mode === 'crash') { console.error('simulated engine failure: compile error in scene 1'); process.exit(1); }
if (mode === 'hang') { run.stages.push({stage: 'render', status: 'running'}); save(); await sleep(600000); }

fs.writeFileSync(path.join(out, 'render', 'fake.mp4'), Buffer.from('0123456789abcdefFAKEVIDEO'));
fs.writeFileSync(path.join(out, 'storyboard', 'storyboard-sheet.png'), Buffer.from([0x89, 0x50, 0x4e, 0x47]));
fs.writeFileSync(path.join(out, 'storyboard', 'frames', '01-t0.70.png'), Buffer.from([0x89, 0x50, 0x4e, 0x47]));
const qaFail = mode === 'qa-fail';
fs.writeFileSync(path.join(out, 'reports', 'qa-report.json'), JSON.stringify({status: qaFail ? 'fail' : 'pass', failed: qaFail ? 1 : 0, warnings: 1,
  checks: [{id: 'duration', status: qaFail ? 'fail' : 'pass', detail: 'x'}, {id: 'quality-warning-1', status: 'warn', detail: 'soft'}], note: 'Technical QA only.'}));
fs.writeFileSync(path.join(out, 'production-manifest.json'), JSON.stringify({status: 'x', outputs: []}));
run.stages.push({stage: 'render', status: 'done', seconds: 0.2}, {stage: 'qa', status: 'done', seconds: 0.1});
Object.assign(run, {status: qaFail ? 'qa-failed' : 'produced', render: {frames: 3}, qa: {status: qaFail ? 'fail' : 'pass'}, seconds: 0.5});
save();
process.exit(qaFail ? 2 : 0);
