"""Generate evidence-gated OSEAS decision-support outputs in PostGIS."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oseas.assessments import assess_assets  # noqa: E402
from oseas.config import database_url  # noqa: E402


def main() -> int:
    url = database_url()
    if not url:
        raise RuntimeError("DB_URL, DATABASE_URL, or SUPABASE_DB_URL is required")
    import psycopg

    result = None
    for attempt in range(1, 9):
        connection = None
        try:
            connection = psycopg.connect(url, prepare_threshold=None, connect_timeout=15,
                options="-c statement_timeout=120000", application_name="oseas-evidence-assessments")
            if attempt == 1:
                with connection.cursor() as cur:
                    cur.execute("""SELECT to_regclass('public.energy_assets'),to_regclass('public.asset_hazard_exposure'),
                        to_regclass('public.asset_criticality_assessments'),to_regclass('public.service_dependency_assessments'),
                        to_regclass('public.asset_vulnerability_assessments'),to_regclass('public.grid_resilience_assessments'),
                        to_regclass('public.intervention_scenarios'),to_regclass('public.ingestion_runs')""")
                    if not all(cur.fetchone()):
                        raise RuntimeError("Assessment schema is incomplete; apply additive database/schema.sql and run npm run db:setup")
            print(f"Evidence assessment: resuming durable database checkpoint (attempt {attempt}/8)", flush=True)
            # Stable evidence IDs and per-batch checkpoints make reconnect retries idempotent.
            result = assess_assets(connection, batch_size=250, connection_dsn=url)
            break
        except Exception as error:
            if attempt == 8:
                raise
            delay = min(attempt * 5, 30)
            print(f"Assessment connection/run interrupted; committed batches are preserved. Retrying in {delay}s: {error}", flush=True)
            time.sleep(delay)
        finally:
            if connection is not None and not connection.closed:
                connection.close()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Evidence assessment failed: {error}", file=sys.stderr)
        raise SystemExit(1)
