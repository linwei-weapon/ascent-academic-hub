import sqlite3
import unittest

from backend.api.envelope import ApiError
from backend.api.main import _sensitive_read_event
from backend.api.routers.system_management import (
    PARAMETER_DEFAULTS,
    _validate_parameter,
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
    def test_migration_completes_eight_modules_and_is_idempotent(self):
        conn = make_conn()
        first = migrate(conn)
        second = migrate(conn)
        self.assertEqual(first, second)
        self.assertEqual(8, second["systemMenus"])
        self.assertEqual(len(PARAMETER_DEFAULTS), second["systemParameters"])
        # 8 条总览指标 + M1 新增 4 条课程质量三分层指标。
        self.assertEqual(12, second["registeredKpis"])
        system_titles = {
            row["title"] for row in conn.execute(
                "SELECT title FROM sys_menu WHERE parent_id='/admin/system'"
            )
        }
        self.assertEqual({
            "账号管理", "角色与功能权限", "菜单管理", "数据权限",
            "指标与口径管理", "分析方案管理", "审计日志", "系统参数",
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
