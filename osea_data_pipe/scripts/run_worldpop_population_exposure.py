"""Estimate population within observed flood footprints using WorldPop counts."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oseas.config import database_url  # noqa: E402
from oseas.worldpop import (  # noqa: E402
    DATASET_KEY,
    attach_admin_units,
    events_from_local_unosat,
    persist_local_results,
    persist_summaries,
    summarize_footprints,
    _db_events,
)


def active_unosat_processes() -> list[str]:
    """Detect the current long-running local importer, including pre-lock legacy runs."""
    pattern = re.compile(r"scripts[/\\]ingest_unosat_flood_reference\.py", re.IGNORECASE)
    if os.name == "nt":
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
            r"Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(\.exe)?$' -and $_.CommandLine -match 'ingest_unosat_flood_reference\.py' } | Select-Object -ExpandProperty ProcessId | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError("Could not verify whether a UNOSAT importer process is active")
        output = result.stdout.strip()
        if not output:
            return []
        try:
            process_ids = json.loads(output)
        except json.JSONDecodeError as error:
            raise RuntimeError("Could not parse the UNOSAT process check") from error
        if not isinstance(process_ids, list):
            process_ids = [process_ids]
        return [str(pid) for pid in process_ids]
    proc_root = Path("/proc")
    if proc_root.exists():
        found = []
        for entry in proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            except OSError:
                continue
            if pattern.search(command) and "run_worldpop_population_exposure.py" not in command:
                found.append(entry.name)
        return found
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raster", type=Path, default=ROOT / "data/raw/worldpop/ken_pop_2024_CN_100m_R2025A_v1.tif")
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--source-dir", type=Path, default=ROOT / "KENYA_FLOOD_2024_SHP_UNOSAT")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/worldpop_unosat_2024.geojson")
    parser.add_argument("--persist", action="store_true", help="Persist summaries using already-ingested flood-reference rows")
    parser.add_argument("--include-administrative-units", action="store_true", help="Read county/ward polygons from PostGIS for a local, non-persistent zonal preview")
    args = parser.parse_args()
    if not args.raster.is_file():
        raise FileNotFoundError(f"WorldPop raster is missing: {args.raster}. Run npm run oseas:population:download first.")

    if args.persist:
        active_processes = active_unosat_processes()
        if active_processes:
            raise RuntimeError(f"UNOSAT importer process(es) {','.join(active_processes)} still exist; population persistence is paused")
        url = database_url()
        if not url:
            raise RuntimeError("DB_URL, DATABASE_URL, or SUPABASE_DB_URL is required for --persist")
        import psycopg

        with psycopg.connect(url, connect_timeout=15, options="-c statement_timeout=120000", application_name="oseas-worldpop-exposure") as connection:
            with connection.cursor() as cur:
                cur.execute("SELECT id::text FROM ingestion_runs WHERE pipeline_name='oseas_local_flood_reference_ingest' AND status='running' ORDER BY started_at DESC LIMIT 1")
                active = cur.fetchone()
                if active:
                    raise RuntimeError(f"UNOSAT reference ingestion run {active[0]} is still marked running; population persistence is paused to avoid overlapping writes")
                cur.execute("SELECT to_regclass('public.population_exposure_assessments'),to_regclass('public.spatial_coverage_assessments'),to_regclass('public.flood_reference_features')")
                if not all(cur.fetchone()):
                    raise RuntimeError("Population/exposure schema is missing; apply database/schema.sql and run npm run db:setup")
            events = _db_events(connection, "kenya_flood_2024_unosat")
            if not events:
                raise RuntimeError("No UNOSAT flood reference rows are persisted yet; finish the reference ingestion before --persist")
            # Attach county and ward units intersecting each event and summarize coverage.
            attach_admin_units(connection, events)
            summary = summarize_footprints(args.raster, events, year=args.year)
            result = persist_summaries(connection, summary, args.raster, "kenya_flood_2024_unosat",
                                       f"WorldPop Global2 R2025A v1, year {args.year}")
        print(json.dumps({"status": "completed", **result, "dataset_key": DATASET_KEY}, indent=2))
        return 0

    events = events_from_local_unosat(args.source_dir)
    if args.include_administrative_units:
        url = database_url()
        if not url:
            raise RuntimeError("DB_URL, DATABASE_URL, or SUPABASE_DB_URL is required for county/ward preview")
        import psycopg

        with psycopg.connect(url, connect_timeout=15, options="-c default_transaction_read_only=on -c statement_timeout=120000", application_name="oseas-worldpop-admin-preview") as connection:
            attach_admin_units(connection, events)
    summary = summarize_footprints(args.raster, events, year=args.year)
    persist_local_results(args.output, summary, args.raster)
    print(json.dumps({"status": "local_preview_only", "output": str(args.output),
                      "events": [{"event_key": event["event_key"], "source_feature_count": event["source_feature_count"],
                                  "event_population_estimate": event["zones"][0]["population"],
                                  "valid_raster_fraction": event["zones"][0]["valid_fraction"]}
                                 for event in summary["events"]],
                      "database_written": False, "limitations": summary["limitations"]}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"WorldPop population exposure failed: {error}", file=sys.stderr)
        raise SystemExit(1)
