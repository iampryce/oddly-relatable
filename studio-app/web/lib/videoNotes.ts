// The video notes' allowed values (the same lists as the server's video_notes.py) and a readable line per range.
export const NOTE_SHOTS = ['wide', 'medium', 'close'];
export const NOTE_CAMERA = ['static', 'pan', 'tilt', 'zoom in', 'zoom out', 'handheld', 'tracking'];
export const NOTE_SETTINGS = ['office', 'meeting room', 'kitchen', 'living room', 'bedroom', 'bathroom', 'hallway', 'dining room',
  'restaurant', 'cafe', 'bar', 'shop', 'supermarket', 'street', 'car', 'bus', 'train', 'park', 'garden', 'beach', 'school',
  'classroom', 'hospital', 'gym', 'stage', 'studio', 'lobby', 'elevator', 'outdoors', 'indoors', 'other'];

export const NOTE_FURNITURE = ['long table', 'round table', 'desk', 'sofa', 'counter', 'bed', 'bench', 'none'];
export const NOTE_TIME = ['daytime', 'evening', 'night'];
export const NOTE_POSITIONS = ['left', 'center', 'right', 'background'];
export const NOTE_POSES = ['standing', 'seated', 'walking', 'leaning', 'lying', 'kneeling'];
export const NOTE_FACING = ['camera', 'away', 'left', 'right', 'speaker', ...Array.from({length: 9}, (_, i) => `reactor ${i + 1}`)];
export const NOTE_EMOTIONS = ['neutral', 'calm', 'happy', 'amused', 'laughing', 'excited', 'proud', 'smug', 'surprised', 'shocked',
  'confused', 'curious', 'worried', 'nervous', 'anxious', 'scared', 'sad', 'disappointed', 'embarrassed', 'awkward', 'annoyed',
  'irritated', 'frustrated', 'angry', 'bored', 'tired', 'skeptical', 'pleading', 'relieved', 'determined', 'serious', 'deadpan'];

export type NoteRole = {role: string; position?: string; pose?: string; facing?: string; emotion?: string};
export type NoteRange = {start: number; end: number; shot?: string; camera?: string; setting?: string; furniture?: string; time?: string;
  roles?: NoteRole[]; line_ids?: string[]};
export type RangeKey = 'shot' | 'camera' | 'setting' | 'furniture' | 'time';
export type RoleKey = 'position' | 'pose' | 'facing' | 'emotion';

export function describeRoles(roles: NoteRole[] = []): string {
  return roles.map(r => {
    const bits = [r.position, r.pose, r.facing ? `facing ${r.facing}` : '', r.emotion].filter(Boolean);
    return bits.length ? `${r.role}: ${bits.join(', ')}` : r.role;
  }).join(' · ');
}

// A field of one range set (or removed with an empty value); the line ids are the server's view and are not sent back.
export function setField(ranges: NoteRange[], i: number, key: RangeKey, value: string): NoteRange[] {
  return ranges.map((r, k) => {
    if (k !== i) return r;
    const {[key]: _old, ...rest} = r;
    return value ? {...rest, [key]: value} : rest;
  });
}
// One role's field set (or removed with an empty value).
export function setRoleField(ranges: NoteRange[], i: number, j: number, key: RoleKey, value: string): NoteRange[] {
  return ranges.map((r, k) => k !== i ? r : {...r, roles: (r.roles || []).map((ro, m) => {
    if (m !== j) return ro;
    const {[key]: _old, ...rest} = ro;
    return value ? {...rest, [key]: value} : rest;
  })});
}
export const forServer = (ranges: NoteRange[]) => ranges.map(({line_ids, ...r}) => r);
