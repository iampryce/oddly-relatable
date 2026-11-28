// Import of local generations (asset_import.py): the pose dimension, the provenance panel and the check shown before an
// upload (what will be stored). The server verifies the file's sha256 again and refuses a mismatch; an import is always a
// candidate that the owner approves or rejects with the existing flows.

export const DIMENSIONS: Record<string, string[]> = {
  posture: ['standing', 'seated'], body_turn: ['front', 'left', 'right'], view: ['front', 'back'], framing: ['full', 'chest_up', 'bust'],
};
export const DIMENSION_LABEL: Record<string, string> = {posture: 'Posture', body_turn: 'Body turn', view: 'View', framing: 'Framing'};
export const CHARACTER_KINDS = ['pose', 'mask', 'expression-sheet', 'back-view'];
export const SET_KINDS = ['set-plate', 'set'];

// "seated · turned left · chest up"; the default dimension (all empty) reads "standing · front (default)".
export function dimensionLabel(a: any): string {
  const bits: string[] = [];
  bits.push(a.posture || 'standing');
  if (a.body_turn && a.body_turn !== 'front') bits.push(`turned ${a.body_turn}`);
  else bits.push('front');
  if (a.view === 'back') bits.push('seen from the back');
  if (a.framing && a.framing !== 'full') bits.push(a.framing.replace('_', '-'));
  const isDefault = !a.posture && !a.body_turn && !a.view && !a.framing;
  return bits.join(' · ') + (isDefault ? ' (default)' : '');
}

export const isImported = (a: any): boolean => !!a?.imported;

// Imported assets of a character, newest first, each followed by the assets that belong to it (a mask under its pose).
export function importedAssets(assets: any[]): any[] {
  const mine = assets.filter(isImported);
  const ids = new Set(mine.map(a => a.id));
  const roots = mine.filter(a => !a.parent_asset_id || !ids.has(a.parent_asset_id));
  const out: any[] = [];
  const walk = (a: any) => { out.push(a); mine.filter(x => x.parent_asset_id === a.id).forEach(walk); };
  roots.forEach(walk);
  return out;
}

export type FileFacts = {name: string; size: number; sha256: string; width?: number; height?: number};

// What will be stored, before anything is uploaded, and every reason the server would refuse it.
export function importPreview(manifest: any, file: FileFacts | null, target: 'character' | 'set'): {rows: [string, string][]; problems: string[]} {
  const problems: string[] = [];
  const rows: [string, string][] = [];
  if (!manifest || typeof manifest !== 'object') return {rows, problems: ['choose the manifest (JSON)']};
  if (!file) problems.push('choose the image file');
  const kinds = target === 'set' ? SET_KINDS : CHARACTER_KINDS;
  if (!kinds.includes(manifest.kind)) problems.push(`kind must be one of ${kinds.join(', ')} (manifest says ${manifest.kind ?? 'nothing'})`);
  if (!/^[0-9a-f]{64}$/.test(manifest.sha256 || '')) problems.push('the manifest has no valid sha256');
  if (file && manifest.sha256 && file.sha256 !== manifest.sha256) problems.push(`the file's sha256 (${file.sha256.slice(0, 16)}…) is not the manifest's (${String(manifest.sha256).slice(0, 16)}…): it would be refused`);
  if (file && file.width && file.height && (file.width !== manifest.width || file.height !== manifest.height))
    problems.push(`the image is ${file.width}×${file.height}, the manifest says ${manifest.width}×${manifest.height}`);
  const g = manifest.generated || {};
  if (!g.at || !g.by) problems.push('the manifest needs generated.at and generated.by (when, and by which route)');
  if (manifest.approved && manifest.rejected) problems.push('approved and rejected are both recorded: at most one decision');
  if (manifest.kind === 'mask' && !manifest.mask) problems.push('a mask needs its mask block (method, script, script_sha256, source_sha256, spec)');
  for (const k of Object.keys(DIMENSIONS)) {
    if (manifest[k] != null && !DIMENSIONS[k].includes(manifest[k])) problems.push(`${DIMENSION_LABEL[k].toLowerCase()} must be one of ${DIMENSIONS[k].join(', ')}`);
  }
  if (target === 'character' && manifest.kind === 'mask' && !manifest.parent_asset_id && !manifest.parent_sha256) problems.push('a mask must name its parent pose');
  if (target === 'set' && !(manifest.label || '').trim()) problems.push('a set needs a label');
  rows.push(['Kind', String(manifest.kind ?? '')]);
  if (target === 'character') {
    rows.push(['Expression', manifest.expressions?.length ? manifest.expressions.join(', ') : (manifest.expression || '—')]);
    rows.push(['Pose dimension', dimensionLabel(manifest)]);
    if (manifest.parent_asset_id || manifest.parent_sha256) rows.push(['Belongs to', manifest.parent_asset_id ? `asset ${manifest.parent_asset_id}` : `the file ${String(manifest.parent_sha256).slice(0, 16)}…`]);
  } else {
    rows.push(['Set', manifest.label || '—']);
    if (manifest.reverse_of) rows.push(['Reverse of', String(manifest.reverse_of)]);
  }
  rows.push(['File', file ? `${file.name}, ${(file.size / 1024 / 1024).toFixed(2)} MB${file.width ? `, ${file.width}×${file.height}` : ''}` : '—']);
  rows.push(['sha256', manifest.sha256 || '—']);
  rows.push(['Generated', `${g.at || '—'} · ${g.by || '—'}`]);
  if (g.session_id) rows.push(['Session', g.session_id]);
  if (g.original_path) rows.push(['Original path', g.original_path]);
  rows.push(['References', String((g.references || []).length)]);
  const noted = recordedDecision(manifest);
  if (noted) rows.push(['Noted in manifest', noted]);
  rows.push(['Stored as', 'a candidate awaiting your decision (never approved by the import)']);
  return {rows, problems};
}

export async function sha256Hex(buf: ArrayBuffer): Promise<string> {
  const d = await globalThis.crypto.subtle.digest('SHA-256', buf);
  return Array.from(new Uint8Array(d)).map(b => b.toString(16).padStart(2, '0')).join('');
}

export function base64Of(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

// The provenance panel's rows (route, prompt file, session, original path, sha256, who imported it and when).
export function provenanceRows(p: any): [string, string][] {
  if (!p) return [];
  const rows: [string, string][] = [];
  const add = (k: string, v: any) => { if (v !== undefined && v !== null && v !== '') rows.push([k, String(v)]); };
  const g = p.generated || {};
  add('Route', g.by);
  add('Generated', g.at);
  add('Method', g.how);
  add('File', p.file_name);
  add('sha256', p.sha256);
  add('Original path', g.original_path);
  add('Session', g.session_id);
  add('Prompt file', g.prompt_file);
  if (p.reviewed) add('Reviewed (manifest)', `${p.reviewed.by}, ${p.reviewed.at}${p.reviewed.notes?.length ? `: ${p.reviewed.notes.join('; ')}` : ''}`);
  add('Decision (manifest)', recordedDecision(p));
  add('Imported', p.imported_at ? `${p.imported_at}${p.imported_by ? ` by ${p.imported_by}` : ''}` : '');
  return rows;
}

// A decision recorded in the manifest (information only: the studio's own decision is the one that counts).
export function recordedDecision(p: any): string {
  const d = p?.approved ? ['approved', p.approved] : p?.rejected ? ['rejected', p.rejected] : null;
  if (!d) return '';
  const [what, x] = d as [string, any];
  return `${what} by ${x.by}, ${x.at}${x.note ? ` (${x.note})` : ''}`;
}
