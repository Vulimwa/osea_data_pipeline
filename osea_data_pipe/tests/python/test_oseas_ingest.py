import unittest
from types import SimpleNamespace
from unittest.mock import patch

from oseas.config import ASSETS, configured_assets, database_url, missing_asset_keys
from oseas.ingest import _acquire_run_lock, _fail_abandoned_runs, _geometry, _get_features, _next_page_token, _persist_feature_page, _source_feature_id, _stable_id, _write_page, inspect_asset


class RecordingCursor:
    def __init__(self):
        self.batches = []
        self.statements = []
        self.rowcount = 2

    def executemany(self, statement, rows):
        self.batches.append((statement, list(rows)))

    def execute(self, statement, params=None):
        self.statements.append((statement, params))

    def fetchone(self):
        return (True,)


class FakeConnection:
    def __init__(self):
        self.cursor_instance = RecordingCursor()

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        pass

    def rollback(self):
        pass


class CursorContext:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self.cursor

    def __exit__(self, *_args):
        return False


class FakeEarthEngine:
    class FeatureCollection:
        def __init__(self, asset_id):
            self.asset_id = asset_id

        def size(self):
            return SimpleNamespace(getInfo=lambda: 17)

    class Data:
        @staticmethod
        def getAsset(asset_id):
            return {"type": "TABLE", "columns": [{"name": "code", "type": "STRING"}]}

        @staticmethod
        def listFeatures(params):
            return {
                "features": [{"id": "ward-1", "geometry": {"type": "Point", "coordinates": [36.8, -1.2]}, "properties": {"code": "W001"}}],
                "next_page_token": "next-page",
            }

    data = Data()


class OseasIngestTests(unittest.TestCase):
    def test_ids_are_repeatable_and_dataset_scoped(self):
        feature = {"id": "generated-row-id", "properties": {"OBJECTID": 42, "name": "Transformer"}}
        self.assertEqual(_stable_id("transformers", feature), _stable_id("transformers", feature))
        self.assertNotEqual(_stable_id("transformers", feature), _stable_id("schools", feature))
        self.assertEqual(_source_feature_id(feature), "42")
        self.assertEqual(_source_feature_id({"properties": {"gid": 9, "uid": "W-9"}}), "W-9")

    def test_geometry_validation_rejects_missing_geometry(self):
        self.assertIsNone(_geometry({"properties": {}}))
        self.assertEqual(_geometry({"geometry": {"type": "Point", "coordinates": [1, 2]}})["type"], "Point")

    def test_feature_pages_keep_page_size_and_token(self):
        response = _get_features(FakeEarthEngine, "asset/path", "next-page")
        self.assertEqual(response["next_page_token"], "next-page")
        self.assertEqual(_next_page_token(response), "next-page")

    def test_asset_inspection_reports_table_schema_sample_and_count(self):
        details = inspect_asset(FakeEarthEngine, "asset/path")
        self.assertEqual(details["asset_type"], "TABLE")
        self.assertEqual(details["geometry_type"], "Point")
        self.assertEqual(details["feature_count"], 17)
        self.assertIn("code", details["property_schema"])

    def test_asset_page_uses_batched_upserts_and_preserves_source_attributes(self):
        spec = next(asset for asset in ASSETS if asset.key == "distribution_transformers")
        feature = {
            "id": "ee-id",
            "geometry": {"type": "Point", "coordinates": [36.8, -1.2]},
            "properties": {"OBJECTID": 123, "County2": "Example", "Name": "T-123"},
        }
        cursor = RecordingCursor()
        self.assertEqual(_persist_feature_page(cursor, "run-id", spec, "asset-id", [feature]), 1)
        self.assertEqual(len(cursor.batches), 2)  # common asset row and typed transformer row
        self.assertEqual(cursor.batches[0][1][0][4], "123")
        self.assertIn('"County2": "Example"', cursor.batches[0][1][0][7])
        self.assertEqual(len(cursor.statements), 1)  # dataset freshness is updated once per page

    def test_page_progress_jsonb_keys_have_explicit_postgres_types(self):
        spec = next(asset for asset in ASSETS if asset.key == "kenya_counties")
        connection = FakeConnection()
        connection.cursor = lambda: CursorContext(connection.cursor_instance)
        feature = {"id": "county-1", "geometry": {"type": "Point", "coordinates": [36.8, -1.2]}, "properties": {"code": "KE-1"}}
        with patch("oseas.ingest._persist_feature_page", return_value=1):
            self.assertEqual(_write_page(connection, "00000000-0000-4000-8000-000000000001", spec, "asset", [feature], 0, 47, 1), (1, 0))
        statement, params = connection.cursor_instance.statements[0]
        self.assertIn("'current_dataset', %s::text", statement)
        self.assertIn("'current_processed', %s::bigint", statement)
        self.assertEqual(params[0], spec.key)

    def test_page_write_skips_feature_with_missing_geometry_and_tracks_warning(self):
        spec = next(asset for asset in ASSETS if asset.key == "kenya_wards")
        connection = FakeConnection()
        connection.cursor = lambda: CursorContext(connection.cursor_instance)
        features = [
            {"id": "ward-valid", "geometry": {"type": "Point", "coordinates": [36.8, -1.2]}, "properties": {}},
            {"id": "ward-invalid", "geometry": None, "properties": {}},
        ]
        with patch("oseas.ingest._persist_feature_page", return_value=1) as persist:
            self.assertEqual(_write_page(connection, "00000000-0000-4000-8000-000000000001", spec, "asset", features, 0, 2, 1), (1, 1))
        persist.assert_called_once()
        statement, params = connection.cursor_instance.statements[0]
        self.assertIn("'current_skipped_geometry', %s::bigint", statement)
        self.assertEqual(params[3], 1)

    def test_writer_lock_is_session_scoped_and_rejects_competing_runs(self):
        connection = FakeConnection()
        connection.cursor = lambda: CursorContext(connection.cursor_instance)
        _acquire_run_lock(connection)
        statement, params = connection.cursor_instance.statements[0]
        self.assertIn("pg_try_advisory_lock", statement)
        self.assertEqual(params, ("oseas_earth_engine_ingest",))

        connection.cursor_instance.fetchone = lambda: (False,)
        with self.assertRaisesRegex(RuntimeError, "Another OSEAS ingestion process"):
            _acquire_run_lock(connection)

    def test_abandoned_run_recovery_only_marks_run_metadata_failed(self):
        cursor = RecordingCursor()
        self.assertEqual(_fail_abandoned_runs(cursor), 2)
        statement, _ = cursor.statements[0]
        self.assertIn("status = 'failed'", statement)
        self.assertIn("status = 'running'", statement)
        self.assertIn("interrupted", statement)
        self.assertNotIn("DELETE", statement.upper())
        self.assertNotIn("TRUNCATE", statement.upper())

    def test_asset_environment_is_configurable_and_database_aliases_work(self):
        spec = ASSETS[0]
        with patch.dict("os.environ", {spec.env_key: "projects/test/assets/counties", "DB_URL": "postgresql://db"}, clear=True):
            self.assertEqual(configured_assets()[0][1], "projects/test/assets/counties")
            self.assertEqual(database_url(), "postgresql://db")
            self.assertEqual(len(missing_asset_keys()), len(ASSETS) - 1)


if __name__ == "__main__":
    unittest.main()
