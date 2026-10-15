#!/usr/bin/env python3
"""Run resumable, nationwide Prithvi flood screening and persist admin pixel stats."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import logging
import os
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
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from scripts.run_prithvi_flood import (  # noqa: E402
    BANDS,
    CHECKPOINT,
    INGEST_LOCK,
    MODEL_ID,
    MODEL_LOCK,
    MODEL_REVISION,
    SUPPORTED_MODEL_ID,
)

LOG = logging.getLogger("oseas.prithvi.national")
NAMESPACE = uuid.UUID("f31e7f78-7742-4223-8644-b45517271c2a")
GRID_CRS = 6933
MODEL_PATCH_SIZE_PIXELS = 512
DEFAULT_OVERLAP_PIXELS = 64
PIXEL_SIZE_METRES = 10
MIN_VALID_COVERAGE = 0.5
PIPELINE_NAME = "oseas_prithvi_national_screen"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-start", default=os.getenv("OSEAS_PRITHVI_EVENT_START", "").strip())
    parser.add_argument("--event-end", default=os.getenv("OSEAS_PRITHVI_EVENT_END", "").strip())
    parser.add_argument("--max-cloud-percent", type=float, default=float(os.getenv("OSEAS_PRITHVI_MAX_CLOUD_PERCENT", "30")))
    parser.add_argument("--overlap-pixels", type=int, default=DEFAULT_OVERLAP_PIXELS)
    parser.add_argument("--max-tiles", type=int, help="Process at most this many pending tiles; remaining tiles stay resumable")
    parser.add_argument("--report", default="outputs/prithvi_national_latest.json")
    args = parser.parse_args()
    if not args.event_start or not args.event_end:
        parser.error("--event-start and --event-end (or matching OSEAS_PRITHVI_EVENT_START/END values) are required")
    return args


def validate_args(args: argparse.Namespace) -> None:
    start = date.fromisoformat(args.event_start)
    end = date.fromisoformat(args.event_end)
    if start >= end or (end - start).days > 45:
        raise ValueError("event interval must be chronological and no longer than 45 days")
    if not 0 <= args.max_cloud_percent <= 100:
        raise ValueError("--max-cloud-percent must be between 0 and 100")
    if args.overlap_pixels < 0 or args.overlap_pixels >= MODEL_PATCH_SIZE_PIXELS // 2 or args.overlap_pixels % 2:
        raise ValueError("--overlap-pixels must be an even number in [0, 255]")
    if args.max_tiles is not None and args.max_tiles <= 0:
        raise ValueError("--max-tiles must be greater than zero")


def tile_dimensions(overlap_pixels: int = DEFAULT_OVERLAP_PIXELS) -> dict[str, int]:
    if overlap_pixels < 0 or overlap_pixels >= MODEL_PATCH_SIZE_PIXELS // 2 or overlap_pixels % 2:
        raise ValueError("overlap must be an even number less than half the model patch size")
    stride_pixels = MODEL_PATCH_SIZE_PIXELS - overlap_pixels
    return {
        "chip_pixels": MODEL_PATCH_SIZE_PIXELS,
        "overlap_pixels": overlap_pixels,
        "core_pixels": stride_pixels,
        "stride_pixels": stride_pixels,
        "chip_size_m": MODEL_PATCH_SIZE_PIXELS * PIXEL_SIZE_METRES,
        "stride_m": stride_pixels * PIXEL_SIZE_METRES,
    }


def _event_fingerprint(parameters: dict[str, Any], boundary_signature: str) -> str:
    canonical = json.dumps(
        {
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "parameters": parameters,
            "boundary_signature": boundary_signature,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _candidate_mask(labels: Any, valid_mask: Any, jrc_occurrence: Any, lake_mask: Any) -> Any:
    arrays = (labels, valid_mask, jrc_occurrence, lake_mask)
    if len({array.shape for array in arrays}) != 1:
        raise ValueError("prediction and source masks must have identical dimensions")
    return (labels == 1) & valid_mask.astype(bool) & (jrc_occurrence < 80) & ~lake_mask.astype(bool)


def _zonal_pixel_stats(
    labels: Any,
    valid_mask: Any,
    jrc_occurrence: Any,
    lake_mask: Any,
    admin_units: list[dict[str, Any]],
    tile_bounds: tuple[float, float, float, float],
    overlap_pixels: int = DEFAULT_OVERLAP_PIXELS,
) -> list[dict[str, Any]]:
    """Count valid and candidate pixels once, using only the non-overlapping tile core."""
    import numpy as np
    from rasterio.features import rasterize
    from rasterio.transform import from_origin

    if labels.shape != (MODEL_PATCH_SIZE_PIXELS, MODEL_PATCH_SIZE_PIXELS):
        raise ValueError(f"expected a {MODEL_PATCH_SIZE_PIXELS}x{MODEL_PATCH_SIZE_PIXELS} prediction")
    if not (labels.shape == valid_mask.shape == jrc_occurrence.shape == lake_mask.shape):
        raise ValueError("prediction and source masks must have identical dimensions")

    margin = overlap_pixels // 2
    core_slice = (slice(margin, MODEL_PATCH_SIZE_PIXELS - margin),) * 2
    core_labels = labels[core_slice]
    core_valid = valid_mask[core_slice].astype(bool)
    core_jrc = jrc_occurrence[core_slice]
    core_lakes = lake_mask[core_slice].astype(bool)
    candidate = _candidate_mask(core_labels, core_valid, core_jrc, core_lakes)

    min_x, _, _, max_y = tile_bounds
    core_transform = from_origin(
        min_x + margin * PIXEL_SIZE_METRES,
        max_y - margin * PIXEL_SIZE_METRES,
        PIXEL_SIZE_METRES,
        PIXEL_SIZE_METRES,
    )
    shape = core_labels.shape
    results = []
    for unit in admin_units:
        mask = rasterize(
            [(unit["geometry"], 1)],
            out_shape=shape,
            transform=core_transform,
            fill=0,
            dtype="uint8",
        ).astype(bool)
        total_pixels = int(mask.sum())
        if not total_pixels:
            continue
        valid_pixels = int(np.count_nonzero(mask & core_valid))
        candidate_pixels = int(np.count_nonzero(mask & candidate))
        results.append(
            {
                "administrative_unit_id": unit["id"],
                "unit_level": unit["unit_level"],
                "total_pixels": total_pixels,
                "valid_pixels": valid_pixels,
                "candidate_pixels": candidate_pixels,
            }
        )
    return results


def _tile_bounds(grid_x: int, grid_y: int, overlap_pixels: int) -> tuple[float, float, float, float]:
    dimensions = tile_dimensions(overlap_pixels)
    half_chip = dimensions["chip_size_m"] / 2
    center_x = grid_x * dimensions["stride_m"]
    center_y = grid_y * dimensions["stride_m"]
    return (
        center_x - half_chip,
        center_y - half_chip,
        center_x + half_chip,
        center_y + half_chip,
    )


def _validate_schema(cur: Any) -> None:
    required = {
        "datasets",
        "dataset_versions",
        "ingestion_runs",
        "model_runs",
        "data_quality_checks",
        "administrative_units",
        "asset_admin_assignments",
        "administrative_hazard_summaries",
        "prithvi_national_batches",
        "prithvi_national_admin_batch_stats",
    }
    cur.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name=ANY(%s)",
        (sorted(required),),
    )
    present = {row[0] for row in cur.fetchall()}
    missing = sorted(required - present)
    if missing:
        raise RuntimeError("Apply the current database/schema.sql in Supabase; missing: " + ", ".join(missing))
    cur.execute(
        "SELECT table_name,column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=ANY(%s)",
        (
            [
                "administrative_hazard_summaries",
                "prithvi_national_batches",
                "prithvi_national_admin_batch_stats",
            ],
        ),
    )
    columns: dict[str, set[str]] = {}
    for table_name, column_name in cur.fetchall():
        columns.setdefault(table_name, set()).add(column_name)
    required_columns = {
        "administrative_hazard_summaries": {
            "total_pixels",
            "valid_pixels",
            "candidate_pixels",
            "candidate_area_m2",
            "valid_coverage_fraction",
        },
        "prithvi_national_batches": {"grid_x", "grid_y", "status", "batch_geom"},
        "prithvi_national_admin_batch_stats": {
            "administrative_unit_id",
            "total_pixels",
            "valid_pixels",
            "candidate_pixels",
        },
    }
    missing_columns = [
        f"{table}.{column}"
        for table, expected in required_columns.items()
        for column in sorted(expected - columns.get(table, set()))
    ]
    if missing_columns:
        raise RuntimeError("Current database/schema.sql is required; missing columns: " + ", ".join(missing_columns))


def _boundary_signature(cur: Any) -> tuple[str, int, int]:
    cur.execute(
        """
        SELECT count(*) FILTER (WHERE unit_level='county')::int,
               count(*) FILTER (WHERE unit_level='ward')::int,
               md5(string_agg(id::text || ':' || md5(encode(ST_AsEWKB(geom),'hex')), ',' ORDER BY id))
        FROM administrative_units WHERE unit_level IN ('county','ward')
        """
    )
    county_count, ward_count, signature = cur.fetchone()
    if county_count != 47 or ward_count < 1:
        raise RuntimeError(
            f"Nationwide Prithvi requires all 47 counties and ward boundaries; found counties={county_count}, wards={ward_count}"
        )
    return signature, county_count, ward_count


def _ensure_grid(cur: Any, fingerprint: str, run_id: str, overlap_pixels: int) -> int:
    dimensions = tile_dimensions(overlap_pixels)
    chip_m = dimensions["chip_size_m"]
    stride_m = dimensions["stride_m"]
    core_half_m = stride_m / 2
    cur.execute(
        """
        WITH country AS (
          SELECT ST_UnaryUnion(ST_Collect(ST_Transform(geom,6933))) AS geom
          FROM administrative_units WHERE unit_level='county'
        ), bounds AS (
          SELECT ST_XMin(ST_Envelope(geom)) AS min_x, ST_YMin(ST_Envelope(geom)) AS min_y,
                 ST_XMax(ST_Envelope(geom)) AS max_x, ST_YMax(ST_Envelope(geom)) AS max_y
          FROM country
        ), axes AS (
          SELECT x.grid_x, y.grid_y, country.geom AS country_geom
          FROM bounds CROSS JOIN country
          CROSS JOIN LATERAL generate_series(
            ceil((bounds.min_x - %s) / %s)::bigint,
            floor((bounds.max_x + %s) / %s)::bigint
          ) AS x(grid_x)
          CROSS JOIN LATERAL generate_series(
            ceil((bounds.min_y - %s) / %s)::bigint,
            floor((bounds.max_y + %s) / %s)::bigint
          ) AS y(grid_y)
        ), tiles AS (
          SELECT grid_x,grid_y,country_geom,
            ST_MakeEnvelope(grid_x*%s-%s/2,grid_y*%s-%s/2,
                            grid_x*%s+%s/2,grid_y*%s+%s/2,6933) AS tile_geom,
            ST_MakeEnvelope(grid_x*%s-%s/2,grid_y*%s-%s/2,
                            grid_x*%s+%s/2,grid_y*%s+%s/2,6933) AS core_geom
          FROM axes
        )
        INSERT INTO prithvi_national_batches
          (event_fingerprint,batch_id,processing_run_id,batch_geom,status,grid_x,grid_y)
        SELECT %s,'x'||grid_x||'_y'||grid_y,%s,ST_Transform(tile_geom,4326),'pending',grid_x,grid_y
        FROM tiles WHERE ST_Intersects(core_geom,country_geom)
        ON CONFLICT (event_fingerprint,batch_id) DO NOTHING
        """,
        (
            core_half_m,
            stride_m,
            core_half_m,
            stride_m,
            core_half_m,
            stride_m,
            core_half_m,
            stride_m,
            stride_m,
            chip_m,
            stride_m,
            chip_m,
            stride_m,
            chip_m,
            stride_m,
            chip_m,
            stride_m,
            core_half_m,
            stride_m,
            core_half_m,
            stride_m,
            core_half_m,
            stride_m,
            core_half_m,
            fingerprint,
            run_id,
        ),
    )
    cur.execute("SELECT count(*)::int FROM prithvi_national_batches WHERE event_fingerprint=%s", (fingerprint,))
    return int(cur.fetchone()[0])


def _load_admin_units(cur: Any, core_bounds: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    from shapely.geometry import shape

    min_x, min_y, max_x, max_y = core_bounds
    cur.execute(
        """
        SELECT id::text,unit_level,ST_AsGeoJSON(ST_Transform(geom,6933))::json
        FROM administrative_units
        WHERE unit_level IN ('county','ward')
          AND ST_Intersects(
            geom,
            ST_Transform(ST_MakeEnvelope(%s,%s,%s,%s,6933),4326)
          )
        """,
        (min_x, min_y, max_x, max_y),
    )
    return [
        {"id": row[0], "unit_level": row[1], "geometry": shape(row[2])}
        for row in cur.fetchall()
    ]


def _initialize_model(model_dir: Path) -> tuple[Any, Any, Any]:
    inference_path = model_dir / "inference.py"
    checkpoint = model_dir / CHECKPOINT
    config = model_dir / "config.yaml"
    if not all(path.is_file() and path.stat().st_size for path in (inference_path, checkpoint, config)):
        raise RuntimeError("Pinned Prithvi model bundle is missing; run `npm run oseas:prithvi:setup` first")
    spec = importlib.util.spec_from_file_location("oseas_prithvi_pinned_inference", inference_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the pinned Prithvi inference module")
    inference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inference)

    import yaml
    from terratorch.cli_tools import LightningInferenceModel

    config_data = yaml.safe_load(config.read_text(encoding="utf-8"))
    config_data["model"]["init_args"]["model_args"]["backbone_pretrained"] = False
    with tempfile.TemporaryDirectory(prefix="oseas-prithvi-national-config-") as temp_dir:
        runtime_config = Path(temp_dir) / "config.yaml"
        runtime_config.write_text(yaml.safe_dump(config_data, sort_keys=False), encoding="utf-8")
        model = LightningInferenceModel.from_config(str(runtime_config), str(checkpoint))
    model.model.eval()
    return inference, model.model, model.datamodule


def _predict(inference: Any, model: Any, datamodule: Any, input_path: Path) -> Any:
    import numpy as np

    input_data, temporal_coords, location_coords, _ = inference.load_example(
        file_paths=[str(input_path)],
        indices=list(range(len(BANDS))),
    )
    if input_data.mean() > 1:
        input_data = input_data / 10000
    output = inference.run_model(
        input_data,
        temporal_coords,
        location_coords,
        model,
        datamodule,
        MODEL_PATCH_SIZE_PIXELS,
    )
    labels = np.squeeze(output.detach().cpu().numpy())
    if labels.shape != (MODEL_PATCH_SIZE_PIXELS, MODEL_PATCH_SIZE_PIXELS):
        raise RuntimeError(f"Prithvi returned unexpected prediction dimensions: {labels.shape}")
    unexpected = sorted(int(value) for value in np.unique(labels) if int(value) not in (0, 1))
    if unexpected:
        raise RuntimeError(f"Prithvi returned unexpected class IDs: {unexpected}")
    return labels.astype("uint8", copy=False)


def _download_tile(
    ee: Any,
    grid_x: int,
    grid_y: int,
    overlap_pixels: int,
    event_start: str,
    event_end: str,
    max_cloud_percent: float,
    destination: Path,
    lake_asset_id: str | None,
) -> dict[str, Any] | None:
    import rasterio

    dimensions = tile_dimensions(overlap_pixels)
    min_x, min_y, max_x, max_y = _tile_bounds(grid_x, grid_y, overlap_pixels)
    roi = ee.Geometry.Rectangle(
        [min_x, min_y, max_x, max_y],
        proj=ee.Projection(f"EPSG:{GRID_CRS}"),
        geodesic=False,
    )
    collection = (
        ee.ImageCollection("COPERNICUS/S2_HARMONIZED")
        .filterBounds(roi)
        .filterDate(event_start, event_end)
        .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", max_cloud_percent))
    )
    scene_count = int(collection.size().getInfo())
    if not scene_count:
        return None
    scene = ee.Image(collection.sort("CLOUDY_PIXEL_PERCENTAGE").first())
    clear = (
        scene.select("QA60").bitwiseAnd(1 << 10).eq(0)
        .And(scene.select("QA60").bitwiseAnd(1 << 11).eq(0))
        .And(scene.select("B2").mask())
    )
    reflectance = scene.updateMask(clear).select(BANDS)
    valid_mask = reflectance.select("B2").mask().unmask(0).rename("VALID_MASK").toInt16()
    permanent_water = (
        ee.Image("JRC/GSW1_4/GlobalSurfaceWater")
        .select("occurrence")
        .rename("JRC_OCCURRENCE")
    )
    bands = BANDS + ["VALID_MASK", "JRC_OCCURRENCE"]
    image = reflectance.unmask(0).toInt16().addBands(valid_mask)
    image = image.addBands(permanent_water.unmask(-1).toInt16())
    if lake_asset_id:
        lakes = ee.FeatureCollection(lake_asset_id).filterBounds(roi)
        if int(lakes.size().getInfo()):
            lake_mask = ee.Image.constant(0).byte().paint(lakes, 1).rename("LAKE_MASK")
            image = image.addBands(lake_mask.toInt16())
            bands.append("LAKE_MASK")
    image = image.clip(roi)
    transform = [PIXEL_SIZE_METRES, 0, min_x, 0, -PIXEL_SIZE_METRES, max_y]
    url = image.getDownloadURL(
        {
            "name": "oseas_prithvi_national_tile",
            "bands": bands,
            "region": roi,
            "crs": f"EPSG:{GRID_CRS}",
            "crs_transform": transform,
            "format": "GEO_TIFF",
            "filePerBand": False,
        }
    )
    request = Request(url, headers={"User-Agent": "oseas-prithvi-national/1.0"})
    with urlopen(request, timeout=180) as response, destination.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    if zipfile.is_zipfile(destination):
        with zipfile.ZipFile(destination) as archive:
            tiffs = [name for name in archive.namelist() if name.lower().endswith((".tif", ".tiff"))]
            if len(tiffs) != 1:
                raise RuntimeError(f"Expected one multiband tile GeoTIFF from Earth Engine; found {len(tiffs)}")
            extracted = destination.with_suffix(".unpacked.tif")
            with archive.open(tiffs[0]) as source, extracted.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
        destination.unlink(missing_ok=True)
        extracted.replace(destination)

    properties = scene.toDictionary(
        ["system:index", "system:time_start", "CLOUDY_PIXEL_PERCENTAGE", "MGRS_TILE", "PROCESSING_BASELINE"]
    ).getInfo()
    with rasterio.open(destination) as raster:
        if (
            raster.width != MODEL_PATCH_SIZE_PIXELS
            or raster.height != MODEL_PATCH_SIZE_PIXELS
            or raster.count not in (8, 9)
            or raster.crs.to_epsg() != GRID_CRS
        ):
            raise RuntimeError(
                f"Earth Engine tile has unexpected shape/bands/CRS: "
                f"{raster.width}x{raster.height}, bands={raster.count}, crs={raster.crs}"
            )
        if not raster.transform.almost_equals(
            rasterio.Affine(
                PIXEL_SIZE_METRES, 0, min_x, 0, -PIXEL_SIZE_METRES, max_y
            )
        ):
            raise RuntimeError("Earth Engine tile transform does not match the requested national grid")
        margin = overlap_pixels // 2
        valid_band = raster.read(7)
        valid_fraction = float(
            (valid_band[margin : MODEL_PATCH_SIZE_PIXELS - margin,
                        margin : MODEL_PATCH_SIZE_PIXELS - margin] == 1).mean()
        )
    timestamp = properties.get("system:time_start")
    acquired = (
        datetime.fromtimestamp(float(timestamp) / 1000, tz=timezone.utc).isoformat()
        if timestamp is not None
        else None
    )
    return {
        "scene_id": properties.get("system:index"),
        "acquisition_datetime_utc": acquired,
        "cloudy_pixel_percentage_scene": properties.get("CLOUDY_PIXEL_PERCENTAGE"),
        "mgrs_tile": properties.get("MGRS_TILE"),
        "processing_baseline": properties.get("PROCESSING_BASELINE"),
        "candidate_scene_count": scene_count,
        "valid_pixel_coverage": valid_fraction,
        "input_bands": BANDS,
        "pixel_size_m": PIXEL_SIZE_METRES,
        "crs": f"EPSG:{GRID_CRS}",
        "chip_pixels": dimensions["chip_pixels"],
        "overlap_pixels": dimensions["overlap_pixels"],
    }


def _read_tile_arrays(input_path: Path, labels: Any | None = None) -> tuple[Any, Any, Any, Any]:
    import numpy as np
    import rasterio

    with rasterio.open(input_path) as source:
        if source.count not in (8, 9):
            raise RuntimeError(f"Expected six model bands and two or three auxiliary bands; found {source.count}")
        valid = source.read(7) == 1
        jrc = source.read(8)
        lakes = source.read(9) == 1 if source.count >= 9 else np.zeros(valid.shape, dtype=bool)
    prediction = labels if labels is not None else np.zeros(valid.shape, dtype="uint8")
    return prediction, valid, jrc, lakes


def _record_admin_stats(cur: Any, fingerprint: str, batch_id: str, stats: list[dict[str, Any]]) -> tuple[int, int]:
    if stats:
        cur.executemany(
            """
            INSERT INTO prithvi_national_admin_batch_stats
              (event_fingerprint,batch_id,administrative_unit_id,total_pixels,valid_pixels,candidate_pixels)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (event_fingerprint,batch_id,administrative_unit_id) DO UPDATE SET
              total_pixels=EXCLUDED.total_pixels,valid_pixels=EXCLUDED.valid_pixels,
              candidate_pixels=EXCLUDED.candidate_pixels
            """,
            [
                (
                    fingerprint,
                    batch_id,
                    item["administrative_unit_id"],
                    item["total_pixels"],
                    item["valid_pixels"],
                    item["candidate_pixels"],
                )
                for item in stats
            ],
        )
    county_stats = [item for item in stats if item["unit_level"] == "county"]
    return (
        sum(item["valid_pixels"] for item in county_stats),
        sum(item["candidate_pixels"] for item in county_stats),
    )


def _mark_batch_processing(connection: Any, fingerprint: str, batch_id: str, run_id: str) -> None:
    with connection.cursor() as cur:
        cur.execute(
            """
            UPDATE prithvi_national_batches
            SET status='processing',processing_run_id=%s,error_message=NULL,processed_at=NULL
            WHERE event_fingerprint=%s AND batch_id=%s
            """,
            (run_id, fingerprint, batch_id),
        )
    connection.commit()


def _save_batch_result(
    connection: Any,
    fingerprint: str,
    batch_id: str,
    status: str,
    scene_id: str | None,
    error_message: str | None,
    stats: list[dict[str, Any]],
    run_id: str,
) -> None:
    with connection.cursor() as cur:
        valid_pixels, candidate_pixels = _record_admin_stats(cur, fingerprint, batch_id, stats)
        cur.execute(
            """
            UPDATE prithvi_national_batches
            SET status=%s,processing_run_id=%s,scene_ids=%s::jsonb,
                valid_pixels=%s,candidate_pixels=%s,candidate_area_m2=%s,
                error_message=%s,processed_at=NOW()
            WHERE event_fingerprint=%s AND batch_id=%s
            """,
            (
                status,
                run_id,
                json.dumps([scene_id] if scene_id else []),
                valid_pixels,
                candidate_pixels,
                candidate_pixels * PIXEL_SIZE_METRES**2,
                error_message,
                fingerprint,
                batch_id,
            ),
        )
    connection.commit()


def _process_batch(
    connection: Any,
    ee: Any,
    model: Any,
    inference: Any,
    datamodule: Any,
    run_id: str,
    fingerprint: str,
    batch: tuple[str, int, int],
    args: argparse.Namespace,
    lake_asset_id: str | None,
) -> dict[str, Any]:
    import numpy as np

    batch_id, grid_x, grid_y = batch
    dimensions = tile_dimensions(args.overlap_pixels)
    tile_bounds = _tile_bounds(grid_x, grid_y, args.overlap_pixels)
    core_half = dimensions["stride_m"] / 2
    center_x = grid_x * dimensions["stride_m"]
    center_y = grid_y * dimensions["stride_m"]
    core_bounds = (center_x - core_half, center_y - core_half, center_x + core_half, center_y + core_half)
    with connection.cursor() as cur:
        admin_units = _load_admin_units(cur, core_bounds)
    empty = np.zeros((MODEL_PATCH_SIZE_PIXELS, MODEL_PATCH_SIZE_PIXELS), dtype="uint8")
    no_observation_stats = _zonal_pixel_stats(
        empty,
        empty,
        np.full(empty.shape, -1, dtype="int16"),
        empty,
        admin_units,
        tile_bounds,
        args.overlap_pixels,
    )
    scene_id: str | None = None
    with tempfile.TemporaryDirectory(prefix="oseas-prithvi-tile-") as temp_dir:
        input_path = Path(temp_dir) / "input.tif"
        try:
            quality = _download_tile(
                ee,
                grid_x,
                grid_y,
                args.overlap_pixels,
                args.event_start,
                args.event_end,
                args.max_cloud_percent,
                input_path,
                lake_asset_id,
            )
            if quality is None:
                _save_batch_result(
                    connection,
                    fingerprint,
                    batch_id,
                    "no_observation",
                    None,
                    "No Sentinel-2 scene matched the tile, event interval and scene cloud filter.",
                    no_observation_stats,
                    run_id,
                )
                return {"batch_id": batch_id, "status": "no_observation"}
            scene_id = quality["scene_id"]
            if quality["valid_pixel_coverage"] < MIN_VALID_COVERAGE:
                _save_batch_result(
                    connection,
                    fingerprint,
                    batch_id,
                    "no_observation",
                    scene_id,
                    f"Only {quality['valid_pixel_coverage']:.1%} clear pixels; minimum is {MIN_VALID_COVERAGE:.0%}.",
                    no_observation_stats,
                    run_id,
                )
                return {
                    "batch_id": batch_id,
                    "status": "no_observation",
                    "valid_pixel_coverage": quality["valid_pixel_coverage"],
                }
            labels = _predict(inference, model, datamodule, input_path)
            _, valid, jrc, lakes = _read_tile_arrays(input_path, labels)
            stats = _zonal_pixel_stats(
                labels,
                valid,
                jrc,
                lakes,
                admin_units,
                tile_bounds,
                args.overlap_pixels,
            )
            _save_batch_result(
                connection,
                fingerprint,
                batch_id,
                "completed",
                scene_id,
                None,
                stats,
                run_id,
            )
            return {
                "batch_id": batch_id,
                "status": "completed",
                "scene_id": scene_id,
                "valid_pixel_coverage": quality["valid_pixel_coverage"],
            }
        except Exception as error:
            message = f"{type(error).__name__}: {error}"[:2000]
            LOG.exception("Prithvi national tile %s failed", batch_id)
            _save_batch_result(
                connection,
                fingerprint,
                batch_id,
                "failed",
                scene_id,
                message,
                no_observation_stats,
                run_id,
            )
            return {"batch_id": batch_id, "status": "failed", "error": message}


def _finalize(
    connection: Any,
    fingerprint: str,
    run_id: str,
    model_run_id: str,
    parameters: dict[str, Any],
    expected_tile_count: int,
) -> dict[str, Any]:
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT status,count(*)::int
            FROM prithvi_national_batches
            WHERE event_fingerprint=%s GROUP BY status
            """,
            (fingerprint,),
        )
        counts = {status: count for status, count in cur.fetchall()}
        dimensions = tile_dimensions(parameters["overlap_pixels"])
        cur.execute(
            """
            WITH batches AS (
              SELECT b.*,
                ST_Transform(ST_MakeEnvelope(
                  b.grid_x*%s-%s/2,b.grid_y*%s-%s/2,
                  b.grid_x*%s+%s/2,b.grid_y*%s+%s/2,6933
                ),4326) AS core_geom
              FROM prithvi_national_batches b WHERE b.event_fingerprint=%s
            ), unit_batch_counts AS (
              SELECT u.id,
                count(*) FILTER (WHERE b.status='completed')::int AS completed_tiles,
                count(*) FILTER (WHERE b.status='no_observation')::int AS no_observation_tiles,
                count(*) FILTER (WHERE b.status='failed')::int AS failed_tiles,
                count(*) FILTER (WHERE b.status IN ('pending','processing'))::int AS pending_tiles
              FROM administrative_units u
              LEFT JOIN batches b ON ST_Intersects(u.geom,b.core_geom)
              WHERE u.unit_level IN ('ward','county')
              GROUP BY u.id
            ), zonal AS (
              SELECT administrative_unit_id,sum(valid_pixels)::bigint AS valid_pixels,
                     sum(candidate_pixels)::bigint AS candidate_pixels
              FROM prithvi_national_admin_batch_stats WHERE event_fingerprint=%s
              GROUP BY administrative_unit_id
            ), units AS (
              SELECT u.id,u.unit_level,u.name,u.stable_code,u.geom,
                greatest(0,round(ST_Area(ST_Transform(u.geom,6933))/%s)::bigint) AS expected_pixels,
                coalesce(z.valid_pixels,0)::bigint AS valid_pixels,
                coalesce(z.candidate_pixels,0)::bigint AS candidate_pixels,
                coalesce(b.completed_tiles,0) AS completed_tiles,
                coalesce(b.no_observation_tiles,0) AS no_observation_tiles,
                coalesce(b.failed_tiles,0) AS failed_tiles,
                coalesce(b.pending_tiles,0) AS pending_tiles,
                (SELECT count(DISTINCT aa.energy_asset_id)::int FROM asset_admin_assignments aa
                 WHERE aa.administrative_unit_id=u.id AND aa.is_current=TRUE) AS assigned_assets
              FROM administrative_units u
              LEFT JOIN zonal z ON z.administrative_unit_id=u.id
              LEFT JOIN unit_batch_counts b ON b.id=u.id
              WHERE u.unit_level IN ('ward','county')
            )
            INSERT INTO administrative_hazard_summaries
              (id,administrative_unit_id,hazard_type,event_fingerprint,period_start,period_end,
               assessment_status,assigned_energy_asset_count,candidate_exposed_asset_count,
               candidate_exposure_fraction,provenance,processing_run_id,total_pixels,valid_pixels,
               candidate_pixels,candidate_area_m2,valid_coverage_fraction)
            SELECT md5(u.id::text||':'||%s)::uuid,u.id,'flood',%s,%s::date,%s::date,
              CASE WHEN u.pending_tiles=0 AND u.failed_tiles=0 AND u.expected_pixels>0
                         AND least(1.0,u.valid_pixels::double precision/u.expected_pixels)>=%s
                   THEN 'screened' ELSE 'insufficient_data' END,
              u.assigned_assets,NULL,NULL,
              jsonb_build_object(
                'pipeline','prithvi_national_tiled',
                'model_id',%s::text,'model_revision',%s::text,
                'event_fingerprint',%s::text,'evidence_kind','modeled',
                'class_label','water_or_flood_candidate',
                'validation_status','inference_only',
                'grid_crs','EPSG:6933','pixel_size_m',%s,
                'chip_size_pixels',%s,'overlap_pixels',%s,'core_size_pixels',%s,
                'completed_tiles',u.completed_tiles,'no_observation_tiles',u.no_observation_tiles,
                'failed_tiles',u.failed_tiles,'pending_tiles',u.pending_tiles,
                'expected_pixels_are_area_derived',true,
                'candidate_pixels_are_center_rasterized',true,
                'permanent_water_mask','JRC occurrence >=80% excluded; missing occurrence retained',
                'limitations',jsonb_build_array(
                  'Class 1 is model-predicted water/flood candidate, not verified inundation.',
                  'Kenya-specific accuracy is not validated.',
                  'Candidate-exposed asset counts and composite risk scores are not assessed.'
                )
              ),%s,u.expected_pixels,u.valid_pixels,u.candidate_pixels,
              u.candidate_pixels::double precision*%s,
              CASE WHEN u.expected_pixels>0 THEN least(1.0,u.valid_pixels::double precision/u.expected_pixels) END
            FROM units u
            ON CONFLICT (administrative_unit_id,hazard_type,event_fingerprint) DO UPDATE SET
              period_start=EXCLUDED.period_start,period_end=EXCLUDED.period_end,
              assessment_status=EXCLUDED.assessment_status,
              assigned_energy_asset_count=EXCLUDED.assigned_energy_asset_count,
              candidate_exposed_asset_count=NULL,candidate_exposure_fraction=NULL,
              provenance=EXCLUDED.provenance,processing_run_id=EXCLUDED.processing_run_id,
              total_pixels=EXCLUDED.total_pixels,valid_pixels=EXCLUDED.valid_pixels,
              candidate_pixels=EXCLUDED.candidate_pixels,candidate_area_m2=EXCLUDED.candidate_area_m2,
              valid_coverage_fraction=EXCLUDED.valid_coverage_fraction
            """,
            (
                dimensions["stride_m"],
                dimensions["stride_m"],
                dimensions["stride_m"],
                dimensions["stride_m"],
                dimensions["stride_m"],
                dimensions["stride_m"],
                dimensions["stride_m"],
                dimensions["stride_m"],
                fingerprint,
                fingerprint,
                PIXEL_SIZE_METRES**2,
                fingerprint,
                fingerprint,
                parameters["event_start"],
                parameters["event_end"],
                MIN_VALID_COVERAGE,
                MODEL_ID,
                MODEL_REVISION,
                fingerprint,
                PIXEL_SIZE_METRES,
                dimensions["chip_pixels"],
                dimensions["overlap_pixels"],
                dimensions["core_pixels"],
                run_id,
                PIXEL_SIZE_METRES**2,
            ),
        )
        summary_count = cur.rowcount
        status_counts = {key: counts.get(key, 0) for key in ("pending", "processing", "completed", "no_observation", "failed")}
        pipeline_status = (
            "completed"
            if status_counts["pending"] == status_counts["processing"] == status_counts["failed"] == status_counts["no_observation"] == 0
            and status_counts["completed"] == expected_tile_count
            else "partial"
        )
        metrics = {
            "event_fingerprint": fingerprint,
            "tile_counts": status_counts,
            "planned_tiles": expected_tile_count,
            "administrative_summaries_upserted": summary_count,
            "chip_size_pixels": dimensions["chip_pixels"],
            "overlap_pixels": dimensions["overlap_pixels"],
            "pixel_size_m": PIXEL_SIZE_METRES,
            "kenya_validation": "not_evaluated",
        }
        cur.execute(
            "UPDATE model_runs SET status=%s,finished_at=NOW(),metrics=%s::jsonb WHERE id=%s",
            (pipeline_status, json.dumps(metrics), model_run_id),
        )
        cur.execute(
            """
            UPDATE ingestion_runs SET status=%s,finished_at=NOW(),metadata=metadata||%s::jsonb
            WHERE id=%s
            """,
            (pipeline_status, json.dumps(metrics), run_id),
        )
        cur.execute(
            """
            INSERT INTO data_quality_checks(run_id,dataset_key,check_name,status,details)
            VALUES(%s,'sentinel2_l1c','prithvi_national_tile_coverage',%s,%s::jsonb)
            """,
            (
                run_id,
                "passed" if pipeline_status == "completed" else "warning",
                json.dumps(metrics),
            ),
        )
    connection.commit()
    return {
        "status": pipeline_status,
        "event_fingerprint": fingerprint,
        "tile_counts": {key: counts.get(key, 0) for key in ("pending", "processing", "completed", "no_observation", "failed")},
        "planned_tiles": expected_tile_count,
        "administrative_summaries_upserted": summary_count,
    }


def _write_report(report_path: Path, result: dict[str, Any]) -> None:
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2), encoding="utf-8")
    temporary.replace(report_path)


def run(args: argparse.Namespace) -> dict[str, Any]:
    if MODEL_ID != SUPPORTED_MODEL_ID:
        raise RuntimeError(f"National preprocessing supports only the pinned model {SUPPORTED_MODEL_ID}")
    validate_args(args)
    project = os.getenv("GEE_PROJECT_ID", "").strip()
    from oseas.config import database_url

    db_url = database_url()
    if not db_url or not project:
        raise RuntimeError("DB_URL (or supported alias) and GEE_PROJECT_ID are required")
    model_dir = Path(os.getenv("PRITHVI_MODEL_DIR", "models/prithvi/flood_sen1floods11"))
    if not model_dir.is_absolute():
        model_dir = ROOT / model_dir

    import psycopg
    from gee.auth import initialize_earth_engine

    if not initialize_earth_engine(project):
        raise RuntimeError("Earth Engine authentication failed; check GEE_PROJECT_ID and configured credentials")
    import ee

    lake_asset_id = os.getenv("GEE_ASSET_KENYA_LAKES", "").strip() or None
    dimensions = tile_dimensions(args.overlap_pixels)
    parameters = {
        "event_start": args.event_start,
        "event_end": args.event_end,
        "max_cloud_percent": args.max_cloud_percent,
        "grid_crs": f"EPSG:{GRID_CRS}",
        "pixel_size_m": PIXEL_SIZE_METRES,
        "chip_size_pixels": MODEL_PATCH_SIZE_PIXELS,
        "overlap_pixels": args.overlap_pixels,
        "core_size_pixels": dimensions["core_pixels"],
        "input_collection": "COPERNICUS/S2_HARMONIZED",
        "input_bands": BANDS,
        "minimum_valid_coverage": MIN_VALID_COVERAGE,
        "lake_mask_asset_id": lake_asset_id,
        "checkpoint": CHECKPOINT,
        "preprocessing_version": "oseas-prithvi-national-grid-v1",
    }
    inference, model, datamodule = _initialize_model(model_dir)
    run_id, model_run_id = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(
        db_url,
        prepare_threshold=None,
        connect_timeout=15,
        options="-c statement_timeout=0",
        application_name="oseas-prithvi-national",
    ) as connection:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s),hashtext('writer'))", (INGEST_LOCK,))
            if not cur.fetchone()[0]:
                raise RuntimeError("Infrastructure ingestion is active; wait for it to finish")
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s),hashtext('writer'))", (MODEL_LOCK,))
            if not cur.fetchone()[0]:
                raise RuntimeError("Another Prithvi inference run is active")
            _validate_schema(cur)
            boundary_signature, county_count, ward_count = _boundary_signature(cur)
            fingerprint = _event_fingerprint(parameters, boundary_signature)
            cur.execute(
                """
                INSERT INTO ingestion_runs(id,pipeline_name,status,started_at,metadata)
                VALUES(%s,%s,'running',NOW(),%s::jsonb)
                """,
                (run_id, PIPELINE_NAME, json.dumps({"parameters": parameters, "event_fingerprint": fingerprint})),
            )
            cur.execute(
                """
                INSERT INTO model_runs(id,model_name,model_version,checkpoint,task,parameters,metrics,status,processing_run_id)
                VALUES(%s,%s,%s,%s,'flood_segmentation',%s::jsonb,'{}'::jsonb,'running',%s)
                """,
                (model_run_id, MODEL_ID, MODEL_REVISION, CHECKPOINT, json.dumps(parameters), run_id),
            )
            cur.execute(
                """
                INSERT INTO datasets(dataset_key,name,source_type,source_reference,category,licence,attribution,is_optional)
                VALUES('sentinel2_l1c','Sentinel-2 Level-1C harmonized','earth_engine_image_collection',
                       'COPERNICUS/S2_HARMONIZED','satellite','Copernicus Sentinel Data Terms',
                       'Copernicus Sentinel-2',TRUE)
                ON CONFLICT(dataset_key) DO UPDATE SET updated_at=NOW()
                """
            )
            cur.execute(
                """
                INSERT INTO dataset_versions
                  (dataset_key,source_reference,retrieved_at,observation_start,observation_end,
                   feature_count,metadata,processing_run_id)
                VALUES('sentinel2_l1c','COPERNICUS/S2_HARMONIZED',NOW(),%s::date,%s::date,NULL,%s::jsonb,%s)
                """,
                (
                    args.event_start,
                    args.event_end,
                    json.dumps(
                        {
                            "model": MODEL_ID,
                            "model_revision": MODEL_REVISION,
                            "event_fingerprint": fingerprint,
                            "processing_scope": "Kenya national grid",
                            "parameters": parameters,
                        }
                    ),
                    run_id,
                ),
            )
            cur.execute(
                """
                UPDATE prithvi_national_batches
                SET status='pending',processing_run_id=%s,error_message=NULL,processed_at=NULL
                WHERE event_fingerprint=%s AND status IN ('processing','failed')
                """,
                (run_id, fingerprint),
            )
            expected_tile_count = _ensure_grid(cur, fingerprint, run_id, args.overlap_pixels)
        connection.commit()
        LOG.info(
            "Starting Kenya-wide tiled inference: counties=%s wards=%s planned_tiles=%s chip=%sx%s overlap=%s pixels",
            county_count,
            ward_count,
            expected_tile_count,
            dimensions["chip_pixels"],
            dimensions["chip_pixels"],
            dimensions["overlap_pixels"],
        )

        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT batch_id,grid_x,grid_y FROM prithvi_national_batches
                WHERE event_fingerprint=%s AND status='pending'
                ORDER BY grid_y,grid_x
                """,
                (fingerprint,),
            )
            batches = [(row[0], int(row[1]), int(row[2])) for row in cur.fetchall()]
        if args.max_tiles is not None:
            batches = batches[: args.max_tiles]

        tile_results = []
        started = time.monotonic()
        for index, batch in enumerate(batches, start=1):
            _mark_batch_processing(connection, fingerprint, batch[0], run_id)
            LOG.info("Processing national tile %s/%s (%s)", index, len(batches), batch[0])
            tile_results.append(
                _process_batch(
                    connection,
                    ee,
                    model,
                    inference,
                    datamodule,
                    run_id,
                    fingerprint,
                    batch,
                    args,
                    lake_asset_id,
                )
            )
            if index % 25 == 0:
                LOG.info("National tile progress: %s/%s; elapsed %.0fs", index, len(batches), time.monotonic() - started)

        result = _finalize(connection, fingerprint, run_id, model_run_id, parameters, expected_tile_count)
        result.update(
            {
                "run_id": run_id,
                "model_run_id": model_run_id,
                "parameters": parameters,
                "processed_this_run": len(tile_results),
                "failed_this_run": sum(item["status"] == "failed" for item in tile_results),
                "no_observation_this_run": sum(item["status"] == "no_observation" for item in tile_results),
                "resumable": any(
                    result["tile_counts"][status] > 0
                    for status in ("pending", "processing", "failed")
                ),
                "summary_endpoint": "/api/v1/oseas/layers/prithvi_national_summaries/geojson",
            }
        )
        return result


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    result = run(args)
    _write_report(Path(args.report), result)
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
