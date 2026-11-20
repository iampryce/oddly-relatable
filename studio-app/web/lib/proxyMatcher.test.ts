// The dashboard proxy (middleware) must never run on /api: Next.js would then buffer request bodies and pass on only
// the first 10 MB, silently cutting audio and video uploads. The media upload also goes straight from Caddy to the API.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

// read the matcher from proxy.ts itself (importing it would load Next.js)
const src = readFileSync(new URL('../proxy.ts', import.meta.url), 'utf8');
const matcher: string[] = JSON.parse(src.match(/matcher:\s*(\[[^\]]*\])/)![1].replace(/'/g, '"'));
const runs = (path: string) => matcher.some(m => new RegExp(`^${m}$`).test(path));

test('the proxy never runs on API routes, uploads included', () => {
  for (const p of ['/api/episodes/5/audio', '/api/episodes/5/audio/trim', '/api/ideas', '/api/health']) assert.equal(runs(p), false, p);
});

test('the proxy still protects dashboard pages', () => {
  for (const p of ['/', '/episodes/5', '/characters', '/settings']) assert.equal(runs(p), true, p);
  assert.equal(runs('/login'), false);
});
