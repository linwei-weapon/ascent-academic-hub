import sqlite3
import unittest

from backend.api.envelope import ApiError
from backend.api.main import _sensitive_read_event
from backend.api.routers.system_management import (
    PARAMETER_DEFAULTS,
    _validate_parameter,
)
from backend.api.routers.settings import (
    metric_catalog_detail,
    metric_catalog_list,
    metric_catalog_pages,
    metric_catalog_summary,
)
from backend.etl.seed import DEMO_PASSWORD, hash_password
from backend.permission_catalog import ACTION_CATALOG
from backend.api.security import verify_password
from scripts.migrate_system_management import harden_legacy_demo_admin, migrate


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE sys_menu (
            menu_id TEXT PRIMARY KEY,
            parent_id TEXT,
            title TEXT NOT NULL,
            path TEXT,
            icon TEXT,
            sort_order INTEGER DEFAULT 0
        );
        CREATE TABLE sys_role_menu (
            role_id TEXT,
            menu_id TEXT,
            PRIMARY KEY(role_id,menu_id)
        );
    """)
    return conn


class SystemManagementTest(unittest.TestCase):
    def test_migration_completes_system_modules_and_is_idempotent(self):
        conn = make_conn()
        first = migrate(conn)
        second = migrate(conn)
        self.assertEqual(first, second)
        self.assertEqual(10, second["systemMenus"])
        self.assertEqual(len(PARAMETER_DEFAULTS), second["systemParameters"])
        # 8 条总览指标 + M1 新增 4 条课程质量三分层指标。
        self.assertEqual(12, second["registeredKpis"])
        self.assertGreaterEqual(second["metricDefinitions"], 200)
        system_titles = {
            row["title"] for row in conn.execute(
                "SELECT title FROM sys_menu WHERE parent_id='/admin/system'"
            )
        }
        self.assertEqual({
            "账号管理", "角色与功能权限", "菜单管理", "数据权限",
            "指标与口径管理", "分析方案管理", "审计日志", "系统参数",
            "决策配置", "数据采集监控",
        }, system_titles)
        conn.close()

    def test_registered_kpi_formula_replaces_legacy_placeholder(self):
        conn = make_conn()
        conn.execute("""
            CREATE TABLE sys_kpi_config (
                kpi_id TEXT PRIMARY KEY,module TEXT NOT NULL,label TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,sort_order INTEGER DEFAULT 0,
                calc_type TEXT,formula TEXT,unit TEXT,color_rule TEXT,
                threshold_warn REAL,threshold_danger REAL,
                scope_applicable TEXT DEFAULT 'all',
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.execute("""
            INSERT INTO sys_kpi_config(
              kpi_id,module,label,calc_type,formula,unit
            ) VALUES('student_count','dashboard','学生数','count','count_all','人')
        """)
        migrate(conn)
        row = conn.execute("""
            SELECT label,formula,data_source,management_value
            FROM sys_kpi_config WHERE kpi_id='student_count'
        """).fetchone()
        self.assertEqual("在籍学生数", row["label"])
        self.assertEqual("在籍状态学生去重计数", row["formula"])
        self.assertEqual("dim_student", row["data_source"])
        self.assertTrue(row["management_value"])
        conn.close()

    def test_metric_catalog_separates_definition_binding_and_legacy_status(self):
        conn = make_conn()
        result = migrate(conn)
        self.assertGreaterEqual(result["metricDefinitions"], 200)
        current = conn.execute("""
            SELECT name,formula,definition_status,implementation_status,
                   technical_kpi_id
            FROM sys_metric_definition WHERE metric_id='O-10'
        """).fetchone()
        self.assertEqual("当前挂科学生率", current["name"])
        self.assertIn("去重学生数", current["formula"])
        self.assertEqual("published", current["definition_status"])
        self.assertEqual("verified", current["implementation_status"])
        self.assertEqual("current_fail_rate", current["technical_kpi_id"])

        legacy = conn.execute("""
            SELECT definition_status,implementation_status,page_refs
            FROM sys_metric_definition WHERE metric_id='LEGACY-GRAD-RATE'
        """).fetchone()
        self.assertEqual("deprecated", legacy["definition_status"])
        self.assertEqual("retired", legacy["implementation_status"])
        self.assertEqual("[]", legacy["page_refs"])

        registered = conn.execute("""
            SELECT label,formula,version,enabled,page_refs
            FROM sys_kpi_config WHERE kpi_id='current_fail_rate'
        """).fetchone()
        self.assertEqual("当前挂科学生率", registered["label"])
        self.assertIn("去重学生数", registered["formula"])
        self.assertEqual("2.0", registered["version"])
        self.assertEqual(1, registered["enabled"])

        retired = conn.execute("""
            SELECT enabled,page_refs FROM sys_kpi_config
            WHERE kpi_id='grad_rate'
        """).fetchone()
        self.assertEqual(0, retired["enabled"])
        self.assertEqual("[]", retired["page_refs"])

        orphan_bindings = conn.execute("""
            SELECT COUNT(*) FROM sys_metric_page_binding b
            LEFT JOIN sys_metric_definition d ON d.metric_id=b.metric_id
            WHERE d.metric_id IS NULL
        """).fetchone()[0]
        self.assertEqual(0, orphan_bindings)
        conn.close()

    def test_metric_catalog_api_supports_summary_filter_paging_and_detail(self):
        conn = make_conn()
        migrate(conn)
        summary = metric_catalog_summary(conn=conn, _={})["data"]
        self.assertGreaterEqual(summary["total"], 200)
        self.assertGreaterEqual(summary["verified"], 9)
        self.assertGreaterEqual(summary["pendingConfirmation"], 190)
        self.assertGreaterEqual(summary["boundPages"], 5)

        listing = metric_catalog_list(
            page=1, page_size=10, domain="教学数据总览",
            definition_status=None, implementation_status=None, keyword="挂科",
            conn=conn, _={},
        )["data"]
        self.assertGreaterEqual(listing["total"], 1)
        self.assertLessEqual(len(listing["items"]), 10)
        self.assertTrue(all(row["domain"] == "教学数据总览"
                            for row in listing["items"]))

        detail = metric_catalog_detail("O-10", conn=conn, _={})["data"]
        self.assertEqual("current_fail_rate",
                         detail["definition"]["technical_kpi_id"])
        self.assertEqual("分析方案管理",
                         detail["governance"]["thresholdManagedBy"])
        self.assertTrue(detail["bindings"])

        pages = metric_catalog_pages(conn=conn, _={})["data"]
        self.assertTrue(any(row["page_path"] == "/admin/dashboard"
                            for row in pages))
        conn.close()

    def test_parameter_validation_rejects_wrong_type_and_enum(self):
        with self.assertRaises(ApiError):
            _validate_parameter(
                {"value_type": "boolean", "options_json": "[]"}, "true"
            )
        with self.assertRaises(ApiError):
            _validate_parameter(
                {"value_type": "enum", "options_json": '["private_model"]'},
                "public_model",
            )
        _validate_parameter(
            {"value_type": "integer", "options_json": "[]"}, 300
        )

    def test_sensitive_audit_only_captures_business_reads_and_ai_runs(self):
        self.assertEqual(
            "data.student.detail.read",
            _sensitive_read_event(
                "GET", "/api/admin/student/20220001"
            )[0],
        )
        self.assertEqual(
            "ai.analysis.run",
            _sensitive_read_event(
                "GET", "/api/admin/ai/briefing/management"
            )[0],
        )
        self.assertEqual(
            "ai.analysis.run",
            _sensitive_read_event(
                "POST", "/api/admin/ai/experts/graduation-readiness/interpret"
            )[0],
        )
        self.assertIsNone(_sensitive_read_event(
            "POST", "/api/admin/ai/experts/graduation-readiness/schemes"
        ))

    def test_action_catalog_has_human_readable_management_metadata(self):
        self.assertIn("system.manage", ACTION_CATALOG)
        self.assertTrue(all(
            group and name and description
            for group, name, description in ACTION_CATALOG.values()
        ))

    def test_frontend_redirects_invalid_permission_context_to_forbidden(self):
        root = __import__("pathlib").Path(__file__).resolve().parents[2]
        router = (root / "frontend/src/router/index.ts").read_text(encoding="utf-8")
        layout = (root / "frontend/src/views/admin/Layout.vue").read_text(
            encoding="utf-8"
        )
        self.assertIn("permissionContext?.authorized === false", router)
        self.assertIn("path: '/admin/forbidden'", router)
        self.assertIn("return '未授权范围'", layout)

    def test_legacy_admin_password_is_hardened_without_overwriting_new_password(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE sys_user (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO sys_user VALUES('admin',?)",
            (hash_password("admin123"),),
        )
        self.assertEqual(1, harden_legacy_demo_admin(conn))
        current = conn.execute(
            "SELECT password_hash FROM sys_user WHERE username='admin'"
        ).fetchone()["password_hash"]
        self.assertTrue(verify_password(DEMO_PASSWORD, current))
        self.assertEqual(0, harden_legacy_demo_admin(conn))
        conn.close()


if __name__ == "__main__":
    unittest.main()
