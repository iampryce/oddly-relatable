'use client';
// Chat: a placeholder until the studio chat is built (separate change). Nothing is sent anywhere from this page.
import Link from 'next/link';

export default function ChatPage() {
  return (
    <>
      <h1>Chat</h1>
      <p className="sub">Talk to the studio about an episode.</p>
      <div className="card empty">
        <p style={{marginTop: 0}}><strong>Coming next.</strong></p>
        <p className="muted small" style={{marginBottom: 0}}>The chat is being built separately. Until then, everything is on <Link href="/">Episodes</Link>.</p>
      </div>
    </>
  );
}
