# Server maintenance: nightly backup and weekly housekeeping

Nothing in this change is installed or run automatically. The owner installs it after this PR is merged and deployed, following the steps below.

## What changes
- **Nightly backup** (`deploy/backup.sh` with `BACKUP_KIND=nightly`, 03:30 server time).
  - It dumps the database and archives the media. Until now, backups only ran on deploys; no nightly job was installed.
  - **Paused since 2026-11-23** (the disk filled up): line 7 of the installed `/etc/cron.d/oddstudio` is commented out with the prefix `# PAUSED 2026-11-23 (disk full): `. `backup.sh` and the deploy-time backups are unchanged, so every deploy still makes a backup first; the newest 30-day database dump in `db-dumps/` stays as it is. While paused, old-backup cleanup keeps the newest 3 complete backups, nightly or deploy-time. **Re-enable** (once there is room for a backup each night, about 2.5 GB plus 2 GB left free): `sed -i 's|^# PAUSED 2026-11-23 (disk full): ||' /etc/cron.d/oddstudio`, then `grep backup.sh /etc/cron.d/oddstudio` should show the line starting with `30 3 * * *`.
- **Retention is counted per kind**, so frequent deploys can't push out the nightly history.
  - Folders are named `<stamp>-nightly` or `<stamp>-deploy`. Older unsuffixed folders count as deploy-time.
  - **Nightly: the newest 7** (`KEEP_NIGHTLY`).
  - **Deploy-time** (`deploy.sh`, `restore.sh`): **the newest 3** (2026-11-23, after a deploy-time backup filled the disk). `deploy.sh` sets this itself (`DEPLOY_KEEP_BACKUPS`, default 3), so the `KEEP_DEPLOY=5` that an older installed `ci-deploy.sh` passes is not used; `restore.sh` and `maintenance.sh` use `KEEP_DEPLOY` (default 3).
  - The old `KEEP` variable still works for `backup.sh` run by hand and sets the count for the kind being written.
  - **Only complete backups count** (a folder with `SHA256SUMS`). An incomplete folder is listed by `backup.sh` and `maintenance.sh` and left alone: check it, then remove it by hand.
- **Free space before every backup** (2026-11-23: the 531a40c deploy's backup filled the disk and was left half-written). `backup.sh` first checks that the disk has room for the media volume (without `work/uploads`), the database dump, and 2G left free afterwards (`BACKUP_HEADROOM`); a deploy also asks for 5G for its image build (`DEPLOY_BUILD_FREE`). Without that room it stops with exit code 3 and says what is needed and what is free; nothing is written and no backup is removed, and the deploy stops before building, still on the previous release.
- **A backup that fails part-way removes its own incomplete folder** (only the one it created; it never writes into another backup's folder). The backup it has just made is never removed, and no script ever removes a Docker volume.
- **Weekly housekeeping** (`deploy/maintenance.sh`, Sunday 04:30). Run by hand without options it is a **dry run**: it only lists what it would remove, with sizes. The weekly job runs it with `--apply` (owner decision 2026-11-21, after one verified manual run), which removes:
  - every release folder except the current one, any release a running container uses, and the 5 newest. The `oddstudio-api`/`oddstudio-web` images of removed releases go too, so `rollback.sh` keeps working for every kept release.
  - the unused `hello-world` and `nginx:1.27-alpine` images, but only if no container uses them.
  - dangling images, build cache older than 7 days, and any build cache above 10 GB (`BUILD_CACHE_MAX`; the least recently used goes first).
  - backups beyond the newest 7 nightly and 3 deploy-time, counted separately (complete backups only). The newest backup is never removed.
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

# 3. The CI deploy wrapper lives outside the repo: reinstall it (check the hash first). Not needed for the retention:
#    deploy.sh sets the deploy-time count itself (3).
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

## The Bin and cleared jobs

- **Delete moves an item to the Bin** (Characters, single poses, Settings › Sets, an episode's page, comparison clips). The item is hidden everywhere and can be restored for 30 days.
  - **Refused, with the reason:** anything another non-deleted episode uses, locked artwork, and rendered or published episodes.
  - Deleting an episode never deletes its characters or sets.
- **Bin page:** Restore, Delete forever and Empty Bin. The confirm lists exactly what goes and the space freed. Rows and files are removed, only inside the studio's storage and work folders.
- **Weekly purge:** the weekly `maintenance.sh --apply` removes items that have been in the Bin for more than 30 days (`BIN_DAYS`), inside the API container (`python -m oddstudio.bin purge`), and logs each one. The dry run only lists them.
- **Backups:** until purged, binned items are still in the database and storage, so backups cover them as before.
- **Bulk actions** show the list and count first:
  - Characters: "Delete all rejected / never-approved poses";
  - Settings › Sets: "Delete unused candidates";
  - Production: "Delete failed episodes".
- **Archive is different** (Characters › Clean up): it only hides a character on that page, and nothing is ever removed.
- **Clearing failed jobs** (Production): per row, or "Clear all failed jobs older than today" with the count first. A cleared job is only hidden; it is never deleted. A failed job that a live episode still needs to retry (the latest of its kind for an episode whose production or publishing failed) stays, with the reason. "Recent jobs" shows the latest 10, with "Show more".
