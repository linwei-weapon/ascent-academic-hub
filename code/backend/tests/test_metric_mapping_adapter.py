"""Consumer compatibility must not turn existing supporting metrics into new acceptance tasks."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from backend.metric_verification.config import ASSETS
from backend.metric_verification import registry
from backend.metric_verification.mapping_adapter import catalog, queries_document, metric_sources
from backend.metric_verification.mapping_contract import validate_package
from backend.metric_verification.mapping_store import legacy_bindings


class MappingAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package = json.loads((ASSETS / "mappings" / "teaching-overview" / "package.json").read_text(encoding="utf-8-sig"))
        cls.validation = validate_package(cls.package)
        if not cls.validation["valid"]:
            raise AssertionError(cls.validation["errors"])
        cls.bindings = legacy_bindings(cls.package)

    def revision(self, bindings=None):
        return {"revisionId": "isolated-compatibility", "package": self.package,
                "validation": self.validation, "bindings": bindings or self.bindings}

    def old_frozen_bindings(self):
        old = deepcopy(self.bindings)
        primary = {e["metricId"] for e in old["entries"]}
        supporting = {mid for e in old["entries"] for mid in e.get("evidenceMetricIds", [])}
        for entry in old["entries"]:
            entry.pop("name", None)  # The original frozen adapter omitted this presentation field.
        for mid in supporting - primary:
            req_id = "mapping-anchor:" + mid
            old["entries"].append({"id": "mapping:" + mid, "metricId": mid, "requirementId": req_id,
                                   "pageId": "home", "group": "自动关联", "aliases": [], "evidenceMetricIds": [],
                                   "comparisonKind": "scalar", "internalCompatibilityAnchor": True})
            old["requirements"][req_id] = {"id": req_id, "section": "内部关联", "area": "总览"}
        self.assertEqual(9, len(supporting - primary))
        return old

    def assert_expected_catalog(self, document):
        entries = document["indicatorSystem"]["entries"]
        self.assertEqual(75, len(document["metrics"]))
        self.assertEqual(113, len(entries))
        self.assertEqual(18, sum(e["pageId"] == "home" for e in entries))
        self.assertFalse(any(e["id"].startswith("mapping:") for e in entries))
        self.assertFalse(any(r["id"].startswith("mapping-anchor:") for r in document["requirements"]))
        named = {e["id"]: e["name"] for e in entries}
        self.assertEqual("重点核查课程TOP10", named["home-o-21"])
        self.assertEqual("优先核查课程TOP1", named["home-course-top1"])

    def test_new_bindings_preserve_existing_scene_and_component_boundaries(self):
        self.assert_expected_catalog(catalog(self.revision()))

    def test_old_frozen_fallbacks_are_filtered_without_mutating_snapshot(self):
        old = self.old_frozen_bindings()
        before = deepcopy(old)
        self.assert_expected_catalog(catalog(self.revision(old)))
        self.assertEqual(before, old)
        # A later revision also stops carrying those generated anchors forward.
        next_bindings = legacy_bindings(self.package, old)
        self.assert_expected_catalog(catalog(self.revision(next_bindings)))
        self.assertEqual("优先核查课程TOP1", next(e for e in next_bindings["entries"] if e["id"] == "home-course-top1")["name"])

    def test_supporting_metric_queries_remain_accessible_from_original_scene(self):
        revision = self.revision(self.old_frozen_bindings())
        with patch.object(registry, "_active_revision", return_value=revision):
            document = registry.catalog()
            primary = {e["metricId"] for e in document["indicatorSystem"]["entries"]}
            supporting = {mid for e in document["indicatorSystem"]["entries"] for mid in e.get("evidenceMetricIds", [])} - primary
            for mid in supporting:
                scene = next(e for e in document["indicatorSystem"]["entries"] if mid in e.get("evidenceMetricIds", []))
                self.assertEqual(scene["id"], registry.scenario(scene["id"], scene["requirementId"], mid, allow_evidence=True)["id"])
                self.assertIn(mid, registry.requirement(scene["requirementId"])["metricIds"])
                metric_queries = registry.metric_queries(mid, allow_execute=True)
                self.assertTrue(any(layer["queries"] for layer in metric_queries["layers"]), mid)

    def test_specific_frozen_alias_is_preserved_and_formula_comes_from_package(self):
        bindings = self.old_frozen_bindings()
        target = next(e for e in bindings["entries"] if e["id"] == "home-course-top1")
        target["aliases"] = ["已确认的课程优先核查TOP1", "O-21"]
        document = catalog(self.revision(bindings))
        entry = next(e for e in document["indicatorSystem"]["entries"] if e["id"] == target["id"])
        metric = next(m for m in self.package["metrics"] if m["id"] == "O-21")
        self.assertEqual(target["aliases"][0], entry["name"])
        self.assertEqual(metric["definition"]["formula"], entry["formula"])

    def test_only_a_truly_unassociated_new_metric_gets_a_fallback(self):
        package = deepcopy(self.package)
        added = deepcopy(package["metrics"][0])
        added.update(id="NEW-BUSINESS-METRIC", name="新的独立业务指标")
        package["metrics"].append(added)
        bindings = legacy_bindings(package)
        generated = [e for e in bindings["entries"] if e.get("internalCompatibilityAnchor")]
        self.assertEqual(["NEW-BUSINESS-METRIC"], [e["metricId"] for e in generated])
        self.assertEqual("新的独立业务指标", generated[0]["name"])

    def test_layer_explanation_is_human_readable_and_dialect_duplicates_are_removed(self):
        package = deepcopy(self.package)
        metric = next(m for m in package["metrics"] if m["id"] == "O-10")
        step = metric["processing"]["steps"][-1]
        step.update(physicalPredicate=None, fieldMappings=None, description="按相同学期和学院范围选取对应结果")
        output_layer = next(n["layer"] for n in metric["lineage"]["nodes"] if n["id"] == step["outputNodeId"])
        source_plan = next(p for p in metric["verificationPlan"]["queriesByLayer"] if p["layer"] == "source")
        metric["verificationPlan"]["queriesByLayer"].append(deepcopy(source_plan))
        revision = {**self.revision(), "package": package}
        view = next(m for m in queries_document(revision)["metrics"] if m["metricId"] == "O-10")
        rendered = next(layer for layer in view["layers"] if layer["id"] == output_layer)
        self.assertIn(step["description"], rendered["transform"])
        self.assertNotIn("select_result", rendered["transform"])
        source = next(layer for layer in view["layers"] if layer["id"] == "source")
        self.assertEqual(len(source["directSource"].split("、")), len(set(source["directSource"].split("、"))))
        self.assertEqual(len(source["issues"]), len(set(source["issues"])))
        self.assertEqual(len(source["remainingGaps"]), len(set(source["remainingGaps"])))
        self.assertIn("mappingSources", view)

    def test_metric_sources_include_processing_and_requirement_evidence_without_unrelated_excerpts(self):
        package = deepcopy(self.package)
        metric = next(m for m in package["metrics"] if m["id"] == "O-10")
        source = package["sourceManifest"][0]
        source["evidence"].extend([
            {"id": "processing-citation", "excerpt": "Required join evidence", "schemaSnapshot": {"columns": ["unrelated_table.secret_column"]}},
            {"id": "unrelated-citation", "excerpt": "Another metric only"},
        ])
        metric["processing"]["steps"][0]["evidenceRefs"].append("processing-citation")
        rendered = metric_sources(package, metric)
        ids = {item["id"] for source in rendered for item in source["evidence"]}
        self.assertIn("processing-citation", ids)
        self.assertFalse(any("schemaSnapshot" in item for source in rendered for item in source["evidence"]))
        self.assertNotIn("unrelated-citation", ids)
        self.assertTrue(set(metric["definition"]["evidenceRefs"]).issubset(ids))
        self.assertTrue(set(metric["actualBinding"]["evidenceRefs"]).issubset(ids))
        rendered[0]["evidence"].clear()
        self.assertTrue(source["evidence"])


if __name__ == "__main__":
    unittest.main()
