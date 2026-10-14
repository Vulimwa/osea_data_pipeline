import tempfile
import unittest
import os
from pathlib import Path

import numpy as np
import rasterio
RASTERIO_PROJ = Path(rasterio.__file__).resolve().parent / "proj_data"
if (RASTERIO_PROJ / "proj.db").exists():
    os.environ["PROJ_LIB"] = str(RASTERIO_PROJ)
    os.environ["PROJ_DATA"] = str(RASTERIO_PROJ)
from rasterio.transform import from_origin
from shapely.geometry import box

from oseas.worldpop import _pixel_stats, stable_assessment_id, summarize_footprints


class WorldPopZonalTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.raster_path = Path(self.temp_dir.name) / "population.tif"
        data = np.array([[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12], [13, 14, 15, 16]], dtype="float32")
        data[0, 0] = -9999
        profile = {"driver": "GTiff", "height": 4, "width": 4, "count": 1, "dtype": "float32",
                   "crs": "EPSG:4326", "transform": from_origin(0, 4, 1, 1), "nodata": -9999}
        with rasterio.open(self.raster_path, "w", **profile) as dst:
            dst.write(data, 1)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_pixel_sum_respects_valid_mask_and_pixel_center(self):
        with rasterio.open(self.raster_path) as src:
            result = _pixel_stats(src, box(0, 2, 2, 4))
        self.assertEqual(result["inside_pixels"], 4)
        self.assertEqual(result["valid_pixels"], 3)
        self.assertEqual(result["population"], 2 + 5 + 6)
        self.assertAlmostEqual(result["valid_fraction"], 0.75)

    def test_overlapping_features_union_without_duplicate_pixels(self):
        events = [{"event_key": "event-a", "features": [
            {"geom": box(0, 3, 2, 4), "event_date": "2024-01-01"},
            {"geom": box(1, 3, 3, 4), "event_date": "2024-01-01"},
        ]}]
        result = summarize_footprints(self.raster_path, events)
        zone = result["events"][0]["zones"][0]
        self.assertEqual(zone["inside_pixels"], 3)
        self.assertEqual(zone["population"], 2 + 3)

    def test_stable_ids_are_repeatable_and_scope_specific(self):
        first = stable_assessment_id("hash", "event", "county", "1")
        self.assertEqual(first, stable_assessment_id("hash", "event", "county", "1"))
        self.assertNotEqual(first, stable_assessment_id("hash", "event", "ward", "1"))


if __name__ == "__main__":
    unittest.main()
