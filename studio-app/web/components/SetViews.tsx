'use client';
// Set views (feat/set-views): up to four views of the same room. Wide is the set's own picture; speaker, audience and
// two-shot are each drawn from the set's text plus the view's camera words (read from the reference video, editable)
// with the set's own approved wide picture as the reference image. Cost first; nothing generated or approved by itself;
// each view's seats, facing, floor line, desk front and standing area are edited on its picture.
import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from './ui';
import SetStaging from './SetStaging';
import {planLine, viewStatusText, VIEW_LABEL} from '@/lib/setViews';

function ViewCard({sid, eid, v, cost, canGenerate, reload}: {sid: string; eid: number; v: any; cost: string; canGenerate: boolean; reload: () => unknown}) {
  const [words, setWords] = useState(v.camera_words || '');
  const [b, setB] = useState<any>(v.blocking || {});
  useEffect(() => { setWords(v.camera_words || ''); }, [v.camera_words]);
  useEffect(() => { setB(v.blocking || {}); }, [JSON.stringify(v.blocking)]);   // eslint-disable-line react-hooks/exhaustive-deps
  const {busy, error, run} = useAction(reload);
  const dirty = JSON.stringify(b) !== JSON.stringify(v.blocking || {});
  const generate = () => {
    if (!window.confirm(`Draw the ${v.view} view of this set (${cost}) from its text and these camera words, with the set's own wide picture as the reference?`)) return;
    run('gen', async () => {
      if (words.trim() !== (v.camera_words || '')) await api(`/episodes/${eid}/camera-angles`, {method: 'PUT', body: {view: v.view, text: words}});
      await api(`/sets/${sid}/views/${v.view}/generate`, {body: {episode_id: eid}});
    });
  };
  return (
    <div className="card stack small" style={{padding: 10}}>
      <div className="row" style={{gap: 6, flexWrap: 'wrap'}}><strong>{VIEW_LABEL[v.view]}</strong>
        <span className={`badge ${v.status === 'approved' ? 'good' : v.status === 'candidate' ? 'warn' : ''}`}>{viewStatusText(v)}</span></div>
      <ErrorBox error={error} />
      <label>Camera words{v.words_from ? ` (from ${v.words_from})` : ''}
        <textarea rows={3} value={words} onChange={e => setWords(e.target.value)} placeholder="Camera behind the audience, medium shot. In frame: desk, bookcase." /></label>
      {v.url && v.width ? <SetStaging url={v.url} width={v.width} height={v.height} blocking={b} onChange={setB} size={240} /> : null}
      <div className="row" style={{gap: 6, flexWrap: 'wrap'}}>
        <button className="btn sm" disabled={!!busy || !canGenerate || words.trim().length < 10} onClick={generate}>{v.status === 'missing' ? 'Generate' : 'Generate another'} ({cost})</button>
        {v.status === 'candidate' && <>
          <button className="btn sm good" disabled={!!busy} onClick={() => run('ok', () => api(`/sets/${sid}/views/${v.view}/decide`, {body: {decision: 'approve', blocking: b}}))}>Approve</button>
          <button className="btn sm danger" disabled={!!busy} onClick={() => run('no', () => api(`/sets/${sid}/views/${v.view}/decide`, {body: {decision: 'reject'}}))}>Reject</button></>}
        {v.status !== 'missing' && <button className="btn sm" disabled={!!busy || !dirty} onClick={() => run('st', () => api(`/sets/${sid}/views/${v.view}/staging`, {method: 'PUT', body: {blocking: b}}))}>Save the staging</button>}
      </div>
      {v.request_text && <details><summary>The exact request sent to the image API</summary><pre style={{whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', margin: 0}}>{v.request_text}</pre></details>}
    </div>);
}

export default function SetViews({sid, eid}: {sid: string; eid: number}) {
  const {data, error, reload} = useApi<any>(`/sets/${sid}/views?episode=${eid}`, 6000);
  const plan = useApi<any>(`/episodes/${eid}/view-plan`, 15000).data;
  if (!data) return error ? <ErrorBox error={error} /> : null;
  return (
    <details className="stack small" style={{minWidth: 0, overflowWrap: 'anywhere'}}><summary><strong>Views of this room</strong> (wide is this picture; {data.views.filter((v: any) => v.status === 'approved').length} more approved)</summary>
      <span className="muted">Each view is drawn from the set's text plus its camera words, with this set's own approved wide picture as the reference (no video frame or other picture is ever sent). A shot whose view is missing uses the wide view.</span>
      {data.reason && <span className="muted">{data.reason}</span>}
      <div className="stack">{data.views.map((v: any) => <ViewCard key={v.view} sid={sid} eid={eid} v={v} cost={data.cost} canGenerate={data.can_generate} reload={reload} />)}</div>
      {plan?.rows?.length > 0 && <div className="stack"><strong>The view each shot uses</strong>
        <ul style={{margin: 0}}>{plan.rows.map((r: any, i: number) => <li key={i}>{planLine(r)}</li>)}</ul></div>}
    </details>);
}
