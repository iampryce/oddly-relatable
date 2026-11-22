// node --test: the GPU state line, session rows and the all-in cost per clip.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {allInPerClip, gpuLine, sessionLine} from './gpuView.ts';

test('the GPU line says the mode, the month against the cap and why it cannot run', () => {
  assert.equal(gpuLine({mode: 'off'}), 'Self-hosted GPU: off (Settings > GPU worker)');
  assert.equal(gpuLine({mode: 'own', ok: true}), 'Self-hosted GPU: our own machine, no rental cost');
  const r = {mode: 'rented', gpu_type: 'NVIDIA H100 PCIe', price_per_hour: 2.89, spent_usd: 1.2, cap_usd: 50, reservation_usd: 6.0208,
    max_lifetime_minutes: 120, ok: true, warn_at: 0.8, warning: false, live_session: false};
  assert.equal(gpuLine(r), 'Self-hosted GPU: rented NVIDIA H100 PCIe at $2.89/h · $1.20 spent this month of the $50.00 cap · a new session reserves $6.02 (boot + up to 120 min)');
  assert.match(gpuLine({...r, ok: false, reason: 'Paused: monthly GPU cap reached', warning: true}), /over 80% of the cap · cannot run: Paused/);
  assert.match(gpuLine({...r, live_session: true}), /a session is running/);
});

test('session rows and the all-in cost per clip', () => {
  const s = {gpu_type: 'NVIDIA H100 PCIe', price_per_hour: 2.89, clips: 4, cost_usd: 1.0, status: 'ended', ended_at: 1795300000, reason: 'idle for 5 min'};
  assert.match(sessionLine(s), /4 clip\(s\) · \$1\.00 · ended .* \(idle for 5 min\)/);
  assert.equal(allInPerClip(s), 0.25);
  assert.equal(allInPerClip({...s, clips: 0}), null);
  assert.match(sessionLine({...s, status: 'ready', launched_at: 1795300000, reserved_usd: 6.02}), /ready since .* reserved \$6\.02/);
});
