"""Dependency-free scaffold job runner.

This module intentionally avoids FastAPI imports so it can be exercised in CI
without installing service dependencies. The API layer wraps these functions.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


def create_scaffold_result(job: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic scaffold AnalysisResult for a valid-looking job."""

    required = {"schema_version", "job_id", "mode", "scenario", "rf_profile"}
    missing = sorted(required - set(job))
    if missing:
        raise ValueError(f"AnalysisJob missing required fields: {missing}")

    target_area = job["scenario"].get("target_area", {})
    coordinates = _candidate_coordinate_from_target(target_area)

    return {
        "schema_version": "analysis-result/v1",
        "job_id": job["job_id"],
        "state": "complete",
        "mode": job["mode"],
        "engine": {
            "name": "scaffold",
            "version": "phase1",
            "adapter_version": "none",
        },
        "assumptions": {
            "source_job_schema": job["schema_version"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "note": "Scaffold result. RF modelling is not yet run by the API service.",
        },
        "candidates": [
            {
                "candidate_id": "candidate_scaffold_001",
                "rank": 1,
                "location": {
                    "type": "Point",
                    "coordinates": coordinates,
                },
                "suitability_score": 50.0,
                "confidence": "low",
                "explanation": [
                    "Scaffold candidate returned by the Phase 1 API spine.",
                    "Do not use for RF or operational decisions.",
                ],
            }
        ],
        "artifacts": [],
    }


def _candidate_coordinate_from_target(target_area: dict[str, Any]) -> list[float]:
    """Pick a stable point near the first coordinate in a GeoJSON polygon."""

    fallback = [0.0, 0.0]
    if target_area.get("type") != "Polygon":
        return fallback

    coordinates = deepcopy(target_area.get("coordinates"))
    try:
        ring = coordinates[0]
        first = ring[0]
        second = ring[1]
        lon = (float(first[0]) + float(second[0])) / 2.0
        lat = (float(first[1]) + float(second[1])) / 2.0
        return [lon, lat]
    except (IndexError, TypeError, ValueError):
        return fallback
