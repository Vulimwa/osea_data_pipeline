"""Acquire NASA POWER daily air temperature and persist coarse heat indicators."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from oseas.config import database_url  # noqa: E402

NAMESPACE = uuid.UUID("32a11fb6-bace-4e09-9373-fdf4d5460f87")
DATASET_KEY = "nasa_power_daily"
API_ROOT = "https://power.larc.nasa.gov/api/temporal"
KENYA_BBOX = {"latitude-min": -5.1, "latitude-max": 5.1, "longitude-min": 33.5, "longitude-max": 42.0}
METHOD = "nasa_power_t2m_max_monthly_climatology_screen_v1"


def fetch_json(url: str, params: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    response = requests.get(url, params=params, timeout=(20, 180), headers={"User-Agent": "OSEAS climate evidence pipeline/1.0"})
    response.raise_for_status()
    raw = response.content
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        raise ValueError("NASA POWER response is missing its regional GeoJSON features")
    return data, raw


def _id(*parts: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, "|".join(parts))


def acquire(start: date, end: date, threshold_c: float) -> dict[str, Any]:
    if end < start:
        raise ValueError("Heat period end must be on or after start")
    if (end - start).days > 366:
        raise ValueError("Bound NASA POWER heat acquisition to at most 367 daily observations per run")
    base = {**KENYA_BBOX, "parameters": "T2M_MAX", "community": "SB", "format": "JSON"}
    print(f"NASA POWER heat: requesting Kenya regional daily T2M_MAX {start} through {end} (inclusive)", flush=True)
    daily, daily_raw = fetch_json(f"{API_ROOT}/daily/regional", {
        **base, "start": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"), "time-standard": "UTC"})
    print("NASA POWER heat: requesting monthly climatology baseline (NASA POWER precomputed period)", flush=True)
    climate, climate_raw = fetch_json(f"{API_ROOT}/climatology/regional", base)
    header = climate.get("header", {})
    baseline = f"{header.get('start', 'unknown')}..{header.get('end', 'unknown')}"
    daily_features = daily["features"]
    climate_by_cell = {
        (round(feature["geometry"]["coordinates"][0], 5), round(feature["geometry"]["coordinates"][1], 5)):
            feature.get("properties", {}).get("parameter", {}).get("T2M_MAX", {})
        for feature in climate["features"]
    }
    expected_dates = []
    cursor = start
    while cursor <= end:
        expected_dates.append(cursor.strftime("%Y%m%d"))
        cursor += timedelta(days=1)
    content_hash = hashlib.sha256(daily_raw + b"\n" + climate_raw).hexdigest()
    cells = []
    records = []
    for feature in daily_features:
        coordinates = feature.get("geometry", {}).get("coordinates", [])
        if len(coordinates) < 2:
            continue
        lon, lat = round(float(coordinates[0]), 5), round(float(coordinates[1]), 5)
        daily_values = feature.get("properties", {}).get("parameter", {}).get("T2M_MAX", {})
        normals = climate_by_cell.get((lon, lat), {})
        values = []
        anomalies = []
        for day in expected_dates:
            value = daily_values.get(day)
            if value is None or float(value) <= -900:
                continue
            value = float(value)
            month = date(int(day[:4]), int(day[4:6]), int(day[6:8])).strftime("%b").upper()
            normal = normals.get(month)
            anomaly = value - float(normal) if normal is not None and float(normal) > -900 else None
            values.append((day, value, anomaly))
            records.append((lon, lat, day, value, anomaly))
        if values:
            valid_fraction = len(values) / len(expected_dates)
            hot_days = sum(value >= threshold_c for _, value, _ in values)
            mean_anomaly = (sum(item[2] for item in values if item[2] is not None) /
                            max(1, sum(item[2] is not None for item in values)))
            cells.append({"lon": lon, "lat": lat, "valid_fraction": valid_fraction, "valid_days": len(values),
                          "hot_days": hot_days, "max_t2m_c": max(value for _, value, _ in values),
                          "mean_monthly_climatology_anomaly_c": mean_anomaly})
    if not cells:
        raise ValueError("NASA POWER returned no valid daily T2M_MAX values for the configured Kenya extent/period")
    return {"start": start, "end": end, "threshold_c": threshold_c, "baseline": baseline,
            "baseline_period": {"start": header.get("start"), "end": header.get("end")},
            "daily_response": daily, "climatology_response": climate,
            "content_sha256": content_hash, "daily_records": records, "cells": cells,
            "expected_days": len(expected_dates), "method": METHOD,
            "limitations": ["NASA POWER T2M_MAX is gridded near-surface air temperature, not Landsat land-surface temperature.",
              "Regional grid spacing is 0.5 degrees (~50 km); this is coarse exposure context, not asset-scale microclimate.",
              "Monthly climatology anomaly compares daily maximum air temperature with the provider monthly climatology.",
              "Hot-day threshold is a configurable screening threshold, not a universal equipment-failure or health threshold.",
              "An exceedance indicates modeled heat exposure only and does not establish asset damage or outage."]}


def persist(connection: Any, result: dict[str, Any]) -> dict[str, Any]:
    run_id = uuid.uuid4()
    start, end = result["start"], result["end"]
    threshold = result["threshold_c"]
    digest = result["content_sha256"]
    reference = f"{API_ROOT}/daily/regional; {API_ROOT}/climatology/regional"
    metadata = {"method": METHOD, "input_content_sha256": digest, "period_start": start.isoformat(),
                "period_end": end.isoformat(), "threshold_c": threshold, "baseline_period": result["baseline_period"],
                "grid_cell_count": len(result["cells"]), "daily_records": len(result["daily_records"]),
                "limitation": result["limitations"]}
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", ("oseas_nasa_power_heat",))
        if not cur.fetchone()[0]:
            raise RuntimeError("Another NASA POWER heat run is active")
        cur.execute("""INSERT INTO datasets(dataset_key,name,source_type,source_reference,category,licence,attribution,is_optional)
          VALUES (%s,'NASA POWER daily gridded maximum air temperature','nasa_power_api',%s,'climate','NASA POWER terms','NASA POWER; cite POWER documentation',TRUE)
          ON CONFLICT(dataset_key) DO UPDATE SET source_reference=EXCLUDED.source_reference,updated_at=NOW()""",
          (DATASET_KEY, reference))
        cur.execute("INSERT INTO ingestion_runs(id,pipeline_name,status,metadata) VALUES (%s,'oseas_nasa_power_heat','running',%s::jsonb)",
                    (run_id, json.dumps(metadata)))
    connection.commit()
    try:
        observation_count = 0
        with connection.cursor() as cur:
            for offset in range(0, len(result["daily_records"]), 2000):
                batch = result["daily_records"][offset:offset + 2000]
                cur.executemany("""INSERT INTO climate_observations
                  (id,dataset_key,variable,value,unit,observed_at,geom,source_properties,processing_run_id)
                  VALUES (%s,%s,%s,%s,'degC',%s::date,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s::jsonb,%s)
                  ON CONFLICT(id) DO NOTHING""",
                  [(_id(digest, str(lon), str(lat), day, "t2m_max"), DATASET_KEY, "T2M_MAX", value, day,
                    lon, lat, json.dumps({"source": "NASA POWER", "parameter": "T2M_MAX", "timeStandard": "UTC",
                      "method": METHOD, "monthlyClimatologyAnomalyC": anomaly, "inputSha256": digest,
                      "baselinePeriod": result["baseline_period"]}), run_id)
                   for lon, lat, day, value, anomaly in batch])
                observation_count += len(batch)
                print(f"NASA POWER heat persistence: daily records={min(offset + len(batch), len(result['daily_records']))}/{len(result['daily_records'])}", flush=True)
            for cell in result["cells"]:
                hazard_id = _id(digest, f"{cell['lon']:.5f}", f"{cell['lat']:.5f}", start.isoformat(), end.isoformat(),
                                str(threshold), "heat-grid-cell")
                cell_metadata = {"method": METHOD, "threshold_c": threshold, "hot_days": cell["hot_days"],
                  "valid_days": cell["valid_days"], "expected_days": result["expected_days"],
                  "valid_data_fraction": cell["valid_fraction"], "max_t2m_c": cell["max_t2m_c"],
                  "mean_monthly_climatology_anomaly_c": cell["mean_monthly_climatology_anomaly_c"],
                  "grid_spacing_degrees": 0.5, "baseline_period": result["baseline_period"],
                  "scientific_validation_status": "not_validated", "limitations": result["limitations"]}
                cur.execute("""INSERT INTO hazard_events
                  (id,hazard_type,evidence_kind,dataset_key,event_start,event_end,source_reference,confidence,geom,metadata,processing_run_id)
                  VALUES (%s,'heat','modeled',%s,%s,%s,%s,NULL,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s::jsonb,%s)
                  ON CONFLICT(id) DO NOTHING""",
                  (hazard_id, DATASET_KEY, start, end, reference, cell["lon"], cell["lat"], json.dumps(cell_metadata), run_id))
                cur.execute("""INSERT INTO climate_observations
                  (id,dataset_key,variable,value,unit,observed_at,geom,source_properties,processing_run_id)
                  VALUES (%s,%s,%s,%s,'day',%s::date,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s::jsonb,%s)
                  ON CONFLICT(id) DO NOTHING""",
                  (_id(digest, str(cell["lon"]), str(cell["lat"]), start.isoformat(), end.isoformat(),
                       str(threshold), "heat_days"), DATASET_KEY, f"HEAT_DAYS_GE_{threshold:g}C", cell["hot_days"], end,
                   cell["lon"], cell["lat"], json.dumps(cell_metadata), run_id))
            cur.execute("""INSERT INTO asset_hazard_exposure
              (id,energy_asset_id,hazard_event_id,hazard_type,assessment_period_start,assessment_period_end,
               exposure_status,distance_m,evidence_kind,confidence,provenance,processing_run_id)
              SELECT md5(a.id::text||h.id::text)::uuid,a.id,h.id,'heat',%s,%s,
                CASE WHEN (h.metadata->>'valid_data_fraction')::double precision < 0.8 THEN 'unknown'
                     WHEN (h.metadata->>'hot_days')::integer > 0 THEN 'exposed' ELSE 'not_exposed' END,
                ST_Distance(a.geom::geography,h.geom::geography),'modeled',NULL,
                jsonb_build_object('method',%s,'thresholdC',%s,'gridSpacingDegrees',0.5,
                  'matchingRule','nearest NASA POWER regional grid cell within 45 km',
                  'limitation','Coarse modeled air-temperature context; no asset damage inference.'),
                %s
              FROM energy_assets a
              CROSS JOIN LATERAL (
                SELECT id,geom,metadata FROM hazard_events
                WHERE processing_run_id=%s AND hazard_type='heat'
                  AND ST_DWithin(a.geom::geography,geom::geography,45000)
                ORDER BY a.geom <-> geom LIMIT 1
              ) h
              ON CONFLICT(id) DO NOTHING""",
              (start, end, METHOD, threshold, run_id, run_id))
            exposure_count = cur.rowcount
            coverage_geom = json.dumps({"type": "Polygon", "coordinates": [[
              [33.5, -5.1], [42.0, -5.1], [42.0, 5.1], [33.5, 5.1], [33.5, -5.1]]]})
            cur.execute("""INSERT INTO spatial_coverage_assessments
              (dataset_key,processing_run_id,reporting_unit_level,hazard_type,evidence_kind,observation_start,observation_end,
               coverage_status,area_coverage_fraction,valid_data_fraction,observation_footprint,quality_mask,
               validation_status,limitations,provenance)
              VALUES (%s,%s,'national','heat','modeled',%s,%s,'partially_assessed',NULL,%s,
                ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s::jsonb,'not_validated',%s::jsonb,%s::jsonb)""",
              (DATASET_KEY, run_id, start, end, sum(cell["valid_fraction"] for cell in result["cells"]) / len(result["cells"]),
               coverage_geom, json.dumps({"gridCells": len(result["cells"]), "expectedDays": result["expected_days"],
                                         "dailyObservations": len(result["daily_records"])}),
               json.dumps(result["limitations"]), json.dumps({"method": METHOD, "inputSha256": digest})))
            cur.execute("""INSERT INTO dataset_versions(dataset_key,source_reference,source_version,checksum,retrieved_at,
              observation_start,observation_end,feature_count,metadata,processing_run_id)
              SELECT %s,%s,%s,%s,NOW(),%s,%s,%s,%s::jsonb,%s WHERE NOT EXISTS
                (SELECT 1 FROM dataset_versions WHERE dataset_key=%s AND checksum=%s)""",
              (DATASET_KEY, reference, f"NASA POWER T2M_MAX {start}/{end}", digest, start, end,
               len(result["daily_records"]), json.dumps({"baseline_period": result["baseline_period"], "method": METHOD}), run_id,
               DATASET_KEY, digest))
            cur.execute("INSERT INTO data_quality_checks(run_id,dataset_key,check_name,status,details) VALUES (%s,%s,'heat_source_and_grid_coverage','warning',%s::jsonb)",
              (run_id, DATASET_KEY, json.dumps({"daily_observations": observation_count, "grid_cells": len(result["cells"]),
                "asset_exposure_rows": exposure_count, "baseline_period": result["baseline_period"], "limitations": result["limitations"]})))
            cur.execute("UPDATE datasets SET last_ingested_at=NOW(),updated_at=NOW() WHERE dataset_key=%s", (DATASET_KEY,))
            cur.execute("UPDATE ingestion_runs SET status='completed',finished_at=NOW(),metadata=metadata||%s::jsonb WHERE id=%s",
              (json.dumps({"daily_observations": observation_count, "grid_cells": len(result["cells"]), "asset_exposure_rows": exposure_count}), run_id))
        connection.commit()
    except Exception as error:
        connection.rollback()
        with connection.cursor() as cur:
            cur.execute("UPDATE ingestion_runs SET status='failed',finished_at=NOW(),error_message=%s WHERE id=%s", (str(error)[:4000], run_id))
        connection.commit()
        raise
    finally:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", ("oseas_nasa_power_heat",))
        connection.commit()
    return {"status": "completed", "run_id": str(run_id), "daily_observations": observation_count,
            "grid_cells": len(result["cells"]), "asset_exposure_rows": exposure_count,
            "period": f"{start}/{end}", "source_sha256": digest}


def main() -> int:
    start = date.fromisoformat(os.getenv("OSEAS_HEAT_START_DATE", "2024-01-01"))
    end = date.fromisoformat(os.getenv("OSEAS_HEAT_END_DATE", "2024-12-31"))
    threshold = float(os.getenv("OSEAS_HEAT_SCREEN_THRESHOLD_C", "35"))
    result = acquire(start, end, threshold)
    url = database_url()
    if not url:
        raise RuntimeError("DB_URL, DATABASE_URL, or SUPABASE_DB_URL is required")
    import psycopg
    with psycopg.connect(url, connect_timeout=15, options="-c statement_timeout=120000", application_name="oseas-nasa-power-heat") as connection:
        output = persist(connection, result)
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"NASA POWER heat ingestion failed: {error}", file=sys.stderr)
        raise SystemExit(1)
