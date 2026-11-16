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
    return [{source: '/:path*', headers: [
      {key: 'X-Frame-Options', value: 'DENY'},
      {key: 'X-Content-Type-Options', value: 'nosniff'},
      {key: 'Referrer-Policy', value: 'same-origin'},
    ]}];
  },
};
