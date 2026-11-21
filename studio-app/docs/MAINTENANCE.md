# Server maintenance: nightly backup and weekly housekeeping

Nothing in this change is installed or run automatically. The owner installs it after this PR is merged and deployed, following the steps below.

## What changes
- **Nightly backup** (`deploy/backup.sh` with `BACKUP_KIND=nightly`, 03:30 server time).
  - It dumps the database and archives the media. Until now, backups only ran on deploys; no nightly job was installed.
- **Retention is counted per kind**, so frequent deploys can't push out the nightly history.
  - Folders are named `<stamp>-nightly` or `<stamp>-deploy`. Older unsuffixed folders count as deploy-time.
  - **Nightly: the newest 7** (`KEEP_NIGHTLY`).
  - **Deploy-time** (`deploy.sh`, `restore.sh`): **the newest 5** (`KEEP_DEPLOY`).
  - The old `KEEP` variable still works and sets the count for the kind being written. The currently installed `ci-deploy.sh` passes `KEEP=15` until it is reinstalled (step 3); the new one passes `KEEP_DEPLOY=5`.
- **Weekly housekeeping** (`deploy/maintenance.sh`, Sunday 04:30). Run by hand without options it is a **dry run**: it only lists what it would remove, with sizes. The weekly job runs it with `--apply` (owner decision 2026-11-21, after one verified manual run), which removes:
  - every release folder except the current one, any release a running container uses, and the 5 newest. The `oddstudio-api`/`oddstudio-web` images of removed releases go too, so `rollback.sh` keeps working for every kept release.
  - the unused `hello-world` and `nginx:1.27-alpine` images, but only if no container uses them.
  - dangling images, build cache older than 7 days, and any build cache above 10 GB (`BUILD_CACHE_MAX`; the least recently used goes first).
  - backups beyond the newest 7 nightly and 5 deploy-time, counted separately. The newest backup is never removed.
  - database dumps older than 30 days. The newest dump is never removed.
  - deploy logs older than 30 days, and the systemd journal above 100 MB.
- **Upload leftovers** (audio-first Stage 1b): files in `work/uploads` inside the media volume that are older than 24 hours (`UPLOAD_HOURS`). This is a video whose audio was never extracted, or frames sampled for hints. These files are temporary and normally deleted within seconds; the weekly sweep catches anything a crash left behind. Backups also leave `work/uploads` out.
- **What it never touches:** `/srv/stickman/incoming` (kept on the owner's request), `shared/`, `repo/`, the Docker volumes (database and media, apart from `work/uploads`) and running containers.
- **Build cache cap** (owner decision 2026-11-20): every deploy builds images and refreshes the Docker build cache, so with frequent deploys nothing in it is ever older than 7 days and the age rule frees nothing; the cache had grown to 45 GB. `--apply` therefore also caps it with `docker builder prune --max-used-space $BUILD_CACHE_MAX` (default 10GB). The 10 GB kept covers the recent layers, so normal deploys stay fast; a deploy after a large dependency change rebuilds those layers and takes a few minutes longer.
- **Deploy lock:** `--apply` holds the deploy lock (`/srv/stickman/.ci-deploy.lock`, the one `ci-deploy.sh` takes). If a deploy is running, the releases, images and build-cache steps are skipped and the rest still runs; a deploy that starts while maintenance holds the lock fails with "another deploy is running" and can be re-run.
- **Projected free space:** the dry run ends with `projected free after --apply`, in the same units as `df -h`, counting the releases it would remove, the images no container uses, and the build cache above the cap.
- **Tuning:** `KEEP_RELEASES`, `KEEP_NIGHTLY`, `KEEP_DEPLOY`, `DUMP_DAYS`, `LOG_DAYS`, `BUILD_CACHE_HOURS`, `BUILD_CACHE_MAX` and `JOURNAL_MAX` are environment variables.
- **The 30-day database-dump folder** (`/srv/stickman/db-dumps/`):
  - Each nightly backup also writes `<stamp>-nightly.dump` with a `.sha256` file there.
  - Dumps are kept for 30 days (`DUMP_DAYS`), pruned by age by the nightly job and by `maintenance.sh`. The newest dump is never removed, however old it is.
  - Dumps are small (about 135 KB today), so a month of database history costs little, while full backup folders (with about 1.2 GB of media each) are kept for a week.
- **Restore** (`deploy/restore.sh`) takes any backup folder, whichever of the three name forms it has: `…-nightly`, `…-deploy` or an old unsuffixed one. It also takes a dump from `db-dumps/`, restoring the database only after checking the dump's `.sha256`.
  - **Fixed in this change:** the safety backup that `restore.sh` takes first could prune the folder being restored if that was the oldest kept backup. That folder is now protected.
  - **Also fixed:** a relative path broke the media restore. Paths are now made absolute.
- **Simulation:** `deploy/tests/simulate-backups.sh` runs `backup.sh`, `restore.sh` and `maintenance.sh` against a fake `/srv/stickman` with a stub `docker`. It checks retention per kind, the dump folder, and restoring from every kind of backup. CI runs it on every PR.

## Install (owner, on the server, after this PR is deployed)

```
# 1. Look at the dry run first: nothing is removed.
/srv/stickman/current/studio-app/deploy/maintenance.sh

# 2. Install the scheduled jobs (nightly backup; weekly housekeeping with --apply).
install -o root -g root -m 644 /srv/stickman/current/studio-app/deploy/cron.d-oddstudio /etc/cron.d/oddstudio

# 3. The CI deploy wrapper lives outside the repo: reinstall it so deploys keep 5 deploy-time backups (check the hash first).
sha256sum /srv/stickman/current/studio-app/deploy/ci-deploy.sh
install -o root -g root -m 755 /srv/stickman/current/studio-app/deploy/ci-deploy.sh /srv/stickman/ci-deploy.sh

# 4. An installed cron file from before 2026-11-21 still runs the dry run: make it act (undo: the reverse sed)
sed -i 's#deploy/maintenance.sh >>#deploy/maintenance.sh --apply >>#' /etc/cron.d/oddstudio
# sed -i 's#deploy/maintenance.sh --apply >>#deploy/maintenance.sh >>#' /etc/cron.d/oddstudio   (back to the dry run)
```

- **Logs:** `/var/log/oddstudio-backup.log` and `/var/log/oddstudio-maintenance.log`.
- **Restore examples:**
  - `restore.sh /srv/stickman/backups/20261121T023000Z-nightly --media`: database and media from a full backup.
  - `restore.sh /srv/stickman/db-dumps/20261105T023000Z-nightly.dump`: database only, from up to 30 days back.
- **Check the next morning:** `ls -l /srv/stickman/backups` should show a new folder.
- **Undo:** `rm /etc/cron.d/oddstudio`. Releases, images and backups that were already removed cannot be restored, which is why the job stays a dry run until step 4.
