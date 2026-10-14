#!/usr/bin/env python3
"""Download the official Prithvi-EO-2.0 Sen1Floods11 task checkpoint."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
DEFAULT_MODEL_ID = "ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL-Sen1Floods11"
MODEL_REVISION = "91ce9d38086a80b078a192b374df758b8855b732"
FILES = [
    "Prithvi-EO-V2-300M-TL-Sen1Floods11.pt",
    "inference.py",
    "config.yaml",
    "config.json",
    "examples/India_900498_S2Hand.tif",
]


def download_file(model_id: str, revision: str, filename: str, destination: Path) -> Path:
    try:
        import requests
    except ImportError as exc:
        raise SystemExit("Install requests from requirements.txt before downloading the model.") from exc

    target = destination / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    url = f"https://huggingface.co/{model_id}/resolve/{revision}/{quote(filename, safe='/')}?download=true"
    with requests.head(url, timeout=(20, 30), allow_redirects=True) as head:
        head.raise_for_status()
        remote_size = int(head.headers.get("Content-Length") or head.headers.get("X-Linked-Size") or "0")
    if remote_size and target.is_file() and target.stat().st_size == remote_size:
        print(f"Already present; pinned file size matches: {filename} ({remote_size:,} bytes)", flush=True)
        return target
    for attempt in range(1, 6):
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "oseas-prithvi-setup/1.0"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        try:
            with requests.get(url, headers=headers, stream=True, timeout=(20, 120), allow_redirects=True) as response:
                if offset and response.status_code == 200:
                    partial.unlink(missing_ok=True)
                    offset = 0
                elif offset and response.status_code == 416:
                    partial.unlink(missing_ok=True)
                    continue
                response.raise_for_status()
                if offset and response.status_code != 206:
                    raise RuntimeError(f"Server did not resume the partial {filename} download (HTTP {response.status_code})")
                chunk_size = 8 * 1024 * 1024
                expected_size = remote_size or int(response.headers.get("Content-Length") or response.headers.get("X-Linked-Size") or "0")
                mode = "ab" if offset else "wb"
                last_reported = -1
                started = time.monotonic()
                size_label = f"{expected_size / 1024**2:.1f} MiB" if expected_size else "unknown size"
                print(f"Downloading {filename}: {size_label}", flush=True)
                with partial.open(mode) as output:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if not chunk:
                            continue
                        output.write(chunk)
                        completed = output.tell()
                        percent = int(completed * 100 / expected_size) if expected_size else None
                        if (percent is not None and (percent >= last_reported + 5 or percent == 100)) or (percent is None and completed - offset >= 1024 * 1024):
                            elapsed = max(time.monotonic() - started, 0.001)
                            rate = max((completed - offset) / elapsed, 1)
                            if expected_size:
                                eta_s = max(0, expected_size - completed) / rate
                                print(f"  {filename}: {completed / 1024**2:.1f}/{expected_size / 1024**2:.1f} MiB ({percent}%, ETA {eta_s / 60:.1f} min)", flush=True)
                                last_reported = percent
                            else:
                                print(f"  {filename}: {completed / 1024**2:.1f} MiB received", flush=True)
                actual_size = partial.stat().st_size
                if actual_size == 0 or (expected_size and actual_size != expected_size):
                    raise RuntimeError(f"Incomplete {filename}: received {actual_size} of {expected_size} bytes")
                partial.replace(target)
                print(f"Verified download size: {filename} ({actual_size:,} bytes)", flush=True)
                return target
        except Exception as error:
            print(f"Download attempt {attempt}/5 for {filename} failed: {type(error).__name__}: {error}", flush=True)
            if attempt == 5:
                raise
            time.sleep(min(attempt * 3, 15))
    raise RuntimeError(f"Unable to download {filename}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", default=os.getenv("PRITHVI_MODEL_ID", DEFAULT_MODEL_ID))
    parser.add_argument("--destination", default=os.getenv("PRITHVI_MODEL_DIR", "models/prithvi/flood_sen1floods11"))
    args = parser.parse_args()
    if args.model_id != DEFAULT_MODEL_ID:
        raise SystemExit(f"This pipeline's six-band flood preprocessing is pinned to {DEFAULT_MODEL_ID}; refusing incompatible model {args.model_id!r}")
    destination = Path(args.destination)
    if not destination.is_absolute():
        destination = ROOT / destination
    destination.mkdir(parents=True, exist_ok=True)

    print(f"Model: {args.model_id}")
    print("Task: Sentinel-2 flood segmentation fine-tuned on Sen1Floods11")
    print(f"Destination: {destination}")
    print("Checkpoint downloads are streamed with resume support and progress output.", flush=True)
    for name in FILES:
        download_file(args.model_id, MODEL_REVISION, name, destination)
    missing = [name for name in FILES if not (destination / name).is_file() or (destination / name).stat().st_size == 0]
    if missing:
        raise SystemExit("Model bundle is incomplete: " + ", ".join(missing))
    for name in FILES:
        path = destination / name
        print(f"Verified {name}: {path.stat().st_size:,} bytes")
    print("Pinned files verified. Running the official sample-inference smoke test next.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
