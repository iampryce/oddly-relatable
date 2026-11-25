'use client';
// Chat: ask the studio questions. An LLM answers (Anthropic Claude Opus 5.5 when its key is saved, else OpenAI) with a
// read-only summary of the studio (episodes, characters, recent jobs, non-secret settings); it changes nothing. Each
// message shows its estimated cost before it is sent (the send carries the most it can cost) and its real usage after.
// Conversations are kept on the server, one per chat.
import {useEffect, useRef, useState} from 'react';
import Link from 'next/link';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import {chatEstimateText, chatUsageText, usd4} from '@/lib/stickPipeline';

export default function ChatPage() {
  const {data: sessions, reload} = useApi<any[]>('/chat/sessions');
  const [sid, setSid] = useState<string | null>(null);
  const {data: chat, reload: reloadChat} = useApi<any>(sid ? `/chat/sessions/${sid}` : null);
  const act = useAction(async () => { await reload(); await reloadChat(); });
  const [text, setText] = useState('');
  const [est, setEst] = useState<any>(null);
  const [estErr, setEstErr] = useState('');
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { if (!sid && sessions?.length) setSid(sessions[0].id); }, [sessions, sid]);
  useEffect(() => { end.current?.scrollIntoView({block: 'end'}); }, [chat?.messages?.length]);
  // the estimate follows the typed text (no paid call: the server only counts)
  useEffect(() => {
    setEst(null); setEstErr('');
    if (!sid || !text.trim()) return;
    const t = setTimeout(() => api('/chat/estimate', {body: {session_id: sid, text}}).then(setEst, e => setEstErr(e.message)), 500);
    return () => clearTimeout(t);
  }, [text, sid]);
  const newChat = () => act.run('new', async () => { const r = await api('/chat/sessions', {method: 'POST'}); setSid(r.id); });
  const send = async (e: {preventDefault: () => void}) => {
    e.preventDefault();
    if (!sid || !est || !text.trim() || act.busy) return;
    if (await act.run('send', () => api('/chat/send', {body: {session_id: sid, text, confirm_usd: est.usd_max}}))) setText('');
  };
  const remove = () => { if (sid && window.confirm('Delete this chat?')) act.run('del', async () => { await api(`/chat/sessions/${sid}`, {method: 'DELETE'}); setSid(null); }); };
  return (
    <>
      <div className="spread"><div><h1>Chat</h1><p className="sub">Ask about your episodes, characters, jobs and settings. The chat only reads; it never changes anything.</p></div>
        <button className="btn primary" disabled={!!act.busy} onClick={newChat}>New chat</button></div>
      <ErrorBox error={act.error} />
      <div className="grid" style={{gridTemplateColumns: 'minmax(160px, 240px) 1fr', gap: 16, alignItems: 'start'}}>
        <nav className="card stack" aria-label="Chats" style={{gap: 4}}>
          {!sessions?.length && <span className="muted small">No chats yet.</span>}
          {(sessions || []).map(x => (
            <button key={x.id} type="button" className={`btn sm ${x.id === sid ? 'primary' : ''}`} style={{textAlign: 'left'}} onClick={() => setSid(x.id)}>
              {x.title || 'New chat'} <span className="muted small">· {usd4(x.usd)}</span></button>))}
        </nav>
        <section className="card stack" aria-label="Conversation">
          {!sid ? <p className="muted">Start a <button className="btn sm" onClick={newChat}>new chat</button>.</p> : <>
            <div className="stack" style={{maxHeight: '60vh', overflow: 'auto', gap: 10}}>
              {(chat?.messages || []).map((m: any, i: number) => (
                <div key={i} style={{alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '85%', borderRadius: 8, padding: '8px 12px',
                  border: '1px solid var(--line, #ddd)', background: m.role === 'user' ? 'var(--panel-2, transparent)' : 'var(--panel, transparent)'}}>
                  <div style={{whiteSpace: 'pre-wrap'}}>{m.content}</div>
                  {m.role === 'assistant' && <div className="muted small" style={{marginTop: 4}}>{m.model} · {chatUsageText(m)}{m.estimate ? ` (estimated up to ${usd4(m.estimate.usd_max)})` : ''}</div>}
                </div>))}
              {!chat?.messages?.length && <p className="muted small">Ask a question, e.g. &ldquo;Which characters still need an approved master?&rdquo;</p>}
              <div ref={end} />
            </div>
            <form className="stack" onSubmit={send}>
              <label htmlFor="chat-text" className="small">Your question</label>
              <textarea id="chat-text" value={text} maxLength={8000} onChange={e => setText(e.target.value)} rows={3}
                onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) send(e); }} />
              <div className="spread small">
                <span className={estErr ? 'bad' : 'muted'} role="status">{estErr ? <>{estErr} <Link href="/settings">Settings</Link></> : est ? `Cost: ${chatEstimateText(est)}` : text.trim() ? 'Checking the cost…' : ''}</span>
                <span className="row">
                  {chat && <span className="muted">This chat: {usd4(chat.usd)}</span>}
                  <button type="button" className="btn sm" disabled={!!act.busy} onClick={remove}>Delete chat</button>
                  <button className="btn primary" type="submit" disabled={!!act.busy || !est || !text.trim()}>
                    {act.busy === 'send' ? 'Asking…' : est ? `Send · up to ${usd4(est.usd_max)}` : 'Send'}</button></span>
              </div>
            </form></>}
        </section>
      </div>
    </>);
}
