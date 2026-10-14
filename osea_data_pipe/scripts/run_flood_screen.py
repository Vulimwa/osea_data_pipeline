"""Run one explicit, bounded Sentinel-1 flood candidate assessment and persist outputs."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oseas.catalog import BY_KEY
from oseas.config import database_url
from oseas.flood import METHOD_VERSION, build_candidate_vectors, stable_event_fingerprint, validate_bbox
from oseas.spatial import refresh_asset_admin_assignments

LOG = logging.getLogger("oseas.flood")
NAMESPACE = uuid.UUID("f31e7f78-7742-4223-8644-b45517271c2a")
INGEST_LOCK = "oseas_earth_engine_ingest"
FLOOD_LOCK = "oseas_sar_flood_screen"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"), help="Small analysis bbox in EPSG:4326; max 1000 km2")
    parser.add_argument("--event-start", required=True, help="Inclusive YYYY-MM-DD Sentinel-1 event window")
    parser.add_argument("--event-end", required=True, help="Exclusive YYYY-MM-DD event window end")
    parser.add_argument("--baseline-start", required=True, help="Inclusive YYYY-MM-DD reference window")
    parser.add_argument("--baseline-end", required=True, help="Exclusive YYYY-MM-DD reference window end")
    parser.add_argument("--min-backscatter-db", type=float, default=-16)
    parser.add_argument("--min-drop-db", type=float, default=-3)
    parser.add_argument("--max-slope-degrees", type=float, default=5)
    parser.add_argument("--permanent-water-occurrence-pct", type=float, default=80)
    parser.add_argument("--min-patch-area-m2", type=int, default=10000)
    parser.add_argument("--orbit-pass", choices=("ASCENDING", "DESCENDING"), default="ASCENDING")
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    return parser.parse_args()


def _validate_schema(cur: Any) -> None:
    required = {
        "ingestion_runs": {"id", "pipeline_name", "status", "metadata"},
        "datasets": {"dataset_key", "name", "source_type", "source_reference", "category"},
        "dataset_versions": {"dataset_key", "source_reference", "retrieved_at", "feature_count", "metadata", "processing_run_id"},
        "data_quality_checks": {"run_id", "dataset_key", "check_name", "status", "details"},
        "model_runs": {"id", "model_name", "model_version", "task", "parameters", "metrics", "status", "processing_run_id"},
        "hazard_events": {"id", "hazard_type", "evidence_kind", "dataset_key", "event_start", "event_end", "geom", "metadata", "processing_run_id"},
        "flood_extents": {"hazard_event_id", "method", "area_km2", "quality"},
        "energy_assets": {"id", "geom"},
        "asset_hazard_exposure": {"id", "energy_asset_id", "hazard_event_id", "hazard_type", "exposure_status", "evidence_kind", "provenance", "processing_run_id"},
        "administrative_units": {"id", "unit_level", "geom"},
        "asset_admin_assignments": {"energy_asset_id", "administrative_unit_id", "is_current"},
        "administrative_hazard_summaries": {"id", "administrative_unit_id", "event_fingerprint", "processing_run_id"},
        "spatial_coverage_assessments": {"id", "dataset_key", "processing_run_id", "coverage_status", "area_coverage_fraction", "observation_footprint", "valid_data_fraction", "quality_mask", "validation_status"},
    }
    table_names = list(required)
    cur.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=ANY(%s)", (table_names,))
    actual: dict[str, set[str]] = {}
    for table, column in cur.fetchall():
        actual.setdefault(table, set()).add(column)
    missing = [f"{table}.{column}" for table, columns in required.items() for column in sorted(columns - actual.get(table, set()))]
    if missing:
        raise RuntimeError("Apply database/schema.sql before running flood screening; missing: " + ", ".join(missing))


def _dataset_rows(cur: Any, run_id: str, quality: dict[str, Any]) -> None:
    source_counts = {
        "sentinel1_grd": quality["event_s1_image_count"] + quality["baseline_s1_image_count"],
        "chirps_daily": quality["chirps_image_count"],
        "dem_glo30": 1,
        "surface_water": 1,
    }
    for key, count in source_counts.items():
        spec = BY_KEY[key]
        cur.execute(
            """INSERT INTO datasets (dataset_key,name,source_type,source_reference,category,licence,attribution,is_optional)
               VALUES (%s,%s,'earth_engine_image_collection',%s,%s,%s,%s,TRUE)
               ON CONFLICT(dataset_key) DO UPDATE SET name=EXCLUDED.name,source_reference=EXCLUDED.source_reference,
                 category=EXCLUDED.category,licence=EXCLUDED.licence,attribution=EXCLUDED.attribution,updated_at=NOW()""",
            (key, spec.name, spec.collection_id, "satellite" if key in {"sentinel1_grd", "dem_glo30", "surface_water"} else "climate", spec.attribution, spec.attribution),
        )
        check_status = "passed" if count else "warning"
        version_metadata = {"method_version": METHOD_VERSION, "retrieved_count": count, "last_successful_retrieval": bool(count)}
        if key == "sentinel1_grd":
            version_metadata["event_scene_ids"] = quality["event_s1_scene_ids"]
            version_metadata["baseline_scene_ids"] = quality["baseline_s1_scene_ids"]
        cur.execute(
            "INSERT INTO dataset_versions (dataset_key,source_reference,retrieved_at,feature_count,metadata,processing_run_id) VALUES (%s,%s,NOW(),%s,%s::jsonb,%s)",
            (key, spec.collection_id, count, json.dumps(version_metadata), run_id),
        )
        cur.execute(
            "INSERT INTO data_quality_checks (run_id,dataset_key,check_name,status,details) VALUES (%s,%s,'event_window_retrieval',%s,%s::jsonb)",
            (run_id, key, check_status, json.dumps({"retrieved_image_or_asset_count": count})),
        )
        if count:
            cur.execute("UPDATE datasets SET last_ingested_at=NOW(),updated_at=NOW() WHERE dataset_key=%s", (key,))


def _persist_output(cur: Any, run_id: str, fingerprint: str, parameters: dict[str, Any], features: list[dict[str, Any]], quality: dict[str, Any]) -> dict[str, Any]:
    created = 0
    for feature in features:
        geometry = feature.get("geometry")
        if not geometry or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError("Earth Engine returned a candidate without polygon geometry")
        props = feature.get("properties", {})
        geometry_json = json.dumps(geometry, sort_keys=True, separators=(",", ":"))
        event_id = str(uuid.uuid5(NAMESPACE, fingerprint + ":" + geometry_json))
        area_m2 = float(props.get("sum", 0))
        compact_quality = {key: value for key, value in quality.items() if key != "event_observation_footprint"}
        metadata = {"event_fingerprint": fingerprint, "method_version": METHOD_VERSION, "parameters": parameters, "quality": compact_quality, "candidate_pixel_area_m2": area_m2, "candidate_label": "unvalidated_flood_candidate"}
        cur.execute(
            """INSERT INTO hazard_events (id,hazard_type,evidence_kind,dataset_key,event_start,event_end,source_reference,confidence,geom,metadata,processing_run_id)
               VALUES (%s,'flood','modeled','sentinel1_grd',%s::date,%s::date,'COPERNICUS/S1_GRD',NULL,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s::jsonb,%s)
               ON CONFLICT(id) DO UPDATE SET event_start=EXCLUDED.event_start,event_end=EXCLUDED.event_end,
                 source_reference=EXCLUDED.source_reference,geom=EXCLUDED.geom,metadata=EXCLUDED.metadata,processing_run_id=EXCLUDED.processing_run_id""",
            (event_id, parameters["event_start"], parameters["event_end"], geometry_json, json.dumps(metadata), run_id),
        )
        cur.execute(
            """INSERT INTO flood_extents (hazard_event_id,observation_start,observation_end,method,area_km2,quality)
               VALUES (%s,%s::date,%s::date,%s,%s,%s::jsonb)
               ON CONFLICT(hazard_event_id) DO UPDATE SET observation_start=EXCLUDED.observation_start,
                 observation_end=EXCLUDED.observation_end,method=EXCLUDED.method,area_km2=EXCLUDED.area_km2,quality=EXCLUDED.quality""",
            (event_id, parameters["event_start"], parameters["event_end"], METHOD_VERSION, area_m2 / 1_000_000, json.dumps(compact_quality)),
        )
        created += 1

    # Only positive spatial intersections are emitted. No intersection is not converted to a zero-risk score.
    cur.execute(
        """INSERT INTO asset_hazard_exposure
             (id,energy_asset_id,hazard_event_id,hazard_type,assessment_period_start,assessment_period_end,exposure_status,
              intersection_area_m2,intersection_length_m,evidence_kind,confidence,provenance,processing_run_id)
           SELECT md5(a.id::text || ':' || h.id::text || ':flood')::uuid,a.id,h.id,'flood',%s::date,%s::date,'exposed',
             CASE WHEN ST_Dimension(a.geom)=2 THEN ST_Area(ST_Intersection(a.geom,h.geom)::geography) END,
             CASE WHEN ST_Dimension(a.geom)=1 THEN ST_Length(ST_CollectionExtract(ST_Intersection(a.geom,h.geom),2)::geography) END,
             'modeled',NULL,jsonb_build_object('method_version',%s,'event_fingerprint',%s,'source_collection','COPERNICUS/S1_GRD','quality',%s::jsonb),%s
           FROM energy_assets a JOIN hazard_events h ON h.processing_run_id=%s AND h.hazard_type='flood' AND ST_Intersects(a.geom,h.geom)
           ON CONFLICT(id) DO UPDATE SET exposure_status=EXCLUDED.exposure_status,
             intersection_area_m2=EXCLUDED.intersection_area_m2,intersection_length_m=EXCLUDED.intersection_length_m,
             provenance=EXCLUDED.provenance,processing_run_id=EXCLUDED.processing_run_id""",
        (parameters["event_start"], parameters["event_end"], METHOD_VERSION, fingerprint, json.dumps(quality), run_id, run_id),
    )
    exposure_count = cur.rowcount
    # Refresh spatial membership and use boundary-specific clipped measures for line features.
    LOG.info("Updating current asset-to-ward/county intersections")
    assignment_count = refresh_asset_admin_assignments(cur, run_id)
    cur.execute(
        """WITH unit_asset AS (
             SELECT rel.administrative_unit_id,rel.energy_asset_id
             FROM asset_admin_assignments rel WHERE rel.is_current=TRUE
           ), counts AS (
             SELECT u.id AS unit_id,u.geom AS unit_geom,count(DISTINCT ua.energy_asset_id)::int AS asset_count,
                    count(DISTINCT e.energy_asset_id)::int AS exposed_count
             FROM administrative_units u LEFT JOIN unit_asset ua ON ua.administrative_unit_id=u.id
             LEFT JOIN asset_hazard_exposure e ON e.energy_asset_id=ua.energy_asset_id AND e.hazard_type='flood' AND e.processing_run_id=%s
             WHERE u.unit_level IN ('ward','county') AND ST_Intersects(u.geom,ST_MakeEnvelope(%s,%s,%s,%s,4326))
             GROUP BY u.id,u.geom
           )
           INSERT INTO administrative_hazard_summaries
             (id,administrative_unit_id,hazard_type,event_fingerprint,period_start,period_end,assessment_status,
              assigned_energy_asset_count,candidate_exposed_asset_count,candidate_exposure_fraction,provenance,processing_run_id)
           SELECT md5(unit_id::text || ':' || %s)::uuid,unit_id,'flood',%s,%s::date,%s::date,
             CASE WHEN %s > 0 AND ST_Covers(ST_MakeEnvelope(%s,%s,%s,%s,4326),unit_geom)
               THEN 'screened' ELSE 'insufficient_data' END,
             asset_count,exposed_count,NULL,jsonb_build_object('method_version',%s,'evidence_kind','modeled','summary_definition','assets intersecting unvalidated candidate polygons; fraction omitted because S1 spatial coverage can be incomplete'),%s
           FROM counts
           ON CONFLICT(administrative_unit_id,hazard_type,event_fingerprint) DO UPDATE SET
             period_start=EXCLUDED.period_start,period_end=EXCLUDED.period_end,assessment_status=EXCLUDED.assessment_status,
             assigned_energy_asset_count=EXCLUDED.assigned_energy_asset_count,candidate_exposed_asset_count=EXCLUDED.candidate_exposed_asset_count,
             candidate_exposure_fraction=NULL,provenance=EXCLUDED.provenance,processing_run_id=EXCLUDED.processing_run_id""",
        (run_id,*parameters["bbox"],fingerprint,fingerprint,parameters["event_start"],parameters["event_end"],quality["candidate_feature_count"],*parameters["bbox"],METHOD_VERSION,run_id),
    )
    summary_count = cur.rowcount
    footprint = quality.get("event_observation_footprint")
    if not footprint:
        raise RuntimeError("Sentinel-1 event observation footprint was not returned; coverage cannot be recorded")
    coverage_status = "partially_assessed" if quality["event_s1_coverage_fraction"] < 0.999 else "assessed"
    cur.execute(
        """INSERT INTO spatial_coverage_assessments
             (dataset_key,processing_run_id,hazard_type,evidence_kind,observation_start,observation_end,coverage_status,
              area_coverage_fraction,valid_data_fraction,observation_footprint,quality_mask,validation_status,limitations,provenance)
           VALUES ('sentinel1_grd',%s,'flood','modeled',%s::date,%s::date,%s,%s,NULL,
              ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s::jsonb,'not_validated',
              '["Scene-footprint fraction is not the same as valid per-pixel quality coverage.","Candidate method has not been independently validated for Kenya."]'::jsonb,
              %s::jsonb) ON CONFLICT DO NOTHING""",
        (run_id, parameters["event_start"], parameters["event_end"], coverage_status,
         quality["event_s1_coverage_fraction"], json.dumps(footprint),
         json.dumps({"event_scene_count": quality["event_s1_image_count"], "baseline_scene_count": quality["baseline_s1_image_count"], "orbit_pass": quality["sentinel1_orbit_pass"], "lake_mask_asset": quality["lake_mask_asset"]}),
         json.dumps({"method_version": METHOD_VERSION, "event_fingerprint": fingerprint})),
    )
    coverage_count = cur.rowcount
    quality.pop("event_observation_footprint", None)
    cur.execute("SELECT count(*) FROM hazard_events WHERE processing_run_id=%s AND hazard_type='flood' AND NOT ST_IsValid(geom)", (run_id,))
    invalid_geometry_count = cur.fetchone()[0]
    if invalid_geometry_count:
        raise RuntimeError(f"PostGIS geometry validation failed for {invalid_geometry_count} flood candidate(s)")
    return {"candidate_polygons": created, "exposure_rows_upserted": exposure_count, "boundary_assignments_upserted": assignment_count, "administrative_summary_rows_upserted": summary_count, "coverage_rows_upserted": coverage_count, "invalid_geometries": invalid_geometry_count}


def run(args: argparse.Namespace) -> dict[str, Any]:
    bbox = validate_bbox(args.bbox)
    parameters = {
        "bbox": bbox, "event_start": args.event_start, "event_end": args.event_end,
        "baseline_start": args.baseline_start, "baseline_end": args.baseline_end,
        "min_backscatter_db": args.min_backscatter_db, "min_drop_db": args.min_drop_db,
        "max_slope_degrees": args.max_slope_degrees,
        "permanent_water_occurrence_pct": args.permanent_water_occurrence_pct,
        "min_patch_area_m2": args.min_patch_area_m2, "orbit_pass": args.orbit_pass,
        "lake_mask_asset_id": os.getenv("GEE_ASSET_KENYA_LAKES", "").strip() or None,
        "method_version": METHOD_VERSION,
    }
    fingerprint = stable_event_fingerprint(parameters)
    run_id = str(uuid.uuid4())
    model_run_id = str(uuid.uuid4())
    url = database_url()
    if not url:
        raise RuntimeError("DB_URL, DATABASE_URL, or SUPABASE_DB_URL is required")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg[binary] is required; install requirements.txt") from exc

    project = os.getenv("GEE_PROJECT_ID", "").strip()
    if not project:
        raise RuntimeError("GEE_PROJECT_ID is required")
    from gee.auth import initialize_earth_engine
    if not initialize_earth_engine(project):
        raise RuntimeError("Earth Engine authentication failed")
    import ee

    with psycopg.connect(url, prepare_threshold=None, connect_timeout=15, options="-c statement_timeout=600000", application_name="oseas-flood-screen") as connection:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s),hashtext('writer'))", (INGEST_LOCK,))
            if not cur.fetchone()[0]:
                raise RuntimeError("Infrastructure ingestion is active; wait until all source pages finish before flood processing")
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s),hashtext('writer'))", (FLOOD_LOCK,))
            if not cur.fetchone()[0]:
                raise RuntimeError("Another OSEAS flood screen is active")
            _validate_schema(cur)
            cur.execute("SELECT status,metadata FROM ingestion_runs WHERE pipeline_name='oseas_earth_engine_ingest' ORDER BY started_at DESC LIMIT 1")
            latest = cur.fetchone()
            failed_assets = (latest[1] or {}).get("failed_assets", 0) if latest else 0
            if not latest or latest[0] not in ("completed", "partial") or failed_assets:
                raise RuntimeError(f"Latest infrastructure ingestion is not usable (status={latest[0] if latest else 'missing'}, failed_assets={failed_assets})")
            cur.execute("INSERT INTO ingestion_runs (id,pipeline_name,status,started_at,metadata) VALUES (%s,'oseas_sentinel1_flood_screen','running',NOW(),%s::jsonb)", (run_id, json.dumps({"parameters": parameters, "event_fingerprint": fingerprint})))
            cur.execute("INSERT INTO model_runs (id,model_name,model_version,task,parameters,metrics,status,started_at,processing_run_id) VALUES (%s,'Sentinel-1 relative-backscatter baseline',%s,'flood_candidate_screening',%s::jsonb,'{}'::jsonb,'running',NOW(),%s)", (model_run_id, METHOD_VERSION, json.dumps(parameters), run_id))
        connection.commit()

        try:
            LOG.info("Fetching Sentinel-1, CHIRPS, DEM, and permanent-water evidence for bbox=%s", bbox)
            features, quality = build_candidate_vectors(
                ee, bbox, args.event_start, args.event_end, args.baseline_start, args.baseline_end,
                args.min_backscatter_db, args.min_drop_db, args.max_slope_degrees,
                args.permanent_water_occurrence_pct, args.min_patch_area_m2, args.orbit_pass,
                parameters["lake_mask_asset_id"],
            )
            LOG.info("Earth Engine returned %s candidate polygons; storing bounded result", len(features))
            with connection.cursor() as cur:
                _dataset_rows(cur, run_id, quality)
                outputs = _persist_output(cur, run_id, fingerprint, parameters, features, quality)
                quality_status = "passed" if features else "warning"
                cur.execute("INSERT INTO data_quality_checks (run_id,dataset_key,check_name,status,details) VALUES (%s,'sentinel1_grd','candidate_polygon_validation',%s,%s::jsonb)", (run_id, quality_status, json.dumps({**quality, **outputs})))
                metrics = {**quality, **outputs, "validation_status": "not_validated_against_reference_flood_data"}
                cur.execute("UPDATE model_runs SET status='completed',finished_at=NOW(),metrics=%s::jsonb WHERE id=%s", (json.dumps(metrics), model_run_id))
                cur.execute("UPDATE ingestion_runs SET status='completed',finished_at=NOW(),metadata=metadata || %s::jsonb WHERE id=%s", (json.dumps({"quality": quality, "outputs": outputs, "model_run_id": model_run_id}), run_id))
            connection.commit()
            return {"run_id": run_id, "model_run_id": model_run_id, "status": "completed", "event_fingerprint": fingerprint, "quality": quality, "outputs": outputs}
        except Exception as error:
            connection.rollback()
            with connection.cursor() as cur:
                cur.execute("UPDATE model_runs SET status='failed',finished_at=NOW(),metrics=%s::jsonb WHERE id=%s", (json.dumps({"error_type": type(error).__name__, "error": str(error)[:1000]}), model_run_id))
                cur.execute("UPDATE ingestion_runs SET status='failed',finished_at=NOW(),error_message=%s,metadata=metadata || %s::jsonb WHERE id=%s", (str(error)[:1000], json.dumps({"error_type": type(error).__name__}), run_id))
            connection.commit()
            raise
        finally:
            with connection.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(hashtext(%s),hashtext('writer'))", (FLOOD_LOCK,))
                cur.execute("SELECT pg_advisory_unlock(hashtext(%s),hashtext('writer'))", (INGEST_LOCK,))


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    result = run(args)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        LOG.exception("Flood screening failed: %s", error)
        raise SystemExit(1)
