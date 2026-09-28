#!/usr/bin/env python3
"""Checks for the asynchronous MVP analysis lifecycle."""

from __future__ import annotations

import sys
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.analysis_jobs import get_analysis_job, submit_analysis  # noqa: E402


def _wait_for_status(job_id: str, expected: str) -> dict:
    deadline = monotonic() + 2.0
    while monotonic() < deadline:
        job = get_analysis_job(job_id)
        if job and job["status"] == expected:
            return job
        sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {expected}")


def main() -> None:
    started = Event()
    release = Event()

    def fake_analysis(request: dict) -> dict:
        started.set()
        assert release.wait(2.0)
        return {"request": request, "answer": "complete"}

    with patch("app.analysis_jobs.run_analysis", side_effect=fake_analysis):
        accepted = submit_analysis({"profile": "VHF"})
        assert accepted["job_id"]
        assert accepted["status"] == "queued"
        assert started.wait(2.0)
        running = _wait_for_status(accepted["job_id"], "running")
        assert running["job_id"] == accepted["job_id"]
        release.set()
        complete = _wait_for_status(accepted["job_id"], "complete")
        assert complete["result"]["answer"] == "complete"

    with patch("app.analysis_jobs.run_analysis", side_effect=RuntimeError("test failure")):
        failed = submit_analysis({})
        error = _wait_for_status(failed["job_id"], "failed")
        assert error["error"] == "test failure"

    assert get_analysis_job("missing-job") is None
    print("analysis job lifecycle checks passed")


if __name__ == "__main__":
    main()
