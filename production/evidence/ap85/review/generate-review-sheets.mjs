// AP-85 Track A owner review: contact sheets for scenes A1, A2, A3a, A3b and A4.
//
// TRACK A ONLY (composition engine). These sheets are NOT identity evidence for any character (that is Track B).
// The blue/green figure is a SYNTHETIC PLACEHOLDER, NOT ARTWORK, and not Character 02.
//
// How the evidence is made (nothing here changes production code, assets or other evidence):
//   1. The scene definitions are taken verbatim from the committed test file production/tests/ap85-track-a.test.mjs
//      (its "scenes" block is evaluated here), so the sheets show exactly the scenes the Track A checks ran on.
//   2. The labelled placeholder is written to a temporary folder by the test fixture (tests/fixtures/ap85-placeholder.mjs).
//   3. Each scene is compiled by the production pipeline (compileProject, allowSynthetic: true, which only tests and this
//      review script pass) into a temporary folder.
//   4. Frames are painted by the UNMODIFIED renderer (its exported loadProject + painter). No video is encoded.
//   5. Each member's outline and tag are placed from the pixels that member actually painted: the frame is painted
//      again without that member's pose layers, and the changed pixels give its box. Labels are therefore derived
//      from the render, not drawn where the scene says the member should be.
//   6. Each scene gets an annotated sheet (outlines, tags, captions) and a clean sheet (same frames, no overlays).
//
// Run (needs FFMPEG/FFPROBE, local, $0):  node production/evidence/ap85/review/generate-review-sheets.mjs
// SCENES=A2,A4 regenerates only those scenes; the manifest keeps the entries of the others. Existing sheets are never
// overwritten unless REPLACE=1 is set.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '..', '..', '..', '..');
const imp = p => import(pathToFileURL(path.join(REPO, p)).href);
const {writePlaceholder, PLACEHOLDER_CHARACTER} = await imp('production/tests/fixtures/ap85-placeholder.mjs');
const {compileProject} = await imp('production/lib/scene.mjs');
const {canvas, ensureFonts, FONT, rendererModules} = await imp('production/lib/runtime.mjs');

if (!process.env.FFPROBE) throw new Error('Set FFMPEG and FFPROBE (the renderer needs them to load a project)');
const ALL_SCENES = ['A1', 'A2', 'A3a', 'A3b', 'A4'];
const SCENE_IDS = process.env.SCENES ? process.env.SCENES.split(',') : ALL_SCENES;
for (const id of SCENE_IDS) if (!ALL_SCENES.includes(id)) throw new Error(`Unknown review scene ${id} (known: ${ALL_SCENES.join(', ')})`);
const sha = b => crypto.createHash('sha256').update(b).digest('hex');
const sheetFile = (id, kind) => path.join(HERE, `${id}-${kind}.png`);
if (process.env.REPLACE !== '1') {
  const existing = SCENE_IDS.flatMap(id => ['annotated', 'clean'].map(k => sheetFile(id, k))).filter(f => fs.existsSync(f));
  if (existing.length) throw new Error(`Refusing to overwrite existing review sheets (set REPLACE=1): ${existing.map(f => path.basename(f)).join(', ')}`);
}

// ---------------------------------------------------------------------------------------------- scene definitions
const TEST_FILE = path.join(REPO, 'production', 'tests', 'ap85-track-a.test.mjs');
const testSource = fs.readFileSync(TEST_FILE, 'utf8');
const C01 = 'character-01', PH = PLACEHOLDER_CHARACTER;
const PH_REG = writePlaceholder(fs.mkdtempSync(path.join(os.tmpdir(), 'ap85-review-placeholder-')));
function loadScenes() {
  const a = testSource.indexOf('const c01 = '), s = testSource.indexOf('const SCENES = {', a), b = testSource.indexOf('\n};\n', s);
  if (a < 0 || s < 0 || b < 0) throw new Error('Could not find the scene definitions in the Track A test file');
  return new Function('C01', 'PH', 'PH_REG', `${testSource.slice(a, b + 3)}\nreturn SCENES;`)(C01, PH, PH_REG);
}
const SCENES = loadScenes();

const PURPOSE = {
  A1: 'Two-shot. Character 01 left, placeholder right, 8 alternating lines, a pose change on every line.',
  A2: 'A1\'s lines with positions swapped and z order reversed. Styles follow the members; bubbles go on the side where the speaker stands.',
  A3a: 'Overlap: the placeholder (z 1) stands partly IN FRONT of Character 01 (z 0).',
  A3b: 'Overlap: the placeholder (z 0) stands partly BEHIND Character 01 (z 1).',
  A4: 'Shot sequence: wide, single on placeholder, single on Character 01, reaction single on Character 01, reaction single on placeholder, wide.',
};
const INSPECT = {
  A1: ['Each bubble belongs to the member tagged SPEAKING.', 'Character 01 bubbles are style "him" (left); placeholder bubbles are style "neutral" (right).', 'Every line changes the speaker\'s pose; the other member keeps its pose.'],
  A2: ['CORRECTED: each bubble now sits on the side where its speaker stands (c01 right, ph left), tail on that side.', 'Bubble styles still come from the speaker ("him" for c01, "neutral" for ph), never from the side.', 'Character 01 is on the RIGHT and in front; the placeholder is on the LEFT, behind, using its right-facing drawings (p1-r, p2-r); nothing is mirrored.'],
  A3a: ['Where the figures overlap, the placeholder is drawn over Character 01.', 'See the overlap detail panel.'],
  A3b: ['Where the figures overlap, Character 01 is drawn over the placeholder.', 'See the overlap detail panel.'],
  A4: ['CORRECTED: medium and close shots are composed: the camera pans to centre the focus member (as far as the background allows) and nobody is cut by the frame edge.',
    'Shots 2 to 5 are declared singles ("single": true): only the focus member is on camera. Shots 2 and 3 now show different members; shot 5 shows only the placeholder.',
    'Zoom levels are unchanged (medium 1.3x, close 1.5x); positions and relative scale are unchanged. An off-camera speaker\'s bubble sits on the side it stands.'],
};

// ---------------------------------------------------------------------------------------------- drawing helpers
ensureFonts();
const COL = {c01: '#ff7a00', ph: '#e000c0'};                 // outline colours, distinct from both figures' own colours
const NAME = {c01: 'CHARACTER 01', ph: 'SYNTHETIC PLACEHOLDER, NOT ARTWORK'};
const TW = 360, TH = 640, PAD = 14, CAP = 132, COLS = 4, OUT_W = 1080;
const font = (w, px) => `${w} ${px}px "${FONT.sans}"`;
const fmtStyle = s => (typeof s === 'string' ? s : `custom ${s.fill}`);

function changedBox(full, without, minChange = 30) {
  let x0 = Infinity, y0 = Infinity, x1 = -1, y1 = -1, n = 0;
  for (let i = 0; i < full.d.length; i += 4) {
    const c = Math.max(Math.abs(full.d[i] - without.d[i]), Math.abs(full.d[i + 1] - without.d[i + 1]), Math.abs(full.d[i + 2] - without.d[i + 2]));
    if (c <= minChange) continue;
    const p = i / 4, x = p % full.w, y = (p - x) / full.w;
    if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; n++;
  }
  return n ? {x0, y0, x1, y1, n} : null;
}
const grab = (draw, t) => { const f = draw(t), c = canvas.createCanvas(f.width, f.height); c.getContext('2d').drawImage(f, 0, 0); return c; };
const px = c => ({w: c.width, h: c.height, d: c.getContext('2d').getImageData(0, 0, c.width, c.height).data});

function tag(ctx, text, x, y, colour, filled) {
  ctx.font = font(700, 12); const w = ctx.measureText(text).width + 10, h = 18;
  x = Math.max(2, Math.min(x, TW - w - 2)); y = Math.max(2, Math.min(y, TH - h - 2));
  ctx.fillStyle = filled ? colour : 'rgba(0,0,0,0.78)'; ctx.fillRect(x, y, w, h);
  ctx.strokeStyle = colour; ctx.lineWidth = 2; ctx.strokeRect(x, y, w, h);
  ctx.fillStyle = '#ffffff'; ctx.textBaseline = 'middle'; ctx.fillText(text, x + 5, y + h / 2 + 1);
  return h;
}

// ---------------------------------------------------------------------------------------------- per scene
const {core, render} = await rendererModules();
const commit = execFileSync('git', ['rev-parse', 'HEAD'], {cwd: REPO, encoding: 'utf8'}).trim();
// The engine and scene sources the sheets were made from, by hash (the working tree may hold changes not yet committed).
const SOURCES = ['production/lib/formats/face-to-face.mjs', 'production/lib/cast.mjs', 'production/tests/ap85-track-a.test.mjs', 'production/evidence/ap85/review/generate-review-sheets.mjs'];
const sources = Object.fromEntries(SOURCES.map(f => [f, sha(fs.readFileSync(path.join(REPO, f)))]));
const dirty = execFileSync('git', ['status', '--porcelain', '--', ...SOURCES], {cwd: REPO, encoding: 'utf8'}).trim() !== '';
const MANIFEST = path.join(HERE, 'manifest.json'), previous = fs.existsSync(MANIFEST) ? JSON.parse(fs.readFileSync(MANIFEST, 'utf8')) : null;
const manifest = {
  schema: 'oddly-relatable/ap85-track-a-review@1', track: 'A (composition architecture only; not identity evidence)',
  placeholder: 'SYNTHETIC PLACEHOLDER, NOT ARTWORK. Test fixture only; not Character 02.',
  ownerAcceptance: 'NOT GIVEN. These sheets are for the owner review; nothing here records acceptance.',
  generator: {file: 'production/evidence/ap85/review/generate-review-sheets.mjs'},
  scenes: {...(previous?.scenes || {})},
};

for (const id of SCENE_IDS) {
  const story = SCENES[id](), scene = story.scenes[0], cast = [...scene.cast].sort((a, b) => a.z - b.z);
  const outDir = fs.mkdtempSync(path.join(os.tmpdir(), `ap85-review-${id}-`));
  const built = await compileProject(story, {outDir: path.join(outDir, 'out'), allowSynthetic: true});
  const report = built.report, project = JSON.parse(fs.readFileSync(built.projectFile, 'utf8'));
  const lines = report.scenes[0].lines, segs = report.character, shots = report.camera[0].shots;
  const scale = OUT_W / project.width;
  if (scale !== 1) throw new Error('expected 1080-wide output');

  // Painters: full frame, and the frame without each member's pose layers (to find what each member painted).
  const full = await render.painter(core.loadProject(built.projectFile)), without = {};
  for (const m of cast) {
    const p = structuredClone(project);
    p.shots[0].layers = p.shots[0].layers.filter(l => !l.path.includes(`/${m.character}-pose-`));
    const f = path.join(path.dirname(built.projectFile), `without-${m.id}.json`); fs.writeFileSync(f, JSON.stringify(p));   // beside project.json: media paths are relative
    without[m.id] = await render.painter(core.loadProject(f));
  }

  // One panel per line, sampled once its bubble has settled (60% through the line).
  const panels = lines.map((l, i) => ({line: l, index: i, t: +(l.start + 0.6 * (l.end - l.start)).toFixed(3)}));
  const rendered = panels.map(pn => {
    const frame = grab(full, pn.t), f = px(frame), boxes = {};
    for (const m of cast) boxes[m.id] = changedBox(f, px(grab(without[m.id], pn.t)));
    return {...pn, frame, boxes};
  });
  // Overlap scenes: add a detail panel cropped around where both members' boxes intersect.
  let detail = null;
  if (id.startsWith('A3')) {
    const r = rendered[0], [a, b] = cast.map(m => r.boxes[m.id]);
    const ix0 = Math.max(a.x0, b.x0), ix1 = Math.min(a.x1, b.x1), iy0 = Math.max(a.y0, b.y0), iy1 = Math.min(a.y1, b.y1);
    if (ix1 <= ix0 || iy1 <= iy0) throw new Error(`${id}: members do not overlap`);
    const cx = (ix0 + ix1) / 2, cy = (iy0 + iy1) / 2, w = Math.min(OUT_W, Math.max(ix1 - ix0 + 160, 400)), h = w * TH / TW;
    detail = {t: r.t, x: Math.max(0, Math.min(OUT_W - w, cx - w / 2)), y: Math.max(0, Math.min(r.frame.height - h, cy - h / 2)), w, h, frame: r.frame};
  }

  const nPanels = rendered.length + (detail ? 1 : 0), rows = Math.ceil(nPanels / COLS);
  const headerLines = 6 + cast.length + INSPECT[id].length + 1;
  const HEAD = 24 + headerLines * 20 + 10;
  const W = PAD + COLS * (TW + PAD), H = HEAD + rows * (TH + CAP + PAD) + PAD;

  for (const kind of ['annotated', 'clean']) {
    const sheet = canvas.createCanvas(W, H), ctx = sheet.getContext('2d');
    ctx.fillStyle = '#1d2433'; ctx.fillRect(0, 0, W, H); ctx.textBaseline = 'top';
    // Header.
    let y = 16; const say = (text, w = 400, px2 = 14, colour = '#dfe5f0') => { ctx.font = font(w, px2); ctx.fillStyle = colour; ctx.fillText(text, PAD, y); y += 20; };
    say(`AP-85 Track A owner review · ${id} · ${kind === 'annotated' ? 'ANNOTATED (outlines and tags drawn by the review script)' : 'CLEAN (renderer frames, no overlays)'}`, 700, 17, '#ffffff');
    say(PURPOSE[id], 600, 14);
    say('TRACK A ONLY: composition engine evidence, not character identity evidence (Track B). The blue/green figure is a SYNTHETIC PLACEHOLDER, NOT ARTWORK, not Character 02.', 700, 13, '#ffd34d');
    say(`Cast (back to front):`, 700, 13);
    for (const m of cast) say(`  ${m.id} · ${m.character}${m.character === PH ? ' (SYNTHETIC PLACEHOLDER, NOT ARTWORK)' : ' (approved Character 01 poses, unchanged)'} · feet (${m.placement.feetX}, ${m.placement.feetY}) · height ${m.placement.figureHeight} · z ${m.z} · facing ${m.facing ?? 'native'} · speech style ${fmtStyle(m.speech.style)}${m.speech.side ? ` · declared side ${m.speech.side}` : ' · bubble side from screen position'}`, 400, 13);
    say(`Shot sequence: ${shots.map((s, i) => `${i + 1} ${s.note ?? s.camera ?? ''}${s.focus ? ` on ${s.focus}` : ' (no focus)'}${s.single ? ' single' : ''}`).join('  |  ')}`, 400, 13);
    say('Owner: inspect', 700, 13);
    for (const t of INSPECT[id]) say(`  • ${t}`, 400, 13);
    say(`Base commit ${commit.slice(0, 12)}${dirty ? ' + engine changes (hashes in manifest.json)' : ''} · scenes from production/tests/ap85-track-a.test.mjs · renderer frames at 1080×1920 shown at 1/3 · outline boxes come from each member's painted pixels`, 400, 12, '#9aa6bd');

    const place = k => ({x: PAD + (k % COLS) * (TW + PAD), y: HEAD + Math.floor(k / COLS) * (TH + CAP + PAD)});
    for (const [k, r] of rendered.entries()) {
      const {x, y: py} = place(k);
      ctx.save(); ctx.translate(x, py);
      ctx.drawImage(r.frame, 0, 0, TW, TH);
      const shot = shots.find(s => r.t >= s.start && r.t < s.end) ?? shots.at(-1);
      if (kind === 'annotated') {
        const s = TW / OUT_W;
        for (const m of cast) {
          const b = r.boxes[m.id]; if (!b) continue;
          ctx.strokeStyle = COL[m.id] ?? '#ffffff'; ctx.lineWidth = 2; ctx.setLineDash([6, 4]);
          ctx.strokeRect(b.x0 * s, b.y0 * s, (b.x1 - b.x0) * s, (b.y1 - b.y0) * s); ctx.setLineDash([]);
          // One fixed tag row per member at the bottom of the frame (back member on the upper row), so tags never cover
          // each other or the bubbles. Each tag starts at its member's outline and shares its colour; the speaker's is filled.
          const row = cast.length - cast.indexOf(m), speaking = r.line.speaker === m.id;
          tag(ctx, `${m.id} · ${NAME[m.id] ?? m.character}${speaking ? ' · SPEAKING' : ''}`, b.x0 * s, TH - row * 21 - 2, COL[m.id] ?? '#ffffff', speaking);
        }
      }
      // Caption.
      const cy = TH + 6, pose = m => segs.find(sg => sg.cast === m.id && r.t >= sg.from && r.t < sg.to);
      const cap = [
        [`Line ${r.index + 1}/${lines.length} · t = ${r.t.toFixed(2)} s`, 700, '#ffffff'],
        [`Speaker: ${r.line.speaker}${r.line.speakerOnScreen === false ? ' (off camera)' : ''} · bubble "${fmtStyle(r.line.style)}", ${r.line.side}`, 600, COL[r.line.speaker] ?? '#ffffff'],
        [`"${scene.lines[r.index].text}"`, 400, '#dfe5f0'],
        [`Shot ${shots.indexOf(shot) + 1}: ${shot.note ?? r.line.shot.camera}${shot.single ? ' single' : ''} · ${shot.focus ? `focus ${shot.focus}` : 'no focus (all)'} · zoom ${shot.zoom}`, 400, '#dfe5f0'],
        [`Poses: ${cast.map(m => { const p = pose(m); return p ? `${m.id} ${p.requestedPose}${p.pose !== p.requestedPose ? ` (drawn as ${p.pose})` : ''}` : `${m.id} –`; }).join(' · ')}`, 400, '#dfe5f0'],
        [`Back to front: ${cast.map(m => m.id).join(', ')}${cast.filter(m => !r.boxes[m.id]).map(m => ` · ${m.id} ${shot.hidden?.includes(m.id) ? 'off camera (single)' : 'not in frame'}`).join('')}`, 400, '#dfe5f0'],
      ];
      cap.forEach(([text, w, c], i) => { ctx.font = font(w, 12.5); ctx.fillStyle = c; ctx.fillText(text, 0, cy + i * 20, TW); });
      ctx.restore();
    }
    if (detail) {
      const {x, y: py} = place(rendered.length);
      ctx.drawImage(detail.frame, detail.x, detail.y, detail.w, detail.h, x, py, TW, TH);
      const front = cast.at(-1);
      ctx.font = font(700, 12.5); ctx.fillStyle = '#ffffff';
      ctx.fillText(`Overlap detail · t = ${detail.t.toFixed(2)} s · ${(OUT_W / detail.w * TW / OUT_W * 3).toFixed(2)}× of the panels`, x, py + TH + 6, TW);
      ctx.font = font(600, 12.5); ctx.fillStyle = COL[front.id];
      ctx.fillText(`Front member (z ${front.z}): ${front.id} · it should be drawn over the other`, x, py + TH + 26, TW);
      ctx.font = font(400, 12.5); ctx.fillStyle = '#dfe5f0';
      ctx.fillText('Crop of the clean renderer frame (no overlays).', x, py + TH + 46, TW);
    }
    fs.writeFileSync(sheetFile(id, kind), sheet.toBuffer('image/png'));
  }
  manifest.scenes[id] = {
    generatedFrom: {baseCommit: commit, uncommittedEngineChanges: dirty, sources},
    purpose: PURPOSE[id], times: rendered.map(r => r.t),
    projectSha256: sha(fs.readFileSync(built.projectFile)), layoutIssues: report.checks?.issues ?? null,
    sheets: Object.fromEntries(['annotated', 'clean'].map(k => [path.basename(sheetFile(id, k)), sha(fs.readFileSync(sheetFile(id, k)))])),
    memberBoxesPx: rendered.map(r => ({t: r.t, ...Object.fromEntries(Object.entries(r.boxes).map(([m, b]) => [m, b && [b.x0, b.y0, b.x1, b.y1]]))})),
  };
  console.log(`${id}: ${rendered.length} frames${detail ? ' + overlap detail' : ''}`);
}
// Entries carried over from an earlier manifest keep their own provenance; older entries recorded it at the top level.
for (const [id, e] of Object.entries(manifest.scenes)) if (!e.generatedFrom && previous?.generatedFromCommit) e.generatedFrom = {commit: previous.generatedFromCommit, sceneDefinitions: previous.sceneDefinitions, generator: previous.generator};
manifest.scenes = Object.fromEntries(ALL_SCENES.filter(id => manifest.scenes[id]).map(id => [id, manifest.scenes[id]]));
fs.writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2) + '\n');
console.log('written', path.relative(REPO, HERE));
