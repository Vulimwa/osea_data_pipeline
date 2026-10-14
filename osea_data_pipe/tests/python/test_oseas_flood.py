import unittest

from oseas.catalog import BY_KEY, DATASETS
from oseas.flood import METHOD_VERSION, stable_event_fingerprint, validate_bbox, validate_period


class OseasFloodConfigTests(unittest.TestCase):
    def test_registry_includes_required_satellite_and_climate_sources(self):
        keys = {item.key for item in DATASETS}
        required = {
            "chirps_daily", "era5_daily", "era5_land_daily", "nasa_power_daily",
            "worldclim_baseline", "climate_projections_cds", "dem_glo30", "sentinel1_grd",
            "sentinel2_sr", "landsat8_l2", "copernicus_landcover", "hydrosheds_rivers",
            "openstreetmap_context", "historical_flood_extents", "historical_flood_events",
            "nasa_firms_active_fire", "modis_burned_area", "kenya_rivers", "kenya_lakes",
            "kenya_flood_2023_reference",
        }
        self.assertTrue(required.issubset(keys))
        self.assertEqual(len(keys), len(DATASETS))

    def test_flood_sources_are_explicitly_registered(self):
        self.assertEqual(BY_KEY["sentinel1_grd"].collection_id, "COPERNICUS/S1_GRD")
        self.assertEqual(BY_KEY["chirps_daily"].collection_id, "UCSB-CHG/CHIRPS/DAILY")
        self.assertEqual(METHOD_VERSION, "oseas-s1-relative-backscatter-screen-v2")

    def test_bbox_requires_valid_small_epsg4326_area(self):
        self.assertEqual(validate_bbox([36.8, -1.3, 36.9, -1.2]), [36.8, -1.3, 36.9, -1.2])
        with self.assertRaises(ValueError):
            validate_bbox([37, 0, 36, 1])
        with self.assertRaises(ValueError):
            validate_bbox([30, -5, 42, 5])

    def test_event_windows_are_exclusive_nonempty_and_disjoint(self):
        self.assertEqual(validate_period("2024-04-01", "2024-04-15", "event")[1].isoformat(), "2024-04-15")
        with self.assertRaises(ValueError):
            validate_period("2024-04-15", "2024-04-01", "event")

    def test_fingerprint_is_reproducible_and_parameter_sensitive(self):
        parameters = {"event_start": "2024-04-01", "bbox": [36.7, -1.4, 37.0, -1.1]}
        self.assertEqual(stable_event_fingerprint(parameters), stable_event_fingerprint(dict(reversed(list(parameters.items())))))
        self.assertNotEqual(stable_event_fingerprint(parameters), stable_event_fingerprint({**parameters, "event_start": "2024-04-02"}))


if __name__ == "__main__":
    unittest.main()
