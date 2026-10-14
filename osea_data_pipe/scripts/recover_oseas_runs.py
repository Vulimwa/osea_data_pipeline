"""Mark abandoned OSEAS importer runs failed without changing ingested feature rows."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oseas.config import database_url
from oseas.ingest import LOCK_NAMESPACE


def main() -> int:
    url = database_url()
    if not url:
        raise RuntimeError("DB_URL, DATABASE_URL, or SUPABASE_DB_URL is required")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg[binary] is required; install requirements.txt") from exc

    with psycopg.connect(url, connect_timeout=15, application_name="oseas-run-recovery") as connection:
        recovered: dict[str, list[str]] = {}
        with connection.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s), hashtext('writer'))", (LOCK_NAMESPACE,))
            if not cur.fetchone()[0]:
                raise RuntimeError("An OSEAS ingestion process is active; no run records were changed")
            cur.execute(
                """UPDATE ingestion_runs
                   SET status = 'failed', finished_at = NOW(),
                       metadata = metadata || jsonb_build_object(
                         'interrupted', TRUE,
                         'interruption_reason', 'Previous ingestion process ended before recording a final status',
                         'recovered_at', NOW()
                       )
                   WHERE pipeline_name = 'oseas_earth_engine_ingest' AND status = 'running'
                   RETURNING id"""
            )
            recovered["oseas_earth_engine_ingest"] = [str(row[0]) for row in cur.fetchall()]
            cur.execute("SELECT pg_advisory_unlock(hashtext(%s), hashtext('writer'))", (LOCK_NAMESPACE,))
            # This session lock is the write guard used by the local UNOSAT importer.
            # Acquiring it proves no local importer currently owns this write path.
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", ("oseas_local_flood_reference_ingest",))
            if not cur.fetchone()[0]:
                raise RuntimeError("A UNOSAT reference ingestion process is active; its run was not changed")
            cur.execute(
                """UPDATE ingestion_runs
                   SET status = 'failed', finished_at = NOW(),
                       metadata = metadata || jsonb_build_object(
                         'interrupted', TRUE,
                         'interruption_reason', 'Previous ingestion process ended before recording a final status',
                         'recovered_at', NOW()
                       )
                   WHERE pipeline_name = 'oseas_local_flood_reference_ingest' AND status = 'running'
                   RETURNING id"""
            )
            recovered["oseas_local_flood_reference_ingest"] = [str(row[0]) for row in cur.fetchall()]
            cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", ("oseas_local_flood_reference_ingest",))
        connection.commit()
    print(json.dumps({"recovered_runs": recovered, "feature_rows_changed": False}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"OSEAS run recovery failed: {error}", file=sys.stderr)
        raise SystemExit(1)
