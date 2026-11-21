// The video notes' allowed values (the same lists as the server's video_notes.py) and a readable line per range.
export const NOTE_SHOTS = ['wide', 'medium', 'close'];
export const NOTE_CAMERA = ['static', 'pan', 'tilt', 'zoom in', 'zoom out', 'handheld', 'tracking'];
export const NOTE_SETTINGS = ['office', 'meeting room', 'kitchen', 'living room', 'bedroom', 'bathroom', 'hallway', 'dining room',
  'restaurant', 'cafe', 'bar', 'shop', 'supermarket', 'street', 'car', 'bus', 'train', 'park', 'garden', 'beach', 'school',
  'classroom', 'hospital', 'gym', 'stage', 'studio', 'lobby', 'elevator', 'outdoors', 'indoors', 'other'];

export type NoteRole = {role: string; position?: string; pose?: string; facing?: string; emotion?: string};
export type NoteRange = {start: number; end: number; shot?: string; camera?: string; setting?: string; roles?: NoteRole[]; line_ids?: string[]};

export function describeRoles(roles: NoteRole[] = []): string {
  return roles.map(r => {
    const bits = [r.position, r.pose, r.facing ? `facing ${r.facing}` : '', r.emotion].filter(Boolean);
    return bits.length ? `${r.role}: ${bits.join(', ')}` : r.role;
  }).join(' · ');
}

// A field of one range set (or removed with an empty value); the line ids are the server's view and are not sent back.
export function setField(ranges: NoteRange[], i: number, key: 'shot' | 'camera' | 'setting', value: string): NoteRange[] {
  return ranges.map((r, k) => {
    if (k !== i) return r;
    const {[key]: _old, ...rest} = r;
    return value ? {...rest, [key]: value} : rest;
  });
}
export const forServer = (ranges: NoteRange[]) => ranges.map(({line_ids, ...r}) => r);
