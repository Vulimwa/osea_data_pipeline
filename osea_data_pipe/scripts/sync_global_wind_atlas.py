"""Download and inspect the three Kenya Global Wind Atlas resource rasters once per cache refresh."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import rasterio
import numpy as np
import requests
from rasterio.windows import from_bounds

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "global_wind_atlas" / "KEN"
PRODUCTS = {
    "wind_speed_10m": ("https://globalwindatlas.info/api/gis/country/KEN/wind-speed/10", "m/s"),
    "power_density_10m": ("https://globalwindatlas.info/api/gis/country/KEN/power-density/10", "W/m2"),
    "air_density_10m": ("https://globalwindatlas.info/api/gis/country/KEN/air-density/10", "kg/m3"),
}
MAX_BYTES = 100 * 1024 * 1024


def download(name: str, url: str) -> tuple[Path, str, int]:
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"{name}.tif"
    partial = target.with_suffix(".tif.part")
    last_error = None
    for attempt in range(3):
        try:
            digest = hashlib.sha256()
            size = 0
            with requests.get(url, stream=True, timeout=(20, 120), headers={"User-Agent": "OSEAS data pipeline/1.0"}) as response:
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if content_type not in {"image/tiff", "application/geotiff", "application/octet-stream"}:
                    raise RuntimeError(f"Unexpected content type for {name}: {content_type or '(missing)'}")
                expected = int(response.headers.get("Content-Length") or 0)
                if expected > MAX_BYTES:
                    raise RuntimeError(f"Refusing {name}: Content-Length {expected} exceeds {MAX_BYTES} byte limit")
                with partial.open("wb") as output:
                    last_progress = 0
                    for block in response.iter_content(chunk_size=1024 * 1024):
                        if not block:
                            continue
                        size += len(block)
                        if size > MAX_BYTES:
                            raise RuntimeError(f"Refusing {name}: streamed content exceeds {MAX_BYTES} byte limit")
                        digest.update(block)
                        output.write(block)
                        if size - last_progress >= 10 * 1024 * 1024:
                            percentage = f" ({size / expected:.0%})" if expected else ""
                            print(f"downloading {name}: {size:,}/{expected:,} bytes{percentage}", flush=True)
                            last_progress = size
                if expected and size != expected:
                    raise RuntimeError(f"Incomplete download for {name}: expected {expected}, received {size}")
            with rasterio.open(partial) as raster:
                if raster.driver not in {"GTiff", "COG"} or raster.count < 1:
                    raise RuntimeError(f"{name} is not a readable single/multiband GeoTIFF")
                if raster.crs is None:
                    raise RuntimeError(f"{name} has no spatial reference")
                if raster.width < 100 or raster.height < 100:
                    raise RuntimeError(f"{name} dimensions are unexpectedly small: {raster.width}x{raster.height}")
            partial.replace(target)
            return target, digest.hexdigest(), size
        except Exception as exc:  # bounded retry; caller receives full failure context
            last_error = exc
            partial.unlink(missing_ok=True)
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Failed to retrieve {name} after three attempts: {last_error}")


def inspect(path: Path, expected_unit: str) -> dict:
    with rasterio.open(path) as raster:
        if raster.crs is None or not raster.crs.is_geographic:
            raise RuntimeError(f"{path.name} must use a geographic coordinate reference to validate Kenya bounds")
        if not (raster.bounds.left <= 34.0 and raster.bounds.bottom <= -4.8 and raster.bounds.right >= 42.0 and raster.bounds.top >= 4.6):
            raise RuntimeError(f"{path.name} does not cover the configured Kenya inspection envelope")
        # Sample the Kenya envelope, not the complete country download (which includes
        # offshore/neighboring pixels and can contain valid values outside Kenya).
        window = from_bounds(34.0, -4.8, 42.0, 4.6, raster.transform).round_offsets().round_lengths()
        sample = raster.read(1, window=window, out_shape=(1024, 1024), masked=True)
        valid = sample.compressed()
        bounds = raster.bounds
        if not valid.size:
            raise RuntimeError(f"{path.name} has no valid pixels in Kenya's bounding envelope")
        negative_fraction = float((valid < 0).sum() / valid.size)
        display_sample = valid[valid >= 0]
        if not display_sample.size:
            raise RuntimeError(f"{path.name} has no physically valid non-negative pixels in Kenya's bounding envelope")
        return {
            "file": path.name,
            "driver": raster.driver,
            "width": raster.width,
            "height": raster.height,
            "band_count": raster.count,
            "crs": raster.crs.to_string(),
            "crs_epsg": raster.crs.to_epsg(),
            "bounds": [bounds.left, bounds.bottom, bounds.right, bounds.top],
            "pixel_size": [raster.transform.a, raster.transform.e],
            "nodata": raster.nodata,
            "unit": expected_unit,
            "unit_source": "Global Wind Atlas layer convention; units are not embedded in this GeoTIFF's tags",
            "kenya_bbox_sample_valid_fraction": float(valid.size / sample.size) if sample.size else 0.0,
            "kenya_bbox_negative_sample_fraction_masked_for_map": negative_fraction,
            "kenya_bbox_sample_min": float(display_sample.min()),
            "kenya_bbox_sample_median": float(np.median(display_sample)),
            "kenya_bbox_sample_max": float(display_sample.max()),
            "tags": raster.tags(),
        }


def make_map_raster(source: Path) -> tuple[Path, str, int]:
    """Keep the source TIFF and create a map copy with non-physical negative pixels masked."""
    import numpy as np

    destination = source.with_name(source.stem + "_map.tif")
    partial = destination.with_suffix(".tif.part")
    digest = hashlib.sha256()
    with rasterio.open(source) as src:
        profile = src.profile.copy()
        profile.update(driver="GTiff", dtype="float32", nodata=float("nan"), compress="deflate", tiled=True, blockxsize=256, blockysize=256, BIGTIFF="IF_SAFER")
        with rasterio.open(partial, "w", **profile) as dst:
            dst.update_tags(**src.tags())
            dst.update_tags(OSEAS_PROCESSING="Negative resource pixels set to nodata for map display", SOURCE_FILE=source.name)
            for _, window in src.block_windows(1):
                data = src.read(window=window, masked=True).astype("float32").filled(float("nan"))
                data[data < 0] = float("nan")
                dst.write(data)
    with partial.open("rb") as output:
        for block in iter(lambda: output.read(1024 * 1024), b""):
            digest.update(block)
    partial.replace(destination)
    return destination, digest.hexdigest(), destination.stat().st_size


def main() -> int:
    products = {}
    for name, (url, unit) in PRODUCTS.items():
        path = OUT / f"{name}.tif"
        if path.exists() and os.getenv("GWA_FORCE_REFRESH", "0") != "1":
            with rasterio.open(path) as existing:
                if existing.crs is not None and existing.width > 0 and existing.height > 0:
                    digest = hashlib.sha256()
                    with path.open("rb") as existing_file:
                        for block in iter(lambda: existing_file.read(1024 * 1024), b""):
                            digest.update(block)
                    sha = digest.hexdigest()
                    size = path.stat().st_size
                else:
                    path.unlink()
                    path, sha, size = download(name, url)
        else:
            path, sha, size = download(name, url)
        metadata = inspect(path, unit)
        if metadata["kenya_bbox_sample_valid_fraction"] <= 0:
            raise RuntimeError(f"{name} contains no valid pixels in the Kenya inspection sample")
        map_path, map_sha, map_size = make_map_raster(path)
        products[name] = {**metadata, "source_url": url, "source_file": path.name, "sha256": sha, "bytes": size, "map_file": map_path.name, "map_sha256": map_sha, "map_bytes": map_size, "retrieved_at": datetime.now(timezone.utc).isoformat()}
        print(f"{name}: {size:,} bytes; {metadata['width']}x{metadata['height']} {metadata['crs']}; pixel={metadata['pixel_size']}; bounds={metadata['bounds']}; Kenya_bbox_valid={metadata['kenya_bbox_sample_valid_fraction']:.1%}; sample_range={metadata['kenya_bbox_sample_min']:.3g}..{metadata['kenya_bbox_sample_max']:.3g} {unit}", flush=True)
    manifest = {
        "provider": "Global Wind Atlas / DTU",
        "country": "KEN",
        "attribution": "Global Wind Atlas / DTU; review current terms before redistribution",
        "evidence_kind": "renewable_resource",
        "usage_note": "Resource context; not an observed extreme-wind hazard or asset-failure assessment.",
        "products": products,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Manifest written: {OUT / 'manifest.json'}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Global Wind Atlas sync failed: {error}", file=sys.stderr)
        raise SystemExit(1)
