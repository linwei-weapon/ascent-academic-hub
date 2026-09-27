import csv
import io
import json
import re
import sqlite3
import unittest
from unittest.mock import patch

from backend.api.deps import require_metric_definition_reader
from backend.api.envelope import ApiError
from backend.api.routers.settings import (
    export_metric_catalog,
    metric_catalog_detail,
    metric_catalog_impact,
    metric_catalog_list,
)
from backend.metric_catalog import parse_confirmation_metrics
from backend.metric_catalog_v2 import (
    catalog_summary,
    get_metric_detail, list_governance_metrics,
    list_metrics,
    migrate_metric_catalog_v2,
)
from backend.metric_catalog_specification import (
    UNKNOWN,
    set_specification_override_status,
    upsert_specification_override,
)
from backend.metric_catalog_verified import iter_verified_metric_seeds
from scripts.migrate_menu import METRIC_QUERY_ROLES, migrate as migrate_menu


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE sys_menu (
            menu_id TEXT PRIMARY KEY,parent_id TEXT,title TEXT NOT NULL,
            path TEXT,icon TEXT,sort_order INTEGER DEFAULT 0
        );
        CREATE TABLE sys_role_menu (
            role_id TEXT,menu_id TEXT,PRIMARY KEY(role_id,menu_id)
        );
    """)
    return conn


class MetricCatalogV2Test(unittest.TestCase):
    def test_old_v2_schema_is_upgraded_in_place_idempotently(self):
        conn = make_conn()
        conn.executescript("""
            CREATE TABLE sys_metric_candidate (
                candidate_id TEXT PRIMARY KEY,source_kind TEXT NOT NULL,
                source_key TEXT NOT NULL,source_ref TEXT NOT NULL,
                metric_code TEXT,name TEXT NOT NULL,domain TEXT,formula TEXT,
                description TEXT,boundary TEXT,
                candidate_status TEXT NOT NULL DEFAULT 'pending_verification',
                payload_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                UNIQUE(source_kind,source_key)
            );
            CREATE TABLE sys_metric_registry (
                metric_id TEXT PRIMARY KEY,metric_code TEXT NOT NULL UNIQUE,
                technical_kpi_id TEXT,current_version_id TEXT,
                lifecycle_status TEXT NOT NULL DEFAULT 'active',
                source_kind TEXT NOT NULL DEFAULT 'formal',
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE sys_metric_version (
                version_id TEXT PRIMARY KEY,metric_id TEXT NOT NULL,
                version_no TEXT NOT NULL,name TEXT NOT NULL,description TEXT,
                formula TEXT NOT NULL,boundary TEXT,management_value TEXT,
                domain TEXT NOT NULL,unit TEXT,value_type TEXT,grain TEXT,
                data_source TEXT,update_cycle TEXT,
                definition_status TEXT NOT NULL,
                implementation_status TEXT NOT NULL,
                effective_status TEXT NOT NULL DEFAULT 'current',
                source_ref TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                UNIQUE(metric_id,version_no),
                FOREIGN KEY(metric_id) REFERENCES sys_metric_registry(metric_id)
            );
        """)
        first = migrate_metric_catalog_v2(conn)
        second = migrate_metric_catalog_v2(conn)
        for table in ("sys_metric_candidate", "sys_metric_version"):
            columns = {
                row[1] for row in conn.execute(f"PRAGMA table_info({table})")
            }
            self.assertTrue({
                "specification_json", "specification_status",
                "specification_source", "specification_updated_at",
            }.issubset(columns))
        self.assertEqual(first, second)
        self.assertEqual(1, second["snapshots"])
        conn.close()

    def test_all_formal_and_candidate_metrics_have_structured_specifications(self):
        conn = make_conn()
        result = migrate_metric_catalog_v2(conn)
        required = {
            "indicatorDescription", "calculationRule",
            "definitionDescription", "managementUse", "statisticalObject",
            "statisticalScope", "calculationType", "calculationFormula",
            "numerator", "denominator", "denominatorZeroRule",
            "deduplicationRule", "inclusionRule", "exclusionRule",
            "boundaryRule", "nullHandlingRule", "precisionRule",
            "dataSources", "dataAsOfRule", "quality",
        }
        formal_rows = conn.execute("""
            SELECT specification_json,value_type FROM sys_metric_version
            WHERE effective_status='current'
        """).fetchall()
        candidate_rows = conn.execute("""
            SELECT specification_json FROM sys_metric_candidate
            WHERE candidate_status<>'removed_from_source'
        """).fetchall()
        self.assertEqual(result["formalMetrics"], len(formal_rows))
        self.assertEqual(result["candidateMetrics"], len(candidate_rows))
        for row in formal_rows + candidate_rows:
            specification = json.loads(row[0])
            self.assertTrue(required.issubset(specification))
            self.assertNotEqual({}, specification)
            self.assertTrue(specification["indicatorDescription"].strip())
            self.assertTrue(specification["calculationRule"].strip())
            self.assertIsNone(re.search(r"[A-Za-z_]", specification["calculationRule"]))
        self.assertTrue(all(row[1] and row[1].strip() for row in formal_rows))

        listed = list_metrics(conn, page_size=1)["items"][0]
        self.assertEqual(
            listed["specification"]["indicatorDescription"],
            listed["description"],
        )
        self.assertEqual(
            listed["specification"]["calculationRule"],
            listed["formula"],
        )
        self.assertIn("specificationStatus", listed)
        self.assertIn("management_value", listed)
        candidate = list_governance_metrics(
            conn, definition_status="pending_confirmation", page_size=1,
        )["items"][0]
        candidate_detail = get_metric_detail(conn, candidate["metric_id"])
        self.assertEqual(
            candidate_detail["metric"]["description"],
            candidate_detail["specification"]["indicatorDescription"],
        )
        self.assertEqual(
            "candidate_needs_confirmation",
            candidate_detail["metric"]["specificationStatus"],
        )
        conn.close()

    def test_display_formulas_are_chinese_business_rules(self):
        conn = make_conn()
        migrate_metric_catalog_v2(conn)
        for row in conn.execute("""
            SELECT metric_id,specification_json FROM sys_metric_version
            WHERE effective_status='current'
        """):
            specification = json.loads(row[1])
            description = specification["indicatorDescription"]
            formula = specification["calculationRule"]
            self.assertTrue(description.strip(), row[0])
            self.assertTrue(formula.strip(), row[0])
            self.assertIsNone(
                re.search(r"[A-Za-z_]", formula),
                f"{row[0]}: {formula}",
            )
            self.assertNotIn("下钻", formula, row[0])
            self.assertNotIn("No Data", formula, row[0])
        conn.close()

    def test_ratio_specs_make_zero_denominator_handling_explicit(self):
        conn = make_conn()
        migrate_metric_catalog_v2(conn)
        for row in conn.execute("""
            SELECT metric_id,specification_json FROM sys_metric_version
            WHERE effective_status='current'
        """):
            specification = json.loads(row[1])
            if specification["calculationType"] != "ratio":
                continue
            self.assertTrue(specification["denominatorZeroRule"], row[0])
            self.assertTrue(
                "分母" in specification["denominatorZeroRule"]
                or UNKNOWN in specification["denominatorZeroRule"],
                row[0],
            )
        for metric_id in ("F-09", "F-19"):
            specification = get_metric_detail(conn, metric_id)["specification"]
            self.assertIn("—", specification["denominatorZeroRule"])
        g16 = get_metric_detail(conn, "G-16")["specification"]
        self.assertNotIn(UNKNOWN, g16["denominatorZeroRule"])
        self.assertIn("分母为0", g16["denominatorZeroRule"])
        conn.close()

    def test_faculty_examples_expose_confirmed_boundaries_and_mismatch(self):
        conn = make_conn()
        migrate_metric_catalog_v2(conn)
        for metric_id in (
            "F-01", "F-09", "F-10", "F-17", "F-18", "F-19",
            "TA.FAC.EVALUABLE_COURSES", "TA.FAC.IMPORTANT_COURSE_FLAG",
        ):
            metric = get_metric_detail(conn, metric_id)["metric"]
            self.assertNotEqual(metric["description"], metric["management_value"])
            self.assertTrue(metric["specificationQuality"]["curatedSpecificationApplied"])

        f10 = get_metric_detail(conn, "F-10")["specification"]
        self.assertIn("规则A（连续单点）", f10["indicatorDescription"])
        self.assertIn("按课程编号去重计数", f10["calculationRule"])
        self.assertIn("DISTINCT", f10["deduplicationRule"])
        self.assertIn("恰好55岁同时属于两侧", f10["boundaryRule"])
        self.assertIn("不触发", f10["nullHandlingRule"])
        evaluable = get_metric_detail(
            conn, "TA.FAC.EVALUABLE_COURSES"
        )["specification"]
        self.assertIn("DISTINCT", evaluable["deduplicationRule"])
        self.assertIn("至少有1个有效教学班", evaluable["inclusionRule"])
        important_detail = get_metric_detail(
            conn, "TA.FAC.IMPORTANT_COURSE_FLAG"
        )
        self.assertIn("不得据此形成风险结论", important_detail["specification"]["nullHandlingRule"])
        priority = get_metric_detail(conn, "TA.FAC.PRIORITY_REVIEW_COURSES")
        self.assertIn(
            "TA.FAC.IMPORTANT_COURSE_FLAG",
            {item["metric_id"] for item in priority["dependencies"]},
        )
        f19 = get_metric_detail(conn, "F-19")["metric"]
        self.assertIn("35岁以下青年授课教师数", f19["description"])
        self.assertIn("× 100%", f19["formula"])
        self.assertEqual("mismatch", f19["specificationStatus"])
        self.assertIn(
            "implementation_definition_mismatch",
            {item["code"] for item in f19["specificationQuality"]["issues"]},
        )
        conn.close()

    def test_human_override_is_audited_and_formula_safe(self):
        conn = make_conn()
        migrate_metric_catalog_v2(conn)
        before = get_metric_detail(conn, "F-09")["metric"]
        override_id = upsert_specification_override(
            conn,
            subject_kind="formal",
            subject_id="F-09",
            override_key="faculty-pdf",
            patch={"precisionRule": "经人工PDF初审：比例保留2位小数。"},
            reason="人工初审师资指标示例",
            source_ref="faculty-definition.pdf#p12",
            changed_by="catalog-reviewer",
        )
        self.assertEqual(override_id, upsert_specification_override(
            conn,
            subject_kind="formal",
            subject_id="F-09",
            override_key="faculty-pdf",
            patch={
                "precisionRule": "经人工PDF核准：比例保留1位小数。",
                "notes": "示例口径已人工复核。",
            },
            reason="人工核准师资指标示例",
            source_ref="faculty-definition.pdf#p12",
            changed_by="catalog-reviewer",
        ))
        set_specification_override_status(
            conn, subject_kind="formal", subject_id="F-09",
            override_key="faculty-pdf", active=False,
            changed_by="catalog-reviewer",
        )
        self.assertEqual(override_id, upsert_specification_override(
            conn,
            subject_kind="formal",
            subject_id="F-09",
            override_key="faculty-pdf",
            patch={
                "precisionRule": "经人工PDF核准：比例保留1位小数。",
                "notes": "示例口径已人工复核。",
            },
            reason="人工核准师资指标示例",
            source_ref="faculty-definition.pdf#p12",
            changed_by="catalog-reviewer",
        ))
        after_first = migrate_metric_catalog_v2(conn)
        after_second = migrate_metric_catalog_v2(conn)
        after = get_metric_detail(conn, "F-09")["metric"]
        self.assertEqual(before["metric_id"], after["metric_id"])
        self.assertEqual(before["formula"], after["formula"])
        self.assertEqual(
            "经人工PDF核准：比例保留1位小数。",
            after["specification"]["precisionRule"],
        )
        self.assertTrue(after["specificationQuality"]["overrideApplied"])
        self.assertEqual(
            override_id,
            after["specificationQuality"]["overrideSources"][0]["overrideId"],
        )
        self.assertEqual(after_first, after_second)
        self.assertEqual(2, after_second["snapshots"])
        self.assertEqual(
            ["created", "updated", "deactivated", "activated"],
            [row[0] for row in conn.execute("""
                SELECT action FROM sys_metric_spec_override_revision
                WHERE override_id=? ORDER BY revision_no
            """, (override_id,))],
        )
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("""
                UPDATE sys_metric_spec_override_revision SET reason='changed'
                WHERE override_id=? AND revision_no=1
            """, (override_id,))
        with self.assertRaises(ValueError):
            upsert_specification_override(
                conn, subject_kind="formal", subject_id="F-09",
                patch={"unsupportedField": "x"}, reason="bad",
                source_ref="test",
            )
        for invalid_patch in (
            {"calculationFormula": "another formula"},
            {"calculationType": "unsupported"},
            {"statisticalScope": ""},
            {"dataSources": []},
            {"qualityDisclosures": [{"field": "x"}]},
        ):
            with self.assertRaises(ValueError):
                upsert_specification_override(
                    conn, subject_kind="formal", subject_id="F-09",
                    override_key="invalid", patch=invalid_patch,
                    reason="invalid", source_ref="test",
                )
        conn.close()

    def test_candidate_override_uses_public_code_and_compatibility_fields(self):
        conn = make_conn()
        migrate_metric_catalog_v2(conn)
        candidate = list_governance_metrics(
            conn, definition_status="pending_confirmation", page_size=1,
        )["items"][0]
        metric_code = candidate["metric_id"]
        upsert_specification_override(
            conn, subject_kind="candidate", subject_id=metric_code,
            override_key="college-review",
            patch={
                "definitionDescription": "学院人工核准的候选指标定义。",
                "managementUse": "学院人工核准的候选指标管理用途。",
            },
            reason="学院人工确认", source_ref="college-review.pdf#p1",
        )
        stored = conn.execute("""
            SELECT subject_id FROM sys_metric_spec_override
            WHERE subject_kind='candidate' AND override_key='college-review'
        """).fetchone()[0]
        self.assertEqual(metric_code, stored)
        self.assertFalse(stored.startswith("candidate:"))
        migrate_metric_catalog_v2(conn)
        metric = get_metric_detail(conn, metric_code)["metric"]
        self.assertTrue(metric["description"].startswith("学院人工核准的候选指标定义。"))
        self.assertEqual(
            "学院人工核准的候选指标管理用途。", metric["management_value"]
        )
        self.assertTrue(metric["specificationQuality"]["overrideApplied"])
        conn.close()

    def test_explicit_seed_value_type_is_not_overwritten(self):
        conn = make_conn()
        explicit = [
            dict(seed)
            for seed in iter_verified_metric_seeds(parse_confirmation_metrics())
        ]
        target = next(seed for seed in explicit if seed["metric_id"] == "F-01")
        target["value_type"] = "teacher_count"
        with patch(
            "backend.metric_catalog_v2.iter_verified_metric_seeds",
            return_value=explicit,
        ):
            migrate_metric_catalog_v2(conn)
        value_type = conn.execute("""
            SELECT value_type FROM sys_metric_version
            WHERE metric_id='F-01' AND effective_status='current'
        """).fetchone()[0]
        self.assertEqual("teacher_count", value_type)
        conn.close()

    def test_migration_is_idempotent_and_separates_candidates(self):
        conn = make_conn()
        first = migrate_metric_catalog_v2(conn)
        second = migrate_metric_catalog_v2(conn)
        self.assertEqual(first, second)
        self.assertGreaterEqual(second["candidateMetrics"], 200)
        self.assertEqual(
            len(iter_verified_metric_seeds(parse_confirmation_metrics())),
            second["formalMetrics"],
        )
        # Code inspection may add implemented technical/helper metrics that
        # are absent from the confirmation document; the two sets are not a
        # subset/count relationship.
        self.assertGreaterEqual(second["formalMetrics"], 1)
        self.assertEqual(1, second["snapshots"])
        self.assertFalse([
            seed["metric_id"]
            for seed in iter_verified_metric_seeds(parse_confirmation_metrics())
            if "按已发布" in (seed.get("formula") or "")
            or "condition is met" in (seed.get("formula") or "").casefold()
        ])
        conn.close()

    def test_filters_cover_module_tags_and_aliases(self):
        conn = make_conn()
        migrate_metric_catalog_v2(conn)
        by_module = list_metrics(conn, module_id="/admin/faculty")
        self.assertGreaterEqual(by_module["total"], 1)
        analysis = next(
            item for item in by_module["facets"]["modules"]
            if item["module_id"] == "/admin/analysis"
        )
        self.assertGreaterEqual(analysis["count"], by_module["total"])
        self.assertTrue(any(
            item["module_id"] == "/admin/faculty"
            for item in analysis["children"]
        ))
        self.assertTrue(all(
            any(u["module_path"] == "/admin/faculty" for u in item["usages"])
            for item in by_module["items"]
        ))
        by_tag = list_metrics(conn, tag_ids="object:teacher")
        self.assertTrue(any(item["metric_id"] == "F-01" for item in by_tag["items"]))
        by_alias = list_metrics(conn, name="current_fail_rate")
        self.assertIn("O-10", [item["metric_id"] for item in by_alias["items"]])
        self.assertEqual("comma-separated", by_alias["filters"]["tagIdsFormat"])
        conn.close()

    def test_usage_count_deduplicates_occurrences_but_keeps_feature_points(self):
        conn = make_conn()
        migrate_metric_catalog_v2(conn)
        conn.execute("""
            INSERT INTO sys_metric_feature_point(
                feature_point_id,module_id,name,description,source_ref
            ) VALUES('fp-extra','/admin/faculty','学院对比卡片','学院对比','test')
        """)
        conn.executemany("""
            INSERT INTO sys_metric_usage(
                usage_id,metric_id,feature_point_id,usage_type,occurrence_key,
                display_name,source_ref
            ) VALUES(?, 'F-01','fp-extra','display',?, '授课教师总数','test')
        """, (("u-extra-1", "card"), ("u-extra-2", "tooltip")))
        detail = get_metric_detail(conn, "F-01")
        feature_points = {
            usage["feature_point_id"] for usage in detail["usagePoints"]
        }
        self.assertEqual(len(feature_points), detail["metric"]["usagePointCount"])
        self.assertIn("fp-extra", feature_points)
        extra = [u for u in detail["usagePoints"] if u["feature_point_id"] == "fp-extra"]
        self.assertEqual(2, len(extra))
        self.assertEqual("教学管理分析", extra[0]["level1"])
        self.assertEqual("师资保障分析", extra[0]["level2"])
        conn.close()

    def test_dependency_direction_counts_and_impact(self):
        conn = make_conn()
        migrate_metric_catalog_v2(conn)
        f17 = metric_catalog_detail("F-17", conn=conn, _={})["data"]
        f01 = metric_catalog_detail("F-01", conn=conn, _={})["data"]
        self.assertEqual(
            len({item["metric_id"] for item in f17["dependencies"]}),
            f17["metric"]["referencedMetricCount"],
        )
        self.assertIn("F-01", [item["metric_id"] for item in f17["dependencies"]])
        self.assertEqual(
            len({item["metric_id"] for item in f01["dependents"]}),
            f01["metric"]["dependentMetricCount"],
        )
        self.assertIn("F-17", [item["metric_id"] for item in f01["dependents"]])
        impact = metric_catalog_impact("F-01", conn=conn, _={})["data"]
        self.assertIn("F-17", [m["metric_id"] for m in impact["directDependents"]])
        self.assertGreaterEqual(impact["summary"]["affectedUsagePointCount"], 1)
        conn.close()

    def test_extension_pack_issues_rules_and_usages_are_published(self):
        conn = make_conn()
        migrate_metric_catalog_v2(conn)
        band = metric_catalog_detail(
            "BR-FAIL-COURSE-BAND-STUDENT-COUNT", conn=conn, _={}
        )["data"]
        self.assertTrue(any(
            issue["issue_type"] == "display_formula_mismatch"
            for issue in band["issues"]
        ))
        alert = metric_catalog_detail(
            "BR-R2-UNRESOLVED-COURSE-COUNT", conn=conn, _={}
        )["data"]
        self.assertEqual({"R2", "R2W"}, {
            rule["name"] for rule in alert["rules"]
        })
        dashboard = metric_catalog_detail("O-01", conn=conn, _={})["data"]
        self.assertTrue(any(
            usage["module_path"].startswith("/admin/basic-reports/")
            for usage in dashboard["usagePoints"]
        ))
        conn.close()

    def test_current_query_hides_retired_metrics_and_export_is_not_truncated(self):
        conn = make_conn()
        migrate_metric_catalog_v2(conn)
        current = list_metrics(conn, page=1, page_size=100)
        self.assertGreater(current["total"], 100)
        self.assertNotIn(
            "LEGACY-GRAD-RATE", [item["metric_id"] for item in current["items"]]
        )
        retired = list_metrics(conn, implementation_status="retired")
        self.assertEqual(
            {"LEGACY-GRAD-RATE", "LEGACY-DEGREE-RATE"},
            {item["metric_id"] for item in retired["items"]},
        )

        response = export_metric_catalog(conn=conn, _={})
        rows = list(csv.reader(io.StringIO(response.body.decode("utf-8-sig"))))
        self.assertEqual(current["total"] + 1, len(rows))
        conn.close()

    def test_governance_scope_keeps_unmatched_candidates_queryable(self):
        conn = make_conn()
        migrate_metric_catalog_v2(conn)
        summary = catalog_summary(conn)
        pending = list_governance_metrics(
            conn, definition_status="pending_confirmation", page_size=100,
        )
        self.assertEqual(summary["pendingConfirmation"], pending["total"])
        self.assertGreater(pending["total"], 0)
        candidate_id = pending["items"][0]["metric_id"]
        self.assertIsNotNone(get_metric_detail(conn, candidate_id))
        self.assertNotIn(
            candidate_id,
            [item["metric_id"] for item in list_metrics(
                conn, name=candidate_id, page_size=100,
            )["items"]],
        )
        mismatch = list_governance_metrics(
            conn, implementation_status="mismatch", page_size=100,
        )
        self.assertEqual(summary["inconsistent"], mismatch["total"])
        self.assertGreater(mismatch["total"], 0)
        response = export_metric_catalog(catalog_scope="governance", conn=conn, _={})
        rows = list(csv.reader(io.StringIO(response.body.decode("utf-8-sig"))))
        self.assertEqual(summary["total"] + 1, len(rows))
        conn.close()

    def test_get_endpoints_are_read_only_and_unmigrated_schema_returns_503(self):
        conn = make_conn()
        with self.assertRaises(ApiError) as caught:
            metric_catalog_list(conn=conn, _={})
        self.assertEqual(503, caught.exception.status_code)

        migrate_metric_catalog_v2(conn)
        write_ops = {
            sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
            sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_CREATE_INDEX,
            sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_DROP_INDEX,
        }

        def authorizer(action, _arg1, _arg2, _db_name, _trigger):
            return sqlite3.SQLITE_DENY if action in write_ops else sqlite3.SQLITE_OK

        conn.set_authorizer(authorizer)
        metric_catalog_list(conn=conn, _={})
        metric_catalog_detail("O-10", conn=conn, _={})
        metric_catalog_impact("F-01", conn=conn, _={})
        conn.set_authorizer(None)
        conn.close()

    def test_menu_coexists_with_management_page_and_read_permission(self):
        conn = make_conn()
        migrate_menu(conn)
        query_roles = {
            row[0] for row in conn.execute("""
                SELECT role_id FROM sys_role_menu
                WHERE menu_id='/admin/system/metric-query'
            """)
        }
        self.assertEqual(set(METRIC_QUERY_ROLES), query_roles)
        self.assertTrue(conn.execute("""
            SELECT 1 FROM sys_role_menu
            WHERE role_id='dean' AND menu_id='/admin/system/kpis'
        """).fetchone())
        self.assertEqual(
            "school_leader",
            require_metric_definition_reader({
                "role_id": "school_leader",
                "permission_context": {"actionPermissions": ["definition.read"]},
            })["role_id"],
        )
        with self.assertRaises(ApiError):
            require_metric_definition_reader({
                "role_id": "counselor",
                "permission_context": {"actionPermissions": []},
            })
        conn.close()


if __name__ == "__main__":
    unittest.main()
