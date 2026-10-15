import tempfile
import unittest
from pathlib import Path

from scripts.run_prithvi_flood import _configure_proj_data, _polygonize, _validate_and_mask_prediction, validate_args
from argparse import Namespace
from shapely.geometry import box
from scripts.run_prithvi_national import _ensure_grid, _finalize, _zonal_pixel_stats, tile_dimensions

_configure_proj_data()
import numpy as np
import rasterio
from rasterio.transform import from_origin


class PrithviFloodPipelineTests(unittest.TestCase):
    def test_national_grid_sql_binds_every_parameter(self):
        class Cursor:
            def __init__(self):
                self.calls = []

            def execute(self, query, params=None):
                self.calls.append((query, params))

            def fetchone(self):
                return (17,)

        cursor = Cursor()
        self.assertEqual(_ensure_grid(cursor, "fingerprint", "run-id", 64), 17)
        grid_query, grid_params = cursor.calls[0]
        self.assertEqual(grid_query.count("%s"), len(grid_params))
        self.assertIn("ON CONFLICT (event_fingerprint,batch_id) DO NOTHING", grid_query)

    def test_national_finalization_sql_binds_every_parameter(self):
        class Cursor:
            def __init__(self):
                self.calls = []
                self.rowcount = 0

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def execute(self, query, params=None):
                self.calls.append((query, params))
                self.rowcount = 47

            def fetchall(self):
                return [("completed", 1)]

        class Connection:
            def __init__(self):
                self.cursor_instance = Cursor()

            def cursor(self):
                return self.cursor_instance

            def commit(self):
                pass

        connection = Connection()
        result = _finalize(
            connection,
            "fingerprint",
            "run-id",
            "model-run-id",
            {"overlap_pixels": 64, "event_start": "2024-01-01", "event_end": "2024-01-02"},
            1,
        )
        self.assertEqual(result["status"], "completed")
        for query, params in connection.cursor_instance.calls:
            if params is not None:
                self.assertEqual(query.count("%s"), len(params))

    def test_national_prithvi_counts_only_the_non_overlapping_tile_core(self):
        dimensions = tile_dimensions(64)
        shape = (dimensions["chip_pixels"], dimensions["chip_pixels"])
        labels = np.zeros(shape, dtype=np.uint8)
        valid = np.ones(shape, dtype=bool)
        jrc = np.zeros(shape, dtype=np.int16)
        lakes = np.zeros(shape, dtype=bool)
        margin = dimensions["overlap_pixels"] // 2
        labels[margin + 10, margin + 10] = 1
        labels[margin + 11, margin + 11] = 1
        labels[margin + 12, margin + 12] = 1
        labels[0, 0] = 1
        jrc[margin + 11, margin + 11] = 90
        lakes[margin + 12, margin + 12] = True
        valid[margin + 13, margin + 13] = False
        core_half_m = dimensions["stride_m"] / 2
        stats = _zonal_pixel_stats(
            labels,
            valid,
            jrc,
            lakes,
            [{
                "id": "admin-unit",
                "unit_level": "ward",
                "geometry": box(-core_half_m, -core_half_m, core_half_m, core_half_m),
            }],
            (-dimensions["chip_size_m"] / 2, -dimensions["chip_size_m"] / 2,
             dimensions["chip_size_m"] / 2, dimensions["chip_size_m"] / 2),
            64,
        )
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]["total_pixels"], dimensions["core_pixels"] ** 2)
        self.assertEqual(stats[0]["valid_pixels"], dimensions["core_pixels"] ** 2 - 1)
        self.assertEqual(stats[0]["candidate_pixels"], 1)

    def test_bbox_rejects_area_above_local_inference_limit(self):
        args = Namespace(
            bbox=[36.0, -1.0, 37.0, 0.0],
            max_cloud_percent=30,
            min_patch_area_m2=10000,
            event_start="2024-04-01",
            event_end="2024-04-10",
        )
        with self.assertRaisesRegex(ValueError, "at most 5 km2"):
            validate_args(args)

    def test_polygonizer_excludes_jrc_permanent_water(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prediction_path = root / "prediction.tif"
            input_path = root / "input.tif"
            profile = {
                "driver": "GTiff",
                "height": 3,
                "width": 3,
                "count": 1,
                "dtype": "uint8",
                "crs": "EPSG:32637",
                "transform": from_origin(500000, 9900000, 10, 10),
                "nodata": 255,
            }
            with rasterio.open(prediction_path, "w", **profile) as raster:
                raster.write(np.ones((3, 3), dtype=np.int16), 1)
            input_profile = {**profile, "count": 8, "dtype": "int16", "nodata": None}
            with rasterio.open(input_path, "w", **input_profile) as raster:
                raster.write(np.zeros((8, 3, 3), dtype=np.int16))
                valid = np.ones((3, 3), dtype=np.int16)
                valid[0, 0] = 0
                raster.write(valid, 7)
                jrc = np.zeros((3, 3), dtype=np.int16)
                jrc[1, 1] = 90
                jrc[1, 2] = -1
                raster.write(jrc, 8)
            features = _polygonize(prediction_path, 1, input_path)
            self.assertEqual(len(features), 1)
            self.assertEqual(features[0]["properties"]["class_label"], "water_or_flood_candidate")
            self.assertIn("missing JRC occurrence retained", features[0]["properties"]["permanent_water_filter"])
            self.assertAlmostEqual(features[0]["properties"]["area_m2"], 700, delta=10)
            self.assertGreater(features[0]["properties"]["area_m2"], 0)

    def test_normalizes_official_byte_encoded_class_one_and_masks_invalid_pixels(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path, upstream_path, output_path = root / "input.tif", root / "upstream.tif", root / "labels.tif"
            profile = {
                "driver": "GTiff", "height": 2, "width": 2, "count": 8,
                "dtype": "int16", "crs": "EPSG:32637", "transform": from_origin(500000, 9900000, 10, 10),
            }
            with rasterio.open(input_path, "w", **profile) as raster:
                raster.write(np.zeros((8, 2, 2), dtype=np.int16))
                raster.write(np.array([[1, 1], [0, 1]], dtype=np.int16), 7)
            with rasterio.open(upstream_path, "w", **{**profile, "count": 1, "dtype": "uint8", "nodata": 0}) as raster:
                raster.write(np.array([[0, 255], [255, 0]], dtype=np.uint8), 1)
            quality = _validate_and_mask_prediction(upstream_path, input_path, output_path)
            with rasterio.open(output_path) as raster:
                np.testing.assert_array_equal(raster.read(1), np.array([[0, 1], [255, 0]], dtype=np.uint8))
                self.assertEqual(raster.nodata, 255)
            self.assertEqual(quality["class_distribution_valid_pixels"], {"0": 2, "1": 1})


if __name__ == "__main__":
    unittest.main()
