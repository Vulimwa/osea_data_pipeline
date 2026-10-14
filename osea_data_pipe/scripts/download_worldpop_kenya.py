"""Download and validate one Kenya WorldPop Global2 100m population-count raster."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests
import rasterio
_RASTERIO_PROJ = str(Path(rasterio.__file__).resolve().parent / "proj_data")
if (Path(_RASTERIO_PROJ) / "proj.db").exists():
    os.environ["PROJ_LIB"] = _RASTERIO_PROJ
    os.environ["PROJ_DATA"] = _RASTERIO_PROJ

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_YEAR = 2024
DATASET_KEY = "worldpop_global2_kenya_population_100m"
BASE_URL = "https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A"
DESTINATION = ROOT / "data" / "raw" / "worldpop"


def source_url(year: int) -> str:
    if year < 2015 or year > 2030:
        raise ValueError("WorldPop Global2 year must be between 2015 and 2030")
    name = f"ken_pop_{year}_CN_100m_R2025A_v1.tif"
    return f"{BASE_URL}/{year}/KEN/v1/100m/constrained/{name}"


def inspect_raster(path: Path, year: int) -> dict[str, object]:
    with rasterio.open(path) as src:
        epsg = src.crs.to_epsg() if src.crs else None
        if src.count != 1 or epsg != 4326:
            raise ValueError(f"Expected a single-band WGS84 raster; got bands={src.count}, EPSG={epsg}")
        if src.width <= 0 or src.height <= 0 or src.res[0] <= 0 or src.res[1] <= 0 or src.transform.e >= 0:
            raise ValueError("WorldPop raster dimensions or geotransform are invalid")
        return {
            "dataset_key": DATASET_KEY,
            "source": source_url(year),
            "provider": "WorldPop Global2 R2025A v1",
            "country": "KEN",
            "year": year,
            "resolution_arc_seconds": 3,
            "units": "estimated persons per pixel",
            "crs": src.crs.to_string(),
            "bounds": list(src.bounds),
            "width": src.width,
            "height": src.height,
            "band_count": src.count,
            "data_type": src.dtypes[0],
            "nodata": src.nodata,
            "pixel_size_degrees": list(src.res),
            "file_size_bytes": path.stat().st_size,
        }


def download(year: int, destination_dir: Path = DESTINATION, audit_only: bool = False) -> dict[str, object]:
    url = source_url(year)
    name = url.rsplit("/", 1)[-1]
    destination = destination_dir / name
    response = requests.head(url, allow_redirects=True, timeout=30)
    response.raise_for_status()
    if "tiff" not in response.headers.get("content-type", "").lower():
        raise ValueError(f"WorldPop response is not a TIFF: {response.headers.get('content-type')}")
    expected_bytes = int(response.headers.get("content-length", "0"))
    if expected_bytes <= 0 or expected_bytes > 500 * 1024 * 1024:
        raise ValueError(f"Unexpected WorldPop file size: {expected_bytes} bytes")
    if audit_only:
        return {"url": url, "status": "available", "content_type": response.headers.get("content-type"), "expected_bytes": expected_bytes}

    destination_dir.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size == expected_bytes:
        metadata = inspect_raster(destination, year)
        digest = hashlib.sha256()
        with destination.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        metadata["sha256"] = digest.hexdigest()
        metadata["license"] = "CC BY 4.0; attribution required"
        destination.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    else:
        partial = destination.with_suffix(destination.suffix + ".part")
        digest = hashlib.sha256()
        received = 0
        started = time.monotonic()
        print(f"WorldPop download started: year={year} bytes={expected_bytes}", flush=True)
        with requests.get(url, stream=True, timeout=(30, 120)) as result:
            result.raise_for_status()
            with partial.open("wb") as output:
                for chunk in result.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    output.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    if received % (10 * 1024 * 1024) < len(chunk) or received == expected_bytes:
                        print(f"WorldPop download progress: {received}/{expected_bytes} bytes ({received / expected_bytes * 100:.1f}%)", flush=True)
        if received != expected_bytes:
            raise IOError(f"Incomplete WorldPop download: expected {expected_bytes}, received {received}")
        os.replace(partial, destination)
        metadata = inspect_raster(destination, year)
        metadata["sha256"] = digest.hexdigest()
        metadata["license"] = "CC BY 4.0; attribution required"
        manifest_path = destination.with_suffix(".json")
        manifest_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    metadata["path"] = str(destination)
    print(f"WorldPop raster ready: {destination} ({metadata['width']}x{metadata['height']})", flush=True)
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR, help="WorldPop Global2 population estimate year (2015-2030)")
    parser.add_argument("--audit-only", action="store_true", help="Check source availability without downloading")
    args = parser.parse_args()
    print(json.dumps(download(args.year, audit_only=args.audit_only), indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"WorldPop acquisition failed: {error}", file=sys.stderr)
        raise SystemExit(1)
