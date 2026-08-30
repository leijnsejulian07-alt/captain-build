import copy
import json
import unittest
from pathlib import Path

from integration_manifest import integration_order, validate_manifest

HERE = Path(__file__).resolve().parent
BASE = json.loads((HERE / "integration-manifest.json").read_text(encoding="utf-8"))


class IntegrationManifestTests(unittest.TestCase):
    def test_current_manifest_is_valid(self):
        validate_manifest(BASE)
        order = integration_order(BASE)
        self.assertLess(order.index("scoped-jobs"), order.index("bounded-build-profiles"))
        self.assertLess(order.index("preview-session"), order.index("builder-artifacts"))
        self.assertLess(order.index("connector-health"), order.index("connector-notices"))

    def test_unknown_dependency_fails_closed(self):
        data = copy.deepcopy(BASE)
        data["components"][0]["depends_on"] = ["not-real"]
        with self.assertRaises(ValueError): validate_manifest(data)

    def test_cycle_fails_closed(self):
        data = copy.deepcopy(BASE)
        data["components"][0]["depends_on"] = ["scoped-jobs"]
        data["components"][1]["depends_on"] = ["agent-skills"]
        with self.assertRaises(ValueError): validate_manifest(data)

    def test_duplicate_pr_fails_closed(self):
        data = copy.deepcopy(BASE)
        data["components"][1]["pr"] = data["components"][0]["pr"]
        with self.assertRaises(ValueError): validate_manifest(data)

    def test_missing_acceptance_check_fails_closed(self):
        data = copy.deepcopy(BASE)
        data["required_local_checks"].remove("router")
        with self.assertRaises(ValueError): validate_manifest(data)

    def test_path_like_id_fails_closed(self):
        data = copy.deepcopy(BASE)
        data["components"][0]["id"] = "../escape"
        with self.assertRaises(ValueError): validate_manifest(data)

    def test_non_object_component_fails_closed(self):
        data = copy.deepcopy(BASE)
        data["components"][0] = "agent-skills"
        with self.assertRaises(ValueError): validate_manifest(data)

    def test_duplicate_external_prerequisite_fails_closed(self):
        data = copy.deepcopy(BASE)
        data["external_prerequisites"].append(data["external_prerequisites"][0])
        with self.assertRaises(ValueError): validate_manifest(data)

    def test_component_external_id_collision_fails_closed(self):
        data = copy.deepcopy(BASE)
        data["external_prerequisites"].append(data["components"][0]["id"])
        with self.assertRaises(ValueError): validate_manifest(data)


if __name__ == "__main__":
    unittest.main()
