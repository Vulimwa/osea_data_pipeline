"""Persist event-window CHIRPS rainfall totals and anomalies by county and ward."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gee.auth import initialize_earth_engine  # noqa: E402
from oseas.config import database_url  # noqa: E402

DATASET_KEY = "chirps_daily"
COLLECTION_ID = "UCSB-CHG/CHIRPS/DAILY"
NAMESPACE = uuid.UUID("b6e28647-497c-49c7-a4b8-e47e4b353d92")
WINDOW_DAYS = 30
BASELINE_START_YEAR = 2001
BASELINE_END_YEAR = 2020
SCALE_METERS = 5566
ADMIN_SIMPLIFICATION_DEGREES = 0.0005
BATCH_SIZE = 150
LOCK_NAME = "oseas_chirps_rainfall_context"
RUN_LEASE_MINUTES = 30
METHOD = "chirps_30_day_event_rainfall_anomaly_by_administrative_unit_v1"


def event_window(event_date: date) -> tuple[date, date]:
    """Return a 30-day window ending on and including the reference event date."""
    return event_date - timedelta(days=WINDOW_DAYS - 1), event_date + timedelta(days=1)


def baseline_window(event_date: date, year: int) -> tuple[date, date]:
    """Return the same calendar window in a baseline year, handling leap day safely."""
    try:
        anchor = event_date.replace(year=year)
    except ValueError:
        # A 29 February event is compared with 28 February in non-leap years.
        anchor = event_date.replace(year=year, day=28)
    return event_window(anchor)


def stable_observation_id(event_key: str, event_date: date, unit_id: str, variable: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, "|".join((event_key, event_date.isoformat(), unit_id, variable, METHOD)))


def content_digest(results: list[dict[str, Any]]) -> str:
    """Hash JSON-safe source measurements for an idempotent dataset version."""
    content_rows = [{**{key: row[key] for key in ("event_key", "unit_id", "event_total_mm", "baseline_mean_mm", "anomaly_mm", "anomaly_percent")},
                     "event_date": row["event_date"].isoformat()}
                    for row in results]
    return hashlib.sha256(json.dumps(content_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _read_inputs(url: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    import psycopg

    with psycopg.connect(
        url,
        prepare_threshold=None,
        connect_timeout=20,
        options="-c default_transaction_read_only=on -c statement_timeout=120000",
        application_name="oseas-chirps-input-read",
    ) as connection:
        with connection.cursor() as cur:
            cur.execute("""
                SELECT event_key, min(event_date)::date
                FROM flood_reference_features
                WHERE event_date IS NOT NULL
                GROUP BY event_key
                ORDER BY min(event_date), event_key
            """)
            events = [{"event_key": row[0], "event_date": row[1]} for row in cur.fetchall()]
            cur.execute("""
                SELECT id::text, unit_level, COALESCE(name, ''),
                       ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, %s))
                FROM administrative_units
                WHERE unit_level IN ('county','ward')
                ORDER BY unit_level, stable_code NULLS LAST, name, id
            """, (ADMIN_SIMPLIFICATION_DEGREES,))
            units = [{"id": row[0], "level": row[1], "name": row[2], "geometry": json.loads(row[3])}
                     for row in cur.fetchall()]
    if not events:
        raise RuntimeError("No dated flood reference events are persisted; ingest the 2023/2024 reference layers first")
    if not units:
        raise RuntimeError("No county/ward geometries are persisted; ingest Kenya administrative boundaries first")
    return events, units


def _earth_engine_summaries(ee: Any, event: dict[str, Any], units: list[dict[str, Any]],
                            progress_callback: Any | None = None) -> tuple[list[dict[str, Any]], int]:
    event_date = event["event_date"]
    period_start, period_end = event_window(event_date)
    collection = ee.ImageCollection(COLLECTION_ID).select("precipitation")
    event_images = collection.filterDate(period_start.isoformat(), period_end.isoformat())
    event_image_count = int(event_images.size().getInfo())
    if event_image_count < math.ceil(WINDOW_DAYS * 0.9):
        raise RuntimeError(
            f"CHIRPS event window for {event['event_key']} has {event_image_count}/{WINDOW_DAYS} daily images; "
            "at least 90% coverage is required"
        )

    event_total = event_images.sum().rename("event_total_mm")
    annual_images = []
    for year in range(BASELINE_START_YEAR, BASELINE_END_YEAR + 1):
        baseline_start, baseline_end = baseline_window(event_date, year)
        annual_images.append(
            collection.filterDate(baseline_start.isoformat(), baseline_end.isoformat())
            .sum().rename("baseline_total_mm")
        )
    annual_collection = ee.ImageCollection.fromImages(ee.List(annual_images))
    baseline_mean = annual_collection.mean().rename("baseline_mean_mm")
    baseline_count = annual_collection.count().rename("baseline_year_count")
    anomaly = event_total.subtract(baseline_mean).rename("anomaly_mm")
    percent = anomaly.divide(baseline_mean).multiply(100).updateMask(baseline_mean.gt(0)).rename("anomaly_percent")
    image = event_total.addBands(baseline_mean).addBands(baseline_count).addBands(anomaly).addBands(percent)

    properties = ["unit_id", "unit_level", "unit_name", "event_total_mm", "baseline_mean_mm",
                  "baseline_year_count", "anomaly_mm", "anomaly_percent"]
    output: list[dict[str, Any]] = []
    for offset in range(0, len(units), BATCH_SIZE):
        batch = units[offset:offset + BATCH_SIZE]
        features = [ee.Feature(ee.Geometry(unit["geometry"], geodesic=False), {
            "unit_id": unit["id"], "unit_level": unit["level"], "unit_name": unit["name"]
        }) for unit in batch]
        reduced = image.reduceRegions(
            collection=ee.FeatureCollection(features),
            reducer=ee.Reducer.mean(),
            scale=SCALE_METERS,
            tileScale=4,
        )
        rows = reduced.reduceColumns(ee.Reducer.toList(len(properties)), properties).get("list").getInfo()
        for row in rows or []:
            values = dict(zip(properties, row))
            output.append({
                "event_key": event["event_key"],
                "event_date": event_date,
                "period_start": period_start,
                "period_end_exclusive": period_end,
                "event_days_available": event_image_count,
                "unit_id": str(values["unit_id"]),
                "unit_level": str(values["unit_level"]),
                "unit_name": str(values.get("unit_name") or ""),
                "event_total_mm": _finite_or_none(values.get("event_total_mm")),
                "baseline_mean_mm": _finite_or_none(values.get("baseline_mean_mm")),
                "baseline_year_count": _finite_or_none(values.get("baseline_year_count")),
                "anomaly_mm": _finite_or_none(values.get("anomaly_mm")),
                "anomaly_percent": _finite_or_none(values.get("anomaly_percent")),
            })
        print(f"CHIRPS {event['event_key']}: administrative summaries {min(offset + len(batch), len(units))}/{len(units)}", flush=True)
        if progress_callback:
            progress_callback(min(offset + len(batch), len(units)), len(units))
    return output, event_image_count


def _finite_or_none(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _record_properties(row: dict[str, Any]) -> dict[str, Any]:
    baseline_count = row["baseline_year_count"]
    data_quality = "assessed" if baseline_count is not None and baseline_count >= 15 else "partial_baseline"
    return {
        "eventKey": row["event_key"],
        "eventDate": row["event_date"].isoformat(),
        "periodStart": row["period_start"].isoformat(),
        "periodEndExclusive": row["period_end_exclusive"].isoformat(),
        "windowDays": WINDOW_DAYS,
        "eventDaysAvailable": row["event_days_available"],
        "baselineStartYear": BASELINE_START_YEAR,
        "baselineEndYear": BASELINE_END_YEAR,
        "baselineYearsPerPixelMean": baseline_count,
        "baselineMeanMm": row["baseline_mean_mm"],
        "anomalyMm": row["anomaly_mm"],
        "anomalyPercent": row["anomaly_percent"],
        "reportingUnitId": row["unit_id"],
        "reportingUnitLevel": row["unit_level"],
        "reportingUnitName": row["unit_name"],
        "method": METHOD,
        "sourceCollection": COLLECTION_ID,
        "spatialScaleMeters": SCALE_METERS,
        "adminBoundarySimplificationDegrees": ADMIN_SIMPLIFICATION_DEGREES,
        "dataQualityStatus": data_quality,
        "interpretation": "CHIRPS gridded rainfall context; an anomaly is not proof of flooding, asset damage, or service disruption.",
    }


def _start_run(url: str, events: list[dict[str, Any]]) -> uuid.UUID:
    """Claim one durable run lease, serialized through a row lock (pooler safe)."""
    import psycopg

    run_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    metadata = {"method": METHOD, "collection": COLLECTION_ID,
                "eventKeys": [event["event_key"] for event in events],
                "windowDays": WINDOW_DAYS, "baselineYears": [BASELINE_START_YEAR, BASELINE_END_YEAR],
                "heartbeatAt": now.isoformat(), "progress": {"stage": "starting"}}
    with psycopg.connect(url, prepare_threshold=None, connect_timeout=20,
                         options="-c statement_timeout=30000", application_name="oseas-chirps-run-start") as connection:
        with connection.cursor() as cur:
            cur.execute("""
                INSERT INTO datasets(dataset_key,name,source_type,source_reference,category,licence,attribution,is_optional)
                VALUES (%s,'CHIRPS daily precipitation','earth_engine_image_collection',%s,'climate',
                  'CHIRPS data terms','UCSB Climate Hazards Center; Funk et al. (2015)',TRUE)
                ON CONFLICT(dataset_key) DO NOTHING
            """, (DATASET_KEY, COLLECTION_ID))
            cur.execute("SELECT dataset_key FROM datasets WHERE dataset_key=%s FOR UPDATE", (DATASET_KEY,))
            cur.execute("""
                SELECT id,COALESCE(NULLIF(metadata->>'heartbeatAt','')::timestamptz,started_at)
                FROM ingestion_runs WHERE pipeline_name=%s AND status='running' FOR UPDATE
            """, (LOCK_NAME,))
            active_runs = cur.fetchall()
            stale_ids = []
            for active_id, heartbeat_at in active_runs:
                if heartbeat_at and heartbeat_at > now - timedelta(minutes=RUN_LEASE_MINUTES):
                    raise RuntimeError(f"CHIRPS run {active_id} has a live database lease; refusing a duplicate run")
                stale_ids.append(active_id)
            if stale_ids:
                cur.execute("""
                    UPDATE ingestion_runs SET status='partial',finished_at=NOW(),
                      error_message='Recovered abandoned CHIRPS run after its progress lease expired'
                    WHERE id=ANY(%s)
                """, (stale_ids,))
            cur.execute("""
                INSERT INTO ingestion_runs(id,pipeline_name,status,metadata)
                VALUES (%s,%s,'running',%s::jsonb)
            """, (run_id, LOCK_NAME, json.dumps(metadata)))
    return run_id


def _heartbeat(url: str, run_id: uuid.UUID, progress: dict[str, Any]) -> None:
    """Refresh the run lease after each Earth Engine batch."""
    import psycopg

    with psycopg.connect(url, prepare_threshold=None, connect_timeout=20,
                         options="-c statement_timeout=30000", application_name="oseas-chirps-heartbeat") as connection:
        with connection.cursor() as cur:
            cur.execute("""
                UPDATE ingestion_runs SET metadata=metadata||jsonb_build_object('heartbeatAt',NOW(),'progress',%s::jsonb)
                WHERE id=%s AND status='running' RETURNING id
            """, (json.dumps(progress), run_id))
            if not cur.fetchone():
                raise RuntimeError(f"CHIRPS run lease {run_id} is no longer active")


def _persist(url: str, events: list[dict[str, Any]], results: list[dict[str, Any]], run_id: uuid.UUID) -> dict[str, Any]:
    import psycopg

    digest = content_digest(results)
    metadata = {
        "method": METHOD,
        "sourceCollection": COLLECTION_ID,
        "baselineYears": [BASELINE_START_YEAR, BASELINE_END_YEAR],
        "windowDays": WINDOW_DAYS,
        "eventCount": len(events),
        "administrativeUnitCount": len({row["unit_id"] for row in results}),
        "observationRows": sum(2 + (row["anomaly_percent"] is not None) for row in results),
        "contentSha256": digest,
    }
    inserted = 0
    sql = """
        INSERT INTO climate_observations
          (id,dataset_key,variable,value,unit,observed_at,geom,source_properties,processing_run_id)
        SELECT %s,%s,%s,%s,%s,%s,ST_PointOnSurface(u.geom),%s::jsonb,%s
        FROM administrative_units u WHERE u.id=%s::uuid
        ON CONFLICT(id) DO UPDATE SET value=EXCLUDED.value,unit=EXCLUDED.unit,
          observed_at=EXCLUDED.observed_at,geom=EXCLUDED.geom,
          source_properties=EXCLUDED.source_properties,processing_run_id=EXCLUDED.processing_run_id
    """
    with psycopg.connect(url, prepare_threshold=None, connect_timeout=20,
                         options="-c statement_timeout=600000", application_name="oseas-chirps-persist") as connection:
        with connection.cursor() as cur:
            cur.execute("""
                INSERT INTO datasets(dataset_key,name,source_type,source_reference,category,licence,attribution,is_optional)
                VALUES (%s,'CHIRPS daily precipitation','earth_engine_image_collection',%s,'climate',
                  'CHIRPS data terms','UCSB Climate Hazards Center; Funk et al. (2015)',TRUE)
                ON CONFLICT(dataset_key) DO UPDATE SET source_reference=EXCLUDED.source_reference,updated_at=NOW()
            """, (DATASET_KEY, COLLECTION_ID))
            pending = []
            for row in results:
                if row["event_total_mm"] is None or row["baseline_mean_mm"] is None or row["anomaly_mm"] is None:
                    continue
                properties = _record_properties(row)
                observed_at = datetime.combine(row["event_date"], time.min, tzinfo=timezone.utc)
                for variable, value in (("CHIRPS_30D_TOTAL_MM", row["event_total_mm"]),
                                        ("CHIRPS_30D_ANOMALY_MM", row["anomaly_mm"]),
                                        ("CHIRPS_30D_ANOMALY_PERCENT", row["anomaly_percent"])):
                    if value is None:
                        continue
                    observation_id = stable_observation_id(row["event_key"], row["event_date"], row["unit_id"], variable)
                    unit = "percent" if variable.endswith("PERCENT") else "mm"
                    source_properties = {**properties, "variable": variable, "valueUnit": unit}
                    pending.append((observation_id, DATASET_KEY, variable, value, unit, observed_at,
                                    json.dumps(source_properties, allow_nan=False), run_id, row["unit_id"]))
            if pending:
                cur.executemany(sql, pending)
                inserted = len(pending)
            period_start = min((event_window(event["event_date"])[0] for event in events))
            period_end = max((event["event_date"] for event in events))
            cur.execute("""
                INSERT INTO dataset_versions(dataset_key,source_reference,source_version,checksum,retrieved_at,
                  observation_start,observation_end,feature_count,metadata,processing_run_id)
                SELECT %s,%s,%s,%s,NOW(),%s,%s,%s,%s::jsonb,%s
                WHERE NOT EXISTS(SELECT 1 FROM dataset_versions WHERE dataset_key=%s AND checksum=%s)
            """, (DATASET_KEY, COLLECTION_ID, "CHIRPS daily via Earth Engine", digest,
                  period_start, period_end, inserted, json.dumps(metadata), run_id, DATASET_KEY, digest))
            expected_rows = sum(2 + (row["anomaly_percent"] is not None) for row in results)
            quality = "passed" if inserted == expected_rows else "warning"
            cur.execute("""
                INSERT INTO data_quality_checks(run_id,dataset_key,check_name,status,details)
                VALUES (%s,%s,'chirps_event_window_and_baseline_coverage',%s,%s::jsonb)
            """, (run_id, DATASET_KEY, quality, json.dumps({**metadata,
                "expectedObservationRows": expected_rows,
                "validObservationRows": inserted,
                "baselineYearsWithInsufficientCoverage": sum(1 for row in results
                    if row["baseline_year_count"] is None or row["baseline_year_count"] < 15),
                "scientificValidationStatus": "not_validated"})))
            cur.execute("UPDATE datasets SET last_ingested_at=NOW(),updated_at=NOW() WHERE dataset_key=%s", (DATASET_KEY,))
            cur.execute("""
                UPDATE ingestion_runs SET status=%s,finished_at=NOW(),metadata=metadata||%s::jsonb,
                  error_message=%s WHERE id=%s
            """, ("completed" if inserted == expected_rows else "partial",
                  json.dumps({**metadata, "persistedObservationRows": inserted}),
                  None if inserted == expected_rows else "Some expected administrative-unit measurements were unavailable", run_id))
        connection.commit()
    expected_rows = sum(2 + (row["anomaly_percent"] is not None) for row in results)
    return {"status": "completed" if inserted == expected_rows else "partial",
            "run_id": str(run_id), "observation_rows": inserted, "expected_observation_rows": expected_rows,
            "units": len({row["unit_id"] for row in results}), "events": len(events), "content_sha256": digest}


def main() -> int:
    url = database_url()
    if not url:
        raise RuntimeError("DB_URL, DATABASE_URL, or SUPABASE_DB_URL is required")
    if not initialize_earth_engine():
        raise RuntimeError("Earth Engine authentication failed; CHIRPS is available through the public Earth Engine catalog")
    events, units = _read_inputs(url)
    print(f"CHIRPS: dated reference events={len(events)}; county/ward units={len(units)}; "
          f"baseline={BASELINE_START_YEAR}-{BASELINE_END_YEAR}", flush=True)

    run_id = _start_run(url, events)
    try:
        import ee
        results: list[dict[str, Any]] = []
        for event in events:
            event_rows, _ = _earth_engine_summaries(ee, event, units,
                progress_callback=lambda completed, total, event_key=event["event_key"]:
                    _heartbeat(url, run_id, {"stage": "earth_engine_summaries", "eventKey": event_key,
                                             "administrativeUnitsCompleted": completed, "administrativeUnitsTotal": total}))
            valid = [row for row in event_rows if row["event_total_mm"] is not None and row["baseline_mean_mm"] is not None]
            results.extend(valid)
            print(f"CHIRPS {event['event_key']}: covered reporting units={len(valid)}/{len(units)}", flush=True)
        if not results:
            raise RuntimeError("CHIRPS returned no event/reference administrative-unit summaries")
        result = _persist(url, events, results, run_id)
        print(json.dumps({**result,
                          "method": METHOD,
                          "limitations": ["Rainfall is averaged across CHIRPS grid cells within each reporting unit.",
                            "Anomaly compares the 30-day event window with the same calendar window in 2001-2020.",
                            "The result is rainfall context, not proof of flood extent, asset damage, or service interruption.",
                            "CHIRPS event outputs have not been independently validated for Kenya." ]}, indent=2), flush=True)
        return 0 if result["status"] == "completed" else 2
    except Exception as error:
        try:
            with psycopg.connect(url, prepare_threshold=None, connect_timeout=15,
                                 application_name="oseas-chirps-run-failure") as connection:
                with connection.cursor() as cur:
                    cur.execute("""
                        UPDATE ingestion_runs SET status='failed',finished_at=NOW(),error_message=%s
                        WHERE id=%s AND status='running'
                    """, (str(error)[:4000], run_id))
        except Exception:
            pass
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"CHIRPS rainfall processing failed: {error}", file=sys.stderr)
        raise SystemExit(1)
