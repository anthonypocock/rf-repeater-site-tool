"""Real-world WA RF propagation MVP analysis.

The MVP uses real terrain and road/track data:

- Mapzen/Terrain Tiles Skadi HGT elevation tiles are downloaded and cached.
- Landgate/SLIP Transport roads, tracks, and DBCA Long Trails are requested
  through ArcGIS REST and cached, with OpenStreetMap/Overpass as fallback.
- Candidate sites are generated from high points sampled along real roads/tracks.
- Coverage is calculated with NTIA ITM point-to-point path loss via rf-core.
  ITM/rf-core failures fail closed; no synthetic path-loss fallback is used.

This is still a field-planning MVP, not a certified engineering tool. It is
intended to make the operational workflow testable with real-world data and
explicit assumptions.
"""

from __future__ import annotations

import array
import gzip
import hashlib
import json
import math
import select
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[3]
RF_CORE_BIN = ROOT / "native" / "rf-core" / "bin" / "rf_core_cli"
RF_CORE_DIR = ROOT / "native" / "rf-core"
CACHE_DIR = ROOT / ".cache" / "rf-data"
ITM_WORKER_TIMEOUT_SECONDS = 8.0
HGT_BASE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/skadi"
SLIP_TRANSPORT_MAPSERVER = "https://services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Transport/MapServer"
SLIP_TRANSPORT_QUERY_LAYERS = {
    17: "primary",
    18: "secondary",
    19: "unclassified",
    20: "track",
    31: "path",
}
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

WA_BOUNDS = {
    "west": 112.0,
    "south": -36.0,
    "east": 129.2,
    "north": -13.0,
}

DEFAULT_TARGET = {
    "name": "Perth Hills / Mundaring WA",
    "lat": -31.9523,
    "lon": 116.1640,
    "target_radius_km": 2.0,
    "search_radius_km": 3.0,
}


class ItmBatchWorker:
    """Keep one rf-core process alive for the duration of an analysis.

    ``rf_core_cli --batch`` accepts one ``tx-height|rx-height|PFL`` line and
    emits one JSON result line. The worker is deliberately scoped to one
    analysis: all calls share the same rf settings, while the existing
    ``path_cache`` remains the first lookup and the worker is closed before
    the result is returned. A broken or timed-out worker raises to the
    fail-closed adapter below; it never causes an FSPL substitute.
    """

    def __init__(self, binary: Path = RF_CORE_BIN) -> None:
        self.binary = binary
        self.process: subprocess.Popen[str] | None = None

    def _start(self, rf: dict[str, Any]) -> None:
        self.process = subprocess.Popen(
            [
                str(self.binary),
                "--batch",
                "--freq-mhz",
                str(float(rf["frequency_mhz"])),
                "--location-pct",
                str(float(rf["location_percent"])),
                "--time-pct",
                str(float(rf["time_percent"])),
                "--situation-pct",
                str(float(rf["situation_percent"])),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def calculate(
        self,
        pfl: list[float],
        tx_height: float,
        rx_height: float,
        rf: dict[str, Any],
    ) -> dict[str, Any]:
        if self.process is None:
            self._start(rf)
        process = self.process
        if process is None or process.stdin is None or process.stdout is None:
            raise RuntimeError("ITM batch worker did not start")
        if process.poll() is not None:
            raise RuntimeError(f"rf-core batch exited with code {process.returncode}")

        line = "|".join(
            [
                str(tx_height),
                str(rx_height),
                ",".join(f"{value:.3f}" for value in pfl),
            ]
        )
        process.stdin.write(line + "\n")
        process.stdin.flush()
        ready, _, _ = select.select([process.stdout], [], [], ITM_WORKER_TIMEOUT_SECONDS)
        if not ready:
            raise TimeoutError("rf-core batch response timed out")
        response = process.stdout.readline()
        if not response:
            raise RuntimeError("rf-core batch worker closed stdout")
        return json.loads(response)

    def close(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
        try:
            process.wait(timeout=1)
        except (subprocess.SubprocessError, OSError):
            process.terminate()
            try:
                process.wait(timeout=1)
            except (subprocess.SubprocessError, OSError):
                process.kill()
        finally:
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()

    def __enter__(self) -> "ItmBatchWorker":
        return self

    def __exit__(self, _exc_type: object, _exc_value: object, _traceback: object) -> None:
        self.close()

ROAD_ACCESS_FACTOR = {
    "motorway": 0.35,
    "trunk": 0.78,
    "primary": 0.98,
    "secondary": 0.95,
    "tertiary": 0.9,
    "unclassified": 0.82,
    "residential": 0.72,
    "service": 0.72,
    "track": 0.58,
    "path": 0.22,
    "footway": 0.12,
    "cycleway": 0.12,
    "bridleway": 0.16,
}

WALKING_ACCESS_HIGHWAYS = {"path", "footway", "cycleway", "bridleway"}
PUBLIC_REFERENCE_HIGHWAYS = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "service"}
SPUR_SOURCE_HIGHWAYS = {"trunk", "primary", "secondary", "tertiary", "unclassified", "service", "track"}
UNNAMED_ROAD_TOKENS = {"", "0", "na", "n/a", "none", "null", "notapplicable", "notavailable", "unknown", "unnamed", "mappedaccess", "roadsunavailable"}

SERVICE_PROFILES = {
    "operational_portable": {
        "name": "Operational portable",
        "required_signal_dbm": -100.0,
        "default_noise_environment": "suburban_incident",
        "required_snr_db": 14.0,
        "fade_margin_db": 14.0,
        "user_losses_db": 6.0,
        "rx_height_m": 1.5,
        "description": "Field portable planning with body/local losses and practical fade margin.",
    },
    "vehicle_mobile": {
        "name": "Vehicle mobile",
        "required_signal_dbm": -104.0,
        "noise_floor_dbm": -119.0,
        "required_snr_db": 12.0,
        "fade_margin_db": 10.0,
        "user_losses_db": 1.5,
        "rx_height_m": 1.8,
        "description": "Vehicle mobile planning with external/vehicle antenna assumptions.",
    },
    "engineering_sensitivity": {
        "name": "Engineering sensitivity",
        "required_signal_dbm": -107.0,
        "noise_floor_dbm": -119.0,
        "required_snr_db": 12.0,
        "fade_margin_db": 10.0,
        "user_losses_db": 0.5,
        "rx_height_m": 1.5,
        "description": "Optimistic receiver-threshold check; useful for comparison, not field assurance.",
    },
}

NOISE_ENVIRONMENTS = {
    "quiet_rural": {
        "name": "Quiet rural",
        "noise_floor_dbm": -113.0,
        "description": "Low man-made noise assumption; suitable for remote country with few nearby electrical or vehicle noise sources.",
    },
    "rural_country": {
        "name": "Rural / country",
        "noise_floor_dbm": -110.0,
        "description": "Country-area VHF planning assumption with some man-made noise allowance.",
    },
    "suburban_incident": {
        "name": "Suburban / incident",
        "noise_floor_dbm": -105.0,
        "description": "Conservative operational portable assumption for semi-rural/suburban areas, vehicles, generators, houses, power lines, and incident activity.",
    },
    "urban_high_noise": {
        "name": "Urban / high noise",
        "noise_floor_dbm": -100.0,
        "description": "High man-made noise assumption for built-up or electrically noisy locations.",
    },
}

# These are screening defaults for the receiver mounted at the mast. They are
# deliberately separate from the conservative portable receiver gate below:
# a 12 m mast site is expected to have less local man-made noise, but this
# assumption still requires field verification before deployment.
REPEATER_RX_DEFAULTS = {
    "noise_environment": "quiet_rural",
    "noise_floor_dbm": -113.0,
    "required_signal_dbm": -107.0,
    "required_snr_db": 12.0,
    "fade_margin_db": 10.0,
    "default_basis": "12 m mast receiver at a quieter site; verify the installed noise floor",
}

SITE_PREFERENCES = {
    "favour_edge": {
        "name": "Favour edge",
        "description": "Prefer accessible high points on or just outside the required coverage area boundary; useful for fire or hazardous-area deployments where the repeater should not sit in the incident footprint.",
    },
    "favour_inside_area": {
        "name": "Favour inside area",
        "description": "Prefer accessible high points inside the required coverage area, with fallback to nearby outside sites when no suitable internal site is available; useful for missing-person searches or operations where the team can safely deploy within the search area.",
    },
}

FAILED_PATH_MARGIN_DB = -999.0


@dataclass(frozen=True)
class BBox:
    west: float
    south: float
    east: float
    north: float


@dataclass(frozen=True)
class Road:
    road_id: str
    name: str
    highway: str
    surface: str
    geometry: list[tuple[float, float]]  # lat, lon
    source_layer: int | None = None


@dataclass
class Candidate:
    candidate_id: str
    name: str
    lat: float
    lon: float
    road_name: str
    road_class: str
    surface: str
    elevation_m: float
    local_relief_m: float
    slope_deg: float
    access_distance_km: float
    terrain_score: float
    access_score: float
    deployment_score: float
    deployment_warning: str
    reference_road_name: str = ""
    reference_road_distance_km: float = -1.0
    target_edge_distance_km: float = 0.0
    target_inside_area: bool = False
    proximity_score: float = 0.0
    centroid_path_loss_db: float | None = None
    rf_core_status: str = "not run"
    coverage_pct: float = 0.0
    min_margin_db: float = 0.0
    median_margin_db: float = 0.0
    downlink_coverage_pct: float = 0.0
    downlink_min_margin_db: float = 0.0
    downlink_median_margin_db: float = 0.0
    uplink_coverage_pct: float = 0.0
    uplink_min_margin_db: float = 0.0
    uplink_median_margin_db: float = 0.0
    unusable_signal_pct: float = 0.0
    weak_signal_pct: float = 0.0
    usable_signal_pct: float = 0.0
    strong_signal_pct: float = 0.0
    rf_quality_score: float = 0.0
    rf_service_score: float = 0.0
    service_status: str = "not assessed"
    service_ok: bool = False
    suitability_score: float = 0.0
    confidence: str = "medium"
    source: str = "road"
    access_source: str = ""
    access_uncertainty: str = ""
    rf_pre_score: float = 0.0


class HgtTile:
    def __init__(self, tile_lat: int, tile_lon: int, values: array.array, size: int) -> None:
        self.tile_lat = tile_lat
        self.tile_lon = tile_lon
        self.values = values
        self.size = size

    def sample(self, lat: float, lon: float) -> float:
        # HGT rows run north-to-south; columns run west-to-east.
        row_f = (self.tile_lat + 1.0 - lat) * (self.size - 1)
        col_f = (lon - self.tile_lon) * (self.size - 1)
        row = max(0, min(self.size - 2, int(math.floor(row_f))))
        col = max(0, min(self.size - 2, int(math.floor(col_f))))
        dr = max(0.0, min(1.0, row_f - row))
        dc = max(0.0, min(1.0, col_f - col))

        def value_at(r: int, c: int) -> float:
            value = self.values[r * self.size + c]
            return 0.0 if value <= -32000 else float(value)

        v00 = value_at(row, col)
        v10 = value_at(row + 1, col)
        v01 = value_at(row, col + 1)
        v11 = value_at(row + 1, col + 1)
        return (v00 * (1 - dr) * (1 - dc)) + (v10 * dr * (1 - dc)) + (v01 * (1 - dr) * dc) + (v11 * dr * dc)


class TerrainProvider:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.tiles: dict[tuple[int, int], HgtTile] = {}
        self.loaded_names: set[str] = set()

    def sample(self, lat: float, lon: float) -> float:
        tile_lat = math.floor(lat)
        tile_lon = math.floor(lon)
        tile = self._load_tile(tile_lat, tile_lon)
        return tile.sample(lat, lon)

    def preload_bbox(self, bbox: BBox) -> None:
        for tile_lat in range(math.floor(bbox.south), math.floor(bbox.north) + 1):
            for tile_lon in range(math.floor(bbox.west), math.floor(bbox.east) + 1):
                self._load_tile(tile_lat, tile_lon)

    def _load_tile(self, tile_lat: int, tile_lon: int) -> HgtTile:
        key = (tile_lat, tile_lon)
        if key in self.tiles:
            return self.tiles[key]

        name = _hgt_tile_name(tile_lat, tile_lon)
        url = f"{HGT_BASE_URL}/{name[:3]}/{name}.hgt.gz"
        gz_path = self.cache_dir / f"{name}.hgt.gz"
        if not gz_path.exists():
            _download(url, gz_path)

        with gzip.open(gz_path, "rb") as handle:
            raw = handle.read()

        values = array.array("h")
        values.frombytes(raw)
        if sys.byteorder == "little":
            values.byteswap()

        size = int(math.sqrt(len(values)))
        if size * size != len(values):
            raise ValueError(f"Unexpected HGT tile size for {name}: {len(values)} samples")

        tile = HgtTile(tile_lat, tile_lon, values, size)
        self.tiles[key] = tile
        self.loaded_names.add(name)
        return tile


def run_analysis(request: dict[str, Any] | None = None) -> dict[str, Any]:
    request = request or {}
    rf = _normalise_rf_request(request)
    target_polygon_ll, target_area_type = _target_polygon_from_request(request, rf)
    centroid = _polygon_centroid(target_polygon_ll)
    rf["target_lat"] = centroid[0]
    rf["target_lon"] = centroid[1]
    if not _has_target_name(request):
        rf["target_name"] = _derived_target_name(centroid[0], centroid[1], target_area_type)
    rf["target_area_type"] = target_area_type
    rf["target_polygon_ll"] = target_polygon_ll
    rf["target_area_sq_km"] = round(
        math.pi * float(rf["target_radius_km"]) ** 2
        if target_area_type == "circle"
        else _polygon_area_sq_km(target_polygon_ll),
        3,
    )
    if target_area_type == "polygon":
        rf["target_grid_cells"] = max(int(rf["target_grid_cells"]), 121)
    bbox = _analysis_bbox(rf, target_polygon_ll)

    terrain = TerrainProvider(CACHE_DIR / "hgt")
    terrain.preload_bbox(bbox)
    target_elevation_m = terrain.sample(float(rf["target_lat"]), float(rf["target_lon"]))
    rf["target_elevation_m"] = target_elevation_m
    roads, road_meta = _load_roads(bbox)

    manual_candidate = _manual_candidate_from_request(terrain, roads, rf)
    if manual_candidate:
        rf["analysis_mode"] = "manual_repeater"
        rf["candidate_count"] = 1
        raw_candidates = [manual_candidate]
    else:
        rf["analysis_mode"] = "candidate_search"
        raw_candidates = _candidate_points_from_roads(terrain, roads, rf)
        if target_area_type == "polygon" and str(rf["site_preference"]) == "favour_inside_area":
            raw_candidates.extend(_interior_area_candidates(terrain, roads, rf, target_polygon_ll))
        if not raw_candidates:
            raw_candidates = _fallback_terrain_candidates(terrain, rf, bbox)

    target_points = _target_grid_points(target_polygon_ll, max_cells=int(rf["target_grid_cells"]))
    requested_count = int(rf["candidate_count"])
    if target_area_type == "polygon" and not manual_candidate:
        eval_floor = 96 if str(rf["site_preference"]) == "favour_inside_area" else 72
    else:
        eval_floor = 16
    eval_count = min(len(raw_candidates), max(requested_count * 8, eval_floor))
    phase_stats: dict[str, int] = {}
    shortlist = _two_phase_shortlist(
        raw_candidates,
        centroid,
        terrain,
        rf,
        target_polygon_ll if target_area_type == "polygon" else None,
        eval_count,
        phase_stats,
    )
    rf["rf_evaluation"] = phase_stats

    _ensure_rf_core()
    path_cache: dict[str, tuple[float | None, str]] = {}
    # One worker handles every uncached ITM path in this analysis. This keeps
    # the numerical inputs and fail-closed result handling of _path_loss_itm,
    # while avoiding hundreds of process starts in the candidate hot path.
    with ItmBatchWorker() as itm_worker:
        for candidate in shortlist:
            _score_candidate_rf(candidate, target_points, centroid, terrain, rf, path_cache, itm_worker)

        shortlist.sort(key=lambda candidate: _candidate_rank_key(candidate, rf), reverse=True)
        display_candidates = shortlist[:requested_count]
        top = display_candidates[0]
        viewport = _viewport_for_payload(bbox)
        coverage_by_candidate = {
            candidate.candidate_id: _coverage_cells(
                candidate, target_points, terrain, rf, path_cache, viewport, itm_worker
            )
            for candidate in display_candidates
        }
        coverage = coverage_by_candidate[top.candidate_id]

    roads_payload = [_road_payload(road, viewport) for road in roads[:220]]
    display_roads = [_display_road_payload(road, viewport) for road in roads[:1600]]
    terrain_rows, terrain_cols = _terrain_resolution(float(rf["search_radius_km"]))
    terrain_cells = _terrain_cells(terrain, viewport, rows=terrain_rows, cols=terrain_cols)

    recommendation = _recommendation_policy(road_meta)

    return {
        "schema_version": "mvp-analysis/v2",
        "mode": "local-real-itm",
        "rf_profile": rf,
        "service_profile": {
            "id": rf["service_profile"],
            "name": SERVICE_PROFILES[str(rf["service_profile"])]["name"],
            "description": SERVICE_PROFILES[str(rf["service_profile"])]["description"],
            "required_signal_dbm": rf["required_signal_dbm"],
            "noise_environment": rf["noise_environment"],
            "noise_floor_dbm": rf["noise_floor_dbm"],
            "required_snr_db": rf["required_snr_db"],
            "fade_margin_db": rf["fade_margin_db"],
            "user_losses_db": rf["user_losses_db"],
            "rx_thresholds": rf["rx_thresholds"],
        },
        "deployment_profile": _deployment_profile(str(rf["deployment_profile"])),
        "target_polygon": [_normalise_point(lat, lon, viewport) for lat, lon in target_polygon_ll],
        "target_polygon_ll": [[round(lat, 6), round(lon, 6)] for lat, lon in target_polygon_ll],
        "target_center": {
            "lat": round(float(rf["target_lat"]), 6),
            "lon": round(float(rf["target_lon"]), 6),
            "x": _normalise_point(float(rf["target_lat"]), float(rf["target_lon"]), viewport)[0],
            "y": _normalise_point(float(rf["target_lat"]), float(rf["target_lon"]), viewport)[1],
            "elevation_m": round(target_elevation_m, 1),
        },
        "roads": roads_payload,
        "display_roads": display_roads,
        "terrain_cells": terrain_cells,
        "coverage": coverage,
        "coverage_candidate_id": top.candidate_id,
        "candidates": [
            _candidate_payload(
                index + 1,
                candidate,
                viewport,
                rf,
                coverage_by_candidate[candidate.candidate_id],
                recommendation,
            )
            for index, candidate in enumerate(display_candidates)
        ],
        "assessment": _assessment_payload(shortlist, requested_count, rf, recommendation),
        "recommendation": recommendation,
        "metadata": {
            "region": "Western Australia",
            "region_description": f"{rf['target_name']} real-data planning area",
            "target_area": {
                "type": target_area_type,
                "area_sq_km": rf["target_area_sq_km"],
                "point_count": len(target_polygon_ll),
            },
            "region_bounds": {
                "crs": "EPSG:4326",
                "west": round(viewport.west, 6),
                "south": round(viewport.south, 6),
                "east": round(viewport.east, 6),
                "north": round(viewport.north, 6),
            },
            "terrain": "Mapzen/Terrain Tiles Skadi HGT real elevation tiles",
            "terrain_tiles": sorted(terrain.loaded_names),
            "roads": road_meta,
            "analysis_preferences": {
                "site_preference": {
                    "id": str(rf["site_preference"]),
                    **SITE_PREFERENCES[str(rf["site_preference"])],
                },
                "noise_environment": {
                    "id": str(rf["noise_environment"]),
                    **NOISE_ENVIRONMENTS[str(rf["noise_environment"])],
                }
                if str(rf["noise_environment"]) in NOISE_ENVIRONMENTS
                else {
                    "id": "custom",
                    "name": "Custom",
                    "noise_floor_dbm": rf["noise_floor_dbm"],
                    "description": "Custom noise floor supplied in request.",
                },
                "rx_thresholds": rf["rx_thresholds"],
            },
            "display_layers": {
                "aerial_imagery": {
                    "dataset": "Landgate / SLIP Locate Public Aerial Imagery",
                    "service": "https://services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Locate/MapServer",
                    "layers": [4],
                    "note": "Whole-of-state public aerial imagery; service metadata states regional and town-site mosaics are at least 400 days old.",
                },
                "roads_tracks_trails": {
                    "dataset": "Landgate / SLIP Transport",
                    "service": "https://services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Transport/MapServer",
                    "layers": [17, 18, 19, 20, 31],
                    "note": "Display overlay and preferred candidate screening use public Roads (Simplified) plus DBCA Long Trails; full Landgate Roads LGATE-012 subscription data should be assessed before production use.",
                },
            },
            "rf_core": str(RF_CORE_BIN),
            "model": "NTIA ITM point-to-point TLS per candidate-to-target-cell path",
            "note": "Decision-support MVP. Validate candidate access, safety, permissions, and RF performance in the field.",
        },
    }


def _rx_threshold_payload(
    receiver_role: str,
    applies_to: str,
    noise_environment: str,
    noise_floor_dbm: float,
    required_signal_dbm: float,
    required_snr_db: float,
    fade_margin_db: float,
    basis: str,
) -> dict[str, Any]:
    """Build the auditable service gate for one receiver role.

    ``threshold_dbm`` is the received-power gate after sensitivity/noise,
    required SNR, and fade margin are combined. The direction-specific
    components are retained so a report can explain the gate rather than only
    exposing its resulting number.
    """
    threshold_dbm = max(required_signal_dbm, noise_floor_dbm + required_snr_db) + fade_margin_db
    return {
        "receiver_role": receiver_role,
        "applies_to": applies_to,
        "noise_environment": noise_environment,
        "noise_floor_dbm": noise_floor_dbm,
        "required_signal_dbm": required_signal_dbm,
        "required_snr_db": required_snr_db,
        "fade_margin_db": fade_margin_db,
        "threshold_dbm": threshold_dbm,
        "basis": basis,
    }


def _rx_threshold(rf: dict[str, Any], receiver_role: str) -> dict[str, Any]:
    """Return one directional threshold, with a legacy-profile fallback."""
    configured = rf.get(f"{receiver_role}_threshold")
    if not isinstance(configured, dict):
        configured = rf.get("rx_thresholds", {}).get(receiver_role)
    if isinstance(configured, dict):
        required_signal_dbm = float(configured.get("required_signal_dbm", rf.get("required_signal_dbm", -100.0)))
        noise_floor_dbm = float(configured.get("noise_floor_dbm", rf.get("noise_floor_dbm", -105.0)))
        required_snr_db = float(configured.get("required_snr_db", rf.get("required_snr_db", 14.0)))
        fade_margin_db = float(configured.get("fade_margin_db", rf.get("fade_margin_db", 14.0)))
        return {
            **configured,
            "required_signal_dbm": required_signal_dbm,
            "noise_floor_dbm": noise_floor_dbm,
            "required_snr_db": required_snr_db,
            "fade_margin_db": fade_margin_db,
            "threshold_dbm": float(
                configured.get(
                    "threshold_dbm",
                    max(required_signal_dbm, noise_floor_dbm + required_snr_db) + fade_margin_db,
                )
            ),
        }

    return _rx_threshold_payload(
        receiver_role,
        (
            "Repeater downlink to the portable/mobile receiver"
            if receiver_role == "portable_rx"
            else "Portable/mobile uplink to the mast-top repeater receiver"
        ),
        str(rf.get("noise_environment", "suburban_incident")),
        float(rf.get("noise_floor_dbm", -105.0)),
        float(rf.get("required_signal_dbm", -100.0)),
        float(rf.get("required_snr_db", 14.0)),
        float(rf.get("fade_margin_db", 14.0)),
        "legacy single-threshold RF profile",
    )


def _normalise_rf_request(request: dict[str, Any]) -> dict[str, Any]:
    profile = str(request.get("profile", "VHF")).upper()
    frequency_mhz = float(request.get("frequency_mhz", 150.0 if profile == "VHF" else 460.0))
    user_radio = str(request.get("user_radio", "portable"))
    service_profile = str(
        request.get("service_profile", "operational_portable" if user_radio == "portable" else "vehicle_mobile")
    )
    if service_profile not in SERVICE_PROFILES:
        service_profile = "operational_portable"
    service_defaults = SERVICE_PROFILES[service_profile]
    deployment_profile = str(request.get("deployment_profile", "pushup_mast_lifepo4"))

    target_lat = _clamp(float(request.get("target_lat", DEFAULT_TARGET["lat"])), WA_BOUNDS["south"], WA_BOUNDS["north"])
    target_lon = _clamp(float(request.get("target_lon", DEFAULT_TARGET["lon"])), WA_BOUNDS["west"], WA_BOUNDS["east"])
    target_radius_km = _clamp(float(request.get("target_radius_km", DEFAULT_TARGET["target_radius_km"])), 1.0, 30.0)
    search_radius_km = _clamp(
        float(request.get("search_radius_km", DEFAULT_TARGET["search_radius_km"])),
        max(3.0, target_radius_km + 1.0),
        45.0,
    )
    repeater_power_w = max(0.1, float(request.get("repeater_power_w", request.get("tx_power_w", 25.0))))
    mobile_power_w = max(0.1, float(request.get("mobile_power_w", 25.0)))
    portable_power_w = max(0.1, float(request.get("portable_power_w", 5.0)))
    uplink_power_w = portable_power_w if user_radio == "portable" else mobile_power_w

    rx_height_default = float(service_defaults["rx_height_m"])
    tx_power_dbm = 10.0 * math.log10(repeater_power_w * 1000.0)
    target_grid_default = 121 if target_radius_km <= 5 else 81
    portable_noise_environment = _normalise_noise_environment(
        request.get("noise_environment"),
        str(service_defaults.get("default_noise_environment", "")),
    )
    manual_repeater_site = _normalise_manual_repeater_site(request.get("manual_repeater_site"))
    portable_noise_floor = float(
        request.get(
            "portable_rx_noise_floor_dbm",
            request.get(
                "noise_floor_dbm",
                NOISE_ENVIRONMENTS[portable_noise_environment]["noise_floor_dbm"]
                if portable_noise_environment in NOISE_ENVIRONMENTS
                else service_defaults["noise_floor_dbm"],
            ),
        )
    )
    portable_required_signal = float(
        request.get(
            "portable_rx_required_signal_dbm",
            request.get("required_signal_dbm", service_defaults["required_signal_dbm"]),
        )
    )
    portable_required_snr = float(
        request.get(
            "portable_rx_required_snr_db",
            request.get("required_snr_db", service_defaults["required_snr_db"]),
        )
    )
    portable_fade_margin = float(
        request.get(
            "portable_rx_fade_margin_db",
            request.get("fade_margin_db", service_defaults["fade_margin_db"]),
        )
    )
    repeater_noise_environment = _normalise_noise_environment(
        request.get("repeater_rx_noise_environment", request.get("repeater_noise_environment")),
        str(REPEATER_RX_DEFAULTS["noise_environment"]),
    )
    repeater_noise_floor = float(
        request.get(
            "repeater_rx_noise_floor_dbm",
            request.get(
                "repeater_noise_floor_dbm",
                NOISE_ENVIRONMENTS[repeater_noise_environment]["noise_floor_dbm"]
                if repeater_noise_environment in NOISE_ENVIRONMENTS
                else REPEATER_RX_DEFAULTS["noise_floor_dbm"],
            ),
        )
    )
    repeater_required_signal = float(
        request.get(
            "repeater_rx_required_signal_dbm",
            request.get("repeater_required_signal_dbm", REPEATER_RX_DEFAULTS["required_signal_dbm"]),
        )
    )
    repeater_required_snr = float(
        request.get(
            "repeater_rx_required_snr_db",
            request.get("repeater_required_snr_db", REPEATER_RX_DEFAULTS["required_snr_db"]),
        )
    )
    repeater_fade_margin = float(
        request.get(
            "repeater_rx_fade_margin_db",
            request.get("repeater_fade_margin_db", REPEATER_RX_DEFAULTS["fade_margin_db"]),
        )
    )
    portable_rx_threshold = _rx_threshold_payload(
        "portable_rx",
        "Repeater downlink to the portable/mobile receiver",
        portable_noise_environment,
        portable_noise_floor,
        portable_required_signal,
        portable_required_snr,
        portable_fade_margin,
        "service profile and selected portable noise environment",
    )
    repeater_rx_threshold = _rx_threshold_payload(
        "repeater_rx",
        "Portable/mobile uplink to the mast-top repeater receiver",
        repeater_noise_environment,
        repeater_noise_floor,
        repeater_required_signal,
        repeater_required_snr,
        repeater_fade_margin,
        str(REPEATER_RX_DEFAULTS["default_basis"]),
    )

    rx_thresholds = {
        "portable_rx": portable_rx_threshold,
        "repeater_rx": repeater_rx_threshold,
    }

    return {
        "region": "Western Australia",
        "target_name": str(request.get("target_name") or _derived_target_name(target_lat, target_lon, "circle")),
        "target_lat": target_lat,
        "target_lon": target_lon,
        "target_radius_km": target_radius_km,
        "search_radius_km": search_radius_km,
        "profile": profile,
        "frequency_mhz": frequency_mhz,
        "repeater_power_w": repeater_power_w,
        "mobile_power_w": mobile_power_w,
        "portable_power_w": portable_power_w,
        "user_radio": user_radio,
        "uplink_power_w": uplink_power_w,
        "tx_power_dbm": tx_power_dbm,
        "tx_height_m": float(request.get("tx_height_m", 12.0)),
        "rx_height_m": float(request.get("rx_height_m", rx_height_default)),
        "antenna_gain_dbi": float(request.get("antenna_gain_dbi", 3.0)),
        "system_losses_db": float(request.get("system_losses_db", 1.5)),
        "user_antenna_gain_dbi": float(request.get("user_antenna_gain_dbi", 0.0)),
        "user_losses_db": float(request.get("user_losses_db", service_defaults["user_losses_db"])),
        "required_signal_dbm": portable_rx_threshold["required_signal_dbm"],
        "noise_environment": portable_noise_environment,
        "noise_floor_dbm": portable_rx_threshold["noise_floor_dbm"],
        "required_snr_db": portable_rx_threshold["required_snr_db"],
        "fade_margin_db": portable_rx_threshold["fade_margin_db"],
        "portable_rx_threshold": portable_rx_threshold,
        "repeater_rx_threshold": repeater_rx_threshold,
        "rx_thresholds": rx_thresholds,
        "service_profile": service_profile,
        "coverage_goal_pct": float(
            request.get("coverage_goal_pct", 90.0 if service_profile == "operational_portable" else 85.0)
        ),
        "median_margin_goal_db": float(
            request.get("median_margin_goal_db", 6.0 if service_profile == "operational_portable" else 3.0)
        ),
        "include_uplink": bool(request.get("include_uplink", True)),
        "location_percent": float(request.get("location_percent", 90.0)),
        "time_percent": float(request.get("time_percent", 50.0)),
        "situation_percent": float(request.get("situation_percent", 50.0)),
        "deployment_profile": deployment_profile,
        "site_preference": _normalise_site_preference(request.get("site_preference")),
        "candidate_count": int(request.get("candidate_count", 4)),
        "target_grid_cells": int(request.get("target_grid_cells", target_grid_default)),
        "manual_repeater_site": manual_repeater_site,
    }


def _normalise_manual_repeater_site(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    try:
        lat = float(value.get("lat"))
        lon = float(value.get("lon"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(lat) or not math.isfinite(lon):
        return None
    return {
        "lat": round(_clamp(lat, WA_BOUNDS["south"], WA_BOUNDS["north"]), 6),
        "lon": round(_clamp(lon, WA_BOUNDS["west"], WA_BOUNDS["east"]), 6),
        "name": str(value.get("name") or "Manual repeater site"),
    }


def _normalise_site_preference(value: Any) -> str:
    text = str(value or "favour_edge").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "edge": "favour_edge",
        "favor_edge": "favour_edge",
        "favour_boundary": "favour_edge",
        "inside": "favour_inside_area",
        "inside_area": "favour_inside_area",
        "favor_inside": "favour_inside_area",
        "favor_inside_area": "favour_inside_area",
        "favour_inside": "favour_inside_area",
    }
    return aliases.get(text, text if text in SITE_PREFERENCES else "favour_edge")


def _normalise_noise_environment(value: Any, default_environment: str = "") -> str:
    text = str(value or default_environment or "rural_country").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "quiet": "quiet_rural",
        "remote": "quiet_rural",
        "country": "rural_country",
        "rural": "rural_country",
        "suburban": "suburban_incident",
        "incident": "suburban_incident",
        "operational": "suburban_incident",
        "urban": "urban_high_noise",
        "high_noise": "urban_high_noise",
    }
    return aliases.get(text, text if text in NOISE_ENVIRONMENTS else "rural_country")


def _has_target_name(request: dict[str, Any]) -> bool:
    return bool(str(request.get("target_name", "")).strip())


def _derived_target_name(lat: float, lon: float, area_type: str) -> str:
    label = "Drawn target area" if area_type == "polygon" else "Target area"
    return f"{label} {lat:.4f}, {lon:.4f}"


def _target_polygon_from_request(request: dict[str, Any], rf: dict[str, Any]) -> tuple[list[tuple[float, float]], str]:
    raw_polygon = request.get("target_polygon_ll")
    if not isinstance(raw_polygon, list) or len(raw_polygon) < 3:
        return _circle_polygon(float(rf["target_lat"]), float(rf["target_lon"]), float(rf["target_radius_km"]), 40), "circle"

    polygon: list[tuple[float, float]] = []
    for raw_point in raw_polygon[:80]:
        if not isinstance(raw_point, (list, tuple)) or len(raw_point) < 2:
            continue
        try:
            lat = float(raw_point[0])
            lon = float(raw_point[1])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(lat) or not math.isfinite(lon):
            continue
        polygon.append(
            (
                _clamp(lat, WA_BOUNDS["south"], WA_BOUNDS["north"]),
                _clamp(lon, WA_BOUNDS["west"], WA_BOUNDS["east"]),
            )
        )

    if len(polygon) < 3:
        return _circle_polygon(float(rf["target_lat"]), float(rf["target_lon"]), float(rf["target_radius_km"]), 40), "circle"
    return polygon, "polygon"


def _analysis_bbox(rf: dict[str, Any], polygon: list[tuple[float, float]] | None = None) -> BBox:
    lat = float(rf["target_lat"])
    lon = float(rf["target_lon"])
    radius = float(rf["search_radius_km"])
    lat_delta = radius / 110.574
    lon_delta = radius / max(25.0, 111.320 * math.cos(math.radians(lat)))
    if polygon:
        west = min(point[1] for point in polygon) - lon_delta
        south = min(point[0] for point in polygon) - lat_delta
        east = max(point[1] for point in polygon) + lon_delta
        north = max(point[0] for point in polygon) + lat_delta
    else:
        west = lon - lon_delta
        south = lat - lat_delta
        east = lon + lon_delta
        north = lat + lat_delta
    manual_site = rf.get("manual_repeater_site")
    if isinstance(manual_site, dict):
        manual_lat = float(manual_site["lat"])
        manual_lon = float(manual_site["lon"])
        west = min(west, manual_lon - 0.01)
        south = min(south, manual_lat - 0.01)
        east = max(east, manual_lon + 0.01)
        north = max(north, manual_lat + 0.01)
    return BBox(
        west=_clamp(west, WA_BOUNDS["west"], WA_BOUNDS["east"]),
        south=_clamp(south, WA_BOUNDS["south"], WA_BOUNDS["north"]),
        east=_clamp(east, WA_BOUNDS["west"], WA_BOUNDS["east"]),
        north=_clamp(north, WA_BOUNDS["south"], WA_BOUNDS["north"]),
    )


def _viewport_for_payload(bbox: BBox) -> BBox:
    width = bbox.east - bbox.west
    height = bbox.north - bbox.south
    pad_x = max(width * 0.05, 0.01)
    pad_y = max(height * 0.05, 0.01)
    return BBox(bbox.west - pad_x, bbox.south - pad_y, bbox.east + pad_x, bbox.north + pad_y)


def _load_roads(bbox: BBox) -> tuple[list[Road], dict[str, Any]]:
    roads, meta = _load_slip_transport_roads(bbox)
    if roads:
        return roads, meta
    osm_roads, osm_meta = _load_osm_roads(bbox)
    if meta.get("errors"):
        osm_meta["primary_source_errors"] = meta["errors"]
    return osm_roads, osm_meta


def _clean_road_name(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).replace("_", " ").strip().split())
    if not text:
        return None
    normalised = "".join(char for char in text.lower() if char.isalnum())
    if normalised in UNNAMED_ROAD_TOKENS or normalised.startswith("notapplicable"):
        return None
    if normalised.startswith("unnamed"):
        return None
    return text


def _road_name_from_values(values: list[Any], highway: str) -> str:
    for value in values:
        clean_name = _clean_road_name(value)
        if clean_name:
            return clean_name
    return _generic_road_name(highway)


def _generic_road_name(highway: str) -> str:
    label = _road_kind_label(highway)
    if label == "mapped access":
        return label
    return f"unnamed {label}"


def _road_kind_label(highway: str) -> str:
    if highway == "track":
        return "track"
    if highway in WALKING_ACCESS_HIGHWAYS:
        return "trail"
    if highway == "service":
        return "service road"
    if highway in {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential"}:
        return "road"
    return "mapped access"


def _load_slip_transport_roads(bbox: BBox) -> tuple[list[Road], dict[str, Any]]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_dir = CACHE_DIR / "slip-transport"
    cache_dir.mkdir(parents=True, exist_ok=True)
    roads: list[Road] = []
    errors: list[str] = []
    sources: list[str] = []

    for layer_id, default_highway in SLIP_TRANSPORT_QUERY_LAYERS.items():
        cache_file = cache_dir / f"layer_{layer_id}_{_bbox_cache_key(bbox)}.geojson"
        payload: dict[str, Any] | None = None
        source = "cache"
        if cache_file.exists() and time.time() - cache_file.stat().st_mtime < 14 * 24 * 3600:
            payload = json.loads(cache_file.read_text())
        else:
            try:
                payload = _query_slip_transport_layer(layer_id, bbox)
                cache_file.write_text(json.dumps(payload))
                source = f"{SLIP_TRANSPORT_MAPSERVER}/{layer_id}/query"
            except (OSError, URLError, TimeoutError, json.JSONDecodeError, ValueError) as error:
                errors.append(f"SLIP layer {layer_id}: {error}")
                if cache_file.exists():
                    payload = json.loads(cache_file.read_text())
                    source = f"stale cache for SLIP layer {layer_id}"
        if payload is None:
            continue
        sources.append(source)
        roads.extend(_roads_from_slip_geojson(payload, layer_id, default_highway, bbox))

    roads.sort(key=lambda road: (ROAD_ACCESS_FACTOR.get(road.highway, 0.0), _road_length_km(road)), reverse=True)
    if len(roads) > 2400:
        roads = roads[:2400]
    return roads, {
        "source": ", ".join(sorted(set(sources))) if roads else "Landgate / SLIP Transport unavailable",
        "dataset": "Landgate / SLIP Transport Roads (Simplified) and DBCA Long Trails",
        "query_bbox": {
            "west": round(bbox.west, 6),
            "south": round(bbox.south, 6),
            "east": round(bbox.east, 6),
            "north": round(bbox.north, 6),
        },
        "layers": sorted(SLIP_TRANSPORT_QUERY_LAYERS),
        "count": len(roads),
        "errors": errors,
        "note": "Public SLIP road features are suitable for pilot screening/display; full Landgate Roads LGATE-012 subscription data should be assessed before production use.",
    }


def _load_osm_roads(bbox: BBox) -> tuple[list[Road], dict[str, Any]]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / "osm" / f"roads_{_bbox_cache_key(bbox)}.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    query = f"""
[out:json][timeout:25];
(
  way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|service|track)$"]({bbox.south:.6f},{bbox.west:.6f},{bbox.north:.6f},{bbox.east:.6f});
);
out body geom;
"""

    payload: dict[str, Any] | None = None
    source = "cache"
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < 14 * 24 * 3600:
        payload = json.loads(cache_file.read_text())
    else:
        errors: list[str] = []
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                body = urlencode({"data": query}).encode("utf-8")
                request = Request(
                    endpoint,
                    data=body,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "User-Agent": "rf-repeater-site-mvp/0.2 (field planning prototype)",
                    },
                )
                with urlopen(request, timeout=35) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                cache_file.write_text(json.dumps(payload))
                source = endpoint
                break
            except (OSError, URLError, TimeoutError, json.JSONDecodeError) as error:
                errors.append(f"{endpoint}: {error}")
        if payload is None and cache_file.exists():
            payload = json.loads(cache_file.read_text())
            source = "stale cache after Overpass failure"
        if payload is None:
            return [], {"source": "Overpass unavailable", "errors": errors, "count": 0}

    roads: list[Road] = []
    for element in payload.get("elements", []):
        if element.get("type") != "way" or "geometry" not in element:
            continue
        tags = element.get("tags", {})
        highway = str(tags.get("highway", "unknown"))
        if highway not in ROAD_ACCESS_FACTOR:
            continue
        geometry = [(float(node["lat"]), float(node["lon"])) for node in element.get("geometry", [])]
        if len(geometry) < 2:
            continue
        roads.append(
            Road(
                road_id=str(element.get("id", "")),
                name=_road_name_from_values([tags.get("name")], highway),
                highway=highway,
                surface=str(tags.get("surface", "unknown")),
                geometry=geometry,
                source_layer=None,
            )
        )

    roads.sort(key=lambda road: (ROAD_ACCESS_FACTOR.get(road.highway, 0.0), _road_length_km(road)), reverse=True)
    if len(roads) > 2400:
        roads = roads[:2400]
    return roads, {
        "source": source,
        "dataset": "OpenStreetMap via Overpass API",
        "query_bbox": {
            "west": round(bbox.west, 6),
            "south": round(bbox.south, 6),
            "east": round(bbox.east, 6),
            "north": round(bbox.north, 6),
        },
        "count": len(roads),
        "cache_file": str(cache_file),
    }


def _query_slip_transport_layer(layer_id: int, bbox: BBox) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    offset = 0
    while True:
        params = {
            "f": "geojson",
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "geometry": f"{bbox.west:.6f},{bbox.south:.6f},{bbox.east:.6f},{bbox.north:.6f}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "7844",
            "outSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "resultRecordCount": "5000",
            "resultOffset": str(offset),
        }
        url = f"{SLIP_TRANSPORT_MAPSERVER}/{layer_id}/query?{urlencode(params)}"
        request = Request(url, headers={"User-Agent": "rf-repeater-site-mvp/0.3 (field planning prototype)"})
        with urlopen(request, timeout=35) as response:
            payload = json.loads(response.read().decode("utf-8"))
        batch = payload.get("features", [])
        if not isinstance(batch, list):
            raise ValueError(f"Unexpected SLIP layer {layer_id} response")
        features.extend(batch)
        if not payload.get("exceededTransferLimit") or not batch:
            break
        offset += len(batch)
        if offset >= 50000:
            break
    return {"type": "FeatureCollection", "features": features}


def _roads_from_slip_geojson(payload: dict[str, Any], layer_id: int, default_highway: str, bbox: BBox) -> list[Road]:
    roads: list[Road] = []
    for index, feature in enumerate(payload.get("features", [])):
        properties = feature.get("properties", {}) if isinstance(feature, dict) else {}
        geometry = feature.get("geometry", {}) if isinstance(feature, dict) else {}
        for line_index, line in enumerate(_geojson_lines(geometry)):
            points = _line_points_within_bbox(line, bbox)
            if len(points) < 2:
                continue
            highway = _slip_highway_class(layer_id, default_highway, properties)
            surface = str(properties.get("roadsurface") or properties.get("surface") or "unknown").lower()
            name = _road_name_from_values([properties.get("road_name"), properties.get("name")], highway)
            roads.append(
                Road(
                    road_id=f"slip-{layer_id}-{properties.get('objectid', index)}-{line_index}",
                    name=name,
                    highway=highway,
                    surface=surface,
                    geometry=points,
                    source_layer=layer_id,
                )
            )
    return roads


def _geojson_lines(geometry: dict[str, Any]) -> list[list[list[float]]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates", [])
    if geometry_type == "LineString" and isinstance(coordinates, list):
        return [coordinates]
    if geometry_type == "MultiLineString" and isinstance(coordinates, list):
        return [line for line in coordinates if isinstance(line, list)]
    return []


def _line_points_within_bbox(line: list[list[float]], bbox: BBox) -> list[tuple[float, float]]:
    margin = 0.015
    points: list[tuple[float, float]] = []
    for coordinate in line:
        if not isinstance(coordinate, list) or len(coordinate) < 2:
            continue
        lon = float(coordinate[0])
        lat = float(coordinate[1])
        if bbox.west - margin <= lon <= bbox.east + margin and bbox.south - margin <= lat <= bbox.north + margin:
            points.append((lat, lon))
    return points


def _slip_highway_class(layer_id: int, default_highway: str, properties: dict[str, Any]) -> str:
    text = " ".join(
        str(properties.get(key, ""))
        for key in ("mapclassification", "fcsubtype", "roadusage", "trl_trail_type")
    ).lower()
    if layer_id == 31 or "trail" in text or "track" in str(properties.get("trl_trail_type", "")).lower():
        return "path"
    if "track" in text:
        return "track"
    if "laneway" in text:
        return "service"
    if "minor" in text:
        return "unclassified"
    if "main" in text:
        return "secondary"
    if "highway" in text or "freeway" in text:
        return "primary"
    return default_highway


def _manual_candidate_from_request(terrain: TerrainProvider, roads: list[Road], rf: dict[str, Any]) -> Candidate | None:
    site = rf.get("manual_repeater_site")
    if not isinstance(site, dict):
        return None
    lat = float(site["lat"])
    lon = float(site["lon"])
    elevation = terrain.sample(lat, lon)
    relief = _local_relief_m(terrain, lat, lon)
    slope = _slope_deg(terrain, lat, lon)
    terrain_score = _terrain_score(elevation, relief, slope, elevation - float(rf.get("target_elevation_m", elevation)))
    public_reference_roads = _named_reference_roads(roads)
    named_access_roads = _named_reference_roads(roads, include_tracks=True)
    nearest = _nearest_road(lat, lon, roads)
    if nearest:
        road, access_distance_km = nearest
    else:
        road = Road(
            road_id="manual-no-road",
            name="manual selection",
            highway="unknown",
            surface="unknown",
            geometry=[(lat, lon)],
        )
        access_distance_km = -1.0
    road_factor = ROAD_ACCESS_FACTOR.get(road.highway, 0.25)
    access_penalty = max(0.0, access_distance_km) * 18.0
    access_score = max(0.0, min(100.0, 100.0 * road_factor - access_penalty - max(0.0, slope - 8.0) * 2.0))
    deployment_score, deployment_warning = _deployment_suitability(str(rf["deployment_profile"]), road, slope)
    if access_distance_km > 0.25:
        deployment_warning = f"{deployment_warning} Manual point is {access_distance_km:.2f} km from nearest mapped road/track."
    reference_name, reference_distance_km, exact_reference = _candidate_reference_road(
        lat,
        lon,
        road,
        public_reference_roads,
        named_access_roads,
    )
    return Candidate(
        candidate_id="manual_001",
        name=str(site.get("name") or "Manual repeater site"),
        lat=lat,
        lon=lon,
        road_name=_candidate_access_road_name(road),
        road_class=road.highway,
        surface=road.surface,
        elevation_m=elevation,
        local_relief_m=relief,
        slope_deg=slope,
        access_distance_km=access_distance_km,
        terrain_score=terrain_score,
        access_score=access_score,
        deployment_score=deployment_score,
        deployment_warning=deployment_warning,
        reference_road_name=reference_name,
        reference_road_distance_km=access_distance_km if exact_reference else reference_distance_km,
        confidence="medium" if nearest else "low",
        source="manual",
        access_source=_mapped_access_source(road),
        access_uncertainty=_mapped_access_uncertainty(
            "Manual point access distance is measured to mapped data only; legality, safety, and physical access require field verification."
        ),
    )


def _nearest_road(lat: float, lon: float, roads: list[Road]) -> tuple[Road, float] | None:
    best: tuple[Road, float] | None = None
    for road in roads:
        if not road.geometry:
            continue
        distance = min(haversine_km(lat, lon, point_lat, point_lon) for point_lat, point_lon in road.geometry)
        if best is None or distance < best[1]:
            best = (road, distance)
    return best


def _named_reference_roads(roads: list[Road], include_tracks: bool = False) -> list[Road]:
    allowed = set(PUBLIC_REFERENCE_HIGHWAYS)
    if include_tracks:
        allowed.add("track")
    return [road for road in roads if road.highway in allowed and _clean_road_name(road.name)]


def _candidate_reference_road(
    lat: float,
    lon: float,
    road: Road,
    public_reference_roads: list[Road],
    named_access_roads: list[Road],
) -> tuple[str, float, bool]:
    exact_name = _clean_road_name(road.name)
    if exact_name:
        return exact_name, 0.0, True

    nearest = _nearest_road(lat, lon, public_reference_roads) or _nearest_road(lat, lon, named_access_roads)
    if nearest:
        reference_road, distance_km = nearest
        reference_name = _clean_road_name(reference_road.name)
        if reference_name:
            return reference_name, distance_km, False

    return _generic_road_name(road.highway), -1.0, False


def _candidate_access_road_name(road: Road) -> str:
    return _clean_road_name(road.name) or _generic_road_name(road.highway)


def _candidate_points_from_roads(terrain: TerrainProvider, roads: list[Road], rf: dict[str, Any]) -> list[Candidate]:
    center = (float(rf["target_lat"]), float(rf["target_lon"]))
    target_polygon = rf.get("target_polygon_ll") if rf.get("target_area_type") == "polygon" else None
    polygon_mode = isinstance(target_polygon, list)
    search_radius = float(rf["search_radius_km"])
    candidates: list[Candidate] = []
    public_reference_roads = _named_reference_roads(roads)
    named_access_roads = _named_reference_roads(roads, include_tracks=True)

    roads_to_sample = (
        sorted(
            roads,
            key=lambda road: (
                _road_target_distance_km(road, target_polygon, center),
                -ROAD_ACCESS_FACTOR.get(road.highway, 0.25),
                -_road_length_km(road),
            ),
        )
        if polygon_mode
        else roads
    )
    sample_budget = 5200 if polygon_mode else 1800
    sample_count = 0
    for road in roads_to_sample:
        if road.highway == "motorway":
            continue
        road_factor = ROAD_ACCESS_FACTOR.get(road.highway, 0.25)
        if road_factor < 0.1:
            continue
        if polygon_mode:
            step_km = 0.25 if road.highway in {"track", "service", "unclassified", "tertiary", "secondary"} else 0.35
        else:
            step_km = 0.8 if road.highway in {"track", "service", "unclassified"} else 1.2
        for lat, lon in _sample_polyline(road.geometry, step_km=step_km):
            sample_count += 1
            if sample_count > sample_budget:
                break
            distance_to_target = (
                _distance_to_polygon_km(lat, lon, target_polygon)
                if polygon_mode
                else haversine_km(lat, lon, center[0], center[1])
            )
            if distance_to_target > search_radius:
                continue
            inside_area = bool(polygon_mode and _point_in_polygon((lat, lon), target_polygon))
            elevation = terrain.sample(lat, lon)
            relief = _local_relief_m(terrain, lat, lon)
            slope = _slope_deg(terrain, lat, lon)
            terrain_score = _terrain_score(elevation, relief, slope, elevation - float(rf.get("target_elevation_m", elevation)))
            proximity_score = _target_proximity_score(
                distance_to_target,
                polygon_mode,
                inside_area,
                str(rf["site_preference"]),
            )
            access_score = max(0.0, min(100.0, 100.0 * road_factor - max(0.0, slope - 8.0) * 2.0))
            deployment_score, deployment_warning = _deployment_suitability(str(rf["deployment_profile"]), road, slope)
            reference_name, reference_distance_km, exact_reference = _candidate_reference_road(
                lat,
                lon,
                road,
                public_reference_roads,
                named_access_roads,
            )
            candidates.append(
                Candidate(
                    candidate_id="",
                    name=_candidate_name(road, lat, lon, reference_name, exact_reference, relief, slope),
                    lat=lat,
                    lon=lon,
                    road_name=_candidate_access_road_name(road),
                    road_class=road.highway,
                    surface=road.surface,
                    elevation_m=elevation,
                    local_relief_m=relief,
                    slope_deg=slope,
                    access_distance_km=0.0,
                    terrain_score=terrain_score,
                    access_score=access_score,
                    deployment_score=deployment_score,
                    deployment_warning=deployment_warning,
                    reference_road_name=reference_name,
                    reference_road_distance_km=reference_distance_km,
                    target_edge_distance_km=distance_to_target,
                    target_inside_area=inside_area,
                    proximity_score=proximity_score,
                    access_source=_mapped_access_source(road),
                    access_uncertainty=_mapped_access_uncertainty(),
                )
            )
            spur = _spur_candidate_from_sample(
                terrain,
                road,
                (lat, lon),
                elevation,
                relief,
                rf,
                distance_to_target,
                inside_area,
                proximity_score,
                reference_name,
                reference_distance_km,
                exact_reference,
            )
            if spur:
                candidates.append(spur)
        if sample_count > sample_budget:
            break

    candidates.sort(
        key=lambda candidate: (
            candidate.proximity_score,
            0.55 * candidate.terrain_score + 0.28 * candidate.access_score + 0.17 * candidate.deployment_score,
            -_distance_to_polygon_km(candidate.lat, candidate.lon, target_polygon) if polygon_mode else 0.0,
        ),
        reverse=True,
    )
    deduped: list[Candidate] = []
    per_road_name: dict[str, int] = {}
    max_per_road = 4 if polygon_mode else 2
    min_spacing_km = 0.35 if polygon_mode else 1.25
    # Keep Phase A broad enough that a site with modest terrain/access scores
    # can still be promoted by the cheap RF geometry score before ITM runs.
    max_candidates = 160 if polygon_mode else 80
    for candidate in candidates:
        road_key = f"{candidate.road_name.lower()}:{candidate.reference_road_name.lower()}"
        if per_road_name.get(road_key, 0) >= max_per_road:
            continue
        required_spacing_km = 0.08 if candidate.source == "spur" or any(
            existing.source == "spur" for existing in deduped
        ) else min_spacing_km
        if all(haversine_km(candidate.lat, candidate.lon, existing.lat, existing.lon) > required_spacing_km for existing in deduped):
            candidate.candidate_id = f"cand_{len(deduped) + 1:03d}"
            deduped.append(candidate)
            per_road_name[road_key] = per_road_name.get(road_key, 0) + 1
        if len(deduped) >= max_candidates:
            break
    return deduped


def _spur_candidate_from_sample(
    terrain: TerrainProvider,
    road: Road,
    road_point: tuple[float, float],
    road_elevation_m: float,
    road_relief_m: float,
    rf: dict[str, Any],
    target_distance_km: float,
    inside_area: bool,
    proximity_score: float,
    reference_name: str,
    reference_distance_km: float,
    exact_reference: bool,
) -> Candidate | None:
    """Return the best plausible DEM peak 100–250 m beyond a mapped way.

    The mapped road/track point is treated as the access end point.  Bearings
    are sampled on three rings so a spur can be found without claiming that
    the DEM describes a real vehicle track, easement, or safe walking route.
    A ring maximum must improve both relative height/relief enough to matter
    and remain within a deployment-plausible slope.
    """
    if road.highway not in SPUR_SOURCE_HIGHWAYS:
        return None

    ring_peaks: list[tuple[float, float, float, float]] = []
    for distance_km in (0.1, 0.175, 0.25):
        probes = _spur_probe_points(road_point[0], road_point[1], distance_km)
        elevations = [terrain.sample(lat, lon) for lat, lon in probes]
        peak_index = max(range(len(probes)), key=lambda index: elevations[index])
        previous_elevation = elevations[(peak_index - 1) % len(elevations)]
        next_elevation = elevations[(peak_index + 1) % len(elevations)]
        peak_elevation = elevations[peak_index]
        if peak_elevation < previous_elevation or peak_elevation < next_elevation:
            continue
        peak_lat, peak_lon = probes[peak_index]
        peak_relief = _local_relief_m(terrain, peak_lat, peak_lon)
        height_gain = peak_elevation - road_elevation_m
        relief_gain = peak_relief - road_relief_m
        if height_gain < 3.0 and relief_gain < 4.0:
            continue
        ring_peaks.append((peak_lat, peak_lon, peak_elevation, peak_relief))

    if not ring_peaks:
        return None

    peak_lat, peak_lon, elevation, relief = max(
        ring_peaks,
        key=lambda peak: (peak[2] - road_elevation_m) * 0.7 + (peak[3] - road_relief_m) * 0.3,
    )
    slope = _slope_deg(terrain, peak_lat, peak_lon)
    if slope > 18.0:
        return None

    access_distance_km = haversine_km(road_point[0], road_point[1], peak_lat, peak_lon)
    profile_id = str(rf["deployment_profile"])
    road_factor = ROAD_ACCESS_FACTOR.get(road.highway, 0.25)
    is_trailer = profile_id == "repeater_trailer_solar"
    access_penalty_per_km = 210.0 if is_trailer else 32.0
    deployment_penalty_per_km = 300.0 if is_trailer else 80.0
    access_score = max(
        0.0,
        min(100.0, 100.0 * road_factor - access_distance_km * access_penalty_per_km - max(0.0, slope - 8.0) * 2.0),
    )
    deployment_score, base_warning = _deployment_suitability(profile_id, road, slope)
    deployment_score = max(0.0, deployment_score - access_distance_km * deployment_penalty_per_km)
    if is_trailer:
        deployment_warning = (
            f"{base_warning} Off-road spur is {access_distance_km:.2f} km beyond the mapped way; "
            "trailer deployment is heavily down-ranked until tow access is field-confirmed."
        )
    else:
        deployment_warning = (
            f"{base_warning} DEM-derived spur is {access_distance_km:.2f} km beyond the mapped way; "
            "portable mast carry distance and guying footprint require field confirmation."
        )

    terrain_score = _terrain_score(
        elevation,
        relief,
        slope,
        elevation - float(rf.get("target_elevation_m", elevation)),
    )
    return Candidate(
        candidate_id="",
        name=f"Off-road spur near {reference_name}" if reference_name else "Off-road spur site",
        lat=peak_lat,
        lon=peak_lon,
        road_name=_candidate_access_road_name(road),
        road_class=road.highway,
        surface=road.surface,
        elevation_m=elevation,
        local_relief_m=relief,
        slope_deg=slope,
        access_distance_km=access_distance_km,
        terrain_score=terrain_score,
        access_score=access_score,
        deployment_score=deployment_score,
        deployment_warning=deployment_warning,
        reference_road_name=reference_name,
        reference_road_distance_km=access_distance_km if exact_reference else reference_distance_km,
        target_edge_distance_km=target_distance_km,
        target_inside_area=inside_area,
        proximity_score=proximity_score,
        confidence="low",
        source="spur",
        access_source=_mapped_access_source(road),
        access_uncertainty=_mapped_access_uncertainty(
            "The spur location is DEM-derived; mapped access ends at the road/track sample."
        ),
    )


def _spur_probe_points(lat: float, lon: float, distance_km: float) -> list[tuple[float, float]]:
    """Generate an eight-bearing DEM ring at a permitted spur distance."""
    return [destination_point(lat, lon, distance_km, bearing) for bearing in range(0, 360, 45)]


def _mapped_access_source(road: Road) -> str:
    source = f"source layer {road.source_layer}" if road.source_layer is not None else "mapped road dataset"
    return f"{_candidate_access_road_name(road)} ({road.highway}; {source})"


def _mapped_access_uncertainty(
    detail: str = "Mapped road/track data does not confirm legal, safe, or physically possible access.",
) -> str:
    return detail


def _interior_area_candidates(
    terrain: TerrainProvider,
    roads: list[Road],
    rf: dict[str, Any],
    target_polygon: list[tuple[float, float]],
) -> list[Candidate]:
    south = min(lat for lat, _ in target_polygon)
    north = max(lat for lat, _ in target_polygon)
    west = min(lon for _, lon in target_polygon)
    east = max(lon for _, lon in target_polygon)
    area_sq_km = max(0.1, float(rf.get("target_area_sq_km", 0.1)))
    grid_size = 11 if area_sq_km < 30.0 else 13 if area_sq_km < 90.0 else 15
    raw_points: list[tuple[float, float]] = [_polygon_centroid(target_polygon)]
    for row in range(grid_size):
        lat = south + (row + 0.5) * (north - south) / grid_size
        for col in range(grid_size):
            lon = west + (col + 0.5) * (east - west) / grid_size
            if _point_in_polygon((lat, lon), target_polygon):
                raw_points.append((lat, lon))

    points: list[tuple[float, float]] = []
    for point in raw_points:
        _append_unique_point(points, point, min_distance_km=0.35)

    candidates: list[Candidate] = []
    public_reference_roads = _named_reference_roads(roads)
    named_access_roads = _named_reference_roads(roads, include_tracks=True)
    for lat, lon in points:
        boundary_distance = _distance_to_polygon_boundary_km(lat, lon, target_polygon)
        nearest = _nearest_road(lat, lon, roads)
        if nearest:
            road, access_distance_km = nearest
        else:
            road = Road(
                road_id="interior-no-road",
                name="interior area",
                highway="unknown",
                surface="unknown",
                geometry=[(lat, lon)],
            )
            access_distance_km = float(rf["search_radius_km"])

        elevation = terrain.sample(lat, lon)
        relief = _local_relief_m(terrain, lat, lon)
        slope = _slope_deg(terrain, lat, lon)
        terrain_score = _terrain_score(elevation, relief, slope, elevation - float(rf.get("target_elevation_m", elevation)))
        road_factor = ROAD_ACCESS_FACTOR.get(road.highway, 0.25)
        access_distance_penalty = max(0.0, access_distance_km) * (65.0 if str(rf["deployment_profile"]) == "repeater_trailer_solar" else 36.0)
        access_score = max(0.0, min(100.0, 100.0 * road_factor - access_distance_penalty - max(0.0, slope - 8.0) * 2.0))
        deployment_score, deployment_warning = _deployment_suitability(str(rf["deployment_profile"]), road, slope)
        if access_distance_km > 0.1:
            deployment_score = max(0.0, deployment_score - access_distance_penalty * 0.35)
            deployment_warning = (
                f"{deployment_warning} Interior point is {access_distance_km:.2f} km from nearest mapped road/track; "
                "verify vehicle approach, clearance, and setup footprint."
            )
        depth_score = _inside_depth_score(boundary_distance, rf)
        screening = 0.36 * depth_score + 0.24 * terrain_score + 0.22 * access_score + 0.18 * deployment_score
        reference_name, reference_distance_km, exact_reference = _candidate_reference_road(
            lat,
            lon,
            road,
            public_reference_roads,
            named_access_roads,
        )
        candidates.append(
            Candidate(
                candidate_id=f"inside_{len(candidates) + 1:03d}",
                name=_candidate_name(road, lat, lon, reference_name, exact_reference and access_distance_km <= 0.05, relief, slope),
                lat=lat,
                lon=lon,
                road_name=_candidate_access_road_name(road),
                road_class=road.highway,
                surface=road.surface,
                elevation_m=elevation,
                local_relief_m=relief,
                slope_deg=slope,
                access_distance_km=access_distance_km,
                terrain_score=terrain_score,
                access_score=access_score,
                deployment_score=deployment_score,
                deployment_warning=deployment_warning,
                reference_road_name=reference_name,
                reference_road_distance_km=access_distance_km if exact_reference else reference_distance_km,
                target_edge_distance_km=boundary_distance,
                target_inside_area=True,
                proximity_score=_target_proximity_score(boundary_distance, True, True, str(rf["site_preference"])),
                confidence="medium" if nearest and access_distance_km <= 0.35 else "low",
                source="interior",
                access_source=_mapped_access_source(road),
                access_uncertainty=_mapped_access_uncertainty(),
            )
        )

    candidates.sort(
        key=lambda candidate: (
            _inside_depth_score(candidate.target_edge_distance_km, rf),
            candidate.access_score,
            candidate.terrain_score,
            candidate.deployment_score,
        ),
        reverse=True,
    )
    return candidates[:40]


def _fallback_terrain_candidates(terrain: TerrainProvider, rf: dict[str, Any], bbox: BBox) -> list[Candidate]:
    candidates: list[Candidate] = []
    target_polygon = rf.get("target_polygon_ll") if rf.get("target_area_type") == "polygon" else None
    for row in range(8):
        lat = bbox.south + (row + 0.5) * (bbox.north - bbox.south) / 8
        for col in range(8):
            lon = bbox.west + (col + 0.5) * (bbox.east - bbox.west) / 8
            distance_to_target = (
                _distance_to_polygon_km(lat, lon, target_polygon)
                if isinstance(target_polygon, list)
                else haversine_km(lat, lon, float(rf["target_lat"]), float(rf["target_lon"]))
            )
            if distance_to_target > float(rf["search_radius_km"]):
                continue
            elevation = terrain.sample(lat, lon)
            relief = _local_relief_m(terrain, lat, lon)
            slope = _slope_deg(terrain, lat, lon)
            terrain_score = _terrain_score(elevation, relief, slope, elevation - float(rf.get("target_elevation_m", elevation)))
            candidates.append(
                Candidate(
                    candidate_id=f"cand_{len(candidates) + 1:03d}",
                    name=f"Terrain {_site_descriptor(Road('terrain', 'mapped access', 'unknown', 'unknown', [(lat, lon)]), relief, slope)}",
                    lat=lat,
                    lon=lon,
                    road_name="roads unavailable",
                    road_class="unknown",
                    surface="unknown",
                    elevation_m=elevation,
                    local_relief_m=relief,
                    slope_deg=slope,
                    access_distance_km=-1.0,
                    terrain_score=terrain_score,
                    access_score=10.0,
                    deployment_score=10.0,
                    deployment_warning="Road/track data unavailable; access must be checked manually.",
                    confidence="low",
                    access_source="Road/track data unavailable",
                    access_uncertainty=_mapped_access_uncertainty(
                        "No mapped access source was available; legal, safe, and physical access are unverified."
                    ),
                )
            )
    candidates.sort(key=lambda candidate: candidate.terrain_score, reverse=True)
    return candidates[:8]


def _two_phase_shortlist(
    candidates: list[Candidate],
    centroid: tuple[float, float],
    terrain: TerrainProvider,
    rf: dict[str, Any],
    target_polygon: list[tuple[float, float]] | None,
    eval_count: int,
    phase_stats: dict[str, int] | None = None,
    cheap_rf_scorer: Callable[[Candidate, tuple[float, float], TerrainProvider, dict[str, Any]], float] | None = None,
) -> list[Candidate]:
    """Build a full-ITM shortlist from non-RF and cheap-RF Phase A leaders.

    Phase A evaluates every retained terrain/access candidate without invoking
    rf-core.  Most slots follow the existing non-RF suitability screen, while
    reserved promotion slots come from a coarse distance/clearance/link-budget
    heuristic.  This union is intentional: a candidate with a weak terrain or
    access pre-score is not permanently excluded when its RF geometry is strong.
    Phase B is the caller's full downlink/uplink ITM evaluation.

    ``cheap_rf_scorer`` is injectable so the promotion boundary can be tested
    without a subprocess and future coarse RF implementations can be compared.
    """
    screened = _screen_candidates(candidates, centroid, rf, target_polygon)
    if not screened or eval_count <= 0:
        if phase_stats is not None:
            phase_stats.update(
                {
                    "phase_a_candidate_count": len(screened),
                    "phase_b_candidate_count": 0,
                    "phase_b_rf_promotions": 0,
                }
            )
        return []

    scorer = cheap_rf_scorer or _cheap_rf_pre_score
    for candidate in screened:
        candidate.rf_pre_score = max(
            0.0,
            min(100.0, float(scorer(candidate, centroid, terrain, rf))),
        )

    shortlist_count = min(len(screened), eval_count)
    promotion_slots = min(shortlist_count, max(1, math.ceil(shortlist_count * 0.25)))
    non_rf_slots = max(1, shortlist_count - promotion_slots)
    non_rf_leaders = screened[:non_rf_slots]
    non_rf_ids = {candidate.candidate_id for candidate in non_rf_leaders}
    rf_leaders = sorted(
        screened,
        key=lambda candidate: (candidate.rf_pre_score, candidate.suitability_score),
        reverse=True,
    )
    promotions = [candidate for candidate in rf_leaders if candidate.candidate_id not in non_rf_ids][:promotion_slots]

    selected = non_rf_leaders + promotions
    if len(selected) < shortlist_count:
        selected_ids = {candidate.candidate_id for candidate in selected}
        selected.extend(
            candidate
            for candidate in screened
            if candidate.candidate_id not in selected_ids
        )
        selected = selected[:shortlist_count]

    if phase_stats is not None:
        phase_stats.update(
            {
                "phase_a_candidate_count": len(screened),
                "phase_b_candidate_count": len(selected),
                "phase_b_rf_promotions": len(promotions),
            }
        )
    return selected


def _cheap_rf_pre_score(
    candidate: Candidate,
    centroid: tuple[float, float],
    terrain: TerrainProvider,
    rf: dict[str, Any],
) -> float:
    """Estimate RF geometry cheaply using free-space budget and coarse LOS.

    This is deliberately not an ITM replacement.  It uses four terrain
    samples along the centroid path and approximate downlink/uplink budgets to
    reserve Phase B slots for geometrically promising sites.
    """
    target_elevation = terrain.sample(centroid[0], centroid[1])
    distance_km = max(0.001, haversine_km(candidate.lat, candidate.lon, centroid[0], centroid[1]))
    free_space_loss = _free_space_loss_db((candidate.lat, candidate.lon), centroid, float(rf["frequency_mhz"]))
    portable_rx_threshold = _rx_threshold(rf, "portable_rx")
    repeater_rx_threshold = _rx_threshold(rf, "repeater_rx")
    downlink_margin = (
        float(rf["tx_power_dbm"])
        + float(rf["antenna_gain_dbi"])
        - float(rf["system_losses_db"])
        - free_space_loss
        + float(rf["user_antenna_gain_dbi"])
        - float(rf["user_losses_db"])
        - float(portable_rx_threshold["threshold_dbm"])
    )
    uplink_tx_dbm = 10.0 * math.log10(float(rf["uplink_power_w"]) * 1000.0)
    uplink_margin = (
        uplink_tx_dbm
        + float(rf["user_antenna_gain_dbi"])
        - float(rf["user_losses_db"])
        - free_space_loss
        + float(rf["antenna_gain_dbi"])
        - float(rf["system_losses_db"])
        - float(repeater_rx_threshold["threshold_dbm"])
    )
    limiting_margin = min(downlink_margin, uplink_margin) if rf.get("include_uplink", True) else downlink_margin
    budget_score = max(0.0, min(100.0, 50.0 + limiting_margin * 2.0))

    endpoint_high = candidate.elevation_m + float(rf["tx_height_m"])
    endpoint_low = target_elevation + float(rf["rx_height_m"])
    clearance_values: list[float] = []
    for index in range(1, 5):
        fraction = index / 5.0
        lat = candidate.lat + (centroid[0] - candidate.lat) * fraction
        lon = candidate.lon + (centroid[1] - candidate.lon) * fraction
        line_elevation = endpoint_high + (endpoint_low - endpoint_high) * fraction
        clearance_values.append(line_elevation - terrain.sample(lat, lon))
    clearance_m = min(clearance_values, default=0.0)
    clearance_score = max(0.0, min(100.0, 50.0 + clearance_m * 1.5))
    relative_height_score = max(
        0.0,
        min(100.0, 50.0 + (candidate.elevation_m - target_elevation) * 0.45 + candidate.local_relief_m * 0.3),
    )
    distance_score = max(0.0, min(100.0, 100.0 - distance_km * 8.0))
    return 0.55 * budget_score + 0.2 * clearance_score + 0.15 * relative_height_score + 0.1 * distance_score


def _screen_candidates(
    candidates: list[Candidate],
    centroid: tuple[float, float],
    rf: dict[str, Any],
    target_polygon: list[tuple[float, float]] | None = None,
) -> list[Candidate]:
    for candidate in candidates:
        inside_area = bool(target_polygon and _point_in_polygon((candidate.lat, candidate.lon), target_polygon))
        target_distance = (
            _distance_to_polygon_boundary_km(candidate.lat, candidate.lon, target_polygon)
            if target_polygon
            else haversine_km(candidate.lat, candidate.lon, centroid[0], centroid[1])
        )
        candidate.target_edge_distance_km = target_distance
        candidate.target_inside_area = inside_area
        candidate.proximity_score = _target_proximity_score(
            target_distance,
            target_polygon is not None,
            candidate.target_inside_area,
            str(rf["site_preference"]),
        )
        height_score = max(0.0, min(100.0, (candidate.elevation_m - float(rf.get("target_elevation_m", candidate.elevation_m))) * 1.2))
        site_preference = str(rf["site_preference"])
        zone_score = _preferred_zone_score(candidate, site_preference) * 100.0
        inside_depth_score = _inside_depth_score(candidate.target_edge_distance_km, rf) if candidate.target_inside_area else 0.0
        zone_bonus = 0.0
        if target_polygon is not None and site_preference == "favour_inside_area" and candidate.target_inside_area:
            zone_bonus = 10.0 + 0.16 * inside_depth_score
        elif target_polygon is not None and site_preference == "favour_edge" and not candidate.target_inside_area and candidate.target_edge_distance_km <= 1.5:
            zone_bonus = 12.0
        candidate.suitability_score = (
            0.22 * candidate.terrain_score
            + 0.18 * candidate.access_score
            + 0.14 * candidate.deployment_score
            + 0.22 * candidate.proximity_score
            + 0.10 * zone_score
            + 0.08 * height_score
            + 0.06 * inside_depth_score
            + zone_bonus
        )
    candidates.sort(key=lambda candidate: candidate.suitability_score, reverse=True)
    return candidates


def _score_candidate_rf(
    candidate: Candidate,
    target_points: list[tuple[float, float]],
    centroid: tuple[float, float],
    terrain: TerrainProvider,
    rf: dict[str, Any],
    path_cache: dict[str, tuple[float | None, str]],
    itm_worker: ItmBatchWorker | None = None,
) -> None:
    candidate.centroid_path_loss_db, candidate.rf_core_status = _path_loss_itm(
        (candidate.lat, candidate.lon),
        centroid,
        terrain,
        rf,
        downlink=True,
        path_cache=path_cache,
        itm_worker=itm_worker,
    )
    margins: list[float] = []
    downlink_margins: list[float] = []
    uplink_margins: list[float] = []
    for point in target_points:
        margin, downlink_margin, uplink_margin = _link_margin(
            candidate, point, terrain, rf, path_cache, itm_worker
        )
        margins.append(margin)
        downlink_margins.append(downlink_margin)
        if rf.get("include_uplink", True):
            uplink_margins.append(uplink_margin)

    if not margins:
        candidate.coverage_pct = 0.0
        candidate.min_margin_db = -999.0
        candidate.median_margin_db = -999.0
        candidate.downlink_coverage_pct = 0.0
        candidate.uplink_coverage_pct = 0.0
        candidate.unusable_signal_pct = 100.0
        candidate.weak_signal_pct = 0.0
        candidate.usable_signal_pct = 0.0
        candidate.strong_signal_pct = 0.0
        candidate.rf_quality_score = 0.0
        candidate.rf_service_score = 0.0
        candidate.confidence = "low"
        return

    candidate.coverage_pct, candidate.min_margin_db, candidate.median_margin_db = _margin_stats(margins)
    (
        candidate.unusable_signal_pct,
        candidate.weak_signal_pct,
        candidate.usable_signal_pct,
        candidate.strong_signal_pct,
        candidate.rf_quality_score,
    ) = _margin_quality_stats(margins)
    (
        candidate.downlink_coverage_pct,
        candidate.downlink_min_margin_db,
        candidate.downlink_median_margin_db,
    ) = _margin_stats(downlink_margins)
    if uplink_margins:
        (
            candidate.uplink_coverage_pct,
            candidate.uplink_min_margin_db,
            candidate.uplink_median_margin_db,
        ) = _margin_stats(uplink_margins)
    else:
        candidate.uplink_coverage_pct = 100.0
        candidate.uplink_min_margin_db = 999.0
        candidate.uplink_median_margin_db = 999.0

    candidate.service_ok, candidate.service_status = _candidate_service_status(candidate, rf)
    rf_score = _rf_service_score(candidate, rf)
    candidate.rf_service_score = rf_score
    margin_penalty = _excess_margin_distance_penalty(candidate, rf)
    inside_depth_score = (
        _inside_depth_score(candidate.target_edge_distance_km, rf)
        if str(rf.get("site_preference")) == "favour_inside_area" and candidate.target_inside_area
        else 0.0
    )
    zone_score = _preferred_zone_score(candidate, str(rf.get("site_preference", "favour_edge"))) * 100.0
    candidate.suitability_score = max(
        0.0,
        min(
            100.0,
            0.72 * rf_score
            + 0.08 * candidate.proximity_score
            + 0.07 * candidate.access_score
            + 0.04 * candidate.deployment_score
            + 0.04 * candidate.terrain_score
            + 0.05 * zone_score
            + 0.03 * inside_depth_score
            - margin_penalty,
        ),
    )
    if candidate.rf_core_status.startswith("ok") and candidate.confidence != "low":
        candidate.confidence = "medium"
    elif not candidate.rf_core_status.startswith("ok"):
        candidate.confidence = "low"


def _margin_stats(margins: list[float]) -> tuple[float, float, float]:
    if not margins:
        return 0.0, -999.0, -999.0
    sorted_margins = sorted(margins)
    coverage_pct = 100.0 * sum(1 for margin in sorted_margins if margin >= 0.0) / len(sorted_margins)
    return coverage_pct, sorted_margins[0], sorted_margins[len(sorted_margins) // 2]


def _margin_quality_stats(margins: list[float]) -> tuple[float, float, float, float, float]:
    if not margins:
        return 100.0, 0.0, 0.0, 0.0, 0.0
    total = len(margins)
    unusable = sum(1 for margin in margins if margin < 0.0)
    weak = sum(1 for margin in margins if 0.0 <= margin < 8.0)
    usable = sum(1 for margin in margins if 8.0 <= margin < 18.0)
    strong = sum(1 for margin in margins if margin >= 18.0)
    unusable_pct = 100.0 * unusable / total
    weak_pct = 100.0 * weak / total
    usable_pct = 100.0 * usable / total
    strong_pct = 100.0 * strong / total
    quality_score = strong_pct + usable_pct * 0.72 + weak_pct * 0.35
    return unusable_pct, weak_pct, usable_pct, strong_pct, quality_score


def _candidate_service_status(candidate: Candidate, rf: dict[str, Any]) -> tuple[bool, str]:
    if not rf.get("include_uplink", True):
        ok = candidate.downlink_coverage_pct >= float(rf["coverage_goal_pct"]) and candidate.downlink_median_margin_db >= float(
            rf["median_margin_goal_db"]
        )
        return ok, "downlink ok" if ok else "downlink poor"

    ok = (
        candidate.coverage_pct >= float(rf["coverage_goal_pct"])
        and candidate.median_margin_db >= float(rf["median_margin_goal_db"])
        and candidate.downlink_coverage_pct >= float(rf["coverage_goal_pct"])
        and candidate.downlink_median_margin_db >= float(rf["median_margin_goal_db"])
        and candidate.uplink_coverage_pct >= float(rf["coverage_goal_pct"])
        and candidate.uplink_median_margin_db >= float(rf["median_margin_goal_db"])
    )
    if ok:
        return True, "two-way portable ok" if rf.get("user_radio") == "portable" else "two-way mobile ok"
    if candidate.downlink_coverage_pct >= float(rf["coverage_goal_pct"]) and candidate.uplink_coverage_pct < float(rf["coverage_goal_pct"]):
        return False, "downlink only / talkback poor"
    if candidate.uplink_median_margin_db < float(rf["median_margin_goal_db"]):
        return False, "talkback margin poor"
    return False, "not suitable for portable" if rf.get("user_radio") == "portable" else "not suitable"


def _rf_service_score(candidate: Candidate, rf: dict[str, Any]) -> float:
    median_goal = float(rf["median_margin_goal_db"])
    limiting_coverage, limiting_median, limiting_min_margin = _limiting_rf_metrics(candidate, rf)
    median_component = max(0.0, min(100.0, 50.0 + (limiting_median - median_goal) * 4.0))
    floor_component = max(0.0, min(100.0, 50.0 + limiting_min_margin * 4.0))
    score = (
        0.42 * limiting_coverage
        + 0.42 * candidate.rf_quality_score
        + 0.12 * median_component
        + 0.04 * floor_component
    )
    if not candidate.service_ok:
        score -= 28.0
    return max(0.0, min(100.0, score))


def _limiting_rf_metrics(candidate: Candidate, rf: dict[str, Any]) -> tuple[float, float, float]:
    if rf.get("include_uplink", True):
        return (
            min(candidate.downlink_coverage_pct, candidate.uplink_coverage_pct, candidate.coverage_pct),
            min(candidate.downlink_median_margin_db, candidate.uplink_median_margin_db, candidate.median_margin_db),
            min(candidate.downlink_min_margin_db, candidate.uplink_min_margin_db, candidate.min_margin_db),
        )
    return candidate.downlink_coverage_pct, candidate.downlink_median_margin_db, candidate.downlink_min_margin_db


def _excess_margin_distance_penalty(candidate: Candidate, rf: dict[str, Any]) -> float:
    if not candidate.service_ok:
        return 0.0
    if str(rf.get("site_preference")) == "favour_inside_area" and candidate.target_inside_area:
        return 0.0
    goal = float(rf["median_margin_goal_db"])
    if rf.get("include_uplink", True):
        limiting_median = min(candidate.downlink_median_margin_db, candidate.uplink_median_margin_db)
    else:
        limiting_median = candidate.downlink_median_margin_db
    margin_surplus = max(0.0, limiting_median - goal)
    if margin_surplus >= 18.0:
        return min(14.0, candidate.target_edge_distance_km * 3.5)
    if margin_surplus >= 10.0:
        return min(8.0, candidate.target_edge_distance_km * 2.0)
    return 0.0


def _candidate_rank_key(candidate: Candidate, rf: dict[str, Any]) -> tuple[float, ...]:
    site_preference = str(rf.get("site_preference", "favour_edge"))
    preferred_zone = _preferred_zone_score(candidate, site_preference)
    service_tier = 2.0 if candidate.service_ok else 0.0
    if candidate.service_ok and site_preference == "favour_inside_area" and candidate.target_inside_area:
        service_tier = 3.0
    if candidate.service_ok and site_preference == "favour_edge" and not candidate.target_inside_area and candidate.target_edge_distance_km <= 1.5:
        service_tier = 3.0
    limiting_coverage, limiting_margin, limiting_min_margin = _limiting_rf_metrics(candidate, rf)
    inside_depth_score = _inside_depth_score(candidate.target_edge_distance_km, rf) if candidate.target_inside_area else 0.0
    return (
        service_tier,
        preferred_zone,
        candidate.rf_service_score,
        candidate.rf_quality_score,
        limiting_coverage,
        min(limiting_margin, 35.0),
        max(-30.0, min(limiting_min_margin, 20.0)),
        candidate.suitability_score,
        inside_depth_score if site_preference == "favour_inside_area" else candidate.proximity_score,
        candidate.access_score,
        -candidate.target_edge_distance_km,
        -candidate.elevation_m,
    )


def _preferred_zone_score(candidate: Candidate, site_preference: str) -> float:
    if site_preference == "favour_inside_area":
        return 1.0 if candidate.target_inside_area else 0.0
    if candidate.target_inside_area:
        return 0.0
    if candidate.target_edge_distance_km <= 1.5:
        return 1.0
    return 0.5


def _recommendation_policy(road_meta: dict[str, Any]) -> dict[str, Any]:
    """Describe the recommendation gate for the current MVP data basis.

    The MVP has a real DEM and ITM engine, but it does not model clutter or
    surface correction and its road/access inputs are screening data. Those
    limitations make a ranked site useful for field planning without making
    it a final recommendation. Keep this policy separate from confidence so a
    failed ITM path can still independently force low confidence.
    """
    road_dataset = str(road_meta.get("dataset", "")).lower()
    road_basis = (
        "simplified road/access data"
        if "simplified" in road_dataset
        else "screening-level road/access data"
    )
    limitations = [
        "DEM-only terrain data",
        "no clutter or surface correction",
        road_basis,
    ]
    return {
        "status": "best_available_verify",
        "label": "best available — verify",
        "recommended": False,
        "field_verification_required": True,
        "warning": (
            "Field verification required: "
            f"{', '.join(limitations)} support screening only, not a final recommendation."
        ),
        "limitations": limitations,
    }


def _assessment_payload(
    candidates: list[Candidate],
    display_count: int,
    rf: dict[str, Any],
    recommendation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ok_candidates = [candidate for candidate in candidates if candidate.service_ok]
    goal = float(rf["coverage_goal_pct"])
    recommendation = recommendation or _recommendation_policy({})
    if ok_candidates:
        status = "two_way_portable_ok_found" if rf.get("user_radio") == "portable" else "two_way_ok_found"
        message = (
            f"{recommendation['label'].capitalize()}. "
            f"Found {len(ok_candidates)} candidate(s) meeting the {goal:.0f}% two-way service goal. "
            f"{recommendation['warning']}"
        )
    else:
        status = "no_two_way_portable_ok_found" if rf.get("user_radio") == "portable" else "no_two_way_ok_found"
        message = (
            f"No candidate in the evaluated search area met the {goal:.0f}% two-way portable service goal. "
            f"{recommendation['label'].capitalize()}; widen the search area or move the repeater toward a better valley-edge site. "
            f"{recommendation['warning']}"
        )
    return {
        "status": status,
        "message": message,
        "recommendation_status": recommendation["status"],
        "recommendation_label": recommendation["label"],
        "recommended": recommendation["recommended"],
        "field_verification_required": recommendation["field_verification_required"],
        "field_verification_warning": recommendation["warning"],
        "coverage_goal_pct": goal,
        "median_margin_goal_db": float(rf["median_margin_goal_db"]),
        "rx_thresholds": rf["rx_thresholds"],
        "evaluated_candidates": len(candidates),
        "displayed_candidates": min(display_count, len(candidates)),
        "ok_candidate_count": len(ok_candidates),
    }


def _coverage_cells(
    candidate: Candidate,
    target_points: list[tuple[float, float]],
    terrain: TerrainProvider,
    rf: dict[str, Any],
    path_cache: dict[str, tuple[float | None, str]],
    viewport: BBox,
    itm_worker: ItmBatchWorker | None = None,
) -> list[dict[str, float]]:
    cells: list[dict[str, float]] = []
    for lat, lon in target_points:
        margin, downlink_margin, uplink_margin = _link_margin(
            candidate, (lat, lon), terrain, rf, path_cache, itm_worker
        )
        x, y = _normalise_point(lat, lon, viewport)
        cells.append(
            {
                "x": x,
                "y": y,
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "margin_db": round(margin, 2),
                "downlink_margin_db": round(downlink_margin, 2),
                "uplink_margin_db": round(uplink_margin, 2),
            }
        )
    return cells


def _terrain_resolution(search_radius_km: float) -> tuple[int, int]:
    if search_radius_km <= 5:
        return 70, 96
    if search_radius_km <= 12:
        return 46, 64
    return 30, 44


def _link_margin(
    candidate: Candidate,
    point: tuple[float, float],
    terrain: TerrainProvider,
    rf: dict[str, Any],
    path_cache: dict[str, tuple[float | None, str]],
    itm_worker: ItmBatchWorker | None = None,
) -> tuple[float, float, float]:
    downlink_path_loss, downlink_status = _path_loss_itm(
        (candidate.lat, candidate.lon),
        point,
        terrain,
        rf,
        downlink=True,
        path_cache=path_cache,
        itm_worker=itm_worker,
    )
    if downlink_path_loss is None:
        candidate.rf_core_status = f"ITM downlink failed: {downlink_status}"
        return FAILED_PATH_MARGIN_DB, FAILED_PATH_MARGIN_DB, FAILED_PATH_MARGIN_DB

    portable_rx_threshold = _rx_threshold(rf, "portable_rx")
    downlink_rx_dbm = (
        float(rf["tx_power_dbm"])
        + float(rf["antenna_gain_dbi"])
        - float(rf["system_losses_db"])
        - downlink_path_loss
        + float(rf["user_antenna_gain_dbi"])
        - float(rf["user_losses_db"])
    )
    downlink_margin = downlink_rx_dbm - float(portable_rx_threshold["threshold_dbm"])

    if not rf.get("include_uplink", True):
        return downlink_margin, downlink_margin, 999.0

    uplink_path_loss, uplink_status = _path_loss_itm(
        (candidate.lat, candidate.lon),
        point,
        terrain,
        rf,
        downlink=False,
        path_cache=path_cache,
        itm_worker=itm_worker,
    )
    if uplink_path_loss is None:
        candidate.rf_core_status = f"ITM uplink failed: {uplink_status}"
        return min(downlink_margin, FAILED_PATH_MARGIN_DB), downlink_margin, FAILED_PATH_MARGIN_DB

    uplink_tx_dbm = 10.0 * math.log10(float(rf["uplink_power_w"]) * 1000.0)
    uplink_rx_dbm = (
        uplink_tx_dbm
        + float(rf["user_antenna_gain_dbi"])
        - float(rf["user_losses_db"])
        - uplink_path_loss
        + float(rf["antenna_gain_dbi"])
        - float(rf["system_losses_db"])
    )
    repeater_rx_threshold = _rx_threshold(rf, "repeater_rx")
    uplink_margin = uplink_rx_dbm - float(repeater_rx_threshold["threshold_dbm"])
    return min(downlink_margin, uplink_margin), downlink_margin, uplink_margin


def _path_loss_itm(
    site: tuple[float, float],
    point: tuple[float, float],
    terrain: TerrainProvider,
    rf: dict[str, Any],
    downlink: bool,
    path_cache: dict[str, tuple[float | None, str]],
    itm_worker: ItmBatchWorker | None = None,
) -> tuple[float | None, str]:
    start = site if downlink else point
    end = point if downlink else site
    tx_height = float(rf["tx_height_m"]) if downlink else float(rf["rx_height_m"])
    rx_height = float(rf["rx_height_m"]) if downlink else float(rf["tx_height_m"])
    cache_key = "|".join(
        [
            f"{start[0]:.5f},{start[1]:.5f}",
            f"{end[0]:.5f},{end[1]:.5f}",
            f"{float(rf['frequency_mhz']):.4f}",
            f"{tx_height:.2f}",
            f"{rx_height:.2f}",
            f"{float(rf['location_percent']):.1f}",
            f"{float(rf['time_percent']):.1f}",
            f"{float(rf['situation_percent']):.1f}",
        ]
    )
    if cache_key in path_cache:
        return path_cache[cache_key]

    if not RF_CORE_BIN.exists():
        return None, "rf-core binary missing"

    pfl = _build_pfl(start, end, terrain)
    path: Path | None = None
    try:
        if itm_worker is not None:
            payload = itm_worker.calculate(pfl, tx_height, rx_height, rf)
        else:
            # Retain the direct one-shot path for callers/tests that invoke
            # this low-level helper outside run_analysis. The production
            # analysis path always supplies ItmBatchWorker above.
            with tempfile.NamedTemporaryFile("w", suffix=".pfl.csv", delete=False) as handle:
                handle.write(",".join(f"{value:.3f}" for value in pfl))
                path = Path(handle.name)
            completed = subprocess.run(
                [
                    str(RF_CORE_BIN),
                    str(path),
                    "--freq-mhz",
                    str(float(rf["frequency_mhz"])),
                    "--tx-height-m",
                    str(tx_height),
                    "--rx-height-m",
                    str(rx_height),
                    "--location-pct",
                    str(float(rf["location_percent"])),
                    "--time-pct",
                    str(float(rf["time_percent"])),
                    "--situation-pct",
                    str(float(rf["situation_percent"])),
                ],
                capture_output=True,
                text=True,
                timeout=8,
            )
            payload = json.loads(completed.stdout)
        path_loss = float(payload["path_loss_db"])
        error_code = int(payload.get("error_code", 0))
        expected_returncode = 0 if error_code == 0 else 2
        if error_code not in (0, 1) or (
            itm_worker is None and completed.returncode != expected_returncode
        ):
            raise RuntimeError(
                f"rf-core exit {completed.returncode}; ITM error code {error_code}"
            )
        if not math.isfinite(path_loss):
            raise ValueError("ITM path loss is not finite")
        status = "ok" if error_code == 0 else f"ok; itm warning {error_code}"
        path_cache[cache_key] = (path_loss, status)
        return path_loss, status
    except (
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
        KeyError,
        ValueError,
    ) as error:
        path_cache[cache_key] = (None, f"rf-core failed: {error}")
        return path_cache[cache_key]
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


def _build_pfl(start: tuple[float, float], end: tuple[float, float], terrain: TerrainProvider) -> list[float]:
    distance_km = max(0.1, haversine_km(start[0], start[1], end[0], end[1]))
    distance_m = distance_km * 1000.0
    target_spacing_m = 40.0 if distance_m <= 5000.0 else 80.0 if distance_m <= 15000.0 else 150.0
    intervals = max(2, min(900, math.ceil(distance_m / target_spacing_m)))
    spacing = distance_m / intervals
    values = [float(intervals), spacing]
    for index in range(intervals + 1):
        t = index / intervals
        lat = start[0] + (end[0] - start[0]) * t
        lon = start[1] + (end[1] - start[1]) * t
        values.append(terrain.sample(lat, lon))
    return values


def _target_grid_points(polygon: list[tuple[float, float]], max_cells: int) -> list[tuple[float, float]]:
    south = min(lat for lat, _ in polygon)
    north = max(lat for lat, _ in polygon)
    west = min(lon for _, lon in polygon)
    east = max(lon for _, lon in polygon)
    rows = max(9, int(math.sqrt(max_cells)))
    cols = rows
    points: list[tuple[float, float]] = []
    for row in range(rows):
        lat = south + (row + 0.5) * (north - south) / rows
        for col in range(cols):
            lon = west + (col + 0.5) * (east - west) / cols
            if _point_in_polygon((lat, lon), polygon):
                _append_unique_point(points, (lat, lon))
    _append_unique_point(points, _polygon_centroid(polygon))
    for point in polygon:
        _append_unique_point(points, point)
    for start, end in zip(polygon, polygon[1:] + polygon[:1]):
        edge_km = haversine_km(start[0], start[1], end[0], end[1])
        steps = max(1, min(8, math.ceil(edge_km / 0.12)))
        for index in range(1, steps):
            t = index / steps
            _append_unique_point(points, (start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t))
    if not points:
        points.append(_polygon_centroid(polygon))
    return points


def _append_unique_point(points: list[tuple[float, float]], point: tuple[float, float], min_distance_km: float = 0.035) -> None:
    if all(haversine_km(point[0], point[1], existing[0], existing[1]) >= min_distance_km for existing in points):
        points.append(point)


def _terrain_cells(terrain: TerrainProvider, viewport: BBox, rows: int, cols: int) -> list[dict[str, float]]:
    samples: list[tuple[float, float, float]] = []
    for row in range(rows):
        lat = viewport.south + (row + 0.5) * (viewport.north - viewport.south) / rows
        for col in range(cols):
            lon = viewport.west + (col + 0.5) * (viewport.east - viewport.west) / cols
            samples.append((lat, lon, terrain.sample(lat, lon)))

    elevations = [value for _, _, value in samples]
    low = min(elevations)
    high = max(elevations)
    spread = max(1.0, high - low)
    cells: list[dict[str, float]] = []
    for lat, lon, elev in samples:
        x, y = _normalise_point(lat, lon, viewport)
        cells.append({"x": x, "y": y, "elevation_m": round(elev, 1), "shade": round((elev - low) / spread, 3)})
    return cells


def _road_payload(road: Road, viewport: BBox) -> list[list[float]]:
    return [list(_normalise_point(lat, lon, viewport)) for lat, lon in road.geometry]


def _display_road_payload(road: Road, viewport: BBox) -> dict[str, Any]:
    return {
        "name": road.name,
        "highway": road.highway,
        "surface": road.surface,
        "source_layer": road.source_layer,
        "kind": _display_road_kind(road),
        "points": _road_payload(road, viewport),
    }


def _display_road_kind(road: Road) -> str:
    if road.source_layer == 31 or road.highway in {"path", "footway", "cycleway", "bridleway"}:
        return "trail"
    if road.source_layer in {19, 20} or road.highway in {"unclassified", "residential", "service", "track"}:
        return "minor"
    return "major"


def _candidate_payload(
    rank: int,
    candidate: Candidate,
    viewport: BBox,
    rf: dict[str, Any],
    coverage_cells: list[dict[str, float]],
    recommendation: dict[str, Any],
) -> dict[str, Any]:
    x, y = _normalise_point(candidate.lat, candidate.lon, viewport)
    access_uncertainty = candidate.access_uncertainty or _mapped_access_uncertainty()
    warning = f"{recommendation['warning']} {candidate.deployment_warning} {access_uncertainty}".strip()
    if candidate.confidence == "low":
        warning = f"{warning} RF/data confidence low.".strip()
    return {
        "rank": rank,
        "candidate_id": candidate.candidate_id,
        "source": candidate.source,
        "name": candidate.name,
        "x": x,
        "y": y,
        "lon": round(candidate.lon, 6),
        "lat": round(candidate.lat, 6),
        "elevation_m": round(candidate.elevation_m, 1),
        "height_above_target_m": round(candidate.elevation_m - float(rf["target_elevation_m"]), 1),
        "local_relief_m": round(candidate.local_relief_m, 1),
        "slope_deg": round(candidate.slope_deg, 1),
        "access_distance_km": round(candidate.access_distance_km, 2),
        "target_edge_distance_km": round(candidate.target_edge_distance_km, 2),
        "target_inside_area": candidate.target_inside_area,
        "road_name": candidate.road_name,
        "road_class": candidate.road_class,
        "surface": candidate.surface,
        "reference_road_name": candidate.reference_road_name,
        "reference_road_distance_km": round(candidate.reference_road_distance_km, 2),
        "access_source": candidate.access_source or _mapped_access_source(
            Road("unknown", candidate.road_name, candidate.road_class, candidate.surface, [(candidate.lat, candidate.lon)])
        ),
        "access_uncertainty": access_uncertainty,
        "deployment_score": round(candidate.deployment_score, 1),
        "deployment_warning": candidate.deployment_warning,
        "access_class": _access_class(str(rf["deployment_profile"]), candidate),
        "service_profile": SERVICE_PROFILES[str(rf["service_profile"])]["name"],
        "rx_thresholds": rf["rx_thresholds"],
        "service_status": candidate.service_status,
        "service_ok": candidate.service_ok,
        "coverage_cells": coverage_cells,
        "coverage_pct": round(candidate.coverage_pct, 1),
        "min_margin_db": round(candidate.min_margin_db, 1),
        "median_margin_db": round(candidate.median_margin_db, 1),
        "downlink_coverage_pct": round(candidate.downlink_coverage_pct, 1),
        "downlink_min_margin_db": round(candidate.downlink_min_margin_db, 1),
        "downlink_median_margin_db": round(candidate.downlink_median_margin_db, 1),
        "uplink_coverage_pct": round(candidate.uplink_coverage_pct, 1),
        "uplink_min_margin_db": round(candidate.uplink_min_margin_db, 1),
        "uplink_median_margin_db": round(candidate.uplink_median_margin_db, 1),
        "unusable_signal_pct": round(candidate.unusable_signal_pct, 1),
        "weak_signal_pct": round(candidate.weak_signal_pct, 1),
        "usable_signal_pct": round(candidate.usable_signal_pct, 1),
        "strong_signal_pct": round(candidate.strong_signal_pct, 1),
        "rf_quality_score": round(candidate.rf_quality_score, 1),
        "rf_service_score": round(candidate.rf_service_score, 1),
        "rf_pre_score": round(candidate.rf_pre_score, 1),
        "suitability_score": round(candidate.suitability_score, 1),
        "confidence": candidate.confidence,
        "downlink_status": "ok"
        if candidate.downlink_coverage_pct >= float(rf["coverage_goal_pct"])
        and candidate.downlink_median_margin_db >= float(rf["median_margin_goal_db"])
        else "poor",
        "uplink_status": "ok"
        if not rf.get("include_uplink", True)
        or (
            candidate.uplink_coverage_pct >= float(rf["coverage_goal_pct"])
            and candidate.uplink_median_margin_db >= float(rf["median_margin_goal_db"])
        )
        else "poor",
        "centroid_path_loss_db": None if candidate.centroid_path_loss_db is None else round(candidate.centroid_path_loss_db, 2),
        "rf_core_status": candidate.rf_core_status,
        "warnings": warning or "Field verification required.",
        "recommendation_status": recommendation["status"],
        "recommendation_label": recommendation["label"],
        "recommended": recommendation["recommended"],
        "field_verification_required": recommendation["field_verification_required"],
        "explanation": [
            f"Service assessment: {candidate.service_status}.",
            f"ITM predicted {candidate.coverage_pct:.1f}% of target cells meeting the two-way threshold; goal is {float(rf['coverage_goal_pct']):.0f}%.",
            f"Two-way signal quality across target cells: {candidate.strong_signal_pct:.1f}% strong, {candidate.usable_signal_pct:.1f}% usable, {candidate.weak_signal_pct:.1f}% weak, {candidate.unusable_signal_pct:.1f}% unusable.",
            f"Uplink/talkback coverage {candidate.uplink_coverage_pct:.1f}% with median margin {candidate.uplink_median_margin_db:.1f} dB.",
            f"Downlink coverage {candidate.downlink_coverage_pct:.1f}% with median margin {candidate.downlink_median_margin_db:.1f} dB.",
            f"Downlink gate: {float(rf['rx_thresholds']['portable_rx']['threshold_dbm']):.0f} dBm at {float(rf['rx_thresholds']['portable_rx']['noise_floor_dbm']):.0f} dBm noise, {float(rf['rx_thresholds']['portable_rx']['required_snr_db']):.0f} dB SNR, {float(rf['rx_thresholds']['portable_rx']['fade_margin_db']):.0f} dB fade; portable gate is unchanged by repeater-RX settings.",
            f"Talkback gate: {float(rf['rx_thresholds']['repeater_rx']['threshold_dbm']):.0f} dBm at {float(rf['rx_thresholds']['repeater_rx']['noise_floor_dbm']):.0f} dBm noise, {float(rf['rx_thresholds']['repeater_rx']['required_snr_db']):.0f} dB SNR, {float(rf['rx_thresholds']['repeater_rx']['fade_margin_db']):.0f} dB fade; {rf['rx_thresholds']['repeater_rx']['basis']}.",
            f"Site selection preference: {SITE_PREFERENCES[str(rf['site_preference'])]['name']}.",
            f"Candidate is {candidate.target_edge_distance_km:.2f} km from the target edge near {candidate.reference_road_name or candidate.road_name}; mapped access is {candidate.road_class} ({candidate.road_name}) with {candidate.local_relief_m:.1f} m local relief.",
            f"Deployment suitability: {_access_class(str(rf['deployment_profile']), candidate)}.",
        ],
    }


def _deployment_profile(profile_id: str) -> dict[str, Any]:
    if profile_id == "repeater_trailer_solar":
        return {
            "id": profile_id,
            "name": "Repeater trailer, solar + battery",
            "summary": "Towable repeater trailer with mast, solar panels, battery system, and stabilisation requirements.",
            "site_checks": ["towable approach", "turnaround", "level parking", "mast clearance", "solar exposure", "battery/charger status"],
        }
    return {
        "id": "pushup_mast_lifepo4",
        "name": "Push-up mast + LiFePO4 packs",
        "summary": "Portable push-up mast deployment with repeater package and LiFePO4 battery packs.",
        "site_checks": ["carry distance", "guy/anchor footprint", "wind exposure", "battery state-of-charge", "safe mast base", "RF exposure separation"],
    }


def _deployment_suitability(profile_id: str, road: Road, slope_deg: float) -> tuple[float, str]:
    road_factor = ROAD_ACCESS_FACTOR.get(road.highway, 0.25)
    slope_penalty = max(0.0, slope_deg - 6.0) * 2.5
    if profile_id == "repeater_trailer_solar":
        if road.highway in {"path", "footway", "cycleway", "bridleway"}:
            return 10.0, "Mapped way is not suitable for repeater trailer access."
        if road.highway == "track":
            return max(25.0, 62.0 - slope_penalty), "Trailer access on mapped track requires field check for width, surface, turnaround, and recovery."
        return max(35.0, min(100.0, 95.0 * road_factor - slope_penalty)), "Check level trailer parking, stabilisation, mast clearance, and solar exposure."

    if road.highway in {"path", "footway", "cycleway", "bridleway"}:
        return max(25.0, 48.0 - slope_penalty), "Portable mast may require walk-in carry; confirm battery pack carry distance and guying footprint."
    return max(40.0, min(100.0, 88.0 * road_factor - slope_penalty)), "Check mast guying/anchoring footprint, wind exposure, and LiFePO4 battery endurance."


def _access_class(profile_id: str, candidate: Candidate) -> str:
    if profile_id == "repeater_trailer_solar":
        if candidate.road_class in {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "service"} and candidate.slope_deg < 8:
            return "likely repeater-trailer accessible"
        if candidate.road_class == "track":
            return "possible 4WD tow access; verify track"
        return "unknown/field verification required"

    if candidate.road_class in {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "service", "track"}:
        return "likely 4WD ute accessible for portable mast"
    return "walk-in or unknown; verify carry distance"


def _candidate_name(
    road: Road,
    lat: float,
    lon: float,
    reference_name: str | None = None,
    exact_reference: bool = False,
    relief_m: float = 0.0,
    slope_deg: float = 0.0,
) -> str:
    descriptor = _site_descriptor(road, relief_m, slope_deg)
    clean_reference = _clean_road_name(reference_name)
    if clean_reference and exact_reference:
        return f"{clean_reference} {descriptor}"
    if clean_reference:
        if road.highway == "track":
            return f"Track access near {clean_reference}"
        if road.highway in WALKING_ACCESS_HIGHWAYS:
            return f"Walk-in site near {clean_reference}"
        return f"{descriptor.title()} near {clean_reference}"
    return f"{descriptor.title()} {abs(hash((round(lat, 3), round(lon, 3)))) % 1000:03d}"


def _site_descriptor(road: Road, relief_m: float, slope_deg: float) -> str:
    if road.highway in WALKING_ACCESS_HIGHWAYS:
        return "walk-in site"
    if road.highway == "track":
        return "track access"
    if relief_m >= 35.0 and slope_deg <= 8.0:
        return "ridge"
    if relief_m >= 18.0:
        return "rise"
    if slope_deg >= 10.0:
        return "slope"
    return "deployment site"


def _terrain_score(elevation_m: float, relief_m: float, slope_deg: float, height_above_target_m: float = 0.0) -> float:
    """Score a temporary-repeater position over the target area.

    A useful temporary radio position is high relative to the people it must
    cover and stands out from nearby terrain. Regional high ground or a broad
    high-ASL plateau is not necessarily useful, so absolute elevation is
    intentionally display-only here. The bounded components keep the result
    on the historical 0--100 scale while making relative height and relief
    the primary terrain drivers.
    """
    target_height_score = max(0.0, min(55.0, max(0.0, height_above_target_m) * 1.25))
    relief_score = max(0.0, min(40.0, max(0.0, relief_m) * 1.0))
    slope_penalty = max(0.0, slope_deg - 10.0) * 1.8
    return max(0.0, min(100.0, target_height_score + relief_score - slope_penalty))


def _local_relief_m(terrain: TerrainProvider, lat: float, lon: float) -> float:
    centre = terrain.sample(lat, lon)
    samples = [terrain.sample(*destination_point(lat, lon, 1.5, bearing)) for bearing in range(0, 360, 45)]
    return centre - (sum(samples) / len(samples))


def _slope_deg(terrain: TerrainProvider, lat: float, lon: float) -> float:
    north = terrain.sample(*destination_point(lat, lon, 0.09, 0))
    south = terrain.sample(*destination_point(lat, lon, 0.09, 180))
    east = terrain.sample(*destination_point(lat, lon, 0.09, 90))
    west = terrain.sample(*destination_point(lat, lon, 0.09, 270))
    dz_dy = (north - south) / 180.0
    dz_dx = (east - west) / 180.0
    return math.degrees(math.atan(math.hypot(dz_dx, dz_dy)))


def _sample_polyline(points: list[tuple[float, float]], step_km: float) -> list[tuple[float, float]]:
    samples: list[tuple[float, float]] = []
    for start, end in zip(points, points[1:]):
        distance = haversine_km(start[0], start[1], end[0], end[1])
        steps = max(1, int(math.ceil(distance / step_km)))
        for index in range(steps):
            t = index / steps
            samples.append((start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t))
    samples.append(points[-1])
    return samples


def _road_length_km(road: Road) -> float:
    return sum(haversine_km(a[0], a[1], b[0], b[1]) for a, b in zip(road.geometry, road.geometry[1:]))


def _road_target_distance_km(
    road: Road,
    target_polygon: list[tuple[float, float]] | None,
    center: tuple[float, float],
) -> float:
    if target_polygon:
        return min(_distance_to_polygon_km(lat, lon, target_polygon) for lat, lon in road.geometry)
    return min(haversine_km(lat, lon, center[0], center[1]) for lat, lon in road.geometry)


def _target_proximity_score(distance_km: float, polygon_mode: bool, inside_area: bool, site_preference: str) -> float:
    if not polygon_mode:
        return max(0.0, min(100.0, 100.0 - distance_km * 8.0))

    if site_preference == "favour_inside_area":
        if inside_area:
            return max(72.0, min(100.0, 72.0 + distance_km * 28.0))
        if distance_km <= 0.25:
            return 92.0 - distance_km * 20.0
        if distance_km <= 1.0:
            return 87.0 - (distance_km - 0.25) * 50.0
        return max(0.0, 49.5 - (distance_km - 1.0) * 35.0)

    if inside_area:
        return 74.0
    if distance_km <= 0.05:
        return 100.0
    if distance_km <= 0.8:
        return 98.0 - distance_km * 10.0
    if distance_km <= 1.5:
        return 91.0 - (distance_km - 0.8) * 35.0
    return max(0.0, 66.5 - (distance_km - 1.5) * 32.0)


def _inside_depth_score(boundary_distance_km: float, rf: dict[str, Any]) -> float:
    area_sq_km = max(0.1, float(rf.get("target_area_sq_km", 0.1)))
    equivalent_radius_km = math.sqrt(area_sq_km / math.pi)
    useful_depth_km = max(0.25, equivalent_radius_km * 0.45)
    return max(0.0, min(100.0, 100.0 * float(boundary_distance_km) / useful_depth_km))


def _circle_polygon(lat: float, lon: float, radius_km: float, count: int) -> list[tuple[float, float]]:
    return [destination_point(lat, lon, radius_km, bearing) for bearing in [index * 360.0 / count for index in range(count)]]


def _polygon_centroid(polygon: list[tuple[float, float]]) -> tuple[float, float]:
    return (sum(point[0] for point in polygon) / len(polygon), sum(point[1] for point in polygon) / len(polygon))


def _polygon_area_sq_km(polygon: list[tuple[float, float]]) -> float:
    if len(polygon) < 3:
        return 0.0
    origin_lat, origin_lon = polygon[0]
    radius = 6371.0088
    cos_origin = math.cos(math.radians(origin_lat))
    projected = [
        (
            math.radians(lon - origin_lon) * cos_origin * radius,
            math.radians(lat - origin_lat) * radius,
        )
        for lat, lon in polygon
    ]
    area = 0.0
    for index, (x1, y1) in enumerate(projected):
        x2, y2 = projected[(index + 1) % len(projected)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    lat, lon = point
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        lati, loni = polygon[i]
        latj, lonj = polygon[j]
        intersects = ((lati > lat) != (latj > lat)) and (
            lon < (lonj - loni) * (lat - lati) / ((latj - lati) or 1e-12) + loni
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def _distance_to_polygon_km(lat: float, lon: float, polygon: list[tuple[float, float]]) -> float:
    if _point_in_polygon((lat, lon), polygon):
        return 0.0
    return _distance_to_polygon_boundary_km(lat, lon, polygon)


def _distance_to_polygon_boundary_km(lat: float, lon: float, polygon: list[tuple[float, float]]) -> float:
    radius = 6371.0088
    cos_lat = math.cos(math.radians(lat))

    def project(point_lat: float, point_lon: float) -> tuple[float, float]:
        x = math.radians(point_lon - lon) * cos_lat * radius
        y = math.radians(point_lat - lat) * radius
        return x, y

    min_distance = float("inf")
    for start, end in zip(polygon, polygon[1:] + polygon[:1]):
        ax, ay = project(start[0], start[1])
        bx, by = project(end[0], end[1])
        dx = bx - ax
        dy = by - ay
        length_sq = dx * dx + dy * dy
        if length_sq <= 1e-12:
            distance = math.hypot(ax, ay)
        else:
            t = _clamp((-(ax * dx + ay * dy)) / length_sq, 0.0, 1.0)
            distance = math.hypot(ax + t * dx, ay + t * dy)
        min_distance = min(min_distance, distance)
    return min_distance


def _normalise_point(lat: float, lon: float, viewport: BBox) -> tuple[float, float]:
    x = (lon - viewport.west) / max(1e-9, viewport.east - viewport.west)
    y = (lat - viewport.south) / max(1e-9, viewport.north - viewport.south)
    return (_clamp(x, 0.0, 1.0), _clamp(y, 0.0, 1.0))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def _free_space_loss_db(site: tuple[float, float], point: tuple[float, float], frequency_mhz: float) -> float:
    """Return a cheap free-space estimate for Phase A only.

    This heuristic is never used as a replacement for a failed ITM path.
    Final margins and service status continue to come only from full ITM.
    """
    distance_km = max(0.001, haversine_km(site[0], site[1], point[0], point[1]))
    return 32.44 + 20.0 * math.log10(frequency_mhz) + 20.0 * math.log10(distance_km)


def destination_point(lat: float, lon: float, distance_km: float, bearing_deg: float) -> tuple[float, float]:
    radius = 6371.0088
    bearing = math.radians(bearing_deg)
    phi1 = math.radians(lat)
    lambda1 = math.radians(lon)
    delta = distance_km / radius
    phi2 = math.asin(math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(bearing))
    lambda2 = lambda1 + math.atan2(
        math.sin(bearing) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    return (math.degrees(phi2), math.degrees(lambda2))


def _hgt_tile_name(tile_lat: int, tile_lon: int) -> str:
    lat_prefix = "N" if tile_lat >= 0 else "S"
    lon_prefix = "E" if tile_lon >= 0 else "W"
    return f"{lat_prefix}{abs(tile_lat):02d}{lon_prefix}{abs(tile_lon):03d}"


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".part")
    request = Request(url, headers={"User-Agent": "rf-repeater-site-mvp/0.2"})
    with urlopen(request, timeout=45) as response:
        tmp.write_bytes(response.read())
    tmp.replace(destination)


def _ensure_rf_core() -> None:
    if RF_CORE_BIN.exists():
        return
    subprocess.run(["make", "-C", str(RF_CORE_DIR), "build"], check=True, timeout=180)


def _bbox_cache_key(bbox: BBox) -> str:
    rounded = f"roads-v2_{bbox.west:.3f}_{bbox.south:.3f}_{bbox.east:.3f}_{bbox.north:.3f}"
    return hashlib.sha1(rounded.encode("utf-8")).hexdigest()[:16]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
