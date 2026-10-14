"""Persist point membership and clipped line/polygon measures to wards/counties."""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oseas.config import database_url
from oseas.spatial import refresh_asset_admin_assignment_batch

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
    connection_options = {"prepare_threshold": None, "connect_timeout": 20, "options": "-c statement_timeout=600000", "application_name": "oseas-admin-assignment"}

    def acquire_locks(connection):
        with connection.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s), hashtext('writer'))", ("oseas_earth_engine_ingest",))
            if not cur.fetchone()[0]:
                raise RuntimeError("OSEAS source ingestion is active; wait for it to finish before assigning boundaries")
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s), hashtext('writer'))", (LOCK_NAMESPACE,))
            if not cur.fetchone()[0]:
                raise RuntimeError("Another boundary assignment run is active")

    processed = 0
    assignment_rows = 0
    started = time.monotonic()
    connection = psycopg.connect(url, **connection_options)
    try:
        acquire_locks(connection)
        with connection.cursor() as cur:
            cur.execute("SELECT id FROM ingestion_runs WHERE pipeline_name='oseas_earth_engine_ingest' ORDER BY started_at DESC LIMIT 1")
            ingest = cur.fetchone()
            if not ingest:
                raise RuntimeError("No OSEAS infrastructure ingestion run exists")
            cur.execute("SELECT status,metadata FROM ingestion_runs WHERE id=%s", (ingest[0],))
            ingest_status, ingest_metadata = cur.fetchone()
            failed_assets = (ingest_metadata or {}).get("failed_assets", 0)
            if ingest_status not in ("completed", "partial") or failed_assets:
                raise RuntimeError(f"Latest OSEAS source ingestion is not usable for assignment (status={ingest_status}, failed_assets={failed_assets})")
            cur.execute("SELECT count(*) FROM energy_assets")
            total_assets = cur.fetchone()[0]
            cur.execute("SELECT id,status,metadata,finished_at FROM ingestion_runs WHERE pipeline_name='oseas_asset_admin_assignment' ORDER BY started_at DESC LIMIT 1")
            previous_assignment = cur.fetchone()
            cur.execute("SELECT count(*),count(DISTINCT energy_asset_id),max(updated_at) FROM asset_admin_assignments WHERE is_current=TRUE")
            current_rows, current_assets, latest_asset_update = cur.fetchone()
            if previous_assignment:
                previous_id, previous_status, previous_metadata, previous_finished = previous_assignment
                if isinstance(previous_metadata, str):
                    previous_metadata = json.loads(previous_metadata)
                if (previous_status == "completed"
                    and previous_metadata.get("source_ingestion_run_id") == str(ingest[0])
                    and previous_metadata.get("energy_assets_total") == total_assets
                    and previous_metadata.get("assignment_rows_upserted") == current_rows
                    and latest_asset_update is not None and latest_asset_update <= previous_finished):
                    cur.execute("SELECT pg_advisory_unlock(hashtext(%s), hashtext('writer'))", (LOCK_NAMESPACE,))
                    cur.execute("SELECT pg_advisory_unlock(hashtext(%s), hashtext('writer'))", ("oseas_earth_engine_ingest",))
                    connection.commit()
                    print(json.dumps({"status": "already_current", "assignment_run_id": str(previous_id),
                      "energy_assets_total": total_assets, "assigned_assets": current_assets,
                      "assignment_rows": current_rows}, indent=2))
                    return 0
            cur.execute("INSERT INTO ingestion_runs (id,pipeline_name,status,started_at,metadata) VALUES (%s,'oseas_asset_admin_assignment','running',NOW(),%s::jsonb)", (run_id, json.dumps({"source_ingestion_run_id": str(ingest[0]), "source_ingestion_status": ingest_status, "source_ingestion_failed_assets": failed_assets, "method": "point coverage; geometry intersection in EPSG:4326 with geodesic measures", "batch_size": 2000, "total_assets": total_assets})))
            cur.execute("UPDATE asset_admin_assignments SET is_current=FALSE WHERE is_current=TRUE")
        connection.commit()

        last_asset_id = "00000000-0000-0000-0000-000000000000"
        while processed < total_assets:
            with connection.cursor() as cur:
                cur.execute("SELECT id::text FROM energy_assets WHERE id>%s::uuid ORDER BY id LIMIT 2000", (last_asset_id,))
                batch_ids = [row[0] for row in cur.fetchall()]
                if not batch_ids:
                    break
                last_asset_id = batch_ids[-1]
                assignment_rows += refresh_asset_admin_assignment_batch(cur, run_id, batch_ids)
                processed += len(batch_ids)
                elapsed = time.monotonic() - started
                rate = processed / max(elapsed, 0.001)
                eta = max(total_assets - processed, 0) / max(rate, 0.001)
                cur.execute("UPDATE ingestion_runs SET metadata=metadata||%s::jsonb WHERE id=%s",
                  (json.dumps({"assets_processed": processed, "assignment_rows_upserted": assignment_rows}), run_id))
            connection.commit()
            print(f"Boundary assignments: assets={processed}/{total_assets}; rows={assignment_rows}; elapsed={elapsed:.0f}s; eta={eta:.0f}s", flush=True)
            if processed < total_assets and processed % 20000 == 0:
                connection.close()
                connection = psycopg.connect(url, **connection_options)
                acquire_locks(connection)
                print(f"Boundary assignments: database connection refreshed at asset {processed}", flush=True)

        with connection.cursor() as cur:
            cur.execute("SELECT unit_level,count(*) FROM asset_admin_assignments WHERE processing_run_id=%s GROUP BY unit_level", (run_id,))
            counts = {level: count for level, count in cur.fetchall()}
            cur.execute("SELECT count(DISTINCT energy_asset_id) FROM asset_admin_assignments WHERE processing_run_id=%s", (run_id,))
            assigned_count = cur.fetchone()[0]
            cur.execute("UPDATE ingestion_runs SET status='completed',finished_at=NOW(),metadata=metadata || %s::jsonb WHERE id=%s", (json.dumps({"assignment_rows_upserted": assignment_rows, "assignments_by_level": counts, "energy_assets_total": total_assets, "assets_assigned": assigned_count, "assets_without_assignment": total_assets-assigned_count}), run_id))
            cur.execute("SELECT pg_advisory_unlock(hashtext(%s), hashtext('writer'))", (LOCK_NAMESPACE,))
            cur.execute("SELECT pg_advisory_unlock(hashtext(%s), hashtext('writer'))", ("oseas_earth_engine_ingest",))
        connection.commit()
    except Exception as error:
        try:
            connection.rollback()
        except Exception:
            pass
        try:
            with psycopg.connect(url, **connection_options) as recovery:
                with recovery.cursor() as cur:
                    cur.execute("UPDATE ingestion_runs SET status='partial',finished_at=NOW(),error_message=%s,metadata=metadata||%s::jsonb WHERE id=%s AND status='running'", (str(error)[:4000], json.dumps({"assets_processed": processed, "assignment_rows_upserted": assignment_rows}), run_id))
                recovery.commit()
        except Exception:
            pass
        raise
    finally:
        connection.close()
    print(json.dumps({"run_id": run_id, "status": "completed", "assignment_rows_upserted": assignment_rows, "assignments_by_level": counts, "energy_assets_total": total_assets, "assets_assigned": assigned_count, "assets_without_assignment": total_assets-assigned_count}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"OSEAS boundary assignment failed: {error}", file=sys.stderr)
        raise SystemExit(1)
