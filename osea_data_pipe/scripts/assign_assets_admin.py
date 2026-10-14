"""Persist point membership and clipped line/polygon measures to wards/counties."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oseas.config import database_url
from oseas.spatial import refresh_asset_admin_assignments

LOCK_NAMESPACE = "oseas_asset_admin_assignment"


def main() -> int:
    url = database_url()
    if not url:
        raise RuntimeError("DB_URL, DATABASE_URL, or SUPABASE_DB_URL is required")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg[binary] is required; install requirements.txt") from exc

    run_id = str(uuid.uuid4())
    with psycopg.connect(url, prepare_threshold=None, connect_timeout=15, options="-c statement_timeout=600000", application_name="oseas-admin-assignment") as connection:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s), hashtext('writer'))", ("oseas_earth_engine_ingest",))
            if not cur.fetchone()[0]:
                raise RuntimeError("OSEAS source ingestion is active; wait for it to finish before assigning boundaries")
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s), hashtext('writer'))", (LOCK_NAMESPACE,))
            if not cur.fetchone()[0]:
                raise RuntimeError("Another boundary assignment run is active")
            cur.execute("SELECT id FROM ingestion_runs WHERE pipeline_name='oseas_earth_engine_ingest' ORDER BY started_at DESC LIMIT 1")
            ingest = cur.fetchone()
            if not ingest:
                raise RuntimeError("No OSEAS infrastructure ingestion run exists")
            cur.execute("SELECT status,metadata FROM ingestion_runs WHERE id=%s", (ingest[0],))
            ingest_status, ingest_metadata = cur.fetchone()
            failed_assets = (ingest_metadata or {}).get("failed_assets", 0)
            if ingest_status not in ("completed", "partial") or failed_assets:
                raise RuntimeError(f"Latest OSEAS source ingestion is not usable for assignment (status={ingest_status}, failed_assets={failed_assets})")

            cur.execute("INSERT INTO ingestion_runs (id,pipeline_name,status,started_at,metadata) VALUES (%s,'oseas_asset_admin_assignment','running',NOW(),%s::jsonb)", (run_id, json.dumps({"source_ingestion_run_id": str(ingest[0]), "source_ingestion_status": ingest_status, "source_ingestion_failed_assets": failed_assets, "method": "point coverage; geometry intersection in EPSG:4326 with geodesic measures"})))
            assignment_rows = refresh_asset_admin_assignments(cur, run_id)
            cur.execute("SELECT unit_level,count(*) FROM asset_admin_assignments WHERE processing_run_id=%s GROUP BY unit_level", (run_id,))
            counts = {level: count for level, count in cur.fetchall()}
            cur.execute("SELECT count(*) FROM energy_assets")
            asset_count = cur.fetchone()[0]
            cur.execute("SELECT count(DISTINCT energy_asset_id) FROM asset_admin_assignments WHERE processing_run_id=%s", (run_id,))
            assigned_count = cur.fetchone()[0]
            cur.execute("UPDATE ingestion_runs SET status='completed',finished_at=NOW(),metadata=metadata || %s::jsonb WHERE id=%s", (json.dumps({"assignment_rows_upserted": assignment_rows, "assignments_by_level": counts, "energy_assets_total": asset_count, "assets_assigned": assigned_count, "assets_without_assignment": asset_count-assigned_count}), run_id))
            cur.execute("SELECT pg_advisory_unlock(hashtext(%s), hashtext('writer'))", (LOCK_NAMESPACE,))
            cur.execute("SELECT pg_advisory_unlock(hashtext(%s), hashtext('writer'))", ("oseas_earth_engine_ingest",))
        connection.commit()
    print(json.dumps({"run_id": run_id, "status": "completed", "assignment_rows_upserted": assignment_rows, "assignments_by_level": counts, "energy_assets_total": asset_count, "assets_assigned": assigned_count, "assets_without_assignment": asset_count-assigned_count}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"OSEAS boundary assignment failed: {error}", file=sys.stderr)
        raise SystemExit(1)
