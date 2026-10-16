"""Create short-lived Earth Engine map tile URLs for the OSEAS map."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from contextlib import redirect_stdout

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import ee
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from gee.auth import initialize_earth_engine


PROJECT = "osea-hack"
ASSETS = {
    "composite_hazard_raster": f"projects/{PROJECT}/assets/composite_hazard_raster",
    "kenya_wards_vulnerability_vector": f"projects/{PROJECT}/assets/kenya_wards_vulnerability_vector",
    "vulnerable_minigrids_vector": f"projects/{PROJECT}/assets/vulnerable_minigrids_vector",
    "vulnerable_substations_vector": f"projects/{PROJECT}/assets/vulnerable_substations_vector",
}
RASTER_SOURCES = {
    "nasa_viirs_black_marble_monthly": {
        "collection": "NASA/VIIRS/002/VNP46A2",
        "band": "DNB_BRDF_Corrected_NTL",
        "title": "VIIRS Black Marble recent radiance",
        "unit": "nW cm-2 sr-1",
        "min": 0,
        "max": 50,
        "palette": ["001133", "0055aa", "ffee00", "ff3300"],
    },
    "chirps_daily": {
        "collection": "UCSB-CHG/CHIRPS/DAILY",
        "band": "precipitation",
        "title": "CHIRPS latest daily precipitation",
        "unit": "mm/day",
        "min": 0,
        "max": 50,
        "palette": ["ffffff", "b3e5fc", "29b6f6", "1565c0", "311b92"],
    },
    "era5_land_daily_temperature": {
        "collection": "ECMWF/ERA5_LAND/DAILY_AGGR",
        "band": "temperature_2m",
        "title": "ERA5-Land daily 2 m temperature",
        "unit": "K",
        "min": 270,
        "max": 320,
        "palette": ["313695", "74add1", "ffffbf", "f46d43", "a50026"],
    },
    "era5_land_daily_precipitation": {
        "collection": "ECMWF/ERA5_LAND/DAILY_AGGR",
        "band": "total_precipitation_sum",
        "title": "ERA5-Land daily total precipitation",
        "unit": "m/day",
        "min": 0,
        "max": 0.05,
        "palette": ["ffffff", "b3e5fc", "29b6f6", "1565c0", "311b92"],
    },
    "era5_daily_temperature": {
        "collection": "ECMWF/ERA5/DAILY",
        "band": "mean_2m_air_temperature",
        "title": "ERA5 daily mean 2 m temperature",
        "unit": "K",
        "min": 270,
        "max": 320,
        "palette": ["313695", "74add1", "ffffbf", "f46d43", "a50026"],
    },
    "era5_daily_precipitation": {
        "collection": "ECMWF/ERA5/DAILY",
        "band": "total_precipitation",
        "title": "ERA5 daily total precipitation",
        "unit": "m/day",
        "min": 0,
        "max": 0.05,
        "palette": ["ffffff", "b3e5fc", "29b6f6", "1565c0", "311b92"],
    },
}


def _styled_substations(collection: ee.FeatureCollection) -> ee.Image:
    def style(feature: ee.Feature) -> ee.Feature:
        score = ee.Number(feature.get("vulnerability_score"))
        color = ee.String(
            ee.Algorithms.If(
                score.gt(0.6),
                "ff1744",
                ee.Algorithms.If(score.gt(0.3), "ffea00", "00e676"),
            )
        )
        return feature.set("style", ee.Dictionary({
            "color": color,
            "fillColor": color,
            "pointSize": 6,
            "width": 1,
        }))

    return collection.map(style).style(styleProperty="style")


def _styled_wards(collection: ee.FeatureCollection) -> ee.Image:
    def style(feature: ee.Feature) -> ee.Feature:
        score = ee.Number(feature.get("grid_vulnerability_index"))
        fill = ee.String(
            ee.Algorithms.If(
                score.gt(0.4),
                "b71c1c44",
                ee.Algorithms.If(score.gt(0.1), "f57f1744", "1b5e2044"),
            )
        )
        return feature.set("style", ee.Dictionary({
            "color": "ffffff",
            "fillColor": fill,
            "width": 0.5,
        }))

    return collection.map(style).style(styleProperty="style")


def _image(layer_id: str) -> tuple[ee.Image, dict[str, object]]:
    asset_id = ASSETS[layer_id]
    if layer_id == "composite_hazard_raster":
        return ee.Image(asset_id), {
            "min": 0,
            "max": 0.7,
            "palette": ["001133", "0055aa", "ffee00", "ff3300"],
        }
    collection = ee.FeatureCollection(asset_id)
    if layer_id == "vulnerable_substations_vector":
        return _styled_substations(collection), {}
    if layer_id == "kenya_wards_vulnerability_vector":
        return _styled_wards(collection), {}
    return collection.style(color="00e5ff", fillColor="00e5ff", pointSize=5, width=1), {}


def _source_raster(layer_id: str, definition: dict[str, object]) -> dict[str, object]:
    collection = ee.ImageCollection(str(definition["collection"]))
    if layer_id == "nasa_viirs_black_marble_monthly":
        now = ee.Date(datetime.now(timezone.utc).date().isoformat())
        collection = collection.filterDate(now.advance(-60, "day"), now)
        collection = collection.map(
            lambda image: image.updateMask(image.select("Mandatory_Quality_Flag").eq(0))
        )
        image = collection.select(str(definition["band"])).median()
        period = "Recent 60-day quality-screened median"
    else:
        image = collection.sort("system:time_start", False).first().select(str(definition["band"]))
        period = "Latest available daily image"
    map_id = image.getMapId({
        "min": definition["min"],
        "max": definition["max"],
        "palette": definition["palette"],
    })
    return {
        "id": f"gee_{layer_id}",
        "title": str(definition["title"]),
        "assetId": str(definition["collection"]),
        "datasetKey": layer_id,
        "band": str(definition["band"]),
        "unit": str(definition["unit"]),
        "periodLabel": period,
        "urlTemplate": map_id["tile_fetcher"].url_format,
        "opacity": 0.8,
        "minScale": 0,
        "maxScale": 0,
    }


def main() -> None:
    project_id = os.getenv("GEE_PROJECT_ID", "").strip()
    with redirect_stdout(sys.stderr):
        if not initialize_earth_engine(project_id or None):
            raise RuntimeError("Earth Engine authentication failed")
    requested_layer = sys.argv[1] if len(sys.argv) > 1 else None
    layers = []
    if requested_layer is None:
        selected_assets = ASSETS.items()
        for layer_id, asset_id in selected_assets:
            image, visualization = _image(layer_id)
            map_id = image.getMapId(visualization)
            layers.append({
                "id": layer_id,
                "title": {
                    "composite_hazard_raster": "Multi-Hazard Overlay Index",
                    "kenya_wards_vulnerability_vector": "Wards Grid Resilience Assessment Map",
                    "vulnerable_minigrids_vector": "Vulnerable Mini-Grids",
                    "vulnerable_substations_vector": "Substations Risk Profile",
                }[layer_id],
                "assetId": asset_id,
                "urlTemplate": map_id["tile_fetcher"].url_format,
                "opacity": 0.65 if layer_id == "composite_hazard_raster" else 1,
                "minScale": 1500000 if layer_id == "kenya_wards_vulnerability_vector" else 0,
                "maxScale": 0,
            })
    elif requested_layer in ASSETS:
        asset_id = ASSETS[requested_layer]
        image, visualization = _image(requested_layer)
        map_id = image.getMapId(visualization)
        layers.append({
            "id": requested_layer,
            "title": requested_layer.replace("_", " ").title(),
            "assetId": asset_id,
            "urlTemplate": map_id["tile_fetcher"].url_format,
            "opacity": 0.65 if requested_layer == "composite_hazard_raster" else 1,
            "minScale": 1500000 if requested_layer == "kenya_wards_vulnerability_vector" else 0,
            "maxScale": 0,
        })
    elif requested_layer.startswith("gee_") and requested_layer[4:] in RASTER_SOURCES:
        layers.append(_source_raster(requested_layer[4:], RASTER_SOURCES[requested_layer[4:]]))
    else:
        raise ValueError("Unknown Earth Engine map layer")
    print(json.dumps({"data": layers}, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Earth Engine map layer preparation failed: {error}", file=sys.stderr)
        raise
