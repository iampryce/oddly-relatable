'use client';
import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';

const PROVIDERS: Record<string, [string, string][]> = {
  text: [['none', 'Off'], ['codex-cli', 'Codex CLI (ChatGPT subscription; worker machine only)'], ['openai', 'OpenAI API (key on server)'], ['anthropic', 'Anthropic API (key on server)']],
  image: [['none', 'Off'], ['codex-cli', 'Codex CLI image generation (worker machine only)'], ['openai', 'OpenAI Images API (key on server)']],
  voice: [['none', 'Off (SFX only, no voices)'], ['openai', 'OpenAI text-to-speech (key on server)']],
};

function Section({name, title, value, children}: {name: string; title: string; value: any; children: (v: any, set: (k: string, x: any) => void) => React.ReactNode}) {
  const [v, setV] = useState<any>(value);
  const {busy, error, run} = useAction();
  const [saved, setSaved] = useState(false);
  useEffect(() => setV(value), [value]);
  const set = (k: string, x: any) => { setSaved(false); setV((o: any) => ({...o, [k]: x})); };
  return (
    <div className="card stack">
      <h2>{title}</h2>
      <ErrorBox error={error} />
      {children(v, set)}
      <div className="row"><button className="btn primary" disabled={!!busy} onClick={async () => { if (await run('save', () => api(`/settings/${name}`, {method: 'PUT', body: v}))) setSaved(true); }}>Save</button>
        {saved && <span className="badge good">saved</span>}</div>
    </div>
  );
}

const Yes = ({ok, label}: {ok: boolean; label: string}) => <li><span className={`badge ${ok ? 'good' : 'bad'}`}>{ok ? 'configured' : 'missing'}</span> {label}</li>;

export default function Settings() {
  const {data, error} = useApi<any>('/settings');
  if (!data) return <ErrorBox error={error} />;
  const s = data.sections, i = data.integrations;
  const provider = (kind: string) => (v: any, set: any) => (
    <div className="grid cols-2">
      <div><label htmlFor="settings-provider-1">Provider</label><select id="settings-provider-1" value={v.provider} onChange={e => set('provider', e.target.value)}>{PROVIDERS[kind].map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></div>
      <div><label htmlFor="settings-model-optional-provider--2">Model (optional; provider default if empty)</label><input id="settings-model-optional-provider--2" value={v.model} onChange={e => set('model', e.target.value)} /></div>
    </div>);
  return (
    <>
      <h1>Settings</h1><p className="sub">Choices are stored in the studio database. Secrets (API keys, YouTube tokens) live only in the server environment and are never shown here.</p>
      <div className="grid cols-2">
        <div className="card"><h2>Server integrations</h2><ul style={{listStyle: 'none', padding: 0}} className="stack">
          <Yes ok={i.openai_api_key} label="OpenAI API key" /><Yes ok={i.anthropic_api_key} label="Anthropic API key" />
          <Yes ok={i.codex_cli} label="Codex CLI on the worker machine" /><Yes ok={i.youtube} label="YouTube channel (OAuth refresh token)" />
          <Yes ok={i.ffmpeg} label="FFmpeg for rendering" /><Yes ok={i.redis} label="Job queue (Redis)" />
          <li><span className="badge">{i.storage}</span> media storage{i.storage === 's3' && !i.s3_bucket_set ? ' (bucket missing)' : ''}</li>
        </ul></div>
        <Section name="text" title="AI writer (scripts)" value={s.text}>{provider('text')}</Section>
        <Section name="image" title="Image generation (character poses)" value={s.image}>{(v, set) => <>{provider('image')(v, set)}
          <div><label htmlFor="settings-size-3">Size</label><select id="settings-size-3" value={v.size} onChange={e => set('size', e.target.value)}><option>1024x1536</option><option>1024x1024</option></select></div></>}</Section>
        <Section name="voice" title="Voice and audio" value={s.voice}>{(v, set) => <>{provider('voice')(v, set)}
          <div><label htmlFor="settings-default-voice-4">Default voice</label><input id="settings-default-voice-4" value={v.default_voice} onChange={e => set('default_voice', e.target.value)} placeholder="e.g. alloy" /></div>
          <div><label>Voice per character (JSON: {'{"character-key": "voice"}'})</label><textarea value={JSON.stringify(v.voices || {})} onChange={e => { try { set('voices', JSON.parse(e.target.value || '{}')); } catch {} }} /></div></>}</Section>
        <Section name="production" title="Production" value={s.production}>{(v, set) => (
          <div className="grid cols-2">
            <div><label htmlFor="settings-default-set-5">Default set</label><select id="settings-default-set-5" value={v.environment} onChange={e => set('environment', e.target.value)}>{data.environments.map((x: string) => <option key={x}>{x}</option>)}</select></div>
            <div><label htmlFor="settings-maximum-length-seconds-6">Maximum length (seconds)</label><input id="settings-maximum-length-seconds-6" type="number" min={10} max={60} value={v.max_seconds} onChange={e => set('max_seconds', Number(e.target.value))} /></div>
            <div><label htmlFor="settings-end-card-text-7">End card text</label><input id="settings-end-card-text-7" value={v.end_card} onChange={e => set('end_card', e.target.value)} /></div>
          </div>)}</Section>
        <Section name="youtube" title="YouTube defaults" value={s.youtube}>{(v, set) => (
          <div className="grid cols-2">
            <div><label htmlFor="settings-default-visibility-8">Default visibility</label><select id="settings-default-visibility-8" value={v.default_privacy} onChange={e => set('default_privacy', e.target.value)}><option value="private">Private</option><option value="unlisted">Unlisted</option><option value="public">Public</option></select></div>
            <div><label htmlFor="settings-default-tags-comma-separ-9">Default tags (comma separated)</label><input id="settings-default-tags-comma-separ-9" value={(v.default_tags || []).join(', ')} onChange={e => set('default_tags', e.target.value.split(',').map((x: string) => x.trim()).filter(Boolean))} /></div>
          </div>)}</Section>
        <Section name="creative" title="House comedy style (given to the AI writer)" value={s.creative}>{(v, set) => (
          <textarea style={{minHeight: 160}} value={v.house_style} onChange={e => set('house_style', e.target.value)} />)}</Section>
      </div>
    </>
  );
}
