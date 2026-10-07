"""Contract and version semantics: the tests deliberately mutate business-critical inputs."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from backend.metric_verification.config import ASSETS
from backend.metric_verification.mapping_contract import (
    validate_package, validate_document, content_hash, semantic_signatures, affected_metrics, _sql_dependencies,
)


def package_fixture():
    package = json.loads((ASSETS / "contracts" / "mapping-output.template.json").read_text(encoding="utf-8-sig"))
    package.update(template=False, packageId="test-package", analysisId="test-analysis")
    package["inputManifest"].update(template=False, analysisId="test-analysis")
    return package


class MappingContractTests(unittest.TestCase):
    def test_templates_match_schemas_but_cannot_be_published(self):
        for path in (ASSETS / "contracts").glob("*.template.json"):
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
            kind = path.name.removeprefix("mapping-").removesuffix(".template.json")
            self.assertEqual([], validate_document(doc, kind), path.name)
        package = package_fixture()
        self.assertTrue(validate_package(package)["valid"])
        package["template"] = True
        self.assertFalse(validate_package(package)["valid"])

    def test_unknown_and_non_business_roots_rejected(self):
        package = package_fixture()
        package["pages"] = [{"id": "page"}]
        self.assertFalse(validate_package(package)["valid"])

    def test_dangling_binding_and_steps_rejected(self):
        package = package_fixture()
        package["queries"][0]["dependencies"][0]["bindingId"] = "missing"
        self.assertFalse(validate_package(package)["valid"])
        package = package_fixture()
        package["metrics"][0]["processing"]["steps"][0]["dependsOn"] = ["STEP-RATIO"]
        self.assertFalse(validate_package(package)["valid"])

    def test_rule_and_metric_cycles_rejected(self):
        package = package_fixture()
        package["metrics"][0]["definition"]["metricRefs"] = [{"metricId": "O-10", "appliesTo": "formula", "parameterBindings": []}]
        self.assertFalse(validate_package(package)["valid"])

    def test_rule_change_invalidates_direct_and_transitive_only(self):
        package = package_fixture()
        first = package["metrics"][0]
        second, third = deepcopy(first), deepcopy(first)
        second["id"] = "O-SECOND"
        second["definition"]["ruleRefs"] = []
        second["definition"]["metricRefs"] = [{"metricId": "O-10", "appliesTo": "formula", "parameterBindings": []}]
        third["id"] = "O-INDEPENDENT"
        third["definition"]["ruleRefs"] = []
        package["metrics"].extend([second, third])
        before = semantic_signatures(package)
        package["sharedRules"][0]["definition"]["validityRules"][0]["text"] += "；新增有效性条件"
        after = semantic_signatures(package)
        self.assertNotEqual(before["O-10"], after["O-10"])
        self.assertNotEqual(before["O-SECOND"], after["O-SECOND"])
        self.assertEqual(before["O-INDEPENDENT"], after["O-INDEPENDENT"])
        self.assertEqual(["O-10", "O-SECOND"], affected_metrics(package, ["RULE-VALID-GRADE"]))

    def test_renaming_does_not_invalidate_business_signature(self):
        package = package_fixture()
        before = semantic_signatures(package)
        package["metrics"][0]["name"] = "名称润色"
        package["metrics"][0]["definition"]["businessPurpose"] = "用途文字说明"
        self.assertEqual(before, semantic_signatures(package))

    def test_unreviewed_shared_rule_change_blocks_activation_report(self):
        base = package_fixture()
        package = deepcopy(base)
        package["sharedRules"][0]["definition"]["validityRules"][0]["text"] += "新规则"
        report = validate_package(package, base)
        self.assertTrue(report["valid"], report["errors"])
        self.assertTrue(any(w.get("blocksActivation") for w in report["warnings"]))

    def test_delete_without_retirement_reason_rejected(self):
        base = package_fixture()
        package = deepcopy(base)
        package.update(metrics=[], queries=[], questions=[], validationCases=[])
        package["sharedRules"] = []
        self.assertFalse(validate_package(package, base)["valid"])

    def test_sql_dependency_and_readonly_protection(self):
        allowed = {"grades": ["student_id", "score"]}
        self.assertEqual([], _sql_dependencies("SELECT g.student_id,g.score FROM grades g", allowed))
        self.assertTrue(_sql_dependencies("SELECT g.secret FROM grades g", allowed))
        self.assertTrue(_sql_dependencies("SELECT secret FROM grades", allowed))
        self.assertTrue(_sql_dependencies("SELECT a.password FROM accounts a", allowed))
        self.assertTrue(_sql_dependencies("SELECT * FROM grades", allowed))
        self.assertEqual([], _sql_dependencies("WITH inputs AS (SELECT g.student_id,g.score FROM grades g) SELECT * FROM inputs", allowed))
        package = package_fixture()
        package["queries"][0]["sql"] = "SELECT 1; DROP TABLE grades"
        self.assertFalse(validate_package(package)["valid"])

    def test_ai_approval_does_not_unlock_unknown_sql(self):
        package = package_fixture()
        package["queries"][0]["executionApproval"] = "documented"
        result = validate_package(package)
        self.assertTrue(result["valid"])
        self.assertEqual("blocked", result["queryChecks"][package["queries"][0]["id"]]["executionApproval"])

    def test_canonical_hash_rejects_nonfinite_numbers(self):
        self.assertEqual(content_hash({"a": 1, "b": 2}), content_hash({"b": 2, "a": 1}))
        with self.assertRaises(ValueError):
            content_hash({"x": float("nan")})

    def test_raw_sample_rows_not_in_exchange_package(self):
        package = package_fixture()
        package["validationCases"][0]["execution"]["actualRows"] = [{"student_id": "S1"}]
        self.assertFalse(validate_package(package)["valid"])


if __name__ == "__main__":
    unittest.main()
