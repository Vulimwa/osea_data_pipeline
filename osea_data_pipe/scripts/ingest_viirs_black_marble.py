"""Acquire quality-screened NASA VIIRS Black Marble and persist map-ready context."""

from __future__ import annotations

import hashlib
import json
import math
import os
import gc
import importlib.util
import shutil
import subprocess
import sys
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any
from contextlib import ExitStack

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from oseas.config import database_url  # noqa: E402
from gee.auth import initialize_earth_engine  # noqa: E402

DATASET_KEY = "nasa_viirs_black_marble_monthly"
METHOD = "viirs_black_marble_daily_quality_screened_monthly_period_median_v3"
NAMESPACE = uuid.UUID("cf4d3e44-cd2b-47ce-a959-8c60f28c36c2")
RADIANCE_UNIT = "nW cm-2 sr-1"


def month_dates(start_month: str, end_month: str) -> list[date]:
    """Return first-of-month dates for the inclusive YYYY-MM interval."""
    try:
        start = date.fromisoformat(f"{start_month}-01")
        end = date.fromisoformat(f"{end_month}-01")
    except ValueError as error:
        raise ValueError("Nightlight months must use YYYY-MM format") from error
    if start.day != 1 or end.day != 1 or start > end:
        raise ValueError("Nightlight month range must be ordered YYYY-MM values")
    dates: list[date] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        dates.append(date(year, month, 1))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return dates


def stable_id(*parts: str) -> str:
    return str(uuid.uuid5(NAMESPACE, "|".join(parts)))


def _active_script_processes() -> list[int]:
    """Find other runs, including older versions that predate the local lock file."""
    if os.name == "nt":
        command = ("$items = @(Get-CimInstance Win32_Process | Where-Object { "
                   "$_.Name -match '^python(w)?(\\.exe)?$' -and $_.CommandLine -match "
                   "'ingest_viirs_black_marble\\.py' } | Select-Object -ExpandProperty ProcessId); "
                   "ConvertTo-Json -Compress -InputObject $items")
        result = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                                capture_output=True, text=True, timeout=15, check=False)
        if result.returncode != 0:
            raise RuntimeError("Could not check for an active Black Marble process")
        output = result.stdout.strip()
        if not output:
            return []
        try:
            values = json.loads(output)
        except json.JSONDecodeError as error:
            raise RuntimeError("Could not parse the active Black Marble process check") from error
        if values is None:
            return []
        if not isinstance(values, list):
            values = [values]
        return [int(value) for value in values if int(value) != os.getpid()]

    proc_root = Path("/proc")
    if not proc_root.exists():
        return []
    active = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            command_line = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if "ingest_viirs_black_marble.py" in command_line:
            active.append(int(entry.name))
    return active


def _acquire_local_process_lock() -> Path:
    lock_path = ROOT / "outputs" / ".viirs_black_marble.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(2):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"pid": os.getpid(), "started_at": time.time()}, stream)
            try:
                active = _active_script_processes()
            except Exception:
                lock_path.unlink(missing_ok=True)
                raise
            if active:
                lock_path.unlink(missing_ok=True)
                raise RuntimeError(f"Black Marble process(es) {','.join(map(str, active))} are already active; refusing duplicate acquisition")
            return lock_path
        except FileExistsError:
            try:
                owner = json.loads(lock_path.read_text(encoding="utf-8"))
                pid = int(owner.get("pid", -1))
            except (OSError, ValueError, json.JSONDecodeError):
                pid = -1
            if pid > 0:
                try:
                    os.kill(pid, 0)
                    raise RuntimeError(f"Black Marble process lock belongs to active PID {pid}")
                except OSError:
                    pass
            if attempt == 0:
                lock_path.unlink(missing_ok=True)
    raise RuntimeError("Could not acquire the local Black Marble process lock")


def _is_transient_remote_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in (
        "name resolution", "failed to resolve", "connection reset", "connection aborted",
        "temporarily unavailable", "timed out", "timeout", "502", "503", "504", "429",
    ))


def _retry_remote_call(label: str, operation: Any, *, attempts: int = 5) -> Any:
    """Retry only transient network/service failures, with visible bounded backoff."""
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as error:
            if attempt == attempts or not _is_transient_remote_error(error):
                raise
            delay_seconds = min(20, 2 ** (attempt - 1))
            print(f"Black Marble: transient {label} error ({type(error).__name__}); retry "
                  f"{attempt + 1}/{attempts} in {delay_seconds}s", flush=True)
            time.sleep(delay_seconds)


def _initialize_earth_engine_with_retry(project_id: str) -> bool:
    for attempt in range(1, 4):
        if initialize_earth_engine(project_id or None):
            return True
        if attempt < 3:
            delay_seconds = 2 ** (attempt - 1)
            print(f"Black Marble: Earth Engine initialization retry {attempt + 1}/3 "
                  f"in {delay_seconds}s", flush=True)
            time.sleep(delay_seconds)
    return False


def summarize_extract(frame: Any, requested_dates: list[date], *, zone_column: str = "zone_key") -> list[dict[str, Any]]:
    """Normalize BlackMarblePy zonal rows and report missing months as coverage, not zero."""
    import pandas as pd

    rows = frame.copy()
    date_column = next((column for column in ("date", "datetime", "Date") if column in rows.columns), None)
    # BlackMarblePy prefixes exact_extract statistics with `ntl_`.
    value_column = next((column for column in ("ntl_mean", "mean", "radiance_mean", "NearNadir_Composite_Snow_Free") if column in rows.columns), None)
    count_column = next((column for column in ("ntl_count", "count", "n", "valid_pixel_count") if column in rows.columns), None)
    if zone_column not in rows.columns or date_column is None or value_column is None:
        raise ValueError(f"BlackMarblePy output schema is unsupported; columns={list(rows.columns)}")
    rows[date_column] = pd.to_datetime(rows[date_column]).dt.date
    rows[value_column] = pd.to_numeric(rows[value_column], errors="coerce")
    requested = set(requested_dates)
    rows = rows[rows[date_column].isin(requested)]
    result = []
    for zone_key, group in rows.groupby(zone_column, sort=True):
        valid = group[group[value_column].notna()]
        values = {row[date_column]: float(row[value_column]) for _, row in valid.iterrows()}
        result.append({"zone_key": str(zone_key), "median_radiance": float(valid[value_column].median()) if len(valid) else None,
                       "mean_radiance": float(valid[value_column].mean()) if len(valid) else None,
                       "mean_valid_pixel_count": float(pd.to_numeric(valid[count_column], errors="coerce").mean()) if count_column and len(valid) else None,
                       "valid_month_count": len(values), "requested_month_count": len(requested_dates),
                       "valid_month_fraction": len(values) / len(requested_dates) if requested_dates else None,
                       "observed_dates": sorted(item.isoformat() for item in values),
                       "monthly_values": {item.isoformat(): value for item, value in values.items()}})
    return result


def _extract_columns(frame: Any) -> tuple[str, str, str | None]:
    date_column = next((column for column in ("date", "datetime", "Date") if column in frame.columns), None)
    value_column = next((column for column in ("ntl_mean", "mean", "radiance_mean", "NearNadir_Composite_Snow_Free") if column in frame.columns), None)
    count_column = next((column for column in ("ntl_count", "count", "n", "valid_pixel_count") if column in frame.columns), None)
    if "zone_key" not in frame.columns or date_column is None or value_column is None:
        raise ValueError(f"BlackMarblePy output schema is unsupported; columns={list(frame.columns)}")
    return date_column, value_column, count_column


def fetch_zones(connection: Any) -> Any:
    """Load county/ward polygons and asset/service points for zonal extraction."""
    import geopandas as gpd
    from shapely import wkb

    with connection.cursor() as count_cursor:
        count_cursor.execute("""SELECT (SELECT count(*) FROM administrative_units WHERE unit_level IN ('county','ward'))
          + (SELECT count(*) FROM energy_assets) + (SELECT count(*) FROM critical_services)""")
        expected_count = int(count_cursor.fetchone()[0])
    print(f"Black Marble zones: preparing {expected_count:,} administrative, asset, and service features", flush=True)
    records = []
    with connection.cursor() as cur:
        # Nightlights are 500 m pixels; a sub-55 m boundary generalization
        # keeps the national transfer small without changing source boundaries.
        cur.execute("""SELECT 'admin:'||id::text,unit_level,name,
                      ST_AsBinary(ST_SimplifyPreserveTopology(geom,0.0005)),id::text
                      FROM administrative_units WHERE unit_level IN ('county','ward')""")
        records.extend(cur.fetchall())
    admin_count = len(records)
    print(f"Black Marble zones: fetched {len(records):,}/{expected_count:,} county/ward polygons", flush=True)
    query = """SELECT 'asset:'||id::text,'energy_asset',COALESCE(name,asset_type),
                      ST_AsBinary(ST_PointOnSurface(ST_SimplifyPreserveTopology(geom,0.0001))),id::text
                      FROM energy_assets
               UNION ALL
               SELECT 'service:'||id::text,'critical_service',COALESCE(name,service_type),
                      ST_AsBinary(ST_PointOnSurface(ST_SimplifyPreserveTopology(geom,0.0001))),id::text
                      FROM critical_services"""
    with connection.cursor(name="oseas_black_marble_zone_cursor") as cur:
        cur.itersize = 5000
        cur.execute(query)
        while True:
            batch = cur.fetchmany(5000)
            if not batch:
                break
            records.extend(batch)
            if (len(records) - admin_count) % 10000 == 0 or len(records) == expected_count:
                print(f"Black Marble zones: fetched {len(records):,}/{expected_count:,}", flush=True)
    if not records:
        raise RuntimeError("No administrative, asset, or critical-service geometries are available for Black Marble extraction")
    features = [{"zone_key": row[0], "zone_type": row[1], "zone_name": row[2], "source_id": row[4], "geometry": wkb.loads(bytes(row[3]))}
                for row in records]
    gdf = gpd.GeoDataFrame(features, geometry="geometry", crs="EPSG:4326")
    del features, records
    gc.collect()
    gdf = gdf.sort_values("zone_key").reset_index(drop=True)
    point_context = gdf["zone_type"].isin(["energy_asset", "critical_service"])
    gdf["context_radius_m"] = None
    gdf.loc[point_context, "context_radius_m"] = 500
    return gdf


def acquire_and_summarize(gdf: Any, start_month: str, end_month: str, output_dir: Path) -> dict[str, Any]:
    """Build monthly radiance summaries from NASA Black Marble through Earth Engine.

    NASA's daily VNP46A2 Black Marble collection is quality masked to persistent
    high-quality pixels (Mandatory_Quality_Flag == 0), reduced to a monthly
    median, and downloaded as two aligned Kenya raster tiles. The validity band
    keeps missing pixels distinct from genuine zero radiance.
    """
    recent_dates = month_dates(start_month, end_month)
    # The baseline is intentionally fixed and independently recorded; callers
    # can change it without changing the recent period.
    baseline_start = os.getenv("OSEAS_NTL_BASELINE_START_MONTH", "2012-01")
    baseline_end = os.getenv("OSEAS_NTL_BASELINE_END_MONTH", "2015-12")
    baseline_dates = month_dates(baseline_start, baseline_end)
    if not _initialize_earth_engine_with_retry(os.getenv("GEE_PROJECT_ID", "").strip()):
        raise RuntimeError("Earth Engine authentication failed; check GEE_PROJECT_ID and configured credentials")
    # Windows PostgreSQL can set PROJ_LIB to an incompatible extension build.
    # Point GDAL at the PROJ database bundled with the installed Rasterio wheel.
    rasterio_spec = importlib.util.find_spec("rasterio")
    if rasterio_spec and rasterio_spec.origin:
        rasterio_proj_data = Path(rasterio_spec.origin).parent / "proj_data"
        if (rasterio_proj_data / "proj.db").is_file():
            os.environ["PROJ_LIB"] = str(rasterio_proj_data)
            os.environ["PROJ_DATA"] = str(rasterio_proj_data)
    try:
        import ee
        import requests
        import rasterio
        from exactextract import exact_extract
        from rasterio.merge import merge
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
    except ImportError as error:
        raise RuntimeError("Install earthengine-api, rasterio, requests, and exactextract from requirements.txt") from error

    import numpy as np
    import pandas as pd

    output_dir.mkdir(parents=True, exist_ok=True)
    zone_keys = gdf["zone_key"].astype(str).tolist()
    if not zone_keys:
        raise RuntimeError("No OSEAS zones are available for Black Marble extraction")
    batch_size = int(os.getenv("OSEAS_NTL_BATCH_SIZE", "5000"))
    if not 500 <= batch_size <= 20000:
        raise ValueError("OSEAS_NTL_BATCH_SIZE must be between 500 and 20000")
    all_dates = recent_dates + baseline_dates
    counties = gdf.loc[gdf["zone_type"] == "county"]
    county_bounds = counties.total_bounds if not counties.empty else gdf.total_bounds
    matrix_path = output_dir / "ntl_monthly_radiance_v3.float32"
    radiance = np.memmap(matrix_path, dtype=np.float32, mode="w+", shape=(len(zone_keys), len(all_dates)))
    radiance[:] = np.nan
    valid_pixel_totals = np.zeros((len(zone_keys), 2), dtype=np.float64)
    valid_month_totals = np.zeros((len(zone_keys), 2), dtype=np.uint16)
    digest = hashlib.sha256()
    zone_geometry_digest = hashlib.sha256()
    product = "NASA/VIIRS/002/VNP46A2"
    quality_rule = "Mandatory_Quality_Flag == 0 (high-quality persistent lights); monthly median of daily values"
    pixel_size_degrees = 1 / 240
    radiance_scale_factor = 1.0  # Earth Engine catalog values are already in the band's radiance units.
    digest.update(json.dumps({"recent": [d.isoformat() for d in recent_dates],
      "baseline": [d.isoformat() for d in baseline_dates], "product": product,
      "quality_rule": quality_rule, "radiance_scale_factor": radiance_scale_factor}, sort_keys=True).encode())
    for zone_key, geometry in zip(zone_keys, gdf.geometry):
        digest.update(zone_key.encode())
        digest.update(bytes(geometry.wkb))
        zone_geometry_digest.update(zone_key.encode())
        zone_geometry_digest.update(bytes(geometry.wkb))
    checkpoint_signature = hashlib.sha256(json.dumps({
        "product": product,
        "recent": [d.isoformat() for d in recent_dates],
        "baseline": [d.isoformat() for d in baseline_dates],
        "quality_rule": quality_rule,
        "radiance_scale_factor": radiance_scale_factor,
        "pixel_size_degrees": pixel_size_degrees,
        "method": METHOD,
        "admin_boundary_simplification_tolerance_degrees": 0.0005,
        "asset_service_representative_point_simplification_tolerance_degrees": 0.0001,
        "asset_service_context_buffer_m": 500,
        "asset_service_buffer_quad_segments": 6,
        "zone_geometry_sha256": zone_geometry_digest.hexdigest(),
    }, sort_keys=True).encode()).hexdigest()
    checkpoint_dir = output_dir / "monthly_checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    variable = "DNB_BRDF_Corrected_NTL"
    source_image_counts: dict[str, int] = {}
    counties = gdf.loc[gdf["zone_type"] == "county"]
    west, south, east, north = counties.total_bounds if not counties.empty else gdf.total_bounds
    # Align download regions to the native 15 arc-second lat/lon grid. Two
    # half-width requests stay under Earth Engine's per-download size limit.
    west = -180 + math.floor((west + 180) / pixel_size_degrees) * pixel_size_degrees
    east = -180 + math.ceil((east + 180) / pixel_size_degrees) * pixel_size_degrees
    south = 90 - math.ceil((90 - south) / pixel_size_degrees) * pixel_size_degrees
    north = 90 - math.floor((90 - north) / pixel_size_degrees) * pixel_size_degrees
    middle = -180 + math.ceil(((west + east) / 2 + 180) / pixel_size_degrees) * pixel_size_degrees
    tile_bounds = [(west, south, middle, north), (middle, south, east, north)]
    http = requests.Session()
    http.mount("https://", HTTPAdapter(max_retries=Retry(total=5, connect=5, read=5,
        status=5, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}), respect_retry_after_header=True)))
    # Keep only the clipped monthly raster plus one small zone batch in memory.
    for column, observation_date in enumerate(all_dates):
        period = "recent" if column < len(recent_dates) else "baseline"
        period_column = column if period == "recent" else column - len(recent_dates)
        period_total = len(recent_dates) if period == "recent" else len(baseline_dates)
        checkpoint_path = checkpoint_dir / f"{observation_date:%Y%m}.npz"
        monthly_values = np.full(len(zone_keys), np.nan, dtype=np.float32)
        monthly_counts = np.zeros(len(zone_keys), dtype=np.uint32)
        restored = False
        if checkpoint_path.is_file():
            try:
                with np.load(checkpoint_path, allow_pickle=False) as checkpoint:
                    if (str(checkpoint["signature"].item()) == checkpoint_signature
                            and str(checkpoint["date"].item()) == observation_date.isoformat()
                            and checkpoint["values"].shape == (len(zone_keys),)
                            and checkpoint["pixel_counts"].shape == (len(zone_keys),)):
                        monthly_values = checkpoint["values"].astype(np.float32, copy=True)
                        monthly_counts = checkpoint["pixel_counts"].astype(np.uint32, copy=True)
                        source_image_counts[observation_date.isoformat()] = int(checkpoint["source_image_count"].item())
                        restored = True
            except (OSError, ValueError, TypeError, KeyError):
                restored = False
        print(f"Black Marble {period}: month {period_column + 1}/{period_total} ({observation_date:%Y-%m}); "
              f"zones={len(zone_keys)}; source={'checkpoint' if restored else 'NASA Earth Engine'}", flush=True)
        if not restored:
            month_cache = output_dir / "tile_cache" / f"{observation_date:%Y%m}"
            month_cache.mkdir(parents=True, exist_ok=True)
            month_end = (date(observation_date.year + (observation_date.month == 12),
                              1 if observation_date.month == 12 else observation_date.month + 1, 1))
            daily = ee.ImageCollection(product).filterDate(observation_date.isoformat(), month_end.isoformat())
            daily_count = int(_retry_remote_call("monthly catalog query", lambda: daily.size().getInfo()))
            source_image_counts[observation_date.isoformat()] = daily_count
            tile_paths: list[Path] = []
            if daily_count:
                def quality_screen(image: Any) -> Any:
                    quality = image.select("Mandatory_Quality_Flag")
                    return image.select(variable).updateMask(quality.eq(0)).rename("radiance")

                monthly_radiance = daily.map(quality_screen).median()
                valid_pixels = daily.map(lambda image: image.select("Mandatory_Quality_Flag").eq(0)
                                         .rename("valid")).sum().gt(0)
                export_image = monthly_radiance.updateMask(valid_pixels).unmask(0).rename("radiance")
                export_image = export_image.addBands(valid_pixels.unmask(0).toUint8().rename("valid"))
                for tile_index, bounds in enumerate(tile_bounds, start=1):
                    tile_path = month_cache / f"tile_{tile_index}.tif"
                    tile_paths.append(tile_path)
                    if tile_path.is_file() and tile_path.stat().st_size > 1024:
                        print(f"Black Marble {observation_date:%Y-%m}: reusing tile {tile_index}/2", flush=True)
                        continue
                    print(f"Black Marble {observation_date:%Y-%m}: requesting raster tile {tile_index}/2", flush=True)
                    url = _retry_remote_call("raster URL request", lambda: export_image.getDownloadURL({
                        "name": f"oseas_ntl_{observation_date:%Y%m}_tile_{tile_index}",
                        "crs": "EPSG:4326",
                        "crs_transform": [pixel_size_degrees, 0, -180, 0, -pixel_size_degrees, 90],
                        "region": list(bounds),
                        "format": "GEO_TIFF",
                    }))
                    response = _retry_remote_call("raster download", lambda: http.get(url, timeout=(30, 240)))
                    response.raise_for_status()
                    if not response.content[:4] in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
                        raise RuntimeError(f"Earth Engine returned a non-TIFF raster for {observation_date:%Y-%m}; content-type={response.headers.get('Content-Type', 'unknown')}")
                    temporary_tile = tile_path.with_suffix(".tif.part")
                    temporary_tile.write_bytes(response.content)
                    temporary_tile.replace(tile_path)
                    print(f"Black Marble {observation_date:%Y-%m}: tile {tile_index}/2 downloaded ({len(response.content):,} bytes)", flush=True)

                normalized_paths: list[Path] = []
                for tile_index, tile_path in enumerate(tile_paths, start=1):
                    normalized_path = month_cache / f"radiance_tile_{tile_index}.tif"
                    normalized_paths.append(normalized_path)
                    if normalized_path.is_file() and normalized_path.stat().st_size > 1024:
                        continue
                    with rasterio.open(tile_path) as source:
                        if source.count < 2:
                            raise RuntimeError("Earth Engine raster omitted the valid-observation mask band")
                        radiance_band = source.read(1).astype(np.float32)
                        validity_band = source.read(2) > 0
                        radiance_band[~validity_band] = np.nan
                        profile = source.profile.copy()
                        profile.update(driver="GTiff", count=1, dtype="float32", nodata=np.nan,
                                       compress="deflate", predictor=3)
                        with rasterio.open(normalized_path, "w", **profile) as target:
                            target.write(radiance_band, 1)
                    del radiance_band, validity_band
                mosaic_path = month_cache / "kenya_monthly_radiance.tif"
                with ExitStack() as stack:
                    sources = [stack.enter_context(rasterio.open(path)) for path in normalized_paths]
                    mosaic, transform = merge(sources, bounds=(west, south, east, north),
                        res=(pixel_size_degrees, pixel_size_degrees), nodata=np.nan,
                        dtype="float32", indexes=1, masked=True)
                    mosaic_values = np.ma.filled(mosaic, np.nan).astype(np.float32)
                    profile = sources[0].profile.copy()
                    profile.update(driver="GTiff", height=mosaic_values.shape[1], width=mosaic_values.shape[2],
                        transform=transform, count=1, dtype="float32", nodata=np.nan,
                        compress="deflate", predictor=3)
                    with rasterio.open(mosaic_path, "w", **profile) as target:
                        target.write(mosaic_values[0], 1)
                del mosaic, mosaic_values
                raster_input: Any = str(mosaic_path)
            else:
                print(f"Black Marble {observation_date:%Y-%m}: no daily images in NASA catalog; month remains missing", flush=True)
                raster_input = None
            for offset in range(0, len(zone_keys), batch_size):
                end_offset = min(offset + batch_size, len(zone_keys))
                zones = gdf.iloc[offset:end_offset].copy()
                context = zones["zone_type"].isin(["energy_asset", "critical_service"])
                context_indices = zones.index[context]
                if len(context_indices):
                    buffers = zones.loc[context_indices].to_crs("EPSG:6933").geometry.buffer(500, resolution=6).to_crs("EPSG:4326")
                    zones.loc[context_indices, "geometry"] = buffers
                    del buffers
                if raster_input is not None:
                    stats = exact_extract(rast=raster_input, vec=zones, ops=["mean", "count"], output="pandas")
                    if len(stats) != len(zones) or not {"mean", "count"}.issubset(stats.columns):
                        raise ValueError(f"Black Marble zonal statistics schema is unsupported; columns={list(stats.columns)}")
                    values = pd.to_numeric(stats["mean"], errors="coerce").to_numpy(dtype=np.float32)
                    counts = pd.to_numeric(stats["count"], errors="coerce").fillna(0).to_numpy(dtype=np.float64)
                    valid = np.isfinite(values) & (counts > 0)
                    row_indices = np.arange(offset, end_offset, dtype=np.int64)[valid]
                    monthly_values[row_indices] = values[valid]
                    monthly_counts[row_indices] = np.minimum(counts[valid], np.iinfo(np.uint32).max).astype(np.uint32)
                    del stats, values, counts
                else:
                    valid = np.zeros(len(zones), dtype=bool)
                print(f"Black Marble {observation_date:%Y-%m}: zones {end_offset:,}/{len(zone_keys):,}; "
                      f"quality-screened={int(valid.sum()):,}", flush=True)
                del zones
                if offset % (batch_size * 4) == 0:
                    gc.collect()
            recorded_source_count = daily_count if raster_input is not None else 0
            gc.collect()
            temporary_path = checkpoint_path.with_suffix(".npz.tmp")
            with temporary_path.open("wb") as checkpoint_file:
                np.savez_compressed(checkpoint_file, signature=np.asarray(checkpoint_signature),
                    date=np.asarray(observation_date.isoformat()), values=monthly_values,
                    pixel_counts=monthly_counts, source_image_count=np.asarray(recorded_source_count))
            temporary_path.replace(checkpoint_path)
            del raster_input
            shutil.rmtree(month_cache, ignore_errors=True)
            if month_cache.exists() and any(month_cache.iterdir()):
                print(f"Black Marble cleanup pending for {observation_date:%Y-%m}; source cache remains at {month_cache}", flush=True)
        valid = np.isfinite(monthly_values) & (monthly_counts > 0)
        row_indices = np.flatnonzero(valid)
        period_index = 0 if period == "recent" else 1
        valid_pixel_totals[row_indices, period_index] += monthly_counts[valid]
        valid_month_totals[row_indices, period_index] += 1
        # Ordered by sorted `zone_key`; hashes include every observed value and
        # valid-pixel count so changed monthly inputs cannot reuse old output IDs.
        digest.update(observation_date.isoformat().encode())
        digest.update(monthly_values.tobytes())
        digest.update(monthly_counts.tobytes())
        radiance[:, column] = monthly_values
        radiance.flush()
    digest.update(json.dumps({"zone_keys": zone_keys, "baseline_start": baseline_start,
      "baseline_end": baseline_end}, sort_keys=True).encode())
    del radiance
    http.close()
    return {"radiance_matrix_path": str(matrix_path), "valid_pixel_totals": valid_pixel_totals,
            "valid_month_totals": valid_month_totals,
            "recent_dates": recent_dates, "baseline_dates": baseline_dates,
            "baseline_start": baseline_start, "baseline_end": baseline_end,
            "source_image_counts": source_image_counts,
            "content_sha256": digest.hexdigest(), "requested_zone_count": len(gdf)}


def persist(connection: Any, gdf: Any, result: dict[str, Any]) -> dict[str, Any]:
    import numpy as np

    run_id = uuid.uuid4()
    digest = result["content_sha256"]
    start, end = result["recent_dates"][0], result["recent_dates"][-1]
    recent_count = len(result["recent_dates"])
    baseline_count = len(result["baseline_dates"])
    zone_count = result["requested_zone_count"]
    radiance = np.memmap(result["radiance_matrix_path"], dtype=np.float32, mode="r",
                         shape=(zone_count, recent_count + baseline_count))
    valid_pixel_totals = result["valid_pixel_totals"]
    valid_month_totals = result["valid_month_totals"]
    metadata = {"method": METHOD, "product": "NASA/VIIRS/002/VNP46A2 daily composites",
      "acquisition": "Google Earth Engine public catalog; monthly median from daily Black Marble images",
      "radiance_unit": RADIANCE_UNIT,
      "radiance_variable": "DNB_BRDF_Corrected_NTL; Earth Engine catalog values in nW cm-2 sr-1",
      "quality_rule": "Mandatory_Quality_Flag == 0 (high-quality persistent lights)",
      "recent_period": [start.isoformat(), end.isoformat()],
      "baseline_period": [result["baseline_start"], result["baseline_end"]],
      "source_image_counts_by_month": result.get("source_image_counts", {}),
      "radiance_scale_factor_applied_in_pipeline": 1.0,
      "requested_zone_count": zone_count, "content_sha256": digest,
      "interpretation": "Nighttime radiance is human-activity context; it does not establish electricity access, outage, or asset dependency.",
      "asset_service_context_buffer_m": 500,
      "asset_service_buffer_quad_segments": 6,
      "admin_boundary_simplification_tolerance_degrees": 0.0005,
      "asset_service_representative_point_simplification_tolerance_degrees": 0.0001,
      "zone_batch_size": int(os.getenv("OSEAS_NTL_BATCH_SIZE", "5000")),
      "spatial_support": "Administrative summaries use polygon zonal statistics; asset and service summaries use a 500 m equal-area buffer around a representative point."}
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", ("oseas_viirs_black_marble",))
        if not cur.fetchone()[0]:
            raise RuntimeError("Another VIIRS Black Marble processing run is active")
        cur.execute("""INSERT INTO datasets(dataset_key,name,source_type,source_reference,category,licence,attribution,is_optional)
          VALUES (%s,'NASA VIIRS Black Marble monthly nighttime radiance','google_earth_engine_catalog',
            'https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/VNP46A2','nighttime_lights',
            'NASA data policy','NASA VIIRS Land Science Investigator-led Processing System; DOI 10.5067/VIIRS/VNP46A2.002',TRUE)
          ON CONFLICT(dataset_key) DO UPDATE SET source_reference=EXCLUDED.source_reference,updated_at=NOW()""", (DATASET_KEY,))
        cur.execute("INSERT INTO ingestion_runs(id,pipeline_name,status,metadata) VALUES (%s,'oseas_viirs_black_marble','running',%s::jsonb)",
                    (run_id, json.dumps(metadata)))
    connection.commit()
    inserted = 0
    try:
        with connection.cursor() as cur:
            insert_sql = """INSERT INTO climate_observations
              (id,dataset_key,variable,value,unit,observed_at,geom,source_properties,processing_run_id)
              VALUES (%s,%s,%s,%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s::jsonb,%s)
              ON CONFLICT(id) DO UPDATE SET value=EXCLUDED.value,unit=EXCLUDED.unit,
                observed_at=EXCLUDED.observed_at,geom=EXCLUDED.geom,
                source_properties=EXCLUDED.source_properties,processing_run_id=EXCLUDED.processing_run_id"""
            pending: list[tuple[Any, ...]] = []
            for index, zone_row in enumerate(gdf.itertuples(index=False)):
                zone_key = str(zone_row.zone_key)
                current_values = radiance[index, :recent_count]
                baseline_values = radiance[index, recent_count:]
                current_valid = current_values[np.isfinite(current_values)]
                baseline_valid = baseline_values[np.isfinite(baseline_values)]
                recent_months = int(len(current_valid))
                baseline_months = int(len(baseline_valid))
                current = {
                    "median_radiance": float(np.median(current_valid)) if recent_months else None,
                    "mean_radiance": float(np.mean(current_valid)) if recent_months else None,
                    "valid_month_count": recent_months,
                    "requested_month_count": recent_count,
                    "valid_month_fraction": recent_months / recent_count,
                    "mean_valid_pixel_count": float(valid_pixel_totals[index, 0] / valid_month_totals[index, 0])
                        if valid_month_totals[index, 0] else None,
                }
                baseline = {
                    "median_radiance": float(np.median(baseline_valid)) if baseline_months else None,
                    "mean_radiance": float(np.mean(baseline_valid)) if baseline_months else None,
                    "valid_month_count": baseline_months,
                    "requested_month_count": baseline_count,
                    "valid_month_fraction": baseline_months / baseline_count,
                    "mean_valid_pixel_count": float(valid_pixel_totals[index, 1] / valid_month_totals[index, 1])
                        if valid_month_totals[index, 1] else None,
                }
                current_value = current["median_radiance"]
                baseline_value = baseline["median_radiance"]
                change = ((current_value - baseline_value) / abs(baseline_value) * 100
                          if current_value is not None and baseline_value not in (None, 0) else None)
                point = zone_row.geometry.representative_point()
                zone_type = str(zone_row.zone_type)
                zone_name = str(zone_row.zone_name) if zone_row.zone_name is not None else None
                context_radius = 500 if zone_type in {"energy_asset", "critical_service"} else None
                properties = {"zoneKey": zone_key, "zoneType": zone_type, "zoneName": zone_name,
                  "sourceFeatureId": str(zone_row.source_id), "method": METHOD, "recentPeriod": metadata["recent_period"],
                  "assetServiceBufferMeters": context_radius,
                  "baselinePeriod": metadata["baseline_period"], "qualityRule": metadata["quality_rule"],
                  "recentValidMonthCount": current.get("valid_month_count", 0),
                  "recentRequestedMonthCount": current.get("requested_month_count", recent_count),
                  "recentValidMonthFraction": current.get("valid_month_fraction"),
                  "recentMeanValidPixelCount": current.get("mean_valid_pixel_count"),
                  "baselineValidMonthCount": baseline.get("valid_month_count", 0),
                  "baselineRequestedMonthCount": baseline.get("requested_month_count", baseline_count),
                  "baselineValidMonthFraction": baseline.get("valid_month_fraction"),
                  "baselineMeanValidPixelCount": baseline.get("mean_valid_pixel_count"),
                  "adminBoundarySimplificationToleranceDegrees": 0.0005 if zone_type in {"county", "ward"} else None,
                  "assetServiceRepresentativePointSimplificationToleranceDegrees": 0.0001 if zone_type in {"energy_asset", "critical_service"} else None,
                  "contentSha256": digest,
                  "limitations": ["A true zero is retained only when a valid quality-screened observation exists; absent months are missing, not zero.",
                    "Nighttime radiance is not a household electrification measure, outage record, or electrical dependency.",
                    "Changes can reflect fires, gas flares, observation conditions, and human activity; they are investigation signals."]}
                values = [("NTL_RECENT_MEDIAN_RADIANCE", current.get("median_radiance"), end),
                          ("NTL_BASELINE_MEDIAN_RADIANCE", baseline.get("median_radiance"), date.fromisoformat(result["baseline_end"] + "-01")),
                          ("NTL_MEDIAN_CHANGE_PERCENT", change, end)]
                for variable, value, observed_at in values:
                    # Keep one current map row per zone and measure. Historical
                    # content checksums live in dataset_versions/run metadata.
                    output_id = stable_id(zone_key, variable)
                    source_properties = {**properties, "variable": variable,
                      "evidenceStatus": "assessed" if value is not None else "insufficient_data"}
                    pending.append((output_id, DATASET_KEY, variable, value,
                       "percent" if variable.endswith("PERCENT") else RADIANCE_UNIT,
                       observed_at, point.x, point.y, json.dumps(source_properties), run_id))
                if len(pending) >= 3000:
                    cur.executemany(insert_sql, pending)
                    inserted += len(pending)
                    pending.clear()
                    cur.execute("UPDATE ingestion_runs SET metadata=metadata||%s::jsonb WHERE id=%s",
                      (json.dumps({"persisted_observations": inserted}), run_id))
                    connection.commit()
                    print(f"Black Marble persistence: observation rows={inserted}", flush=True)
            if pending:
                cur.executemany(insert_sql, pending)
                inserted += len(pending)
                pending.clear()
                connection.commit()
                print(f"Black Marble persistence: observation rows={inserted}", flush=True)
            cur.execute("""INSERT INTO dataset_versions(dataset_key,source_reference,source_version,checksum,retrieved_at,
              observation_start,observation_end,feature_count,metadata,processing_run_id)
              SELECT %s,'NASA Black Marble VNP46A2 via Google Earth Engine','NASA/VIIRS/002/VNP46A2',%s,NOW(),%s,%s,%s,%s::jsonb,%s
              WHERE NOT EXISTS(SELECT 1 FROM dataset_versions WHERE dataset_key=%s AND checksum=%s)""",
              (DATASET_KEY, digest, start, end, inserted, json.dumps(metadata), run_id, DATASET_KEY, digest))
            cur.execute("INSERT INTO data_quality_checks(run_id,dataset_key,check_name,status,details) VALUES (%s,%s,'black_marble_quality_and_period_coverage','warning',%s::jsonb)",
              (run_id, DATASET_KEY, json.dumps({"outputRows": inserted, "requestedZones": zone_count,
                "recentMonths": recent_count, "baselineMonths": baseline_count,
                 "qualityRule": "Mandatory_Quality_Flag == 0", "scientificValidationStatus": "not_validated",
                 "monthsWithDailySourceImages": sum(count > 0 for count in result.get("source_image_counts", {}).values()),
                "validMonthCoverageDefinition": "monthly dates with at least one quality-screened contributing pixel / requested monthly dates",
                "assetAndServiceContextBufferMeters": 500})))
            cur.execute("UPDATE datasets SET last_ingested_at=NOW(),updated_at=NOW() WHERE dataset_key=%s", (DATASET_KEY,))
            cur.execute("UPDATE ingestion_runs SET status='completed',finished_at=NOW(),metadata=metadata||%s::jsonb WHERE id=%s",
              (json.dumps({"persisted_observations": inserted}), run_id))
        connection.commit()
    except Exception as error:
        connection.rollback()
        with connection.cursor() as cur:
            cur.execute("UPDATE ingestion_runs SET status=%s,finished_at=NOW(),error_message=%s,metadata=metadata||%s::jsonb WHERE id=%s",
              ("partial" if inserted else "failed", str(error)[:4000], json.dumps({"persisted_observations": inserted}), run_id))
        connection.commit()
        raise
    finally:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", ("oseas_viirs_black_marble",))
        connection.commit()
        del radiance
        gc.collect()
    return {"status": "completed", "run_id": str(run_id), "observation_rows": inserted,
            "zones": zone_count, "recent_months": recent_count,
            "baseline_months": baseline_count, "source_sha256": digest}


def _run_pipeline() -> int:
    start_month = os.getenv("OSEAS_NTL_START_MONTH", "").strip()
    end_month = os.getenv("OSEAS_NTL_END_MONTH", "").strip()
    if not start_month or not end_month:
        raise RuntimeError("Set OSEAS_NTL_START_MONTH and OSEAS_NTL_END_MONTH to 36 complete months available in the NASA Earth Engine catalog")
    if len(month_dates(start_month, end_month)) != 36:
        raise RuntimeError("OSEAS_NTL_START_MONTH and OSEAS_NTL_END_MONTH must select exactly 36 inclusive months")
    if not _initialize_earth_engine_with_retry(os.getenv("GEE_PROJECT_ID", "").strip()):
        raise RuntimeError("Earth Engine authentication failed; check GEE_PROJECT_ID and configured credentials")
    url = database_url()
    if not url:
        raise RuntimeError("DB_URL, DATABASE_URL, or SUPABASE_DB_URL is required")
    import psycopg
    with psycopg.connect(url, prepare_threshold=None, connect_timeout=20, options="-c statement_timeout=600000", application_name="oseas-black-marble-read") as connection:
        gdf = fetch_zones(connection)
    result = acquire_and_summarize(gdf, start_month, end_month, ROOT / "data" / "raw" / "viirs_black_marble")
    with psycopg.connect(url, prepare_threshold=None, connect_timeout=20, options="-c statement_timeout=600000", application_name="oseas-black-marble-write") as connection:
        output = persist(connection, gdf, result)
    print(json.dumps(output, indent=2))
    return 0


def main() -> int:
    lock_path = _acquire_local_process_lock()
    try:
        return _run_pipeline()
    finally:
        lock_path.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"NASA VIIRS Black Marble processing failed: {error}", file=sys.stderr)
        raise SystemExit(1)
