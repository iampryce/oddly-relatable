// Audio-first Stage 2: moving a cut between scenes in the script editor. Scenes are runs of recorded lines; splitting
// or joining only moves where a cut falls (always between two lines), so every line stays, in order. The server
// checks the same rule (it refuses any change to the recorded dialogue).

type SceneLike = {id?: string; heading: string; lines: any[]};

// Split scene i after its k-th line (1 <= k < lines); scene ids are renumbered.
export function splitScene<T extends SceneLike>(scenes: T[], i: number, k: number): T[] {
  const sc = scenes[i];
  if (!sc || k < 1 || k >= sc.lines.length) return scenes;
  const out = [...scenes.slice(0, i), {...sc, lines: sc.lines.slice(0, k)}, {...sc, heading: `${sc.heading} (cont.)`, lines: sc.lines.slice(k)}, ...scenes.slice(i + 1)];
  return out.map((x, j) => ({...x, id: `s${j + 1}`}));
}

// Join scene i onto the scene before it (its heading and details are kept); ids are renumbered.
export function joinWithPrevious<T extends SceneLike>(scenes: T[], i: number): T[] {
  if (i < 1 || i >= scenes.length) return scenes;
  const out = scenes.flatMap((x, j) => (j === i ? [] : j === i - 1 ? [{...x, lines: [...x.lines, ...scenes[i].lines]}] : [x]));
  return out.map((x, j) => ({...x, id: `s${j + 1}`}));
}
