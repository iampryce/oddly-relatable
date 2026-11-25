'use client';
// The studio frame (clean dashboard, 2026-11-25): one top bar with four places only: Episodes, Characters, Chat and
// Settings. Everything else (Overview, Ideas, Scripts, Storyboards, Production, Lab, Video Library, Publishing, Bin) is
// still at its own address and listed under Settings › Advanced; nothing was removed.
import Link from 'next/link';
import {usePathname, useRouter} from 'next/navigation';
import {api} from '@/lib/api';

const NAV = [['/', 'Episodes'], ['/characters', 'Characters'], ['/chat', 'Chat'], ['/settings', 'Settings']] as const;

// the pages reached from Settings › Advanced keep Settings highlighted
export const ADVANCED = [
  ['/overview', 'Overview', 'Studio totals, disk use and recent activity'], ['/ideas', 'Ideas', 'Script-first ideas and audio uploads'],
  ['/scripts', 'Scripts', 'Scripts waiting for approval'], ['/storyboards', 'Storyboards', 'Storyboards waiting for approval'],
  ['/production', 'Production', 'Every job: running, failed, retry'], ['/lab', 'Lab', 'Shot and model comparisons'],
  ['/library', 'Video Library', 'Finished videos'], ['/publishing', 'Publishing', 'YouTube uploads'],
  ['/bin', 'Bin', 'Deleted episodes, characters and sets'],
] as const;

function active(path: string, href: string): boolean {
  if (href === '/') return path === '/' || path.startsWith('/episodes');
  if (href === '/settings') return path.startsWith('/settings') || ADVANCED.some(([h]) => path.startsWith(h));
  return path.startsWith(href);
}

export default function Shell({children}: {children: React.ReactNode}) {
  const path = usePathname();
  const router = useRouter();
  const toggle = () => {
    const el = document.documentElement;
    const dark = el.dataset.theme ? el.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    el.dataset.theme = dark ? 'light' : 'dark';
    try { localStorage.setItem('odd-theme', el.dataset.theme); } catch {}
  };
  const logout = async () => { await api('/auth/logout', {method: 'POST'}).catch(() => {}); router.push('/login'); };
  return (
    <div className="app">
      <header className="appbar">
        <Link href="/" className="brand"><span className="brand-mark" aria-hidden>OR</span><span>Oddly Relatable</span></Link>
        <nav className="topnav" aria-label="Main">
          {NAV.map(([href, label]) => <Link key={href} href={href} className={active(path, href) ? 'on' : ''}
            aria-current={active(path, href) ? 'page' : undefined}>{label}</Link>)}
        </nav>
        <div className="appbar-tools">
          <button className="btn sm" onClick={toggle} aria-label="Switch light or dark theme">Theme</button>
          <button className="btn sm" onClick={logout}>Sign out</button>
        </div>
      </header>
      <main className="main">{children}</main>
    </div>
  );
}
