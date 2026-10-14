"""Acquire quality-screened NASA VIIRS Black Marble and persist map-ready context."""

from __future__ import annotations

import hashlib
import json
import os
import gc
import shutil
import sys
import uuid
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from oseas.config import database_url, nasa_earthdata_token  # noqa: E402

DATASET_KEY = "nasa_viirs_black_marble_monthly"
METHOD = "viirs_black_marble_quality_screened_period_median_v1"
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


def fetch_zones(connection: Any) -> tuple[Any, dict[str, dict[str, Any]]]:
    """Load county/ward polygons and asset/service points for zonal extraction."""
    import geopandas as gpd
    from shapely import wkb

    with connection.cursor() as cur:
        cur.execute("""SELECT 'admin:'||id::text,unit_level,name,ST_AsBinary(geom),id::text
                      FROM administrative_units WHERE unit_level IN ('county','ward')
                      UNION ALL
                      SELECT 'asset:'||id::text,'energy_asset',COALESCE(name,asset_type),
                             ST_AsBinary(ST_PointOnSurface(geom)),id::text FROM energy_assets
                      UNION ALL
                      SELECT 'service:'||id::text,'critical_service',COALESCE(name,service_type),
                             ST_AsBinary(ST_PointOnSurface(geom)),id::text FROM critical_services""")
        records = cur.fetchall()
    if not records:
        raise RuntimeError("No administrative, asset, or critical-service geometries are available for Black Marble extraction")
    features = [{"zone_key": row[0], "zone_type": row[1], "zone_name": row[2], "source_id": row[4], "geometry": wkb.loads(bytes(row[3]))}
                for row in records]
    gdf = gpd.GeoDataFrame(features, geometry="geometry", crs="EPSG:4326")
    gdf = gdf.sort_values("zone_key").reset_index(drop=True)
    point_context = gdf["zone_type"].isin(["energy_asset", "critical_service"])
    if point_context.any():
        # Point-on-surface samples are expanded to an explicit 500 m context area.
        buffered = gdf.loc[point_context].to_crs("EPSG:6933").geometry.buffer(500).to_crs("EPSG:4326")
        gdf.loc[point_context, "geometry"] = buffered
        for feature in features:
            if feature["zone_type"] in {"energy_asset", "critical_service"}:
                feature["context_radius_m"] = 500
    return gdf, {
        item["zone_key"]: {key: value for key, value in item.items() if key != "geometry"} for item in features}


def acquire_and_summarize(gdf: Any, start_month: str, end_month: str, token: str, output_dir: Path) -> dict[str, Any]:
    if not token:
        raise RuntimeError("NASA_EARTHDATA_TOKEN (or LAAD_TOKEN_NASA) is required for Black Marble VNP46A3 downloads")
    recent_dates = month_dates(start_month, end_month)
    # The baseline is intentionally fixed and independently recorded; callers
    # can change it without changing the recent period.
    baseline_start = os.getenv("OSEAS_NTL_BASELINE_START_MONTH", "2012-01")
    baseline_end = os.getenv("OSEAS_NTL_BASELINE_END_MONTH", "2015-12")
    baseline_dates = month_dates(baseline_start, baseline_end)
    try:
        from blackmarble import bm_extract
    except ImportError as error:
        raise RuntimeError("Install BlackMarblePy and its geospatial dependencies with `python -m pip install -r requirements.txt`") from error

    output_dir.mkdir(parents=True, exist_ok=True)
    common = {"product_id": "VNP46A3", "token": token, "aggfunc": ["mean", "count"],
              "variable": "NearNadir_Composite_Snow_Free", "drop_values_by_quality_flag": [1, 2, 255],
              "check_all_tiles_exist": True, "output_skip_if_exists": True}
    import numpy as np
    import pandas as pd

    zone_keys = gdf["zone_key"].astype(str).tolist()
    zone_index = {zone_key: index for index, zone_key in enumerate(zone_keys)}
    all_dates = recent_dates + baseline_dates
    radiance = np.full((len(zone_keys), len(all_dates)), np.nan, dtype=np.float32)
    valid_pixel_totals = np.zeros((len(zone_keys), 2), dtype=np.float64)
    valid_month_totals = np.zeros((len(zone_keys), 2), dtype=np.uint16)
    digest = hashlib.sha256()
    zone_geometry_digest = hashlib.sha256()
    digest.update(json.dumps({"recent": [d.isoformat() for d in recent_dates],
      "baseline": [d.isoformat() for d in baseline_dates], "product": "VNP46A3 C2.0",
      "quality_flags_excluded": [1, 2, 255]}, sort_keys=True).encode())
    for zone_key, geometry in zip(zone_keys, gdf.geometry):
        digest.update(zone_key.encode())
        digest.update(bytes(geometry.wkb))
        zone_geometry_digest.update(zone_key.encode())
        zone_geometry_digest.update(bytes(geometry.wkb))
    checkpoint_signature = hashlib.sha256(json.dumps({
        "product": "VNP46A3 C2.0",
        "recent": [d.isoformat() for d in recent_dates],
        "baseline": [d.isoformat() for d in baseline_dates],
        "quality_flags_excluded": [1, 2, 255],
        "zone_geometry_sha256": zone_geometry_digest.hexdigest(),
    }, sort_keys=True).encode()).hexdigest()
    checkpoint_dir = output_dir / "monthly_checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    # One monthly extraction at a time bounds raster and tabular working memory;
    # the numeric result matrix is fixed-size and compact even at national scale.
    for column, observation_date in enumerate(all_dates):
        period = "recent" if column < len(recent_dates) else "baseline"
        period_column = column if period == "recent" else column - len(recent_dates)
        period_total = len(recent_dates) if period == "recent" else len(baseline_dates)
        checkpoint_path = checkpoint_dir / f"{observation_date:%Y%m}.json"
        monthly_values = np.full(len(zone_keys), np.nan, dtype=np.float32)
        monthly_counts = np.zeros(len(zone_keys), dtype=np.uint32)
        restored = False
        if checkpoint_path.is_file():
            try:
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                if checkpoint.get("signature") == checkpoint_signature and checkpoint.get("date") == observation_date.isoformat():
                    stored_values = checkpoint.get("values", {})
                    stored_counts = checkpoint.get("pixel_counts", {})
                    if set(stored_values) == set(zone_keys) and set(stored_counts) == set(zone_keys):
                        monthly_values = np.asarray([np.nan if stored_values[key] is None else stored_values[key]
                                                     for key in zone_keys], dtype=np.float32)
                        monthly_counts = np.asarray([stored_counts[key] for key in zone_keys], dtype=np.uint32)
                        restored = True
            except (OSError, ValueError, TypeError, KeyError):
                restored = False
        print(f"Black Marble {period}: month {period_column + 1}/{period_total} ({observation_date:%Y-%m}); "
              f"zones={len(zone_keys)}; source={'checkpoint' if restored else 'NASA LAADS'}", flush=True)
        if not restored:
            month_cache = output_dir / "tile_cache" / f"{observation_date:%Y%m}"
            month_cache.mkdir(parents=True, exist_ok=True)
            frame = bm_extract(gdf, date_range=[observation_date], output_directory=month_cache, **common)
            date_column, value_column, count_column = _extract_columns(frame)
            frame[date_column] = pd.to_datetime(frame[date_column]).dt.date
            frame = frame[frame[date_column] == observation_date]
            indices = frame["zone_key"].astype(str).map(zone_index)
            values = pd.to_numeric(frame[value_column], errors="coerce").to_numpy(dtype=np.float64)
            counts = (pd.to_numeric(frame[count_column], errors="coerce").fillna(0).to_numpy(dtype=np.float64)
                      if count_column else np.where(np.isfinite(values), 1.0, 0.0))
            valid = indices.notna().to_numpy() & np.isfinite(values) & (counts > 0)
            row_indices = indices[valid].to_numpy(dtype=np.int64)
            monthly_values[row_indices] = values[valid].astype(np.float32)
            monthly_counts[row_indices] = np.minimum(counts[valid], np.iinfo(np.uint32).max).astype(np.uint32)
            # Save each month atomically so a stopped machine can resume without
            # re-downloading already summarized full-resolution tiles.
            checkpoint = {"signature": checkpoint_signature, "date": observation_date.isoformat(),
              "values": {key: (float(value) if np.isfinite(value) else None)
                         for key, value in zip(zone_keys, monthly_values)},
              "pixel_counts": {key: int(value) for key, value in zip(zone_keys, monthly_counts)}}
            temporary_path = checkpoint_path.with_suffix(".json.tmp")
            temporary_path.write_text(json.dumps(checkpoint, separators=(",", ":")), encoding="utf-8")
            temporary_path.replace(checkpoint_path)
            del frame
            gc.collect()
            shutil.rmtree(month_cache, ignore_errors=True)
            if month_cache.exists() and any(month_cache.iterdir()):
                print(f"Black Marble cleanup pending for {observation_date:%Y-%m}; source cache remains at {month_cache}", flush=True)
        valid = np.isfinite(monthly_values) & (monthly_counts > 0)
        row_indices = np.flatnonzero(valid)
        radiance[row_indices, column] = monthly_values[valid]
        period_index = 0 if period == "recent" else 1
        valid_pixel_totals[row_indices, period_index] += monthly_counts[valid]
        valid_month_totals[row_indices, period_index] += 1
        # Ordered by sorted `zone_key`; hashes include every observed value and
        # valid-pixel count so changed monthly inputs cannot reuse old output IDs.
        digest.update(observation_date.isoformat().encode())
        digest.update(monthly_values.tobytes())
        digest.update(monthly_counts.tobytes())

    features = []
    for index, zone_key in enumerate(zone_keys):
        current_values = radiance[index, :len(recent_dates)]
        baseline_values = radiance[index, len(recent_dates):]
        current_valid = current_values[np.isfinite(current_values)]
        baseline_valid = baseline_values[np.isfinite(baseline_values)]
        current = {"median_radiance": float(np.median(current_valid)) if len(current_valid) else None,
          "mean_radiance": float(np.mean(current_valid)) if len(current_valid) else None,
          "valid_month_count": int(len(current_valid)), "requested_month_count": len(recent_dates),
          "valid_month_fraction": len(current_valid) / len(recent_dates),
          "mean_valid_pixel_count": float(valid_pixel_totals[index, 0] / valid_month_totals[index, 0]) if valid_month_totals[index, 0] else None}
        baseline = {"median_radiance": float(np.median(baseline_valid)) if len(baseline_valid) else None,
          "mean_radiance": float(np.mean(baseline_valid)) if len(baseline_valid) else None,
          "valid_month_count": int(len(baseline_valid)), "requested_month_count": len(baseline_dates),
          "valid_month_fraction": len(baseline_valid) / len(baseline_dates),
          "mean_valid_pixel_count": float(valid_pixel_totals[index, 1] / valid_month_totals[index, 1]) if valid_month_totals[index, 1] else None}
        current_value = current["median_radiance"]
        baseline_value = baseline["median_radiance"]
        change = ((current_value - baseline_value) / abs(baseline_value) * 100
                  if current_value is not None and baseline_value not in (None, 0) else None)
        features.append({"zone_key": zone_key, "recent": current, "baseline": baseline,
                         "change_pct": change})
    digest.update(json.dumps({"zone_keys": zone_keys, "baseline_start": baseline_start,
      "baseline_end": baseline_end}, sort_keys=True).encode())
    return {"features": features, "recent_dates": recent_dates, "baseline_dates": baseline_dates,
            "baseline_start": baseline_start, "baseline_end": baseline_end,
            "content_sha256": digest.hexdigest(), "requested_zone_count": len(gdf)}


def persist(connection: Any, gdf: Any, zone_metadata: dict[str, dict[str, Any]], result: dict[str, Any]) -> dict[str, Any]:
    run_id = uuid.uuid4()
    digest = result["content_sha256"]
    start, end = result["recent_dates"][0], result["recent_dates"][-1]
    metadata = {"method": METHOD, "product": "VNP46A3 Collection 2.0", "radiance_unit": RADIANCE_UNIT,
      "radiance_variable": "NearNadir_Composite_Snow_Free", "recent_period": [start.isoformat(), end.isoformat()],
      "baseline_period": [result["baseline_start"], result["baseline_end"]], "quality_flags_excluded": [1, 2, 255],
      "requested_zone_count": result["requested_zone_count"], "content_sha256": digest,
      "interpretation": "Nighttime radiance is human-activity context; it does not establish electricity access, outage, or asset dependency.",
      "asset_service_context_buffer_m": 500,
      "spatial_support": "Administrative summaries use polygon zonal statistics; asset and service summaries use a 500 m equal-area buffer around a representative point."}
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", ("oseas_viirs_black_marble",))
        if not cur.fetchone()[0]:
            raise RuntimeError("Another VIIRS Black Marble processing run is active")
        cur.execute("""INSERT INTO datasets(dataset_key,name,source_type,source_reference,category,licence,attribution,is_optional)
          VALUES (%s,'NASA VIIRS Black Marble monthly nighttime radiance','nasa_laads_api',
            'https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/VNP46A3','nighttime_lights',
            'NASA data policy','NASA VIIRS Land Science Investigator-led Processing System; DOI 10.5067/VIIRS/VNP46A3.002',TRUE)
          ON CONFLICT(dataset_key) DO UPDATE SET source_reference=EXCLUDED.source_reference,updated_at=NOW()""", (DATASET_KEY,))
        cur.execute("INSERT INTO ingestion_runs(id,pipeline_name,status,metadata) VALUES (%s,'oseas_viirs_black_marble','running',%s::jsonb)",
                    (run_id, json.dumps(metadata)))
    connection.commit()
    inserted = 0
    gdf_by_zone = dict(zip(gdf["zone_key"].astype(str), gdf.geometry))
    try:
        with connection.cursor() as cur:
            for feature in result["features"]:
                zone_key = feature["zone_key"]
                zone = zone_metadata.get(zone_key)
                if not zone:
                    continue
                current = feature["recent"]
                baseline = feature["baseline"]
                geom = gdf_by_zone[zone_key]
                point = geom.representative_point()
                properties = {"zoneKey": zone_key, "zoneType": zone["zone_type"], "zoneName": zone["zone_name"],
                  "sourceFeatureId": zone["source_id"], "method": METHOD, "recentPeriod": metadata["recent_period"],
                  "assetServiceBufferMeters": zone.get("context_radius_m"),
                  "baselinePeriod": metadata["baseline_period"], "qualityFlagsExcluded": [1, 2, 255],
                  "recentValidMonthCount": current.get("valid_month_count", 0),
                  "recentRequestedMonthCount": current.get("requested_month_count", len(result["recent_dates"])),
                  "recentValidMonthFraction": current.get("valid_month_fraction"),
                  "recentMeanValidPixelCount": current.get("mean_valid_pixel_count"),
                  "baselineValidMonthCount": baseline.get("valid_month_count", 0),
                  "baselineRequestedMonthCount": baseline.get("requested_month_count", len(result["baseline_dates"])),
                  "baselineValidMonthFraction": baseline.get("valid_month_fraction"),
                  "baselineMeanValidPixelCount": baseline.get("mean_valid_pixel_count"),
                  "contentSha256": digest,
                  "limitations": ["A true zero is retained only when a valid quality-screened observation exists; absent months are missing, not zero.",
                    "Nighttime radiance is not a household electrification measure, outage record, or electrical dependency.",
                    "Changes can reflect fires, gas flares, observation conditions, and human activity; they are investigation signals."]}
                values = [("NTL_RECENT_MEDIAN_RADIANCE", current.get("median_radiance"), end),
                          ("NTL_BASELINE_MEDIAN_RADIANCE", baseline.get("median_radiance"), date.fromisoformat(result["baseline_end"] + "-01")),
                          ("NTL_MEDIAN_CHANGE_PERCENT", feature["change_pct"], end)]
                for variable, value, observed_at in values:
                    # Keep one current map row per zone and measure. Historical
                    # content checksums live in dataset_versions/run metadata.
                    output_id = stable_id(zone_key, variable)
                    source_properties = {**properties, "variable": variable,
                      "evidenceStatus": "assessed" if value is not None else "insufficient_data"}
                    cur.execute("""INSERT INTO climate_observations
                      (id,dataset_key,variable,value,unit,observed_at,geom,source_properties,processing_run_id)
                      VALUES (%s,%s,%s,%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s::jsonb,%s)
                      ON CONFLICT(id) DO UPDATE SET value=EXCLUDED.value,unit=EXCLUDED.unit,
                        observed_at=EXCLUDED.observed_at,geom=EXCLUDED.geom,
                        source_properties=EXCLUDED.source_properties,processing_run_id=EXCLUDED.processing_run_id""",
                      (output_id, DATASET_KEY, variable, value,
                       "percent" if variable.endswith("PERCENT") else RADIANCE_UNIT,
                       observed_at, point.x, point.y, json.dumps(source_properties), run_id))
                    inserted += 1
                if inserted and inserted % 3000 == 0:
                    cur.execute("UPDATE ingestion_runs SET metadata=metadata||%s::jsonb WHERE id=%s",
                      (json.dumps({"persisted_observations": inserted}), run_id))
                    connection.commit()
                    print(f"Black Marble persistence: observation rows={inserted}", flush=True)
            cur.execute("""INSERT INTO dataset_versions(dataset_key,source_reference,source_version,checksum,retrieved_at,
              observation_start,observation_end,feature_count,metadata,processing_run_id)
              SELECT %s,'NASA LAADS VNP46A3 Collection 2.0','VNP46A3 C2.0',%s,NOW(),%s,%s,%s,%s::jsonb,%s
              WHERE NOT EXISTS(SELECT 1 FROM dataset_versions WHERE dataset_key=%s AND checksum=%s)""",
              (DATASET_KEY, digest, start, end, inserted, json.dumps(metadata), run_id, DATASET_KEY, digest))
            cur.execute("INSERT INTO data_quality_checks(run_id,dataset_key,check_name,status,details) VALUES (%s,%s,'black_marble_quality_and_period_coverage','warning',%s::jsonb)",
              (run_id, DATASET_KEY, json.dumps({"outputRows": inserted, "requestedZones": result["requested_zone_count"],
                "recentMonths": len(result["recent_dates"]), "baselineMonths": len(result["baseline_dates"]),
                "qualityFlagsExcluded": [1, 2, 255], "scientificValidationStatus": "not_validated",
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
    return {"status": "completed", "run_id": str(run_id), "observation_rows": inserted,
            "zones": result["requested_zone_count"], "recent_months": len(result["recent_dates"]),
            "baseline_months": len(result["baseline_dates"]), "source_sha256": digest}


def main() -> int:
    start_month = os.getenv("OSEAS_NTL_START_MONTH", "").strip()
    end_month = os.getenv("OSEAS_NTL_END_MONTH", "").strip()
    token = nasa_earthdata_token()
    if not start_month or not end_month:
        raise RuntimeError("Set OSEAS_NTL_START_MONTH and OSEAS_NTL_END_MONTH only after reviewing the NASA LAADS product manifest for complete Kenya months")
    if len(month_dates(start_month, end_month)) != 36:
        raise RuntimeError("OSEAS_NTL_START_MONTH and OSEAS_NTL_END_MONTH must select exactly 36 inclusive months")
    if not token:
        raise RuntimeError("NASA_EARTHDATA_TOKEN (or LAAD_TOKEN_NASA) is required for NASA LAADS VNP46A3 retrieval")
    url = database_url()
    if not url:
        raise RuntimeError("DB_URL, DATABASE_URL, or SUPABASE_DB_URL is required")
    import psycopg
    with psycopg.connect(url, prepare_threshold=None, connect_timeout=20, options="-c statement_timeout=600000", application_name="oseas-black-marble-read") as connection:
        gdf, zone_metadata = fetch_zones(connection)
    result = acquire_and_summarize(gdf, start_month, end_month, token, ROOT / "data" / "raw" / "viirs_black_marble")
    with psycopg.connect(url, prepare_threshold=None, connect_timeout=20, options="-c statement_timeout=600000", application_name="oseas-black-marble-write") as connection:
        output = persist(connection, gdf, zone_metadata, result)
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"NASA VIIRS Black Marble processing failed: {error}", file=sys.stderr)
        raise SystemExit(1)
