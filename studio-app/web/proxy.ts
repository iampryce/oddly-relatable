// Route protection: dashboard pages need the session cookie, otherwise the visitor is sent to /login. This is a
// convenience redirect; the API validates the signed session on every request, so a forged cookie gets nothing.
import {NextResponse} from 'next/server';
import type {NextRequest} from 'next/server';

export function proxy(request: NextRequest) {
  // AUTH_DISABLED=true (server .env, read at request time): the owner chose open access; the API agrees.
  if (process.env.AUTH_DISABLED === 'true') return NextResponse.next();
  if (!request.cookies.get('odd_session')) {
    const url = new URL('/login', request.url);
    url.searchParams.set('next', request.nextUrl.pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

// /api must stay excluded: when this proxy runs on a request, Next.js buffers its body and passes on only the first
// 10 MB (proxyClientMaxBodySize) with a warning, which would silently cut uploads (lib/proxyMatcher.test.ts).
export const config = {
  matcher: ['/((?!login|api|_next/static|_next/image|favicon.ico).*)'],
};
