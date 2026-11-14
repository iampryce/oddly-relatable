#!/usr/bin/env node
// AP-84B3 local preflight report (compatibility and setup validation).
//
// Runs every check that can be done on this machine, without a GPU, a Pod, an account or any paid download, and
// lists the checks that can only be done during authorised execution. It only reads: it writes nothing, creates
// nothing and approves nothing. A "fail" here means execution must not start.
//
//   node studio/tools/ap84b3/preflight.mjs [--run <run folder>]
//
// Each check has a status: pass, fail, or execution-time (cannot be verified without the Pod; the runbook step that
// verifies it is named).
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {loadLock, loadEnvironment, sha256File, REPO_ROOT} from '../../lib/experiment-spec.mjs';
import {readLedger, allowance, freezeStatus} from '../../lib/experiment-ledger.mjs';
import {padReference} from './pad-reference.mjs';

const sharp = createRequire(path.join(REPO_ROOT, 'skills', 'directing-stickman-videos', 'package.json'))('sharp');
const GB = 1e9;

export async function runPreflight({runDir = null, lockFile, environmentFile, decisionsFile} = {}) {
  const checks = [];
  const add = (id, status, detail) => checks.push({id, status, detail});
  const opt = {...(lockFile ? {lockFile} : {}), ...(decisionsFile ? {decisionsFile} : {})};
  const {lock, sha256, approved} = loadLock({...opt, requireApproved: false});
  add('experiment-lock', approved ? 'pass' : 'fail', `canonical SHA-256 ${sha256}; ${approved ? 'approved in DECISIONS.md' : 'NOT approved: every tool refuses to run'}`);
  let env = null;
  try {
    const e = loadEnvironment({lock, requireApproved: false, ...(environmentFile ? {environmentFile} : {}), ...(decisionsFile ? {decisionsFile} : {})});
    env = e.env;
    add('environment-lock', e.approved ? 'pass' : 'fail', `canonical SHA-256 ${e.sha256}; ${e.approved ? 'approved in DECISIONS.md' : 'NOT approved: the Pod bundle cannot be built'}`);
  } catch (err) { add('environment-lock', 'fail', err.message); }

  // Inputs and the padded reference, reproduced in memory with this machine's image library.
  for (const k of ['editInput', 'control']) {
    const i = lock.inputs[k], ok = fs.existsSync(path.join(REPO_ROOT, i.file)) && sha256File(path.join(REPO_ROOT, i.file)) === i.sha256;
    add(`input-${k}`, ok ? 'pass' : 'fail', `${i.file} ${ok ? 'matches' : 'does NOT match'} the lock`);
  }
  const ref = lock.workflows.S.reference;
  const pad = await padReference({input: path.join(REPO_ROOT, lock.inputs.editInput.file), canvasWidth: ref.canvasWidth, canvasHeight: ref.canvasHeight, padColourRGB: ref.padColourRGB});
  add('padded-reference', pad.meta.output_sha256 === ref.sha256 ? 'pass' : 'fail',
    `reproduced with sharp ${sharp.versions.sharp} / libvips ${sharp.versions.vips}: ${pad.meta.output_sha256 === ref.sha256 ? 'identical to the lock' : `DIFFERENT (${pad.meta.output_sha256}); the padding tool will refuse to write it`}`);

  // Smoke isolation.
  const seeds = Object.values(lock.candidates).map(c => c.seed);
  add('smoke-isolation', !seeds.includes(lock.smoke.seed) && lock.smoke.neverACandidate === true ? 'pass' : 'fail', `smoke seed ${lock.smoke.seed}; candidate seeds ${seeds.join(', ')}; smoke outputs use their own transfer folder and cannot be imported`);

  // Arithmetic on memory and disk (a budget, not a measurement).
  const sum = wf => lock.models.filter(m => !wf || m.workflow === wf).reduce((n, m) => n + Number(m.sizeGB), 0);
  if (env) {
    const vram = env.gpu.minTotalMemoryBytes / GB;
    add('vram-budget', sum('Q') < vram ? 'pass' : 'fail', `Qwen weights ${sum('Q').toFixed(2)} GB (model, text encoder and VAE) against at least ${vram} GB of GPU memory. Peak use during sampling is not known until the smoke run`);
    const disk = lock.provider.containerDiskGB, image = Number(env.image.compressedLayersGB), need = sum() + env.disk.marginGB;
    add('disk-budget', need < disk ? 'pass' : 'fail', `models ${sum().toFixed(2)} GB + margin ${env.disk.marginGB} GB = ${need.toFixed(2)} GB against an ${disk} GB container disk. pod-setup.sh checks the real free space before downloading`);
    add('image-size', 'execution-time', `the image is ${image} GB compressed; whether RunPod counts it against the container disk is not known. Runbook: pod-setup.sh models checks free space first`);
    const caps = Object.entries(env.gpu.allowed).map(([n, g]) => `${n} ${g.computeCapability}`).join(', ');
    add('gpu-compatibility', 'execution-time', `approved GPUs ${caps}. The A40 (8.6) has no FP8 hardware: ComfyUI must up-cast the FP8 weights, which is slower; not verified. Runbook: pod-setup.sh environment`);
    add('image-identity', 'execution-time', `deploy as ${env.image.deployAs}. Whether RunPod accepts a digest reference is not known; if not, stop and return to the owner. pod-setup.sh environment checks the image fingerprint (CUDA ${env.image.fingerprint.CUDA_VERSION}, cuDNN ${env.image.fingerprint.NV_CUDNN_VERSION}, Python ${env.tier1.python}, torch ${env.tier1.torch})`);
  }

  // Ledger and freezes.
  if (runDir) {
    try {
      const led = readLedger(runDir, lock), a = allowance(lock, led.state);
      add('session-ledger', led.state.lockSha256 === sha256 ? 'pass' : 'fail', `ledger valid to entry ${led.head.seq}; ${led.state.sessions.length} session(s); runtime used ${a.priorRuntimeSeconds} s; consumption recorded $${a.priorConsumedUSD}`);
      const open = led.state.sessions.find(s => s.status === 'prepared');
      if (open) add('session-allowance', 'pass', `session ${open.number} is in progress with ${open.prepared.watchdogStopSecondsRemaining} s before the watchdog stops it (earlier sessions used ${open.prepared.priorRuntimeSeconds} s and $${open.prepared.priorConsumedUSD})`);
      else add('session-allowance', a.allowed ? 'pass' : 'fail', a.allowed ? `the next session may use up to ${a.watchdogStopSecondsRemaining} s before the watchdog stops it` : a.reasons.join('; '));
      for (const w of ['Q', 'S']) {
        const f = freezeStatus({ledger: led, workflow: w});
        add(`freeze-${w}`, f.status === 'broken' ? 'fail' : 'pass', f.status === 'broken' ? f.problems.join('; ') : `workflow ${w}: ${f.status === 'frozen' ? 'frozen, file matches the ledger' : 'not frozen yet'}`);
      }
    } catch (err) { add('session-ledger', 'fail', err.message); }
  }

  for (const [id, detail] of [
    ['qwen-latent-node', 'EmptySD3LatentImage with Qwen-Image-Edit-2511 is an unverified compatibility gate. Runbook §11: the Qwen smoke run'],
    ['qwen-shift', 'the shift value is recorded from the real export, not chosen. Runbook §10: workflow freeze'],
    ['comfyui-ipadapter', 'whether the pinned ComfyUI and IP-Adapter node run together, with the explicit loaders and the pinned options. Runbook §10'],
    ['watchdog-authentication', 'how the stop command authenticates on the Pod and where the Pod identifier comes from. Runbook §8: live test before any download'],
    ['ssh-transfer', 'whether file copy over SSH works on RunPod. Runbook §9'],
    ['provider-billing', 'consumption is read from the provider console by a person; no tool here can enforce a hard billing cap. Runbook §6 and §12'],
  ]) add(id, 'execution-time', detail);
  return {ok: !checks.some(c => c.status === 'fail'), checks};
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  (async () => {
    const i = process.argv.indexOf('--run');
    const r = await runPreflight({runDir: i >= 0 ? process.argv[i + 1] : null});
    for (const c of r.checks) console.log(`${c.status.padEnd(14)} ${c.id}: ${c.detail}`);
    console.log(r.ok ? '\nNo local check failed. Execution-time checks remain.' : '\nAt least one local check FAILED. Execution must not start.');
    process.exit(r.ok ? 0 : 1);
  })().catch(e => { console.error(`preflight: ${e.message}`); process.exit(1); });
}
