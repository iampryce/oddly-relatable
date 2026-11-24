# Server maintenance: backups and weekly housekeeping

Nothing in this change is installed or run automatically. The owner installs it after this PR is merged and deployed, following the steps below.

## What changes
- **Nightly backups are removed (2026-11-23, after the disk filled up). Only deploy-time backups exist now.**
  - `deploy.sh` runs `deploy/backup.sh` before every deploy (database dump and media, with checksums) and keeps the newest 3 complete ones. `restore.sh` also makes one before it restores. Nothing else makes a backup: there is no cron line, systemd timer or scheduler in the studio for it.
  - The nightly entry was deleted from the installed `/etc/cron.d/oddstudio` and from the repo copy `deploy/cron.d-oddstudio`. The installed file before the change is kept as `/root/oddstudio.cron.2026-11-23.bak`.
  - `backup.sh` still accepts `BACKUP_KIND=nightly`, and `maintenance.sh` and `restore.sh` still handle any `-nightly` folders and dumps left from before.
  - Without nightly backups, the database's history goes back only as far as the oldest kept deploy-time backup, and no new dumps go to `db-dumps/`.
  - **To add them back** (first check there is room: about 2.5 GB per backup plus 2 GB left free, times the number kept): add this line to `/etc/cron.d/oddstudio`, and to `deploy/cron.d-oddstudio` in the repo so that a reinstall keeps it:
    ```
    30 3 * * * root BACKUP_KIND=nightly KEEP_NIGHTLY=7 /srv/stickman/current/studio-app/deploy/backup.sh >> /var/log/oddstudio-backup.log 2>&1
    ```
    Then `grep backup.sh /etc/cron.d/oddstudio` should show it. Cron picks up the change by itself.
- **Retention is counted per kind**, so frequent deploys can't push out the nightly history (when nightly backups are on).
  - Folders are named `<stamp>-nightly` or `<stamp>-deploy`. Older unsuffixed folders count as deploy-time.
  - **Nightly: the newest 7** (`KEEP_NIGHTLY`; none are made now).
  - **Deploy-time** (`deploy.sh`, `restore.sh`): **the newest 3** (2026-11-23, after a deploy-time backup filled the disk). `deploy.sh` sets this itself (`DEPLOY_KEEP_BACKUPS`, default 3), so the `KEEP_DEPLOY=5` that an older installed `ci-deploy.sh` passes is not used; `restore.sh` and `maintenance.sh` use `KEEP_DEPLOY` (default 3).
  - The old `KEEP` variable still works for `backup.sh` run by hand and sets the count for the kind being written.
  - **Only complete backups count** (a folder with `SHA256SUMS`). An incomplete folder is listed by `backup.sh` and `maintenance.sh` and left alone: check it, then remove it by hand.
- **Free space before every backup** (2026-11-23: the 531a40c deploy's backup filled the disk and was left half-written). `backup.sh` first checks that the disk has room for the media volume (without `work/uploads`), the database dump, and 2G left free afterwards (`BACKUP_HEADROOM`); a deploy also asks for 5G for its image build (`DEPLOY_BUILD_FREE`). Without that room it stops with exit code 3 and says what is needed and what is free; nothing is written and no backup is removed, and the deploy stops before building, still on the previous release.
- **A backup that fails part-way removes its own incomplete folder** (only the one it created; it never writes into another backup's folder). The backup it has just made is never removed, and no script ever removes a Docker volume.
- **Weekly housekeeping** (`deploy/maintenance.sh`, Sunday 04:30). Run by hand without options it is a **dry run**: it only lists what it would remove, with sizes. The weekly job runs it as a **dry run** too, both in the repo's `deploy/cron.d-oddstudio` and on the server (owner decision 2026-11-23), so installing the cron file never starts deleting by itself. Only `--apply`, added deliberately (install step 4), removes:
  - everything beyond the **keep-limits** below, which the dry run lists with sizes.
  - database dumps older than 30 days. The newest dump is never removed.
  - deploy logs older than 30 days.

## Keep-limits (2026-11-23)

What `maintenance.sh` keeps; everything else of these kinds is listed by the dry run (with sizes) and removed only by `--apply`:

| What | Kept | Removed by `--apply` |
|---|---|---|
| Release folders (`/srv/stickman/releases`) | the live release, the **previous 2** (`KEEP_PREVIOUS_RELEASES`), and any release a container uses | older folders, and a folder whose deploy failed before it was built ("never built") |
| Docker images | every image a container uses; the live and the **previous** release's `oddstudio-api`/`oddstudio-web` images (so `rollback.sh` works for the previous release); `alpine:3.20`, which the scripts run (`KEEP_IMAGES`) | every other image, with `docker image rm`, and dangling images with `docker image prune`. Never by deleting files under `/var/lib/docker` or `/var/lib/containerd`. |
| Docker build cache | the most recent, up to 10 GB (`BUILD_CACHE_MAX`, owner decision 2026-11-20) | cache older than 7 days (`docker builder prune --filter until=168h`, `BUILD_CACHE_HOURS`), then the least recently used above 10 GB |
| systemd journal | up to **200M** (`JOURNAL_MAX`) | the oldest journal files above that (`journalctl --vacuum-size`) |
| Backups | the **newest 3 complete deploy-time** backups (`KEEP_DEPLOY`; it refuses fewer than 3), the newest 7 nightly ones (none are made now), and always the newest backup | older complete backups. Incomplete folders are listed, never removed. |

- **"Previous" means the deploy order**, not the folders' dates. `deploy.sh` and `rollback.sh` add a line to `/srv/stickman/releases.log` for each release that goes live. Until that log has entries (the first deploys after this change), the order the release images were built stands in for it.
- **Never touched:** Docker volumes, the database, media, running containers, `incoming/`, `shared/` and `repo/`.
- **Listed only, never removed (owner decision 2026-11-23):** upload leftovers in `work/uploads` older than 24 hours, and Bin items older than 30 days. Both are listed by the dry run and by `--apply`, but neither removes them. Remove Bin items with the Bin page's Delete forever or Empty Bin.
- **Rollback after `--apply`:** `rollback.sh` works for the previous release. For an older release, its images are gone, so it says "run deploy.sh" (the images are rebuilt from the release folder, if it is still kept).

## The disk report and the Overview page

- Every run of `maintenance.sh` (dry run or `--apply`) writes `/srv/stickman/reports/disk-report.json` (`REPORT_DIR`). It holds:
  - the disk's size, use and free space;
  - the biggest consumers: backups, release folders, Docker images, Docker build cache, media, database, and logs with the journal;
  - what `--apply` would free (or, after `--apply`, what it freed).

  Each run also appends one line to `reports/disk-history.log`. The weekly cron line also keeps its text output in `/var/log/oddstudio-maintenance.log`.
- The API container mounts `/srv/stickman/reports` read-only (`docker-compose.yml`). The **Overview** page shows:
  - a **Disk** card: used, free and percent, measured live, the same numbers as `df -h`;
  - the consumers from the last report, and how old that report is;
  - a **yellow warning from 80%**;
  - a **red banner from 90%** that names the biggest consumers.

  The page only reads; nothing can be removed from it.
- Before the first report exists, the card shows the live numbers and says to run `maintenance.sh` without options (a dry run) on the server.
- **Upload leftovers** (audio-first Stage 1b): files in `work/uploads` inside the media volume that are older than 24 hours (`UPLOAD_HOURS`). This is a video whose audio was never extracted, or frames sampled for hints. These files are temporary and normally deleted within seconds; `maintenance.sh` lists anything a crash left behind but no longer removes it (2026-11-23). Backups also leave `work/uploads` out.
- **What it never touches:** `/srv/stickman/incoming` (kept on the owner's request), `shared/`, `repo/`, the Docker volumes (database and media) and running containers.
- **Build cache cap** (owner decision 2026-11-20): every deploy builds images and refreshes the Docker build cache, so with frequent deploys nothing in it is ever older than 7 days and the age rule frees nothing; the cache had grown to 45 GB. `--apply` therefore also caps it with `docker builder prune --max-used-space $BUILD_CACHE_MAX` (default 10GB). The 10 GB kept covers the recent layers, so normal deploys stay fast; a deploy after a large dependency change rebuilds those layers and takes a few minutes longer.
- **Deploy lock:** `--apply` holds the deploy lock (`/srv/stickman/.ci-deploy.lock`, the one `ci-deploy.sh` takes). If a deploy is running, the releases, images and build-cache steps are skipped and the rest still runs; a deploy that starts while maintenance holds the lock fails with "another deploy is running" and can be re-run.
- **Projected free space:** the dry run ends with `projected free after --apply`, in the same units as `df -h`, with the share of releases, images, build cache, backups and journal.
- **Tuning:** `KEEP_PREVIOUS_RELEASES`, `KEEP_IMAGES`, `KEEP_NIGHTLY`, `KEEP_DEPLOY`, `DUMP_DAYS`, `LOG_DAYS`, `BUILD_CACHE_HOURS`, `BUILD_CACHE_MAX`, `JOURNAL_MAX` and `REPORT_DIR` are environment variables. (`KEEP_RELEASES` is no longer used.)
- **The 30-day database-dump folder** (`/srv/stickman/db-dumps/`):
  - Each nightly backup also wrote `<stamp>-nightly.dump` with a `.sha256` file there. With nightly backups removed, no new dumps are added; the existing ones age out after 30 days, except the newest, which is kept.
  - Dumps are kept for 30 days (`DUMP_DAYS`), pruned by age by the nightly job and by `maintenance.sh`. The newest dump is never removed, however old it is.
  - Dumps are small (about 135 KB today), so a month of database history costs little, while full backup folders (with about 1.2 GB of media each) are kept for a week.
- **Restore** (`deploy/restore.sh`) takes any backup folder, whichever of the three name forms it has: `…-nightly`, `…-deploy` or an old unsuffixed one. It also takes a dump from `db-dumps/`, restoring the database only after checking the dump's `.sha256`.
  - **Fixed in this change:** the safety backup that `restore.sh` takes first could prune the folder being restored if that was the oldest kept backup. That folder is now protected.
  - **Also fixed:** a relative path broke the media restore. Paths are now made absolute.
- **Simulation:**
  - `deploy/tests/simulate-backups.sh` runs `backup.sh`, `restore.sh` and `maintenance.sh` against a fake `/srv/stickman` with a stub `docker`. It checks retention per kind, the dump folder, and restoring from every kind of backup.
  - `deploy/tests/simulate-maintenance.sh` checks the keep-limits, the dry run, `--apply` and the disk report.

  CI runs both on every PR.

## Install (owner, on the server, after this PR is deployed)

```
# 1. Look at the dry run first: nothing is removed.
/srv/stickman/current/studio-app/deploy/maintenance.sh

# 2. Install the scheduled jobs (weekly housekeeping as a dry run; no nightly backup since 2026-11-23).
#    Installing this file never turns on --apply: that is step 4, done deliberately.
install -o root -g root -m 644 /srv/stickman/current/studio-app/deploy/cron.d-oddstudio /etc/cron.d/oddstudio

# 3. The CI deploy wrapper lives outside the repo: reinstall it (check the hash first). Not needed for the retention:
#    deploy.sh sets the deploy-time count itself (3).
sha256sum /srv/stickman/current/studio-app/deploy/ci-deploy.sh
install -o root -g root -m 755 /srv/stickman/current/studio-app/deploy/ci-deploy.sh /srv/stickman/ci-deploy.sh

# 4. Optional and deliberate: let the weekly job remove things (--apply). Nothing does this for you: the cron file in
#    the repo and on the server runs the dry run, and installing it (step 2) keeps it that way.
#    First read a dry run (step 1) and the Overview page's Disk card; to try --apply once by hand:
#      /srv/stickman/current/studio-app/deploy/maintenance.sh --apply
#    Then make the weekly job apply it (undo: the reverse sed).
sed -i 's#deploy/maintenance.sh >>#deploy/maintenance.sh --apply >>#' /etc/cron.d/oddstudio
# sed -i 's#deploy/maintenance.sh --apply >>#deploy/maintenance.sh >>#' /etc/cron.d/oddstudio   (back to the dry run)
```

- **Logs:** `/var/log/oddstudio-backup.log` and `/var/log/oddstudio-maintenance.log`.
- **Restore examples:**
  - `restore.sh /srv/stickman/backups/20261121T023000Z-nightly --media`: database and media from a full backup.
  - `restore.sh /srv/stickman/db-dumps/20261105T023000Z-nightly.dump`: database only, from up to 30 days back.
- **Check the next morning:** `ls -l /srv/stickman/backups` should show a new folder.
- **Undo:** `rm /etc/cron.d/oddstudio`. Releases, images and backups that were already removed cannot be restored, which is why the job stays a dry run unless step 4 is done deliberately.

## The Bin and cleared jobs

- **Delete moves an item to the Bin** (Characters, single poses, Settings › Sets, an episode's page, comparison clips). The item is hidden everywhere and can be restored for 30 days.
  - **Refused, with the reason:** anything another non-deleted episode uses, locked artwork, and rendered or published episodes.
  - Deleting an episode never deletes its characters or sets.
- **Bin page:** Restore, Delete forever and Empty Bin. The confirm lists exactly what goes and the space freed. Rows and files are removed, only inside the studio's storage and work folders.
- **No automatic purge (2026-11-23):** `maintenance.sh` only lists items that have been in the Bin for more than 30 days (`BIN_DAYS`), even with `--apply`. To remove them, use Delete forever or Empty Bin on the Bin page. `python -m oddstudio.bin purge` still exists to run by hand inside the API container.
- **Backups:** until purged, binned items are still in the database and storage, so backups cover them as before.
- **Bulk actions** show the list and count first:
  - Characters: "Delete all rejected / never-approved poses";
  - Settings › Sets: "Delete unused candidates";
  - Production: "Delete failed episodes".
- **Archive is different** (Characters › Clean up): it only hides a character on that page, and nothing is ever removed.
- **Clearing failed jobs** (Production): per row, or "Clear all failed jobs older than today" with the count first. A cleared job is only hidden; it is never deleted. A failed job that a live episode still needs to retry (the latest of its kind for an episode whose production or publishing failed) stays, with the reason. "Recent jobs" shows the latest 10, with "Show more".
- **Quiet by default** (Production, 2026-11-23): failed jobs older than a day are hidden behind a count ("N older failed job(s) hidden · Show them"), unless a live episode still needs one; succeeded preparation and keying jobs are not listed in Recent jobs (each episode's History has them). Nothing is cleared or deleted by this; it only changes what the lists show. In the Lab, models that cannot run for a line are one "not available · why" line instead of rows.
