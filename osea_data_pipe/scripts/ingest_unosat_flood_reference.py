"""Audit or ingest the bundled 2024 UNOSAT flood reference shapefiles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oseas.config import database_url  # noqa: E402
from oseas.local_flood_reference import DEFAULT_SOURCE_DIR, ingest_reference, inspect_reference  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-only", action="store_true", help="Validate local shapefiles without database writes")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    args = parser.parse_args()

    report = inspect_reference(args.input_dir, progress=True)
    if args.audit_only:
        print(json.dumps(report, indent=2))
        return 0

    url = database_url()
    if not url:
        raise RuntimeError("DB_URL, DATABASE_URL, or SUPABASE_DB_URL is required")
    import psycopg

    with psycopg.connect(url, connect_timeout=15, options="-c statement_timeout=120000", application_name="oseas-unosat-reference") as connection:
        with connection.cursor() as cur:
            cur.execute("""SELECT to_regclass('public.flood_reference_features'), to_regclass('public.ingestion_runs'),
                                 to_regclass('public.datasets'), to_regclass('public.dataset_versions'),
                                 to_regclass('public.data_quality_checks')""")
            tables = cur.fetchone()
            if not all(tables):
                raise RuntimeError("OSEAS reference schema is missing; apply database/schema.sql and run npm run db:setup first")
        result = ingest_reference(connection, args.input_dir, summary=report)
    print(json.dumps({**report, **result}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"UNOSAT reference ingestion failed: {error}", file=sys.stderr)
        raise SystemExit(1)
