# Security review: Oddly Relatable Studio (pre-deployment)

**Date:** 2026-11-16.
**Scope:** everything under `studio-app/` (API, worker, dashboard, Compose and scripts). The unchanged engine and renderer are covered only where the studio calls them.
**Deployment model reviewed:** single owner; localhost-bound behind an SSH tunnel; not public.

## Findings and status

| # | Area | Finding | Status |
|---|---|---|---|
| 1 | Authentication | Single owner account; PBKDF2-SHA256 (310k iterations) hash from the environment; constant-time comparisons; HMAC-signed session with expiry in an httpOnly, `SameSite=Strict` cookie (`Secure` once on HTTPS) | OK |
| 2 | Sign-in rate limit | The per-client limit keys on the address from `X-Forwarded-For`, which Next.js keeps if a caller sends it, so it could be bypassed | **Fixed:** an added global cap (30 failures per 15 min) bounds guessing however addresses are presented; per-client memory is bounded |
| 3 | Sessions | Tokens are stateless and cannot be revoked one by one | Accepted for one owner. Revoke all sessions by rotating `SESSION_SECRET`; sessions last 12 h by default |
| 4 | CSRF | State changes need JSON bodies and a `SameSite=Strict` cookie; there are no form posts or cross-site requests | OK |
| 5 | XSS | React escapes all content. The only `dangerouslySetInnerHTML` is a static theme script with no user data. A CSP header now restricts sources to the site itself (and S3 media) | **Improved:** CSP added. `'unsafe-inline'` scripts remain because the Next.js App Router bootstrap is inline |
| 6 | Clickjacking and headers | `X-Frame-Options: DENY`, `frame-ancestors 'none'`, `nosniff`, same-origin referrer, `no-store` on API responses | OK |
| 7 | Secrets | API keys and OAuth tokens only in the server environment (`/srv/stickman/shared/.env`, mode 600, git-ignored); `/api/settings` returns presence flags only (tested); none reach the browser bundle | OK |
| 8 | Media access | S3: presigned GET URLs, 1 h default. Local: HMAC-signed, expiring URLs; keys checked against traversal and limited to a safe character set (tested) | OK |
| 9 | Uploads | Character references must be PNG or JPEG under about 9 MB, checked with Pillow before storage | OK. Pillow's decompression-bomb guard applies |
| 10 | Command execution | Engine, FFmpeg, Codex and Piper run with argument lists, never a shell. Prompts go to Codex on stdin, in a read-only sandbox (text) or a temporary folder (images) | OK |
| 11 | Prompt injection | Ideas and scripts are owner-supplied; model output is parsed as JSON and validated by `script_schema` before use; it never runs as code or commands | OK (residual: an odd but valid script, which owner review catches) |
| 12 | Workflow integrity | Every gate is enforced by the API (`workflow.require`); publishing needs typed approval bound to the exact revision and video, re-checked by the upload job; edits withdraw approval (tested) | OK |
| 13 | Network exposure | Postgres, Redis and API have no host ports; only the dashboard binds `127.0.0.1:3000` | **Improved:** the API host port was removed |
| 14 | Containers | Non-root users (uid 10001/10002); worker CPU and memory limits; no Docker socket mounted; no privileged mode | OK |
| 15 | Dependencies | Python and npm versions pinned; lockfile committed; images from official `node`, `postgres` and `redis` | OK. Re-check advisories at each release (`pip-audit`, `npm audit`) |
| 16 | Error handling | Unhandled errors return a generic message; details go to the API log only. Job errors are shown to the owner on purpose | OK |
| 17 | Server | Root login and password SSH authentication were still enabled at the last audit | **Open, outside this app:** hardening per `docs/VPS_PRODUCTION_READINESS.md` before any public exposure |
| 18 | Backups | Nightly `pg_dump` and media archive, checksums, retention, restore script | OK. Off-box copy needs a target (`OFFSITE_S3`), currently **open** |
| 19 | Audit trail | Approvals, rejections and revision requests are append-only, with actor and time | OK |
| 20 | Logging | Job logs contain engine and provider output, not keys. Provider HTTP errors keep at most 500 characters of the response body | OK |

## Before any public exposure (not approved)

1. Domain and TLS reverse proxy that overwrites `X-Forwarded-For`.
2. `COOKIE_SECURE=true`.
3. SSH hardening (#17).
4. Off-box backups (#18).
5. Owner sign-off on this review.
