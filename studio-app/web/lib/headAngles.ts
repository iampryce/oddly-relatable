// Head angles (feat/3d-rig PR 1): the words the Characters page uses. Pure; node --test.
export function angleLabel(a: string): string {
  return ({'three-quarter': 'three-quarter', side: 'side', back: 'back'} as Record<string, string>)[a] || a;
}

export function angleStatusText(r: {status: string; review?: unknown[]}): string {
  if (r.status === 'approved') return 'approved (used by the 3D rig)';
  if (r.status === 'review') return `${(r.review || []).length} to review; mock in use`;
  return 'mock in use';
}
