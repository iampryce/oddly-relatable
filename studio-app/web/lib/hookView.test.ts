// node --test: what the hook banner switch says.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {hookNote} from './hookView.ts';

test('the banner note: off for audio by default, the text when on, locked while rendering', () => {
  assert.match(hookNote({hook_banner: false, source: 'audio'}, false), /^Off \(audio episodes start without a banner\)/);
  assert.match(hookNote({hook_banner: false, source: 'script'}, false), /^Off;/);
  assert.equal(hookNote({hook_banner: true, hook_text: 'POV: the will'}, false), 'Shows "POV: the will" at the top; applies to the stills and the next render');
  assert.match(hookNote({hook_banner: true, hook_text: ''}, false), /the script's hook/);
  assert.equal(hookNote({hook_banner: true}, true), 'Locked while rendering');
});
