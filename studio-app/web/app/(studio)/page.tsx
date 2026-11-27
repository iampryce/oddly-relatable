'use client';
// Episodes (clean dashboard, owner-approved layout 2026-11-25): a new episode from a video in one form, then every
// episode as one line with what it waits for. The old Overview is under Settings › Advanced (/overview).
import Link from 'next/link';
import {useEffect, useRef, useState} from 'react';
import {useRouter} from 'next/navigation';
import {api, isVideoFile, uploadAudio} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import {KEEP_VIDEO_TEXT, videoSeconds} from '@/components/VideoNotesOptions';
import {round1, windowError, windowFrom} from '@/lib/trimWindow';
import {listStatus, money} from '@/lib/dashboard';

const LIMIT = {short: 60, long: 450};          // seconds the episode uses (audio_first.py MAX_SECONDS)
const SHORT_MAX = 180; // a Short runs at most 3 minutes (YouTube Shorts and Reels)
const SOURCE_LIMIT = {short: 1800, long: 450}; // a Short's recording may be longer: the owner picks its window

export default function Episodes() {
  const {data: eps, error, reload} = useApi<any[]>('/episodes', 15000);
  return (
    <>
      <div className="spread"><div><h1>Episodes</h1><p className="sub">Drop a video, press Generate, and decide where the studio asks you.</p></div></div>
      <NewEpisode onCreated={reload} />
      <ErrorBox error={error} />
      <section className="card ep-list" aria-label="Episodes">
        {!eps ? <p className="muted" style={{margin: 0}}>Loading…</p>
          : !eps.length ? <p className="muted" style={{margin: 0}}>No episodes yet. Drop a video above to start one.</p>
          : eps.map(e => <EpisodeRow key={e.id} ep={e} />)}
      </section>
    </>
  );
}

// One line per episode; the workspace says precisely what waits for the owner (read-only, refreshed every minute).
function EpisodeRow({ep}: {ep: any}) {
  const live = ep.stage !== 'published';
  const {data: ws} = useApi<any>(live ? `/episodes/${ep.id}/workspace` : null, 60000);
  const st = listStatus(ep, ws || undefined);
  return (
    <Link href={`/episodes/${ep.id}`} className="ep-row">
      <span className="ep-title">{ep.title}<span className="muted small"> · {ep.format === 'long' ? 'YouTube long' : 'Short'}</span></span>
      <span className={`ep-status ${st.tone}`}><span aria-hidden>{st.icon}</span> {st.text}</span>
    </Link>);
}

// The new-episode form: a video (or audio) file, a title, the format and the rights the server requires; Generate
// creates the episode and uploads the file. The video notes are a PAID vision call: off unless ticked, with the
// estimate shown next to the box before anything is sent.
function NewEpisode({onCreated}: {onCreated: () => unknown}) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [over, setOver] = useState(false);
  const [title, setTitle] = useState('');
  const [format, setFormat] = useState<'long' | 'short'>('long');
  const [source, setSource] = useState('');
  const [rights, setRights] = useState(false);
  const [notes, setNotes] = useState(false);
  const [keep, setKeep] = useState(true);   // keep the video privately for the guided steps: on unless the owner unticks it
  const [duration, setDuration] = useState<number | null>(null);
  const [win, setWin] = useState({start: 0, end: 60});
  const [est, setEst] = useState<any>(null);
  const {busy, error, run} = useAction(onCreated);
  const video = isVideoFile(file);
  useEffect(() => {
    setDuration(null);
    if (!file) return;
    if (!title) setTitle(file.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').slice(0, 120));
    if (video) videoSeconds(file).then(d => { setDuration(d); setWin(windowFrom(0, d, 60)); });
  }, [file]);   // eslint-disable-line react-hooks/exhaustive-deps
  const needsWindow = notes && video && format === 'short' && duration != null && duration > SHORT_MAX + 0.5;
  const winErr = needsWindow ? windowError(win.start, win.end, duration, 60) : null;
  const tooLong = duration != null && duration > SOURCE_LIMIT[format] + 0.5;
  const seconds = needsWindow ? Math.max(0, win.end - win.start) : Math.min(duration ?? LIMIT[format], LIMIT[format]);
  useEffect(() => {
    if (!notes || !video) { setEst(null); return; }
    let alive = true;
    api(`/audio/video-notes/estimate?seconds=${round1(seconds)}&format=${format}`).then(e => { if (alive) setEst(e); }).catch(() => alive && setEst(null));
    return () => { alive = false; };
  }, [notes, video, seconds, format]);
  const notesOk = !notes || (!!est?.configured && est.within_cap !== false && !winErr);
  const ready = !!file && !!title.trim() && !!source && rights && notesOk && !tooLong;
  const pick = (f: File | null | undefined) => { if (f) setFile(f); };
  const generate = () => run('create', async () => {
    const ep = await api('/audio-episodes', {body: {title: title.trim(), format, rights_confirmed: rights, rights_source: source}});
    // a YouTube long episode is drawn and rendered 16:9 (1920x1080); a Short keeps the full 9:16 frame
    if (format === 'long') await api(`/episodes/${ep.id}/layout`, {method: 'PUT', body: {value: 'landscape'}});
    await uploadAudio(`/episodes/${ep.id}/audio`, file!, {hints: notes && video, window: needsWindow && !winErr ? win : null, keepVideo: keep && video});
    router.push(`/episodes/${ep.id}`);
  });
  return (
    <section className="card new-ep" aria-label="New episode">
      <h2>+ New episode</h2>
      <ErrorBox error={error} />
      <div className="new-ep-grid">
        <div className={`drop${over ? ' over' : ''}${file ? ' has' : ''}`} role="button" tabIndex={0}
          onClick={() => input.current?.click()} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.current?.click(); } }}
          onDragOver={e => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
          onDrop={e => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files?.[0]); }}>
          {file ? <><strong>{file.name}</strong><span className="muted small">{(file.size / 1048576).toFixed(1)} MB{duration ? ` · ${round1(duration)} s` : ''} · click to change</span></>
            : <><strong>Drop your video here</strong><span className="muted small">or click to choose (video up to 250 MB, or audio up to 60 MB)</span></>}
          <input ref={input} type="file" accept="video/*,audio/*" hidden onChange={e => pick(e.target.files?.[0])} />
        </div>
        <div className="stack">
          <div><label htmlFor="ne-title">Title</label><input id="ne-title" value={title} maxLength={200} onChange={e => setTitle(e.target.value)} /></div>
          <div role="radiogroup" aria-label="Format" className="seg">
            {([['long', 'YouTube long 16:9'], ['short', 'Short 9:16']] as const).map(([v, l]) => (
              <button key={v} type="button" role="radio" aria-checked={format === v} className={format === v ? 'on' : ''} onClick={() => setFormat(v)}>{l}</button>))}
          </div>
          <div><label htmlFor="ne-source">The recording is</label>
            <select id="ne-source" value={source} onChange={e => setSource(e.target.value)}>
              <option value="">Choose…</option><option value="own_recording">My own recording</option><option value="licensed">Licensed</option>
              <option value="voice_actor">Recorded for me by a voice actor</option><option value="other">Other</option></select></div>
          <label className="check"><input type="checkbox" checked={rights} onChange={e => setRights(e.target.checked)} />I have the right to use this recording (its audio and any video it came with)</label>
          {video && <label className="check"><input type="checkbox" checked={keep} onChange={e => setKeep(e.target.checked)} />
            {KEEP_VIDEO_TEXT}. Free.</label>}
          {video && <label className="check"><input type="checkbox" checked={notes} onChange={e => setNotes(e.target.checked)} />
            Analyse the video for staging notes (paid: {est?.configured ? `about ${money(est.usd)}` : 'cost shown when ticked'})</label>}
        </div>
      </div>
      {needsWindow && <div className="row small" style={{marginTop: 8}}>
        The video runs {round1(duration!)} s: the Short's window of up to {SHORT_MAX / 60} minutes (only this part is analysed)
        <label className="row small" style={{margin: 0}}>from <input type="number" min={0} step={0.1} style={{width: 90}} value={win.start} onChange={e => setWin({...win, start: Number(e.target.value)})} /></label>
        <label className="row small" style={{margin: 0}}>to <input type="number" min={0} step={0.1} style={{width: 90}} value={win.end} onChange={e => setWin({...win, end: Number(e.target.value)})} /></label></div>}
      {winErr && <p className="small bad">{winErr}</p>}
      {notes && est && !est.configured && <p className="small bad">{est.message}</p>}
      {notes && est?.within_cap === false && <p className="small bad">About {money(est.usd)}: over the {money(est.cap_usd)} cap per episode. Use a shorter part, or raise the cap in Settings.</p>}
      {tooLong && <p className="small bad">The recording runs {round1(duration!)} s; a {format === 'long' ? 'long episode' : 'Short'} allows at most {SOURCE_LIMIT[format]} s.</p>}
      <div className="spread" style={{marginTop: 12}}>
        <span className="muted small">Generate creates the episode, uploads the file and transcribes it. It then stops at each of your decisions; paid steps wait for their own button. The episode page then shows the next guided step (Cast from video is step 4).</span>
        <button className="btn primary" disabled={!ready || !!busy} onClick={generate}>{busy ? 'Uploading…' : 'Generate'}</button>
      </div>
    </section>);
}
