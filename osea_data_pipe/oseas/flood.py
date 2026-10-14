"""Bounded, transparent Sentinel-1 event-window flood-candidate screening."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from typing import Any

METHOD_VERSION = "oseas-s1-relative-backscatter-screen-v2"
MAX_AOI_KM2 = 1000
MAX_POLYGONS = 500


def validate_bbox(bbox: list[float]) -> list[float]:
    if len(bbox) != 4:
        raise ValueError("bbox must be [min_lon,min_lat,max_lon,max_lat]")
    west, south, east, north = map(float, bbox)
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("bbox coordinates are invalid")
    # Prevent accidental national-scale interactive extraction from Earth Engine.
    width_km = (east - west) * 111.32 * max(0.05, abs(math.cos(math.radians((north + south) / 2))))
    height_km = (north - south) * 111.32
    if width_km * height_km > MAX_AOI_KM2:
        raise ValueError(f"bbox is too large for bounded vector retrieval ({MAX_AOI_KM2} km2 maximum)")
    return [west, south, east, north]


def validate_period(start: str, end: str, label: str) -> tuple[date, date]:
    start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    if end_date <= start_date:
        raise ValueError(f"{label} end must be after start; dates use an exclusive end")
    if (end_date - start_date).days > 45:
        raise ValueError(f"{label} window cannot exceed 45 days")
    return start_date, end_date


def stable_event_fingerprint(parameters: dict[str, Any]) -> str:
    canonical = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_candidate_vectors(
    ee: Any,
    bbox: list[float],
    event_start: str,
    event_end: str,
    baseline_start: str,
    baseline_end: str,
    min_backscatter_db: float = -16,
    min_drop_db: float = -3,
    max_slope_degrees: float = 5,
    permanent_water_occurrence_pct: float = 80,
    min_patch_area_m2: int = 10000,
    orbit_pass: str = "ASCENDING",
    lake_asset_id: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Use S1 VV decline with terrain/permanent-water masks; this is screening, not validated inundation."""
    bbox = validate_bbox(bbox)
    event_from, event_to = validate_period(event_start, event_end, "event")
    baseline_from, baseline_to = validate_period(baseline_start, baseline_end, "baseline")
    if max(event_from, baseline_from) < min(event_to, baseline_to):
        raise ValueError("event and baseline date windows must not overlap")
    if orbit_pass not in {"ASCENDING", "DESCENDING"}:
        raise ValueError("orbit_pass must be ASCENDING or DESCENDING")
    if not all(math.isfinite(value) for value in (min_backscatter_db, min_drop_db, max_slope_degrees, permanent_water_occurrence_pct)):
        raise ValueError("thresholds must be finite numbers")
    if not -35 <= min_backscatter_db <= 0 or not -20 <= min_drop_db < 0 or not 0 <= max_slope_degrees <= 90 or not 0 <= permanent_water_occurrence_pct <= 100 or min_patch_area_m2 <= 0:
        raise ValueError("thresholds are outside their valid ranges")

    roi = ee.Geometry.Rectangle(bbox, geodesic=False)
    sentinel = ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(roi).filter(ee.Filter.eq("instrumentMode", "IW")).filter(ee.Filter.eq("orbitProperties_pass", orbit_pass)).filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV")).select("VV")
    event_collection = sentinel.filterDate(event_start, event_end)
    baseline_collection = sentinel.filterDate(baseline_start, baseline_end)
    event_count = int(event_collection.size().getInfo())
    baseline_count = int(baseline_collection.size().getInfo())
    if not event_count or not baseline_count:
        raise RuntimeError(f"Sentinel-1 VV coverage is insufficient: event_images={event_count}, baseline_images={baseline_count}")

    def coverage_fraction(collection: Any) -> float:
        covered = collection.geometry().intersection(roi, ee.ErrorMargin(100)).area(100)
        return float(covered.divide(roi.area(100)).getInfo())

    event_coverage = coverage_fraction(event_collection)
    baseline_coverage = coverage_fraction(baseline_collection)
    if min(event_coverage, baseline_coverage) < 0.7:
        raise RuntimeError(f"Sentinel-1 coverage is incomplete: event={event_coverage:.3f}, baseline={baseline_coverage:.3f}; minimum is 0.70")
    event_scenes = event_collection.aggregate_array("system:index").getInfo()
    baseline_scenes = baseline_collection.aggregate_array("system:index").getInfo()
    event_times = event_collection.aggregate_array("system:time_start").getInfo()
    baseline_times = baseline_collection.aggregate_array("system:time_start").getInfo()
    event_footprint = event_collection.geometry().intersection(roi, ee.ErrorMargin(100)).simplify(500).getInfo()

    # Earth Engine COPERNICUS/S1_GRD values are in dB; filtering above aligns VV, IW, and AOI.
    event_vv = event_collection.median().focal_median(radius=20, units="meters")
    baseline_vv = baseline_collection.median().focal_median(radius=20, units="meters")
    drop = event_vv.subtract(baseline_vv)
    dem_collection = ee.ImageCollection("COPERNICUS/DEM/GLO30_2024_1").filterBounds(roi).select("DEM")
    dem = dem_collection.mosaic().setDefaultProjection(dem_collection.first().projection())
    slope = ee.Terrain.slope(dem)
    permanent_water = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").unmask(0)
    lake_feature_count = 0
    lake_mask = None
    if lake_asset_id:
        lakes = ee.FeatureCollection(lake_asset_id).filterBounds(roi)
        lake_feature_count = int(lakes.size().getInfo())
        if lake_feature_count:
            # Mapped lakes supplement JRC permanent water. Rivers stay contextual,
            # since buffering them could erase genuine floodplain inundation.
            lake_mask = ee.Image.constant(0).byte().paint(lakes, 1).eq(0)
    candidate = (
        event_vv.lt(min_backscatter_db)
        .And(drop.lt(min_drop_db))
        .And(slope.lt(max_slope_degrees))
        .And(permanent_water.lt(permanent_water_occurrence_pct))
    )
    if lake_mask is not None:
        candidate = candidate.And(lake_mask)
    connected = candidate.selfMask().connectedPixelCount(100, True).gte(5)
    mask = candidate.updateMask(connected)
    vector_image = mask.rename("candidate").toByte().addBands(ee.Image.pixelArea().rename("pixel_area_m2"))
    vectors = vector_image.reduceToVectors(
        reducer=ee.Reducer.sum(), geometry=roi, scale=20, geometryType="polygon",
        eightConnected=True, labelProperty="class", maxPixels=1e10, tileScale=4,
    ).filter(ee.Filter.gte("sum", min_patch_area_m2))
    vector_count = int(vectors.size().getInfo())
    if vector_count > MAX_POLYGONS:
        raise RuntimeError(f"Candidate vector count {vector_count} exceeds safe response limit {MAX_POLYGONS}; use a smaller bbox")
    vector_result = vectors.getInfo()
    features = vector_result.get("features", [])

    rain = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY").filterBounds(roi).filterDate(event_start, event_end).select("precipitation")
    rain_count = int(rain.size().getInfo())
    rainfall_mean_mm = None
    if rain_count:
        rain_sum = rain.sum()
        rain_stats = rain_sum.reduceRegion(reducer=ee.Reducer.mean(), geometry=roi, scale=5566, maxPixels=1_000_000).getInfo()
        rainfall_mean_mm = rain_stats.get("precipitation")

    quality = {
        "method_version": METHOD_VERSION,
        "event_s1_image_count": event_count,
        "baseline_s1_image_count": baseline_count,
        "event_s1_coverage_fraction": event_coverage,
        "event_observation_footprint": event_footprint,
        "baseline_s1_coverage_fraction": baseline_coverage,
        "event_s1_scene_ids": event_scenes,
        "baseline_s1_scene_ids": baseline_scenes,
        "event_s1_scene_times_ms_utc": event_times,
        "baseline_s1_scene_times_ms_utc": baseline_times,
        "sentinel1_orbit_pass": orbit_pass,
        "chirps_image_count": rain_count,
        "event_window_mean_rainfall_mm": rainfall_mean_mm,
        "mapped_lake_features_in_aoi": lake_feature_count,
        "lake_mask_asset": lake_asset_id,
        "lake_mask_role": "mapped lakes excluded as permanent water; rivers retained as flood context" if lake_asset_id else "not configured",
        "thresholds": {"event_vv_below_db": min_backscatter_db, "vv_change_below_db": min_drop_db, "slope_below_degrees": max_slope_degrees, "permanent_water_occurrence_below_pct": permanent_water_occurrence_pct, "min_patch_area_m2": min_patch_area_m2},
        "vector_scale_m": 20,
        "candidate_feature_count": vector_count,
        "evidence_kind": "modeled",
        "validation": "Not validated against independent flood reference data; candidates are not confirmed inundation.",
        "rainfall_role": "context only; not used as an event classification threshold",
    }
    return features, quality
