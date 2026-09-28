"""Small in-process asynchronous analysis queue for the MVP server.

The queue intentionally uses one worker by default. Analyses are CPU- and
network-heavy, so this prevents a local pilot from multiplying memory and
rf-core load. ``MVP_ANALYSIS_WORKERS`` can raise the limit when the host has
been sized for concurrent work. Job state is process-local and is therefore
appropriate for the single-container MVP, not a multi-instance production
queue.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from threading import Lock
from typing import Any
from uuid import uuid4

from app.mvp_analysis import run_analysis


def _worker_count() -> int:
    try:
        return max(1, int(os.environ.get("MVP_ANALYSIS_WORKERS", "1")))
    except ValueError:
        return 1


_executor = ThreadPoolExecutor(max_workers=_worker_count(), thread_name_prefix="rf-analysis")
_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = Lock()


def submit_analysis(request: dict[str, Any]) -> dict[str, str]:
    """Queue an analysis and return its stable public job identifier."""

    job_id = uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {"status": "queued"}
    try:
        _executor.submit(_run_analysis, job_id, deepcopy(request))
    except Exception as error:  # pragma: no cover - executor failure is defensive
        with _jobs_lock:
            _jobs[job_id] = {"status": "failed", "error": str(error)}
    return {"job_id": job_id, "status": "queued"}


def get_analysis_job(job_id: str) -> dict[str, Any] | None:
    """Return a snapshot suitable for the GET job endpoint."""

    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        return {"job_id": job_id, **deepcopy(job)}


def _run_analysis(job_id: str, request: dict[str, Any]) -> None:
    with _jobs_lock:
        _jobs[job_id] = {"status": "running"}
    try:
        result = run_analysis(request)
    except Exception as error:
        with _jobs_lock:
            _jobs[job_id] = {"status": "failed", "error": str(error)}
        return
    with _jobs_lock:
        _jobs[job_id] = {"status": "complete", "result": result}
