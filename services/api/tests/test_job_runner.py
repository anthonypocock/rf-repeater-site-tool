#!/usr/bin/env python3
"""Tests for the scaffold job runner."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.job_runner import create_scaffold_result  # noqa: E402


def load_job() -> dict:
    path = ROOT / "packages" / "schemas" / "samples" / "analysis-job.sample.json"
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> None:
    job = load_job()
    result = create_scaffold_result(job)

    assert result["schema_version"] == "analysis-result/v1"
    assert result["job_id"] == job["job_id"]
    assert result["state"] == "complete"
    assert result["mode"] == job["mode"]
    assert result["candidates"][0]["rank"] == 1
    assert result["candidates"][0]["confidence"] == "low"

    try:
        create_scaffold_result({"job_id": "bad"})
    except ValueError:
        pass
    else:
        raise AssertionError("missing required fields should fail")

    print("api job runner checks passed")


if __name__ == "__main__":
    main()

