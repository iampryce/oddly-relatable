// node --test: the Now box.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {nowBox} from './nowBox.ts';

test('the Now box: one action, its cost, and a button that only opens or hands over to the existing confirm', () => {
  assert.equal(nowBox(null), null);
  assert.deepEqual(nowBox({section: 'plan', title: 'Reference plan', text: 'Accept the Reference plan.', kind: 'decision',
    cost_text: 'no cost: your decision', button: {action: 'open', label: 'Open Reference plan'}}),
  {title: 'Reference plan', text: 'Accept the Reference plan.', cost: 'no cost: your decision', tone: '',
    button: {action: 'open', label: 'Open Reference plan', section: 'plan'}});
  const t = nowBox({section: 'talking', title: 'Talking shots', text: '1 of 4 lines keyed.', kind: 'paid', cost_usd: 0.135,
    cost_text: 'about $0.135 for 3 line(s), shown again with the total before anything starts', button: {action: 'run_talking', label: 'Run 3 line(s)'}});
  assert.equal(t?.button?.action, 'run_talking');
  assert.match(t!.cost, /shown again with the total before anything starts/);
  const s = nowBox({section: 'script', title: 'Script', text: 'Generate the script.', kind: 'estimate', cost_text: 'cost shown before it starts',
    button: {action: 'open', label: 'Open Script'}});
  assert.equal(s?.cost, 'cost shown before it starts', 'no estimate: never "free"');
  const w = nowBox({section: 'production', title: 'Production', text: 'Rendering…', kind: 'working', cost_text: '', button: null});
  assert.deepEqual([w?.tone, w?.button], ['muted', null]);
});
