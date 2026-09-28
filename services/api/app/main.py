"""FastAPI wrapper for the scaffold job runner."""

from __future__ import annotations

from typing import Any

from app.job_runner import create_scaffold_result

try:
    from fastapi import FastAPI
except ImportError as exc:  # pragma: no cover - exercised only without deps
    raise RuntimeError(
        "FastAPI is not installed. Install services/api/requirements.txt to run the API service."
    ) from exc


app = FastAPI(title="RF Repeater Tool API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/scenarios/{scenario_id}/jobs")
def submit_job(scenario_id: str, job: dict[str, Any]) -> dict[str, Any]:
    if job.get("scenario", {}).get("scenario_id") != scenario_id:
        job = dict(job)
        job.setdefault("scenario", {})
        job["scenario"]["scenario_id"] = scenario_id
    return create_scaffold_result(job)

