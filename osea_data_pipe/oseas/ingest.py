"""Validate configured Earth Engine assets and persist their features to PostGIS."""

from __future__ import annotations

import argparse
import inspect
import json
import logging
import os
import random
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from oseas.config import configured_assets, database_url, missing_asset_keys

LOG = logging.getLogger("oseas.ingest")
NAMESPACE = uuid.UUID("f31e7f78-7742-4223-8644-b45517271c2a")
PAGE_SIZE = max(1, min(int(os.getenv("GEE_FEATURE_PAGE_SIZE", "500")), 1000))
MAX_RETRIES = max(0, min(int(os.getenv("OSEAS_MAX_RETRIES", "3")), 8))
LOCK_NAMESPACE = "oseas_earth_engine_ingest"


def _asset_metadata(ee: Any, asset_id: str) -> dict[str, Any]:
    return ee.data.getAsset(asset_id)


def _property_schema(metadata: dict[str, Any], first_feature: dict[str, Any] | None) -> dict[str, Any]:
    columns = metadata.get("columns") or metadata.get("properties")
    if isinstance(columns, list):
        return {str(col.get("name", "")): col.get("type") for col in columns if isinstance(col, dict)}
    return {str(k): type(v).__name__ for k, v in (first_feature or {}).get("properties", {}).items()}


def _get_features(ee: Any, asset_id: str, page_token: str | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"pageSize": PAGE_SIZE}
    if page_token:
        params["pageToken"] = page_token
    parameters = inspect.signature(ee.data.listFeatures).parameters
    if len(parameters) == 1:
        return ee.data.listFeatures({"assetId": asset_id, **params})
    return ee.data.listFeatures(asset_id, params)


def _next_page_token(page: dict[str, Any]) -> str | None:
    return page.get("next_page_token") or page.get("nextPageToken")


def _is_transient(error: Exception) -> bool:
    sqlstate = getattr(error, "sqlstate", None) or getattr(error, "pgcode", None)
    if sqlstate and (sqlstate.startswith("08") or sqlstate.startswith("40") or sqlstate in {"53300", "57P03"}):
        return True
    status = getattr(error, "status_code", None)
    response = getattr(error, "response", None)
    status = status or getattr(response, "status_code", None)
    if status in (408, 425, 429) or (isinstance(status, int) and status >= 500):
        return True
    message = str(error).lower()
    return any(marker in message for marker in ("timed out", "timeout", "connection reset", "temporarily unavailable", "try again", "503", "429"))


def _retry(operation: Any, label: str) -> Any:
    for attempt in range(MAX_RETRIES + 1):
        try:
            return operation()
        except Exception as error:
            if attempt >= MAX_RETRIES or not _is_transient(error):
                raise
            delay = min(30.0, (2 ** attempt) + random.random())
            LOG.warning("Transient failure during %s (attempt %s/%s); retrying in %.1fs: %s", label, attempt + 1, MAX_RETRIES, delay, error)
            time.sleep(delay)


def inspect_asset(ee: Any, asset_id: str) -> dict[str, Any]:
    metadata = _asset_metadata(ee, asset_id)
    if metadata.get("type") != "TABLE":
        raise ValueError(f"Expected a TABLE asset; Earth Engine reports {metadata.get('type', 'unknown')}")
    sample = _get_features(ee, asset_id)
    first = (sample.get("features") or [None])[0]
    geometry_column = metadata.get("geometryColumn")
    geometry_type = geometry_column.get("geometryType") if isinstance(geometry_column, dict) else None
    if not geometry_type and first:
        geometry_type = (first.get("geometry") or {}).get("type")
    return {
        "asset_type": metadata.get("type"),
        "geometry_type": geometry_type or metadata.get("geometryType"),
        "property_schema": _property_schema(metadata, first),
        "sample_feature_count": len(sample.get("features", [])),
        "feature_count": int(ee.FeatureCollection(asset_id).size().getInfo()),
        "first_feature": first,
        "metadata": metadata,
        "next_page_token": _next_page_token(sample),
    }


def _source_feature_id(feature: dict[str, Any]) -> str | None:
    properties = feature.get("properties") or {}
    for stable_field in ("uid", "gaul1_code", "objectid", "code", "gid", "system:index"):
        for key, value in properties.items():
            if key.lower() == stable_field and value is not None:
                return str(value)
    return str(feature["id"]) if feature.get("id") is not None else None


def _stable_id(dataset_key: str, feature: dict[str, Any]) -> str:
    source_id = _source_feature_id(feature)
    seed = f"{dataset_key}:{source_id}" if source_id is not None else f"{dataset_key}:{json.dumps(feature, sort_keys=True, separators=(',', ':'))}"
    return str(uuid.uuid5(NAMESPACE, seed))


def _geometry(feature: dict[str, Any]) -> dict[str, Any] | None:
    geom = feature.get("geometry")
    supported = {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"}
    if isinstance(geom, dict) and geom.get("type") in supported and geom.get("coordinates"):
        return geom
    if isinstance(geom, dict) and geom.get("type") == "GeometryCollection" and geom.get("geometries"):
        return geom
    return None


def _geometry_for_target(feature: dict[str, Any], target: str) -> dict[str, Any] | None:
    geometry = _geometry(feature)
    if geometry is None or target not in {"county", "ward"} or geometry.get("type") != "GeometryCollection":
        return geometry

    polygons: list[list[Any]] = []

    def collect_polygonal(candidate: dict[str, Any]) -> None:
        geometry_type = candidate.get("type")
        coordinates = candidate.get("coordinates")
        if geometry_type == "Polygon" and coordinates:
            polygons.append(coordinates)
        elif geometry_type == "MultiPolygon" and coordinates:
            polygons.extend(coordinates)
        elif geometry_type == "GeometryCollection":
            for child in candidate.get("geometries", []):
                if isinstance(child, dict):
                    collect_polygonal(child)

    collect_polygonal(geometry)
    if not polygons:
        return None
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


def _persist_feature_page(cur: Any, run_id: str, spec: Any, asset_id: str, features: list[dict[str, Any]]) -> int:
    """Prepare and write one bounded page using batched DB commands."""
    admin_rows, service_rows, asset_rows = [], [], []
    line_rows, substation_rows, transformer_rows, station_rows, mini_grid_rows = [], [], [], [], []
    hydrography_rows, flood_reference_rows = [], []
    for feature in features:
        geometry = _geometry_for_target(feature, spec.target)
        if not geometry:
            raise ValueError(f"Feature {_source_feature_id(feature) or '(no source ID)'} has no usable geometry")
        feature_id = _stable_id(spec.key, feature)
        props = feature.get("properties") or {}
        original_id = _source_feature_id(feature) or feature_id
        props_json = json.dumps(props)
        geom_json = json.dumps(geometry)
        name = _name(props)
        if spec.target == "hydrography":
            hydrography_rows.append((spec.key, str(original_id), spec.category, name, props_json, geom_json, run_id))
        elif spec.target == "flood_reference":
            event_key = _text(props, ("eventid", "event_id")) or "FL-20231121-KEN-03"
            event_date = _text(props, ("date_proc", "event_date")) or "20231121"
            event_metadata = json.dumps({"reported_event_area_m2": 543793.0, "reported_affected_population": 242812, "metadata_source": "user-supplied ADAM event record", "adam_id": "FL-20231121-KEN-03"}) if event_key == "FL-20231121-KEN-03" else "{}"
            flood_reference_rows.append((spec.key, str(original_id), event_key, event_date, props_json, event_metadata, geom_json, run_id))
        elif spec.target in ("county", "ward"):
            admin_rows.append((feature_id, spec.target, spec.key, asset_id, str(original_id), _stable_admin_code(props, spec.target), name, props_json, geom_json, run_id))
        elif spec.target == "critical_service":
            service_rows.append((feature_id, spec.category, spec.key, asset_id, str(original_id), name, props_json, geom_json, run_id))
        else:
            voltage = _voltage(spec.key)
            asset_rows.append((feature_id, spec.category, spec.key, asset_id, str(original_id), name, voltage, props_json, geom_json, run_id))
            if spec.target == "network_line":
                line_rows.append((feature_id, voltage, spec.category, props_json))
            if spec.category == "primary_substation":
                substation_rows.append((feature_id, _text(props, ("type", "substation_type")), _number(props, ("capacity_mva", "mva")), props_json))
            elif spec.category == "distribution_transformer":
                transformer_rows.append((feature_id, _number(props, ("capacity_kva", "kva")), props_json))
            elif spec.category == "power_station":
                station_rows.append((feature_id, _text(props, ("generation_type", "fuel", "technology")), _number(props, ("capacity_mw", "mw")), props_json))
            elif spec.category in ("mini_grid_existing", "mini_grid_development"):
                mini_grid_rows.append((feature_id, "existing" if spec.category == "mini_grid_existing" else "under_development", _number(props, ("capacity_kw", "kw")), props_json))

    if admin_rows:
        cur.executemany(
            """INSERT INTO administrative_units
                 (id, unit_level, source_dataset_key, source_asset_id, source_feature_id, stable_code, name, source_properties, geom, last_ingested_run_id, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)), %s, NOW())
               ON CONFLICT (source_dataset_key, source_feature_id) DO UPDATE SET stable_code=EXCLUDED.stable_code,
                 name=EXCLUDED.name, source_properties=EXCLUDED.source_properties, geom=EXCLUDED.geom,
                 last_ingested_run_id=EXCLUDED.last_ingested_run_id, updated_at=NOW()""",
            admin_rows,
        )
    if service_rows:
        cur.executemany(
            """INSERT INTO critical_services
                 (id, service_type, source_dataset_key, source_asset_id, source_feature_id, name, source_properties, geom, last_ingested_run_id, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, ST_SetSRID(ST_GeomFromGeoJSON(%s),4326), %s, NOW())
               ON CONFLICT (source_dataset_key, source_feature_id) DO UPDATE SET name=EXCLUDED.name,
                 source_properties=EXCLUDED.source_properties, geom=EXCLUDED.geom,
                 last_ingested_run_id=EXCLUDED.last_ingested_run_id, updated_at=NOW()""",
            service_rows,
        )
    if asset_rows:
        cur.executemany(
            """INSERT INTO energy_assets
                 (id, asset_type, source_dataset_key, source_asset_id, source_feature_id, name, voltage_kv, source_properties, geom, last_ingested_run_id, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, ST_SetSRID(ST_GeomFromGeoJSON(%s),4326), %s, NOW())
               ON CONFLICT (source_dataset_key, source_feature_id) DO UPDATE SET name=EXCLUDED.name,
                 voltage_kv=COALESCE(EXCLUDED.voltage_kv,energy_assets.voltage_kv),
                 source_properties=EXCLUDED.source_properties, geom=EXCLUDED.geom,
                 last_ingested_run_id=EXCLUDED.last_ingested_run_id, updated_at=NOW()""",
            asset_rows,
        )
    if line_rows:
        cur.executemany(
            """INSERT INTO network_lines (asset_id, voltage_kv, line_class, source_properties)
               VALUES (%s,%s,%s,%s::jsonb) ON CONFLICT (asset_id) DO UPDATE SET voltage_kv=EXCLUDED.voltage_kv,
                 line_class=EXCLUDED.line_class, source_properties=EXCLUDED.source_properties""",
            line_rows,
        )
    if substation_rows:
        cur.executemany(
            """INSERT INTO substations (asset_id, substation_type, capacity_mva, source_properties)
               VALUES (%s,%s,%s,%s::jsonb) ON CONFLICT (asset_id) DO UPDATE SET
                 substation_type=EXCLUDED.substation_type, capacity_mva=EXCLUDED.capacity_mva, source_properties=EXCLUDED.source_properties""",
            substation_rows,
        )
    if transformer_rows:
        cur.executemany(
            """INSERT INTO distribution_transformers (asset_id, capacity_kva, source_properties)
               VALUES (%s,%s,%s::jsonb) ON CONFLICT (asset_id) DO UPDATE SET
                 capacity_kva=EXCLUDED.capacity_kva, source_properties=EXCLUDED.source_properties""",
            transformer_rows,
        )
    if station_rows:
        cur.executemany(
            """INSERT INTO power_stations (asset_id, generation_type, capacity_mw, source_properties)
               VALUES (%s,%s,%s,%s::jsonb) ON CONFLICT (asset_id) DO UPDATE SET
                 generation_type=EXCLUDED.generation_type, capacity_mw=EXCLUDED.capacity_mw, source_properties=EXCLUDED.source_properties""",
            station_rows,
        )
    if mini_grid_rows:
        cur.executemany(
            """INSERT INTO mini_grids (asset_id, development_status, capacity_kw, source_properties)
               VALUES (%s,%s,%s,%s::jsonb) ON CONFLICT (asset_id) DO UPDATE SET
                 development_status=EXCLUDED.development_status, capacity_kw=EXCLUDED.capacity_kw, source_properties=EXCLUDED.source_properties""",
            mini_grid_rows,
        )
    if hydrography_rows:
        cur.executemany(
            """INSERT INTO hydrography_features
                 (dataset_key, source_feature_id, feature_type, name, source_properties, geom, processing_run_id, updated_at)
               VALUES (%s,%s,%s,%s,%s::jsonb,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s,NOW())
               ON CONFLICT (dataset_key, source_feature_id) DO UPDATE SET feature_type=EXCLUDED.feature_type,
                 name=EXCLUDED.name,source_properties=EXCLUDED.source_properties,geom=EXCLUDED.geom,
                 processing_run_id=EXCLUDED.processing_run_id,updated_at=NOW()""",
            hydrography_rows,
        )
    if flood_reference_rows:
        cur.executemany(
            """INSERT INTO flood_reference_features
                 (dataset_key, source_feature_id, event_key, event_date, source_properties, event_metadata, geom, processing_run_id, updated_at)
               VALUES (%s,%s,%s,TO_DATE(%s,'YYYYMMDD'),%s::jsonb,%s::jsonb,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s,NOW())
               ON CONFLICT (dataset_key, source_feature_id) DO UPDATE SET event_key=EXCLUDED.event_key,
                 event_date=EXCLUDED.event_date,source_properties=EXCLUDED.source_properties,geom=EXCLUDED.geom,
                 event_metadata=EXCLUDED.event_metadata,processing_run_id=EXCLUDED.processing_run_id,updated_at=NOW()""",
            flood_reference_rows,
        )
    cur.execute("UPDATE datasets SET last_ingested_at=NOW(), updated_at=NOW() WHERE dataset_key=%s", (spec.key,))
    return len(features)


def _number(properties: dict[str, Any], candidates: tuple[str, ...]) -> float | None:
    for key, value in properties.items():
        if key.lower() in candidates and value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def _text(properties: dict[str, Any], candidates: tuple[str, ...]) -> str | None:
    for key, value in properties.items():
        if key.lower() in candidates and value is not None:
            return str(value)[:200]
    return None


def _name(properties: dict[str, Any]) -> str | None:
    name_fields = {"name", "asset_name", "facility", "label", "facility_n", "school_nam", "name8", "locationna", "name_im", "lake", "river"}
    for key, value in properties.items():
        if key.lower() in name_fields and value is not None and str(value).strip():
            return str(value).strip()[:500]
    return None


def _stable_admin_code(properties: dict[str, Any], level: str) -> str | None:
    candidates = {"county": ("gaul1_code", "county_code", "county_id"), "ward": ("uid", "ward_code", "ward_id")}
    allowed = set(candidates[level])
    for key, value in properties.items():
        if key.lower() in allowed and value is not None:
            return str(value)
    return None


def _voltage(key: str) -> float | None:
    for voltage in (33, 66, 132, 220):
        if f"{voltage}kv" in key:
            return float(voltage)
    return None


def _ensure_dataset(cur: Any, spec: Any, asset_id: str) -> None:
    cur.execute(
        """INSERT INTO datasets (dataset_key, name, source_type, source_reference, category, is_optional)
           VALUES (%s, %s, 'earth_engine_table', %s, %s, TRUE)
           ON CONFLICT (dataset_key) DO UPDATE SET name = EXCLUDED.name,
             source_reference = EXCLUDED.source_reference, category = EXCLUDED.category""",
        (spec.key, spec.label, asset_id, spec.category),
    )


def _start_run(cur: Any, run_id: str, total: int) -> None:
    cur.execute(
        "INSERT INTO ingestion_runs (id, pipeline_name, status, started_at, metadata) VALUES (%s, 'oseas_earth_engine_ingest', 'running', NOW(), %s::jsonb)",
        (run_id, json.dumps({"configured_assets": total, "page_size": PAGE_SIZE})),
    )


def _acquire_run_lock(connection: Any) -> None:
    """Hold a session advisory lock for the full run to prevent concurrent writers."""
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(hashtext(%s), hashtext('writer'))", (LOCK_NAMESPACE,))
        acquired = cur.fetchone()[0]
    if not acquired:
        raise RuntimeError("Another OSEAS ingestion process holds the database run lock; no new run was started")


def _fail_abandoned_runs(cur: Any) -> int:
    """Close stale run records after this process has acquired the exclusive writer lock."""
    cur.execute(
        """UPDATE ingestion_runs
           SET status = 'failed', finished_at = NOW(),
               metadata = metadata || jsonb_build_object(
                 'interrupted', TRUE,
                 'interruption_reason', 'Previous ingestion process ended before recording a final status',
                 'recovered_at', NOW()
               )
           WHERE pipeline_name = 'oseas_earth_engine_ingest' AND status = 'running'"""
    )
    return cur.rowcount


def _write_page(connection: Any, run_id: str, spec: Any, asset_id: str, features: list[dict[str, Any]], prior_count: int, total: int, page_number: int) -> tuple[int, int]:
    def persist() -> tuple[int, int]:
        try:
            with connection.cursor() as cur:
                valid_features = [feature for feature in features if _geometry_for_target(feature, spec.target)]
                skipped_count = len(features) - len(valid_features)
                if skipped_count:
                    invalid_ids = [
                        _source_feature_id(feature) or "(no source ID)"
                        for feature in features
                        if not _geometry_for_target(feature, spec.target)
                    ]
                    LOG.warning("Skipping %s source features without usable geometry for dataset=%s page=%s sample_ids=%s", skipped_count, spec.key, page_number, invalid_ids[:10])
                page_count = _persist_feature_page(cur, run_id, spec, asset_id, valid_features) if valid_features else 0
                cur.execute(
                    "UPDATE ingestion_runs SET metadata = metadata || jsonb_build_object('current_dataset', %s::text, 'current_processed', %s::bigint, 'current_persisted', %s::bigint, 'current_skipped_geometry', %s::bigint, 'current_total', %s::bigint, 'current_page', %s::integer, 'progress_updated_at', NOW()) WHERE id = %s::uuid",
                    (spec.key, prior_count + len(features), page_count, skipped_count, total, page_number, run_id),
                )
            connection.commit()
            return page_count, skipped_count
        except Exception:
            connection.rollback()
            raise
    return _retry(persist, f"PostGIS page write for {spec.key}, page {page_number}")


def _validate_schema(connection: Any) -> None:
    required = {
        "datasets": {"dataset_key", "source_reference", "last_ingested_at"},
        "ingestion_runs": {"id", "pipeline_name", "status", "started_at", "finished_at", "metadata"},
        "dataset_versions": {"dataset_key", "source_reference", "retrieved_at", "feature_count", "metadata"},
        "data_quality_checks": {"run_id", "dataset_key", "check_name", "status", "details"},
        "energy_assets": {"id", "asset_type", "source_dataset_key", "source_asset_id", "source_feature_id", "source_properties", "geom", "last_ingested_run_id"},
        "network_lines": {"asset_id", "voltage_kv", "line_class", "source_properties"},
        "substations": {"asset_id", "source_properties"},
        "distribution_transformers": {"asset_id", "source_properties"},
        "power_stations": {"asset_id", "source_properties"},
        "mini_grids": {"asset_id", "development_status", "source_properties"},
        "critical_services": {"id", "service_type", "source_dataset_key", "source_asset_id", "source_feature_id", "source_properties", "geom", "last_ingested_run_id"},
        "administrative_units": {"id", "unit_level", "source_dataset_key", "source_asset_id", "source_feature_id", "stable_code", "source_properties", "geom", "last_ingested_run_id"},
        "hydrography_features": {"dataset_key", "source_feature_id", "feature_type", "source_properties", "geom", "processing_run_id"},
        "flood_reference_features": {"dataset_key", "source_feature_id", "event_key", "event_date", "source_properties", "geom", "processing_run_id"},
    }
    names = list(required)
    with connection.cursor() as cur:
        cur.execute(
            "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = ANY(%s)",
            (names,),
        )
        actual: dict[str, set[str]] = {}
        for table, column in cur.fetchall():
            actual.setdefault(table, set()).add(column)
    missing = [f"{table}.{column}" for table, columns in required.items() for column in sorted(columns - actual.get(table, set()))]
    if missing:
        raise RuntimeError("OSEAS schema is incomplete; apply database/schema.sql first. Missing: " + ", ".join(missing))


def run(audit_only: bool = False) -> int:
    try:
        import ee
    except ImportError as exc:
        raise RuntimeError("earthengine-api is required; install requirements.txt") from exc
    from gee.auth import initialize_earth_engine

    project = os.getenv("GEE_PROJECT_ID", "").strip()
    if not project:
        raise RuntimeError("GEE_PROJECT_ID is required")
    if not initialize_earth_engine(project):
        raise RuntimeError("Earth Engine authentication failed; check project and credentials")

    selected = {value.strip() for value in os.getenv("OSEAS_DATASETS", "").split(",") if value.strip()}
    assets = configured_assets()
    if selected:
        assets = [(spec, asset_id) for spec, asset_id in assets if spec.key in selected]
        unknown = selected - {spec.key for spec, _ in assets}
        if unknown:
            raise RuntimeError("Unknown or unconfigured OSEAS_DATASETS keys: " + ", ".join(sorted(unknown)))
    if not assets:
        raise RuntimeError("No GEE_ASSET_* variables are configured")
    if missing := missing_asset_keys():
        LOG.warning("Some optional assets are not configured: %s", ", ".join(missing))

    connection = None
    run_id = str(uuid.uuid4())
    report: list[dict[str, Any]] = []
    try:
        if not audit_only:
            url = database_url()
            if not url:
                raise RuntimeError("DATABASE_URL or SUPABASE_DB_URL is required for ingestion")
            try:
                import psycopg
            except ImportError as exc:
                raise RuntimeError("psycopg[binary] is required; install requirements.txt") from exc
            connection = psycopg.connect(url, prepare_threshold=None, connect_timeout=15, options="-c statement_timeout=120000", application_name="oseas-ingest")
            _acquire_run_lock(connection)
            _validate_schema(connection)
            with connection.cursor() as cur:
                abandoned = _fail_abandoned_runs(cur)
                if abandoned:
                    LOG.warning("Closed %s abandoned ingestion run record(s); their committed feature rows are retained and will be safely upserted", abandoned)
                _start_run(cur, run_id, len(assets))
            connection.commit()

        for spec, asset_id in assets:
            started = datetime.now(timezone.utc)
            try:
                details = inspect_asset(ee, asset_id)
                count = 0
                skipped_geometry = 0
                if not audit_only:
                    with connection.cursor() as cur:
                        _ensure_dataset(cur, spec, asset_id)
                    connection.commit()
                    token = None
                    page_number = 0
                    asset_started = time.monotonic()
                    total = details["feature_count"]
                    while True:
                        page = _retry(lambda: _get_features(ee, asset_id, token), f"Earth Engine page fetch for {spec.key}, page {page_number + 1}")
                        features = page.get("features", [])
                        page_count, page_skipped = _write_page(connection, run_id, spec, asset_id, features, count, total, page_number + 1)
                        count += page_count
                        skipped_geometry += page_skipped
                        processed = count + skipped_geometry
                        page_number += 1
                        elapsed = time.monotonic() - asset_started
                        rate = processed / elapsed if elapsed else 0
                        eta = max(0, total - processed) / rate if rate else None
                        percent = (processed / total * 100) if total else 100.0
                        LOG.info(
                            "progress dataset=%s page=%s source_batch=%s persisted_batch=%s skipped_geometry=%s processed=%s/%s percent=%.1f elapsed_s=%.1f eta_s=%s",
                            spec.key, page_number, len(features), page_count, page_skipped, processed, total, percent, elapsed,
                            "unknown" if eta is None else f"{eta:.0f}",
                        )
                        token = _next_page_token(page)
                        if not token:
                            break
                else:
                    count = details["feature_count"]
                item = {"dataset_key": spec.key, "asset_id": asset_id, "status": "validated" if audit_only else ("partial" if skipped_geometry else "completed"), "geometry_type": details["geometry_type"], "property_schema": details["property_schema"], "features_processed": details["feature_count"] if audit_only else count + skipped_geometry, "features_persisted": 0 if audit_only else count, "features_would_persist": count if audit_only else None, "features_skipped_geometry": skipped_geometry, "checked_at": started.isoformat()}
                report.append(item)
                LOG.info("%s: %s; %s features", spec.key, item["status"], count)
                if not audit_only:
                    with connection.cursor() as cur:
                        cur.execute("INSERT INTO dataset_versions (dataset_key, source_reference, retrieved_at, feature_count, metadata, processing_run_id) VALUES (%s, %s, NOW(), %s, %s::jsonb, %s)", (spec.key, asset_id, count, json.dumps({"geometry_type": details["geometry_type"], "property_schema": details["property_schema"], "source_feature_count": count + skipped_geometry, "skipped_geometry_count": skipped_geometry}), run_id))
                        quality_status = "warning" if skipped_geometry else "passed"
                        cur.execute("INSERT INTO data_quality_checks (run_id, dataset_key, check_name, status, details) VALUES (%s, %s, 'earth_engine_asset_validation', %s, %s::jsonb)", (run_id, spec.key, quality_status, json.dumps({"asset_type": details["asset_type"], "geometry_type": details["geometry_type"], "feature_count": count, "source_feature_count": count + skipped_geometry, "skipped_geometry_count": skipped_geometry, "property_schema": details["property_schema"]})))
                        cur.execute("UPDATE datasets SET last_ingested_at = NOW(), updated_at = NOW() WHERE dataset_key = %s", (spec.key,))
                    connection.commit()
            except Exception as exc:
                LOG.exception("Asset processing failed: %s", spec.key)
                item = {"dataset_key": spec.key, "asset_id": asset_id, "status": "failed", "error": str(exc), "checked_at": started.isoformat()}
                report.append(item)
                if connection:
                    connection.rollback()
                    with connection.cursor() as cur:
                        cur.execute("INSERT INTO data_quality_checks (run_id, dataset_key, check_name, status, details) VALUES (%s, %s, 'earth_engine_asset_validation', 'failed', %s::jsonb)", (run_id, spec.key, json.dumps({"error": str(exc)})))
                    connection.commit()

        failures = sum(item["status"] == "failed" for item in report)
        warnings = sum(item["status"] == "partial" for item in report)
        if connection:
            with connection.cursor() as cur:
                final_status = "failed" if failures == len(report) else ("partial" if failures or warnings else "completed")
                cur.execute("UPDATE ingestion_runs SET status = %s, finished_at = NOW(), metadata = metadata || %s::jsonb WHERE id = %s", (final_status, json.dumps({"assets": report, "failed_assets": failures, "warning_assets": warnings}), run_id))
            connection.commit()
        final_status = "failed" if failures == len(report) else ("partial" if failures or warnings else "completed")
        print(json.dumps({"run_id": run_id, "status": final_status, "assets": report}, indent=2))
        return 1 if failures == len(report) else (2 if failures or warnings else 0)
    finally:
        if connection:
            connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and ingest configured OSEAS Earth Engine assets.")
    parser.add_argument("--audit-only", action="store_true", help="Validate asset existence, type, sample geometry and schema without writing to PostGIS.")
    parser.add_argument("--datasets", help="Comma-separated configured dataset keys to process; defaults to all configured assets.")
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    args = parser.parse_args()
    if args.datasets:
        os.environ["OSEAS_DATASETS"] = args.datasets
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        raise SystemExit(run(audit_only=args.audit_only))
    except Exception as exc:
        LOG.error("OSEAS ingestion did not run: %s", exc)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
