import unittest

from oseas.assessments import METHOD_VERSION, _canonical, _stable_id


class EvidenceAssessmentIdentityTests(unittest.TestCase):
    def test_canonical_json_is_order_independent(self):
        self.assertEqual(_canonical({"a": 1, "b": 2}), _canonical({"b": 2, "a": 1}))

    def test_same_evidence_is_idempotent_and_new_evidence_is_versioned(self):
        evidence = {"hazard": [{"id": "event-1", "status": "exposed"}]}
        first = _stable_id("intervention", "asset-1", evidence)
        repeated = _stable_id("intervention", "asset-1", {"hazard": [{"status": "exposed", "id": "event-1"}]})
        changed = _stable_id("intervention", "asset-1", {"hazard": [{"id": "event-2", "status": "exposed"}]})
        self.assertEqual(first, repeated)
        self.assertNotEqual(first, changed)

    def test_method_version_is_explicit(self):
        self.assertTrue(METHOD_VERSION.endswith("_v1"))


if __name__ == "__main__":
    unittest.main()
