// Generation worker adapters (AP-84B1). Interface:
//   status()                 -> {available: boolean, reason}
//   generate(request, ctx)   -> [{name, buffer, width, height, synthetic, provenance}]
// "none" is the default and never produces anything. "fake" draws a deterministic, clearly labelled synthetic test
// card (not artwork) so the queue, quarantine and review flow can be exercised without any model, GPU or service.
// RunPod/ComfyUI adapters are future work (AP-84B3+), not implemented here.
import crypto from 'node:crypto';
import {canvas, ensureFonts, FONT} from '../../production/lib/runtime.mjs';

export class NoWorkerError extends Error {
  constructor() { super('No generation worker is configured (adapter "none"). Nothing was generated.'); this.code = 'NO_WORKER'; this.retryable = false; }
}

export const noneAdapter = {
  id: 'none',
  status: () => ({available: false, reason: 'No generation worker is configured. Generation jobs can be queued and reviewed, but nothing is generated.'}),
  async generate() { throw new NoWorkerError(); },
};

// Deterministic seed from the request (and attempt), so identical requests give byte-identical fixtures.
export const requestSeed = (request, attempt) => crypto.createHash('sha256').update(JSON.stringify({assetType: request.assetType, assetKey: request.assetKey, description: request.description, attempt})).digest('hex');

export const fakeAdapter = {
  id: 'fake',
  status: () => ({available: true, reason: 'Local fake adapter: produces labelled synthetic test fixtures only (never artwork).'}),
  async generate(request, {attempt = 1} = {}) {
    ensureFonts();
    const seed = requestSeed(request, attempt), W = 512, H = 768;
    const c = canvas.createCanvas(W, H), ctx = c.getContext('2d');
    // Diagonal test-card stripes in grey and magenta: unmistakably not production artwork.
    ctx.fillStyle = '#9a9a9a'; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = '#d13ad1';
    for (let x = -H; x < W + H; x += 64) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x + 32, 0); ctx.lineTo(x + 32 + H, H); ctx.lineTo(x + H, H); ctx.closePath(); ctx.fill(); }
    ctx.fillStyle = '#ffffff'; ctx.fillRect(24, 250, W - 48, 268);
    ctx.fillStyle = '#000000'; ctx.textBaseline = 'top';
    ctx.font = `700 34px "${FONT.sans}"`; ctx.fillText('SYNTHETIC TEST FIXTURE', 40, 266);
    ctx.font = `600 22px "${FONT.sans}"`; ctx.fillText('NOT ARTWORK · NOT FOR PRODUCTION', 40, 314);
    ctx.font = `400 18px "${FONT.sans}"`;
    ctx.fillText(`type: ${request.assetType}`, 40, 360);
    ctx.fillText(`key: ${String(request.assetKey).slice(0, 36)}`, 40, 388);
    ctx.fillText(`attempt: ${attempt}`, 40, 416);
    ctx.fillText(`seed: ${seed.slice(0, 24)}`, 40, 444);
    ctx.fillText('adapter: fake (AP-84B1)', 40, 472);
    const buffer = c.toBuffer('image/png');
    return [{name: `synthetic-test-fixture-${seed.slice(0, 12)}.png`, buffer, width: W, height: H, synthetic: true,
      provenance: {adapter: 'fake', synthetic: true, seed, attempt, generator: 'studio/lib/gen-adapters.mjs fakeAdapter', note: 'Synthetic test fixture for pipeline testing; contains no artwork.'}}];
  },
};

export const ADAPTERS = Object.freeze({none: noneAdapter, fake: fakeAdapter});
export function adapterFor(id) {
  const a = ADAPTERS[id];
  if (!a) throw new Error(`Unknown generation adapter "${id}" (available: ${Object.keys(ADAPTERS).join(', ')})`);
  return a;
}
