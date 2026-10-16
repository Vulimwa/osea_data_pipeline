"""Create short-lived Earth Engine map tile URLs for the OSEAS map."""

from __future__ import annotations

import json
import os
import sys
from contextlib import redirect_stdout

from dotenv import load_dotenv
load_dotenv()

import ee
from gee.auth import initialize_earth_engine


PROJECT = "osea-hack"
ASSETS = {
    "composite_hazard_raster": f"projects/{PROJECT}/assets/composite_hazard_raster",
    "kenya_wards_vulnerability_vector": f"projects/{PROJECT}/assets/kenya_wards_vulnerability_vector",
    "vulnerable_minigrids_vector": f"projects/{PROJECT}/assets/vulnerable_minigrids_vector",
    "vulnerable_substations_vector": f"projects/{PROJECT}/assets/vulnerable_substations_vector",
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


def main() -> None:
    project_id = os.getenv("GEE_PROJECT_ID", "").strip()
    with redirect_stdout(sys.stderr):
        if not initialize_earth_engine(project_id or None):
            raise RuntimeError("Earth Engine authentication failed")
    layers = []
    for layer_id, asset_id in ASSETS.items():
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
    print(json.dumps({"data": layers}, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Earth Engine map layer preparation failed: {error}", file=sys.stderr)
        raise
