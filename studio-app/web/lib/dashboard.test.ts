// node --test: the clean dashboard's steps, list status, Generate plan and the episode's own characters.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {episodeCharacters, GENERATE_FREE, generatePlan, listStatus, money, phrase, stepSections, steps} from './dashboard.ts';

const sec = (key: string, status: string, label = status, note = `${key} note.`) =>
  ({key, title: key[0].toUpperCase() + key.slice(1), status, label, note, blocking: false, open: false, jobs: []});

const ALL = ['set', 'people', 'plan', 'lines', 'notes', 'cast', 'script', 'storyboard', 'talking', 'production', 'review', 'publishing'];
function ws(over: Record<string, any> = {}, extra: Record<string, any> = {}) {
  return {sections: ALL.map(k => over[k] || sec(k, 'waiting')), blocker: null, current: null, next: null, running: [], ...extra};
}
const audioEp = (stage: string, actions: string[] = []) => ({id: 7, source: 'audio', stage, allowed_actions: actions, jobs: []});

test('six steps in order; an audio episode keeps its scenes (script) with the storyboard', () => {
  const s = steps(ws(), {source: 'audio'});
  assert.deepEqual(s.map(x => x.title), ['Video', 'Characters', 'Sets', 'Storyboard', 'Video', 'Final']);
  assert.deepEqual(stepSections(true).storyboard, ['script', 'storyboard']);
  assert.deepEqual(stepSections(false).source, ['script']);
  assert.equal(steps(ws(), {source: 'script'})[0].title, 'Script');
});

test('a step shows its worst section; done steps show the counts', () => {
  const w = ws({lines: sec('lines', 'done'), notes: sec('notes', 'done'), people: sec('people', 'not_needed'), plan: sec('plan', 'done'),
    cast: sec('cast', 'done'), set: sec('set', 'todo', 'choose'), script: sec('script', 'action', 'review', 'Review and approve the script.'),
    storyboard: sec('storyboard', 'waiting')});
  const s = steps(w, {source: 'audio'}, {lines: 24, shots: 40, approvedCharacters: 9, setsWaiting: 2});
  assert.equal(s[0].state, 'done');
  assert.equal(s[0].text, 'analysed (40 shots, 24 lines)');
  assert.equal(s[1].text, '9 approved');
  assert.equal(s[2].state, 'you', 'a waiting set candidate is the owner\'s decision');
  assert.equal(s[2].text, '2 sets to approve');
  assert.equal(s[3].state, 'you');
  assert.equal(s[3].text, 'Review and approve the script.');
  assert.equal(s[4].state, 'waiting');
  const failed = steps(ws({production: sec('production', 'failed'), review: sec('review', 'waiting')}), {source: 'audio'});
  assert.equal(failed[4].state, 'failed');
});

test('the list line: published, working, failed, and what waits for the owner', () => {
  assert.deepEqual(listStatus({stage: 'published'}), {tone: 'good', icon: '✓', text: 'Published'});
  assert.equal(listStatus({stage: 'producing', next_step: 'Production is running'}).tone, 'busy');
  assert.equal(listStatus({stage: 'production_failed', next_step: 'Fix it'}).tone, 'bad');
  const w = ws({set: sec('set', 'action', 'choose', 'Production cannot start.')}, {blocker: {section: 'set'}, current: 'set'});
  assert.equal(listStatus({stage: 'storyboard_approved'}, w).text, 'Waiting for you: approve sets');
  assert.equal(listStatus({stage: 'script_review', next_step: 'Review, edit and approve the script'}).text,
    'Waiting for you: Review, edit and approve the script');
  assert.equal(phrase('review', 'review'), 'approve the video');
  assert.equal(phrase('odd', 'thing', 'Do this.'), 'do this');
});

test('Generate builds the scenes only when the writer costs exactly nothing; a priced writer stops with the cost', () => {
  const ep = audioEp('audio_labelling', ['build_audio_scenes']);
  const w = ws({script: sec('script', 'action', 'build')}, {blocker: {section: 'script'}, current: 'script'});
  assert.equal(generatePlan(ep, w, null).kind, 'stop', 'no estimate yet: nothing starts');
  const free = generatePlan(ep, w, {writer: {provider: 'none', usd: 0}});
  assert.equal(free.kind, 'free');
  assert.ok(free.kind === 'free' && free.path === '/episodes/7/audio/scenes');
  const paid = generatePlan(ep, w, {writer: {provider: 'anthropic', usd: 0.042}});
  assert.equal(paid.kind, 'stop');
  assert.ok(paid.kind === 'stop' && paid.why === 'paid' && paid.text.includes('$0.042'));
  const unknown = generatePlan(ep, w, {writer: {provider: 'unknown', usd: null}});
  assert.ok(unknown.kind === 'stop' && unknown.why === 'paid', 'an estimate that could not be made is never treated as free');
});

test('Generate makes the storyboard from an approved script (free), and stops at every decision', () => {
  const sb = generatePlan({id: 3, stage: 'script_approved', allowed_actions: ['generate_storyboard'], jobs: []},
    ws({storyboard: sec('storyboard', 'action', 'build')}, {blocker: {section: 'storyboard'}, current: 'storyboard'}), null);
  assert.ok(sb.kind === 'free' && sb.path === '/episodes/3/storyboard/generate');
  for (const [stage, key, label] of [['script_review', 'script', 'review'], ['storyboard_review', 'storyboard', 'review'],
    ['video_review', 'review', 'review'], ['final_approved', 'publishing', 'approve'], ['audio_labelling', 'lines', 'speakers'],
    ['audio_labelling', 'plan', 'accept'], ['storyboard_approved', 'set', 'choose']]) {
    const p = generatePlan(audioEp(stage, ['approve_script', 'approve_storyboard', 'approve_video', 'approve_publish', 'publish']),
      ws({[key]: sec(key, 'action', label)}, {blocker: {section: key}, current: key}), {writer: {usd: 0}});
    assert.equal(p.kind, 'stop', `${stage}/${key} is the owner's`);
    assert.ok(p.kind === 'stop' && p.why === 'decision');
  }
});

test('Generate never starts a paid step: production and talking shots only show their cost', () => {
  const prod = generatePlan(audioEp('storyboard_approved', ['start_production']),
    ws({production: sec('production', 'action', 'start')}, {blocker: {section: 'production'}, current: 'production',
      next: {section: 'production', title: 'Production', kind: 'estimate', cost_usd: null}}), null);
  assert.ok(prod.kind === 'stop' && prod.why === 'paid');
  const talk = generatePlan(audioEp('storyboard_approved'), ws({talking: sec('talking', 'todo')}, {current: 'talking',
    next: {section: 'talking', title: 'Talking shots', kind: 'paid', cost_usd: 0.135}}), null);
  assert.ok(talk.kind === 'stop' && talk.why === 'paid' && talk.text.includes('$0.135'));
});

test('Generate waits while anything runs, and its only calls are the free ones', () => {
  const busy = generatePlan({...audioEp('script_approved', ['generate_storyboard']), jobs: [{status: 'running'}]}, ws(), null);
  assert.ok(busy.kind === 'stop' && busy.why === 'working');
  assert.ok(generatePlan(audioEp('published'), ws(), null).kind === 'stop');
  for (const p of GENERATE_FREE) assert.doesNotMatch(p, /approve|decide|publish|production|talking|shot-batch|reject|cast\/generate|set-proposal/);
});

test('money: small amounts keep their digits; unknown is said, never $0', () => {
  assert.equal(money(0.0042), '$0.0042');
  assert.equal(money(0.135), '$0.135');
  assert.equal(money(2.5), '$2.50');
  assert.equal(money(null), 'cost unknown');
});

test("an episode's characters: script cast, speakers and silent cast, each once, nothing else from the library", () => {
  const lib = [{key: 'mortimer', name: 'Mortimer', id: 1, art_status: 'approved', assets: [{kind: 'pose', status: 'approved', url: '/m.png'}]},
    {key: 'winnie', name: 'Winnie', id: 2, art_status: 'review'}, {key: 'ralph', name: 'Ralph', id: 3, art_status: 'approved', locked: true},
    {key: 'stranger', name: 'Not in this episode', id: 4, art_status: 'approved'}];
  const out = episodeCharacters([{key: 'mortimer'}], {speakers: ['mortimer', 'winnie', 'Speaker 3'], speakers_without_character: ['Speaker 3'],
    silent_cast: [{name: 'Ralph', character_key: 'ralph'}, {name: 'Nobody', character_key: null}]}, lib);
  assert.deepEqual(out.map(c => [c.key, c.status, c.role]), [['mortimer', 'approved', 'in the script'], ['winnie', 'review', 'speaks'],
    ['Speaker 3', 'missing', 'not cast yet'], ['ralph', 'approved', 'silent']]);
  assert.equal(out[0].thumb, '/m.png');
  assert.equal(episodeCharacters(null, null, lib).length, 0);
});
