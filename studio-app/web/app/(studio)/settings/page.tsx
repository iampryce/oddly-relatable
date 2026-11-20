'use client';
import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';

// Capabilities come from the server's provider registry (capabilities.py): which providers exist, what they need,
// whether they are integrated, configured and VERIFIED by a real worker test. Nothing here is assumed.
const CAP_ORDER = ['script', 'transcription', 'vision', 'image', 'voice', 'motion', 'lipsync', 'sound', 'storage', 'publishing'];
const CREDENTIALS: [string, string][] = [
  ['openai_api_key', 'OpenAI API key'], ['anthropic_api_key', 'Anthropic API key'], ['elevenlabs_api_key', 'ElevenLabs API key'],
  ['fish_api_key', 'Fish Audio API key'],
  ['aws_access_key_id', 'AWS access key ID (S3)'], ['aws_secret_access_key', 'AWS secret access key (S3)'],
  ['youtube_client_id', 'YouTube OAuth client ID'], ['youtube_client_secret', 'YouTube OAuth client secret'],
  ['youtube_refresh_token', 'YouTube refresh token (set by "Connect YouTube")'], ['comfyui_token', 'ComfyUI access token (optional)'],
  ['fal_key', 'fal.ai API key (hosted video models)'],
];
const NEED_LABEL = (n: string) => n.startsWith('tool:') ? `${n.slice(5)} installed on the worker` : n.startsWith('setting:') ? `${n.slice(8).replace('.', ' ')} set below` :
  (CREDENTIALS.find(([k]) => k === n)?.[1] || n.replace(/_/g, ' '));

function useSection(name: string, value: any) {
  const [v, setV] = useState<any>(value);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const {busy, error, run} = useAction();
  // keep unsaved edits while the page refreshes test results in the background
  useEffect(() => { if (!dirty) setV(value); }, [value, dirty]);
  const set = (k: string, x: any) => { setSaved(false); setDirty(true); setV((o: any) => ({...o, [k]: x})); };
  const save = async () => { if (await run('save', () => api(`/settings/${name}`, {method: 'PUT', body: v}))) { setSaved(true); setDirty(false); } };
  return {v, set, save, busy, error, saved};
}

function SaveRow({s}: {s: ReturnType<typeof useSection>}) {
  return <div className="row"><button className="btn primary" disabled={!!s.busy} onClick={s.save}>Save</button>{s.saved && <span className="badge good">saved</span>}</div>;
}

function Section({name, title, value, children}: {name: string; title: string; value: any; children: (v: any, set: (k: string, x: any) => void) => React.ReactNode}) {
  const s = useSection(name, value);
  return <div className="card stack"><h2>{title}</h2><ErrorBox error={s.error} />{children(s.v, s.set)}<SaveRow s={s} /></div>;
}

function TestResult({t}: {t: any}) {
  if (!t) return <span className="muted small">not tested</span>;
  if (t.status === 'queued' || t.status === 'running') return <span className="badge busy">{t.status === 'queued' && t.error ? 'retrying' : 'testing'}…</span>;
  if (t.status === 'failed') return <span className="stack"><span className="badge bad">test failed</span><span className="small">{t.error}</span></span>;
  const r = t.result || {}, ct = t.content_type || '';
  const facts = [r.seconds_taken !== undefined && `${r.seconds_taken} s`, r.channel && `channel ${r.channel}`, r.bucket && `bucket ${r.bucket}`,
    r.voice && `voice ${r.voice}`, r.answer?.joke && `“${r.answer.joke}”`, r.transcript && `heard “${r.transcript}” (${r.words_matched} of words, ${r.word_timestamps} word timings)`,
    r.answer?.figures !== undefined && `saw ${r.answer.figures} figures, ${r.answer.raising} raising an arm`, r.mouth_shapes && `${r.cues} mouth cues (${r.mouth_shapes})`,
    r.devices && r.devices.join(', '), r.render_seconds && `rendered in ${r.render_seconds} s`].filter(Boolean).join(' · ');
  return (
    <span className="stack">
      <span><span className="badge good">test passed</span> <span className="muted small">{facts}</span></span>
      {t.url && ct.startsWith('audio') && <audio controls src={t.url} style={{maxWidth: '100%'}} />}
      {t.url && ct.startsWith('image') && <img src={t.url} alt="test result" style={{maxWidth: 160, background: '#eee', borderRadius: 6}} />}
      {t.url && ct.startsWith('video') && <video controls src={t.url} style={{maxWidth: 220, borderRadius: 6}} />}
    </span>);
}

function ProviderRows({cap, reload}: {cap: any; reload: () => unknown}) {
  const {busy, error, run} = useAction(reload);
  return (
    <div className="stack">
      <ErrorBox error={error} />
      <div className="table-wrap"><table>
        <thead><tr><th>Provider</th><th>Status</th><th>Real worker test</th></tr></thead>
        <tbody>{Object.entries(cap.providers).map(([pid, p]: [string, any]) => (
          <tr key={pid}>
            <td><strong>{p.label}</strong>{p.default_model && <div className="muted small">default model {p.default_model}</div>}{p.note && <div className="muted small">{p.note}</div>}</td>
            <td className="small">
              {!p.implemented ? <span className="badge">not integrated</span> : p.verified ? <span className="badge good">verified</span> :
                p.configured ? <span className="badge warn">configured, not verified</span> : <span className="badge bad">not configured</span>}
              {p.implemented && p.missing.length > 0 && <div className="muted">needs: {p.missing.map(NEED_LABEL).join(', ')}</div>}
            </td>
            <td className="small">
              {(p.implemented || p.note?.includes('connection')) && !p.note?.includes('paid per clip') &&
                <button className="btn sm" disabled={!!busy || ['queued', 'running'].includes(p.last_test?.status)}
                  onClick={() => run(pid, () => api('/settings/test', {method: 'POST', body: {target: p.test_target}}))}>Test</button>}{' '}
              <TestResult t={p.last_test} />
            </td>
          </tr>))}
        </tbody></table></div>
    </div>);
}

// Provider choice (primary, fallback, model) for capabilities that have a selectable provider.
function Selection({cap, s}: {cap: any; s: ReturnType<typeof useSection>}) {
  const ids = Object.entries(cap.providers).filter(([, p]: [string, any]) => p.implemented);
  const opts = (none: string) => [<option key="none" value="none">{none}</option>, ...ids.map(([k, p]: [string, any]) => <option key={k} value={k}>{p.label}</option>)];
  const sec = cap.section;
  return (
    <div className="grid cols-2">
      <div><label htmlFor={`${sec}-provider`}>Primary provider</label><select id={`${sec}-provider`} value={s.v.provider ?? 'none'} onChange={e => s.set('provider', e.target.value)}>{opts('Off')}</select></div>
      {'fallback' in s.v && <div><label htmlFor={`${sec}-fallback`}>Fallback provider</label><select id={`${sec}-fallback`} value={s.v.fallback || 'none'} onChange={e => s.set('fallback', e.target.value)}>{opts('No fallback')}</select></div>}
      {'model' in s.v && <div><label htmlFor={`${sec}-model`}>Model (empty: the provider default)</label><input id={`${sec}-model`} value={s.v.model} onChange={e => s.set('model', e.target.value)} /></div>}
    </div>);
}

function CapabilityCard({id, cap, sections, data, reload}: {id: string; cap: any; sections: any; data: any; reload: () => unknown}) {
  const s = useSection(cap.section, sections[cap.section]);
  const i = data.integrations;
  const selectable = !['storage', 'publishing'].includes(id);
  return (
    <div className="card stack">
      <h2>{cap.label}</h2>
      <ErrorBox error={s.error} />
      {selectable && <Selection cap={cap} s={s} />}
      {id === 'image' && <div><label htmlFor="image-size">Size</label><select id="image-size" value={s.v.size} onChange={e => s.set('size', e.target.value)}><option>1024x1536</option><option>1024x1024</option></select></div>}
      {id === 'voice' && <div className="grid cols-2">
        <div><label htmlFor="voice-default">Default voice</label><input id="voice-default" value={s.v.default_voice} onChange={e => s.set('default_voice', e.target.value)} placeholder="alloy, an ElevenLabs voice id, or a Piper model file" /></div>
        <div><label htmlFor="voice-gain">Voice level (0.2–2)</label><input id="voice-gain" type="number" step="0.1" min={0.2} max={2} value={s.v.gain ?? 1} onChange={e => s.set('gain', Number(e.target.value))} /></div>
        <div><label htmlFor="voice-fish-default">Fish Audio default voice (used when Fish is the fallback, and by its test if no character has a Fish voice)</label><input id="voice-fish-default" value={s.v.fish_default_voice ?? ''} onChange={e => s.set('fish_default_voice', e.target.value)} placeholder="Fish voice id" /></div>
        <div style={{gridColumn: '1 / -1'}}><label htmlFor="voice-library">Fish voice library (auto-casting). One voice per line: voice id or fish.audio link | label | him/her/neutral | how it sounds. New characters get the best match; each can be changed.</label>
          <textarea id="voice-library" rows={6} value={s.v.library ?? ''} onChange={e => s.set('library', e.target.value)} placeholder={'e3cd384158934cc9a01029cd7d278634 | Warm advisor | her | calm, warm, reassuring'} /></div></div>}
      {id === 'voice' && <VoiceCompare />}
      {id === 'transcription' && <div><label htmlFor="tr-lang">Language (empty: detect)</label><input id="tr-lang" value={s.v.language} onChange={e => s.set('language', e.target.value)} placeholder="en" /></div>}
      {id === 'motion' && <>
        <p className="muted small">The studio 2D rig animator performs the script&apos;s acting on the CPU and keeps the approved characters exact. Hosted video models (fal.ai) are paid per clip and capped by the budget below.</p>
        <div><label htmlFor="motion-budget">Experimental budget for paid generation (USD)</label><input id="motion-budget" type="number" min={0} step={1} value={s.v.budget_usd ?? 25} onChange={e => s.set('budget_usd', Number(e.target.value))} /></div>
        <p className="small">The hosted model comparison runs from <a href="/production#motion-comparison">Production › Motion Model Comparison</a>.</p></>}
      {id === 'storage' && <><div className="grid cols-2">
        <div><label htmlFor="storage-backend">Store new media in</label><select id="storage-backend" value={s.v.backend || i.storage} onChange={e => s.set('backend', e.target.value)}><option value="local">Server volume</option><option value="s3">AWS S3</option></select></div>
        <div><label htmlFor="storage-bucket">S3 bucket</label><input id="storage-bucket" value={s.v.bucket} onChange={e => s.set('bucket', e.target.value)} /></div>
        <div><label htmlFor="storage-region">S3 region</label><input id="storage-region" value={s.v.region} onChange={e => s.set('region', e.target.value)} placeholder="eu-central-1" /></div>
        <div><label htmlFor="storage-prefix">Key prefix</label><input id="storage-prefix" value={s.v.prefix} onChange={e => s.set('prefix', e.target.value)} /></div></div>
        <p className="muted small">The database and job queue stay on the server; S3 holds media only. Media saved before switching stays on the server volume and keeps working.</p></>}
      {id === 'publishing' && <><div className="grid cols-2">
        <div><label htmlFor="yt-privacy">Default visibility</label><select id="yt-privacy" value={s.v.default_privacy} onChange={e => s.set('default_privacy', e.target.value)}><option value="private">Private</option><option value="unlisted">Unlisted</option><option value="public">Public</option></select></div>
        <div><label htmlFor="yt-tags">Default tags (comma separated)</label><input id="yt-tags" value={(s.v.default_tags || []).join(', ')} onChange={e => s.set('default_tags', e.target.value.split(',').map((x: string) => x.trim()).filter(Boolean))} /></div></div>
        <div className="row"><a className="btn" href="/api/youtube/connect">Connect YouTube channel</a><span className={`badge ${i.youtube ? 'good' : ''}`}>{i.youtube ? 'connected' : 'not connected'}</span></div>
        <p className="muted small">Save the OAuth client ID and secret under Credentials first. Every video still needs your publish approval.</p></>}
      <SaveRow s={s} />
      <ProviderRows cap={cap} reload={reload} />
    </div>);
}

function VoiceCompare() {
  const {data, reload} = useApi<any>('/voice/compare', 5000);
  const {busy, error, run} = useAction(reload);
  const job = data?.job, res = data?.result;
  const active = job && ['queued', 'running'].includes(job.status);
  const cell = (x: any) => !x ? '—' : (<div className="stack small"><audio controls src={x.url} style={{maxWidth: 220}} />
    <span className="muted">{x.voice} · {x.audio_seconds} s audio · made in {x.generation_seconds} s (×{x.real_time_factor} real time) · CPU {x.cpu_seconds} s{x.peak_worker_mb ? ` · peak ${x.peak_worker_mb} MB` : ''}</span></div>);
  return (
    <div className="stack">
      <h3>Kokoro vs Piper (identical lines)</h3>
      <ErrorBox error={error || (job?.status === 'failed' ? job.error : '')} />
      <div className="row"><button className="btn" disabled={!!busy || active} onClick={() => run('cmp', () => api('/voice/compare', {method: 'POST'}))}>{active ? 'Comparing…' : 'Run voice comparison'}</button>
        <span className="muted small">Free: both engines run on the worker&apos;s CPU. Does not change any character&apos;s voice.</span></div>
      {res?.rows && <div className="table-wrap"><table>
        <thead><tr><th>Line</th><th>Piper</th><th>Kokoro</th></tr></thead>
        <tbody>{res.rows.map((r: any) => <tr key={r.character}><td className="small"><strong>{r.name}</strong><div>“{r.text}”</div></td><td>{cell(r.piper)}</td><td>{cell(r.kokoro)}</td></tr>)}</tbody>
      </table></div>}
      {res && <span className="muted small">Kokoro model load: {res.kokoro_load_seconds} s (once per worker start).</span>}
    </div>);
}

function SetCandidate({set: x, reload}: {set: any; reload: () => unknown}) {
  const [b, setB] = useState<any>(x.blocking);
  const {busy, error, run} = useAction(reload);
  const field = (k: string, label: string) => <div><label htmlFor={`${x.id}-${k}`}>{label}</label><input id={`${x.id}-${k}`} type="number" value={b[k]} onChange={e => setB((o: any) => ({...o, [k]: Number(e.target.value)}))} /></div>;
  return (
    <div className="stack small" style={{borderTop: '1px solid var(--line, #ddd)', paddingTop: 8}}>
      <div className="row" style={{gap: 8}}><strong>{x.label}</strong><span className={`badge ${x.status === 'approved' ? 'good' : x.status === 'rejected' ? 'bad' : 'warn'}`}>{x.status}</span><span className="muted">{x.width}×{x.height}</span></div>
      <ErrorBox error={error} />
      <div className="row" style={{alignItems: 'flex-start', gap: 12, flexWrap: 'wrap'}}>
        {x.url && <a href={x.url} target="_blank" rel="noreferrer"><img src={x.url} alt={x.label} style={{width: 150, borderRadius: 6}} /></a>}
        {x.preview_url && <div className="stack"><img src={x.preview_url} alt="staging" style={{width: 150, borderRadius: 6}} /><span className="muted">red: floor line · blue: standing area</span></div>}
      </div>
      {x.status === 'candidate' && <>
        <div className="grid cols-2">{field('floor_y', 'Floor line (px from top)')}{field('stand_min_x', 'Standing area from x')}{field('stand_max_x', 'Standing area to x')}</div>
        <div className="row"><button className="btn primary" disabled={!!busy} onClick={() => run('ok', () => api(`/sets/${x.id}/decide`, {method: 'POST', body: {decision: 'approve', blocking: b}}))}>Approve set</button>
          <button className="btn" disabled={!!busy} onClick={() => run('no', () => api(`/sets/${x.id}/decide`, {method: 'POST', body: {decision: 'reject'}}))}>Reject</button></div></>}
    </div>);
}

function SetsCard() {
  const {data, reload} = useApi<any>('/sets', 5000);
  const [label, setLabel] = useState(''), [desc, setDesc] = useState('');
  const {busy, error, run} = useAction(reload);
  const active = (data?.jobs || []).filter((j: any) => ['queued', 'running'].includes(j.status));
  return (
    <div className="card stack">
      <h2>Sets (background environments)</h2>
      <p className="muted small">New sets are generated as candidates in the approved house style (the living room is the style reference) and are used in production only after you approve them. They appear to the writer when the studio rig animator is the motion provider.</p>
      <ErrorBox error={error} />
      {(data?.sets || []).map((x: any) => <SetCandidate key={`${x.id}-${x.status}-${x.created}`} set={x} reload={reload} />)}
      {active.length > 0 && <span className="badge busy">generating {active.length} candidate(s)…</span>}
      {(data?.jobs || []).filter((j: any) => j.status === 'failed').slice(0, 2).map((j: any) => <div key={j.id} className="small" style={{color: 'var(--bad)'}}>{j.error}</div>)}
      <div className="grid cols-2">
        <div><label htmlFor="set-label">New set name</label><input id="set-label" value={label} onChange={e => setLabel(e.target.value)} placeholder="Office" /></div>
        <div><label htmlFor="set-desc">Description</label><input id="set-desc" value={desc} onChange={e => setDesc(e.target.value)} placeholder="a small open-plan office…" /></div>
      </div>
      <div className="row"><button className="btn" disabled={!!busy || label.length < 2 || desc.length < 10} onClick={() => run('gen', async () => { await api('/sets/generate', {method: 'POST', body: {label, description: desc}}); setLabel(''); setDesc(''); })}>Generate candidate</button>
        <span className="muted small">Uses the OpenAI key (about $0.05–0.20 per image).</span></div>
    </div>);
}

function Credentials({creds, reload}: {creds: any; reload: () => unknown}) {
  const [vals, setVals] = useState<Record<string, string>>({});
  const {busy, error, run} = useAction(reload);
  const save = (k: string, v: string | null) => run(k, async () => { await api('/settings/credentials', {method: 'PUT', body: {values: {[k]: v}}}); setVals(o => ({...o, [k]: ''})); });
  return (
    <div className="card stack">
      <h2>Credentials</h2>
      <p className="muted small">Encrypted on the server and never shown again. Server environment variables are used when nothing is saved here.</p>
      <ErrorBox error={error} />
      {CREDENTIALS.map(([k, label]) => (
        <div key={k}>
          <label htmlFor={`cred-${k}`}>{label} <span className={`badge ${creds[k]?.set ? 'good' : ''}`}>{creds[k]?.set ? `set (${creds[k].source})` : 'not set'}</span></label>
          <div className="row">
            <input id={`cred-${k}`} type="password" autoComplete="off" value={vals[k] || ''} placeholder={creds[k]?.set ? '•••••••• (enter to replace)' : ''} onChange={e => setVals(o => ({...o, [k]: e.target.value}))} />
            <button className="btn" disabled={!!busy || !vals[k]} onClick={() => save(k, vals[k])}>Save</button>
            {creds[k]?.source === 'settings' && <button className="btn" disabled={!!busy} onClick={() => save(k, null)}>Clear</button>}
          </div>
        </div>))}
    </div>);
}

export default function Settings() {
  const {data, error, reload} = useApi<any>('/settings', 4000);
  const [notice, setNotice] = useState('');
  useEffect(() => {
    const y = new URLSearchParams(window.location.search).get('youtube');
    if (y) setNotice(y === 'connected' ? 'YouTube connected. Run the YouTube test to confirm.' : 'YouTube connection failed or was cancelled. Try again.');
  }, []);
  if (!data) return <ErrorBox error={error} />;
  const caps = data.capabilities || {}, s = data.sections;
  const verified = Object.values(caps).flatMap((c: any) => Object.values(c.providers)).filter((p: any) => p.verified).length;
  return (
    <>
      <h1>Settings</h1>
      <p className="sub">Providers by production capability. A provider counts as verified only after a real job on the worker succeeds ({verified} verified).</p>
      {notice && <div className="card"><span className="badge">{notice}</span></div>}
      <div className="grid cols-2">
        <Credentials creds={data.credentials || {}} reload={reload} />
        {CAP_ORDER.filter(id => caps[id]).map(id => <CapabilityCard key={id} id={id} cap={caps[id]} sections={s} data={data} reload={reload} />)}
        <SetsCard />
        <Section name="comfyui" title="ComfyUI server (GPU)" value={s.comfyui}>{(v, set) => (
          <div><label htmlFor="comfyui-url">ComfyUI server URL</label><input id="comfyui-url" value={v.url} onChange={e => set('url', e.target.value)} placeholder="https://…" /></div>)}</Section>
        <Section name="production" title="Production" value={s.production}>{(v, set) => (
          <div className="grid cols-2">
            <div><label htmlFor="prod-set">Default set</label><select id="prod-set" value={v.environment} onChange={e => set('environment', e.target.value)}>{data.environments.map((x: string) => <option key={x}>{x}</option>)}</select></div>
            <div><label htmlFor="prod-max">Maximum length (seconds)</label><input id="prod-max" type="number" min={10} max={60} value={v.max_seconds} onChange={e => set('max_seconds', Number(e.target.value))} /></div>
            <div><label htmlFor="prod-end">End card text</label><input id="prod-end" value={v.end_card} onChange={e => set('end_card', e.target.value)} /></div>
          </div>)}</Section>
        <Section name="creative" title="House comedy style (given to the AI writer)" value={s.creative}>{(v, set) => (
          <textarea style={{minHeight: 160}} value={v.house_style} onChange={e => set('house_style', e.target.value)} />)}</Section>
      </div>
    </>);
}
