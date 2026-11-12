#!/usr/bin/env node
// Oddly Relatable Studio: local dashboard for the production engine.
//   node studio/server.mjs            (or: npm --prefix studio start)
// Environment: FFMPEG and FFPROBE (needed by the production engine), optional STUDIO_PORT (default 4317) and
// STUDIO_WORKSPACE (default studio-work/studio). The server binds to 127.0.0.1 only.
import path from 'node:path';
import {REPO_ROOT} from '../production/lib/runtime.mjs';
import {createStudio} from './lib/app.mjs';

const port = Number(process.env.STUDIO_PORT || 4317);
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('STUDIO_PORT must be an integer between 1024 and 65535');
const workspace = path.resolve(REPO_ROOT, process.env.STUDIO_WORKSPACE || 'studio-work/studio');

const studio = createStudio({workspace, port});
const recovered = await studio.listen('127.0.0.1');
console.log(`Oddly Relatable Studio: http://127.0.0.1:${port}/`);
console.log(`Workspace: ${path.relative(REPO_ROOT, workspace) || '.'}`);
if (!process.env.FFMPEG || !process.env.FFPROBE) console.log('Warning: FFMPEG/FFPROBE are not set; production runs will fail until they are.');
if (recovered.watching.length || recovered.adopted.length || recovered.interrupted.length || recovered.queued)
  console.log(`Recovered runs: ${JSON.stringify(recovered)}`);

const shutdown = async () => { console.log('Stopping (running productions continue and are reconciled on the next start)'); await studio.close(); process.exit(0); };
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
