"""Mark abandoned OSEAS importer runs failed without changing ingested feature rows."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oseas.config import database_url
from oseas.ingest import LOCK_NAMESPACE

UNOSAT_LOCK = "oseas_local_flood_reference_ingest"
SAR_FLOOD_LOCK = "oseas_sar_flood_screen"
PRITHVI_LOCK = "oseas_prithvi_flood_screen"
STALE_AFTER_MINUTES = 30


def main() -> int:
    url = database_url()
    if not url:
        raise RuntimeError("DB_URL, DATABASE_URL, or SUPABASE_DB_URL is required")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg[binary] is required; install requirements.txt") from exc

    with psycopg.connect(url, prepare_threshold=None, connect_timeout=15, application_name="oseas-run-recovery") as connection:
        recovered: dict[str, list[str]] = {}
        with connection.cursor() as cur:
            # Acquire every writer guard before changing status. Active runs on
            # another process or teammate's machine keep their session lock and
            # make recovery stop without modifying any run records.
            locks = [
                ("writer", LOCK_NAMESPACE, True),
                ("UNOSAT", UNOSAT_LOCK, False),
                ("Sentinel-1", SAR_FLOOD_LOCK, True),
                ("Prithvi", PRITHVI_LOCK, True),
            ]
            for label, lock_name, two_key in locks:
                if two_key:
                    cur.execute("SELECT pg_try_advisory_lock(hashtext(%s), hashtext('writer'))", (lock_name,))
                else:
                    cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (lock_name,))
                if not cur.fetchone()[0]:
                    raise RuntimeError(f"An OSEAS {label} process is active; no run records were changed")

            pipelines = (
                "oseas_earth_engine_ingest",
                "oseas_local_flood_reference_ingest",
                "oseas_sentinel1_flood_screen",
                "oseas_prithvi_flood_screen",
            )
            for pipeline_name in pipelines:
                cur.execute(
                    """UPDATE ingestion_runs
                       SET status = 'failed', finished_at = NOW(),
                           error_message = COALESCE(error_message, 'Process ended without recording a final status; stale run recovered'),
                           metadata = metadata || jsonb_build_object(
                             'interrupted', TRUE,
                             'interruption_reason', 'No matching active writer lock; run exceeded the stale-run threshold',
                             'recovered_at', NOW()
                           )
                       WHERE pipeline_name = %s AND status = 'running'
                         AND started_at < NOW() - (%s * INTERVAL '1 minute')
                       RETURNING id""",
                    (pipeline_name, STALE_AFTER_MINUTES),
                )
                run_ids = [str(row[0]) for row in cur.fetchall()]
                recovered[pipeline_name] = run_ids
                if pipeline_name in ("oseas_sentinel1_flood_screen", "oseas_prithvi_flood_screen") and run_ids:
                    cur.execute(
                        """UPDATE model_runs
                           SET status = 'failed', finished_at = NOW(),
                               metrics = metrics || jsonb_build_object(
                                 'interrupted', TRUE,
                                 'error', 'Processing process ended before model output was committed'
                               )
                           WHERE processing_run_id = ANY(%s::uuid[]) AND status = 'running'""",
                        (run_ids,),
                    )

            for _, lock_name, two_key in reversed(locks):
                if two_key:
                    cur.execute("SELECT pg_advisory_unlock(hashtext(%s), hashtext('writer'))", (lock_name,))
                else:
                    cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (lock_name,))
        connection.commit()
    print(json.dumps({"recovered_runs": recovered, "feature_rows_changed": False, "stale_after_minutes": STALE_AFTER_MINUTES}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"OSEAS run recovery failed: {error}", file=sys.stderr)
        raise SystemExit(1)
