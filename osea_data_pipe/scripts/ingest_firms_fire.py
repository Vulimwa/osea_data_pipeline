"""Acquire NASA FIRMS VIIRS active-fire detections and create proximity evidence."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from oseas.config import database_url  # noqa: E402

DATASET_KEY = "nasa_firms_active_fire"
NAMESPACE = uuid.UUID("e0a24a71-1004-49f1-9f83-7c79fd8de229")
METHOD = "firms_viirs_active_detection_asset_proximity_v1"
DEFAULT_BBOX = "-180,-90,180,90"


def acquire(start: date, end: date, bbox: str, source: str, map_key: str) -> dict[str, Any]:
    if not map_key:
        raise RuntimeError("NASA_FIRMS_MAP_KEY is required by the NASA FIRMS Area API; no fire output was fabricated")
    if end < start or (end - start).days > 366:
        raise ValueError("FIRMS period must be ordered and no longer than 367 days")
    coordinates = [float(value) for value in bbox.split(",")]
    if len(coordinates) != 4 or coordinates[0] >= coordinates[2] or coordinates[1] >= coordinates[3]:
        raise ValueError("OSEAS_FIRE_BBOX must be west,south,east,north")
    digest = hashlib.sha256()
    records = []
    day = start
    while day <= end:
        day_count = min(5, (end - day).days + 1)
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{map_key}/{source}/{bbox}/{day_count}/{day.isoformat()}"
        print(f"FIRMS: fetching {source} day window {day}..{day + timedelta(days=day_count - 1)}", flush=True)
        response = requests.get(url, timeout=(20, 90), headers={"User-Agent": "OSEAS fire evidence pipeline/1.0"})
        response.raise_for_status()
        content = response.content
        if b"latitude" not in content[:500].lower() or b"longitude" not in content[:500].lower():
            raise ValueError("FIRMS returned a response without the expected hotspot CSV schema")
        digest.update(content)
        for row in csv.DictReader(io.StringIO(content.decode("utf-8-sig"))):
            try:
                lat, lon = float(row["latitude"]), float(row["longitude"])
                acquired = date.fromisoformat(row["acq_date"])
            except (KeyError, ValueError, TypeError):
                continue
            if not (coordinates[0] <= lon <= coordinates[2] and coordinates[1] <= lat <= coordinates[3]):
                continue
            records.append({"lat": lat, "lon": lon, "date": acquired.isoformat(),
              "time": str(row.get("acq_time", "")), "satellite": row.get("satellite"),
              "instrument": row.get("instrument"), "confidence_category": row.get("confidence"),
              "frp_mw": _number(row.get("frp")), "scan_km": _number(row.get("scan")),
              "track_km": _number(row.get("track")), "daynight": row.get("daynight"),
              "version": row.get("version")})
        day += timedelta(days=day_count)
    unique = {}
    for record in records:
        key = (record["lat"], record["lon"], record["date"], record["time"], record["satellite"], record["instrument"])
        unique[key] = record
    return {"records": list(unique.values()), "sha256": digest.hexdigest(), "start": start, "end": end,
            "bbox": bbox, "source": source}


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def persist(connection: Any, data: dict[str, Any], distance_km: float) -> dict[str, Any]:
    if distance_km <= 0 or distance_km > 100:
        raise ValueError("OSEAS_FIRE_PROXIMITY_KM must be between 0 and 100")
    run_id = uuid.uuid4()
    source_reference = "NASA FIRMS Area API; VIIRS active-fire detection points"
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", ("oseas_firms_fire_ingest",))
        if not cur.fetchone()[0]:
            raise RuntimeError("Another NASA FIRMS fire ingestion is active")
        cur.execute("""INSERT INTO datasets(dataset_key,name,source_type,source_reference,category,licence,attribution,is_optional)
          VALUES (%s,'NASA FIRMS VIIRS active-fire detections','firms_api',%s,'fire','NASA FIRMS data policy','NASA FIRMS; retain product, sensor and acquisition attribution',TRUE)
          ON CONFLICT(dataset_key) DO UPDATE SET source_reference=EXCLUDED.source_reference,updated_at=NOW()""",
          (DATASET_KEY, source_reference))
        cur.execute("INSERT INTO ingestion_runs(id,pipeline_name,status,metadata) VALUES (%s,'oseas_firms_fire_ingest','running',%s::jsonb)",
          (run_id, json.dumps({"method": METHOD, "source": data["source"], "period_start": data["start"].isoformat(),
            "period_end": data["end"].isoformat(), "bbox": data["bbox"], "input_sha256": data["sha256"],
            "proximity_threshold_km": distance_km})))
    connection.commit()
    try:
        rows = []
        for record in data["records"]:
            identity = "|".join(str(record.get(key, "")) for key in
              ("satellite", "instrument", "date", "time", "lat", "lon", "version"))
            event_id = uuid.uuid5(NAMESPACE, identity)
            metadata = {"source": "NASA FIRMS", "sensor": record["satellite"], "instrument": record["instrument"],
              "acquisitionDate": record["date"], "acquisitionTimeUtc": record["time"],
              "sourceConfidenceCategory": record["confidence_category"], "frpMw": record["frp_mw"],
              "scanKm": record["scan_km"], "trackKm": record["track_km"], "dayNight": record["daynight"],
              "sourceVersion": record["version"], "method": METHOD,
              "limitation": "Active-fire detection point; not a fire perimeter and not evidence of asset damage."}
            rows.append((event_id, record, metadata))
        with connection.cursor() as cur:
            for offset in range(0, len(rows), 1000):
                batch = rows[offset:offset + 1000]
                cur.executemany("""INSERT INTO hazard_events
                  (id,hazard_type,evidence_kind,dataset_key,event_start,event_end,source_reference,confidence,geom,metadata,processing_run_id)
                  VALUES (%s,'fire','observed',%s,%s::date + %s::time,%s::date + %s::time,%s,NULL,
                    ST_SetSRID(ST_MakePoint(%s,%s),4326),%s::jsonb,%s)
                  ON CONFLICT(id) DO NOTHING""",
                  [(event_id, DATASET_KEY, record["date"], (record["time"][:2] or "00")+":"+(record["time"][2:4] or "00")+":00",
                    record["date"], (record["time"][:2] or "00")+":"+(record["time"][2:4] or "00")+":00",
                    source_reference, record["lon"], record["lat"], json.dumps(metadata), run_id) for event_id, record, metadata in batch])
                print(f"FIRMS persistence: detection points={min(offset + len(batch), len(rows))}/{len(rows)}", flush=True)
            cur.execute("""INSERT INTO fire_events(hazard_event_id,fire_status,confidence,burned_area_ha,quality)
              SELECT h.id,'active_detection',NULL,NULL,h.metadata FROM hazard_events h
              WHERE h.processing_run_id=%s AND h.hazard_type='fire'
              ON CONFLICT(hazard_event_id) DO NOTHING""", (run_id,))
            cur.execute("""INSERT INTO asset_hazard_exposure
              (id,energy_asset_id,hazard_event_id,hazard_type,assessment_period_start,assessment_period_end,
               exposure_status,distance_m,evidence_kind,confidence,provenance,processing_run_id)
              SELECT md5(a.id::text||h.id::text)::uuid,a.id,h.id,'wildfire',%s,%s,'exposed',
                ST_Distance(a.geom::geography,h.geom::geography),'observed',NULL,
                jsonb_build_object('method',%s,'proximityThresholdKm',%s,'measurement','distance to active-fire detection point',
                  'confidenceCategory',(h.metadata->>'sourceConfidenceCategory'),
                  'limitations',jsonb_build_array('Active detections are not perimeters.','Proximity is not damage or outage evidence.')),
                %s
              FROM energy_assets a JOIN hazard_events h ON h.processing_run_id=%s AND h.hazard_type='fire'
              WHERE ST_DWithin(a.geom::geography,h.geom::geography,%s)
              ON CONFLICT(id) DO NOTHING""",
              (data["start"], data["end"], METHOD, distance_km, run_id, run_id, distance_km * 1000))
            exposure_count = cur.rowcount
            cur.execute("""INSERT INTO dataset_versions(dataset_key,source_reference,source_version,checksum,retrieved_at,
              observation_start,observation_end,feature_count,metadata,processing_run_id)
              SELECT %s,%s,%s,%s,NOW(),%s,%s,%s,%s::jsonb,%s WHERE NOT EXISTS
              (SELECT 1 FROM dataset_versions WHERE dataset_key=%s AND checksum=%s)""",
              (DATASET_KEY, source_reference, data["source"], data["sha256"], data["start"], data["end"],
               len(rows), json.dumps({"method": METHOD, "bbox": data["bbox"]}), run_id, DATASET_KEY, data["sha256"]))
            cur.execute("INSERT INTO data_quality_checks(run_id,dataset_key,check_name,status,details) VALUES (%s,%s,'firms_acquisition_and_detection_quality','warning',%s::jsonb)",
              (run_id, DATASET_KEY, json.dumps({"active_detection_count": len(rows), "asset_proximity_rows": exposure_count,
                "source": data["source"], "method": METHOD, "burnedAreaPerimeter": "not produced"})))
            cur.execute("UPDATE datasets SET last_ingested_at=NOW(),updated_at=NOW() WHERE dataset_key=%s", (DATASET_KEY,))
            cur.execute("UPDATE ingestion_runs SET status='completed',finished_at=NOW(),metadata=metadata||%s::jsonb WHERE id=%s",
              (json.dumps({"detection_points": len(rows), "asset_proximity_rows": exposure_count}), run_id))
        connection.commit()
    except Exception as error:
        connection.rollback()
        with connection.cursor() as cur:
            cur.execute("UPDATE ingestion_runs SET status='failed',finished_at=NOW(),error_message=%s WHERE id=%s", (str(error)[:4000], run_id))
        connection.commit()
        raise
    finally:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", ("oseas_firms_fire_ingest",))
        connection.commit()
    return {"status": "completed", "run_id": str(run_id), "detection_points": len(rows),
            "asset_proximity_rows": exposure_count, "input_sha256": data["sha256"]}


def main() -> int:
    map_key = os.getenv("NASA_FIRMS_MAP_KEY", "").strip()
    start_raw, end_raw = os.getenv("OSEAS_FIRE_START_DATE", ""), os.getenv("OSEAS_FIRE_END_DATE", "")
    if not start_raw or not end_raw:
        raise RuntimeError("Set OSEAS_FIRE_START_DATE and OSEAS_FIRE_END_DATE (YYYY-MM-DD) to define the FIRMS acquisition window")
    start, end = date.fromisoformat(start_raw), date.fromisoformat(end_raw)
    bbox = os.getenv("OSEAS_FIRE_BBOX", "-180,-90,180,180").strip()
    source = os.getenv("OSEAS_FIRE_SENSOR", "VIIRS_SNPP_SP").strip()
    distance_km = float(os.getenv("OSEAS_FIRE_PROXIMITY_KM", "5"))
    data = acquire(start, end, bbox, source, map_key)
    url = database_url()
    if not url:
        raise RuntimeError("DB_URL, DATABASE_URL, or SUPABASE_DB_URL is required")
    import psycopg
    with psycopg.connect(url, connect_timeout=15, options="-c statement_timeout=120000", application_name="oseas-firms-fire") as connection:
        result = persist(connection, data, distance_km)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"NASA FIRMS fire ingestion failed: {error}", file=sys.stderr)
        raise SystemExit(1)
