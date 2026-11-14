#!/usr/bin/env node
// Oddly Relatable Studio: local dashboard for the production engine.
//   node studio/server.mjs            (or: npm --prefix studio start)
// Environment: FFMPEG and FFPROBE (needed by the production engine), optional STUDIO_PORT (default 4317),
// STUDIO_WORKSPACE (default studio-work/studio), STUDIO_GEN_ADAPTER (none | fake | import) and, for the import adapter,
// STUDIO_GEN_IMPORT_DIR (an AP-84B3 run folder outside the repository). The server binds to 127.0.0.1 only.
import path from 'node:path';
import {REPO_ROOT} from '../production/lib/runtime.mjs';
import {createStudio} from './lib/app.mjs';

const port = Number(process.env.STUDIO_PORT || 4317);
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('STUDIO_PORT must be an integer between 1024 and 65535');
const workspace = path.resolve(REPO_ROOT, process.env.STUDIO_WORKSPACE || 'studio-work/studio');

// Generation adapter (AP-84B1): 'none' (default, nothing is generated), 'fake' (labelled synthetic test fixtures) or
// 'import' (AP-84B3 D1-6: imports transfer-verified candidates from STUDIO_GEN_IMPORT_DIR; it generates nothing).
const genAdapter = process.env.STUDIO_GEN_ADAPTER || 'none';
if (!['none', 'fake', 'import'].includes(genAdapter)) throw new Error('STUDIO_GEN_ADAPTER must be none, fake or import');
if (genAdapter === 'import') {
  const dir = process.env.STUDIO_GEN_IMPORT_DIR;
  if (!dir || !path.isAbsolute(dir)) throw new Error('STUDIO_GEN_IMPORT_DIR must be an absolute path to an AP-84B3 run folder when STUDIO_GEN_ADAPTER=import');
  const rel = path.relative(REPO_ROOT, path.resolve(dir));
  if (rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel))) throw new Error('STUDIO_GEN_IMPORT_DIR must be outside the repository');
}
const studio = createStudio({workspace, port, genAdapter});
const recovered = await studio.listen('127.0.0.1');
console.log(`Oddly Relatable Studio: http://127.0.0.1:${port}/`);
console.log(`Workspace: ${path.relative(REPO_ROOT, workspace) || '.'}`);
console.log(`Generation adapter: ${genAdapter}${genAdapter === 'none' ? ' (no generation worker configured)' : ''}`);
if (!process.env.FFMPEG || !process.env.FFPROBE) console.log('Warning: FFMPEG/FFPROBE are not set; production runs will fail until they are.');
if (recovered.watching.length || recovered.adopted.length || recovered.interrupted.length || recovered.queued || recovered.generation.interrupted.length || recovered.generation.queued)
  console.log(`Recovered runs: ${JSON.stringify(recovered)}`);

const shutdown = async () => { console.log('Stopping (running productions continue and are reconciled on the next start)'); await studio.close(); process.exit(0); };
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
