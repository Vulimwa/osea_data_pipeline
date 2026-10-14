#!/usr/bin/env python3
"""Fetch a small Sentinel-2 scene, run the official Prithvi flood segmenter, and persist products."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import logging
import math
import os
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from oseas.catalog import BY_KEY

LOG = logging.getLogger("oseas.prithvi")
MODEL_ID = os.getenv("PRITHVI_MODEL_ID", "ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL-Sen1Floods11")
SUPPORTED_MODEL_ID = "ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL-Sen1Floods11"
MODEL_REVISION = "91ce9d38086a80b078a192b374df758b8855b732"
CHECKPOINT = "Prithvi-EO-V2-300M-TL-Sen1Floods11.pt"
BANDS = ["B2", "B3", "B4", "B8A", "B11", "B12"]
INGEST_LOCK = "oseas_earth_engine_ingest"
MODEL_LOCK = "oseas_prithvi_flood_screen"
NAMESPACE = uuid.UUID("f31e7f78-7742-4223-8644-b45517271c2a")
MAX_AOI_KM2 = 5.0
MAX_POLYGONS = 500


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"))
    parser.add_argument("--event-start", required=True, help="Inclusive Sentinel-2 image start (YYYY-MM-DD)")
    parser.add_argument("--event-end", required=True, help="Exclusive Sentinel-2 image end (YYYY-MM-DD)")
    parser.add_argument("--scene-id", help="Pin one COPERNICUS/S2_HARMONIZED system:index for exact reproduction")
    parser.add_argument("--max-cloud-percent", type=float, default=30.0)
    parser.add_argument("--min-patch-area-m2", type=float, default=10000.0)
    parser.add_argument("--output-dir", default="outputs/prithvi")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> list[float]:
    west, south, east, north = map(float, args.bbox)
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("bbox must be an ordered EPSG:4326 box")
    if not (0 <= args.max_cloud_percent <= 100):
        raise ValueError("--max-cloud-percent must be between 0 and 100")
    if not (0 < args.min_patch_area_m2 <= 1_000_000):
        raise ValueError("--min-patch-area-m2 must be >0 and <=1,000,000")
    start, end = date.fromisoformat(args.event_start), date.fromisoformat(args.event_end)
    if start >= end or (end - start).days > 45:
        raise ValueError("event interval must be chronological and no longer than 45 days")
    from pyproj import Geod
    area = abs(Geod(ellps="WGS84").polygon_area_perimeter([west, east, east, west], [south, south, north, north])[0]) / 1_000_000
    if area > MAX_AOI_KM2:
        raise ValueError(f"Prithvi supports at most {MAX_AOI_KM2:g} km2 per local inference run; supplied bbox is {area:.2f} km2")
    return [west, south, east, north]


def _download_image(ee: Any, bbox: list[float], start: str, end: str, max_cloud: float, raw_path: Path, scene_id: str | None = None, lake_asset_id: str | None = None) -> dict[str, Any]:
    roi = ee.Geometry.Rectangle(bbox, geodesic=False)
    collection = ee.ImageCollection("COPERNICUS/S2_HARMONIZED").filterBounds(roi).filterDate(start, end).filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", max_cloud))
    if scene_id:
        collection = collection.filter(ee.Filter.eq("system:index", scene_id))
    count = int(collection.size().getInfo())
    if not count:
        raise RuntimeError("No Sentinel-2 L1C scenes match this bbox/date/cloud filter")
    image = ee.Image(collection.sort("CLOUDY_PIXEL_PERCENTAGE").first())
    qa = image.select("QA60")
    clear = qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0)).And(image.select("B2").mask())
    reflectance = image.updateMask(clear).select(BANDS)
    valid_mask = reflectance.select("B2").mask().unmask(0).rename("VALID_MASK").toInt16()
    permanent_water = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").rename("JRC_OCCURRENCE")
    lake_feature_count = 0
    lake_mask_asset = None
    if lake_asset_id:
        lakes = ee.FeatureCollection(lake_asset_id).filterBounds(roi)
        lake_feature_count = int(lakes.size().getInfo())
        if lake_feature_count:
            lake_mask_asset = ee.Image.constant(0).byte().paint(lakes, 1).rename("LAKE_MASK")
    # Sentinel-2 TOA bands are DN scaled by 10,000. Zero-filled invalid pixels
    # remain identifiable from VALID_MASK and are excluded after inference.
    image = reflectance.unmask(0).toInt16().addBands(valid_mask).addBands(permanent_water.unmask(-1).toInt16())
    if lake_mask_asset is not None:
        image = image.addBands(lake_mask_asset.toInt16())
    image = image.clip(roi)
    valid_pixels = valid_mask.reduceRegion(
        reducer=ee.Reducer.sum(), geometry=roi, scale=10, maxPixels=20_000_000, bestEffort=True
    ).get("VALID_MASK").getInfo() or 0
    expected_pixels = roi.area(10).divide(100).getInfo()
    coverage = min(1.0, float(valid_pixels) / max(float(expected_pixels), 1.0))
    if coverage < 0.5:
        raise RuntimeError(f"Cloud-free Sentinel-2 pixel coverage is only {coverage:.1%}; choose another date interval")

    lon = (bbox[0] + bbox[2]) / 2
    utm_zone = max(1, min(60, math.floor((lon + 180) / 6) + 1))
    utm_hemisphere = 32600 if (bbox[1] + bbox[3]) / 2 >= 0 else 32700
    params = {
        "name": "oseas_sentinel2_prithvi_input", "bands": BANDS + ["VALID_MASK", "JRC_OCCURRENCE"] + (["LAKE_MASK"] if lake_mask_asset is not None else []),
        "region": roi, "scale": 10, "crs": f"EPSG:{utm_hemisphere + utm_zone}", "format": "GEO_TIFF",
    }
    url = image.getDownloadURL(params)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "oseas-prithvi-pipeline/1.0"})
    with urlopen(request, timeout=180) as response, raw_path.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    if zipfile.is_zipfile(raw_path):
        with zipfile.ZipFile(raw_path) as archive:
            tiffs = [name for name in archive.namelist() if name.lower().endswith((".tif", ".tiff"))]
            if len(tiffs) != 1:
                raise RuntimeError(f"Expected one multiband GeoTIFF from Earth Engine; found {len(tiffs)}")
            extracted = raw_path.with_suffix(".unpacked.tif")
            with archive.open(tiffs[0]) as src, extracted.open("wb") as dst:
                while chunk := src.read(1024 * 1024):
                    dst.write(chunk)
        raw_path.unlink(missing_ok=True)
        extracted.replace(raw_path)
    scene_properties = ee.Image(collection.sort("CLOUDY_PIXEL_PERCENTAGE").first())
    properties = scene_properties.toDictionary([
        "system:index", "system:time_start", "CLOUDY_PIXEL_PERCENTAGE", "MGRS_TILE", "PROCESSING_BASELINE"
    ]).getInfo()
    acquisition = ee.Date(properties["system:time_start"]).format("YYYY-MM-dd'T'HH:mm:ss'Z'").getInfo()
    return {
        "candidate_scene_count": count,
        "scene_count": 1,
        "scene_ids": [properties["system:index"]],
        "scene_id": properties["system:index"],
        "acquisition_datetime_utc": acquisition,
        "cloudy_pixel_percentage_scene": properties.get("CLOUDY_PIXEL_PERCENTAGE"),
        "mgrs_tile": properties.get("MGRS_TILE"),
        "processing_baseline": properties.get("PROCESSING_BASELINE"),
        "valid_pixel_coverage": coverage,
        "collection_id": "COPERNICUS/S2_HARMONIZED",
        "input_bands": BANDS,
        "input_auxiliary_bands": ["VALID_MASK", "JRC_OCCURRENCE"] + (["LAKE_MASK"] if lake_mask_asset is not None else []),
        "input_band_order": ["Blue", "Green", "Red", "NIR_narrow", "SWIR_1", "SWIR_2"],
        "input_units": "Sentinel-2 L1C top-of-atmosphere reflectance DN scaled by 10000; official inference rescales to 0-1 then applies checkpoint normalization",
        "input_resampling": "Earth Engine export at 10 m; native 20 m bands use nearest-neighbor reprojection",
        "cloud_mask": "QA60 opaque-cloud and cirrus bits; cloud shadow is not masked",
        "nodata_policy": "Reflectance zero-filled for inference; VALID_MASK band reapplied as nodata after inference",
        "lake_mask_asset": lake_asset_id,
        "mapped_lake_features_in_aoi": lake_feature_count,
        "lake_mask_applied": lake_mask_asset is not None,
        "lake_mask_role": "Mapped lakes are excluded from retained water candidates; JRC remains a separate permanent-water check.",
        "export_crs": f"EPSG:{utm_hemisphere + utm_zone}",
        "export_pixel_size_m": 10,
    }


def _run_official_inference(input_path: Path, output_dir: Path, model_dir: Path, input_indices: list[int] | None = None) -> Path:
    inference = model_dir / "inference.py"
    checkpoint = model_dir / CHECKPOINT
    config = model_dir / "config.yaml"
    if not all(path.is_file() and path.stat().st_size for path in (inference, checkpoint, config)):
        raise RuntimeError("Prithvi task bundle is missing; run `python scripts/download_prithvi_weights.py` first")
    output_dir.mkdir(parents=True, exist_ok=True)
    import yaml

    # The fine-tuned task checkpoint contains the backbone weights. Disable the
    # training-time pretrained initialization so inference does not fetch a
    # second 1.3 GB foundation checkpoint from Hugging Face on every new host.
    config_data = yaml.safe_load(config.read_text(encoding="utf-8"))
    config_data["model"]["init_args"]["model_args"]["backbone_pretrained"] = False
    with tempfile.TemporaryDirectory(prefix="oseas-prithvi-config-") as config_dir:
        runtime_config = Path(config_dir) / "config.yaml"
        runtime_config.write_text(yaml.safe_dump(config_data, sort_keys=False), encoding="utf-8")
        indices = input_indices or list(range(6))
        command = [sys.executable, str(inference), "--data_file", str(input_path), "--config", str(runtime_config), "--checkpoint", str(checkpoint), "--output_dir", str(output_dir), "--input_indices", *[str(index) for index in indices]]
        LOG.info("Starting official Prithvi inference using the pinned task checkpoint")
        inference_started = time.monotonic()
        process = subprocess.Popen(command, cwd=str(model_dir))
        while process.poll() is None:
            time.sleep(30)
            if process.poll() is None:
                LOG.info("Prithvi inference is still running; elapsed %.0f seconds", time.monotonic() - inference_started)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)
    prediction = output_dir / f"pred_{input_path.stem}.tiff"
    if not prediction.is_file():
        raise RuntimeError("Prithvi inference exited without creating its prediction raster")
    return prediction


def _validate_and_mask_prediction(raw_prediction: Path, input_path: Path, output_path: Path) -> dict[str, Any]:
    """Validate model class labels against the source grid and preserve cloud/nodata."""
    import numpy as np
    import rasterio

    with rasterio.open(input_path) as source, rasterio.open(raw_prediction) as prediction:
        if source.count not in (8, 9):
            raise RuntimeError(f"Expected six model bands, VALID_MASK, JRC_OCCURRENCE and optional LAKE_MASK; source has {source.count} bands")
        if (prediction.width, prediction.height) != (source.width, source.height):
            raise RuntimeError("Prithvi prediction dimensions do not match the Sentinel-2 input grid")
        if prediction.crs != source.crs or prediction.transform != source.transform:
            raise RuntimeError("Prithvi prediction CRS/transform does not match the Sentinel-2 input grid")
        if prediction.count != 1 or prediction.dtypes[0] != "uint8":
            raise RuntimeError(f"Expected one uint8 class-label band, got {prediction.count} band(s), dtype={prediction.dtypes}")
        raw_labels = prediction.read(1)
        # The pinned upstream inference writer multiplies argmax labels by 255
        # before casting to uint8, so class 1 is serialized as 255. The source
        # validity mask distinguishes real model pixels from cloud/no-data.
        labels = np.where(raw_labels == 255, 1, raw_labels).astype(np.uint8)
        valid = source.read(7) == 1
        unexpected = sorted(int(value) for value in np.unique(labels[valid]) if int(value) not in (0, 1))
        if unexpected:
            raise RuntimeError(f"Prithvi output contains unexpected class IDs on valid pixels: {unexpected}")
        valid_values, valid_counts = np.unique(labels[valid], return_counts=True)
        distribution = {str(int(value)): int(count) for value, count in zip(valid_values, valid_counts, strict=True)}
        output = labels.copy()
        output[~valid] = 255
        profile = prediction.profile.copy()
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)
        profile.update(dtype="uint8", count=1, nodata=255, compress="deflate", tiled=False)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        with rasterio.open(temporary, "w", **profile) as target:
            target.write(output, 1)
        temporary.replace(output_path)
        valid_count = int(valid.sum())
        return {
            "classification": "argmax class labels (not probabilities/logits); official writer encoding 0->0 and 1->255 normalized to 0/1",
            "class_ids": {"0": "non-water/background", "1": "water/flood candidate", "255": "cloud/nodata excluded"},
            "class_distribution_valid_pixels": distribution,
            "valid_pixel_count": valid_count,
            "nodata_pixel_count": int(valid.size - valid_count),
            "dimensions": {"width": source.width, "height": source.height},
            "crs": source.crs.to_string() if source.crs else None,
            "transform": list(source.transform)[:6],
            "pixel_size_m": [abs(source.transform.a), abs(source.transform.e)],
            "prediction_nodata_value": 255,
        }


def _configure_proj_data() -> None:
    """Use the matching PROJ database for Rasterio/GDAL and pyproj."""
    from pyproj import datadir

    pyproj_dir = Path(datadir.get_data_dir())
    rasterio_spec = importlib.util.find_spec("rasterio")
    rasterio_dir = Path(rasterio_spec.origin).parent if rasterio_spec and rasterio_spec.origin else None
    rasterio_proj_dir = rasterio_dir / "proj_data" if rasterio_dir else None
    proj_dir = rasterio_proj_dir if rasterio_proj_dir and (rasterio_proj_dir / "proj.db").is_file() else pyproj_dir
    if not (proj_dir / "proj.db").is_file():
        raise RuntimeError(f"PROJ database is missing from Rasterio and pyproj installations: {proj_dir}")
    datadir.set_data_dir(str(pyproj_dir))
    os.environ["PROJ_LIB"] = str(proj_dir)


def _polygonize(mask_path: Path, minimum_area_m2: float, water_mask_path: Path) -> list[dict[str, Any]]:
    _configure_proj_data()
    import numpy as np
    import rasterio
    from rasterio.features import shapes
    from shapely.geometry import shape, mapping
    from shapely.ops import transform
    from pyproj import Geod, Transformer

    features = []
    with rasterio.open(mask_path) as src, rasterio.open(water_mask_path) as source:
        array = src.read(1)
        valid_pixels = source.read(7) == 1
        persistent_water = source.read(8)
        mapped_lake_mask = source.read(9) == 1 if source.count >= 9 else np.zeros(array.shape, dtype=bool)
        if persistent_water.shape != array.shape:
            raise RuntimeError("Sentinel-2 prediction grid differs from the accompanying JRC water-mask grid")
        if not valid_pixels.shape == array.shape or source.transform != src.transform or source.crs != src.crs:
            raise RuntimeError("Prediction and Sentinel-2 validity/source grids are not aligned")
        transform_to_wgs84 = None if src.crs and src.crs.to_epsg() == 4326 else Transformer.from_crs(src.crs, "EPSG:4326", always_xy=True).transform
        # JRC occurrence -1 means no occurrence observation is available, not
        # zero flood likelihood. Keep Prithvi candidates with unknown JRC data;
        # only remove pixels positively identified as persistent water.
        valid = (array == 1) & valid_pixels & (persistent_water < 80) & ~mapped_lake_mask
        if src.nodata is not None:
            valid &= array != src.nodata
        for geometry_json, value in shapes(array, mask=valid, transform=src.transform, connectivity=8):
            if int(value) != 1:
                continue
            geometry = shape(geometry_json)
            if transform_to_wgs84:
                geometry = transform(transform_to_wgs84, geometry)
            area = abs(Geod(ellps="WGS84").geometry_area_perimeter(geometry)[0])
            if area < minimum_area_m2:
                continue
            features.append({"type": "Feature", "geometry": mapping(geometry), "properties": {"class_id": 1, "class_label": "water_or_flood_candidate", "area_m2": float(area), "permanent_water_filter": "JRC occurrence >=80% and configured mapped lake pixels excluded; missing JRC occurrence retained with permanence unknown"}})
            if len(features) > MAX_POLYGONS:
                raise RuntimeError(f"Prithvi produced more than {MAX_POLYGONS} retained polygons; reduce the AOI or raise minimum patch area")
    return features


def _fingerprint(parameters: dict[str, Any], quality: dict[str, Any]) -> str:
    canonical = json.dumps({"model": MODEL_ID, "revision": MODEL_REVISION, "parameters": parameters, "scene_ids": sorted(quality["scene_ids"])}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _validate_schema(cur: Any) -> dict[str, bool]:
    required = ["ingestion_runs", "datasets", "dataset_versions", "data_quality_checks", "model_runs", "hazard_events", "flood_extents", "asset_hazard_exposure", "energy_assets", "administrative_units", "spatial_coverage_assessments"]
    optional = ["asset_admin_assignments", "administrative_hazard_summaries"]
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name=ANY(%s)", (required + optional,))
    present = {row[0] for row in cur.fetchall()}
    missing = sorted(set(required) - present)
    if missing:
        raise RuntimeError("Apply the current database/schema.sql in Supabase SQL Editor; missing core OSEAS tables: " + ", ".join(missing))
    missing_admin = sorted(set(optional) - present)
    if missing_admin:
        LOG.warning("Administrative summary persistence is unavailable until schema.sql is applied; missing tables: %s", ", ".join(missing_admin))
    return {"asset_admin_assignments": "asset_admin_assignments" in present,
            "administrative_hazard_summaries": "administrative_hazard_summaries" in present}


def _persist(cur: Any, run_id: str, model_run_id: str, fingerprint: str, parameters: dict[str, Any], quality: dict[str, Any], features: list[dict[str, Any]], schema_capabilities: dict[str, bool]) -> dict[str, Any]:
    spec = BY_KEY["sentinel2_l1c"]
    cur.execute("INSERT INTO datasets(dataset_key,name,source_type,source_reference,category,licence,attribution,is_optional) VALUES(%s,%s,'earth_engine_image_collection',%s,'satellite',%s,%s,TRUE) ON CONFLICT(dataset_key) DO UPDATE SET source_reference=EXCLUDED.source_reference,updated_at=NOW()", (spec.key, spec.name, spec.collection_id, spec.attribution, spec.attribution))
    scene_day = quality["acquisition_datetime_utc"][:10]
    cur.execute("INSERT INTO dataset_versions(dataset_key,source_reference,retrieved_at,observation_start,observation_end,feature_count,metadata,processing_run_id) VALUES(%s,%s,NOW(),%s::date,%s::date,%s,%s::jsonb,%s)", (spec.key, f"{spec.collection_id}/{quality['scene_id']}", scene_day, scene_day, quality["scene_count"], json.dumps(quality), run_id))
    cur.execute("INSERT INTO data_quality_checks(run_id,dataset_key,check_name,status,details) VALUES(%s,%s,'sentinel2_scene_coverage',%s,%s::jsonb)", (run_id, spec.key, "passed" if quality["valid_pixel_coverage"] >= .7 else "warning", json.dumps(quality)))
    # Cloud-shadow QA is not applied, so keep the reporting status conservative even
    # when the measured clear-pixel fraction reaches 100%.
    coverage_status = "partially_assessed"
    cur.execute(
        """INSERT INTO spatial_coverage_assessments
             (dataset_key,processing_run_id,hazard_type,evidence_kind,observation_start,observation_end,coverage_status,
              area_coverage_fraction,valid_data_fraction,observation_footprint,quality_mask,validation_status,limitations,provenance)
           VALUES (%s,%s,'flood','modeled',%s::date,%s::date,%s,NULL,%s,
              ST_MakeEnvelope(%s,%s,%s,%s,4326),%s::jsonb,'not_validated',
              '["Cloud shadow is not masked.","Valid-pixel fraction is measured over the requested AOI and may include edge effects.","Flood segmentation is not scientifically validated for Kenya."]'::jsonb,
              %s::jsonb) ON CONFLICT DO NOTHING""",
        (spec.key, run_id, parameters["event_start"], parameters["event_end"], coverage_status,
         quality["valid_pixel_coverage"], *parameters["bbox"],
         json.dumps({"mask": quality["cloud_mask"], "nodataPolicy": quality["nodata_policy"], "validPixelCoverage": quality["valid_pixel_coverage"]}),
         json.dumps({"model_id": MODEL_ID, "model_revision": MODEL_REVISION, "scene_id": quality["scene_id"], "fingerprint": fingerprint})),
    )
    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union

    event_id = None
    exposure_count = 0
    if features:
        flood_geometry = unary_union([shape(feature["geometry"]) for feature in features])
        if not flood_geometry.is_valid:
            raise RuntimeError("Prithvi flood candidate union is invalid")
        geom_json = json.dumps(mapping(flood_geometry), sort_keys=True, separators=(",", ":"))
        event_id = str(uuid.uuid5(NAMESPACE, fingerprint + ":prithvi-flood-layer"))
        metadata = {"model_id": MODEL_ID, "model_revision": MODEL_REVISION, "event_fingerprint": fingerprint,
                    "class_id": 1, "class_label": "water_or_flood_candidate", "validated_for_kenya": False,
                    "validation_status": "inference_only", "quality": quality}
        source_reference = f"COPERNICUS/S2_HARMONIZED/{quality['scene_id']}"
        cur.execute("""INSERT INTO hazard_events(id,hazard_type,evidence_kind,dataset_key,event_start,event_end,source_reference,confidence,geom,metadata,processing_run_id)
          VALUES(%s,'flood','modeled',%s,%s::date,%s::date,%s,NULL,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s::jsonb,%s)
          ON CONFLICT(id) DO UPDATE SET event_start=EXCLUDED.event_start,event_end=EXCLUDED.event_end,source_reference=EXCLUDED.source_reference,
            geom=EXCLUDED.geom,metadata=EXCLUDED.metadata,processing_run_id=EXCLUDED.processing_run_id""",
          (event_id, spec.key, scene_day, scene_day, source_reference, geom_json, json.dumps(metadata), run_id))
        scene_day = quality["acquisition_datetime_utc"][:10]
        cur.execute("""INSERT INTO flood_extents(hazard_event_id,observation_start,observation_end,method,area_km2,quality)
          VALUES(%s,%s::date,%s::date,%s,%s,%s::jsonb)
          ON CONFLICT(hazard_event_id) DO UPDATE SET observation_start=EXCLUDED.observation_start,observation_end=EXCLUDED.observation_end,
            method=EXCLUDED.method,area_km2=EXCLUDED.area_km2,quality=EXCLUDED.quality""",
          (event_id, scene_day, scene_day, MODEL_ID, sum(feature["properties"]["area_m2"] for feature in features) / 1_000_000, json.dumps(quality)))
        cur.execute("""INSERT INTO asset_hazard_exposure(id,energy_asset_id,hazard_event_id,hazard_type,assessment_period_start,assessment_period_end,exposure_status,intersection_area_m2,intersection_length_m,evidence_kind,confidence,provenance,processing_run_id)
          SELECT md5(a.id::text||':'||%s||':prithvi-flood')::uuid,a.id,%s,'flood',%s::date,%s::date,'exposed',
            CASE WHEN ST_Dimension(a.geom)=2 THEN ST_Area(ST_Intersection(a.geom,h.geom)::geography) END,
            CASE WHEN ST_Dimension(a.geom)=1 THEN ST_Length(ST_CollectionExtract(ST_Intersection(a.geom,h.geom),2)::geography) END,
            'modeled',NULL,jsonb_build_object('model_id',%s::text,'model_revision',%s::text,'event_fingerprint',%s::text,'scene_id',%s::text,'validation_status','inference_only'),%s
          FROM energy_assets a CROSS JOIN hazard_events h
          WHERE h.id=%s AND ST_Intersects(a.geom,h.geom)
          ON CONFLICT(id) DO UPDATE SET hazard_event_id=EXCLUDED.hazard_event_id,exposure_status=EXCLUDED.exposure_status,
            intersection_area_m2=EXCLUDED.intersection_area_m2,intersection_length_m=EXCLUDED.intersection_length_m,
            provenance=EXCLUDED.provenance,processing_run_id=EXCLUDED.processing_run_id""",
          (fingerprint, event_id, parameters["event_start"], parameters["event_end"], MODEL_ID, MODEL_REVISION,
           fingerprint, quality["scene_id"], run_id, event_id))
        exposure_count = cur.rowcount

    summary_count = 0
    if schema_capabilities["administrative_hazard_summaries"]:
      cur.execute("""WITH aoi AS (SELECT ST_MakeEnvelope(%s,%s,%s,%s,4326) AS geom), membership AS (
      SELECT u.id AS administrative_unit_id,a.id AS energy_asset_id
      FROM administrative_units u CROSS JOIN aoi JOIN energy_assets a ON ST_Intersects(a.geom,u.geom) AND ST_Intersects(a.geom,aoi.geom)
      WHERE u.unit_level IN ('ward','county') AND ST_Intersects(u.geom,aoi.geom)), counts AS (
      SELECT u.id,u.geom unit_geom,count(DISTINCT m.energy_asset_id)::int asset_count,count(DISTINCT e.energy_asset_id)::int exposed_count
      FROM administrative_units u LEFT JOIN membership m ON m.administrative_unit_id=u.id
      LEFT JOIN asset_hazard_exposure e ON e.energy_asset_id=m.energy_asset_id AND e.hazard_type='flood' AND e.processing_run_id=%s
      WHERE u.unit_level IN ('ward','county') AND ST_Intersects(u.geom,ST_MakeEnvelope(%s,%s,%s,%s,4326)) GROUP BY u.id,u.geom)
      INSERT INTO administrative_hazard_summaries(id,administrative_unit_id,hazard_type,event_fingerprint,period_start,period_end,assessment_status,assigned_energy_asset_count,candidate_exposed_asset_count,candidate_exposure_fraction,provenance,processing_run_id)
      SELECT md5(id::text||':'||%s)::uuid,id,'flood',%s,%s::date,%s::date,
      CASE WHEN %s>0 AND ST_Covers(ST_MakeEnvelope(%s,%s,%s,%s,4326),unit_geom) THEN 'screened' ELSE 'insufficient_data' END,asset_count,exposed_count,NULL,
       jsonb_build_object('model_id',%s::text,'evidence_kind','modeled','fraction_omitted',true),%s FROM counts
      ON CONFLICT(administrative_unit_id,hazard_type,event_fingerprint) DO UPDATE SET candidate_exposed_asset_count=EXCLUDED.candidate_exposed_asset_count,assigned_energy_asset_count=EXCLUDED.assigned_energy_asset_count,provenance=EXCLUDED.provenance,processing_run_id=EXCLUDED.processing_run_id""",
      (*parameters["bbox"],run_id,*parameters["bbox"],fingerprint,fingerprint,parameters["event_start"],parameters["event_end"],len(features),*parameters["bbox"],MODEL_ID,run_id))
      summary_count = cur.rowcount
    cur.execute("SELECT count(*) FROM hazard_events WHERE processing_run_id=%s AND NOT ST_IsValid(geom)", (run_id,))
    invalid_count = cur.fetchone()[0]
    if invalid_count:
        raise RuntimeError(f"PostGIS rejected {invalid_count} invalid Prithvi polygon geometries")
    cur.execute("INSERT INTO data_quality_checks(run_id,dataset_key,check_name,status,details) VALUES(%s,%s,'prithvi_polygon_output',%s,%s::jsonb)", (run_id, spec.key, "passed" if features else "warning", json.dumps({"candidate_polygon_count": len(features), "exposure_rows_upserted": exposure_count, "administrative_summaries_upserted": summary_count, "invalid_geometry_count": invalid_count})))
    cur.execute("UPDATE datasets SET last_ingested_at=NOW(),updated_at=NOW() WHERE dataset_key=%s", (spec.key,))
    admin_summary_ready = schema_capabilities["administrative_hazard_summaries"] and summary_count > 0
    run_status = "completed" if features and admin_summary_ready else "partial"
    partial_reasons = ([] if features else ["no_candidate_polygons_above_minimum_area"])
    if not admin_summary_ready:
        partial_reasons.append("administrative_summary_schema_unavailable" if not schema_capabilities["administrative_hazard_summaries"] else "no_administrative_units_summarized")
    cur.execute("UPDATE model_runs SET status=%s,finished_at=NOW(),metrics=%s::jsonb WHERE id=%s", (run_status, json.dumps({"scene_count": quality["scene_count"], "coverage": quality["valid_pixel_coverage"], "candidate_polygon_count": len(features), "asset_exposures_upserted": exposure_count, "kenya_validation": "not_evaluated", "partial_reasons": partial_reasons}), model_run_id))
    cur.execute("UPDATE ingestion_runs SET status=%s,finished_at=NOW(),metadata=metadata||%s::jsonb WHERE id=%s", (run_status, json.dumps({"model_run_id": model_run_id, "event_fingerprint": fingerprint, "quality": quality, "candidate_polygon_count": len(features), "asset_admin_assignments_available": schema_capabilities["asset_admin_assignments"], "administrative_summaries_persisted": summary_count}), run_id))
    return {"candidate_polygons": len(features), "asset_exposures_upserted": exposure_count, "administrative_summaries_upserted": summary_count, "status": run_status, "event_id": event_id}


def _write_asset_exposures(cur: Any, bbox: list[float], run_id: str, output_path: Path) -> dict[str, Any]:
    cur.execute("""SELECT a.id,a.asset_type,a.name,a.source_dataset_key,a.source_feature_id,
           ST_AsGeoJSON(a.geom)::json AS geometry,e.exposure_status,e.intersection_area_m2,e.intersection_length_m,
           e.hazard_event_id,e.provenance
      FROM energy_assets a
      LEFT JOIN asset_hazard_exposure e ON e.energy_asset_id=a.id AND e.processing_run_id=%s AND e.hazard_type='flood'
      WHERE ST_Intersects(a.geom,ST_MakeEnvelope(%s,%s,%s,%s,4326)) ORDER BY a.asset_type,a.id""", (run_id, *bbox))
    rows = cur.fetchall()
    type_counts: dict[str, int] = {}
    exposed_counts: dict[str, int] = {}
    features = []
    for row in rows:
        asset_id, asset_type, name, dataset_key, source_feature_id, geometry, status, area, length, event_id, provenance = row
        asset_type = asset_type or "unknown"
        type_counts[asset_type] = type_counts.get(asset_type, 0) + 1
        exposure_status = status or "unknown"
        if exposure_status == "exposed":
            exposed_counts[asset_type] = exposed_counts.get(asset_type, 0) + 1
        features.append({"type": "Feature", "id": str(asset_id), "geometry": geometry,
                         "properties": {"assetId": str(asset_id), "assetType": asset_type, "name": name,
                                        "sourceDatasetKey": dataset_key, "sourceFeatureId": source_feature_id,
                                        "exposureStatus": exposure_status, "intersectionAreaM2": float(area) if area is not None else None,
                                        "intersectionLengthM": float(length) if length is not None else None, "hazardEventId": str(event_id) if event_id else None,
                                        "evidenceKind": "modeled", "validationStatus": "inference_only",
                                        "provenance": provenance or {"reason": "No candidate polygon intersected this asset; imagery/model uncertainty is not a confirmed non-exposure"}}})
    output_path.write_text(json.dumps({"type": "FeatureCollection", "features": features,
                                      "spatialReference": "EPSG:4326", "status": "inference_only"}, default=str, indent=2), encoding="utf-8")
    return {"assets_in_pilot_aoi": len(features), "asset_counts_by_type": type_counts,
            "exposed_asset_counts_by_type": exposed_counts, "asset_exposure_geojson": str(output_path)}


def _write_admin_summaries(cur: Any, bbox: list[float], run_id: str, coverage: float, output_path: Path) -> dict[str, Any]:
    cur.execute("""WITH aoi AS (SELECT ST_MakeEnvelope(%s,%s,%s,%s,4326) AS geom), rows AS (
      SELECT u.id,u.unit_level,u.name,u.stable_code,u.source_properties,u.geom,
        count(DISTINCT a.id)::int AS assets_in_aoi,
        count(DISTINCT a.id) FILTER (WHERE a.asset_type='distribution_transformer')::int AS transformers_in_aoi,
        count(DISTINCT a.id) FILTER (WHERE a.asset_type='transmission_line')::int AS transmission_lines_in_aoi,
        count(DISTINCT a.id) FILTER (WHERE a.asset_type='primary_substation')::int AS substations_in_aoi,
        count(DISTINCT a.id) FILTER (WHERE a.asset_type='power_station')::int AS power_stations_in_aoi,
        count(DISTINCT a.id) FILTER (WHERE a.asset_type='mini_grid_existing')::int AS mini_grids_in_aoi,
        count(DISTINCT a.id) FILTER (WHERE e.exposure_status='exposed')::int AS candidate_exposed_assets,
        ST_Covers(aoi.geom,u.geom) AS fully_covered,
        ST_Area(ST_Intersection(u.geom,aoi.geom)::geography)/NULLIF(ST_Area(u.geom::geography),0) AS area_coverage,
        ST_AsGeoJSON(u.geom)::json AS geometry
      FROM administrative_units u CROSS JOIN aoi
      LEFT JOIN energy_assets a ON ST_Intersects(u.geom,a.geom) AND ST_Intersects(a.geom,aoi.geom)
      LEFT JOIN asset_hazard_exposure e ON e.energy_asset_id=a.id AND e.processing_run_id=%s AND e.hazard_type='flood'
      WHERE u.unit_level IN ('ward','county') AND ST_Intersects(u.geom,aoi.geom)
      GROUP BY u.id,u.unit_level,u.name,u.stable_code,u.source_properties,u.geom,aoi.geom)
      SELECT * FROM rows ORDER BY unit_level,name""", (*bbox, run_id))
    result_features = []
    for row in cur.fetchall():
        (unit_id, level, name, code, properties, geom, asset_count, transformer_count, line_count,
         substation_count, power_count, mini_count, exposed_count, fully_covered, area_coverage, geometry) = row
        properties = properties or {}
        display_name = name or properties.get("GAUL1_NAME") or properties.get("ward") or code
        summary_status = "screened" if fully_covered and coverage >= .7 else "insufficient_data"
        result_features.append({"type": "Feature", "id": str(unit_id), "geometry": geometry,
          "properties": {"unitLevel": level, "name": display_name, "stableCode": code,
            "assessmentStatus": summary_status, "aoiAreaCoverageFraction": float(area_coverage or 0),
            "assetsCountedInPilotAoi": asset_count, "candidateExposedAssets": exposed_count,
            "assetCountsByType": {"distribution_transformer": transformer_count,"transmission_line": line_count,
                                  "primary_substation": substation_count,"power_station": power_count,"mini_grid_existing": mini_count},
            "processingRunId": run_id, "evidenceKind": "modeled", "validationStatus": "inference_only",
            "limitation": "Counts cover only the pilot AOI portion; this is not a whole county/ward assessment."}})
    output_path.write_text(json.dumps({"type": "FeatureCollection", "features": result_features,
                                      "spatialReference": "EPSG:4326", "status": "inference_only"}, indent=2), encoding="utf-8")
    return {"administrative_units_touched": len(result_features),
            "fully_covered_units": sum(1 for feature in result_features if feature["properties"]["assessmentStatus"] == "screened"),
            "admin_summary_geojson": str(output_path)}


def _write_visual_preview(input_path: Path, prediction_path: Path, output_path: Path) -> None:
    import numpy as np
    import rasterio
    from rasterio.plot import plotting_extent
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with rasterio.open(input_path) as source, rasterio.open(prediction_path) as prediction:
        reflectance = source.read([3, 2, 1]).astype(np.float32) / 10000.0
        valid = source.read(7) == 1
        labels = prediction.read(1)
        rgb = np.moveaxis(reflectance, 0, -1)
        valid_values = rgb[valid]
        lo, hi = np.percentile(valid_values, [2, 98]) if valid_values.size else (0.0, 1.0)
        rgb = np.clip((rgb - lo) / max(hi - lo, 1e-6), 0, 1)
        rgb[~valid] = 0
        flood_overlay = np.zeros((*labels.shape, 4), dtype=np.float32)
        flood_overlay[labels == 1] = (1.0, 0.08, 0.0, 0.55)
        extent = plotting_extent(source)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(9, 9))
    axis.imshow(rgb, extent=extent, origin="upper")
    axis.imshow(flood_overlay, extent=extent, origin="upper")
    axis.set_title("Prithvi class 1 overlay (red) â€” candidate water, not validated flood extent")
    axis.set_xlabel("Easting (m)")
    axis.set_ylabel("Northing (m)")
    figure.tight_layout()
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def run(args: argparse.Namespace) -> dict[str, Any]:
    if MODEL_ID != SUPPORTED_MODEL_ID:
        raise RuntimeError(f"This pipeline's six-band preprocessing supports only {SUPPORTED_MODEL_ID}; got {MODEL_ID}")
    _configure_proj_data()
    bbox = validate_args(args)
    from oseas.config import database_url
    db_url = database_url()
    project = os.getenv("GEE_PROJECT_ID", "").strip()
    if not db_url or not project:
        raise RuntimeError("DB_URL (or supported alias) and GEE_PROJECT_ID are required")
    model_dir = Path(os.getenv("PRITHVI_MODEL_DIR", "models/prithvi/flood_sen1floods11"))
    if not model_dir.is_absolute():
        model_dir = ROOT / model_dir
    output_root = Path(args.output_dir)
    if not output_root.is_absolute():
        output_root = ROOT / output_root

    import psycopg
    from gee.auth import initialize_earth_engine
    if not initialize_earth_engine(project):
        raise RuntimeError("Earth Engine authentication failed")
    import ee

    run_id, model_run_id = str(uuid.uuid4()), str(uuid.uuid4())
    parameters = {"bbox": bbox, "event_start": args.event_start, "event_end": args.event_end, "scene_id": args.scene_id,
                  "max_cloud_percent": args.max_cloud_percent, "min_patch_area_m2": args.min_patch_area_m2,
                  "model_id": MODEL_ID, "model_revision": MODEL_REVISION, "checkpoint": CHECKPOINT,
                  "preprocessing_version": "oseas-s2-l1c-prithvi-v3",
                  "lake_mask_asset_id": os.getenv("GEE_ASSET_KENYA_LAKES", "").strip() or None}
    with psycopg.connect(db_url, prepare_threshold=None, connect_timeout=15, options="-c statement_timeout=600000", application_name="oseas-prithvi-flood") as connection:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s),hashtext('writer'))", (INGEST_LOCK,))
            if not cur.fetchone()[0]:
                raise RuntimeError("Infrastructure ingestion is active; wait for it to finish")
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s),hashtext('writer'))", (MODEL_LOCK,))
            if not cur.fetchone()[0]:
                raise RuntimeError("Another Prithvi flood run is active")
            schema_capabilities = _validate_schema(cur)
            cur.execute("SELECT status,metadata FROM ingestion_runs WHERE pipeline_name='oseas_earth_engine_ingest' ORDER BY started_at DESC LIMIT 1")
            latest = cur.fetchone()
            failed_assets = (latest[1] or {}).get("failed_assets", 0) if latest else 0
            if not latest or latest[0] not in ("completed", "partial") or failed_assets:
                raise RuntimeError(f"Latest infrastructure ingestion is not usable (status={latest[0] if latest else 'missing'}, failed_assets={failed_assets})")
            cur.execute("INSERT INTO ingestion_runs(id,pipeline_name,status,started_at,metadata) VALUES(%s,'oseas_prithvi_flood_screen','running',NOW(),%s::jsonb)", (run_id, json.dumps({"parameters": parameters})))
            cur.execute("INSERT INTO model_runs(id,model_name,model_version,checkpoint,task,parameters,metrics,status,processing_run_id) VALUES(%s,%s,%s,%s,'flood_segmentation',%s::jsonb,'{}'::jsonb,'running',%s)", (model_run_id, MODEL_ID, MODEL_REVISION, CHECKPOINT, json.dumps(parameters), run_id))
        connection.commit()
        run_dir = output_root / run_id
        raw_path, prediction_dir = run_dir / "sentinel2_l1c.tif", run_dir / "model"
        try:
            run_started_at = datetime.now(timezone.utc)
            timer_start = time.monotonic()
            run_dir.mkdir(parents=True, exist_ok=True)
            LOG.info("Selecting one Sentinel-2 L1C scene for bbox=%s; AOI limit=%.1f km2", bbox, MAX_AOI_KM2)
            quality = _download_image(ee, bbox, args.event_start, args.event_end, args.max_cloud_percent, raw_path, args.scene_id, parameters["lake_mask_asset_id"])
            LOG.info("Selected %s (%s), scene cloud=%.1f%%, AOI clear-pixel coverage=%.1f%%",
                     quality["scene_id"], quality["acquisition_datetime_utc"], quality["cloudy_pixel_percentage_scene"], quality["valid_pixel_coverage"] * 100)
            raw_prediction = _run_official_inference(raw_path, prediction_dir, model_dir)
            prediction = run_dir / "prithvi_class_labels.tif"
            prediction_quality = _validate_and_mask_prediction(raw_prediction, raw_path, prediction)
            quality["prediction"] = prediction_quality
            LOG.info("Validated output grid %sx%s; class distribution=%s; excluded no-data pixels=%s",
                     prediction_quality["dimensions"]["width"], prediction_quality["dimensions"]["height"],
                     prediction_quality["class_distribution_valid_pixels"], prediction_quality["nodata_pixel_count"])
            features = _polygonize(prediction, args.min_patch_area_m2, raw_path)
            for feature in features:
                feature["properties"].update({"scene_id": quality["scene_id"],
                    "acquisition_datetime_utc": quality["acquisition_datetime_utc"], "model_id": MODEL_ID,
                    "model_revision": MODEL_REVISION, "validation_status": "inference_only"})
            fingerprint = _fingerprint(parameters, quality)
            output = run_dir / "flood_candidates.geojson"
            output.write_text(json.dumps({"type": "FeatureCollection", "features": features,
                "metadata": {"scene_id": quality["scene_id"], "acquisition_datetime_utc": quality["acquisition_datetime_utc"],
                    "model_id": MODEL_ID, "model_revision": MODEL_REVISION, "checkpoint": CHECKPOINT,
                    "evidence_kind": "modeled", "validation_status": "inference_only", "quality": quality}}, indent=2), encoding="utf-8")
            with connection.cursor() as cur:
                result = _persist(cur, run_id, model_run_id, fingerprint, parameters, quality, features, schema_capabilities)
                asset_output = _write_asset_exposures(cur, bbox, run_id, run_dir / "asset_exposures.geojson")
                admin_output = _write_admin_summaries(cur, bbox, run_id, quality["valid_pixel_coverage"], run_dir / "administrative_summary.geojson")
            preview = run_dir / "preview.png"
            _write_visual_preview(raw_path, prediction, preview)
            run_finished_at = datetime.now(timezone.utc)
            duration_seconds = time.monotonic() - timer_start
            run_metadata = {"processing_run_id": run_id, "model_run_id": model_run_id,
                "started_at_utc": run_started_at.isoformat(), "finished_at_utc": run_finished_at.isoformat(),
                "duration_seconds": duration_seconds, "parameters": parameters, "quality": quality,
                "candidate_polygon_count": len(features), "asset_overlay": asset_output,
                "administrative_overlay": admin_output,
                "validation_status": {"inference_executed": True, "output_geospatial_validated": True,
                                      "scientifically_validated": False},
                "limitations": ["No local reference flood polygon was used for accuracy metrics.",
                                "Class 1 is model-predicted water/flood candidate, not a confirmed flood event.",
                                "QA60 masks cloud/cirrus but does not remove cloud shadows.",
                                "County/ward summaries cover only the pilot AOI and are persisted only when the additive admin schema exists."]}
            metadata_path = run_dir / "run_metadata.json"
            metadata_path.write_text(json.dumps(run_metadata, indent=2, default=str), encoding="utf-8")
            connection.commit()
            result.update({"run_id": run_id, "model_run_id": model_run_id, "output_geojson": str(output),
                "prediction_raster": str(prediction), "raw_prediction_raster": str(raw_prediction),
                "input_raster": str(raw_path), "preview_png": str(preview), "run_metadata": str(metadata_path),
                "quality": quality, "asset_overlay": asset_output, "administrative_overlay": admin_output,
                "runtime_seconds": duration_seconds,
                "validation_status": {"inference_executed": "PASS", "output_geospatial_validated": "PASS", "scientifically_validated": "NOT_EVALUATED"}})
            return result
        except Exception as error:
            connection.rollback()
            with connection.cursor() as cur:
                cur.execute("UPDATE model_runs SET status='failed',finished_at=NOW(),metrics=%s::jsonb WHERE id=%s", (json.dumps({"error_type": type(error).__name__, "error": str(error)[:1000]}), model_run_id))
                cur.execute("UPDATE ingestion_runs SET status='failed',finished_at=NOW(),error_message=%s,metadata=metadata||%s::jsonb WHERE id=%s", (str(error)[:1000], json.dumps({"error_type": type(error).__name__}), run_id))
            connection.commit()
            raise
        finally:
            with connection.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(hashtext(%s),hashtext('writer'))", (MODEL_LOCK,))
                cur.execute("SELECT pg_advisory_unlock(hashtext(%s),hashtext('writer'))", (INGEST_LOCK,))


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    print(json.dumps(run(args), indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        LOG.exception("Prithvi flood pipeline failed: %s", error)
        raise SystemExit(1)
