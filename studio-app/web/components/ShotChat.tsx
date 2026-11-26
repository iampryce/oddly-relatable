'use client';
// Chat under each shot: a conversation attached to the thing shown just above it (a master, a still, a clip, one
// shot's acting notes, a prompt draft). The owner gives context; the assistant answers and may propose one change,
// shown as a card with what will change and its price. Apply goes through that step's own button logic on the server
// (paid ones carry the price shown, like every paid button). Each message shows its cost before it is sent. If sending
// fails (no credit, no key) the typed message stays in the box. Drop <ShotChat step=… item=… /> under any preview.
import {useEffect, useRef, useState} from 'react';
import Link from 'next/link';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import {confirmText, chatUsageText} from '@/lib/stickPipeline';
import {applyLabel, estimateText, PROPOSAL_STATUS, PROPOSAL_TITLE, proposalDetail, refBody, sendLabel, STEP_NOUN,
  threadQuery, type Step} from '@/lib/shotChat';

export default function ShotChat({step, item, episodeId, onApplied}: {step: Step; item: string | number;
  episodeId?: string | number | null; onApplied?: () => unknown}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="sc">
      <button type="button" className="btn sm sc-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? 'Hide the chat' : `Chat about ${STEP_NOUN[step]}`}</button>
      {open && <Thread step={step} item={item} episodeId={episodeId} onApplied={onApplied} />}
    </div>);
}

function Thread({step, item, episodeId, onApplied}: {step: Step; item: string | number; episodeId?: string | number | null;
  onApplied?: () => unknown}) {
  const {data: t, error, reload} = useApi<any>(threadQuery(step, item, episodeId));
  const act = useAction(reload);
  const [text, setText] = useState('');
  const [est, setEst] = useState<any>(null);
  const [estErr, setEstErr] = useState('');
  const end = useRef<HTMLDivElement>(null);
  const ref = refBody(step, item, episodeId);
  useEffect(() => { end.current?.scrollIntoView({block: 'nearest'}); }, [t?.messages?.length]);
  // the estimate follows the typed text (no paid call: the server only counts)
  useEffect(() => {
    setEst(null); setEstErr('');
    if (!text.trim()) return;
    const h = setTimeout(() => api('/shot-chat/estimate', {body: {...ref, text}}).then(setEst, e => setEstErr(e.message)), 500);
    return () => clearTimeout(h);
  }, [text]);   // eslint-disable-line react-hooks/exhaustive-deps
  const send = async (e: {preventDefault: () => void}) => {
    e.preventDefault();
    if (!est || !text.trim() || act.busy) return;
    // the text is cleared only when the answer came back: a failed send keeps it in the box
    if (await act.run('send', () => api('/shot-chat/send', {body: {...ref, text, confirm_usd: est.usd_max}}))) setText('');
  };
  const decide = (m: any, what: 'apply' | 'dismiss') => {
    let body: any = {...ref, message_id: m.id};
    if (what === 'apply' && m.cost) {
      if (m.cost.usd == null || !window.confirm(confirmText(PROPOSAL_TITLE[m.proposal.type] || 'Apply', m.cost))) return;
      body = {...body, confirm_usd: m.cost.usd};
    }
    act.run(`${what}-${m.id}`, async () => { await api(`/shot-chat/${what}`, {body}); if (what === 'apply') await onApplied?.(); });
  };
  if (!t) return error ? <ErrorBox error={error} /> : <p className="small muted">Loading the chat…</p>;
  return (
    <section className="sc-thread" aria-label={`Chat about ${STEP_NOUN[step]}`}>
      <div className="sc-messages">
        {!t.messages.length && <p className="small muted">Tell the assistant what you want here, e.g. &ldquo;He should look
          smug, not angry&rdquo;. It knows this {step === 'acting' ? 'shot' : 'item'}&apos;s prompt, acting notes and the house style.</p>}
        {t.messages.map((m: any) => (
          <div key={m.id} className={`sc-msg ${m.role === 'user' ? 'me' : ''}`}>
            <div className="sc-text">{m.text}</div>
            {m.role === 'assistant' && <div className="small muted">{m.model} · {chatUsageText(m)}</div>}
            {m.proposal_left_out && <div className="small muted">The assistant suggested a change this step cannot make, so it was left out.</div>}
            {m.proposal && m.proposal.type !== 'note_only' && <Proposal m={m} busy={!!act.busy} decide={decide} />}
          </div>))}
        <div ref={end} />
      </div>
      <ErrorBox error={act.error} />
      {act.error && /balance|API key|Settings/.test(act.error) && <p className="small">Change the assistant in <Link href="/settings">Settings › Chat under each shot</Link>.</p>}
      <form className="stack sc-form" onSubmit={send}>
        <textarea aria-label="Your message" rows={2} maxLength={6000} value={text} onChange={e => setText(e.target.value)}
          placeholder="Give context or ask for a change…"
          onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) send(e); }} />
        <div className="spread small">
          <span className={estErr ? 'bad' : 'muted'} role="status">{estErr || (est ? estimateText(est) : text.trim() ? 'Checking the cost…' : '')}</span>
          <span className="row">
            {t.usd > 0 && <span className="muted">This chat: ${t.usd.toFixed(4)}</span>}
            <button className="btn sm primary" type="submit" disabled={!!act.busy || !est || !text.trim()}>{sendLabel(est, act.busy === 'send')}</button>
          </span>
        </div>
      </form>
    </section>);
}

function Proposal({m, busy, decide}: {m: any; busy: boolean; decide: (m: any, what: 'apply' | 'dismiss') => void}) {
  const st = PROPOSAL_STATUS[m.proposal_status] || {tone: '', text: m.proposal_status};
  const detail = proposalDetail(m.proposal);
  return (
    <div className="sc-proposal">
      <div className="spread small"><strong>{PROPOSAL_TITLE[m.proposal.type] || 'Proposal'}</strong>
        <span className={`badge ${st.tone}`}>{st.text}</span></div>
      <div className="small"><span className="muted">What will change: </span>{m.what_will_change}</div>
      {detail && <pre className="small sc-detail">{detail}</pre>}
      {m.proposal_note && <div className="small muted">{m.proposal_note}</div>}
      {m.proposal_status === 'pending' && <>
        <div className="small"><span className="muted">Cost: </span>{m.cost ? m.cost.label : 'free'}</div>
        <div className="row">
          <button className="btn sm good" disabled={busy || (m.cost && m.cost.usd == null)} onClick={() => decide(m, 'apply')}>{applyLabel(m.cost)}</button>
          <button className="btn sm" disabled={busy} onClick={() => decide(m, 'dismiss')}>Dismiss</button>
        </div></>}
      {m.proposal_status === 'applied' && m.result?.done && <div className="small muted">{m.result.done}</div>}
    </div>);
}
