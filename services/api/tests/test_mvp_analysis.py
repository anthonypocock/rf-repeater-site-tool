#!/usr/bin/env python3
"""Smoke tests for the real-world MVP analysis."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.mvp_analysis import (  # noqa: E402
    Candidate,
    ItmBatchWorker,
    Road,
    _candidate_name,
    _candidate_points_from_roads,
    _candidate_rank_key,
    _candidate_reference_road,
    _clean_road_name,
    _link_margin,
    _normalise_rf_request,
    _path_loss_itm,
    _recommendation_policy,
    _score_candidate_rf,
    _terrain_score,
    _two_phase_shortlist,
    destination_point,
    run_analysis,
)


def _candidate(**overrides: object) -> Candidate:
    base: dict[str, object] = {
        "candidate_id": "test",
        "name": "Test candidate",
        "lat": -32.0,
        "lon": 116.0,
        "road_name": "Test Rd",
        "road_class": "track",
        "surface": "unknown",
        "elevation_m": 200.0,
        "local_relief_m": 20.0,
        "slope_deg": 3.0,
        "access_distance_km": 0.0,
        "terrain_score": 80.0,
        "access_score": 75.0,
        "deployment_score": 75.0,
        "deployment_warning": "",
        "target_inside_area": True,
        "coverage_pct": 95.0,
        "downlink_coverage_pct": 95.0,
        "uplink_coverage_pct": 95.0,
        "downlink_median_margin_db": 14.0,
        "uplink_median_margin_db": 14.0,
        "median_margin_db": 14.0,
        "weak_signal_pct": 0.0,
        "usable_signal_pct": 30.0,
        "strong_signal_pct": 70.0,
        "rf_quality_score": 91.6,
        "rf_service_score": 91.6,
        "service_ok": True,
        "suitability_score": 88.0,
    }
    base.update(overrides)
    return Candidate(**base)  # type: ignore[arg-type]


class _FlatTerrain:
    def sample(self, lat: float, lon: float) -> float:
        return 100.0


def _assert_itm_errors_do_not_return_path_loss() -> None:
    rf = _normalise_rf_request({"profile": "VHF", "frequency_mhz": 150.0})
    path_cache: dict[str, tuple[float | None, str]] = {}
    failed_process = SimpleNamespace(
        returncode=2,
        stdout='{"path_loss_db": 80.0, "error_code": 3}',
        stderr="",
    )

    with (
        patch("app.mvp_analysis.RF_CORE_BIN", Path(__file__)),
        patch("app.mvp_analysis.subprocess.run", return_value=failed_process),
    ):
        path_loss, status = _path_loss_itm(
            (-32.0, 116.0),
            (-32.01, 116.01),
            _FlatTerrain(),
            rf,
            downlink=True,
            path_cache=path_cache,
        )

    assert path_loss is None
    assert "failed" in status
    assert path_cache
    assert path_cache[next(iter(path_cache))][0] is None


def _assert_itm_batch_worker_reuses_one_process() -> None:
    rf = _normalise_rf_request({"profile": "VHF", "frequency_mhz": 150.0})
    path_cache: dict[str, tuple[float | None, str]] = {}
    starts = 0

    class FakeStream:
        def write(self, value: str) -> int:
            return len(value)

        def flush(self) -> None:
            pass

        def readline(self) -> str:
            return '{"path_loss_db": 101.0, "error_code": 0}\n'

        def close(self) -> None:
            pass

    class FakeProcess:
        def __init__(self) -> None:
            self.stdin = FakeStream()
            self.stdout = FakeStream()
            self.stderr = FakeStream()
            self.returncode = None

        def poll(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            self.returncode = 0
            return 0

        def terminate(self) -> None:
            self.returncode = 0

        def kill(self) -> None:
            self.returncode = -9

    def fake_popen(*args: object, **kwargs: object) -> FakeProcess:
        nonlocal starts
        starts += 1
        return FakeProcess()

    worker = ItmBatchWorker(Path("/fake/rf_core_cli"))
    with (
        patch("app.mvp_analysis.RF_CORE_BIN", Path(__file__)),
        patch("app.mvp_analysis.subprocess.Popen", side_effect=fake_popen),
        patch("app.mvp_analysis.select.select", return_value=([worker], [], [])),
    ):
        first = _path_loss_itm(
            (-32.0, 116.0),
            (-32.01, 116.01),
            _FlatTerrain(),
            rf,
            downlink=True,
            path_cache=path_cache,
            itm_worker=worker,
        )
        second = _path_loss_itm(
            (-32.0, 116.0),
            (-32.02, 116.02),
            _FlatTerrain(),
            rf,
            downlink=True,
            path_cache=path_cache,
            itm_worker=worker,
        )
        worker.close()

    assert first == (101.0, "ok")
    assert second == (101.0, "ok")
    assert len(path_cache) == 2
    assert starts == 1, "batch ITM should start one process for multiple paths"


def _assert_failed_itm_cannot_fabricate_service() -> None:
    rf = _normalise_rf_request(
        {
            "profile": "VHF",
            "frequency_mhz": 150.0,
            "target_lat": -32.0,
            "target_lon": 116.0,
            "include_uplink": True,
        }
    )
    candidate = _candidate()

    with patch(
        "app.mvp_analysis._path_loss_itm",
        return_value=(None, "rf-core failed: test failure"),
    ):
        _score_candidate_rf(
            candidate,
            [(-32.01, 116.01)],
            (-32.01, 116.01),
            _FlatTerrain(),
            rf,
            {},
        )

    assert candidate.coverage_pct == 0.0
    assert candidate.downlink_coverage_pct == 0.0
    assert candidate.uplink_coverage_pct == 0.0
    assert candidate.min_margin_db < 0.0
    assert candidate.downlink_min_margin_db < 0.0
    assert candidate.uplink_min_margin_db < 0.0
    assert candidate.service_ok is False
    assert candidate.confidence == "low"


def _assert_failed_uplink_does_not_reuse_downlink_loss() -> None:
    rf = _normalise_rf_request(
        {
            "profile": "VHF",
            "frequency_mhz": 150.0,
            "include_uplink": True,
        }
    )
    candidate = _candidate()
    path_results = [
        (100.0, "ok"),  # centroid pre-check
        (100.0, "ok"),  # downlink target path
        (None, "rf-core failed: uplink test failure"),
    ]

    with patch("app.mvp_analysis._path_loss_itm", side_effect=path_results):
        _score_candidate_rf(
            candidate,
            [(-32.01, 116.01)],
            (-32.01, 116.01),
            _FlatTerrain(),
            rf,
            {},
        )

    assert candidate.downlink_coverage_pct == 100.0
    assert candidate.uplink_coverage_pct == 0.0
    assert candidate.uplink_min_margin_db < 0.0
    assert candidate.coverage_pct == 0.0
    assert candidate.service_ok is False
    assert candidate.confidence == "low"


def _assert_directional_rx_thresholds_are_independent() -> None:
    rf = _normalise_rf_request(
        {
            "profile": "VHF",
            "frequency_mhz": 150.0,
            "include_uplink": True,
        }
    )
    assert rf["portable_rx_threshold"]["threshold_dbm"] == -77.0
    assert rf["repeater_rx_threshold"]["threshold_dbm"] == -91.0
    assert rf["rx_thresholds"]["portable_rx"] == rf["portable_rx_threshold"]
    assert rf["rx_thresholds"]["repeater_rx"] == rf["repeater_rx_threshold"]

    candidate = _candidate()
    with patch(
        "app.mvp_analysis._path_loss_itm",
        return_value=(120.0, "ok"),
    ):
        _, downlink_margin, uplink_margin = _link_margin(
            candidate,
            (-32.01, 116.01),
            _FlatTerrain(),
            rf,
            {},
        )

    assert downlink_margin != uplink_margin
    assert downlink_margin < 0.0
    assert uplink_margin > 0.0


def _assert_repeater_threshold_change_does_not_change_portable_gate() -> None:
    base_rf = _normalise_rf_request({"profile": "VHF", "frequency_mhz": 150.0})
    adjusted_rf = _normalise_rf_request(
        {
            "profile": "VHF",
            "frequency_mhz": 150.0,
            "repeater_rx_fade_margin_db": 20.0,
        }
    )
    candidate = _candidate()

    with patch(
        "app.mvp_analysis._path_loss_itm",
        return_value=(120.0, "ok"),
    ):
        _, base_downlink, base_uplink = _link_margin(
            candidate,
            (-32.01, 116.01),
            _FlatTerrain(),
            base_rf,
            {},
        )
        _, adjusted_downlink, adjusted_uplink = _link_margin(
            candidate,
            (-32.01, 116.01),
            _FlatTerrain(),
            adjusted_rf,
            {},
        )

    assert adjusted_rf["portable_rx_threshold"] == base_rf["portable_rx_threshold"]
    assert adjusted_rf["repeater_rx_threshold"]["fade_margin_db"] == 20.0
    assert adjusted_downlink == base_downlink
    assert adjusted_uplink < base_uplink


def _assert_inside_rank_prefers_useful_interior_depth() -> None:
    rf = {
        "site_preference": "favour_inside_area",
        "include_uplink": True,
        "coverage_goal_pct": 85.0,
        "median_margin_goal_db": 3.0,
        "target_area_sq_km": 12.0,
    }
    edge_site = _candidate(
        name="Boundary high point",
        target_edge_distance_km=0.03,
        coverage_pct=96.0,
        downlink_coverage_pct=96.0,
        uplink_coverage_pct=96.0,
        downlink_median_margin_db=14.0,
        uplink_median_margin_db=14.0,
        median_margin_db=14.0,
        rf_quality_score=91.6,
        rf_service_score=91.6,
        suitability_score=88.0,
        access_score=70.0,
    )
    interior_site = _candidate(
        name="Interior working-area site",
        target_edge_distance_km=1.0,
        coverage_pct=96.0,
        downlink_coverage_pct=96.0,
        uplink_coverage_pct=96.0,
        downlink_median_margin_db=14.0,
        uplink_median_margin_db=14.0,
        median_margin_db=14.0,
        rf_quality_score=91.6,
        rf_service_score=91.6,
        suitability_score=88.0,
        access_score=70.0,
    )

    assert _candidate_rank_key(interior_site, rf) > _candidate_rank_key(edge_site, rf)


def _assert_stronger_rf_distribution_beats_weaker_threshold_pass() -> None:
    rf = {
        "site_preference": "favour_inside_area",
        "include_uplink": True,
        "coverage_goal_pct": 90.0,
        "median_margin_goal_db": 6.0,
        "target_area_sq_km": 8.0,
    }
    weak_pass = _candidate(
        name="High but patchy site",
        target_edge_distance_km=1.0,
        coverage_pct=100.0,
        downlink_coverage_pct=100.0,
        uplink_coverage_pct=100.0,
        weak_signal_pct=45.0,
        usable_signal_pct=35.0,
        strong_signal_pct=20.0,
        rf_quality_score=61.0,
        rf_service_score=74.0,
        suitability_score=94.0,
        elevation_m=268.0,
        access_score=95.0,
    )
    mostly_green = _candidate(
        name="Lower but strong site",
        target_edge_distance_km=0.45,
        coverage_pct=100.0,
        downlink_coverage_pct=100.0,
        uplink_coverage_pct=100.0,
        weak_signal_pct=0.0,
        usable_signal_pct=8.0,
        strong_signal_pct=92.0,
        rf_quality_score=97.8,
        rf_service_score=98.0,
        suitability_score=92.0,
        elevation_m=236.0,
        access_score=75.0,
    )

    assert _candidate_rank_key(mostly_green, rf) > _candidate_rank_key(weak_pass, rf)


def _assert_terrain_score_prefers_relative_position_over_asl() -> None:
    lower_relative_site = _terrain_score(
        elevation_m=250.0,
        relief_m=60.0,
        slope_deg=4.0,
        height_above_target_m=120.0,
    )
    high_asl_plateau = _terrain_score(
        elevation_m=900.0,
        relief_m=8.0,
        slope_deg=4.0,
        height_above_target_m=24.0,
    )

    assert lower_relative_site > high_asl_plateau


def _assert_confidence_policy_blocks_recommendation() -> None:
    policy = _recommendation_policy(
        {"dataset": "Landgate / SLIP Transport Roads (Simplified) and DBCA Long Trails"}
    )

    assert policy["label"] == "best available — verify"
    assert policy["recommended"] is False
    assert policy["field_verification_required"] is True
    assert "DEM-only terrain data" in policy["warning"]
    assert "no clutter or surface correction" in policy["warning"]
    assert "simplified road/access data" in policy["warning"]


def _assert_candidate_names_use_reference_roads() -> None:
    unnamed_track = Road(
        road_id="track-1",
        name="NotApplicable",
        highway="track",
        surface="unknown",
        geometry=[(-32.12, 116.08), (-32.121, 116.081)],
    )
    named_public_road = Road(
        road_id="road-1",
        name="Brookton Hwy",
        highway="secondary",
        surface="sealed",
        geometry=[(-32.119, 116.078), (-32.122, 116.082)],
    )

    assert _clean_road_name("NotApplicable") is None
    reference_name, _, exact_reference = _candidate_reference_road(
        -32.12,
        116.08,
        unnamed_track,
        [named_public_road],
        [named_public_road],
    )
    title = _candidate_name(unnamed_track, -32.12, 116.08, reference_name, exact_reference, relief_m=22.0, slope_deg=4.0)

    assert reference_name == "Brookton Hwy"
    assert title == "Track access near Brookton Hwy"
    assert "notapplicable" not in title.lower()
    assert "high point" not in title.lower()


def _assert_dem_peak_creates_off_road_spur() -> None:
    road_point = (-31.95, 116.16)
    peak = destination_point(road_point[0], road_point[1], 0.175, 90.0)

    class PeakTerrain:
        def sample(self, lat: float, lon: float) -> float:
            # The east-facing 175 m probe is a local DEM peak; all other
            # samples remain low so the test exercises the ring maximum.
            return 145.0 if (lat - peak[0]) ** 2 + (lon - peak[1]) ** 2 < 0.0002**2 else 100.0

    road = Road(
        road_id="road-peak",
        name="Peak Road",
        highway="track",
        surface="gravel",
        geometry=[road_point, destination_point(road_point[0], road_point[1], 0.8, 0.0)],
    )
    rf = {
        "target_lat": road_point[0],
        "target_lon": road_point[1],
        "search_radius_km": 3.0,
        "target_elevation_m": 100.0,
        "deployment_profile": "pushup_mast_lifepo4",
        "site_preference": "favour_edge",
    }

    candidates = _candidate_points_from_roads(PeakTerrain(), [road], rf)  # type: ignore[arg-type]
    spurs = [candidate for candidate in candidates if candidate.source == "spur"]
    assert spurs, "nearby DEM peak should create a spur candidate"
    assert 0.0 < spurs[0].access_distance_km <= 0.25
    assert spurs[0].access_source.startswith("Peak Road")
    assert "DEM-derived" in spurs[0].access_uncertainty


def _assert_cheap_rf_can_promote_candidate() -> None:
    rf = _normalise_rf_request(
        {
            "target_lat": -32.0,
            "target_lon": 116.0,
            "include_uplink": True,
            "candidate_count": 2,
        }
    )
    non_rf_leader = _candidate(
        candidate_id="non-rf-leader",
        target_inside_area=False,
        elevation_m=260.0,
        terrain_score=95.0,
        access_score=95.0,
        deployment_score=95.0,
        proximity_score=100.0,
    )
    rf_geometry_site = _candidate(
        candidate_id="rf-geometry-site",
        target_inside_area=False,
        elevation_m=95.0,
        local_relief_m=0.0,
        terrain_score=0.0,
        access_score=0.0,
        deployment_score=0.0,
        proximity_score=0.0,
        target_edge_distance_km=3.0,
    )
    filler = _candidate(
        candidate_id="filler",
        target_inside_area=False,
        elevation_m=160.0,
        terrain_score=55.0,
        access_score=55.0,
        deployment_score=55.0,
        proximity_score=55.0,
    )
    stats: dict[str, int] = {}

    shortlist = _two_phase_shortlist(
        [non_rf_leader, rf_geometry_site, filler],
        (-32.0, 116.0),
        _FlatTerrain(),  # type: ignore[arg-type]
        rf,
        None,
        2,
        stats,
        cheap_rf_scorer=lambda candidate, *_: 100.0 if candidate.candidate_id == "rf-geometry-site" else 1.0,
    )

    assert [candidate.candidate_id for candidate in shortlist] == ["non-rf-leader", "rf-geometry-site"]
    assert stats["phase_b_rf_promotions"] == 1


def main() -> None:
    _assert_itm_errors_do_not_return_path_loss()
    _assert_itm_batch_worker_reuses_one_process()
    _assert_failed_itm_cannot_fabricate_service()
    _assert_failed_uplink_does_not_reuse_downlink_loss()
    _assert_directional_rx_thresholds_are_independent()
    _assert_repeater_threshold_change_does_not_change_portable_gate()
    _assert_inside_rank_prefers_useful_interior_depth()
    _assert_stronger_rf_distribution_beats_weaker_threshold_pass()
    _assert_terrain_score_prefers_relative_position_over_asl()
    _assert_confidence_policy_blocks_recommendation()
    _assert_candidate_names_use_reference_roads()
    _assert_dem_peak_creates_off_road_spur()
    _assert_cheap_rf_can_promote_candidate()

    result = run_analysis(
        {
            "profile": "VHF",
            "frequency_mhz": 150.0,
            "tx_height_m": 12.0,
            "candidate_count": 3,
            "target_grid_cells": 25,
            "site_preference": "inside",
        }
    )
    assert result["schema_version"] == "mvp-analysis/v2"
    assert result["mode"] == "local-real-itm"
    assert result["target_polygon"]
    assert result["roads"]
    assert result["terrain_cells"]
    assert result["metadata"]["terrain_tiles"]
    assert result["metadata"]["roads"]["count"] > 0
    assert result["assessment"]["evaluated_candidates"] >= len(result["candidates"])
    assert result["assessment"]["coverage_goal_pct"] >= 85.0
    assert result["rf_profile"]["site_preference"] == "favour_inside_area"
    assert result["rf_profile"]["noise_environment"] == "suburban_incident"
    assert result["rf_profile"]["noise_floor_dbm"] == -105.0
    assert result["rf_profile"]["portable_rx_threshold"]["threshold_dbm"] == -77.0
    assert result["rf_profile"]["repeater_rx_threshold"]["threshold_dbm"] == -91.0
    assert result["metadata"]["analysis_preferences"]["site_preference"]["id"] == "favour_inside_area"
    assert result["metadata"]["analysis_preferences"]["noise_environment"]["id"] == "suburban_incident"
    assert result["metadata"]["analysis_preferences"]["rx_thresholds"]["portable_rx"]["applies_to"].startswith(
        "Repeater downlink"
    )
    assert result["metadata"]["analysis_preferences"]["rx_thresholds"]["repeater_rx"]["applies_to"].startswith(
        "Portable/mobile uplink"
    )
    assert result["metadata"]["target_area"]["area_sq_km"] > 0
    assert result["rf_profile"]["target_area_sq_km"] == result["metadata"]["target_area"]["area_sq_km"]
    assert len(result["candidates"]) >= 3
    assert len(result["coverage"]) > 10

    top = result["candidates"][0]
    assert top["rank"] == 1
    assert "source" in top
    assert top["coverage_pct"] >= 0
    assert "service_status" in top
    assert "uplink_coverage_pct" in top
    assert "downlink_coverage_pct" in top
    assert top["rx_thresholds"] == result["rf_profile"]["rx_thresholds"]
    assert "strong_signal_pct" in top
    assert "rf_quality_score" in top
    assert "target_inside_area" in top
    assert "reference_road_name" in top
    assert top["rf_core_status"].startswith("ok"), top["rf_core_status"]
    assert top["centroid_path_loss_db"] is not None
    assert top["access_class"]

    print("mvp analysis checks passed")


if __name__ == "__main__":
    main()
