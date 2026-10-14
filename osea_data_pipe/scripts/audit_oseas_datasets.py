"""Small authenticated Earth Engine retrieval checks; prints only public metadata."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

from oseas.catalog import DATASETS


def main() -> int:
    try:
        import ee
    except ImportError as exc:
        raise RuntimeError("earthengine-api is required") from exc
    from gee.auth import initialize_earth_engine

    project = os.getenv("GEE_PROJECT_ID", "").strip()
    if not project or not initialize_earth_engine(project):
        raise RuntimeError("Earth Engine authentication failed")

    roi = ee.Geometry.Rectangle([36.70, -1.40, 37.00, -1.10], geodesic=False)
    selected = {"sentinel1_grd", "chirps_daily", "era5_land_daily", "era5_daily", "sentinel2_sr", "sentinel2_l1c", "landsat8_l2", "dem_glo30", "surface_water", "modis_burned_area"}
    report = []
    for spec in DATASETS:
        if spec.key not in selected:
            report.append({"dataset_key": spec.key, "collection_id": spec.collection_id, "status": "not_tested_in_smoke", "registry_status": spec.status})
            continue
        try:
            date_start, date_end = "2024-04-01", "2024-05-01"
            if spec.key == "era5_daily":
                # The ERA5 daily aggregate collection stops in 2020-07 in EE.
                date_start, date_end = "2019-04-01", "2019-05-01"
            elif spec.key == "modis_burned_area":
                date_start, date_end = "2024-01-01", "2025-01-01"
            if spec.key in {"dem_glo30", "surface_water"}:
                image = ee.ImageCollection(spec.collection_id).filterBounds(roi).mosaic() if spec.key == "dem_glo30" else ee.Image(spec.collection_id)
                bands = image.bandNames().getInfo()
                image.geometry().intersects(roi, ee.ErrorMargin(100)).getInfo()
                report.append({"dataset_key": spec.key, "collection_id": spec.collection_id, "status": "retrieved", "bands": bands, "test_area": "Nairobi 0.3 degree bbox"})
                continue
            collection = ee.ImageCollection(spec.collection_id).filterBounds(roi)
            if spec.key == "sentinel1_grd":
                collection = collection.filterDate(date_start, date_end).filter(ee.Filter.eq("instrumentMode", "IW")).filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
            elif spec.key == "sentinel2_sr":
                collection = collection.filterDate(date_start, date_end)
            elif spec.key == "modis_burned_area":
                collection = collection.filterDate(date_start, date_end)
            else:
                collection = collection.filterDate(date_start, date_end)
            count = int(collection.size().getInfo())
            if count < 1:
                raise RuntimeError("No images intersect the test area and date range")
            bands = collection.first().bandNames().getInfo()
            report.append({"dataset_key": spec.key, "collection_id": spec.collection_id, "status": "retrieved", "image_count": count, "sample_bands": bands[:12], "band_count": len(bands), "date_start": date_start, "date_end_exclusive": date_end, "test_area": "Nairobi 0.3 degree bbox"})
        except Exception as exc:
            report.append({"dataset_key": spec.key, "collection_id": spec.collection_id, "status": "unavailable_or_empty", "error_type": type(exc).__name__, "error": str(exc)[:500]})
    output = {"checked_at": datetime.now(timezone.utc).isoformat(), "project_configured": True, "report": report}
    print(json.dumps(output, indent=2))
    required = {"sentinel1_grd", "sentinel2_l1c", "chirps_daily", "era5_daily", "dem_glo30", "landsat8_l2", "surface_water", "modis_burned_area"}
    required_results = [row for row in report if row["dataset_key"] in required]
    return 0 if len(required_results) == len(required) and all(row["status"] == "retrieved" for row in required_results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
