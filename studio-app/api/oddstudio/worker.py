"""Worker process: takes job IDs from Redis and runs them (python -m oddstudio.worker).

Several workers can run at once; each job is claimed atomically in PostgreSQL. On start, jobs left running by a
stopped worker are marked failed (retryable) and queued jobs are re-announced, so a restart never loses work.
"""
from __future__ import annotations

import logging
import signal
import sys

from .config import get_settings
from .db import new_session
from .queue import QUEUE_KEY, recover, redis_client
from .tasks import run_job

log = logging.getLogger("oddstudio.worker")
_stop = False


def _graceful(*_):
    global _stop
    _stop = True


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    s = get_settings()
    r = redis_client()
    signal.signal(signal.SIGTERM, _graceful)
    signal.signal(signal.SIGINT, _graceful)
    if r is None:
        if s.env == "production":
            log.error("REDIS_URL is not set; the production worker needs the queue")
            return 2
        return poll_database()
    with new_session() as db:
        n = recover(db)
    log.info("worker started (env=%s, storage=%s); re-announced %d queued job(s)", s.env, s.storage_backend, n)
    while not _stop:
        item = r.brpop(QUEUE_KEY, timeout=5)
        if not item:
            continue
        job_id = int(item[1])
        with new_session() as db:
            job = run_job(db, job_id)
            if job is not None:
                log.info("job %s %s: %s", job.id, job.kind, job.status if job.status != "failed" else job.error[:200])
    log.info("worker stopped")
    return 0


def poll_database() -> int:
    """Development only (no Redis): pick up queued jobs straight from the database every two seconds."""
    import time
    from .models import Job
    log.warning("REDIS_URL is not set: development mode, polling the database for queued jobs")
    with new_session() as db:
        recover(db)
    while not _stop:
        with new_session() as db:
            ids = [j.id for j in db.query(Job).filter_by(status="queued").order_by(Job.id).limit(10)]
        for job_id in ids:
            with new_session() as db:
                job = run_job(db, job_id)
                if job is not None:
                    log.info("job %s %s: %s", job.id, job.kind, job.status if job.status != "failed" else job.error[:200])
        if not ids:
            time.sleep(2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
