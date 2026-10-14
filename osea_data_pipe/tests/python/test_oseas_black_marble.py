import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

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
        zones = gpd.GeoDataFrame({"zone_key": ["admin:1", "asset:1"]},
                                 geometry=[Point(37.0, -1.0), Point(37.1, -1.1)], crs="EPSG:4326")
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "OSEAS_NTL_BASELINE_START_MONTH": "2012-01",
            "OSEAS_NTL_BASELINE_END_MONTH": "2012-01",
        }):
            def fake_extract(_gdf, *, date_range, output_directory, **_kwargs):
                return pd.DataFrame([
                    {"zone_key": "admin:1", "date": date_range[0], "ntl_mean": 0.0, "ntl_count": 8},
                    {"zone_key": "asset:1", "date": date_range[0], "ntl_mean": 2.5, "ntl_count": 4},
                ])

            with patch("blackmarble.bm_extract", side_effect=fake_extract) as extract:
                first = acquire_and_summarize(zones, "2024-01", "2024-01", "test-token", Path(temporary))
                self.assertEqual(extract.call_count, 2)
            self.assertEqual(first["features"][0]["recent"]["median_radiance"], 0.0)
            self.assertEqual(first["features"][0]["baseline"]["median_radiance"], 0.0)
            self.assertTrue((Path(temporary) / "monthly_checkpoints" / "202401.json").is_file())
            self.assertTrue((Path(temporary) / "monthly_checkpoints" / "201201.json").is_file())
            self.assertEqual(list((Path(temporary) / "tile_cache").iterdir()), [])

            with patch("blackmarble.bm_extract", side_effect=AssertionError("checkpoint should avoid retrieval")):
                resumed = acquire_and_summarize(zones, "2024-01", "2024-01", "test-token", Path(temporary))
            self.assertEqual(resumed["content_sha256"], first["content_sha256"])
            self.assertEqual(resumed["features"], first["features"])


if __name__ == "__main__":
    unittest.main()
