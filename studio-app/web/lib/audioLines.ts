// Audio-first line edits (split, merge, bulk speaker) as pure functions on {lines, selected}.
// The selection holds row indices, so any edit that adds or removes rows clears it: otherwise "Set speaker for
// selected" would label whichever rows moved into the old indices (Codex review of Stage 1c, P2).

export type Word = {start: number; end: number; word: string};
export type Line = {id: string; start: number; end: number; text: string; speaker: string; words: Word[]};
export type LinesState = {lines: Line[]; selected: Set<number>};
export type LineEdit =
  | {kind: 'split'; index: number; word: number}     // split line `index` before word `word`
  | {kind: 'merge'; index: number}                   // merge line `index` with the next one
  | {kind: 'speaker'; speaker: string};              // set the speaker of the selected lines

const wordsText = (ws: Word[]) => ws.map(x => x.word).join(' ');

export function applyEdit(state: LinesState, edit: LineEdit): LinesState {
  const {lines} = state;
  if (edit.kind === 'split') {
    const l = lines[edit.index];
    if (!l) return state;
    const first = l.words.slice(0, edit.word), second = l.words.slice(edit.word);
    if (!first.length || !second.length) return state;
    return {lines: [...lines.slice(0, edit.index), {...l, end: first[first.length - 1].end, text: wordsText(first), words: first},
                    {...l, id: `${l.id}b`, start: second[0].start, text: wordsText(second), words: second}, ...lines.slice(edit.index + 1)],
            selected: new Set()};
  }
  if (edit.kind === 'merge') {
    const a = lines[edit.index], b = lines[edit.index + 1];
    if (!a || !b) return state;
    return {lines: [...lines.slice(0, edit.index), {...a, end: b.end, text: `${a.text} ${b.text}`.trim(), speaker: a.speaker || b.speaker,
                                                    words: [...a.words, ...b.words]}, ...lines.slice(edit.index + 2)],
            selected: new Set()};
  }
  const sp = edit.speaker.trim().slice(0, 40);
  return {lines: lines.map((l, k) => (state.selected.has(k) ? {...l, speaker: sp} : l)), selected: new Set()};
}
