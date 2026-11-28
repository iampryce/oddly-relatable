// usage: node shoot.mjs <page.html> <out.png> [w] [h]   -- serves web/, waits for window.ready, saves the #c canvas as PNG
import { chromium } from 'playwright'; import http from 'http'; import fs from 'fs'; import path from 'path';
const [,, page, out, w = '1920', h = '1080'] = process.argv;
const root = path.resolve('web');
const types = { js: 'text/javascript', html: 'text/html', png: 'image/png', json: 'application/json' };
const srv = http.createServer((q, s) => { const p = path.join(root, decodeURIComponent(q.url.split('?')[0])); if (!fs.existsSync(p)) { s.writeHead(404); return s.end(); } s.writeHead(200, { 'Content-Type': types[p.split('.').pop()] || 'application/octet-stream' }); fs.createReadStream(p).pipe(s); }).listen(0);
await new Promise(r => srv.on('listening', r));
const b = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const pg = await b.newPage({ viewport: { width: +w, height: +h } });
pg.on('console', m => console.log('PAGE', m.text())); pg.on('pageerror', e => console.log('ERR', e.message));
await pg.goto(`http://localhost:${srv.address().port}/${page}`);
await pg.waitForFunction(() => window.ready || window.err, null, { timeout: 120000 });
const d = await pg.evaluate(() => document.getElementById('c').toDataURL('image/png'));
fs.writeFileSync(out, Buffer.from(d.split(',')[1], 'base64')); console.log('saved', out);
await b.close(); srv.close();
