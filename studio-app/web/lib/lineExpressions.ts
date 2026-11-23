// A character's usable expressions and which one a line actually gets (feat/3d-rig PR 4; the same rule as the API's
// casting.closest_expression). Pure; node --test.
const FAMILIES = [
  ['angry', 'furious', 'mad', 'annoyed', 'irritated', 'cross', 'outraged', 'frustrated', 'stern'],
  ['happy', 'amused', 'pleased', 'cheerful', 'delighted', 'glad', 'laughing', 'grinning', 'smiling', 'excited'],
  ['smug', 'sly', 'proud', 'satisfied', 'superior', 'knowing'],
  ['shocked', 'surprised', 'stunned', 'astonished', 'startled', 'amazed', 'aghast'],
  ['worried', 'anxious', 'nervous', 'concerned', 'uneasy', 'scared', 'afraid', 'fearful'],
  ['sad', 'upset', 'gloomy', 'hurt', 'disappointed', 'miserable', 'crying'],
  ['deadpan', 'neutral', 'calm', 'serious', 'flat', 'blank', 'bored'],
  ['confused', 'puzzled', 'bewildered', 'doubtful', 'skeptical'],
];

export function usableExpressions(c: any): string[] {
  return [...new Set(['neutral', ...Object.keys(c?.expressions || {})])].sort();
}

export function usedExpression(c: any, wanted: string): string {
  const have = usableExpressions(c), w = (wanted || 'neutral').toLowerCase();
  if (have.includes(w)) return w;
  const loose = have.find(e => e && (w.includes(e) || e.includes(w)));
  if (loose) return loose;
  for (const fam of FAMILIES) if (fam.includes(w) || fam.some(f => w.includes(f))) { const f = fam.find(x => have.includes(x)); if (f) return f; }
  return 'neutral';
}
