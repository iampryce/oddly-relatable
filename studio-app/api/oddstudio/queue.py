"""Job queue: PostgreSQL holds the job (status, attempts, logs, results); Redis only carries job IDs to workers.

Because the database is the source of truth, nothing is lost if Redis restarts: a worker re-announces queued jobs on
start (`recover`). A worker claims a job with a conditional UPDATE (queued -> running), so a job ID delivered twice
still runs once.
"""
from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Event, Job, now

QUEUE_KEY = "oddstudio:jobs"
_redis = None


def redis_client():
    global _redis
    url = get_settings().redis_url
    if not url:
        return None
    if _redis is None:
        import redis
        _redis = redis.Redis.from_url(url, socket_timeout=30, socket_connect_timeout=5)
    return _redis


def reset_queue() -> None:
    global _redis
    _redis = None


def enqueue(db: Session, kind: str, *, episode_id=None, scene_id=None, character_id=None, revision=1, payload=None) -> Job:
    job = Job(kind=kind, episode_id=episode_id, scene_id=scene_id, character_id=character_id, revision=revision,
              payload=payload or {}, status="queued")
    db.add(job)
    db.flush()
    db.add(Event(episode_id=episode_id, kind="job", message=f"Queued {kind} (job {job.id})"))
    db.commit()
    announce(job.id)
    return job


def announce(job_id: int) -> bool:
    r = redis_client()
    if r is None:
        return False
    r.lpush(QUEUE_KEY, job_id)
    return True


def claim(db: Session, job_id: int) -> Job | None:
    res = db.execute(update(Job).where(Job.id == job_id, Job.status == "queued")
                     .values(status="running", started_at=now(), attempts=Job.attempts + 1, error=""))
    db.commit()
    if res.rowcount != 1:
        return None
    return db.get(Job, job_id)


def recover(db: Session) -> int:
    """On worker start: jobs left 'running' by a stopped worker become failed (retryable); queued jobs are re-announced."""
    stale = db.query(Job).filter(Job.status == "running").all()
    for j in stale:
        j.status, j.error, j.finished_at = "failed", "The worker stopped while this job was running. Retry it.", now()
    db.commit()
    queued = [j.id for j in db.query(Job).filter(Job.status == "queued").order_by(Job.id)]
    for jid in queued:
        announce(jid)
    return len(queued)
