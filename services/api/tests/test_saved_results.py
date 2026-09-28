#!/usr/bin/env python3
"""Checks for file-backed saved analysis persistence."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.saved_results import delete_result, list_results, load_result, save_result, update_result  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        result = {
            "schema_version": "mvp-analysis/v2",
            "mode": "local-real-itm",
            "rf_profile": {
                "profile": "VHF",
                "frequency_mhz": 150.0,
                "target_lat": -31.9523,
                "target_lon": 116.164,
                "target_radius_km": 2.0,
                "target_area_sq_km": 12.566,
                "search_radius_km": 3.0,
                "service_profile": "operational_portable",
                "deployment_profile": "pushup_mast_lifepo4",
            },
            "assessment": {"status": "two_way_portable_ok_found", "ok_candidate_count": 1},
            "candidates": [
                {
                    "name": "Mundaring Weir Road high point",
                    "suitability_score": 93.2,
                    "coverage_pct": 100.0,
                    "uplink_coverage_pct": 100.0,
                    "service_ok": True,
                }
            ],
        }

        manifest = save_result(
            root,
            {
                "incident_number": "INC 2026/001",
                "name": "Portable valley check",
                "location": "Mundaring",
                "description": "Smoke test result",
                "result": result,
            },
        )

        assert manifest["incident_id"] == "inc-2026-001"
        assert manifest["name"] == "Portable valley check"
        assert (root / manifest["relative_path"] / "manifest.json").exists()
        assert (root / manifest["relative_path"] / "result.json").exists()

        listing = list_results(root)
        assert listing["storage_root"] == str(root)
        assert len(listing["incidents"]) == 1
        assert listing["incidents"][0]["analysis_count"] == 1
        assert listing["results"][0]["analysis_id"] == manifest["analysis_id"]

        loaded = load_result(root, manifest["incident_id"], manifest["analysis_id"])
        assert loaded["manifest"]["description"] == "Smoke test result"
        assert loaded["result"]["rf_profile"]["target_radius_km"] == 2.0

        result["candidates"][0]["name"] = "Renamed manual test site"
        updated = update_result(
            root,
            manifest["incident_id"],
            manifest["analysis_id"],
            {
                "incident_number": "INC 2026/002",
                "name": "Edited portable valley check",
                "location": "Demo Valley",
                "description": "Edited metadata",
                "result": result,
            },
        )
        assert updated["incident_id"] == "inc-2026-002"
        assert updated["analysis_id"] == manifest["analysis_id"]
        assert updated["name"] == "Edited portable valley check"
        assert updated["summary"]["top_candidate"]["name"] == "Renamed manual test site"
        assert not (root / manifest["relative_path"]).exists()
        loaded_updated = load_result(root, updated["incident_id"], updated["analysis_id"])
        assert loaded_updated["manifest"]["description"] == "Edited metadata"
        assert loaded_updated["result"]["candidates"][0]["name"] == "Renamed manual test site"

        deleted = delete_result(root, updated["incident_id"], updated["analysis_id"])
        assert deleted["deleted"] is True
        assert not (root / updated["relative_path"]).exists()
        assert not (root / updated["incident_id"]).exists()
        assert list_results(root)["results"] == []

    print("saved result checks passed")


if __name__ == "__main__":
    main()
