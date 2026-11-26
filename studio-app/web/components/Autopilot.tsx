'use client';
// "Make whole episode" (API: autopilot.py), at the top of the guided page. The owner types ONE total budget and
// confirms it; the autopilot then runs the steps in order and stops at every approval, which stays the owner's click.
// The panel shows the current step, spent vs budget, what it waits for, what each provider can do (never a key), and
// Pause / Resume / Stop (Stop also turns the rented GPU off).
import Link from 'next/link';
import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {useAction, useApi} from '@/lib/hooks';
import {ErrorBox} from '@/components/ui';
import {apStatus, budgetPercent, budgetText, controls, parseBudget, providerBadge, startConfirmText} from '@/lib/autopilot';

export default function Autopilot({id, onChange}: {id: string; onChange: () => unknown}) {
  const [poll, setPoll] = useState(15000);
  const {data: s, error, reload} = useApi<any>(`/episodes/${id}/autopilot`, poll);
  const act = useAction(async () => { await reload(); await onChange(); });
  const [budget, setBudget] = useState('');
  const [free, setFree] = useState(false);
  const [open, setOpen] = useState(false);
  const live = s?.status === 'running' || s?.status === 'waiting';
  useEffect(() => { setPoll(live ? 5000 : 15000); if (s) onChange(); }, [s?.status, s?.step, s?.spent_usd]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!s) return error ? <ErrorBox error={error} /> : null;
  const st = apStatus(s);
  const c = controls(s);
  const amount = parseBudget(budget);
  const start = () => {
    if (amount == null || !window.confirm(startConfirmText(amount))) return;
    act.run('start', () => api(`/episodes/${id}/autopilot/start`, {body: {budget_usd: amount, confirm_usd: amount, use_free_tier: free}}));
  };
  const resume = () => {
    const body: any = {};
    if (amount != null && amount !== s.budget_usd) {
      if (!window.confirm(`Change the budget of this run to $${amount.toFixed(2)} and go on?`)) return;
      body.budget_usd = amount; body.confirm_usd = amount;
    }
    act.run('resume', () => api(`/episodes/${id}/autopilot/resume`, {body}));
  };
  const stop = () => {
    if (!window.confirm('Stop the autopilot and turn the rented GPU off now? A shot rendering now fails and can be made again.')) return;
    act.run('stop', () => api(`/episodes/${id}/autopilot/stop`, {method: 'POST'}));
  };
  return (
    <section className="card ap" aria-label="Make whole episode">
      <div className="spread">
        <h2 className="gd-title">Make whole episode</h2>
        <span className={`badge ${st.tone}`}>{st.text}</span>
      </div>
      <p className="small muted" style={{margin: '6px 0 10px', maxWidth: 760}}>Set one budget for the whole episode. The autopilot
        runs the steps below in order, starts paid work only while it fits in the budget and the monthly GPU cap, and
        stops to wait for you at every approval. It never approves anything for you.</p>
      <ErrorBox error={act.error} />
      {s.status !== 'off' && <div className="ap-now">
        <div className="small"><span className="muted">Now: </span>{s.step_label || '—'}</div>
        <div className="small">{s.message}</div>
        <div className="ap-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={budgetPercent(s)}
          aria-label="Budget used"><span style={{width: `${budgetPercent(s)}%`}} /></div>
        <div className="small muted">{budgetText(s)}</div>
      </div>}
      {s.waiting_for?.length > 0 && <div className="ap-wait">
        <strong className="small">Waiting for you</strong>
        <ul className="small">{s.waiting_for.map((w: any, i: number) => <li key={i}>{w.what} <span className="muted">({w.where})</span></li>)}</ul>
      </div>}
      {s.blockers?.length > 0 && <div className="small bad">{s.blockers.map((b: string) => <div key={b}>{b}</div>)}
        <Link href="/settings">Open Settings</Link></div>}
      <div className="row" style={{marginTop: 10}}>
        <label className="small" htmlFor="ap-budget" style={{margin: 0}}>Budget (USD)</label>
        <input id="ap-budget" inputMode="decimal" style={{width: 110}} placeholder={s.budget_usd ? s.budget_usd.toFixed(2) : 'e.g. 10'}
          value={budget} onChange={e => setBudget(e.target.value)} />
        {c.start && <button className="btn primary" disabled={!!act.busy || amount == null || s.blockers?.length > 0} onClick={start}>
          {act.busy === 'start' ? 'Starting…' : amount != null ? `Make whole episode · budget $${amount.toFixed(2)}` : 'Make whole episode'}</button>}
        {c.resume && <button className="btn primary" disabled={!!act.busy} onClick={resume}>
          {amount != null && amount !== s.budget_usd ? `Resume with $${amount.toFixed(2)}` : 'Resume'}</button>}
        {c.pause && <button className="btn" disabled={!!act.busy} onClick={() => act.run('pause', () => api(`/episodes/${id}/autopilot/pause`, {method: 'POST'}))}>Pause</button>}
        {c.stop && <button className="btn danger" disabled={!!act.busy} onClick={stop}>Stop</button>}
      </div>
      {c.start && <label className="row small" style={{fontWeight: 400, color: 'inherit', marginTop: 6}}>
        <input type="checkbox" style={{width: 'auto'}} checked={free} onChange={e => setFree(e.target.checked)} />
        Let the acting analysis use Gemini&rsquo;s free tier when the paid model is busy (Google may use the video to train its models).</label>}
      <details className="ap-details" open={open} onToggle={e => setOpen((e.target as HTMLDetailsElement).open)}>
        <summary className="small">Providers, notes and what was started</summary>
        <table className="ap-table small">
          <thead><tr><th>Step</th><th>Uses</th><th>Status</th><th>Note</th></tr></thead>
          <tbody>{(s.providers || []).map((p: any) => {
            const b = providerBadge(p);
            return <tr key={p.step}><td>{p.label}</td><td>{p.provider}</td><td><span className={`badge ${b.tone}`}>{b.text}</span></td>
              <td className="muted">{p.note}</td></tr>;
          })}</tbody>
        </table>
        {s.notes?.length > 0 && <ul className="small muted">{s.notes.map((n: string, i: number) => <li key={i}>{n}</li>)}</ul>}
        <p className="small muted">Automatic redos after the quality check: at most {s.max_redos_per_shot} per shot, only for clear problems
          (Settings › Quality check and autopilot).</p>
        {s.actions?.length > 0 && <table className="ap-table small">
          <thead><tr><th>Started</th><th>At most</th><th>Cost</th><th>State</th></tr></thead>
          <tbody>{s.actions.map((a: any, i: number) => <tr key={i}><td>{a.what}</td><td>${(a.usd_max || 0).toFixed(2)}</td>
            <td>{a.usd != null ? `$${a.usd.toFixed(2)}` : '—'}</td><td>{a.state}</td></tr>)}</tbody>
        </table>}
      </details>
    </section>);
}
