// Route protection: dashboard pages need the session cookie, otherwise the visitor is sent to /login. This is a
// convenience redirect; the API validates the signed session on every request, so a forged cookie gets nothing.
import {NextResponse} from 'next/server';
import type {NextRequest} from 'next/server';

export function proxy(request: NextRequest) {
  if (!request.cookies.get('odd_session')) {
    const url = new URL('/login', request.url);
    url.searchParams.set('next', request.nextUrl.pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!login|api|_next/static|_next/image|favicon.ico).*)'],
};
