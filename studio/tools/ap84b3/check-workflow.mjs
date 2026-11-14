#!/usr/bin/env node
// AP-84B3 workflow checker (D1-6, addition A4, required by the owner's D1-2 caveat: the exact node graph and
// shift value must be exported, hashed and recorded before any candidate, with no silent workflow changes).
//
// Input: a workflow exported from ComfyUI in API format (Workflow > Export (API)): an object of
//   "<node id>": {"class_type": "...", "inputs": {...}}   where a link is ["<node id>", <output index>].
// The checker confirms that the model files, seed, steps, CFG, sampler, scheduler, size, prompts and batch size
// equal the approved experiment lock, that no LoRA node is present, and prints the SHA-256 to record in the run
// sheet. It reports the values it cannot judge (for workflow Q, the model-sampling shift) so they are recorded.
//
//   node studio/tools/ap84b3/check-workflow.mjs --workflow Q|S --candidate A|B|C --file <exported.json>
//
// Built from the public pinned template only (owner decision: Option A; ComfyUI is not installed locally):
//   comfyui-workflow-templates==0.11.107 (pinned by ComfyUI v0.45.3), templates/image_qwen_image_edit_2511.json,
//   SHA-256 fd2d7ebc17c80ab1e55f8320babd13a568de94c26b67807dbdf2a74cea18b65b.
// That template uses these node types: UNETLoader, CLIPLoader, VAELoader, TextEncodeQwenImageEditPlus,
// ModelSamplingAuraFlow (shift 3.1 in the template), CFGNorm, KSampler, VAEEncode, VAEDecode and an optional
// Lightning LoraLoaderModelOnly. The approved specification differs from the template in two ways the operator
// must apply before exporting: remove the LoRA node, and set the latent size explicitly (an empty-latent node
// at 1024x1536) instead of deriving it from the scaled input image. The API export of this graph has NOT been
// seen (it needs a running ComfyUI), so the checker is deliberately strict: anything it cannot confirm fails.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {loadLock, sha256Buffer} from '../../lib/experiment-spec.mjs';

const isLink = v => Array.isArray(v) && v.length === 2 && typeof v[0] === 'string' && Number.isInteger(v[1]);
const base = p => String(p).split(/[\\/]/).pop();
const num = (lockString, value) => typeof value === 'number' && Number(lockString) === value;

export function checkWorkflow({graph, workflow, candidate, lock}) {
  const problems = [], recorded = {};
  const bad = m => problems.push(m);
  if (!graph || typeof graph !== 'object' || Array.isArray(graph) || 'nodes' in graph) return {ok: false, problems: ['this is not an API-format export (use Workflow > Export (API) in ComfyUI)'], recorded};
  const W = lock.workflows[workflow], C = lock.candidates[candidate];
  if (!W || !C || C.workflow !== workflow) return {ok: false, problems: [`candidate ${candidate} does not use workflow ${workflow}`], recorded};
  const nodes = Object.entries(graph).map(([id, n]) => ({id, type: n?.class_type, inputs: n?.inputs || {}}));
  if (nodes.some(n => typeof n.type !== 'string')) return {ok: false, problems: ['every node needs a class_type'], recorded};
  const ofType = t => nodes.filter(n => n.type === t);
  const byId = id => nodes.find(n => n.id === id);
  // Follow a link upstream until a node satisfying `found` is reached (bounded, so a cycle cannot hang it).
  const trace = (link, found, hops = 12) => {
    let cur = isLink(link) ? byId(link[0]) : null;
    for (let i = 0; cur && i < hops; i++) {
      if (found(cur)) return cur;
      const next = Object.values(cur.inputs).find(isLink);
      cur = next ? byId(next[0]) : null;
    }
    return null;
  };

  // No LoRA anywhere in the exported graph.
  for (const n of nodes) if (/lora/i.test(n.type)) bad(`LoRA node present (${n.type}); the approved workflow uses none`);

  // Exactly one sampler, with the approved settings.
  const samplers = ofType('KSampler');
  if (samplers.length !== 1) bad(`expected exactly one KSampler, found ${samplers.length}`);
  const k = samplers[0];
  if (k) {
    if (k.inputs.seed !== C.seed) bad(`seed is ${JSON.stringify(k.inputs.seed)}, approved ${C.seed}`);
    if (k.inputs.steps !== W.steps) bad(`steps is ${JSON.stringify(k.inputs.steps)}, approved ${W.steps}`);
    if (!num(W.cfg, k.inputs.cfg)) bad(`cfg is ${JSON.stringify(k.inputs.cfg)}, approved ${W.cfg}`);
    if (k.inputs.sampler_name !== W.sampler) bad(`sampler is ${JSON.stringify(k.inputs.sampler_name)}, approved ${W.sampler}`);
    if (k.inputs.scheduler !== W.scheduler) bad(`scheduler is ${JSON.stringify(k.inputs.scheduler)}, approved ${W.scheduler}`);
    if (k.inputs.denoise !== 1) bad(`denoise is ${JSON.stringify(k.inputs.denoise)}, expected 1`);
    // Explicit latent size and batch size.
    const latent = trace(k.inputs.latent_image, n => Number.isInteger(n.inputs.width) && Number.isInteger(n.inputs.height) && 'batch_size' in n.inputs, 1);
    if (!latent) bad('the latent size must be set explicitly by an empty-latent node connected directly to the sampler');
    else {
      if (latent.inputs.width !== W.width || latent.inputs.height !== W.height) bad(`latent size is ${latent.inputs.width}x${latent.inputs.height}, approved ${W.width}x${W.height}`);
      if (latent.inputs.batch_size !== W.batchSize) bad(`batch size is ${JSON.stringify(latent.inputs.batch_size)}, approved ${W.batchSize}`);
    }
    // Prompts: the text that actually reaches the sampler's positive and negative inputs.
    const textOf = n => (typeof n.inputs.prompt === 'string' ? n.inputs.prompt : typeof n.inputs.text === 'string' ? n.inputs.text : null);
    const pos = trace(k.inputs.positive, n => textOf(n) !== null), neg = trace(k.inputs.negative, n => textOf(n) !== null);
    if (!pos) bad('no prompt text reaches the sampler\'s positive input');
    else if (textOf(pos) !== W.prompt) bad('the positive prompt differs from the approved prompt');
    if (!neg) bad('no prompt text reaches the sampler\'s negative input');
    else if (textOf(neg) !== W.negativePrompt) bad('the negative prompt differs from the approved negative prompt');
  }

  const models = Object.fromEntries(lock.models.filter(m => m.workflow === workflow).map(m => [m.role, base(m.saveAs)]));
  const one = (type, input, expected, label) => {
    const found = ofType(type);
    if (found.length !== 1) return bad(`expected exactly one ${type}, found ${found.length}`);
    if (base(found[0].inputs[input]) !== expected) bad(`${label} is ${JSON.stringify(found[0].inputs[input])}, approved ${expected}`);
  };
  if (workflow === 'Q') {
    one('UNETLoader', 'unet_name', models['diffusion-model'], 'diffusion model');
    one('CLIPLoader', 'clip_name', models['text-encoder'], 'text encoder');
    one('VAELoader', 'vae_name', models.vae, 'VAE');
    if (ofType('CheckpointLoaderSimple').length) bad('workflow Q must not load a checkpoint');
    const shift = ofType('ModelSamplingAuraFlow');
    if (shift.length !== 1 || typeof shift[0].inputs.shift !== 'number') bad('expected exactly one ModelSamplingAuraFlow node with a numeric shift');
    else recorded.shift = shift[0].inputs.shift;                     // not an approved value: recorded, not judged
    if (!nodes.some(n => n.type === 'LoadImage')) bad('workflow Q needs the input image (LoadImage)');
  } else {
    one('CheckpointLoaderSimple', 'ckpt_name', models.checkpoint, 'checkpoint');
    if (ofType('UNETLoader').length) bad('workflow S must not load a separate diffusion model');
    const ipa = nodes.filter(n => /^IPAdapter/.test(n.type) && 'weight' in n.inputs);
    if (ipa.length !== 1) bad(`expected exactly one IP-Adapter apply node, found ${ipa.length}`);
    else {
      const a = ipa[0].inputs, A = W.ipAdapter;
      if (!num(A.weight, a.weight)) bad(`IP-Adapter weight is ${JSON.stringify(a.weight)}, approved ${A.weight}`);
      if (a.weight_type !== A.weightType) bad(`IP-Adapter weight type is ${JSON.stringify(a.weight_type)}, approved ${A.weightType}`);
      if (!num(A.startAt, a.start_at) || !num(A.endAt, a.end_at)) bad(`IP-Adapter range is ${JSON.stringify(a.start_at)} to ${JSON.stringify(a.end_at)}, approved ${A.startAt} to ${A.endAt}`);
    }
    for (const n of nodes) if (/controlnet/i.test(n.type)) bad(`ControlNet node present (${n.type}); the approved baseline uses none`);
    for (const n of nodes) if (/refiner/i.test(JSON.stringify(n.inputs))) bad('a refiner is referenced; the approved baseline uses none');
    // The final resize may be done in the workflow or locally. If it is in the workflow it must be the approved one.
    const resize = nodes.filter(n => n.type === 'ImageScale');
    recorded.resizeInWorkflow = resize.length > 0;
    for (const r of resize) if (r.inputs.upscale_method !== W.finalResize || r.inputs.width !== W.finalWidth || r.inputs.height !== W.finalHeight) bad(`resize is ${r.inputs.upscale_method} ${r.inputs.width}x${r.inputs.height}, approved ${W.finalResize} ${W.finalWidth}x${W.finalHeight}`);
    if (!nodes.some(n => n.type === 'LoadImage')) bad('workflow S needs the reference image (LoadImage)');
  }
  recorded.nodeTypes = [...new Set(nodes.map(n => n.type))].sort();
  return {ok: problems.length === 0, problems, recorded};
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const arg = n => { const i = process.argv.indexOf(n); return i >= 0 ? process.argv[i + 1] : undefined; };
    const workflow = arg('--workflow'), candidate = arg('--candidate'), file = arg('--file');
    if (!['Q', 'S'].includes(workflow) || !['A', 'B', 'C'].includes(candidate) || !file) throw new Error('usage: check-workflow.mjs --workflow Q|S --candidate A|B|C --file <exported API-format JSON>');
    const {lock, sha256: lockSha256} = loadLock();                              // refuses unless the lock is owner-approved
    const bytes = fs.readFileSync(file);
    const result = checkWorkflow({graph: JSON.parse(bytes.toString('utf8')), workflow, candidate, lock});
    console.log(JSON.stringify({workflow, candidate, lockSha256, apiSha256: sha256Buffer(bytes), ...result}, null, 1));
    if (!result.ok) process.exit(1);
  } catch (e) { console.error(`check-workflow: ${e.message}`); process.exit(1); }
}
