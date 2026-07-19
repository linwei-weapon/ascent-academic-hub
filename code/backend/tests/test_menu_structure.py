import sqlite3
import unittest

from backend.api.envelope import ApiError
from backend.api.routers.admin_rbac import _assert_valid_parent, _leaf_menu_ids
from backend.api.routers.auth import _menus_for_role
from scripts.migrate_menu import LEAF_IDS, PARENT_IDS, TARGET_MENUS, migrate


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


class MenuStructureTest(unittest.TestCase):
    def test_migration_is_idempotent_and_transfers_legacy_grants(self):
        conn = make_conn()
        conn.executemany(
            "INSERT INTO sys_menu VALUES(?,?,?,?,?,?)",
            [
                ("/admin/dashboard", None, "数据大屏", "/admin/dashboard", "", 1),
                ("/admin/operation", None, "教学运行", "/admin/operation", "", 2),
                ("/admin/operation/classroom", "/admin/operation", "教室", "/admin/operation/classroom", "", 3),
                ("/admin/reports", None, "管理决策专题", "/admin/reports", "", 4),
                ("/admin/students/list", None, "学生清单", "/admin/students/list", "", 5),
                ("/admin/settings", None, "系统设置", "/admin/settings", "", 6),
            ],
        )
        conn.executemany(
            "INSERT INTO sys_role_menu VALUES(?,?)",
            [
                ("college_dean", "/admin/dashboard"),
                ("college_dean", "/admin/operation/classroom"),
                ("college_dean", "/admin/reports"),
                ("counselor", "/admin/students/list"),
                ("school_leader", "/admin/reports"),
                ("school_leader", "/admin/settings"),
            ],
        )

        migrate(conn)
        first_menu = conn.execute("""
            SELECT menu_id,parent_id,title,path,icon,sort_order
            FROM sys_menu ORDER BY sort_order,menu_id
        """).fetchall()
        first_grant = conn.execute("""
            SELECT role_id,menu_id FROM sys_role_menu ORDER BY role_id,menu_id
        """).fetchall()
        migrate(conn)
        second_menu = conn.execute("""
            SELECT menu_id,parent_id,title,path,icon,sort_order
            FROM sys_menu ORDER BY sort_order,menu_id
        """).fetchall()
        second_grant = conn.execute("""
            SELECT role_id,menu_id FROM sys_role_menu ORDER BY role_id,menu_id
        """).fetchall()

        self.assertEqual(first_menu, second_menu)
        self.assertEqual(first_grant, second_grant)
        self.assertEqual({row[0] for row in TARGET_MENUS},
                         {row["menu_id"] for row in first_menu})
        self.assertFalse(any(row["menu_id"] in PARENT_IDS for row in first_grant))
        self.assertEqual(
            LEAF_IDS,
            {row["menu_id"] for row in first_grant if row["role_id"] == "dean"},
        )
        self.assertNotIn(
            ("school_leader", "/admin/settings"),
            {(row["role_id"], row["menu_id"]) for row in first_grant},
        )
        self.assertIn(
            ("college_dean", "/admin/operation/courses"),
            {(row["role_id"], row["menu_id"]) for row in first_grant},
        )
        self.assertIn(
            ("counselor", "/admin/students/analysis"),
            {(row["role_id"], row["menu_id"]) for row in first_grant},
        )
        self.assertIn(
            ("counselor", "/admin/dashboard"),
            {(row["role_id"], row["menu_id"]) for row in first_grant},
        )
        conn.close()

    def test_login_contract_adds_only_needed_parent(self):
        conn = make_conn()
        migrate(conn)
        conn.execute(
            "INSERT OR IGNORE INTO sys_role_menu VALUES(?,?)",
            ("limited", "/admin/curriculum"),
        )
        menus = _menus_for_role(conn, "limited")
        self.assertEqual(
            ["/admin/analysis", "/admin/curriculum"],
            [menu["menu_id"] for menu in menus],
        )
        self.assertIsNone(menus[0]["parent_id"])
        self.assertEqual("/admin/analysis", menus[1]["parent_id"])
        conn.close()

    def test_role_assignment_stores_leaf_permissions_only(self):
        conn = make_conn()
        migrate(conn)
        selected = _leaf_menu_ids(
            conn,
            ["/admin/analysis", "/admin/dashboard", "/admin/decision"],
        )
        self.assertEqual(["/admin/dashboard"], selected)
        with self.assertRaises(ApiError):
            _leaf_menu_ids(conn, ["/admin/not-found"])
        conn.close()

    def test_menu_parent_validation_rejects_third_level(self):
        conn = make_conn()
        migrate(conn)
        with self.assertRaises(ApiError):
            _assert_valid_parent(
                conn, "/admin/new-leaf", "/admin/dashboard",
            )
        with self.assertRaises(ApiError):
            _assert_valid_parent(
                conn, "/admin/analysis", "/admin/system",
            )
        conn.close()


if __name__ == "__main__":
    unittest.main()
