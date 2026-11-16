# Deploying Oddly Relatable Studio

**Status (2026-11-16):** the owner has approved deployment under `/srv/stickman` **in principle**. The conditions are isolated containers, access by SSH tunnel only, nothing public, and no change to the Kids project. **Nothing is deployed yet**; this document is the procedure for when the owner says go.

## 1. What runs where

| Component | Container | Exposed |
|---|---|---|
| PostgreSQL 16 | `oddstudio-postgres-1` | no host port |
| Redis 7 (job dispatch only, AOF) | `oddstudio-redis-1` | no host port |
| API (FastAPI; runs migrations on start) | `oddstudio-api-1` | no host port (dashboard → API on the private network) |
| Worker (engine, FFmpeg, providers) | `oddstudio-worker-1` | none; limited to 3 CPUs / 4 GB |
| Dashboard (Next.js) | `oddstudio-web-1` | `127.0.0.1:3000` only |

**Isolation from the Kids project:**
- Compose project `oddstudio`, so container, network and volume names are all prefixed `oddstudio_`.
- Files live only under `/srv/stickman`.
- Nothing reads or writes `/root/youtube-automation` or any other project.
- No other project's port is used.

**Server facts (read-only audit, 2026-11-16):**
- Ubuntu 24.04, 4 vCPU, 7.8 GB RAM, 92 GB free disk, no GPU.
- Docker 29.9 is installed.
- Only SSH is listening.

## 2. One-time server preparation (owner-approved actions only)

1. **Directories:** `mkdir -p /srv/stickman/{releases,shared,backups} && chmod 700 /srv/stickman/shared /srv/stickman/backups`.
2. **Secrets:** create `/srv/stickman/shared/.env` from `studio-app/deploy/.env.example` (mode 600).
   - `POSTGRES_PASSWORD` and `SESSION_SECRET`: random strings.
   - `OWNER_EMAIL`, and `OWNER_PASSWORD_HASH` from `python -m oddstudio.auth hash`.
   - Leave `COOKIE_SECURE=false` while access is by SSH tunnel over plain HTTP.
   - Optional provider keys (see `VOICE-AND-CASTING.md`).
3. **Nightly backup:** add a root crontab line, or a systemd timer:
   `30 3 * * * /srv/stickman/current/studio-app/deploy/backup.sh >> /srv/stickman/backups/backup.log 2>&1`
4. **Recommended but separate (not done by this deployment):** the SSH hardening listed in `docs/VPS_PRODUCTION_READINESS.md`. That covers a named admin account, key-only login and no root password login.

## 3. Deploy a release

On the workstation, from a clean checkout of the reviewed commit:

```bash
sha=$(git rev-parse --short=12 HEAD)
git archive --format=tar.gz -o "/tmp/oddstudio-$sha.tar.gz" HEAD
scp "/tmp/oddstudio-$sha.tar.gz" <admin>@<server>:/srv/stickman/releases/
ssh <admin>@<server> "cd /srv/stickman/releases && mkdir $sha && tar -xzf oddstudio-$sha.tar.gz -C $sha && rm oddstudio-$sha.tar.gz \
  && $sha/studio-app/deploy/deploy.sh $sha"
```

`deploy.sh` does the following:
1. Backs up the running release, if there is one.
2. Builds images tagged `oddstudio-api:<sha>` and `oddstudio-web:<sha>`.
3. Switches `/srv/stickman/current`.
4. Starts the containers. The API applies database migrations on start.
5. Waits for `/api/health`. If the release does not become healthy, it switches back to the previous release automatically.

**First use:** open the tunnel with `ssh -L 3000:127.0.0.1:3000 <admin>@<server>`, then browse to http://127.0.0.1:3000 and sign in.

The first build downloads base images and packages: Debian, Node and Python packages, and Postgres and Redis images (already present). Expect about 3 GB of disk for images and roughly 10 minutes.

## 4. Backups

`deploy/backup.sh`, run nightly and before every deploy, writes `/srv/stickman/backups/<UTC stamp>/` with:
- `db.dump`: `pg_dump -Fc` of all workflow state;
- `media.tar.gz`: the `work_data` volume, which holds local media storage;
- `SHA256SUMS`.

**Retention:** the newest 14. Change it with `KEEP=`.
- Redis is not backed up: it only carries job IDs, and queued jobs are re-announced from PostgreSQL when a worker starts.
- When S3 storage is used, media are in S3; enable bucket versioning and lifecycle rules there.

**Off-box copy:** set `OFFSITE_S3=s3://<bucket>/<prefix>` for the cron job. It needs the AWS CLI and credentials limited to that prefix.
- The VPS readiness review requires an off-box target. Until one is configured, backups live only on the server's disk, and the owner can fetch them over SSH (`scp`).

**Test a restore** at least once after the first deploy, on a copy if possible:

```bash
/srv/stickman/current/studio-app/deploy/restore.sh /srv/stickman/backups/<stamp> --media
```

`restore.sh` verifies the checksums and first backs up the current state. It then stops the app, restores the database (and the media with `--media`) and starts the app again.

## 5. Rollback

- **Code only** (normal case): `rollback.sh <previous sha>`. The previous images are still on the host, so this is a restart, not a rebuild.
- **Code and data:** `rollback.sh <previous sha> /srv/stickman/backups/<stamp before the bad deploy>`.
- **Migrations:**
  - Every schema change is an Alembic migration.
  - The current migrations are additive: `0001` is the initial schema; `0002` adds two character columns with defaults. Older code keeps working on the newer schema.
  - A future migration that removes or renames something must say so in its docstring. Rolling back past it then needs the pre-deploy backup, which `deploy.sh` always takes.
- **Old releases:** keep the last 3 release folders and images. `docker image prune` only removes untagged images.

## 6. Operations

| Task | Command (on the server) |
|---|---|
| Status | `docker compose -p oddstudio ps` |
| Logs | `docker compose -p oddstudio logs -f --tail=200 api worker` |
| Restart the worker after a provider change | `docker compose -p oddstudio restart worker` |
| Disk | `docker system df`, `du -sh /srv/stickman/backups` |
| Stop everything | `docker compose -p oddstudio stop` (data stays in volumes) |

## 7. Optional: a worker on the owner's workstation (Codex CLI)

Codex CLI runs only where it is installed and signed in, which is the owner's PC, not the containers. To use Codex for scripts and poses from the server deployment, run a worker on the PC that reaches PostgreSQL and Redis through the SSH tunnel. That needs three things:
1. **Ports:** a Compose override binding Postgres and Redis to `127.0.0.1` on the server.
2. **Tunnels:** `ssh -L 5432:127.0.0.1:5432 -L 6379:127.0.0.1:6379`.
3. **S3 storage:** `STORAGE_BACKEND=s3`, so both workers see the same media; local storage is per machine.

Until then, use an API provider (OpenAI or Anthropic) on the server.

## 8. Going public later (not approved)

Going public needs:
- a domain and a TLS reverse proxy that sets `X-Forwarded-For` itself, overwriting anything the client sent;
- `COOKIE_SECURE=true`;
- the SSH hardening above;
- an owner security sign-off.

See `SECURITY-REVIEW.md`.
