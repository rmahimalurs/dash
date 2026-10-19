"""Generic in-memory background-job tracker for long bulk operations (org
invites, Copilot seat assignment, repo creation) that must report live
progress instead of blocking one HTTP request for as long as hundreds or
thousands of sequential GitHub calls take. Same shape as the per-env
sweep state in controller_users.py, generalized across job kinds instead
of one dict per env.

Job state lives in-process only (not persisted), same tradeoff the
existing sweep state already accepts: a backend restart loses in-flight
jobs, which is acceptable for a kicked-off batch the operator can re-run.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid

logger = logging.getLogger(__name__)

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()
_JOB_TTL_SECONDS = 3600  # how long a finished job's state is kept for polling


def new_job(kind: str, username: str, total: int) -> str:
    _evict_stale()
    job_id = uuid.uuid4().hex[:12]
    with _LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "kind": kind,
            "username": username,
            "status": "running",  # running | done | error
            "total": total,
            "done": 0,
            "current": None,
            "results": [],
            "extra": {},
            "started_at": time.time(),
            "finished_at": None,
            "error": None,
        }
    return job_id


def get_job(job_id: str) -> dict | None:
    """A snapshot safe to read (e.g. serialize to JSON) after the lock is
    released -- `results` and `extra` are copied too, not just referenced,
    so a worker thread appending to the live job can't mutate a list the
    caller is still reading."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        return {**job, "results": list(job["results"]), "extra": dict(job["extra"])}


def set_current(job_id: str, current: str | None) -> None:
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id]["current"] = current


def increment_done(job_id: str, by: int = 1) -> None:
    """For jobs whose progress isn't one-result-per-done (e.g. Copilot seat
    assignment, where the preflight check and the post-write verification
    are each one call per handle around a single bulk write in between).
    Clamped at total, since a retry pass can call this more times than
    there are items left to account for."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job:
            job["done"] = min(job["done"] + by, job["total"])


def append_result(job_id: str, result: dict) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job:
            job["results"].append(result)
            job["done"] = len(job["results"])


def replace_results(job_id: str, results: list[dict]) -> None:
    """Swap in a full results list -- used after the final retry-only-failed
    pass, which re-attempts some already-recorded items and needs to update
    their entries in place rather than append duplicates."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job:
            job["results"] = results
            job["done"] = len(results)


def set_extra(job_id: str, **fields) -> None:
    """Feature-specific summary fields (e.g. invited_by, org) alongside the
    generic progress/results shape."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job:
            job["extra"].update(fields)


def finish(job_id: str, error: str | None = None) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job:
            job["status"] = "error" if error else "done"
            job["finished_at"] = time.time()
            job["current"] = None
            job["error"] = error


def run_in_background(target, *args, **kwargs) -> None:
    threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True).start()


def _evict_stale() -> None:
    cutoff = time.time() - _JOB_TTL_SECONDS
    with _LOCK:
        stale = [jid for jid, j in _JOBS.items() if j["finished_at"] and j["finished_at"] < cutoff]
        for jid in stale:
            del _JOBS[jid]
