# Server maintenance: nightly backup and weekly housekeeping

Nothing in this change is installed or run automatically. The owner installs it after this PR is merged and deployed, following the steps below.

## What changes
- **Nightly backup** (`deploy/backup.sh`, 03:30 server time).
  - It dumps the database and archives the media.
  - It keeps the **newest 7** backups. The default `KEEP` is now 7 (was 14), and deploys also keep 7 (`ci-deploy.sh`: was 15).
  - Until now, backups only ran on deploys; no nightly job was installed.
- **Weekly housekeeping** (`deploy/maintenance.sh`, Sunday 04:30). It is a **dry run** by default: it only lists what it would remove, with sizes. With `--apply` it removes:
  - every release folder except the current one, any release a running container uses, and the 5 newest. The `oddstudio-api`/`oddstudio-web` images of removed releases go too, so `rollback.sh` keeps working for every kept release.
  - the unused `hello-world` and `nginx:1.27-alpine` images, but only if no container uses them.
  - dangling images, and build cache older than 7 days.
  - backups beyond the newest 7. The newest one is never removed.
  - deploy logs older than 30 days, and the systemd journal above 100 MB.
- **What it never touches:** `/srv/stickman/incoming` (kept on the owner's request), `shared/`, `repo/`, the Docker volumes (database and media) and running containers.
- **Tuning:** `KEEP_RELEASES`, `KEEP_BACKUPS`, `LOG_DAYS`, `BUILD_CACHE_HOURS` and `JOURNAL_MAX` are environment variables.

## Install (owner, on the server, after this PR is deployed)

```
# 1. Look at the dry run first: nothing is removed.
/srv/stickman/current/studio-app/deploy/maintenance.sh

# 2. Install the scheduled jobs (nightly backup; weekly housekeeping still as a dry run).
install -o root -g root -m 644 /srv/stickman/current/studio-app/deploy/cron.d-oddstudio /etc/cron.d/oddstudio

# 3. The CI deploy wrapper lives outside the repo: reinstall it so deploys keep 7 backups (check the hash first).
sha256sum /srv/stickman/current/studio-app/deploy/ci-deploy.sh
install -o root -g root -m 755 /srv/stickman/current/studio-app/deploy/ci-deploy.sh /srv/stickman/ci-deploy.sh

# 4. Once the weekly reports in /var/log/oddstudio-maintenance.log look right, make it act:
sed -i 's#deploy/maintenance.sh >>#deploy/maintenance.sh --apply >>#' /etc/cron.d/oddstudio
```

- **Logs:** `/var/log/oddstudio-backup.log` and `/var/log/oddstudio-maintenance.log`.
- **Check the next morning:** `ls -l /srv/stickman/backups` should show a new folder.
- **Undo:** `rm /etc/cron.d/oddstudio`. Releases, images and backups that were already removed cannot be restored, which is why the job stays a dry run until step 4.
