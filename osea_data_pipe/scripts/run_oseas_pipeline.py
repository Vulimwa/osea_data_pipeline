"""Run the configured OSEAS acquisition and assessment chain in dependency order."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "data" / ".oseas_pipeline.lock"


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


def npm_run(script: str) -> list[str]:
    npm = "npm.cmd" if os.name == "nt" else "npm"
    return [npm, "run", script]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-earth-engine", action="store_true", help="Use already-ingested source features")
    parser.add_argument("--skip-worldpop-download", action="store_true", help="Require the selected WorldPop raster to exist locally")
    args = parser.parse_args()
    stages: list[dict[str, object]] = []
    acquire_lock()
    try:
        if not run_stage("database preflight", npm_run("db:setup"), stages):
            return 1

        ingestion_ok = True
        if args.skip_earth_engine or os.getenv("OSEAS_PIPELINE_SKIP_EE", "").lower() in {"1", "true", "yes"}:
            print("\n[Earth Engine source ingestion] SKIPPED: explicit skip; existing source inventory will be used", flush=True)
            stages.append({"stage": "Earth Engine source ingestion", "status": "skipped", "reason": "explicit skip"})
        else:
            ingestion_ok = run_stage("Earth Engine source ingestion", npm_run("oseas:ingest"), stages)

        if ingestion_ok:
            run_stage("asset-to-county-and-ward assignment", npm_run("oseas:assign-admin"), stages)
        else:
            stages.append({"stage": "asset-to-county-and-ward assignment", "status": "blocked", "reason": "source ingestion failed"})

        unosat_ok = run_stage("UNOSAT flood reference ingest", npm_run("oseas:flood:unosat:ingest"), stages)

        worldpop_file = ROOT / "data" / "raw" / "worldpop" / "ken_pop_2024_CN_100m_R2025A_v1.tif"
        if args.skip_worldpop_download:
            download_ok = worldpop_file.exists()
            stages.append({"stage": "WorldPop acquisition", "status": "skipped" if download_ok else "blocked",
                           "reason": "download skipped; raster exists" if download_ok else "download skipped but required raster is missing"})
        else:
            download_ok = run_stage("WorldPop acquisition and validation", npm_run("oseas:population:download"), stages)
        if unosat_ok and download_ok:
            run_stage("WorldPop event and administrative population exposure", npm_run("oseas:population:persist"), stages)
        else:
            stages.append({"stage": "WorldPop population exposure", "status": "blocked",
                           "reason": "requires successful UNOSAT ingest and a validated WorldPop raster"})

        run_stage("evidence-gated criticality, dependencies, vulnerability, resilience and intervention outputs",
                  npm_run("oseas:assessments"), stages)

        bbox = os.getenv("OSEAS_FLOOD_BBOX", "").strip()
        event_start = os.getenv("OSEAS_FLOOD_EVENT_START", "").strip()
        event_end = os.getenv("OSEAS_FLOOD_EVENT_END", "").strip()
        baseline_start = os.getenv("OSEAS_FLOOD_BASELINE_START", "").strip()
        baseline_end = os.getenv("OSEAS_FLOOD_BASELINE_END", "").strip()
        if all((bbox, event_start, event_end, baseline_start, baseline_end)):
            command = npm_run("oseas:flood:screen") + ["--", "--bbox", *bbox.split(","), "--event-start", event_start,
              "--event-end", event_end, "--baseline-start", baseline_start, "--baseline-end", baseline_end]
            run_stage("bounded Sentinel-1 flood screening", command, stages)
        else:
            stages.append({"stage": "Sentinel-1 flood screening", "status": "blocked",
              "reason": "set OSEAS_FLOOD_BBOX, OSEAS_FLOOD_EVENT_START/END and OSEAS_FLOOD_BASELINE_START/END; no national dates or AOI are inferred"})

        report = {"status": "completed_with_limitations" if all(stage["status"] in {"completed", "skipped", "blocked"} for stage in stages) else "partial",
                  "started_at": stages[0].get("started_at") if stages else None,
                  "stages": stages,
                  "unsupported_or_unconfigured_sources": ["heat/Landsat LST", "FIRMS active fire and burned area", "CHIRPS anomaly products", "reusable national terrain and drainage"],
                  "duplication_policy": "Source feature keys, raster-content assessment keys, deterministic assessment IDs and importer advisory locks; same-input outputs are upserted or ignored."}
        report_path = ROOT / "outputs" / "last_pipeline_run.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("\nOSEAS PIPELINE SUMMARY")
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "completed_with_limitations" else 1
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"OSEAS pipeline stopped: {error}", file=sys.stderr)
        raise SystemExit(1)
