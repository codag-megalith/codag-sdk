"""Regression tests for required-field coverage in the shared fixture table."""

import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE_SPEC = importlib.util.spec_from_file_location(
    "check_openapi", ROOT / "scripts" / "check_openapi.py"
)
contract = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(contract)


class ContractCoverageCase(unittest.TestCase):
    def setUp(self):
        self.schemas = json.loads(contract.SPEC.read_text())["components"]["schemas"]
        self.cases = json.loads(contract.CASES.read_text())

    def test_shared_cases_cover_required_fields(self):
        contract.check_required_fields_are_covered(self.schemas, self.cases)

    def test_invalid_value_cases_do_not_replace_omission_cases(self):
        for name, field in (
            ("metric_missing_action_kind", "action_kind"),
            ("metric_missing_decision", "decision"),
            ("action_missing_kind", "kind"),
            ("action_missing_tool", "tool"),
        ):
            with self.subTest(case=name):
                cases = [case for case in self.cases if case["name"] != name]
                with self.assertRaisesRegex(SystemExit, field):
                    contract.check_required_fields_are_covered(self.schemas, cases)

    def test_omission_case_must_match_an_accepted_input(self):
        cases = copy.deepcopy(self.cases)
        case = next(case for case in cases if case["name"] == "metric_missing_id")
        case["input"]["events"][0]["decision"] = ""
        with self.assertRaisesRegex(SystemExit, "id"):
            contract.check_required_fields_are_covered(self.schemas, cases)

    def test_new_required_field_needs_coverage(self):
        self.schemas["MetricEvent"]["required"].append("session_id")
        with self.assertRaisesRegex(SystemExit, "session_id"):
            contract.check_required_fields_are_covered(self.schemas, self.cases)


if __name__ == "__main__":
    unittest.main()
