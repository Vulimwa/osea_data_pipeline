import unittest
from datetime import date

import pandas as pd

from scripts.ingest_viirs_black_marble import month_dates, summarize_extract


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


if __name__ == "__main__":
    unittest.main()
