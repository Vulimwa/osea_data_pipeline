"""Run the configured OSEAS acquisition and assessment chain in dependency order."""

from __future__ import annotations

import argparse
from collections import deque
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LOCK = ROOT / "data" / ".oseas_pipeline.lock"
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def acquire_lock() -> None:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(2):
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat()}, stream)
            return
        except FileExistsError:
            try:
                owner = json.loads(LOCK.read_text(encoding="utf-8"))
                pid = int(owner.get("pid", -1))
            except (OSError, ValueError, json.JSONDecodeError):
                pid = -1
            if pid > 0 and _pid_alive(pid):
                raise RuntimeError(f"OSEAS pipeline is already running (PID {pid}); refusing duplicate run")
            if attempt == 0:
                LOCK.unlink(missing_ok=True)
    raise RuntimeError("Could not acquire the OSEAS pipeline lock")


def run_stage(
    name: str,
    command: list[str],
    stages: list[dict[str, object]],
    *,
    skip_reason: str | None = None,
    accepted_exit_codes: tuple[int, ...] = (0,),
) -> bool:
    if skip_reason:
        print(f"\n[{name}] SKIPPED: {skip_reason}", flush=True)
        stages.append({"stage": name, "status": "blocked", "reason": skip_reason})
        return False
    print(f"\n[{name}] START {datetime.now(timezone.utc).isoformat()}", flush=True)
    started = time.monotonic()
    try:
        result = subprocess.run(command, cwd=ROOT, check=False)
    except OSError as error:
        duration = round(time.monotonic() - started, 1)
        print(f"[{name}] FAILED to start ({type(error).__name__})", flush=True)
        stages.append({"stage": name, "status": "failed", "reason": f"Could not start stage ({type(error).__name__})",
                       "duration_seconds": duration})
        return False
    duration = round(time.monotonic() - started, 1)
    status = "completed" if result.returncode == 0 else (
        "partial" if result.returncode in accepted_exit_codes else "failed"
    )
    print(f"[{name}] {status.upper()} exit={result.returncode} duration={duration}s", flush=True)
    stages.append({"stage": name, "status": status, "exit_code": result.returncode, "duration_seconds": duration})
    return result.returncode in accepted_exit_codes


def python_run(script: str, *arguments: str) -> list[str]:
    return [sys.executable, script, *arguments]


def active_python_processes(script_fragment: str) -> list[str]:
    """Find an existing source job before starting a duplicate acquisition."""
    if os.name == "nt":
        command = (
            "$items = @(Get-CimInstance Win32_Process | Where-Object { "
            r"$_.Name -match '^python(w)?(\.exe)?$' -and $_.CommandLine -match "
            f"'{re.escape(script_fragment)}'"
            "} | Select-Object -ExpandProperty ProcessId); "
            "ConvertTo-Json -Compress -InputObject $items"
        )
        result = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                                capture_output=True, text=True, timeout=15, check=False)
        if result.returncode != 0:
            raise RuntimeError("Could not check for an active source-processing process")
        output = result.stdout.strip()
        if not output:
            return []
        try:
            process_ids = json.loads(output)
        except json.JSONDecodeError as error:
            raise RuntimeError("Could not parse the active source-process check") from error
        if process_ids is None:
            return []
        if not isinstance(process_ids, list):
            process_ids = [process_ids]
        return [str(pid) for pid in process_ids]

    proc_root = Path("/proc")
    if not proc_root.exists():
        return []
    active = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command_line = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if script_fragment in command_line and "run_oseas_pipeline.py" not in command_line:
            active.append(entry.name)
    return active


def validate_ntl_result(status: str, metadata: dict[str, object], stored_rows: int,
                        expected_recent: list[str] | None = None,
                        expected_baseline: list[str] | None = None) -> tuple[bool, str]:
    """Require the complete three-measure result set for every summarized zone."""
    try:
        zone_count = int(metadata.get("requested_zone_count", 0))
        inserted_rows = int(metadata.get("persisted_observations", 0))
        stored_rows = int(stored_rows)
    except (TypeError, ValueError):
        return False, "Night-lights run metadata has invalid row or zone counts"
    expected_rows = zone_count * 3
    if status != "completed":
        return False, f"Night-lights processing ended with database status '{status}'"
    if zone_count <= 0 or inserted_rows != expected_rows or stored_rows != expected_rows:
        return False, (f"Night-lights result is incomplete: expected {expected_rows:,} rows, "
                       f"run metadata reports {inserted_rows:,}, database contains {stored_rows:,}")
    if expected_recent and metadata.get("recent_period") != expected_recent:
        return False, "Night-lights result period does not match OSEAS_NTL_START_MONTH / OSEAS_NTL_END_MONTH"
    if expected_baseline and metadata.get("baseline_period") != expected_baseline:
        return False, "Night-lights baseline does not match OSEAS_NTL_BASELINE_START_MONTH / OSEAS_NTL_BASELINE_END_MONTH"
    return True, f"verified {stored_rows:,} persisted rows across {zone_count:,} zones"


def validate_inventory_result(status: str, metadata: dict[str, object]) -> tuple[bool, str]:
    """Require current county and ward source rows before refreshing dependent outputs."""
    if status not in {"completed", "partial"}:
        return False, f"latest inventory run is {status!r}, not usable"
    try:
        failed_assets = int(metadata.get("failed_assets", -1))
    except (TypeError, ValueError):
        return False, "latest inventory run has invalid failed-asset metadata"
    if failed_assets != 0:
        return False, f"latest inventory run reports {failed_assets} failed asset(s)"

    assets = metadata.get("assets")
    if not isinstance(assets, list):
        return False, "latest inventory run does not contain per-source results"
    by_key = {
        str(asset.get("dataset_key")): asset
        for asset in assets
        if isinstance(asset, dict) and asset.get("dataset_key")
    }
    for key in ("kenya_counties", "kenya_wards"):
        asset = by_key.get(key)
        if asset is None:
            return False, f"latest inventory run did not include required boundary source {key}"
        if asset.get("status") not in {"completed", "partial"}:
            return False, f"required boundary source {key} ended with status {asset.get('status')!r}"
        try:
            persisted = int(asset.get("features_persisted", 0))
        except (TypeError, ValueError):
            return False, f"required boundary source {key} has invalid persisted-feature metadata"
        if persisted <= 0:
            return False, f"required boundary source {key} persisted no boundary features"
        try:
            skipped = int(asset.get("features_skipped_geometry", 0))
        except (TypeError, ValueError):
            return False, f"required boundary source {key} has invalid skipped-geometry metadata"
        if skipped:
            return False, f"required boundary source {key} skipped {skipped} feature(s) with unusable geometry"
    return True, "latest run has persisted county and ward boundaries and no failed source assets"


def verify_latest_inventory(not_before: datetime | None = None) -> tuple[bool, str]:
    """Read-only verification of the newest inventory run before dependent processing."""
    from oseas.config import database_url

    url = database_url()
    if not url:
        return False, "database connection is not configured"
    try:
        import psycopg
    except ImportError:
        return False, "psycopg is unavailable; cannot verify the latest inventory run"

    try:
        with psycopg.connect(
            url,
            connect_timeout=15,
            options="-c default_transaction_read_only=on -c statement_timeout=30000",
            application_name="oseas-pipeline-inventory-check",
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                  SELECT status,metadata,started_at
                  FROM ingestion_runs
                  WHERE pipeline_name='oseas_earth_engine_ingest'
                  ORDER BY started_at DESC
                  LIMIT 1
                """)
                row = cursor.fetchone()
    except psycopg.Error as error:
        return False, f"could not read the latest inventory run ({type(error).__name__})"
    if row is None:
        return False, "no Earth Engine inventory run is recorded in the database"
    status, metadata, started_at = row
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if not_before is not None and started_at < not_before:
        return False, "no inventory run started during this pipeline invocation"
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            return False, "latest inventory run contains invalid JSON metadata"
    if not isinstance(metadata, dict):
        return False, "latest inventory run contains invalid metadata"
    return validate_inventory_result(str(status), metadata)


def latest_ntl_progress() -> str:
    path = ROOT / "outputs" / "logs" / "nightlights.stdout.log"
    if not path.is_file():
        return ""
    tail: deque[str] = deque(maxlen=4)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            tail.extend(line.rstrip() for line in stream)
    except OSError:
        return ""
    return " | ".join(line for line in tail if line)


def verify_ntl_result(completed_after: datetime | None = None) -> dict[str, object] | None:
    """Read back the completed night-lights run and its rows; never trusts exit text alone."""
    from oseas.config import database_url
    import psycopg

    url = database_url()
    if not url:
        raise RuntimeError("database connection is not configured")
    with psycopg.connect(url, connect_timeout=15) as connection:
        with connection.cursor() as cursor:
            query = """
              SELECT id::text,status,metadata,finished_at
              FROM ingestion_runs
              WHERE pipeline_name='oseas_viirs_black_marble' AND status='completed'
            """
            if completed_after is not None:
                query += " AND finished_at >= %s"
            query += " ORDER BY finished_at DESC LIMIT 1"
            cursor.execute(query, (completed_after,) if completed_after is not None else ())
            run = cursor.fetchone()
            if not run:
                return None
            run_id, status, metadata, finished_at = run
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            cursor.execute("""
              SELECT COUNT(*) FROM climate_observations
              WHERE processing_run_id=%s::uuid AND dataset_key='nasa_viirs_black_marble_monthly'
            """, (run_id,))
            stored_rows = int(cursor.fetchone()[0])
    start_month = os.getenv("OSEAS_NTL_START_MONTH", "").strip()
    end_month = os.getenv("OSEAS_NTL_END_MONTH", "").strip()
    baseline_start = os.getenv("OSEAS_NTL_BASELINE_START_MONTH", "2012-01").strip()
    baseline_end = os.getenv("OSEAS_NTL_BASELINE_END_MONTH", "2015-12").strip()
    expected_recent = None
    if start_month and end_month:
        expected_recent = [f"{start_month}-01", f"{end_month}-01"]
    expected_baseline = [baseline_start, baseline_end] if baseline_start and baseline_end else None
    valid, detail = validate_ntl_result(str(status), metadata or {}, stored_rows,
                                        expected_recent, expected_baseline)
    if not valid:
        raise RuntimeError(detail)
    return {"run_id": run_id, "finished_at": finished_at.isoformat(), "detail": detail}


def wait_for_active_ntl(active_pids: list[str], stages: list[dict[str, object]], timeout_minutes: int) -> bool:
    """Wait for an already-running Black Marble job, then verify its persisted output."""
    started = datetime.now(timezone.utc)
    timeout_seconds = timeout_minutes * 60
    last_report = 0.0
    print("\n[NASA VIIRS Black Marble monthly radiance and context] WAITING: "
          f"active process(es) {','.join(active_pids)}; will not launch a duplicate", flush=True)
    while active_pids:
        elapsed = time.monotonic() - last_report
        if elapsed >= 60:
            progress = latest_ntl_progress()
            if progress:
                print(f"[NASA VIIRS Black Marble] still running; {progress}", flush=True)
            else:
                elapsed_seconds = int((datetime.now(timezone.utc) - started).total_seconds())
                print(f"[NASA VIIRS Black Marble] still running; elapsed={elapsed_seconds}s", flush=True)
            last_report = time.monotonic()
        if timeout_seconds and (datetime.now(timezone.utc) - started).total_seconds() >= timeout_seconds:
            stages.append({"stage": "NASA VIIRS Black Marble monthly radiance and context", "status": "failed",
                           "reason": f"Waited {timeout_minutes} minutes for the existing process; it remains active. "
                                     "The process was left running and must not be duplicated."})
            return False
        try:
            time.sleep(20)
            active_pids = active_python_processes("ingest_viirs_black_marble.py")
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            stages.append({"stage": "NASA VIIRS Black Marble monthly radiance and context", "status": "failed",
                           "reason": f"Could not safely monitor active process ({type(error).__name__}); no duplicate was started"})
            return False

    print("[NASA VIIRS Black Marble] process exited; verifying committed database output", flush=True)
    try:
        result = verify_ntl_result(started)
        if result is None:
            # The process may have finished between process discovery and the
            # first polling pass. Reuse a complete matching output if present.
            result = verify_ntl_result()
    except Exception as error:
        stages.append({"stage": "NASA VIIRS Black Marble monthly radiance and context", "status": "failed",
                       "reason": f"Existing process ended but output verification failed ({type(error).__name__})"})
        return False
    if result is None:
        stages.append({"stage": "NASA VIIRS Black Marble monthly radiance and context", "status": "failed",
                       "reason": "Existing process ended without a newly completed database run; check outputs/logs/nightlights.stderr.log"})
        return False
    stages.append({"stage": "NASA VIIRS Black Marble monthly radiance and context", "status": "completed",
                   "external_process": True, **result})
    print(f"[NASA VIIRS Black Marble] COMPLETED: {result['detail']}; run={result['run_id']}", flush=True)
    return True


def build_report(
    stages: list[dict[str, object]],
    started_at: str,
    image_downloads_enabled: bool = False,
) -> dict[str, object]:
    incomplete = [stage for stage in stages if stage["status"] in {"failed", "blocked", "partial"}]
    return {
        "status": "partial" if incomplete else "completed_with_limitations",
        "started_at": started_at,
        "stages": stages,
        "incomplete_stage_count": len(incomplete),
        "unsupported_or_unconfigured_sources": [
            "Landsat land-surface temperature (NASA POWER provides air temperature only)",
            "burned-area perimeters and independent fire-damage evidence",
            "standalone ERA5 outputs and reusable national DEM-derived drainage metrics",
            "validated Kenya-specific Prithvi metrics and verified feeder/outage records",
        ],
        "duplication_policy": "Stable source keys, deterministic assessment IDs, source-content fingerprints and source-specific locks; same-input outputs are upserted or resumed.",
        "database_write_policy": "Existing source and assessment rows are preserved; writers use stable-key upserts or append-only run provenance.",
        "map_output_policy": "Persisted products are served from PostGIS through the read-only OSEAS API under /api/v1/oseas; blocked stages do not imply an empty or complete map layer.",
        "image_downloads_enabled": image_downloads_enabled,
    }


def write_report(report: dict[str, object]) -> None:
    report_path = ROOT / "outputs" / "last_pipeline_run.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = report_path.with_suffix(".json.tmp")
    temporary_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temporary_path.replace(report_path)
    print("\nOSEAS PIPELINE SUMMARY", flush=True)
    print(json.dumps(report, indent=2), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-earth-engine", action="store_true", help="Use already-ingested source features")
    parser.add_argument("--skip-worldpop-download", action="store_true", help="Require the selected WorldPop raster to exist locally")
    parser.add_argument(
        "--allow-image-downloads",
        action="store_true",
        help="Opt in to local WorldPop, Black Marble, and Prithvi image workflows",
    )
    parser.add_argument("--active-ntl-timeout-minutes", type=int,
                        default=int(os.getenv("OSEAS_PIPELINE_ACTIVE_NTL_TIMEOUT_MINUTES", "1440")),
                        help="Wait limit for an already-running night-lights job (default: 24 hours; 0 waits indefinitely)")
    args = parser.parse_args()
    if args.active_ntl_timeout_minutes < 0:
        parser.error("--active-ntl-timeout-minutes must be zero or greater")
    stages: list[dict[str, object]] = []
    pipeline_started_at = datetime.now(timezone.utc).isoformat()
    acquire_lock()
    try:
        if not run_stage("database preflight", ["node", "scripts/setup_database.js"], stages):
            write_report(build_report(stages, pipeline_started_at, args.allow_image_downloads))
            return 1

        if args.skip_earth_engine or os.getenv("OSEAS_PIPELINE_SKIP_EE", "").lower() in {"1", "true", "yes"}:
            print("\n[Earth Engine source ingestion] SKIPPED: explicit skip; verifying persisted county/ward inventory", flush=True)
            stages.append({"stage": "Earth Engine source ingestion", "status": "skipped", "reason": "explicit skip"})
            ingestion_ok, inventory_detail = verify_latest_inventory()
        else:
            ingestion_ok = run_stage(
                "Earth Engine source ingestion",
                python_run("-m", "oseas.ingest"),
                stages,
                accepted_exit_codes=(0, 2),
            )
            if ingestion_ok:
                ingestion_ok, inventory_detail = verify_latest_inventory(
                    datetime.fromisoformat(pipeline_started_at),
                )
            else:
                inventory_detail = "source importer returned a fatal error"

        if stages and stages[-1]["stage"] == "Earth Engine source ingestion":
            stages[-1]["inventory_verification"] = inventory_detail
            if not ingestion_ok and stages[-1]["status"] == "skipped":
                stages[-1]["status"] = "blocked"
                stages[-1]["reason"] = inventory_detail
            elif not ingestion_ok and stages[-1]["status"] in {"completed", "partial"}:
                stages[-1]["status"] = "failed"
                stages[-1]["reason"] = inventory_detail

        if ingestion_ok:
            assignment_ok = run_stage(
                "asset-to-county-and-ward assignment",
                python_run("scripts/assign_assets_admin.py"),
                stages,
            )
            if assignment_ok:
                run_stage("NASA POWER heat acquisition and exposure", python_run("scripts/ingest_nasa_power_heat.py"), stages)
            else:
                stages.append({"stage": "NASA POWER heat acquisition and exposure", "status": "blocked",
                               "reason": "county/ward assignment refresh failed"})
        else:
            assignment_ok = False
            stages.append({"stage": "asset-to-county-and-ward assignment", "status": "blocked", "reason": "source ingestion failed"})
            stages.append({"stage": "NASA POWER heat acquisition and exposure", "status": "blocked", "reason": "no configured asset inventory update completed"})

        ntl_start = os.getenv("OSEAS_NTL_START_MONTH", "").strip()
        ntl_end = os.getenv("OSEAS_NTL_END_MONTH", "").strip()
        if not assignment_ok:
            stages.append({"stage": "NASA VIIRS Black Marble monthly radiance and context", "status": "blocked",
                           "reason": "requires current county/ward boundaries and asset assignments"})
        elif not ntl_start or not ntl_end:
            stages.append({"stage": "NASA VIIRS Black Marble monthly radiance and context", "status": "blocked",
              "reason": "Manifest-verified OSEAS_NTL_START_MONTH and OSEAS_NTL_END_MONTH are required; Earth Engine authentication is checked by the adapter (no NASA LAADS token is needed)"})
        else:
            try:
                active_ntl = active_python_processes("ingest_viirs_black_marble.py")
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                stages.append({"stage": "NASA VIIRS Black Marble monthly radiance and context", "status": "failed",
                               "reason": f"Could not safely check for an existing process ({type(error).__name__}); no duplicate was started"})
                active_ntl = []
                ntl_process_check_failed = True
            else:
                ntl_process_check_failed = False

            if not ntl_process_check_failed and active_ntl:
                wait_for_active_ntl(active_ntl, stages, args.active_ntl_timeout_minutes)
            elif not ntl_process_check_failed:
                ntl_output_check_failed = False
                try:
                    existing_ntl = verify_ntl_result()
                except RuntimeError as error:
                    if str(error).startswith(("Night-lights result is incomplete", "Night-lights result period", "Night-lights baseline")):
                        print(f"\n[NASA VIIRS Black Marble] existing result does not match configured output: {error}", flush=True)
                        existing_ntl = None
                    else:
                        existing_ntl = None
                        ntl_output_check_failed = True
                        stages.append({"stage": "NASA VIIRS Black Marble monthly radiance and context", "status": "failed",
                                       "reason": "Could not safely verify existing night-lights output; no new acquisition was started"})
                except Exception as error:
                    existing_ntl = None
                    ntl_output_check_failed = True
                    stages.append({"stage": "NASA VIIRS Black Marble monthly radiance and context", "status": "failed",
                                   "reason": f"Could not safely verify existing night-lights output ({type(error).__name__}); no new acquisition was started"})
                if not ntl_output_check_failed and existing_ntl:
                    stages.append({"stage": "NASA VIIRS Black Marble monthly radiance and context", "status": "completed",
                                   "reused_persisted_output": True, **existing_ntl})
                    print(f"\n[NASA VIIRS Black Marble] REUSED: {existing_ntl['detail']}; run={existing_ntl['run_id']}", flush=True)
                elif not ntl_output_check_failed:
                    if not args.allow_image_downloads:
                        stages.append({"stage": "NASA VIIRS Black Marble monthly radiance and context",
                                       "status": "blocked",
                                       "reason": "local image workflow disabled; use --allow-image-downloads to opt in"})
                    else:
                        ntl_started = datetime.now(timezone.utc)
                        if run_stage("NASA VIIRS Black Marble monthly radiance and context",
                                     python_run("scripts/ingest_viirs_black_marble.py"), stages):
                            try:
                                ntl_result = verify_ntl_result(ntl_started)
                            except Exception as error:
                                ntl_result = None
                                ntl_failure = f"database output verification failed ({type(error).__name__})"
                            else:
                                ntl_failure = "the run exited successfully but no complete persisted output was found"
                            if ntl_result is None:
                                stages[-1]["status"] = "failed"
                                stages[-1]["reason"] = ntl_failure
                                print(f"[NASA VIIRS Black Marble] FAILED: {ntl_failure}", flush=True)
                            else:
                                stages[-1].update(ntl_result)
                                print(f"[NASA VIIRS Black Marble] verified: {ntl_result['detail']}; run={ntl_result['run_id']}", flush=True)

        unosat_ok = run_stage("UNOSAT flood reference ingest", python_run("scripts/ingest_unosat_flood_reference.py"), stages)

        if assignment_ok and unosat_ok:
            run_stage("CHIRPS 30-day rainfall totals and anomalies by county and ward",
                      python_run("scripts/ingest_chirps_rainfall.py"), stages)
        else:
            stages.append({"stage": "CHIRPS 30-day rainfall totals and anomalies by county and ward", "status": "blocked",
                           "reason": "requires successful county/ward assignment and UNOSAT reference ingestion"})

        if not args.allow_image_downloads:
            download_ok = False
            stages.append({"stage": "WorldPop acquisition", "status": "blocked",
                           "reason": "local image workflow disabled; use --allow-image-downloads to opt in"})
            stages.append({"stage": "WorldPop population exposure", "status": "blocked",
                           "reason": "requires the opt-in local WorldPop image workflow and a successful UNOSAT ingest"})
        else:
            worldpop_file = ROOT / "data" / "raw" / "worldpop" / "ken_pop_2024_CN_100m_R2025A_v1.tif"
            if args.skip_worldpop_download:
                download_ok = worldpop_file.exists()
                stages.append({"stage": "WorldPop acquisition", "status": "skipped" if download_ok else "blocked",
                               "reason": "download skipped; raster exists" if download_ok else "download skipped but required raster is missing"})
            else:
                download_ok = run_stage("WorldPop acquisition and validation", python_run("scripts/download_worldpop_kenya.py"), stages)
            if unosat_ok and download_ok:
                run_stage("WorldPop event and administrative population exposure",
                          python_run("scripts/run_worldpop_population_exposure.py", "--persist"), stages)
            else:
                stages.append({"stage": "WorldPop population exposure", "status": "blocked",
                               "reason": "requires successful UNOSAT ingest and a validated WorldPop raster"})

        fire_key = os.getenv("NASA_FIRMS_MAP_KEY", "").strip()
        fire_start = os.getenv("OSEAS_FIRE_START_DATE", "").strip()
        fire_end = os.getenv("OSEAS_FIRE_END_DATE", "").strip()
        if not assignment_ok:
            stages.append({"stage": "NASA FIRMS active-fire acquisition and asset proximity", "status": "blocked",
                           "reason": "requires current county/ward boundaries and asset assignments"})
        elif fire_key and (bool(fire_start) == bool(fire_end)):
            run_stage("NASA FIRMS active-fire acquisition and asset proximity", python_run("scripts/ingest_firms_fire.py"), stages)
        else:
            stages.append({"stage": "NASA FIRMS active-fire acquisition and asset proximity", "status": "blocked",
              "reason": "NASA_FIRMS_MAP_KEY is required; historical dates must be supplied as a pair (leave both empty for latest NRT)"})

        if assignment_ok:
            run_stage("evidence-gated criticality, dependencies, vulnerability, resilience and intervention outputs",
                      python_run("scripts/run_evidence_assessments.py"), stages)
        else:
            stages.append({"stage": "evidence-gated criticality, dependencies, vulnerability, resilience and intervention outputs",
                           "status": "blocked", "reason": "requires current county/ward assignments"})

        bbox = os.getenv("OSEAS_FLOOD_BBOX", "").strip()
        event_start = os.getenv("OSEAS_FLOOD_EVENT_START", "").strip()
        event_end = os.getenv("OSEAS_FLOOD_EVENT_END", "").strip()
        baseline_start = os.getenv("OSEAS_FLOOD_BASELINE_START", "").strip()
        baseline_end = os.getenv("OSEAS_FLOOD_BASELINE_END", "").strip()
        if assignment_ok and all((bbox, event_start, event_end, baseline_start, baseline_end)):
            command = python_run("scripts/run_flood_screen.py", "--bbox", *bbox.split(","), "--event-start", event_start,
              "--event-end", event_end, "--baseline-start", baseline_start, "--baseline-end", baseline_end)
            run_stage("bounded Sentinel-1 flood screening", command, stages)
        elif not assignment_ok:
            stages.append({"stage": "Sentinel-1 flood screening", "status": "blocked",
                           "reason": "requires current county/ward boundaries and assignments"})
        else:
            stages.append({"stage": "Sentinel-1 flood screening", "status": "blocked",
              "reason": "set OSEAS_FLOOD_BBOX, OSEAS_FLOOD_EVENT_START/END and OSEAS_FLOOD_BASELINE_START/END; no national dates or AOI are inferred"})

        prithvi_bbox = os.getenv("OSEAS_PRITHVI_BBOX", "").strip() or bbox
        prithvi_start = os.getenv("OSEAS_PRITHVI_EVENT_START", "").strip() or event_start
        prithvi_end = os.getenv("OSEAS_PRITHVI_EVENT_END", "").strip() or event_end
        prithvi_max_cloud = os.getenv("OSEAS_PRITHVI_MAX_CLOUD_PERCENT", "30").strip() or "30"
        if not assignment_ok:
            stages.append({"stage": "bounded Sentinel-2 Prithvi flood inference", "status": "blocked",
                           "reason": "requires current county/ward boundaries and assignments"})
        elif not args.allow_image_downloads:
            stages.append({"stage": "bounded Sentinel-2 Prithvi flood inference", "status": "blocked",
                           "reason": "local image workflow disabled; use --allow-image-downloads to opt in"})
        elif prithvi_bbox and prithvi_start and prithvi_end:
            command = python_run("scripts/run_prithvi_flood.py", "--bbox", *prithvi_bbox.split(","),
                                 "--event-start", prithvi_start, "--event-end", prithvi_end,
                                 "--max-cloud-percent", prithvi_max_cloud)
            run_stage("bounded Sentinel-2 Prithvi flood inference", command, stages)
        else:
            stages.append({"stage": "bounded Sentinel-2 Prithvi flood inference", "status": "blocked",
              "reason": "set OSEAS_PRITHVI_BBOX and OSEAS_PRITHVI_EVENT_START/END (or reuse the Sentinel-1 bbox/event dates); the model limits each inference to 5 km²"})

        run_stage("final database status", ["node", "scripts/oseas_status.js"], stages)
        report = build_report(
            stages,
            pipeline_started_at,
            args.allow_image_downloads,
        )
        write_report(report)
        return 0 if report["status"] == "completed_with_limitations" else 1
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"OSEAS pipeline stopped: {error}", file=sys.stderr)
        raise SystemExit(1)
