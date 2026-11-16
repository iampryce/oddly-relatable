'use client';
import {useCallback, useEffect, useRef, useState} from 'react';
import {api} from './api';

// Load JSON from the API and keep it fresh. `pollMs` refreshes while the page is visible (production progress).
export function useApi<T = any>(path: string | null, pollMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const alive = useRef(true);
  const load = useCallback(async () => {
    if (!path) return;
    try {
      const d = await api<T>(path);
      if (alive.current) { setData(d); setError(''); }
    } catch (e: any) {
      if (alive.current) setError(e.message);
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    alive.current = true;
    load();
    if (!pollMs) return () => { alive.current = false; };
    const t = setInterval(() => { if (document.visibilityState === 'visible') load(); }, pollMs);
    return () => { alive.current = false; clearInterval(t); };
  }, [load, pollMs]);
  return {data, error, loading, reload: load, setData};
}

// Run an action, report its error, and reload afterwards.
export function useAction(after?: () => unknown) {
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const run = useCallback(async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label); setError('');
    try { await fn(); await after?.(); return true; }
    catch (e: any) { setError(e.message); return false; }
    finally { setBusy(''); }
  }, [after]);
  return {busy, error, run, setError};
}
