'use client';
// The studio switcher (docs/studios.md): Stick Man Studio is the only choice that can be selected; the other two are
// shown, disabled, until its unlock gates pass. Nothing is stored and nothing routes yet.
import {ACTIVE_STUDIO, LOCKED_NOTE, STUDIOS} from '@/lib/studios';

export default function StudioSwitcher() {
  return (
    <select className="studio-switch" aria-label="Studio" value={ACTIVE_STUDIO} onChange={() => {}} title="Studio">
      {STUDIOS.map(s => (
        <option key={s.id} value={s.id} disabled={s.locked} title={s.locked ? LOCKED_NOTE : undefined}>
          {s.locked ? `${s.label} (locked)` : s.label}
        </option>
      ))}
    </select>
  );
}
