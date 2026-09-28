#!/usr/bin/env python3
"""Basic schema/sample consistency checks without third-party dependencies."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def require_keys(document: dict, keys: list[str], label: str) -> None:
    missing = [key for key in keys if key not in document]
    if missing:
        raise AssertionError(f"{label} missing required keys: {missing}")


def main() -> None:
    schemas = [
        ROOT / "analysis-job.schema.json",
        ROOT / "analysis-result.schema.json",
        ROOT / "rf-profile.schema.json",
    ]
    for schema_path in schemas:
        schema = load_json(schema_path)
        require_keys(schema, ["$schema", "$id", "title", "type"], schema_path.name)

    job = load_json(ROOT / "samples" / "analysis-job.sample.json")
    require_keys(
        job,
        ["schema_version", "job_id", "created_at", "mode", "scenario", "rf_profile", "analysis", "datasets"],
        "analysis-job.sample.json",
    )
    if job["schema_version"] != "analysis-job/v1":
        raise AssertionError("Unexpected AnalysisJob schema_version")
    if job["mode"] not in {"connected", "edge", "offline"}:
        raise AssertionError("Unexpected AnalysisJob mode")

    result = load_json(ROOT / "samples" / "analysis-result.sample.json")
    require_keys(
        result,
        ["schema_version", "job_id", "state", "mode", "engine", "assumptions", "candidates", "artifacts"],
        "analysis-result.sample.json",
    )
    if result["schema_version"] != "analysis-result/v1":
        raise AssertionError("Unexpected AnalysisResult schema_version")
    if result["job_id"] != job["job_id"]:
        raise AssertionError("Sample job/result IDs do not match")

    print("schema file checks passed")


if __name__ == "__main__":
    main()

