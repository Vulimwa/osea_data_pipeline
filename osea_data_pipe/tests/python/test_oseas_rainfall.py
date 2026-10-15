import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from ingest_chirps_rainfall import (  # noqa: E402
    baseline_window,
    content_digest,
    event_window,
    stable_observation_id,
)
from run_oseas_pipeline import build_report, validate_ntl_result  # noqa: E402


class ChirpsRainfallTests(unittest.TestCase):
    def test_event_window_is_30_days_and_includes_event_date(self):
        start, end_exclusive = event_window(date(2024, 4, 21))
        self.assertEqual(start, date(2024, 3, 23))
        self.assertEqual(end_exclusive, date(2024, 4, 22))
        self.assertEqual((end_exclusive - start).days, 30)

    def test_baseline_window_handles_february_29(self):
        start, end_exclusive = baseline_window(date(2024, 2, 29), 2021)
        self.assertEqual(start, date(2021, 1, 30))
        self.assertEqual(end_exclusive, date(2021, 3, 1))

    def test_observation_ids_are_repeatable_and_measure_specific(self):
        event_day = date(2024, 4, 21)
        first = stable_observation_id("FL20240421KEN", event_day, "ward-uuid", "CHIRPS_30D_TOTAL_MM")
        again = stable_observation_id("FL20240421KEN", event_day, "ward-uuid", "CHIRPS_30D_TOTAL_MM")
        anomaly = stable_observation_id("FL20240421KEN", event_day, "ward-uuid", "CHIRPS_30D_ANOMALY_MM")
        self.assertEqual(first, again)
        self.assertNotEqual(first, anomaly)

    def test_content_digest_serializes_dates_deterministically(self):
        rows = [{"event_key": "event", "event_date": date(2024, 4, 21), "unit_id": "ward",
                 "event_total_mm": 20.0, "baseline_mean_mm": 10.0,
                 "anomaly_mm": 10.0, "anomaly_percent": 100.0}]
        self.assertEqual(content_digest(rows), content_digest(rows.copy()))

    def test_pipeline_report_does_not_call_blocked_stages_complete(self):
        report = build_report([{"stage": "rainfall", "status": "blocked", "reason": "missing input"}], "start")
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["incomplete_stage_count"], 1)

    def test_nightlights_stage_requires_complete_persisted_period(self):
        metadata = {
            "requested_zone_count": 10,
            "persisted_observations": 30,
            "recent_period": ["2023-08-01", "2026-07-01"],
            "baseline_period": ["2012-01", "2015-12"],
        }
        valid, _ = validate_ntl_result("completed", metadata, 30,
                                       ["2023-08-01", "2026-07-01"], ["2012-01", "2015-12"])
        self.assertTrue(valid)
        incomplete, reason = validate_ntl_result("completed", metadata, 29,
                                                 ["2023-08-01", "2026-07-01"], ["2012-01", "2015-12"])
        self.assertFalse(incomplete)
        self.assertIn("incomplete", reason)

    def test_nightlights_stage_rejects_wrong_period(self):
        valid, reason = validate_ntl_result("completed", {
            "requested_zone_count": 10,
            "persisted_observations": 30,
            "recent_period": ["2022-01-01", "2024-12-01"],
            "baseline_period": ["2012-01", "2015-12"],
        }, 30, ["2023-08-01", "2026-07-01"], ["2012-01", "2015-12"])
        self.assertFalse(valid)
        self.assertIn("period", reason)


if __name__ == "__main__":
    unittest.main()
