'use client';
// The episode's set panel (feat/episode-workspace): every set made for this episode as a large picture with its status
// and cost; Approve, Reject, Generate another and Keep for future episodes; the seats, desk front, floor and standing
// lines edited on the picture (candidates and approved sets); the seats a vision model suggested from the picture
// (the speaker's seat behind the desk with the desk front marked, the others in the audience row), shown for you to
// adjust; "N seats for M people". The set jobs (with their errors) show at the top of the Set section. Nothing is
// approved for you.
import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from './ui';
import SetStaging from './SetStaging';
import {candidateCost, seatsLine, statusTone} from '@/lib/workspace';
import {spacingWarnings} from '@/lib/setStaging';

// Seats closer than one head width at the smallest cast height: a warning with the numbers (never a refusal).
export function SpacingWarning({seats, need, minHeight}: {seats: any[]; need: number; minHeight?: number}) {
  const w = spacingWarnings(seats, need);
  if (!w.length) return null;
  return <div className="alert warn small" role="status"><strong>Seats too close for the cast's heads:</strong> {w.map(x => x.text).join('; ')}.
    {' '}Their heads will overlap even at the smallest cast height{minHeight ? ` (${minHeight} px)` : ''}: move the seats apart on the picture, mark fewer seats, or keep them as they are.</div>;
}

// the picture's width: 360 px, narrower on a phone so the card never scrolls sideways
function usePictureWidth(): number {
  const [w, setW] = useState(360);
  useEffect(() => {
    const fit = () => setW(Math.max(200, Math.min(360, window.innerWidth - 100)));
    fit();
    window.addEventListener('resize', fit);
    return () => window.removeEventListener('resize', fit);
  }, []);
  return w;
}

function SetCard({ep, x, data, reload}: {ep: any; x: any; data: any; reload: () => unknown}) {
  const pictureWidth = usePictureWidth();
  const [b, setB] = useState<any>(x.blocking);
  const saved = JSON.stringify(x.blocking);
  useEffect(() => { setB(x.blocking); }, [saved]);   // eslint-disable-line react-hooks/exhaustive-deps
  const {busy, error, run} = useAction(reload);
  const locked = ['producing', 'publishing'].includes(ep.stage);
  const dirty = JSON.stringify(b) !== saved;
  const seats = (b.seats || (b.seat ? [b.seat] : [])).length;
  const line = seatsLine(seats, x.people);
  const sc = data.suggest_cost || {};
  const again = () => {
    if (!window.confirm(`Generate another candidate from exactly the same request (${data.image_cost}${sc.usd != null ? `, plus about $${sc.usd.toFixed(3)} for the suggested seats` : ''})?`)) return;
    run('again', () => api(`/episodes/${ep.id}/set-proposal/generate`, {body: {again_of: x.id}}));
  };
  const suggest = () => {
    if (!sc.configured) return;
    if (!window.confirm(`Ask the vision model (${sc.provider}) for suggested seats on this picture: about $${sc.usd.toFixed(3)} (cap $${Number(sc.cap_usd).toFixed(2)})?`)) return;
    run('suggest', () => api(`/sets/${x.id}/suggest-seats`, {method: 'POST'}));
  };
  return (
    <div className="card stack" style={{padding: 12, outline: x.chosen ? '2px solid var(--accent, #36c)' : undefined}}>
      <div className="row" style={{gap: 8, flexWrap: 'wrap'}}>
        <strong>{x.label}</strong>
        <span className={`badge ${statusTone(x.status)}`}>{x.status}</span>
        {x.chosen && <span className="badge good">this episode's set</span>}
        {x.view && <span className="badge">{x.view}</span>}
        <span className={`badge ${line.short ? 'warn' : ''}`}>{line.text}</span>
        <span className="muted small">{candidateCost(x)}</span>
      </div>
      <ErrorBox error={error} />
      {x.url && x.width ? <SetStaging url={x.url} width={x.width} height={x.height} blocking={b} onChange={setB} size={pictureWidth} />
        : <div className="card empty small">No picture</div>}
      <SpacingWarning seats={b.seats || (b.seat ? [b.seat] : [])} need={data.min_head_px} minHeight={data.min_height} />
      {x.suggested && <div className="small">
        <strong>Suggested by the vision model:</strong> {x.suggested.summary}{x.suggested.spacing?.length ? ` (close seats: ${x.suggested.spacing.map((w: any) => `${w.seats[0]} and ${w.seats[1]}, ${w.gap} px apart`).join("; ")})` : ""}{x.staging_edited ? ' (your edits are kept; the suggestion is not applied by itself)' : ''}
        {' '}<button className="btn sm" disabled={locked || !!busy} onClick={() => setB({...b, ...x.suggested.blocking})}>Use the suggestion</button></div>}
      {x.suggest_error && <div className="alert warn small">No suggested seats: {x.suggest_error}</div>}
      <div className="row" style={{gap: 6, flexWrap: 'wrap'}}>
        {x.status === 'candidate' && <>
          <button className="btn good" disabled={locked || !!busy} onClick={() => run('ok', () => api(`/sets/${x.id}/decide`, {body: {decision: 'approve', blocking: b}}))}>Approve{dirty ? ' with this staging' : ''}</button>
          <button className="btn danger" disabled={locked || !!busy} onClick={() => run('no', () => api(`/sets/${x.id}/decide`, {body: {decision: 'reject'}}))}>Reject</button></>}
        {x.status !== 'rejected' && <button className="btn" disabled={locked || !!busy || !dirty} onClick={() => run('staging', () => api(`/sets/${x.id}/staging`, {method: 'PUT', body: {blocking: b}}))}>Save the staging</button>}
        {dirty && <button className="btn" disabled={!!busy} onClick={() => setB(x.blocking)}>Undo</button>}
        {x.status === 'approved' && !x.chosen && <button className="btn primary" disabled={locked || !!busy}
          onClick={() => run('use', () => api(`/episodes/${ep.id}/set`, {method: 'PUT', body: {set_id: x.id}}))}>Use for this episode</button>}
        {x.for_this_episode && x.request && <button className="btn" disabled={locked || !!busy} onClick={again}>Generate another ({data.image_cost})</button>}
        {x.status !== 'rejected' && <button className="btn" disabled={locked || !!busy || !sc.configured || sc.within_cap === false}
          title={sc.configured ? '' : sc.message} onClick={suggest}>Suggest seats again{sc.usd != null ? ` (about $${sc.usd.toFixed(3)})` : ''}</button>}
      </div>
      {x.status !== 'rejected' && <label className="small row" style={{gap: 4}}><input type="checkbox" checked={!!x.kept} disabled={!!busy}
        onChange={e => run('keep', () => api(`/sets/${x.id}/keep`, {method: 'POST', body: {keep: e.target.checked}}))} />Keep for future episodes</label>}
      {x.request_text && <details><summary className="small">The exact request sent to the image API</summary>
        <pre className="small" style={{whiteSpace: 'pre-wrap', margin: 0}}>{x.request_text}</pre></details>}
    </div>);
}

export default function SetPanel({ep, onChange}: {ep: any; onChange?: () => unknown}) {
  const {data, error, reload} = useApi<any>(`/episodes/${ep.id}/set-panel`, 5000);
  const refresh = async () => { await reload(); await onChange?.(); };
  if (!data) return error ? <ErrorBox error={error} /> : null;
  return (
    <div className="stack">
      <strong>This episode's sets</strong>
      {!data.sets.length && <p className="muted small">No set made for this episode yet: write or propose the description below, then generate it.</p>}
      <div className="grid cols-2">{data.sets.map((x: any) => <SetCard key={`${x.id}-${x.status}`} ep={ep} x={x} data={data} reload={refresh} />)}</div>
    </div>);
}
