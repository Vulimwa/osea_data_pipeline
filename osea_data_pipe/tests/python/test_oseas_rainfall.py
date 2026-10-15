import json
import sys
import unittest
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from ingest_chirps_rainfall import (  # noqa: E402
    baseline_window,
    content_digest,
    event_window,
    stable_observation_id,
)
from run_oseas_pipeline import (  # noqa: E402
    build_report,
    run_stage,
    validate_inventory_result,
    validate_ntl_result,
    validate_wind_resource_cache,
)


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
        self.assertTrue(report["image_downloads_enabled"])

    def test_pipeline_report_records_image_workflows_enabled(self):
        report = build_report([], "start", image_downloads_enabled=True)
        self.assertTrue(report["image_downloads_enabled"])

    def test_wind_cache_verification_requires_manifest_and_all_api_rasters(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_dir = Path(temporary_directory)
            self.assertEqual(validate_wind_resource_cache(cache_dir)[0], False)
            products = {
                "wind_speed_10m": "wind_speed_10m_map.tif",
                "power_density_10m": "power_density_10m_map.tif",
                "air_density_10m": "air_density_10m_map.tif",
            }
            manifest = {"products": {key: {"map_file": filename} for key, filename in products.items()}}
            (cache_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            for filename in products.values():
                (cache_dir / filename).write_bytes(b"map-data")
            self.assertTrue(validate_wind_resource_cache(cache_dir)[0])
            (cache_dir / "air_density_10m_map.tif").unlink()
            valid, detail = validate_wind_resource_cache(cache_dir)
            self.assertFalse(valid)
            self.assertIn("air_density_10m_map.tif", detail)

    def test_pipeline_report_does_not_call_partial_stages_complete(self):
        report = build_report([{"stage": "inventory", "status": "partial"}], "start")
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["incomplete_stage_count"], 1)

    @patch("run_oseas_pipeline.subprocess.run", return_value=SimpleNamespace(returncode=2))
    def test_pipeline_accepts_warning_only_ingestion_as_partial(self, mock_run):
        stages = []
        successful = run_stage("inventory", ["not-run"], stages, accepted_exit_codes=(0, 2))
        self.assertTrue(successful)
        self.assertEqual(stages[0]["status"], "partial")
        mock_run.assert_called_once()

    def test_inventory_allows_geometry_warnings_when_county_and_ward_rows_persist(self):
        valid, detail = validate_inventory_result("partial", {
            "failed_assets": 0,
            "assets": [
                {"dataset_key": "kenya_counties", "status": "completed", "features_persisted": 47},
                {"dataset_key": "kenya_wards", "status": "completed", "features_persisted": 1450},
                {"dataset_key": "transmission_lines_33kv", "status": "partial", "features_persisted": 31620},
            ],
        })
        self.assertTrue(valid)
        self.assertIn("county and ward", detail)

    def test_inventory_blocks_dependent_stages_when_ward_source_failed(self):
        valid, reason = validate_inventory_result("partial", {
            "failed_assets": 1,
            "assets": [
                {"dataset_key": "kenya_counties", "status": "completed", "features_persisted": 47},
                {"dataset_key": "kenya_wards", "status": "failed", "features_persisted": 0},
            ],
        })
        self.assertFalse(valid)
        self.assertIn("failed asset", reason)

    def test_inventory_requires_both_reporting_boundary_sources(self):
        valid, reason = validate_inventory_result("completed", {
            "failed_assets": 0,
            "assets": [{"dataset_key": "kenya_counties", "status": "completed", "features_persisted": 47}],
        })
        self.assertFalse(valid)
        self.assertIn("kenya_wards", reason)

    def test_inventory_rejects_skipped_ward_geometries(self):
        valid, reason = validate_inventory_result("partial", {
            "failed_assets": 0,
            "assets": [
                {"dataset_key": "kenya_counties", "status": "completed", "features_persisted": 47},
                {"dataset_key": "kenya_wards", "status": "partial", "features_persisted": 1420,
                 "features_skipped_geometry": 30},
            ],
        })
        self.assertFalse(valid)
        self.assertIn("skipped 30", reason)

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
