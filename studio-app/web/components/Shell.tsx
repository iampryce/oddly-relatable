'use client';
import Link from 'next/link';
import {usePathname, useRouter} from 'next/navigation';
import {api} from '@/lib/api';
import {useApi} from '@/lib/hooks';

const NAV = [
  ['/', 'Overview'], ['/ideas', 'Ideas'], ['/scripts', 'Scripts'], ['/characters', 'Characters'],
  ['/storyboards', 'Storyboards'], ['/production', 'Production'], ['/library', 'Video Library'],
  ['/publishing', 'Publishing'], ['/settings', 'Settings'],
] as const;

export default function Shell({children}: {children: React.ReactNode}) {
  const path = usePathname();
  const router = useRouter();
  const {data: o} = useApi<any>('/overview', 15000);
  const count: Record<string, number | undefined> = o ? {
    '/ideas': o.ideas_awaiting, '/scripts': o.scripts_awaiting_approval, '/storyboards': o.storyboards_awaiting_approval,
    '/production': o.failed_jobs || o.active_jobs, '/library': o.videos_awaiting_review,
  } : {};
  const toggle = () => {
    const el = document.documentElement;
    const dark = el.dataset.theme ? el.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    el.dataset.theme = dark ? 'light' : 'dark';
    try { localStorage.setItem('odd-theme', el.dataset.theme); } catch {}
  };
  const logout = async () => { await api('/auth/logout', {method: 'POST'}).catch(() => {}); router.push('/login'); };
  return (
    <div className="shell">
      <aside className="side">
        <div className="brand"><div className="brand-mark">OR</div><div>Oddly Relatable<small>Studio</small></div></div>
        <nav className="nav">
          {NAV.map(([href, label]) => {
            const on = href === '/' ? path === '/' : path.startsWith(href) || (href === '/production' && path.startsWith('/episodes'));
            const n = count[href];
            return <Link key={href} href={href} className={on ? 'on' : ''}>{label}{n ? <span className="badge">{n}</span> : null}</Link>;
          })}
        </nav>
        <div className="side-foot">
          <button className="btn sm" onClick={toggle} aria-label="Switch light or dark theme">Theme</button>
          <button className="btn sm" onClick={logout}>Sign out</button>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}
