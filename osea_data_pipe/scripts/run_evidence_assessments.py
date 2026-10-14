"""Generate evidence-gated OSEAS decision-support outputs in PostGIS."""

from __future__ import annotations

import json
import sys
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

    with psycopg.connect(url, prepare_threshold=None, connect_timeout=15, options="-c statement_timeout=120000", application_name="oseas-evidence-assessments") as connection:
        with connection.cursor() as cur:
            cur.execute("""SELECT to_regclass('public.energy_assets'),to_regclass('public.asset_hazard_exposure'),
                to_regclass('public.asset_criticality_assessments'),to_regclass('public.service_dependency_assessments'),
                to_regclass('public.asset_vulnerability_assessments'),to_regclass('public.grid_resilience_assessments'),
                to_regclass('public.intervention_scenarios'),to_regclass('public.ingestion_runs')""")
            if not all(cur.fetchone()):
                raise RuntimeError("Assessment schema is incomplete; apply additive database/schema.sql and run npm run db:setup")
        print("Evidence assessment: reading current assets, measured exposures and explicitly verified service links", flush=True)
        # Keep each geospatial read/write transaction small enough for the
        # Supabase pooler. Stable evidence IDs make a retry safe after a drop.
        result = assess_assets(connection, batch_size=100)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Evidence assessment failed: {error}", file=sys.stderr)
        raise SystemExit(1)
