'use client';
// Import of local generations (asset_import.py): the upload panel (shows what will be stored first), the imported assets
// of a character with their pose dimension and provenance, and the provenance panel shared with Settings > Sets.
import {useState} from 'react';
import {api} from '@/lib/api';
import {useAction} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import {DIMENSIONS, DIMENSION_LABEL, base64Of, dimensionLabel, importPreview, importedAssets, provenanceRows, recordedDecision, sha256Hex, type FileFacts} from '@/lib/assetImport';

async function imageSize(file: File): Promise<{width?: number; height?: number}> {
  try { const b = await createImageBitmap(file); const r = {width: b.width, height: b.height}; b.close(); return r; }
  catch { return {}; }
}

export function ImportPanel({target, characterId, onDone}: {target: 'character' | 'set'; characterId?: number; onDone: () => unknown}) {
  const [file, setFile] = useState<File | null>(null);
  const [facts, setFacts] = useState<FileFacts | null>(null);
  const [manifest, setManifest] = useState<any>(null);
  const [manifestError, setManifestError] = useState('');
  const [result, setResult] = useState('');
  const {busy, error, run} = useAction(onDone);
  const pickFile = async (f?: File) => {
    setResult(''); setFile(f || null); setFacts(null);
    if (!f) return;
    const buf = await f.arrayBuffer();
    setFacts({name: f.name, size: f.size, sha256: await sha256Hex(buf), ...(await imageSize(f))});
  };
  const pickManifest = async (f?: File) => {
    setResult(''); setManifest(null); setManifestError('');
    if (!f) return;
    try { setManifest(JSON.parse(await f.text())); } catch { setManifestError('the manifest is not valid JSON'); }
  };
  const preview = manifest ? importPreview(manifest, facts, target) : null;
  const upload = () => run('import', async () => {
    const body = {file_base64: base64Of(await file!.arrayBuffer()), manifest};
    if (target === 'set') {
      const r: any = await api('/sets/import', {body});
      setResult(`Imported as the set candidate ${r.id}: approve or reject it below with its staging.`);
    } else {
      const r: any = await api(`/characters/${characterId}/import`, {body});
      setResult(`Imported as candidate asset ${r.asset_id}: decide it in the Imported list.`);
    }
    setFile(null); setFacts(null); setManifest(null);
  });
  const id = `${target}-${characterId ?? 'sets'}-import`;
  return (
    <details className="card stack small" style={{background: 'var(--panel, transparent)'}}>
      <summary><strong>Import local generation</strong> <span className="muted">image + manifest; stored unchanged as a candidate</span></summary>
      <div className="grid cols-2">
        <div><label htmlFor={`${id}-file`}>Image (PNG or JPEG)</label><input id={`${id}-file`} type="file" accept="image/png,image/jpeg" onChange={e => pickFile(e.target.files?.[0])} /></div>
        <div><label htmlFor={`${id}-manifest`}>Manifest (JSON)</label><input id={`${id}-manifest`} type="file" accept="application/json,.json" onChange={e => pickManifest(e.target.files?.[0])} /></div>
      </div>
      <ErrorBox error={manifestError || error} />
      {preview && <>
        <table className="small"><tbody>{preview.rows.map(([k, v]) => <tr key={k}><th style={{textAlign: 'left', paddingRight: 12, whiteSpace: 'nowrap'}}>{k}</th><td className={k === 'sha256' || k === 'Original path' ? 'mono' : ''} style={{wordBreak: 'break-all'}}>{v}</td></tr>)}</tbody></table>
        {preview.problems.map(p => <div key={p} className="alert warn">{p}</div>)}
        <div className="row"><button className="btn primary" disabled={!!busy || !file || preview.problems.length > 0} onClick={upload}>{busy ? 'Uploading…' : 'Upload as candidate'}</button>
          <span className="muted">The server checks the sha256 again. Nothing is approved by an import.</span></div></>}
      {result && <div className="alert good" role="status">{result}</div>}
    </details>);
}

export function ProvenancePanel({assetId, provenance}: {assetId?: number; provenance?: any}) {
  // a set record carries its whole provenance; a character asset carries a summary and loads the rest when opened
  const [full, setFull] = useState<any>(provenance && provenance.generated?.prompt !== undefined ? provenance : null);
  const [err, setErr] = useState('');
  const load = () => {
    if (full || assetId == null) return;
    api(`/character-assets/${assetId}/provenance`).then((r: any) => setFull(r.provenance)).catch(e => setErr(e.message));
  };
  const p = full || provenance;
  return (
    <details className="small" onToggle={e => { if ((e.target as HTMLDetailsElement).open) load(); }}>
      <summary>Provenance</summary>
      <ErrorBox error={err} />
      <table><tbody>{provenanceRows(p).map(([k, v]) => <tr key={k}><th style={{textAlign: 'left', paddingRight: 10, whiteSpace: 'nowrap'}}>{k}</th><td className={k === 'sha256' || k === 'Original path' ? 'mono' : ''} style={{wordBreak: 'break-all'}}>{v}</td></tr>)}</tbody></table>
      {full?.generated?.references?.length > 0 && <><strong>References</strong>
        <ul style={{margin: '4px 0', paddingLeft: 18}}>{full.generated.references.map((r: any, i: number) => <li key={i}>{r.role || r.file}{r.file && r.role ? ` (${r.file})` : ''} <span className="mono muted" style={{wordBreak: 'break-all'}}>{r.sha256}</span></li>)}</ul></>}
      {full?.notes?.length > 0 && <ul style={{margin: '4px 0', paddingLeft: 18}}>{full.notes.map((n: string, i: number) => <li key={i}>{n}</li>)}</ul>}
      {full?.mask && <details><summary>Mask polygon spec</summary><pre className="small" style={{whiteSpace: 'pre-wrap'}}>{JSON.stringify(full.mask, null, 1)}</pre></details>}
      {full?.generated?.prompt && <details><summary>Prompt</summary><pre className="small" style={{whiteSpace: 'pre-wrap'}}>{full.generated.prompt}</pre></details>}
      {!full && assetId != null && !err && <span className="muted">Loading…</span>}
    </details>);
}

function DimensionSelects({a, onSave, busy}: {a: any; onSave: (d: any) => void; busy: boolean}) {
  const [d, setD] = useState<any>({posture: a.posture, body_turn: a.body_turn, view: a.view, framing: a.framing});
  const changed = Object.keys(DIMENSIONS).some(k => (d[k] || null) !== (a[k] || null));
  return (
    <div className="row small" style={{gap: 4, flexWrap: 'wrap', justifyContent: 'center'}}>
      {Object.keys(DIMENSIONS).map(k => (
        <select key={k} aria-label={DIMENSION_LABEL[k]} value={d[k] || ''} onChange={e => setD({...d, [k]: e.target.value || null})}>
          <option value="">{DIMENSION_LABEL[k]}: default</option>
          {DIMENSIONS[k].map(v => <option key={v} value={v}>{v.replace('_', '-')}</option>)}
        </select>))}
      {changed && <button className="btn sm" disabled={busy} onClick={() => onSave(d)}>Save dimension</button>}
    </div>);
}

// The character's imported assets: Imported badge, kind, pose dimension (editable while a candidate), provenance, and
// the existing one-by-one decision (approve / reject).
export function ImportedAssets({c, reload}: {c: any; reload: () => unknown}) {
  const act = useAction(reload);
  const list = importedAssets(c.assets);
  if (!list.length) return null;
  const pending = list.filter(a => a.status === 'review').length;
  return (
    <div className="stack">
      <strong className="small">Imported assets <span className="muted">({list.length}{pending ? `, ${pending} awaiting your decision` : ''})</span></strong>
      <ErrorBox error={act.error} />
      <div className="poses">{list.map((a: any) => (
        <div key={a.id} className="pose" style={a.parent_asset_id ? {borderLeft: '3px solid var(--line, #ccc)'} : undefined}>
          <a href={a.url} target="_blank" rel="noreferrer"><img src={a.url} alt={`${c.name} ${a.kind} ${a.expression}`} loading="lazy"
            style={a.kind === 'mask' ? {background: 'repeating-conic-gradient(#ddd 0% 25%, #fff 0% 50%) 50% / 16px 16px'} : undefined} /></a>
          <div className="row small" style={{gap: 4, justifyContent: 'center', flexWrap: 'wrap'}}>
            <span className="badge">Imported</span><span className="badge">{a.kind}</span>
            <span className={`badge ${a.status === 'approved' ? 'good' : a.status === 'rejected' ? 'bad' : 'warn'}`}>{a.status === 'review' ? 'candidate' : a.status}</span></div>
          {a.expression && <div className="small">{a.expression}</div>}
          <NotedInManifest p={a.provenance} />
          <div className="small muted">{dimensionLabel(a)}</div>
          {a.parent_asset_id && <div className="small muted">belongs to asset {a.parent_asset_id}</div>}
          {a.status === 'review' && !c.locked && <>
            <DimensionSelects a={a} busy={!!act.busy} onSave={d => act.run('dim', () => api(`/character-assets/${a.id}/dimension`, {method: 'PUT', body: d}))} />
            <div className="row" style={{justifyContent: 'center', marginTop: 4}}>
              <button className="btn sm good" disabled={!!act.busy} onClick={() => act.run('a', () => api(`/character-assets/${a.id}/decision`, {body: {decision: 'approve'}}))}>Approve</button>
              <button className="btn sm danger" disabled={!!act.busy} onClick={() => act.run('r', () => api(`/character-assets/${a.id}/decision`, {body: {decision: 'reject'}}))}>Reject</button></div></>}
          <div style={{textAlign: 'left', marginTop: 4}}><ProvenancePanel assetId={a.id} provenance={a.provenance} /></div>
        </div>))}</div>
    </div>);
}

// An approval or rejection the manifest recorded before the import: shown as information, never as the studio's status.
export function NotedInManifest({p}: {p: any}) {
  const t = recordedDecision(p);
  return t ? <div className="small muted" title="Recorded in the manifest before the import; your decision here is the one that counts">noted in manifest: {t}</div> : null;
}
