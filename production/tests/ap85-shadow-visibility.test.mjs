// AP-85 corrective task (approved 2026-11-16): shadow visibility in single shots.
//
// A member's shadow must be visible exactly when the member is on camera: absent while the member is off camera in
// another member's single, back when the member returns, and never duplicated. Uses the accepted AP-85 A4 scene
// (wide, single on ph, single on c01, close single on c01, close single on ph, wide) and A1 (no singles), taken from the
// Track A test file so the scenes are exactly the accepted ones. Pixel checks use the UNMODIFIED renderer's painter.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {compileProject} from '../lib/scene.mjs';
import {rendererModules, PRODUCTION_ROOT} from '../lib/runtime.mjs';
import {writePlaceholder, PLACEHOLDER_CHARACTER} from './fixtures/ap85-placeholder.mjs';

const needsRenderer = {skip: process.env.FFPROBE ? false : 'set FFMPEG/FFPROBE to run renderer-backed checks'};
const tmp = n => fs.mkdtempSync(path.join(os.tmpdir(), `ap85sh-${n}-`));
const PH = PLACEHOLDER_CHARACTER;
// The accepted AP-85 scenes, evaluated from the Track A test file (the same method as the AP-85 review sheets).
const SCENES = (() => {
  const src = fs.readFileSync(path.join(PRODUCTION_ROOT, 'tests', 'ap85-track-a.test.mjs'), 'utf8');
  const a = src.indexOf('const c01 = '), s = src.indexOf('const SCENES = {', a), b = src.indexOf('\n};\n', s);
  return new Function('C01', 'PH', 'PH_REG', `${src.slice(a, b + 3)}\nreturn SCENES;`)('character-01', PH, writePlaceholder(tmp('ph')));
})();
const build = async name => { const dir = tmp(name), r = await compileProject(SCENES[name](), {outDir: dir, allowSynthetic: true}); return {...r, dir, project: JSON.parse(fs.readFileSync(r.projectFile, 'utf8'))}; };
const layers = b => b.project.shots[0].layers;
const isPose = id => l => l.path.includes(id === 'c01' ? '/character-01-pose-' : `/${PH}-pose-`);
// Shadows are drawn immediately before their member's pose layers; this gives each shadow layer its owner.
function shadowsByMember(b) {
  const L = layers(b), out = {c01: [], ph: []};
  L.forEach((l, i) => {
    if (!l.path.includes('/shadow-')) return;
    const next = L.slice(i + 1).find(x => isPose('c01')(x) || isPose('ph')(x));
    out[isPose('c01')(next) ? 'c01' : 'ph'].push({layer: l, index: i});
  });
  return out;
}
const windowOf = (l, duration) => [l.from ?? 0, l.to ?? duration];
const activeAt = (l, t, duration) => { const [a, z] = windowOf(l, duration); return t >= a - 1e-9 && t < z - 1e-9; };
// When each member is on camera, from the report's shots (a member is off camera in a single on someone else).
function onCamera(report, id) {
  const out = [];
  for (const s of report.camera[0].shots) {
    if (s.hidden.includes(id)) continue;
    const last = out.at(-1);
    if (last && Math.abs(last[1] - s.start) < 1e-9) last[1] = s.end; else out.push([s.start, s.end]);
  }
  return out;
}

test('AP-85 shadows: in the render plan every shadow is shown exactly while its member is on camera, once, never duplicated', async () => {
  const b = await build('A4'), dur = b.report.scenes[0].duration, by = shadowsByMember(b);
  assert.deepEqual(onCamera(b.report, 'c01'), [[0, 1.5], [3, 6], [7.5, dur]]);
  assert.deepEqual(onCamera(b.report, 'ph'), [[0, 3], [6, dur]]);
  for (const id of ['c01', 'ph']) {
    // One shadow layer per on-camera interval, with exactly that window.
    assert.deepEqual(by[id].map(x => windowOf(x.layer, dur)), onCamera(b.report, id), `${id}: shadow windows equal the on-camera intervals`);
    // At every frame: one shadow while on camera, none while off camera.
    const pose = layers(b).filter(isPose(id));
    for (let f = 0; f < Math.round(dur * 30); f++) {
      const t = f / 30, shadows = by[id].filter(x => activeAt(x.layer, t, dur)).length, visible = pose.some(l => t >= l.from - 1e-9 && t < l.to - 1e-9);
      assert.equal(shadows, visible ? 1 : 0, `${id} at ${t.toFixed(3)}s: ${shadows} shadow layer(s) while the member is ${visible ? 'on' : 'off'} camera`);
    }
    // Each windowed shadow's keys lie inside its window, and its centre is under the member's feet in that window.
    for (const {layer} of by[id]) {
      const [a, z] = windowOf(layer, dur);
      assert.ok(layer.keys[0].t >= a - 1e-9 && layer.keys.at(-1).t < z - 1e-9, `${id}: shadow keys inside [${a}, ${z})`);
    }
  }
  // A scene without singles keeps one whole-shot shadow per member, with no window (unchanged from before the fix).
  const a1 = shadowsByMember(await build('A1'));
  assert.deepEqual([a1.c01.length, a1.ph.length], [1, 1]);
  assert.ok([...a1.c01, ...a1.ph].every(x => x.layer.from === undefined && x.layer.to === undefined), 'no window when the member is always on camera');
});

test('AP-85 shadows in rendered frames: present in the wide shot, gone with the member in another member\'s single, back when it returns', needsRenderer, async () => {
  const b = await build('A4'), dur = b.report.scenes[0].duration, by = shadowsByMember(b), L = layers(b);
  const {core, render} = await rendererModules();
  const paint = async drop => {
    const p = structuredClone(b.project); p.shots[0].layers = L.filter((l, i) => !drop.includes(i));
    const f = path.join(b.dir, `drop-${crypto.randomBytes(4).toString('hex')}.json`); fs.writeFileSync(f, JSON.stringify(p));
    const draw = await render.painter(core.loadProject(f)); return t => draw(t).getContext('2d').getImageData(0, 0, 1080, 1920).data;
  };
  const full = await paint([]), changed = (x, y) => { let n = 0; for (let i = 0; i < x.length; i += 4) if (x[i] !== y[i] || x[i + 1] !== y[i + 1] || x[i + 2] !== y[i + 2]) n++; return n; };
  const without = {}; for (const id of ['c01', 'ph']) without[id] = await paint(by[id].map(x => x.index));
  const each = {}; for (const id of ['c01', 'ph']) each[id] = await Promise.all(by[id].map(x => paint([x.index])));
  const expect = {0.75: {c01: true, ph: true}, 2.25: {c01: false, ph: true}, 3.75: {c01: true, ph: false}, 8.25: {c01: true, ph: true}};
  for (const [t, want] of Object.entries(expect).map(([t, w]) => [+t, w])) {
    const F = full(t);
    for (const id of ['c01', 'ph']) {
      const shadowPx = changed(F, without[id](t)), painting = each[id].filter(d => changed(F, d(t)) > 0).length;
      const memberShown = L.filter(isPose(id)).some(l => t >= l.from && t < l.to);
      assert.equal(memberShown, want[id], `${id} artwork ${want[id] ? 'on' : 'off'} camera at ${t}s`);
      if (want[id]) { assert.ok(shadowPx > 200, `${id} casts a shadow at ${t}s (${shadowPx} px)`); assert.equal(painting, 1, `${id}: exactly one shadow at ${t}s`); }
      else assert.equal(shadowPx, 0, `${id} is off camera at ${t}s and its shadow is absent`);
    }
  }
  assert.ok(dur > 8.25);
});
