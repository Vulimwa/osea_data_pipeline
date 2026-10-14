"""Acquire NASA POWER daily air temperature and persist coarse heat indicators."""

from __future__ import annotations

import hashlib
import json
import math
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
KENYA_BBOX = {"latitude-min": -5.0, "latitude-max": 5.0, "longitude-min": 33.5, "longitude-max": 42.0}
METHOD = "nasa_power_t2m_max_monthly_baseline_anomaly_v2"


def fetch_json(url: str, params: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    response = requests.get(url, params=params, timeout=(20, 180), headers={"User-Agent": "OSEAS climate evidence pipeline/1.0"})
    if not response.ok:
        raise RuntimeError(f"NASA POWER returned HTTP {response.status_code}: {response.text[:1000]}")
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
    baseline_start = int(os.getenv("OSEAS_HEAT_BASELINE_START_YEAR", "2001"))
    baseline_end = int(os.getenv("OSEAS_HEAT_BASELINE_END_YEAR", "2020"))
    if baseline_start > baseline_end or baseline_end >= start.year:
        raise ValueError("Heat baseline years must be ordered and end before the assessment period")
    print(f"NASA POWER heat: requesting monthly T2M_MAX baseline for {baseline_start}-{baseline_end}", flush=True)
    climate, climate_raw = fetch_json(f"{API_ROOT}/monthly/regional", {**base, "start": str(baseline_start), "end": str(baseline_end)})
    header = climate.get("header", {})
    baseline = f"{header.get('start', f'{baseline_start}0101')}..{header.get('end', f'{baseline_end}1231')}"
    daily_features = daily["features"]
    climate_by_cell = {}
    for feature in climate["features"]:
        coords = feature.get("geometry", {}).get("coordinates", [])
        values = feature.get("properties", {}).get("parameter", {}).get("T2M_MAX", {})
        month_values: dict[str, list[float]] = {}
        for stamp, raw in values.items():
            if len(stamp) != 6 or float(raw) <= -900:
                continue
            month_values.setdefault(stamp[4:6], []).append(float(raw))
        climate_by_cell[(round(float(coords[0]), 5), round(float(coords[1]), 5))] = {
            month: sum(items) / len(items) for month, items in month_values.items() if items}
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
            month = day[4:6]
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
                          "mean_monthly_baseline_anomaly_c": mean_anomaly})
    if not cells:
        raise ValueError("NASA POWER returned no valid daily T2M_MAX values for the configured Kenya extent/period")
    return {"start": start, "end": end, "threshold_c": threshold_c, "baseline": baseline,
            "baseline_period": {"start": header.get("start", f"{baseline_start}0101"),
              "end": header.get("end", f"{baseline_end}1231"), "statistic": "mean of monthly T2M_MAX values by calendar month"},
            "daily_response": daily, "monthly_baseline_response": climate,
            "content_sha256": content_hash, "daily_records": records, "cells": cells,
            "expected_days": len(expected_dates), "method": METHOD,
            "limitations": ["NASA POWER T2M_MAX is gridded near-surface air temperature, not Landsat land-surface temperature.",
              "Regional grid spacing is 0.5 degrees (~50 km); this is coarse exposure context, not asset-scale microclimate.",
              "Anomaly is daily maximum air temperature minus the baseline-period mean monthly T2M_MAX value for that calendar month.",
              "Hot-day threshold is a configurable screening threshold, not a universal equipment-failure or health threshold.",
              "An exceedance indicates modeled heat exposure only and does not establish asset damage or outage."]}


def reuse_matching_persisted_input(url: str, result: dict[str, Any]) -> dict[str, Any]:
    """Reuse a prior source fingerprint only after comparing persisted values."""
    import psycopg

    expected: dict[tuple[str, str, float, float], float] = {}
    for lon, lat, day, value, anomaly in result["daily_records"]:
        key = ("T2M_MAX", datetime.strptime(day, "%Y%m%d").date().isoformat(), lon, lat)
        expected[key] = value
        if anomaly is not None:
            expected[("T2M_MAX_MONTHLY_CLIMATOLOGY_ANOMALY", key[1], lon, lat)] = anomaly
    with psycopg.connect(url, prepare_threshold=None, connect_timeout=20,
                         options="-c statement_timeout=600000", application_name="oseas-heat-resume-check") as connection:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", ("oseas_nasa_power_heat",))
            if not cur.fetchone()[0]:
                raise RuntimeError("Another NASA POWER heat run is active; resume check did not modify data")
            cur.execute("""SELECT source_properties->>'inputSha256' AS input_hash,count(*)::int
              FROM climate_observations WHERE dataset_key=%s AND source_properties ? 'inputSha256'
                AND variable IN ('T2M_MAX','T2M_MAX_MONTHLY_CLIMATOLOGY_ANOMALY')
              GROUP BY 1 ORDER BY count(*) DESC""", (DATASET_KEY,))
            candidates = cur.fetchall()
            compatible: list[tuple[int, str]] = []
            for candidate_hash, row_count in candidates:
                if not candidate_hash or row_count > len(expected):
                    continue
                cur.execute("""SELECT variable,observed_at::date::text,round(ST_X(geom)::numeric,5)::double precision,
                    round(ST_Y(geom)::numeric,5)::double precision,value
                  FROM climate_observations WHERE dataset_key=%s AND source_properties->>'inputSha256'=%s
                    AND variable IN ('T2M_MAX','T2M_MAX_MONTHLY_CLIMATOLOGY_ANOMALY')""", (DATASET_KEY, candidate_hash))
                rows = cur.fetchall()
                matches = True
                for variable, observed_at, lon, lat, value in rows:
                    expected_value = expected.get((variable, observed_at, lon, lat))
                    if expected_value is None or value is None or not math.isclose(float(value), expected_value, rel_tol=1e-9, abs_tol=1e-6):
                        matches = False
                        break
                if matches and rows:
                    compatible.append((len(rows), candidate_hash))
        if not compatible:
            return result
        compatible.sort(reverse=True)
        selected_hash = compatible[0][1]
        matching_hashes = [candidate_hash for _, candidate_hash in compatible]
        with connection.cursor() as cur:
            cur.execute("""SELECT id,metadata->>'input_content_sha256' FROM ingestion_runs
              WHERE pipeline_name='oseas_nasa_power_heat' AND status IN ('running','partial')
                AND metadata->>'input_content_sha256'=ANY(%s)""", (matching_hashes,))
            compatible_runs = cur.fetchall()
            superseded_ids = [row[0] for row in compatible_runs if row[1] != selected_hash]
            removed_rows = 0
            if superseded_ids:
                cur.execute("""DELETE FROM climate_observations WHERE dataset_key=%s AND processing_run_id=ANY(%s)
                  AND variable IN ('T2M_MAX','T2M_MAX_MONTHLY_CLIMATOLOGY_ANOMALY')
                  AND source_properties->>'inputSha256'=ANY(%s)""",
                  (DATASET_KEY, superseded_ids, [row[1] for row in compatible_runs if row[1] != selected_hash]))
                removed_rows = cur.rowcount
                cur.execute("""UPDATE ingestion_runs SET status='partial',finished_at=NOW(),
                  error_message='Superseded by a value-verified source fingerprint during idempotent resume',
                  metadata=metadata||jsonb_build_object('superseded_duplicate_rows_removed',%s)
                  WHERE id=ANY(%s)""", (removed_rows, superseded_ids))
            connection.commit()
        result["content_sha256"] = selected_hash
        print(f"NASA POWER heat: verified prior source values and reused fingerprint {selected_hash[:12]}; removed duplicate retry rows={removed_rows}", flush=True)
        return result


def persist(connection: Any, result: dict[str, Any]) -> dict[str, Any]:
    import psycopg

    database_dsn = connection.info.dsn
    connection_options = {"prepare_threshold": None, "connect_timeout": 20,
      "options": "-c statement_timeout=600000", "application_name": "oseas-nasa-power-heat"}
    start, end = result["start"], result["end"]
    threshold = result["threshold_c"]
    digest = result["content_sha256"]
    reference = f"{API_ROOT}/daily/regional; {API_ROOT}/monthly/regional"
    metadata = {"method": METHOD, "input_content_sha256": digest, "period_start": start.isoformat(),
                "period_end": end.isoformat(), "threshold_c": threshold, "baseline_period": result["baseline_period"],
                "grid_cell_count": len(result["cells"]), "daily_records": len(result["daily_records"]),
                "limitation": result["limitations"]}
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", ("oseas_nasa_power_heat",))
        if not cur.fetchone()[0]:
            raise RuntimeError("Another NASA POWER heat run is active")
        cur.execute("""SELECT id,metadata FROM ingestion_runs
          WHERE pipeline_name='oseas_nasa_power_heat' AND metadata->>'input_content_sha256'=%s
            AND status='completed' ORDER BY started_at DESC LIMIT 1""", (digest,))
        completed = cur.fetchone()
        if completed:
            completed_id, completed_metadata = completed
            if isinstance(completed_metadata, str):
                completed_metadata = json.loads(completed_metadata)
            cur.execute("SELECT count(*) FROM asset_admin_assignments WHERE is_current=TRUE")
            current_assignments = cur.fetchone()[0]
            if completed_metadata.get("administrative_summary_rows", 0) or not current_assignments:
                connection.commit()
                return {"status": "already_completed", "run_id": str(completed_id),
                  "daily_observations": completed_metadata.get("daily_observations", 0),
                  "grid_cells": completed_metadata.get("grid_cells", len(result["cells"])),
                  "asset_exposure_rows": completed_metadata.get("asset_exposure_rows", 0),
                  "administrative_summary_rows": completed_metadata.get("administrative_summary_rows", 0),
                  "period": f"{start}/{end}", "source_sha256": digest}
            cur.execute("""UPDATE ingestion_runs SET status='partial',finished_at=NOW(),
              error_message='Administrative boundaries were assigned after initial heat processing; refreshing ward/county summaries',
              metadata=metadata||jsonb_build_object('administrative_summary_refresh_required',TRUE) WHERE id=%s""", (completed_id,))
        cur.execute("""INSERT INTO datasets(dataset_key,name,source_type,source_reference,category,licence,attribution,is_optional)
          VALUES (%s,'NASA POWER daily gridded maximum air temperature','nasa_power_api',%s,'climate','NASA POWER terms','NASA POWER; cite POWER documentation',TRUE)
          ON CONFLICT(dataset_key) DO UPDATE SET source_reference=EXCLUDED.source_reference,updated_at=NOW()""",
          (DATASET_KEY, reference))
        cur.execute("""SELECT id,metadata FROM ingestion_runs
          WHERE pipeline_name='oseas_nasa_power_heat' AND metadata->>'input_content_sha256'=%s
            AND status IN ('running','partial') ORDER BY started_at DESC LIMIT 1""", (digest,))
        previous = cur.fetchone()
        if previous:
            run_id, previous_metadata = previous
            if isinstance(previous_metadata, str):
                previous_metadata = json.loads(previous_metadata)
            resume_at = min(max(int(previous_metadata.get("daily_records_processed", 0)), 0), len(result["daily_records"]))
            cur.execute("""UPDATE ingestion_runs SET status='running',finished_at=NULL,error_message=NULL,
                metadata=metadata||%s::jsonb WHERE id=%s""", (json.dumps(metadata), run_id))
            print(f"NASA POWER heat: resuming run {run_id} at daily record {resume_at}/{len(result['daily_records'])}", flush=True)
        else:
            run_id = uuid.uuid4()
            resume_at = 0
            cur.execute("INSERT INTO ingestion_runs(id,pipeline_name,status,metadata) VALUES (%s,'oseas_nasa_power_heat','running',%s::jsonb)",
                        (run_id, json.dumps(metadata)))
    connection.commit()
    try:
        observation_count = resume_at + sum(row[4] is not None for row in result["daily_records"][:resume_at])
        for offset in range(resume_at, len(result["daily_records"]), 2000):
            batch = result["daily_records"][offset:offset + 2000]
            anomaly_records = [(lon, lat, day, anomaly) for lon, lat, day, _value, anomaly in batch if anomaly is not None]
            with connection.cursor() as cur:
                cur.executemany("""INSERT INTO climate_observations
                  (id,dataset_key,variable,value,unit,observed_at,geom,source_properties,processing_run_id)
                  VALUES (%s,%s,%s,%s,'degC',%s::date,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s::jsonb,%s)
                  ON CONFLICT(id) DO UPDATE SET processing_run_id=EXCLUDED.processing_run_id,
                    source_properties=EXCLUDED.source_properties""",
                  [(_id(digest, str(lon), str(lat), day, "t2m_max"), DATASET_KEY, "T2M_MAX", value, day,
                    lon, lat, json.dumps({"source": "NASA POWER", "parameter": "T2M_MAX", "timeStandard": "UTC",
                      "method": METHOD, "monthlyBaselineAnomalyC": anomaly, "inputSha256": digest,
                      "baselinePeriod": result["baseline_period"]}), run_id)
                   for lon, lat, day, value, anomaly in batch])
                cur.executemany("""INSERT INTO climate_observations
                  (id,dataset_key,variable,value,unit,observed_at,geom,source_properties,processing_run_id)
                  VALUES (%s,%s,'T2M_MAX_MONTHLY_CLIMATOLOGY_ANOMALY',%s,'degC',%s::date,
                    ST_SetSRID(ST_MakePoint(%s,%s),4326),%s::jsonb,%s)
                  ON CONFLICT(id) DO UPDATE SET processing_run_id=EXCLUDED.processing_run_id,
                    source_properties=EXCLUDED.source_properties""",
                  [(_id(digest, str(lon), str(lat), day, "t2m_max_monthly_anomaly"),
                    DATASET_KEY, anomaly, day, lon, lat,
                    json.dumps({"source": "NASA POWER", "parameter": "T2M_MAX",
                      "baseline": "mean monthly T2M_MAX for the selected baseline period", "method": METHOD,
                      "inputSha256": digest, "baselinePeriod": result["baseline_period"]}), run_id)
                   for lon, lat, day, anomaly in anomaly_records])
                observation_count += len(batch) + len(anomaly_records)
                processed_to = min(offset + len(batch), len(result["daily_records"]))
                cur.execute("UPDATE ingestion_runs SET metadata=metadata||%s::jsonb WHERE id=%s",
                  (json.dumps({"persisted_observations": observation_count,
                    "daily_records_processed": processed_to}), run_id))
            connection.commit()
            print(f"NASA POWER heat persistence: daily records={processed_to}/{len(result['daily_records'])}; persisted_observations={observation_count}", flush=True)
            if processed_to < len(result["daily_records"]) and processed_to % 20000 == 0:
                connection.close()
                connection = psycopg.connect(database_dsn, **connection_options)
                with connection.cursor() as lock_cursor:
                    lock_cursor.execute("SELECT pg_try_advisory_lock(hashtext(%s))", ("oseas_nasa_power_heat",))
                    if not lock_cursor.fetchone()[0]:
                        raise RuntimeError("Another NASA POWER heat run is active during batch reconnection")
                print(f"NASA POWER heat: database connection refreshed at record {processed_to}", flush=True)
        with connection.cursor() as cur:
            for cell in result["cells"]:
                hazard_id = _id(digest, f"{cell['lon']:.5f}", f"{cell['lat']:.5f}", start.isoformat(), end.isoformat(),
                                str(threshold), "heat-grid-cell")
                cell_metadata = {"method": METHOD, "threshold_c": threshold, "hot_days": cell["hot_days"],
                  "valid_days": cell["valid_days"], "expected_days": result["expected_days"],
                  "valid_data_fraction": cell["valid_fraction"], "max_t2m_c": cell["max_t2m_c"],
                  "mean_monthly_baseline_anomaly_c": cell["mean_monthly_baseline_anomaly_c"],
                  "grid_spacing_degrees": 0.5, "baseline_period": result["baseline_period"],
                  "inputSha256": digest,
                  "scientific_validation_status": "not_validated", "limitations": result["limitations"]}
                cur.execute("""INSERT INTO hazard_events
                  (id,hazard_type,evidence_kind,dataset_key,event_start,event_end,source_reference,confidence,geom,metadata,processing_run_id)
                  VALUES (%s,'heat','modeled',%s,%s,%s,%s,NULL,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s::jsonb,%s)
                  ON CONFLICT(id) DO NOTHING""",
                   (hazard_id, DATASET_KEY, start, end, reference, cell["lon"], cell["lat"], json.dumps(cell_metadata), run_id))
                cur.execute("""INSERT INTO climate_observations
                  (id,dataset_key,variable,value,unit,observed_at,geom,source_properties,processing_run_id)
                  VALUES (%s,%s,%s,%s,'day',%s::date,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s::jsonb,%s)
                 ON CONFLICT(id) DO UPDATE SET processing_run_id=EXCLUDED.processing_run_id,
                   source_properties=EXCLUDED.source_properties""",
                  (_id(digest, str(cell["lon"]), str(cell["lat"]), start.isoformat(), end.isoformat(),
                       str(threshold), "heat_days"), DATASET_KEY, f"HEAT_DAYS_GE_{threshold:g}C", cell["hot_days"], end,
                   cell["lon"], cell["lat"], json.dumps(cell_metadata), run_id))
            print("NASA POWER heat: deriving nearest-cell asset exposure", flush=True)
            cur.execute("""INSERT INTO asset_hazard_exposure
              (id,energy_asset_id,hazard_event_id,hazard_type,assessment_period_start,assessment_period_end,
               exposure_status,distance_m,evidence_kind,confidence,provenance,processing_run_id)
              SELECT md5(c.asset_id::text||c.hazard_id::text)::uuid,c.asset_id,c.hazard_id,'heat',%s,%s,
                CASE WHEN (c.metadata->>'valid_data_fraction')::double precision < 0.8 THEN 'unknown'
                     WHEN (c.metadata->>'hot_days')::integer > 0 THEN 'exposed' ELSE 'not_exposed' END,
                c.distance_m,'modeled',NULL,
                 jsonb_build_object('method',%s::text,'thresholdC',%s::double precision,'gridSpacingDegrees',0.5,
                  'matchingRule','nearest NASA POWER regional grid cell within 45 km',
                  'limitation','Coarse modeled air-temperature context; no asset damage inference.'),
                %s
              FROM (
                SELECT a.id AS asset_id,h.id AS hazard_id,a.geom AS asset_geom,h.geom AS hazard_geom,h.metadata,
                  ST_Distance(a.geom::geography,h.geom::geography) AS distance_m,
                  ROW_NUMBER() OVER (PARTITION BY a.id ORDER BY a.geom <-> h.geom) AS nearest_rank
                FROM hazard_events h JOIN energy_assets a
                  ON a.geom && ST_Expand(h.geom,0.6)
                 AND ST_DWithin(a.geom::geography,h.geom::geography,45000)
                WHERE h.metadata->>'inputSha256'=%s AND h.hazard_type='heat'
              ) c WHERE c.nearest_rank=1
              ON CONFLICT(id) DO NOTHING""",
              (start, end, METHOD, threshold, run_id, digest))
            # Count the persisted evidence for this source, including deterministic
            # rows reused from a prior successful attempt. rowcount only describes
            # newly inserted rows because this write is intentionally idempotent.
            cur.execute("""SELECT count(*) FROM asset_hazard_exposure e
              JOIN hazard_events h ON h.id=e.hazard_event_id
              WHERE e.hazard_type='heat' AND h.metadata->>'inputSha256'=%s""", (digest,))
            exposure_count = cur.fetchone()[0]
            event_fingerprint = f"{digest}:{start.isoformat()}:{end.isoformat()}:{threshold:g}"
            cur.execute("""SELECT u.id::text,u.unit_level,count(DISTINCT aa.energy_asset_id)::int AS assigned_count,
                count(DISTINCT e.energy_asset_id) FILTER (WHERE e.exposure_status IN ('exposed','not_exposed'))::int AS assessed_count,
                count(DISTINCT e.energy_asset_id) FILTER (WHERE e.exposure_status='exposed')::int AS exposed_count,
                count(DISTINCT e.energy_asset_id) FILTER (WHERE e.exposure_status='unknown')::int AS unknown_count
              FROM administrative_units u
              JOIN asset_admin_assignments aa ON aa.administrative_unit_id=u.id AND aa.unit_level=u.unit_level AND aa.is_current=TRUE
              LEFT JOIN asset_hazard_exposure e ON e.energy_asset_id=aa.energy_asset_id AND e.hazard_type='heat'
                AND e.hazard_event_id IN (SELECT id FROM hazard_events WHERE hazard_type='heat' AND metadata->>'inputSha256'=%s)
              WHERE u.unit_level IN ('county','ward')
              GROUP BY u.id,u.unit_level ORDER BY u.unit_level,u.id""", (digest,))
            admin_rows = cur.fetchall()
            summary_records = []
            for unit_id, unit_level, assigned_count, assessed_count, exposed_count, unknown_count in admin_rows:
                summary_id = _id("admin-summary", event_fingerprint, unit_id, unit_level)
                provenance = {"method": METHOD, "sourceSha256": digest, "eventFingerprint": event_fingerprint,
                  "assignedAssetCount": assigned_count, "assessedAssetCount": assessed_count,
                  "unknownAssetCount": unknown_count, "exposedAssetCount": exposed_count,
                  "exposureFractionDenominator": "assets with assessable nearest-cell coverage",
                  "limitations": result["limitations"]}
                summary_records.append((summary_id, unit_id, event_fingerprint, start, end,
                  "screened" if assessed_count else "insufficient_data", assigned_count, exposed_count,
                  exposed_count / assessed_count if assessed_count else None, json.dumps(provenance), run_id))
            cur.executemany("""INSERT INTO administrative_hazard_summaries
                  (id,administrative_unit_id,hazard_type,event_fingerprint,period_start,period_end,assessment_status,
                   assigned_energy_asset_count,candidate_exposed_asset_count,candidate_exposure_fraction,provenance,processing_run_id,created_at)
                  VALUES (%s,%s,'heat',%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,NOW())
                  ON CONFLICT(administrative_unit_id,hazard_type,event_fingerprint) DO UPDATE SET
                    assessment_status=EXCLUDED.assessment_status,assigned_energy_asset_count=EXCLUDED.assigned_energy_asset_count,
                    candidate_exposed_asset_count=EXCLUDED.candidate_exposed_asset_count,
                    candidate_exposure_fraction=EXCLUDED.candidate_exposure_fraction,provenance=EXCLUDED.provenance,
                    processing_run_id=EXCLUDED.processing_run_id,created_at=NOW()""",
                  summary_records)
            coverage_geom = json.dumps({"type": "Polygon", "coordinates": [[
              [33.5, -5.0], [42.0, -5.0], [42.0, 5.0], [33.5, 5.0], [33.5, -5.0]]]})
            cur.execute("""INSERT INTO spatial_coverage_assessments
              (dataset_key,processing_run_id,reporting_unit_level,hazard_type,evidence_kind,observation_start,observation_end,
               coverage_status,area_coverage_fraction,valid_data_fraction,observation_footprint,quality_mask,
               validation_status,limitations,provenance)
              VALUES (%s,%s,'national','heat','modeled',%s,%s,'partially_assessed',NULL,%s,
                ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s::jsonb,'not_validated',%s::jsonb,%s::jsonb)
              ON CONFLICT DO NOTHING""",
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
            quality_details = json.dumps({"daily_observations": observation_count, "grid_cells": len(result["cells"]),
                "asset_exposure_rows": exposure_count, "administrative_summary_rows": len(admin_rows),
                "baseline_period": result["baseline_period"], "limitations": result["limitations"]})
            cur.execute("""UPDATE data_quality_checks SET details=%s::jsonb,status='warning',checked_at=NOW()
              WHERE run_id=%s AND check_name='heat_source_and_grid_coverage'""", (quality_details, run_id))
            if cur.rowcount == 0:
                cur.execute("INSERT INTO data_quality_checks(run_id,dataset_key,check_name,status,details) VALUES (%s,%s,'heat_source_and_grid_coverage','warning',%s::jsonb)",
                  (run_id, DATASET_KEY, quality_details))
            cur.execute("UPDATE datasets SET last_ingested_at=NOW(),updated_at=NOW() WHERE dataset_key=%s", (DATASET_KEY,))
            cur.execute("UPDATE ingestion_runs SET status='completed',finished_at=NOW(),metadata=metadata||%s::jsonb WHERE id=%s",
              (json.dumps({"daily_observations": observation_count, "grid_cells": len(result["cells"]),
                "asset_exposure_rows": exposure_count, "administrative_summary_rows": len(admin_rows)}), run_id))
        connection.commit()
    except Exception as error:
        try:
            connection.rollback()
        except Exception:
            pass
        try:
            with psycopg.connect(database_dsn, **connection_options) as recovery_connection:
                with recovery_connection.cursor() as cur:
                    cur.execute("UPDATE ingestion_runs SET status='partial',finished_at=NOW(),error_message=%s,metadata=metadata||%s::jsonb WHERE id=%s",
                      (str(error)[:4000], json.dumps({"persisted_observations": observation_count}), run_id))
                recovery_connection.commit()
        except Exception as recovery_error:
            print(f"NASA POWER heat checkpoint retained for resume; run status update also failed: {recovery_error}", file=sys.stderr)
        raise
    finally:
        try:
            if not connection.closed:
                with connection.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", ("oseas_nasa_power_heat",))
                connection.commit()
        except Exception:
            connection.close()
    return {"status": "completed", "run_id": str(run_id), "daily_observations": observation_count,
            "grid_cells": len(result["cells"]), "asset_exposure_rows": exposure_count,
            "administrative_summary_rows": len(admin_rows),
            "period": f"{start}/{end}", "source_sha256": digest}


def main() -> int:
    start = date.fromisoformat(os.getenv("OSEAS_HEAT_START_DATE", "2024-01-01"))
    end = date.fromisoformat(os.getenv("OSEAS_HEAT_END_DATE", "2024-12-31"))
    threshold = float(os.getenv("OSEAS_HEAT_SCREEN_THRESHOLD_C", "35"))
    url = database_url()
    if not url:
        raise RuntimeError("DB_URL, DATABASE_URL, or SUPABASE_DB_URL is required")
    result = acquire(start, end, threshold)
    result = reuse_matching_persisted_input(url, result)
    import psycopg
    with psycopg.connect(url, prepare_threshold=None, connect_timeout=15, options="-c statement_timeout=600000", application_name="oseas-nasa-power-heat") as connection:
        output = persist(connection, result)
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"NASA POWER heat ingestion failed: {error}", file=sys.stderr)
        raise SystemExit(1)
