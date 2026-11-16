// The dashboard talks only to its own origin: /api/* is forwarded to the FastAPI service on the private network, so
// the browser never needs the API's address or any credentials. API_URL is read at build time (Docker build arg).
const API_URL = process.env.API_URL || 'http://127.0.0.1:8000';

/** @type {import('next').NextConfig} */
export default {
  output: 'standalone',
  poweredByHeader: false,
  reactStrictMode: true,
  async rewrites() {
    return [{source: '/api/:path*', destination: `${API_URL}/api/:path*`}];
  },
  async headers() {
    // Content-Security-Policy: same-origin only, plus S3 presigned media (img/audio/video). Next.js App Router emits
    // inline bootstrap scripts without a nonce, hence 'unsafe-inline' for scripts; no external scripts are allowed.
    const csp = ["default-src 'self'", "script-src 'self' 'unsafe-inline'", "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data: blob: https://*.amazonaws.com", "media-src 'self' blob: https://*.amazonaws.com",
      "connect-src 'self'", "frame-ancestors 'none'", "base-uri 'self'", "form-action 'self'", "object-src 'none'"].join('; ');
    return [{source: '/:path*', headers: [
      {key: 'Content-Security-Policy', value: csp},
      {key: 'X-Frame-Options', value: 'DENY'},
      {key: 'X-Content-Type-Options', value: 'nosniff'},
      {key: 'Referrer-Policy', value: 'same-origin'},
    ]}];
  },
};
