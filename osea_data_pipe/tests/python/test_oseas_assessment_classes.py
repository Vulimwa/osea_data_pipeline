import unittest

from oseas.assessments import _stable_id, _system_class_counts


class AssessmentClassTests(unittest.TestCase):
    def test_system_classes_keep_mini_grids_and_distribution_separate(self):
        counts = _system_class_counts({
            "power_station": 2,
            "transmission_line_132kv": 3,
            "mini_grid": 4,
            "distribution_transformer": 5,
            "unknown_asset": 6,
        })
        self.assertEqual(counts, {
            "centralizedGridNetworkAssets": 3,
            "decentralizedMiniGrids": 4,
            "distributionAssets": 5,
            "generationAssets": 2,
            "systemClassUnclassified": 6,
        })

    def test_summary_output_id_is_stable_across_repeat_runs(self):
        first = _stable_id("ward_vulnerability_summary", "ward-1", "current")
        second = _stable_id("ward_vulnerability_summary", "ward-1", "current")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
