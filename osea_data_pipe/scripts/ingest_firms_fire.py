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
DEFAULT_SENSOR = "VIIRS_SNPP_NRT"


def fetch_kenya_aoi(connection: Any) -> tuple[Any, str]:
    """Use ingested county boundaries for both the request envelope and exact Kenya clipping."""
    from shapely import wkb

    with connection.cursor() as cur:
        cur.execute("""SELECT ST_AsBinary(kenya.geom),ST_XMin(Box3D(kenya.geom)),ST_YMin(Box3D(kenya.geom)),
            ST_XMax(Box3D(kenya.geom)),ST_YMax(Box3D(kenya.geom))
          FROM (SELECT ST_UnaryUnion(ST_Collect(ST_MakeValid(geom))) AS geom
                FROM administrative_units WHERE unit_level='county') AS kenya""")
        row = cur.fetchone()
    if not row or not row[0]:
        raise RuntimeError("Kenya county boundaries are required to constrain FIRMS acquisition to the project AOI")
    geometry = wkb.loads(bytes(row[0]))
    bbox = ",".join(f"{float(value):.8f}" for value in row[1:5])
    return geometry, bbox


def acquire(start: date | None, end: date | None, bbox: str, source: str, map_key: str,
            kenya_aoi: Any) -> dict[str, Any]:
    if not map_key:
        raise RuntimeError("NASA_FIRMS_MAP_KEY is required by the NASA FIRMS Area API; no fire output was fabricated")
    latest = start is None and end is None
    if (start is None) != (end is None):
        raise ValueError("Set both OSEAS_FIRE_START_DATE and OSEAS_FIRE_END_DATE, or leave both empty for the latest day")
    if not latest and (end < start or (end - start).days > 366):
        raise ValueError("FIRMS period must be ordered and no longer than 367 days")
    coordinates = [float(value) for value in bbox.split(",")]
    if len(coordinates) != 4 or coordinates[0] >= coordinates[2] or coordinates[1] >= coordinates[3]:
        raise ValueError("OSEAS_FIRE_BBOX must be west,south,east,north")
    digest = hashlib.sha256()
    records = []
    from shapely.geometry import Point, mapping

    day = start or date.today()
    while latest or day <= end:
        day_count = 1 if latest else min(5, (end - day).days + 1)
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{map_key}/{source}/{bbox}/{day_count}"
        if not latest:
            url += f"/{day.isoformat()}"
        print(f"FIRMS: fetching {source} {'latest day' if latest else f'{day}..{day + timedelta(days=day_count - 1)}'} within Kenya", flush=True)
        try:
            response = requests.get(url, timeout=(20, 90), headers={"User-Agent": "OSEAS fire evidence pipeline/1.0"})
        except requests.RequestException:
            raise RuntimeError("NASA FIRMS request failed; verify network access and the server-side MAP_KEY (URL redacted)") from None
        if not response.ok:
            raise RuntimeError(f"NASA FIRMS returned HTTP {response.status_code}; verify the server-side MAP_KEY (URL redacted)")
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
            if not kenya_aoi.covers(Point(lon, lat)):
                continue
            records.append({"lat": lat, "lon": lon, "date": acquired.isoformat(),
              "time": str(row.get("acq_time", "")).zfill(4), "satellite": row.get("satellite"),
              "instrument": row.get("instrument"), "confidence_category": row.get("confidence"),
              "frp_mw": _number(row.get("frp")), "scan_km": _number(row.get("scan")),
              "track_km": _number(row.get("track")), "daynight": row.get("daynight"),
              "version": row.get("version")})
        if latest:
            break
        day += timedelta(days=day_count)
    unique = {}
    for record in records:
        key = (record["lat"], record["lon"], record["date"], record["time"], record["satellite"], record["instrument"])
        unique[key] = record
    records = list(unique.values())
    acquired_dates = [date.fromisoformat(record["date"]) for record in records]
    period_start = min(acquired_dates) if acquired_dates else (start or day)
    period_end = max(acquired_dates) if acquired_dates else (end or day)
    return {"records": records, "sha256": digest.hexdigest(), "start": period_start, "end": period_end,
            "bbox": bbox, "source": source, "query_mode": "latest_day" if latest else "historical_period",
            "aoi": "Kenya county boundary union", "aoi_geojson": mapping(kenya_aoi)}


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
            "aoi": data["aoi"], "query_mode": data["query_mode"],
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
              "sourceVersion": record["version"], "inputSha256": data["sha256"], "method": METHOD,
              "aoi": data["aoi"], "queryMode": data["query_mode"],
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
              WHERE h.metadata->>'inputSha256'=%s AND h.hazard_type='fire'
              ON CONFLICT(hazard_event_id) DO NOTHING""", (data["sha256"],))
            cur.execute("""INSERT INTO asset_hazard_exposure
              (id,energy_asset_id,hazard_event_id,hazard_type,assessment_period_start,assessment_period_end,
               exposure_status,distance_m,evidence_kind,confidence,provenance,processing_run_id)
              SELECT md5(a.id::text||h.id::text)::uuid,a.id,h.id,'wildfire',%s,%s,'exposed',
                ST_Distance(a.geom::geography,h.geom::geography),'observed',NULL,
                jsonb_build_object('method',%s::text,'proximityThresholdKm',%s,'measurement','distance to active-fire detection point',
                  'confidenceCategory',(h.metadata->>'sourceConfidenceCategory'),
                  'limitations',jsonb_build_array('Active detections are not perimeters.','Proximity is not damage or outage evidence.')),
                %s
              FROM energy_assets a JOIN hazard_events h ON h.metadata->>'inputSha256'=%s AND h.hazard_type='fire'
              WHERE ST_DWithin(a.geom::geography,h.geom::geography,%s)
              ON CONFLICT(id) DO NOTHING""",
              (data["start"], data["end"], METHOD, distance_km, run_id, data["sha256"], distance_km * 1000))
            exposure_count = cur.rowcount
            cur.execute("""INSERT INTO dataset_versions(dataset_key,source_reference,source_version,checksum,retrieved_at,
              observation_start,observation_end,feature_count,metadata,processing_run_id)
              SELECT %s,%s,%s,%s,NOW(),%s,%s,%s,%s::jsonb,%s WHERE NOT EXISTS
              (SELECT 1 FROM dataset_versions WHERE dataset_key=%s AND checksum=%s)""",
              (DATASET_KEY, source_reference, data["source"], data["sha256"], data["start"], data["end"],
               len(rows), json.dumps({"method": METHOD, "bbox": data["bbox"], "aoi": data["aoi"],
                 "queryMode": data["query_mode"]}), run_id, DATASET_KEY, data["sha256"]))
            footprint = json.dumps(data["aoi_geojson"])
            cur.execute("""INSERT INTO spatial_coverage_assessments
              (dataset_key,processing_run_id,reporting_unit_level,hazard_type,evidence_kind,observation_start,observation_end,
               coverage_status,observation_footprint,quality_mask,validation_status,limitations,provenance)
              VALUES (%s,%s,'national','wildfire','observed',%s,%s,'partially_assessed',
                ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s::jsonb,'not_validated',%s::jsonb,%s::jsonb)""",
              (DATASET_KEY, run_id, data["start"], data["end"], footprint,
               json.dumps({"detectionPointsReturned": len(rows), "sensor": data["source"], "bbox": data["bbox"],
                 "aoi": data["aoi"], "queryMode": data["query_mode"]}),
               json.dumps(["Active-fire detections are not a complete fire perimeter or proof of no fire.",
                 "Detection absence may reflect cloud, overpass timing, sensor limits, or product availability."]),
               json.dumps({"method": METHOD, "inputSha256": data["sha256"]})))
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
    if bool(start_raw) != bool(end_raw):
        raise RuntimeError("Set both OSEAS_FIRE_START_DATE and OSEAS_FIRE_END_DATE, or leave both empty for latest NRT")
    start, end = (date.fromisoformat(start_raw), date.fromisoformat(end_raw)) if start_raw else (None, None)
    configured_bbox = os.getenv("OSEAS_FIRE_BBOX", "").strip()
    source = os.getenv("OSEAS_FIRE_SENSOR", DEFAULT_SENSOR).strip()
    distance_km = float(os.getenv("OSEAS_FIRE_PROXIMITY_KM", "5"))
    url = database_url()
    if not url:
        raise RuntimeError("DB_URL, DATABASE_URL, or SUPABASE_DB_URL is required")
    import psycopg
    with psycopg.connect(url, prepare_threshold=None, connect_timeout=15, options="-c statement_timeout=120000", application_name="oseas-firms-aoi") as connection:
        kenya_aoi, derived_bbox = fetch_kenya_aoi(connection)
    bbox = configured_bbox or derived_bbox
    data = acquire(start, end, bbox, source, map_key, kenya_aoi)
    print(f"FIRMS acquisition: Kenya detections={len(data['records'])}; period={data['start']}..{data['end']}; mode={data['query_mode']}", flush=True)
    with psycopg.connect(url, prepare_threshold=None, connect_timeout=15, options="-c statement_timeout=120000", application_name="oseas-firms-fire") as connection:
        result = persist(connection, data, distance_km)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"NASA FIRMS fire ingestion failed: {error}", file=sys.stderr)
        raise SystemExit(1)
