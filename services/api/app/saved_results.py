"""File-backed saved analysis results for the browser MVP."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def default_results_root(project_root: Path) -> Path:
    return project_root / ".cache" / "rf-results"


def save_result(results_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ValueError("Saved result payload must include a result object.")

    now = datetime.now(timezone.utc)
    incident_number = _clean_label(str(payload.get("incident_number") or "unfiled"))
    name = _clean_label(str(payload.get("name") or _default_name(result, now)))
    location = _clean_label(str(payload.get("location") or _default_location(result)))
    description = str(payload.get("description") or "").strip()

    incident_id = _slug(incident_number, fallback="unfiled")
    analysis_id = _unique_analysis_id(results_root / incident_id, now, name)
    analysis_dir = _safe_child(results_root, incident_id, analysis_id)
    analysis_dir.mkdir(parents=True, exist_ok=False)

    manifest = {
        "schema_version": "saved-analysis/v1",
        "analysis_id": analysis_id,
        "incident_number": incident_number,
        "incident_id": incident_id,
        "name": name,
        "location": location,
        "description": description,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "result_file": "result.json",
        "relative_path": f"{incident_id}/{analysis_id}",
        "summary": _result_summary(result),
    }

    _write_json(analysis_dir / "result.json", result)
    _write_json(analysis_dir / "manifest.json", manifest)
    return manifest


def list_results(results_root: Path) -> dict[str, Any]:
    results_root.mkdir(parents=True, exist_ok=True)
    manifests: list[dict[str, Any]] = []
    for incident_dir in sorted(path for path in results_root.iterdir() if path.is_dir()):
        for analysis_dir in sorted(path for path in incident_dir.iterdir() if path.is_dir()):
            manifest = _read_manifest(analysis_dir)
            if manifest:
                manifests.append(manifest)

    manifests.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
    incidents: dict[str, dict[str, Any]] = {}
    for manifest in manifests:
        incident_id = str(manifest.get("incident_id") or "unfiled")
        incident = incidents.setdefault(
            incident_id,
            {
                "incident_id": incident_id,
                "incident_number": manifest.get("incident_number") or incident_id,
                "analysis_count": 0,
                "analyses": [],
            },
        )
        incident["analysis_count"] += 1
        incident["analyses"].append(manifest)

    return {
        "schema_version": "saved-analysis-list/v1",
        "storage_root": str(results_root),
        "incidents": list(incidents.values()),
        "results": manifests,
    }


def load_result(results_root: Path, incident_id: str, analysis_id: str) -> dict[str, Any]:
    analysis_dir = _safe_child(results_root, _require_safe_id(incident_id), _require_safe_id(analysis_id))
    manifest = _read_manifest(analysis_dir)
    if not manifest:
        raise FileNotFoundError("Saved analysis manifest was not found.")
    result_file = _require_safe_id(str(manifest.get("result_file") or "result.json"))
    result_path = analysis_dir / result_file
    if not result_path.exists():
        raise FileNotFoundError("Saved analysis result was not found.")
    return {
        "manifest": manifest,
        "result": json.loads(result_path.read_text(encoding="utf-8")),
    }


def delete_result(results_root: Path, incident_id: str, analysis_id: str) -> dict[str, Any]:
    safe_incident_id = _require_safe_id(incident_id)
    safe_analysis_id = _require_safe_id(analysis_id)
    analysis_dir = _safe_child(results_root, safe_incident_id, safe_analysis_id)
    if not analysis_dir.exists() or not analysis_dir.is_dir():
        raise FileNotFoundError("Saved analysis was not found.")
    shutil.rmtree(analysis_dir)
    incident_dir = _safe_child(results_root, safe_incident_id)
    try:
        if incident_dir.exists() and incident_dir.is_dir() and not any(incident_dir.iterdir()):
            incident_dir.rmdir()
    except OSError:
        pass
    return {
        "deleted": True,
        "incident_id": safe_incident_id,
        "analysis_id": safe_analysis_id,
    }


def update_result(results_root: Path, incident_id: str, analysis_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    safe_incident_id = _require_safe_id(incident_id)
    safe_analysis_id = _require_safe_id(analysis_id)
    analysis_dir = _safe_child(results_root, safe_incident_id, safe_analysis_id)
    manifest = _read_manifest(analysis_dir)
    if not manifest:
        raise FileNotFoundError("Saved analysis manifest was not found.")

    result_file = _require_safe_id(str(manifest.get("result_file") or "result.json"))
    result_path = analysis_dir / result_file
    if not result_path.exists():
        raise FileNotFoundError("Saved analysis result was not found.")

    result = json.loads(result_path.read_text(encoding="utf-8"))
    if isinstance(payload.get("result"), dict):
        result = payload["result"]

    incident_number = _clean_label(str(payload.get("incident_number") or manifest.get("incident_number") or "unfiled"))
    name = _clean_label(str(payload.get("name") or manifest.get("name") or _default_name(result, datetime.now(timezone.utc))))
    location = _clean_label(str(payload.get("location") or manifest.get("location") or _default_location(result)))
    description = str(payload.get("description", manifest.get("description") or "") or "").strip()
    new_incident_id = _slug(incident_number, fallback="unfiled")

    new_analysis_dir = _safe_child(results_root, new_incident_id, safe_analysis_id)
    if new_analysis_dir != analysis_dir:
        if new_analysis_dir.exists():
            raise ValueError("A saved analysis with this identifier already exists in the target folder.")
        new_analysis_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(analysis_dir), str(new_analysis_dir))
        old_incident_dir = _safe_child(results_root, safe_incident_id)
        try:
            if old_incident_dir.exists() and old_incident_dir.is_dir() and not any(old_incident_dir.iterdir()):
                old_incident_dir.rmdir()
        except OSError:
            pass
        analysis_dir = new_analysis_dir
        result_path = analysis_dir / result_file

    manifest.update(
        {
            "incident_number": incident_number,
            "incident_id": new_incident_id,
            "name": name,
            "location": location,
            "description": description,
            "result_file": result_file,
            "relative_path": f"{new_incident_id}/{safe_analysis_id}",
            "summary": _result_summary(result),
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    )

    _write_json(result_path, result)
    _write_json(analysis_dir / "manifest.json", manifest)
    return manifest


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _read_manifest(analysis_dir: Path) -> dict[str, Any] | None:
    manifest_path = analysis_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(manifest, dict):
        return None
    return manifest


def _safe_child(root: Path, *parts: str) -> Path:
    root = root.resolve()
    path = root.joinpath(*parts).resolve()
    if path != root and root not in path.parents:
        raise ValueError("Saved result path escapes the configured storage root.")
    return path


def _require_safe_id(value: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("Invalid saved result identifier.")
    return value


def _unique_analysis_id(incident_dir: Path, now: datetime, name: str) -> str:
    base = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{_slug(name, fallback='analysis')}"
    candidate = f"{base}-{uuid4().hex[:8]}"
    while (incident_dir / candidate).exists():
        candidate = f"{base}-{uuid4().hex[:8]}"
    return candidate


def _slug(value: str, fallback: str) -> str:
    slug = SAFE_ID_RE.sub("-", value.strip()).strip("._-").lower()
    return slug[:80] or fallback


def _clean_label(value: str) -> str:
    return " ".join(value.strip().split())[:180]


def _default_name(result: dict[str, Any], now: datetime) -> str:
    candidate = (result.get("candidates") or [{}])[0]
    if isinstance(candidate, dict) and candidate.get("name"):
        return str(candidate["name"])
    return f"RF analysis {now.strftime('%Y-%m-%d %H:%M UTC')}"


def _default_location(result: dict[str, Any]) -> str:
    rf = result.get("rf_profile") or {}
    lat = rf.get("target_lat")
    lon = rf.get("target_lon")
    if isinstance(lat, (float, int)) and isinstance(lon, (float, int)):
        return f"{lat:.5f}, {lon:.5f}"
    return str(rf.get("target_name") or "unknown location")


def _result_summary(result: dict[str, Any]) -> dict[str, Any]:
    rf = result.get("rf_profile") or {}
    assessment = result.get("assessment") or {}
    candidates = result.get("candidates") or []
    top_candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    return {
        "profile": rf.get("profile"),
        "frequency_mhz": rf.get("frequency_mhz"),
        "target_lat": rf.get("target_lat"),
        "target_lon": rf.get("target_lon"),
        "target_radius_km": rf.get("target_radius_km"),
        "target_area_sq_km": rf.get("target_area_sq_km"),
        "search_radius_km": rf.get("search_radius_km"),
        "service_profile": rf.get("service_profile"),
        "deployment_profile": rf.get("deployment_profile"),
        "assessment_status": assessment.get("status"),
        "ok_candidate_count": assessment.get("ok_candidate_count"),
        "top_candidate": {
            "name": top_candidate.get("name"),
            "score": top_candidate.get("suitability_score"),
            "two_way_coverage_pct": top_candidate.get("coverage_pct"),
            "uplink_coverage_pct": top_candidate.get("uplink_coverage_pct"),
            "service_ok": top_candidate.get("service_ok"),
        },
    }
