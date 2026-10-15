"""Run the configured OSEAS acquisition and assessment chain in dependency order."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


def run_stage(name: str, command: list[str], stages: list[dict[str, object]], *, skip_reason: str | None = None) -> bool:
    if skip_reason:
        print(f"\n[{name}] SKIPPED: {skip_reason}", flush=True)
        stages.append({"stage": name, "status": "blocked", "reason": skip_reason})
        return False
    print(f"\n[{name}] START {datetime.now(timezone.utc).isoformat()}", flush=True)
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, check=False)
    duration = round(time.monotonic() - started, 1)
    status = "completed" if result.returncode == 0 else "failed"
    print(f"[{name}] {status.upper()} exit={result.returncode} duration={duration}s", flush=True)
    stages.append({"stage": name, "status": status, "exit_code": result.returncode, "duration_seconds": duration})
    return result.returncode == 0


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


def build_report(stages: list[dict[str, object]], started_at: str) -> dict[str, object]:
    incomplete = [stage for stage in stages if stage["status"] in {"failed", "blocked"}]
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
    }


def write_report(report: dict[str, object]) -> None:
    report_path = ROOT / "outputs" / "last_pipeline_run.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\nOSEAS PIPELINE SUMMARY", flush=True)
    print(json.dumps(report, indent=2), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-earth-engine", action="store_true", help="Use already-ingested source features")
    parser.add_argument("--skip-worldpop-download", action="store_true", help="Require the selected WorldPop raster to exist locally")
    args = parser.parse_args()
    stages: list[dict[str, object]] = []
    pipeline_started_at = datetime.now(timezone.utc).isoformat()
    acquire_lock()
    try:
        if not run_stage("database preflight", ["node", "scripts/setup_database.js"], stages):
            write_report(build_report(stages, pipeline_started_at))
            return 1

        ingestion_ok = True
        if args.skip_earth_engine or os.getenv("OSEAS_PIPELINE_SKIP_EE", "").lower() in {"1", "true", "yes"}:
            print("\n[Earth Engine source ingestion] SKIPPED: explicit skip; existing source inventory will be used", flush=True)
            stages.append({"stage": "Earth Engine source ingestion", "status": "skipped", "reason": "explicit skip"})
        else:
            ingestion_ok = run_stage("Earth Engine source ingestion", python_run("-m", "oseas.ingest"), stages)

        if ingestion_ok:
            run_stage("asset-to-county-and-ward assignment", python_run("scripts/assign_assets_admin.py"), stages)
            run_stage("NASA POWER heat acquisition and exposure", python_run("scripts/ingest_nasa_power_heat.py"), stages)
        else:
            stages.append({"stage": "asset-to-county-and-ward assignment", "status": "blocked", "reason": "source ingestion failed"})
            stages.append({"stage": "NASA POWER heat acquisition and exposure", "status": "blocked", "reason": "no configured asset inventory update completed"})

        ntl_start = os.getenv("OSEAS_NTL_START_MONTH", "").strip()
        ntl_end = os.getenv("OSEAS_NTL_END_MONTH", "").strip()
        try:
            active_ntl = active_python_processes("ingest_viirs_black_marble.py")
        except RuntimeError as error:
            active_ntl = [f"process check failed: {error}"]
        if active_ntl:
            reason = f"an existing Black Marble process is active ({','.join(active_ntl)}); wait for it instead of starting a duplicate"
            print(f"\n[NASA VIIRS Black Marble monthly radiance and context] BLOCKED: {reason}", flush=True)
            stages.append({"stage": "NASA VIIRS Black Marble monthly radiance and context", "status": "blocked", "reason": reason})
        elif ntl_start and ntl_end:
            run_stage("NASA VIIRS Black Marble monthly radiance and context", python_run("scripts/ingest_viirs_black_marble.py"), stages)
        else:
            stages.append({"stage": "NASA VIIRS Black Marble monthly radiance and context", "status": "blocked",
              "reason": "Manifest-verified OSEAS_NTL_START_MONTH and OSEAS_NTL_END_MONTH are required; Earth Engine authentication is checked by the adapter (no NASA LAADS token is needed)"})

        unosat_ok = run_stage("UNOSAT flood reference ingest", python_run("scripts/ingest_unosat_flood_reference.py"), stages)

        run_stage("CHIRPS 30-day rainfall totals and anomalies by county and ward",
                  python_run("scripts/ingest_chirps_rainfall.py"), stages)

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
        if fire_key and (bool(fire_start) == bool(fire_end)):
            run_stage("NASA FIRMS active-fire acquisition and asset proximity", python_run("scripts/ingest_firms_fire.py"), stages)
        else:
            stages.append({"stage": "NASA FIRMS active-fire acquisition and asset proximity", "status": "blocked",
              "reason": "NASA_FIRMS_MAP_KEY is required; historical dates must be supplied as a pair (leave both empty for latest NRT)"})

        run_stage("evidence-gated criticality, dependencies, vulnerability, resilience and intervention outputs",
                  python_run("scripts/run_evidence_assessments.py"), stages)

        bbox = os.getenv("OSEAS_FLOOD_BBOX", "").strip()
        event_start = os.getenv("OSEAS_FLOOD_EVENT_START", "").strip()
        event_end = os.getenv("OSEAS_FLOOD_EVENT_END", "").strip()
        baseline_start = os.getenv("OSEAS_FLOOD_BASELINE_START", "").strip()
        baseline_end = os.getenv("OSEAS_FLOOD_BASELINE_END", "").strip()
        if all((bbox, event_start, event_end, baseline_start, baseline_end)):
            command = python_run("scripts/run_flood_screen.py", "--bbox", *bbox.split(","), "--event-start", event_start,
              "--event-end", event_end, "--baseline-start", baseline_start, "--baseline-end", baseline_end)
            run_stage("bounded Sentinel-1 flood screening", command, stages)
        else:
            stages.append({"stage": "Sentinel-1 flood screening", "status": "blocked",
              "reason": "set OSEAS_FLOOD_BBOX, OSEAS_FLOOD_EVENT_START/END and OSEAS_FLOOD_BASELINE_START/END; no national dates or AOI are inferred"})

        prithvi_bbox = os.getenv("OSEAS_PRITHVI_BBOX", "").strip() or bbox
        prithvi_start = os.getenv("OSEAS_PRITHVI_EVENT_START", "").strip() or event_start
        prithvi_end = os.getenv("OSEAS_PRITHVI_EVENT_END", "").strip() or event_end
        prithvi_max_cloud = os.getenv("OSEAS_PRITHVI_MAX_CLOUD_PERCENT", "30").strip() or "30"
        if prithvi_bbox and prithvi_start and prithvi_end:
            command = python_run("scripts/run_prithvi_flood.py", "--bbox", *prithvi_bbox.split(","),
                                 "--event-start", prithvi_start, "--event-end", prithvi_end,
                                 "--max-cloud-percent", prithvi_max_cloud)
            run_stage("bounded Sentinel-2 Prithvi flood inference", command, stages)
        else:
            stages.append({"stage": "bounded Sentinel-2 Prithvi flood inference", "status": "blocked",
              "reason": "set OSEAS_PRITHVI_BBOX and OSEAS_PRITHVI_EVENT_START/END (or reuse the Sentinel-1 bbox/event dates); the model limits each inference to 5 km²"})

        report = build_report(stages, pipeline_started_at)
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
