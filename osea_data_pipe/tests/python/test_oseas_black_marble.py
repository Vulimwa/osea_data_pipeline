import os
import json
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point
from importlib.util import find_spec
rasterio_spec = find_spec("rasterio")
if rasterio_spec and rasterio_spec.origin:
    rasterio_proj = Path(rasterio_spec.origin).parent / "proj_data"
    if (rasterio_proj / "proj.db").is_file():
        os.environ["PROJ_LIB"] = str(rasterio_proj)
        os.environ["PROJ_DATA"] = str(rasterio_proj)
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from scripts.ingest_viirs_black_marble import acquire_and_summarize, month_dates, summarize_extract


class BlackMarbleContractTests(unittest.TestCase):
    def test_month_range_is_inclusive(self):
        self.assertEqual(month_dates("2024-11", "2025-02"), [
            date(2024, 11, 1), date(2024, 12, 1), date(2025, 1, 1), date(2025, 2, 1)
        ])

    def test_missing_months_reduce_coverage_and_zero_radiance_is_not_missing(self):
        frame = pd.DataFrame([
            {"zone_key": "admin:1", "date": "2024-01-01", "mean": 0.0, "count": 12},
            {"zone_key": "admin:1", "date": "2024-03-01", "mean": 4.0, "count": 10},
        ])
        result = summarize_extract(frame, month_dates("2024-01", "2024-03"))[0]
        self.assertEqual(result["valid_month_count"], 2)
        self.assertEqual(result["valid_month_fraction"], 2 / 3)
        self.assertEqual(result["median_radiance"], 2.0)
        self.assertEqual(result["observed_dates"], ["2024-01-01", "2024-03-01"])

    def test_blackmarblepy_prefixed_statistics_are_normalized(self):
        frame = pd.DataFrame([
            {"zone_key": "asset:1", "date": "2024-01-01", "ntl_mean": 3.5, "ntl_count": 4},
        ])
        result = summarize_extract(frame, [date(2024, 1, 1)])[0]
        self.assertEqual(result["median_radiance"], 3.5)
        self.assertEqual(result["mean_valid_pixel_count"], 4.0)

    def test_unsupported_library_output_schema_fails_loudly(self):
        frame = pd.DataFrame([{"zone_key": "admin:1", "wrong_date": "2024-01-01", "wrong_value": 3}])
        with self.assertRaisesRegex(ValueError, "schema is unsupported"):
            summarize_extract(frame, [date(2024, 1, 1)])

    def test_monthly_summaries_resume_from_checkpoints_without_reacquisition(self):
        zones = gpd.GeoDataFrame({"zone_key": ["admin:1", "asset:1"],
                                  "zone_type": ["ward", "energy_asset"],
                                  "zone_name": ["Ward", "Asset"],
                                  "source_id": ["ward-id", "asset-id"],
                                  "context_radius_m": [None, 500]},
                                 geometry=[Point(37.0, -1.0), Point(37.1, -1.1)], crs="EPSG:4326")
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "OSEAS_NTL_BASELINE_START_MONTH": "2012-01",
            "OSEAS_NTL_BASELINE_END_MONTH": "2012-01",
        }):
            class FakeNumber:
                def getInfo(self):
                    return 31

            class FakeImage:
                def select(self, *_args):
                    return self

                def updateMask(self, *_args):
                    return self

                def rename(self, *_args):
                    return self

                def multiply(self, *_args):
                    return self

                def sum(self):
                    return self

                def gt(self, *_args):
                    return self

                def unmask(self, *_args):
                    return self

                def addBands(self, *_args):
                    return self

                def toUint8(self):
                    return self

                def getDownloadURL(self, params):
                    return json.dumps(params)

            class FakeCollection:
                def filterDate(self, *_args):
                    return self

                def size(self):
                    return FakeNumber()

                def map(self, _function):
                    return self

                def median(self):
                    return FakeImage()

                def sum(self):
                    return FakeImage()

            fake_ee = types.SimpleNamespace(ImageCollection=lambda _product: FakeCollection())

            class FakeResponse:
                status_code = 200
                headers = {"Content-Type": "image/tiff"}

                def __init__(self, content):
                    self.content = content

                def raise_for_status(self):
                    return None

            class FakeSession:
                def mount(self, *_args, **_kwargs):
                    return None

                def get(self, url, **_kwargs):
                    params = json.loads(url)
                    west, south, east, north = params["region"]
                    resolution = params["crs_transform"][0]
                    width = round((east - west) / resolution)
                    height = round((north - south) / resolution)
                    with MemoryFile() as memory:
                        with memory.open(driver="GTiff", width=width, height=height, count=2,
                                         dtype="float32", crs="EPSG:4326",
                                         transform=from_origin(west, north, resolution, resolution)) as raster:
                            raster.write(np.full((height, width), 2.5, dtype=np.float32), 1)
                            raster.write(np.ones((height, width), dtype=np.float32), 2)
                        content = memory.read()
                    return FakeResponse(content)

                def close(self):
                    return None

            def fake_exact_extract(*, vec, **_kwargs):
                return pd.DataFrame({
                    "mean": [0.0 if key == "admin:1" else 2.5 for key in vec["zone_key"]],
                    "count": [8 if key == "admin:1" else 4 for key in vec["zone_key"]],
                })

            with patch("scripts.ingest_viirs_black_marble.initialize_earth_engine", return_value=True), \
                 patch.dict(sys.modules, {"ee": fake_ee}), \
                 patch("requests.Session", return_value=FakeSession()), \
                 patch("exactextract.exact_extract", side_effect=fake_exact_extract) as extract:
                first = acquire_and_summarize(zones, "2024-01", "2024-01", Path(temporary))
                self.assertEqual(extract.call_count, 2)
            values = np.memmap(first["radiance_matrix_path"], dtype=np.float32, mode="r", shape=(2, 2))
            self.assertEqual(float(values[0, 0]), 0.0)
            self.assertEqual(float(values[0, 1]), 0.0)
            del values
            self.assertTrue((Path(temporary) / "monthly_checkpoints" / "202401.npz").is_file())
            self.assertTrue((Path(temporary) / "monthly_checkpoints" / "201201.npz").is_file())
            self.assertEqual(list((Path(temporary) / "tile_cache").iterdir()), [])

            with patch("scripts.ingest_viirs_black_marble.initialize_earth_engine", return_value=True), \
                 patch.dict(sys.modules, {"ee": fake_ee}), \
                 patch("requests.Session", return_value=FakeSession()), \
                 patch.object(FakeSession, "get", side_effect=AssertionError("checkpoint should avoid retrieval")), \
                 patch("exactextract.exact_extract", side_effect=AssertionError("checkpoint should avoid extraction")):
                resumed = acquire_and_summarize(zones, "2024-01", "2024-01", Path(temporary))
            self.assertEqual(resumed["content_sha256"], first["content_sha256"])
            self.assertEqual(resumed["valid_month_totals"].tolist(), first["valid_month_totals"].tolist())


if __name__ == "__main__":
    unittest.main()
