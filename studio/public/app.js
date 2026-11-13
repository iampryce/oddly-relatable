// Oddly Relatable Studio dashboard (no framework, no build step). All data is inserted as text nodes, never as HTML.
const view = document.getElementById('view');
let timer = null;   // polling timer for the current page

// ---------- tiny DOM helper: h('tag.class', {attrs}, ...children) ; strings become text nodes
function h(spec, attrs = {}, ...kids) {
  const [tag, ...classes] = spec.split('.');
  const el = document.createElement(tag || 'div');
  if (classes.length) el.className = classes.join(' ');
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v); else el.setAttribute(k, v === true ? '' : String(v));
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
  return el;
}
const pill = (status, text = status) => h(`span.pill.s-${String(status).replace(/[^a-z0-9-]/gi, '')}`, {}, text.replace(/-/g, ' '));
const fmtDate = s => s ? new Date(s).toLocaleString() : '—';
const fmtBytes = n => n == null ? '—' : n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : n > 1e3 ? `${(n / 1e3).toFixed(1)} kB` : `${n} B`;
const fmtSec = s => s == null ? '—' : `${Number(s).toFixed(s < 10 ? 1 : 0)} s`;
const mediaUrl = (runId, key) => `/media/runs/${encodeURIComponent(runId)}/${key.split('/').map(encodeURIComponent).join('/')}`;

async function api(path, options = {}) {
  const res = await fetch(path, {...options, headers: {'Content-Type': 'application/json', ...(options.headers || {})}});
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(body.error || `HTTP ${res.status}`), {status: res.status, body});
  return body;
}
function toast(msg, bad = false) {
  const t = h(`div.toast${bad ? '.notice.error' : ''}`, {role: 'status'}, msg);
  document.body.append(t); setTimeout(() => t.remove(), 4000);
}
function render(...nodes) { view.replaceChildren(...nodes.filter(n => n !== null && n !== undefined && n !== false)); }
function card(title, ...kids) { return h('section.card', {}, title ? h('h2', {}, title) : null, ...kids); }

// ---------- pages
async function overview() {
  const o = await api('/api/overview');
  const tile = (n, label) => h('div.card.tile', {}, h('div.num', {}, n), h('div.label', {}, label));
  render(
    h('div.head', {}, h('div', {}, h('h1', {}, 'Overview'), h('div.muted', {}, 'Episodes, production runs and reviews')),
      h('div.row', {}, h('a.button', {href: '#/episodes/new'}, 'New episode'), h('a.button', {href: '#/episodes'}, 'Open library'))),
    h('div.grid.tiles', {}, tile(o.episodes, 'Episodes'), tile(o.runs, 'Production runs'), tile(o.produced, 'Produced'), tile(o.failed, 'Failed / QA-failed'),
      tile(o.active, 'Queued / running'), tile(o.awaitingReview, 'Awaiting review')),
    h('div.grid.two', {},
      card('Recent runs', runsTable(o.recentRuns)),
      card('Recent activity', o.events.length ? h('ul.feed', {}, o.events.map(e => h('li', {}, h('div', {}, e.message), h('div.muted', {}, fmtDate(e.at))))) : h('div.empty', {}, 'No activity yet'))));
  if (o.active) poll(overview, 3000);
}

function runsTable(runs, {showEpisode = true} = {}) {
  if (!runs.length) return h('div.empty', {}, 'No production runs yet');
  return h('div.table-wrap', {}, h('table', {},
    h('thead', {}, h('tr', {}, h('th', {}, 'Run'), showEpisode ? h('th', {}, 'Episode') : null, h('th', {}, 'Status'), h('th', {}, 'Review'), h('th', {}, 'Started'), h('th', {}, 'Duration'))),
    h('tbody', {}, runs.map(r => h('tr', {},
      h('td.mono', {}, h('a', {href: `#/runs/${r.id}`}, r.id)), showEpisode ? h('td', {}, h('a', {href: `#/episodes/${r.episodeId}`}, r.episodeId)) : null,
      h('td', {}, pill(r.status)), h('td', {}, pill(r.review?.state || 'pending-run')), h('td', {}, fmtDate(r.startedAt || r.createdAt)), h('td', {}, fmtSec(r.summary?.seconds)))))));
}

async function episodes() {
  const list = await api('/api/episodes');
  render(
    h('div.head', {}, h('div', {}, h('h1', {}, 'Episode library'), h('div.muted', {}, 'Episode records point at approved story files in production/stories/ (stories are never edited here)')),
      h('a.button', {href: '#/episodes/new'}, 'New episode')),
    card(null, list.length ? h('div.table-wrap', {}, h('table', {},
      h('thead', {}, h('tr', {}, h('th', {}, 'Title'), h('th', {}, 'ID'), h('th', {}, 'Story'), h('th', {}, 'Duration'), h('th', {}, 'Latest run'), h('th', {}, 'Review'), h('th', {}, ''))),
      h('tbody', {}, list.map(e => h('tr', {},
        h('td', {}, h('a', {href: `#/episodes/${e.id}`}, e.title)), h('td.mono', {}, e.id), h('td.mono', {}, e.storyFile, e.storyChanged ? h('span.pill.s-warn', {}, 'story changed') : null),
        h('td', {}, fmtSec(e.duration)), h('td', {}, e.latestRun ? pill(e.latestRun.status) : h('span.muted', {}, 'never produced')),
        h('td', {}, e.latestRun ? pill(e.latestRun.review.state) : '—'), h('td', {}, h('a', {href: `#/episodes/${e.id}`}, 'Open'))))))) : h('div.empty', {}, 'No episodes yet')));
}

async function newEpisode() {
  const stories = await api('/api/stories');
  const valid = stories.filter(s => s.valid);
  const sel = h('select', {id: 'story'}, valid.map(s => h('option', {value: s.file}, `${s.title} — ${s.file} (${fmtSec(s.duration)})`)));
  const id = h('input', {id: 'eid', placeholder: 'defaults to the story id', maxlength: 64});
  const title = h('input', {id: 'etitle', placeholder: 'defaults to the story title', maxlength: 120});
  const note = h('textarea', {id: 'enote', maxlength: 500, placeholder: 'optional'});
  const submit = h('button.primary', {type: 'submit'}, 'Create episode');
  const form = h('form', {onsubmit: async ev => {
    ev.preventDefault(); submit.disabled = true;
    try {
      const body = {storyFile: sel.value}; if (id.value.trim()) body.id = id.value.trim(); if (title.value.trim()) body.title = title.value.trim(); if (note.value.trim()) body.note = note.value.trim();
      const e = await api('/api/episodes', {method: 'POST', body: JSON.stringify(body)});
      location.hash = `#/episodes/${e.id}`;
    } catch (e) { toast(e.message, true); submit.disabled = false; }
  }}, h('label', {for: 'story'}, 'Story'), sel, h('label', {for: 'eid'}, 'Episode ID'), id, h('label', {for: 'etitle'}, 'Title'), title,
    h('label', {for: 'enote'}, 'Note'), note, h('div.row', {}, submit, h('a.button', {href: '#/episodes'}, 'Cancel')));
  render(h('div.head', {}, h('h1', {}, 'New episode')),
    h('div.grid.two', {}, card('Create from an existing story', valid.length ? form : h('div.empty', {}, 'No valid stories in production/stories/')),
      card('Stories', h('ul.feed', {}, stories.map(s => h('li', {}, h('div', {}, h('b', {}, s.title || s.file), ' ', s.valid ? pill('pass', 'valid') : pill('fail', 'invalid')),
        h('div.muted.mono', {}, s.file), s.valid ? h('div.muted', {}, `${fmtSec(s.duration)} · ${s.size} @ ${s.fps} fps · ${s.formats.join(', ')} · ${s.cast.join(', ')}`) : h('div.notice.error', {}, s.error)))))));
}

async function episodeDetail(id) {
  const e = await api(`/api/episodes/${encodeURIComponent(id)}`);
  const active = e.history.find(r => ['queued', 'running'].includes(r.status));
  const start = h('button.primary', {type: 'button', disabled: !!active || !e.story.valid, onclick: async () => {
    start.disabled = true;
    try { const r = await api(`/api/episodes/${encodeURIComponent(id)}/runs`, {method: 'POST', body: '{}'}); toast(`Run ${r.id} queued`); location.hash = `#/runs/${r.id}`; }
    catch (err) { toast(err.message, true); start.disabled = false; }
  }}, active ? 'Production running…' : 'Start production run');
  const s = e.story;
  render(
    h('div.head', {}, h('div', {}, h('h1', {}, e.title), h('div.muted.mono', {}, e.id)), h('div.row', {}, start)),
    e.storyChanged ? h('div.notice', {}, 'The story file has changed since this episode record was created; runs record the hash they used.') : null,
    !s.valid ? h('div.notice.error', {}, `Story cannot be produced: ${s.error}`) : null,
    h('div.grid.two', {},
      card('Production history', runsTable(e.history, {showEpisode: false})),
      card('Episode', h('dl.kv', {}, h('dt', {}, 'Story file'), h('dd.mono', {}, e.storyFile), h('dt', {}, 'Story SHA-256'), h('dd.mono', {}, e.storySha256.slice(0, 16) + '…'),
        h('dt', {}, 'Duration'), h('dd', {}, fmtSec(s.duration)), h('dt', {}, 'Format'), h('dd', {}, s.valid ? `${s.size} @ ${s.fps} fps` : '—'),
        h('dt', {}, 'Scenes'), h('dd', {}, s.valid ? `${s.scenes} (${s.formats.join(', ')})` : '—'), h('dt', {}, 'Cast'), h('dd', {}, s.valid ? s.cast.join(', ') : '—'),
        h('dt', {}, 'Created'), h('dd', {}, fmtDate(e.createdAt)), h('dt', {}, 'Note'), h('dd', {}, e.note || '—')))),
    h('div.grid', {}, card('Review history', e.reviews.length ? h('ul.feed', {}, e.reviews.map(r => h('li', {}, pill(r.decision), ' ', h('a.mono', {href: `#/runs/${r.runId}`}, r.runId), h('div', {}, r.note), h('div.muted', {}, `${r.reviewer} · ${fmtDate(r.createdAt)}`)))) : h('div.empty', {}, 'No reviews yet'))));
  if (active) poll(() => episodeDetail(id), 3000);
}

async function runsPage() {
  const runs = await api('/api/runs');
  render(h('div.head', {}, h('div', {}, h('h1', {}, 'Production runs'), h('div.muted', {}, 'All runs, newest first'))), card(null, runsTable(runs)));
  if (runs.some(r => ['queued', 'running'].includes(r.status))) poll(runsPage, 3000);
}

const STAGES = ['environment', 'compile', 'audio', 'storyboard', 'render', 'audio-export', 'qa'];
let logState = {runId: null, offset: 0, text: ''};

async function runDetail(id) {
  const r = await api(`/api/runs/${encodeURIComponent(id)}`);
  if (logState.runId !== id) logState = {runId: id, offset: 0, text: ''};
  const log = await api(`/api/runs/${encodeURIComponent(id)}/log?offset=${logState.offset}`);
  logState.text = (logState.text + log.text).slice(-200000); logState.offset = log.nextOffset;
  const active = ['queued', 'running'].includes(r.status);
  const art = Object.fromEntries(r.artifacts.map(a => [a.key, a]));
  const mp4 = r.artifacts.find(a => a.key.startsWith('render/') && a.key.endsWith('.mp4'));
  const frames = r.artifacts.filter(a => a.key.startsWith('storyboard/frames/'));
  const done = new Map(r.stages.map(s => [s.stage, s]));
  const stageList = h('ul.stages', {}, STAGES.map(name => { const s = done.get(name); return h('li', {}, h('span', {}, name), s ? h('span', {}, pill(s.status), s.seconds != null ? ` ${fmtSec(s.seconds)}` : '') : h('span.muted', {}, '—')); }));
  const cancel = active ? h('button.danger', {type: 'button', onclick: async () => { try { await api(`/api/runs/${id}/cancel`, {method: 'POST', body: '{}'}); toast('Cancelling…'); } catch (e) { toast(e.message, true); } }}, 'Cancel run') : null;
  const logBox = h('pre.log.mono', {}, logState.text || '(no output yet)');

  const sections = [
    h('div.head', {}, h('div', {}, h('h1', {}, 'Production run ', h('span.mono', {}, r.id)), h('div.muted', {}, 'Episode ', h('a', {href: `#/episodes/${r.episodeId}`}, r.episodeId), ` · story ${r.storyFile}`)),
      h('div.row', {}, pill(r.status), pill(r.review.state), cancel)),
    r.error ? h('div.notice.error', {}, r.error) : null,
    r.summary?.awaiting ? h('div.notice', {}, r.summary.awaiting) : null,
    h('div.grid.run-grid', {},
      h('div.grid', {},
        card('Stages', stageList),
        card('Run', h('dl.kv', {}, h('dt', {}, 'Created'), h('dd', {}, fmtDate(r.createdAt)), h('dt', {}, 'Started'), h('dd', {}, fmtDate(r.startedAt)), h('dt', {}, 'Finished'), h('dd', {}, fmtDate(r.finishedAt)),
          h('dt', {}, 'Total time'), h('dd', {}, fmtSec(r.summary?.seconds)), h('dt', {}, 'Exit code'), h('dd', {}, r.exitCode ?? '—'),
          h('dt', {}, 'Render'), h('dd', {}, r.summary?.render ? `${r.summary.render.frames} frames · decode ${r.summary.render.rendererDecode}` : '—'),
          h('dt', {}, 'Audio'), h('dd', {}, r.summary?.audio ? `bed: ${r.summary.audio.bed} · SFX cues ${r.summary.audio.sfxCues} · voice clips ${r.summary.audio.voiceClips} · music ${r.summary.audio.music ? 'yes' : 'no'}` : '—'),
          h('dt', {}, 'Story SHA-256'), h('dd.mono', {}, r.storySha256.slice(0, 16) + '…'))),
        reviewCard(r)),
      h('div.grid', {},
        mp4 ? card('Rendered video', h('video', {controls: true, preload: 'metadata', src: mediaUrl(id, mp4.key)}), h('div.muted', {}, `${mp4.key} · ${fmtBytes(mp4.bytes)}`)) : (active ? card('Rendered video', h('div.empty', {}, 'Rendering… the video appears here when the run finishes')) : null),
        r.qa ? qaCard(r.qa) : null,
        art['storyboard/storyboard-sheet.png'] ? card('Storyboard', h('a', {href: mediaUrl(id, 'storyboard/storyboard-sheet.png'), target: '_blank', rel: 'noopener'}, h('img.storyboard', {src: mediaUrl(id, 'storyboard/storyboard-sheet.png'), alt: 'Storyboard sheet'})),
          frames.length ? h('div', {}, h('h3', {}, `Frames (${frames.length})`), h('div.frames', {}, frames.map(f => h('a', {href: mediaUrl(id, f.key), target: '_blank', rel: 'noopener'}, h('img', {src: mediaUrl(id, f.key), alt: f.key, loading: 'lazy'}))))) : null) : null,
        card('Production log', logBox),
        r.artifacts.length ? card('Output files', h('div.table-wrap', {}, h('table', {}, h('tbody', {}, r.artifacts.filter(a => !a.key.startsWith('storyboard/frames/')).map(a => h('tr', {}, h('td.mono', {}, h('a', {href: mediaUrl(id, a.key), target: '_blank', rel: 'noopener'}, a.key)), h('td', {}, fmtBytes(a.bytes)))))))) : null,
        art['production-manifest.json'] ? await manifestCard(id) : null,
        art['reports/layout-report.json'] ? await layoutCard(id) : null)),
  ];
  render(...sections.filter(Boolean));
  logBox.scrollTop = logBox.scrollHeight;
  if (active) poll(() => runDetail(id), 2000);
}

function qaCard(qa) {
  return card('QA report', h('div.row', {}, pill(qa.status, `QA ${qa.status}`), h('span.muted', {}, `${qa.failed} failed · ${qa.warnings} warnings`)),
    h('div.notice', {}, qa.note || 'Technical QA only.'),
    h('div.table-wrap', {}, h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, 'Check'), h('th', {}, 'Result'), h('th', {}, 'Detail'))),
      h('tbody', {}, qa.checks.map(c => h('tr', {}, h('td.mono', {}, c.id), h('td', {}, pill(c.status)), h('td', {}, c.detail, c.fix && c.status !== 'pass' ? h('div.muted', {}, `Fix: ${c.fix}`) : null)))))));
}
async function manifestCard(id) {
  const m = await fetch(mediaUrl(id, 'production-manifest.json')).then(r => r.json()).catch(() => null);
  if (!m) return null;
  const row = (k, v) => [h('dt', {}, k), h('dd.mono', {}, v)];
  return card('Production manifest', h('dl.kv', {}, row('Status', m.status), row('Toolkit', `${m.version}`), row('Git HEAD', m.git?.head ? m.git.head.slice(0, 12) : '—'), row('Node', m.node), row('Story', `${m.inputs.story.path} · ${m.inputs.story.sha256.slice(0, 12)}…`),
    row('Artwork inputs', String(m.inputs.artwork.length)), row('Audio inputs', String(m.inputs.audio.length))),
    h('div.table-wrap', {}, h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, 'Output'), h('th', {}, 'Size'), h('th', {}, 'SHA-256'))),
      h('tbody', {}, m.outputs.map(o => h('tr', {}, h('td.mono', {}, o.path), h('td', {}, fmtBytes(o.bytes)), h('td.mono', {}, o.sha256.slice(0, 16) + '…')))))));
}
async function layoutCard(id) {
  const l = await fetch(mediaUrl(id, 'reports/layout-report.json')).then(r => r.json()).catch(() => null);
  if (!l) return null;
  return card('Layout report', h('dl.kv', {}, h('dt', {}, 'Duration'), h('dd', {}, fmtSec(l.duration)), h('dt', {}, 'Messages'), h('dd', {}, String(l.messages?.length ?? 0)),
    h('dt', {}, 'Typing'), h('dd', {}, String(l.typing?.length ?? 0)), h('dt', {}, 'Camera'), h('dd', {}, (l.camera || []).map(c => `${c.cuts.length} cuts, ${c.moves.length} moves`).join('; ') || '—'),
    h('dt', {}, 'Layout'), h('dd', {}, pill(l.checks.ok ? 'pass' : 'fail', l.checks.ok ? 'no issues' : `${l.checks.issues.length} issues`))),
    l.checks.warnings.length ? h('ul.feed', {}, l.checks.warnings.map(w => h('li', {}, pill('warn'), ' ', w))) : null);
}

function reviewCard(r) {
  const reviewable = ['produced', 'qa-failed', 'awaiting-approval'].includes(r.status);
  const history = r.reviews.length ? h('ul.feed', {}, [...r.reviews].reverse().map(v => h('li', {}, pill(v.decision), h('div', {}, v.note), h('div.muted', {}, `${v.reviewer} · ${fmtDate(v.createdAt)}`)))) : h('div.muted', {}, 'No decisions recorded yet.');
  if (!reviewable) return card('Human review', h('div.muted', {}, ['queued', 'running'].includes(r.status) ? 'Available when the run finishes.' : 'This run cannot be reviewed.'), history);
  const opts = [['approved-next-step', 'Approve for next step'], ['changes-requested', 'Request changes'], ['rejected', 'Reject']];
  const radios = h('div.decisions', {}, opts.map(([v, t], i) => h('label', {}, h('input', {type: 'radio', name: 'decision', value: v, checked: i === 1 ? true : undefined}), t)));
  const note = h('textarea', {id: 'rnote', maxlength: 2000, placeholder: 'What did you see? What should change?', required: true});
  const who = h('input', {id: 'rwho', value: 'owner', maxlength: 60});
  const submit = h('button.primary', {type: 'submit'}, 'Record decision');
  const form = h('form', {onsubmit: async ev => {
    ev.preventDefault(); submit.disabled = true;
    try {
      const decision = radios.querySelector('input:checked')?.value;
      await api(`/api/runs/${r.id}/reviews`, {method: 'POST', body: JSON.stringify({decision, note: note.value, reviewer: who.value})});
      toast('Decision recorded'); runDetail(r.id);
    } catch (e) { toast(e.message, true); submit.disabled = false; }
  }}, h('div.notice', {}, 'Your decision is separate from QA. It does not approve anything in the renderer and does not publish.'),
    radios, h('label', {for: 'rnote'}, 'Note (required)'), note, h('label', {for: 'rwho'}, 'Reviewer'), who, h('div.row', {}, submit));
  return card('Human review', h('div.row', {}, 'Current: ', pill(r.review.state)), form, h('h3', {}, 'History'), history);
}

// ---------- generation (AP-84B1): jobs, quarantined candidates, human review, registry proposals
const genUrl = (jobId, name) => `/media/generation/${encodeURIComponent(jobId)}/${encodeURIComponent(name)}`;

// Sub-navigation shared by the generation pages (AP-84B2).
const genTabs = active => h('div.tabs', {}, [['jobs', 'Jobs', '#/generation'], ['requirements', 'Story requirements', '#/generation/requirements'], ['packs', 'Reference packs', '#/generation/packs']]
  .map(([k, t, href]) => h(`a.tab${k === active ? '.active' : ''}`, {href}, t)));
// A requirement's "Request generation" button pre-fills the new-job form (kept in memory only).
let genPrefill = null;
const REQ_PILL = {available: 'pass', missing: 'fail', unapproved: 'warn', unresolved: 'warn'};
const CHECK_PILL = {pass: 'pass', warn: 'warn', fail: 'fail', 'n/a': 'na'};

async function generationPage() {
  const [cfg, jobs, eps, packs] = await Promise.all([api('/api/generation'), api('/api/generation/jobs'), api('/api/episodes'), api('/api/generation/reference-packs')]);
  const pre = genPrefill; genPrefill = null;
  const type = h('select', {id: 'gtype'}, cfg.assetTypes.map(t => h('option', {value: t, selected: pre?.assetType === t ? true : undefined}, t)));
  const key = h('input', {id: 'gkey', placeholder: 'character-01/pose-07  or  living-room-night', maxlength: 129, required: true, value: pre?.assetKey || ''});
  const desc = h('textarea', {id: 'gdesc', maxlength: 1000, placeholder: 'What should the asset show? (pose, expression, framing)', required: true});
  if (pre?.description) desc.value = pre.description;
  const ep = h('select', {id: 'gep'}, h('option', {value: ''}, '(no episode)'), eps.map(e => h('option', {value: e.id}, `${e.title} (${e.id})`)));
  const pack = h('select', {id: 'gpack'}, h('option', {value: ''}, '(none: compare with current registry)'),
    packs.map(p => h('option', {value: String(p.id)}, `#${p.id} ${p.subject.kind} ${p.subject.id}${p.complete ? '' : ' (incomplete)'}`)));
  const submit = h('button.primary', {type: 'submit'}, 'Queue generation job');
  const form = h('form', {onsubmit: async ev => {
    ev.preventDefault(); submit.disabled = true;
    try {
      const j = await api('/api/generation/jobs', {method: 'POST', body: JSON.stringify({assetType: type.value, assetKey: key.value.trim(), description: desc.value, episodeId: ep.value || null,
        referencePackId: pack.value ? Number(pack.value) : null})});
      location.hash = `#/generation/${j.id}`;
    } catch (e) { toast(e.message, true); submit.disabled = false; }
  }}, h('label', {for: 'gtype'}, 'Asset type'), type, h('label', {for: 'gkey'}, 'Asset key'), key, h('label', {for: 'gdesc'}, 'Description'), desc,
    h('label', {for: 'gep'}, 'Episode (optional)'), ep, h('label', {for: 'gpack'}, 'Reference pack (optional)'), pack, h('div.row', {}, submit));
  render(
    h('div.head', {}, h('div', {}, h('h1', {}, 'Generation'), h('div.muted', {}, 'Candidate assets are quarantined and only enter a registry proposal after a human approves them')),
      h('div.row', {}, pill(cfg.available ? 'pass' : 'warn', `adapter: ${cfg.adapter}`))),
    genTabs('jobs'),
    h('div.notice', {}, cfg.reason), h('div.notice', {}, cfg.note),
    h('div.grid.two', {},
      card('Generation jobs', jobs.length ? h('div.table-wrap', {}, h('table', {},
        h('thead', {}, h('tr', {}, h('th', {}, 'Job'), h('th', {}, 'Asset'), h('th', {}, 'Status'), h('th', {}, 'Adapter'), h('th', {}, 'Attempt'), h('th', {}, 'Created'))),
        h('tbody', {}, jobs.map(j => h('tr', {}, h('td.mono', {}, h('a', {href: `#/generation/${j.id}`}, j.id)), h('td', {}, `${j.assetType} · `, h('span.mono', {}, j.assetKey)),
          h('td', {}, pill(j.status.replace('_', '-'), j.status.replace('_', ' '))), h('td.mono', {}, j.adapter), h('td', {}, String(j.attempt)), h('td', {}, fmtDate(j.createdAt))))))) : h('div.empty', {}, 'No generation jobs yet')),
      card('New generation job', form)));
  if (jobs.some(j => ['queued', 'running'].includes(j.status))) poll(generationPage, 2000);
}

async function genJobPage(id) {
  const j = await api(`/api/generation/jobs/${encodeURIComponent(id)}`);
  const active = ['queued', 'running'].includes(j.status);
  const cancel = active ? h('button.danger', {type: 'button', onclick: async () => { try { await api(`/api/generation/jobs/${id}/cancel`, {method: 'POST', body: '{}'}); genJobPage(id); } catch (e) { toast(e.message, true); } }}, 'Cancel job') : null;
  const candCards = j.candidates.map(c => card(null,
    h('div.row', {}, h('b.mono', {}, c.name), c.synthetic ? pill('warn', 'synthetic test fixture') : null),
    c.mediaType === 'image/png' ? h('a', {href: genUrl(id, c.name), target: '_blank', rel: 'noopener'}, h('img.storyboard', {src: genUrl(id, c.name), alt: c.name})) : null,
    h('dl.kv', {}, h('dt', {}, 'Candidate ID'), h('dd', {}, String(c.id)), h('dt', {}, 'SHA-256'), h('dd.mono', {}, c.sha256), h('dt', {}, 'Size'), h('dd', {}, `${fmtBytes(c.bytes)}${c.width ? ` · ${c.width}×${c.height}` : ''}`),
      h('dt', {}, 'Provenance'), h('dd.mono', {}, JSON.stringify(c.provenance))),
    validationBlock(j, c)));
  render(
    h('div.head', {}, h('div', {}, h('h1', {}, 'Generation job ', h('span.mono', {}, j.id)), h('div.muted', {}, `${j.assetType} · `, h('span.mono', {}, j.assetKey), j.episodeId ? ` · episode ${j.episodeId}` : '')),
      h('div.row', {}, pill(j.status.replace('_', '-'), j.status.replace('_', ' ')), cancel)),
    j.error ? h('div.notice.error', {}, j.error, j.retryable ? ' (retryable)' : '') : null,
    h('div.grid.run-grid', {},
      h('div.grid', {},
        card('Job', h('dl.kv', {}, h('dt', {}, 'Description'), h('dd', {}, j.description), h('dt', {}, 'Adapter'), h('dd.mono', {}, j.adapter), h('dt', {}, 'Initiated by'), h('dd', {}, j.initiatedBy),
          h('dt', {}, 'Attempt'), h('dd', {}, String(j.attempt)), h('dt', {}, 'Parent job'), h('dd', {}, j.parentJobId ? h('a.mono', {href: `#/generation/${j.parentJobId}`}, j.parentJobId) : '—'),
          h('dt', {}, 'Reference pack'), h('dd', {}, j.referencePack ? h('a', {href: `#/generation/packs/${j.referencePack.id}`}, `#${j.referencePack.id} ${j.referencePack.subject.kind} ${j.referencePack.subject.id}`) : '— (current registry)'),
          h('dt', {}, 'Created'), h('dd', {}, fmtDate(j.createdAt)), h('dt', {}, 'Finished'), h('dd', {}, fmtDate(j.finishedAt)))),
        genReviewCard(j),
        card('Registry proposals', j.proposals.length ? h('ul.feed', {}, j.proposals.map(p => h('li', {}, h('span.mono', {}, `${p.registry} · ${p.entryKey}@v${p.version}`), ' ',
          pill(p.promotable ? 'pass' : 'warn', p.promotable ? 'promotable later' : 'not promotable'), h('div.muted', {}, p.reason), h('div.muted.mono', {}, `candidate ${p.candidateId} · ${p.candidateSha256.slice(0, 16)}…`)))) : h('div.muted', {}, 'None. Approval creates a versioned proposal; registries are never changed here.'))),
      h('div.grid', {}, candCards.length ? candCards : card('Candidates', h('div.empty', {}, active ? 'Waiting for the worker…' : 'No candidates.'))))
  );
  if (active) poll(() => genJobPage(id), 1500);
}

function genReviewCard(j) {
  const history = j.reviews.length ? h('ul.feed', {}, [...j.reviews].reverse().map(r => h('li', {}, pill(r.decision === 'approve' ? 'pass' : r.decision === 'reject' ? 'fail' : 'warn', r.decision),
    r.candidateId ? ` candidate ${r.candidateId}` : '', r.regeneratedJobId ? h('span', {}, ' → ', h('a.mono', {href: `#/generation/${r.regeneratedJobId}`}, r.regeneratedJobId)) : null,
    h('div', {}, r.note), h('div.muted', {}, `${r.reviewer} · ${fmtDate(r.createdAt)}`)))) : h('div.muted', {}, 'No decisions yet.');
  if (j.status !== 'candidate_ready') return card('Human review', h('div.muted', {}, 'Review is available when candidates are ready.'), history);
  const decision = h('div.decisions', {}, [['approve', 'Approve candidate'], ['reject', 'Reject'], ['regenerate', 'Request regeneration']].map(([v, t], i) => h('label', {}, h('input', {type: 'radio', name: 'gdecision', value: v, checked: i === 1 ? true : undefined}), t)));
  const cand = h('select', {id: 'gcand'}, j.candidates.map(c => h('option', {value: String(c.id)}, `${c.id}: ${c.name}`)));
  const note = h('textarea', {id: 'gnote', maxlength: 2000, required: true, placeholder: 'Reason (required)'});
  const submit = h('button.primary', {type: 'submit'}, 'Record decision');
  const form = h('form', {onsubmit: async ev => {
    ev.preventDefault(); submit.disabled = true;
    try {
      const r = await api(`/api/generation/jobs/${j.id}/reviews`, {method: 'POST', body: JSON.stringify({decision: decision.querySelector('input:checked').value, candidateId: Number(cand.value), note: note.value})});
      toast('Decision recorded'); location.hash = r.regeneratedJobId ? `#/generation/${r.regeneratedJobId}` : `#/generation/${j.id}`; genJobPage(r.regeneratedJobId || j.id);
    } catch (e) { toast(e.message, true); submit.disabled = false; }
  }}, h('div.notice', {}, 'Approval is an explicit human decision. It creates a versioned registry proposal only; it never edits approved artwork or registries.'),
    decision, h('label', {for: 'gcand'}, 'Candidate'), cand, h('label', {for: 'gnote'}, 'Note'), note, h('div.row', {}, submit));
  return card('Human review', form, h('h3', {}, 'History'), history);
}

// ---------- AP-84B2: validation reports, story requirements, reference packs
// Latest validation report for one candidate, plus a re-validate button. Validation is advisory only.
function validationBlock(j, c) {
  const all = (j.validations || []).filter(v => v.candidateId === c.id);
  const latest = all[all.length - 1];
  const again = h('button', {type: 'button', onclick: async ev => {
    ev.target.disabled = true;
    try { await api(`/api/generation/jobs/${j.id}/validate`, {method: 'POST', body: '{}'}); toast('Validation recorded'); genJobPage(j.id); }
    catch (e) { toast(e.message, true); ev.target.disabled = false; }
  }}, 'Validate again');
  if (!latest) return h('div', {}, h('h3', {}, 'Validation'), h('div.muted', {}, 'No validation report yet.'), j.candidates.length ? h('div.row', {}, again) : null);
  return h('div', {}, h('h3', {}, 'Validation ', pill(CHECK_PILL[latest.status], latest.status)),
    h('div.muted', {}, `${latest.trigger} · ${fmtDate(latest.createdAt)} · ${all.length} report(s)${latest.referencePackId ? ` · pack #${latest.referencePackId}` : ''}. Advisory only: it never approves.`),
    h('ul.checks', {}, latest.checks.map(ch => h('li', {}, pill(CHECK_PILL[ch.status], ch.status), ' ', h('b', {}, ch.id), h('div.muted', {}, ch.detail)))),
    h('div.row', {}, again));
}

async function requirementsPage() {
  const stories = await api('/api/generation/requirements');
  const request = (assetType, assetKey, description) => { genPrefill = {assetType, assetKey, description}; location.hash = '#/generation'; };
  const reqRow = (kind, key, r, onRequest) => h('tr', {},
    h('td', {}, kind), h('td.mono', {}, key), h('td', {}, pill(REQ_PILL[r.status], r.status)),
    h('td.mono', {}, r.approval || '—'), h('td', {}, r.uses ? `${r.uses}× · ${r.scenes.join(', ')}` : r.scenes?.join(', ') || '—'),
    h('td', {}, r.reason || ''), h('td', {}, r.status === 'available' ? '' : onRequest ? h('button', {type: 'button', onclick: onRequest}, 'Request generation') : ''));
  const storyCard = s => {
    if (!s.valid) return card(s.storyFile, h('div.notice.error', {}, s.error));
    const rows = [];
    for (const c of s.characters) for (const p of c.poses)
      rows.push(reqRow('pose', p.pose ? `${c.character}/pose-${p.pose}` : c.character, p,
        p.pose && c.registryFound ? () => request('character-pose', `${c.character}/pose-${p.pose}`, `Pose ${p.pose} for ${c.character}, needed by ${s.title}`) : null));
    for (const e of s.environments) rows.push(reqRow('environment', e.id || '(direct file path)', e, e.id ? () => request('environment', e.id, `Environment ${e.id}, needed by ${s.title}`) : null));
    const mk = h('button', {type: 'button', onclick: async ev => {
      ev.target.disabled = true;
      try { const p = await api('/api/generation/reference-packs', {method: 'POST', body: JSON.stringify({kind: 'story', id: s.storyFile})}); location.hash = `#/generation/packs/${p.id}`; }
      catch (e) { toast(e.message, true); ev.target.disabled = false; }
    }}, 'Record reference pack');
    return card(null, h('div.head', {}, h('div', {}, h('h2', {}, s.title), h('div.muted.mono', {}, s.storyFile)),
      h('div.row', {}, ...Object.entries(s.summary).map(([k, n]) => pill(REQ_PILL[k], `${n} ${k}`)), mk)),
      h('div.table-wrap', {}, h('table', {}, h('thead', {}, h('tr', {}, ...['Kind', 'Asset', 'Status', 'Approval', 'Used', 'Reason', ''].map(t => h('th', {}, t)))), h('tbody', {}, rows))));
  };
  render(h('div.head', {}, h('div', {}, h('h1', {}, 'Story requirements'), h('div.muted', {}, 'What each approved story needs, checked against the registries and files (read-only)'))),
    genTabs('requirements'), stories.length ? h('div.grid', {}, stories.map(storyCard)) : h('div.empty', {}, 'No stories in production/stories/'));
}

async function packsPage() {
  const packs = await api('/api/generation/reference-packs');
  const kind = h('select', {id: 'pkind'}, h('option', {value: 'character'}, 'character'), h('option', {value: 'story'}, 'story'));
  const id = h('input', {id: 'pid', placeholder: 'character-01  or  short-001-v2.story.json', maxlength: 100, required: true});
  const note = h('input', {id: 'pnote', placeholder: 'Optional note', maxlength: 500});
  const submit = h('button.primary', {type: 'submit'}, 'Record reference pack');
  const form = h('form', {onsubmit: async ev => {
    ev.preventDefault(); submit.disabled = true;
    try { const p = await api('/api/generation/reference-packs', {method: 'POST', body: JSON.stringify({kind: kind.value, id: id.value.trim(), note: note.value})}); location.hash = `#/generation/packs/${p.id}`; }
    catch (e) { toast(e.message, true); submit.disabled = false; }
  }}, h('div.notice', {}, 'A pack records each reference file\'s source, SHA-256, dimensions, approval and version. Packs cannot be changed; files are never copied or modified.'),
    h('label', {for: 'pkind'}, 'Subject'), kind, h('label', {for: 'pid'}, 'Character or story'), id, h('label', {for: 'pnote'}, 'Note'), note, h('div.row', {}, submit));
  render(h('div.head', {}, h('div', {}, h('h1', {}, 'Reference packs'), h('div.muted', {}, 'Immutable snapshots of the references a generation request is compared with'))),
    genTabs('packs'),
    h('div.grid.two', {},
      card('Recorded packs', packs.length ? h('div.table-wrap', {}, h('table', {}, h('thead', {}, h('tr', {}, ...['Pack', 'Subject', 'Items', 'State', 'Created'].map(t => h('th', {}, t)))),
        h('tbody', {}, packs.map(p => h('tr', {}, h('td', {}, h('a', {href: `#/generation/packs/${p.id}`}, `#${p.id}`)), h('td', {}, `${p.subject.kind} · `, h('span.mono', {}, p.subject.id)),
          h('td', {}, String(p.itemCount)), h('td', {}, pill(p.complete ? 'pass' : 'warn', p.complete ? 'complete' : 'incomplete')), h('td', {}, fmtDate(p.createdAt))))))) : h('div.empty', {}, 'No reference packs yet')),
      card('New reference pack', form)));
}

async function packDetailPage(id) {
  const p = await api(`/api/generation/reference-packs/${encodeURIComponent(id)}`);
  const now = Object.fromEntries(p.verification.results.map(r => [r.ref, r]));
  const verifyPill = r => r.state === 'ok' ? pill('pass', 'matches') : pill('fail', r.state === 'missing' ? 'missing now' : 'changed since recorded');
  render(
    h('div.head', {}, h('div', {}, h('h1', {}, `Reference pack #${p.id}`), h('div.muted', {}, `${p.subject.kind} · `, h('span.mono', {}, p.subject.id), ` · ${fmtDate(p.createdAt)} · ${p.createdBy}`)),
      h('div.row', {}, pill(p.complete ? 'pass' : 'warn', p.complete ? 'complete when recorded' : 'incomplete when recorded'), pill(p.verification.ok ? 'pass' : 'fail', p.verification.ok ? 'verified now' : 'drift detected'))),
    genTabs('packs'),
    p.problems.length ? h('div.notice.error', {}, `Problems when recorded: ${p.problems.join('; ')}`) : null,
    p.note ? h('div.notice', {}, p.note) : null,
    card('Pack', h('dl.kv', {}, h('dt', {}, 'Pack SHA-256'), h('dd.mono', {}, p.packSha256), h('dt', {}, 'Checked'), h('dd', {}, fmtDate(p.verification.checkedAt)))),
    card('Items', h('div.table-wrap', {}, h('table', {},
      h('thead', {}, h('tr', {}, ...['Reference', 'Role', 'SHA-256', 'Size', 'Measured figure', 'Approval', 'Version', 'Now'].map(t => h('th', {}, t)))),
      h('tbody', {}, p.items.map(i => h('tr', {}, h('td.mono', {}, i.ref), h('td', {}, i.role || ''), h('td.mono', {title: i.sha256 || ''}, i.sha256 ? `${i.sha256.slice(0, 16)}…` : '—'),
        h('td', {}, i.width ? `${i.width}×${i.height}` : '—'), h('td', {}, measuredText(i)),
        h('td.mono', {}, i.approval || '—'), h('td', {}, `v${i.version}`), h('td', {}, now[i.ref] ? verifyPill(now[i.ref]) : '—'))))))));
}
// Silhouette and feet anchor measured from a reference (cut-outs only); source paths are never shown.
function measuredText(i) {
  const m = i.measured;
  if (!m) return '—';
  if (!m.cutout) return 'opaque image';
  const feet = m.feet ? ` · feet ${m.feet.x},${m.feet.y}` : '';
  const reg = i.registeredFeet ? ` (registered ${i.registeredFeet.x},${i.registeredFeet.y})` : '';
  return `${m.silhouette.width}×${m.silhouette.height}${feet}${reg}`;
}

// ---------- router, polling, theme, engine status
function poll(fn, ms) { clearTimeout(timer); timer = setTimeout(() => { if (document.visibilityState === 'visible') fn().catch(() => {}); else poll(fn, ms); }, ms); }
async function route() {
  clearTimeout(timer);
  const hash = location.hash.replace(/^#/, '') || '/';
  const parts = hash.split('/').filter(Boolean);
  document.querySelectorAll('[data-nav]').forEach(a => a.classList.toggle('active', a.dataset.nav === (parts[0] || 'overview')));
  try {
    if (!parts.length) await overview();
    else if (parts[0] === 'episodes' && parts[1] === 'new') await newEpisode();
    else if (parts[0] === 'episodes' && parts[1]) await episodeDetail(decodeURIComponent(parts[1]));
    else if (parts[0] === 'episodes') await episodes();
    else if (parts[0] === 'runs' && parts[1]) await runDetail(decodeURIComponent(parts[1]));
    else if (parts[0] === 'runs') await runsPage();
    else if (parts[0] === 'generation' && parts[1] === 'requirements') await requirementsPage();
    else if (parts[0] === 'generation' && parts[1] === 'packs' && parts[2]) await packDetailPage(decodeURIComponent(parts[2]));
    else if (parts[0] === 'generation' && parts[1] === 'packs') await packsPage();
    else if (parts[0] === 'generation' && parts[1]) await genJobPage(decodeURIComponent(parts[1]));
    else if (parts[0] === 'generation') await generationPage();
    else render(h('div.empty', {}, 'Page not found'));
  } catch (e) { render(h('div.notice.error', {}, e.message)); }
}
const themeBtn = document.getElementById('theme');
function setTheme(t) { document.documentElement.dataset.theme = t; themeBtn.textContent = t === 'dark' ? 'Light' : 'Dark'; try { localStorage.setItem('studio-theme', t); } catch {} }
themeBtn.addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
try { setTheme(localStorage.getItem('studio-theme') || 'dark'); } catch { setTheme('dark'); }
api('/api/health').then(hh => { const e = document.getElementById('engine'); e.textContent = hh.ffmpegConfigured ? 'engine ready' : 'FFMPEG/FFPROBE not set'; e.className = `pill ${hh.ffmpegConfigured ? 's-pass' : 's-warn'}`; }).catch(() => {});
window.addEventListener('hashchange', route);
route();
