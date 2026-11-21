'use client';
// "Reference, not copy" (owner decision 2026-11-21): the video notes option for a video upload. The video is only used
// for its sound; with notes ticked, a few frames of the part the episode uses are read ONCE by the studio's vision
// provider and turned into text-only staging notes (shot, anonymous roles, blocking, emotions, setting, camera); the
// frames and the video are deleted right after. A Short longer than 60 s needs its window now, so only that part is
// analysed. The cost estimate shows before anything is sent.
import {useEffect, useState} from 'react';
import {api, isVideoFile} from '@/lib/api';
import {round1, windowError, windowFrom} from '@/lib/trimWindow';

export type NotesChoice = {notes: boolean; window: {start: number; end: number} | null; ready: boolean};

function videoSeconds(file: File): Promise<number | null> {
  return new Promise(resolve => {
    const v = document.createElement('video');
    const url = URL.createObjectURL(file);
    v.preload = 'metadata';
    v.onloadedmetadata = () => { URL.revokeObjectURL(url); resolve(Number.isFinite(v.duration) ? v.duration : null); };
    v.onerror = () => { URL.revokeObjectURL(url); resolve(null); };
    v.src = url;
  });
}

export default function VideoNotesOptions({file, format, onChange}: {file: File | null; format: string; onChange: (c: NotesChoice) => void}) {
  const video = isVideoFile(file);
  const [notes, setNotes] = useState(false);
  const [duration, setDuration] = useState<number | null>(null);
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState(60);
  const [est, setEst] = useState<any>(null);
  useEffect(() => {
    setDuration(null);
    if (file && video) videoSeconds(file).then(d => { setDuration(d); const w = windowFrom(0, d, 60); setStart(w.start); setEnd(w.end); });
  }, [file, video]);
  const needsWindow = notes && format === 'short' && duration != null && duration > 60.5;
  const err = needsWindow ? windowError(start, end, duration, 60) : null;
  const seconds = needsWindow ? Math.max(0, end - start) : Math.min(duration ?? 60, format === 'short' ? 60 : 450);
  useEffect(() => {
    if (!notes || !video) { setEst(null); return; }
    let live = true;
    api(`/audio/video-notes/estimate?seconds=${round1(seconds)}&format=${format}`).then(e => { if (live) setEst(e); }).catch(() => live && setEst(null));
    return () => { live = false; };
  }, [notes, video, seconds, format]);
  const ready = !notes || (!!est?.configured && !err);
  useEffect(() => { onChange({notes: notes && video, window: needsWindow && !err ? {start, end} : null, ready}); },
            [notes, video, needsWindow, err, start, end, ready]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!video) return null;
  return (
    <div className="stack">
      <label className="row" style={{fontWeight: 400, color: 'inherit'}}>
        <input type="checkbox" style={{width: 'auto'}} checked={notes} onChange={e => setNotes(e.target.checked)} />
        Use the video as a reference for staging notes (text only: shots, who reacts, where people stand, emotions, the kind of place, camera moves; nobody is named or described). The scene writer may use them as suggestions; your characters, sets and dialogue stay your own. The frames are read once and deleted with the video.
      </label>
      {needsWindow && <div className="row" style={{flexWrap: 'wrap'}}>
        <span className="small">The video runs {round1(duration!)} s. Choose the Short's 60 s window now, so only that part is analysed:</span>
        <label className="row small">Start (s) <input type="number" min={0} step={0.1} style={{width: 90}} value={start} onChange={e => setStart(Number(e.target.value))} /></label>
        <label className="row small">End (s) <input type="number" min={0} step={0.1} style={{width: 90}} value={end} onChange={e => setEnd(Number(e.target.value))} /></label>
        <span className="muted small">{round1(end - start)} s</span>
      </div>}
      {err && <p className="small" style={{color: 'var(--bad, #b00)'}}>{err}</p>}
      {notes && est && (est.configured
        ? <p className={`small ${est.within_cap === false ? 'alert bad' : 'muted'}`}>Notes from {est.frames} frame(s) in {est.calls} call(s) · estimated cost about ${est.usd < 0.01 ? est.usd.toFixed(4) : est.usd.toFixed(3)} ({est.provider} {est.model}){est.note ? ` · ${est.note}` : ''} · cap ${Number(est.cap_usd ?? 0.5).toFixed(2)} per episode{est.within_cap === false ? ': over the cap, so the upload with notes will be refused (use a shorter part, or raise the cap in Settings › Video and visual analysis)' : ''}. The actual token use is recorded with the notes.</p>
        : <p className="small" style={{color: 'var(--bad, #b00)'}}>{est.message}</p>)}
    </div>
  );
}
