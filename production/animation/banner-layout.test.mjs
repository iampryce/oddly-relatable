// node --test production/animation/ : banner text rules (no canvas package needed).
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {layoutBanner, hookUnits, trailingEmoji, cutWithEllipsis, BANNER} from './banner-layout.mjs';

// A fake 2D context: every character (an emoji counts as one) is 0.5 × the font size wide.
function fakeCtx() {
  let size = 86;
  return {
    set font(f) { size = parseInt(f, 10); }, get font() { return `${size}px`; },
    measureText: s => ({width: Array.from(s).length * size * 0.5}),
  };
}
const W = 1080;
const emojiAlone = rows => rows.some(r => hookUnits(r).length === 1 && trailingEmoji('x ' + r) === r);

test('an emoji is glued to the word before it (and a leading emoji to the word after it)', () => {
  assert.deepEqual(hookUnits('POV: the card says sorry 😬'), ['POV:', 'the', 'card', 'says', 'sorry 😬']);
  assert.deepEqual(hookUnits('POV: needs met 😂 🍆'), ['POV:', 'needs', 'met 😂 🍆']);
  assert.deepEqual(hookUnits('😬 POV: oops'), ['😬 POV:', 'oops']);
  assert.deepEqual(hookUnits('POV: a family 👨‍👩‍👧 party'), ['POV:', 'a', 'family 👨‍👩‍👧', 'party']);
  assert.equal(trailingEmoji('POV: oops 😬'), '😬');
  assert.equal(trailingEmoji('POV: oops'), '');
});

test('(a) a short hook whose emoji would wrap keeps it on the line with the last word', () => {
  // fake widths: 960 px inner width / 43 px per character at 86 px = 22 characters per row at the top size.
  // 'POV: the card is sorry' is 22 characters: it fills row 1, so the old wrap put '😬' alone on row 2.
  let L = layoutBanner(fakeCtx(), 'POV: the card is sorry 😬', W);
  assert.equal(L.size, BANNER.maxSize);
  assert.deepEqual(L.rows, ['POV: the card is', 'sorry 😬']);
  // the short hook from the episode 5 banner stills (its emoji sat alone on row 2)
  L = layoutBanner(fakeCtx(), 'POV: the card says sorry 😬', W);
  assert.deepEqual(L.rows, ['POV: the card says', 'sorry 😬']);
  assert.ok(!emojiAlone(L.rows));
});

test('every row of a two-line hook ends on a word or a word + emoji, never a bare emoji', () => {
  for (const hook of ["POV: someone signed the boss's birthday card with deepest condolences 😬",
                      'POV: when she is mad at you but still needs her needs met 😂 🍆']) {
    const L = layoutBanner(fakeCtx(), hook, W);
    for (const r of L.rows) assert.ok(!/^\P{L}*$/u.test(r), `row without a word: ${JSON.stringify(L.rows)}`);
    assert.ok(L.rows.at(-1).endsWith(trailingEmoji(hook)));
  }
});

test('(b) a hook cut with "…" keeps its closing emoji after the ellipsis', () => {
  const hook = "POV: you signed the boss's birthday card 'deepest condolences', HR is reading it aloud at the all-hands meeting and everyone turns to look at you 😬";
  const ctx = fakeCtx(), L = layoutBanner(ctx, hook, W), inner = W - 2 * BANNER.margin - 2 * BANNER.pad;
  assert.equal(L.size, BANNER.minSize);
  assert.equal(L.rows.length, BANNER.maxRows);
  assert.ok(L.rows.at(-1).endsWith('… 😬'), JSON.stringify(L.rows));
  assert.equal((L.rows.join(' ').match(/😬/gu) || []).length, 1, 'the emoji appears once');
  const kept = L.rows.at(-1).replace(/… 😬$/u, '');
  assert.ok(hook.includes(kept + ' '), `cut inside a word: ${L.rows.at(-1)}`);
  ctx.font = `${L.size}px`;
  for (const r of L.rows) assert.ok(ctx.measureText(r).width <= inner + 1e-9, `row too wide: ${r}`);
});

test('a cut hook without an emoji ends with a plain ellipsis; emoji are never split', () => {
  const L = layoutBanner(fakeCtx(), 'POV: ' + 'endless words '.repeat(20), W);
  assert.ok(L.rows.at(-1).endsWith('…') && !L.rows.at(-1).endsWith(' …'));
  const ctx = fakeCtx(); ctx.font = '52px';
  const cut = cutWithEllipsis(ctx, 'abc 👨‍👩‍👧 def ghi', 52 * 0.5 * 8, '😬');
  assert.ok(!/[\ud800-\udbff]$/.test(cut.replace('… 😬', '')), 'no half surrogate pair');
  assert.ok(cut.endsWith('… 😬'));
});

test('a cut that already ends on a whole word keeps that word', () => {
  const ctx = fakeCtx(); ctx.font = '52px';
  // room for 'aaaa bbbb cccc' + '… 😬' exactly: the next character is a space, so 'cccc' stays
  assert.equal(cutWithEllipsis(ctx, 'aaaa bbbb cccc dddd', 26 * 17, '😬'), 'aaaa bbbb cccc… 😬');
  // one character less: the cut falls inside 'cccc', so it backs up to 'bbbb'
  assert.equal(cutWithEllipsis(ctx, 'aaaa bbbb cccc dddd', 26 * 16, '😬'), 'aaaa bbbb… 😬');
});
