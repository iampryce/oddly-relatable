'use client';
import {Suspense, useState} from 'react';
import {useRouter, useSearchParams} from 'next/navigation';
import {api} from '@/lib/api';

function LoginForm() {
  const router = useRouter();
  const next = useSearchParams().get('next') || '/';
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError('');
    try {
      await api('/auth/login', {body: {email, password}});
      // Only same-site paths: never redirect to another origin after sign-in.
      router.replace(next.startsWith('/') && !next.startsWith('//') ? next : '/');
    } catch (err: any) { setError(err.message); } finally { setBusy(false); }
  };
  return (
    <form className="card" onSubmit={submit}>
      <div className="brand" style={{padding: '0 0 16px'}}><div className="brand-mark">OR</div><div>Oddly Relatable<small>Studio</small></div></div>
      <h1>Sign in</h1>
      <p className="sub">Production control centre</p>
      {error && <div className="alert bad" role="alert">{error}</div>}
      <div className="field"><label htmlFor="username">Username</label><input id="username" type="text" autoComplete="username" autoCapitalize="none" spellCheck={false} value={email} onChange={e => setEmail(e.target.value)} required /></div>
      <div className="field"><label htmlFor="pw">Password</label><input id="pw" type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required /></div>
      <button className="btn primary" style={{width: '100%'}} disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
    </form>
  );
}

export default function Login() {
  return <div className="login"><Suspense><LoginForm /></Suspense></div>;
}
