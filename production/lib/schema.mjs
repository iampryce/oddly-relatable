// Shared validation helpers for the AP-86 data models (S1). Every check throws an Error whose message starts with
// where the problem is ("set bar-01 plate wide mark stool-1: ..."), so authors can find it. Nothing here reads files.
//
// Identifier rules match the existing cast rules (lowercase, digits, hyphens). Anchor and tag names may use
// camelCase (e.g. "handRight"), matching the existing "feet" anchor.

export const ID = /^[a-z0-9][a-z0-9-]{0,63}$/;
export const NAME = /^[a-z][a-zA-Z0-9]{0,63}$/;
export const SHA256 = /^[0-9a-f]{64}$/;

export const fail = (where, msg) => { throw new Error(`${where}: ${msg}`); };
export const isObject = v => v !== null && typeof v === 'object' && !Array.isArray(v);

export function object(v, where, what = 'an object') {
  if (!isObject(v)) fail(where, `must be ${what}`);
  return v;
}
export function onlyKeys(o, allowed, where) {
  for (const k of Object.keys(o)) if (!allowed.includes(k)) fail(where, `unknown field "${k}" (allowed: ${allowed.join(', ')})`);
  return o;
}
export function id(v, where) {
  if (typeof v !== 'string' || !ID.test(v)) fail(where, `"${v}" is not a valid identifier (lowercase letters, digits and hyphens)`);
  return v;
}
export function name(v, where) {
  if (typeof v !== 'string' || !NAME.test(v)) fail(where, `"${v}" is not a valid name (a letter, then letters and digits, e.g. "handRight")`);
  return v;
}
export function finite(v, where, {min = -Infinity, max = Infinity, exclusiveMin = false} = {}) {
  if (!Number.isFinite(v) || v > max || (exclusiveMin ? v <= min : v < min)) fail(where, `must be a number ${exclusiveMin ? '>' : '>='} ${min}${Number.isFinite(max) ? ` and <= ${max}` : ''} (got ${JSON.stringify(v)})`);
  return v;
}
// Plate coordinates are fractions of the plate (0 to 1), independent of any output size.
export const fraction = (v, where) => finite(v, where, {min: 0, max: 1});
export function point01(p, where) {
  object(p, where, 'a point {x, y} in plate fractions (0 to 1)');
  onlyKeys(p, ['x', 'y'], where);
  fraction(p.x, `${where}.x`); fraction(p.y, `${where}.y`);
  return p;
}
// Image-pixel points (anchors in artwork), like the existing "feet" anchor.
export function pixelPoint(p, where) {
  object(p, where, 'a point {x, y} in image pixels');
  onlyKeys(p, ['x', 'y'], where);
  finite(p.x, `${where}.x`, {min: 0}); finite(p.y, `${where}.y`, {min: 0});
  return p;
}
// A file reference: a repository-relative path and an optional SHA-256 that loaders verify.
export function asset(a, where) {
  object(a, where, 'an asset {file, sha256?}');
  onlyKeys(a, ['file', 'sha256', 'note'], where);
  if (typeof a.file !== 'string' || !a.file || /^([a-zA-Z]:|[\\/])/.test(a.file) || a.file.split(/[\\/]/).includes('..')) fail(`${where}.file`, 'must be a repository-relative path without ".."');
  if (a.sha256 !== undefined && (typeof a.sha256 !== 'string' || !SHA256.test(a.sha256))) fail(`${where}.sha256`, 'must be 64 lowercase hex characters');
  return a;
}
export function idMap(m, where, each) {
  object(m, where, 'an object keyed by identifier');
  for (const [k, v] of Object.entries(m)) each(id(k, `${where} key`), v, `${where} ${k}`);
  return m;
}
export function schemaVersion(v, supported, where) {
  if (!supported.includes(v)) fail(where, `unsupported schemaVersion ${JSON.stringify(v)} (supported: ${supported.map(s => s === undefined ? 'absent' : s).join(', ')})`);
  return v;
}
