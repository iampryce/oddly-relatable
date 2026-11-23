'use client';
// Each line's expressions in a storyboard scene, changeable in place (feat/3d-rig PR 4): the speaker's and each
// reacting character's, from that character's usable (approved) expressions only. Only the storyboard line changes:
// the script and its approval stay as they are. An expression without its own pose shows which approved one is used.
import {api} from '@/lib/api';
import {usableExpressions, usedExpression} from '@/lib/lineExpressions';

const STAGES = ['storyboard_review', 'storyboard_approved', 'production_failed', 'video_review'];

export default function LineExpressions({ep, scene, characters, act}: {ep: any; scene: any; characters: any[]; act: any}) {
  const editable = STAGES.includes(ep.stage);
  const char = (k: string) => characters.find(c => c.key === k);
  const set = (li: number, expression: string, character?: string) => act.run(`expr-${li}`, () =>
    api(`/episodes/${ep.id}/scenes/${scene.id}/lines/${li}/expression`, {method: 'PUT', body: {expression, ...(character ? {character} : {})}}));
  const pick = (li: number, key: string, value: string, reacting: boolean) => {
    const c = char(key), usable = usableExpressions(c), used = usedExpression(c, value);
    return <label key={`${li}-${key}`} className="row small" style={{gap: 4}}>{c?.name || key}
      <select aria-label={`line ${li + 1} ${c?.name || key} expression`} style={{width: 'auto'}} disabled={!editable || !!act.busy}
        value={usable.includes(value) ? value : ''} onChange={e => set(li, e.target.value, reacting ? key : undefined)}>
        {!usable.includes(value) && <option value="">{value || 'neutral'} (uses {used})</option>}
        {usable.map(x => <option key={x} value={x}>{x}</option>)}
      </select></label>;
  };
  if (!(scene.lines || []).length) return null;
  return (
    <details className="small"><summary>Expressions per line{editable ? ' (change without sending the script back)' : ''}</summary>
      <div className="stack" style={{marginTop: 6}}>
        {scene.lines.map((ln: any, li: number) => (
          <div key={li} className="row" style={{gap: 10, flexWrap: 'wrap'}}>
            <span className="muted">{li + 1}. “{String(ln.text || '').slice(0, 40)}{String(ln.text || '').length > 40 ? '…' : ''}”</span>
            {pick(li, ln.speaker, ln.expression || 'neutral', false)}
            {(ln.reactions || []).map((r: any) => pick(li, r.character, r.expression || 'neutral', true))}
          </div>))}
      </div></details>);
}
