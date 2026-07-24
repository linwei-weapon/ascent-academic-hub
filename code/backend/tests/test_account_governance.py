import sqlite3
import unittest

from backend.api.envelope import ApiError
from backend.api.routers.admin_rbac import (
    AccountStatusIn,
    AuthIdentityIn,
    UserUpdateIn,
    account_readiness,
    archive_user,
    delete_user,
    get_user_detail,
    list_users,
    set_auth_identity,
    update_user,
)
from backend.api.security_governance import ensure_security_tables


ADMIN = {"username": "admin", "role_id": "dean"}


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE sys_user (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT,
            role_id TEXT,
            status TEXT DEFAULT 'active'
        );
        CREATE TABLE sys_role (
            role_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            data_scope_type TEXT NOT NULL
        );
        CREATE TABLE sys_user_role (
            user_role_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            role_id TEXT NOT NULL,
            is_default INTEGER DEFAULT 0,
            valid_from TEXT,
            valid_to TEXT,
            status TEXT DEFAULT 'active',
            source TEXT
        );
        CREATE TABLE sys_user_scope (
            user_scope_id TEXT PRIMARY KEY,
            user_role_id TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            valid_from TEXT NOT NULL DEFAULT '1970-01-01',
            valid_to TEXT,
            status TEXT DEFAULT 'active',
            source TEXT
        );
        CREATE TABLE sys_user_staff (
            username TEXT NOT NULL,
            staff_id TEXT NOT NULL,
            valid_from TEXT NOT NULL DEFAULT '1970-01-01',
            valid_to TEXT,
            status TEXT DEFAULT 'active',
            source TEXT,
            source_updated_at TEXT,
            PRIMARY KEY(username,staff_id,valid_from)
        );
    """)
    ensure_security_tables(conn)
    conn.executemany(
        "INSERT INTO sys_role VALUES(?,?,?)",
        [
            ("dean", "教务处处长", "all"),
            ("school_leader", "校领导", "all"),
            ("mentor", "学业导师", "staff_relation"),
        ],
    )
    users = [
        ("admin", "x", "系统管理员", "dean", "active"),
        ("mapped", "x", "已映射账号", "dean", "active"),
        ("needs_staff", "x", "缺少人员关系", "mentor", "active"),
        ("disabled", "x", "停用账号", "dean", "disabled"),
    ]
    for index in range(8):
        users.append((f"user{index}", "x", f"用户{index}", "dean", "active"))
    conn.executemany(
        "INSERT INTO sys_user(username,password_hash,name,role_id,status) VALUES(?,?,?,?,?)",
        users,
    )
    for username, _, _, role_id, _ in users:
        conn.execute(
            """INSERT INTO sys_user_role(
                 user_role_id,username,role_id,is_default,status,source
               ) VALUES(?,?,?,1,'active','test')""",
            (f"UR:{username}:{role_id}", username, role_id),
        )
    # legacy role故意与实际默认身份不同，用于验证列表读取统一身份真值。
    conn.execute("UPDATE sys_user SET role_id='school_leader' WHERE username='mapped'")
    conn.commit()
    return conn


class AccountGovernanceTest(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        mapped_id = self.conn.execute(
            "SELECT user_id FROM sys_user WHERE username='mapped'"
        ).fetchone()[0]
        set_auth_identity(
            mapped_id,
            AuthIdentityIn(
                provider="unified_identity",
                subject_id="SUB-MAPPED",
                status="active",
            ),
            ADMIN,
            self.conn,
        )
        set_auth_identity(
            mapped_id,
            AuthIdentityIn(
                provider="wecom",
                subject_id="WX-MAPPED",
                status="active",
            ),
            ADMIN,
            self.conn,
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_list_is_server_paginated_and_multi_provider_does_not_duplicate(self):
        first = list_users(
            page=1, page_size=10, keyword=None, status=None, role_id=None,
            auth_status=None, permission_status=None, account_source=None,
            _=ADMIN, conn=self.conn,
        )["data"]
        second = list_users(
            page=2, page_size=10, keyword=None, status=None, role_id=None,
            auth_status=None, permission_status=None, account_source=None,
            _=ADMIN, conn=self.conn,
        )["data"]
        self.assertEqual(12, first["total"])
        self.assertEqual(10, len(first["items"]))
        self.assertEqual(2, len(second["items"]))
        self.assertEqual(
            1,
            sum(1 for row in [*first["items"], *second["items"]]
                if row["username"] == "mapped"),
        )
        mapped = next(row for row in first["items"] if row["username"] == "mapped")
        self.assertEqual(2, mapped["auth_mapping_count"])
        self.assertEqual("dean", mapped["role_id"])
        self.assertEqual("教务处处长", mapped["role_name"])

    def test_filters_and_summary_use_governance_truth(self):
        mapped = list_users(
            page=1, page_size=20, keyword=None, status=None, role_id=None,
            auth_status="mapped", permission_status=None, account_source=None,
            _=ADMIN, conn=self.conn,
        )["data"]
        issues = list_users(
            page=1, page_size=20, keyword=None, status=None, role_id=None,
            auth_status=None, permission_status="issue", account_source=None,
            _=ADMIN, conn=self.conn,
        )["data"]
        self.assertEqual(1, mapped["total"])
        self.assertEqual("mapped", mapped["items"][0]["username"])
        self.assertEqual(1, issues["total"])
        self.assertEqual("needs_staff", issues["items"][0]["username"])
        self.assertEqual(1, mapped["summary"]["mapped"])
        self.assertEqual(1, mapped["summary"]["permissionIssues"])

    def test_detail_exposes_all_auth_mappings_and_permission_issue(self):
        user_id = self.conn.execute(
            "SELECT user_id FROM sys_user WHERE username='mapped'"
        ).fetchone()[0]
        detail = get_user_detail(user_id, ADMIN, self.conn)["data"]
        self.assertEqual(2, len(detail["authMappings"]))
        self.assertEqual("ready", detail["permissionStatus"])
        needs_id = self.conn.execute(
            "SELECT user_id FROM sys_user WHERE username='needs_staff'"
        ).fetchone()[0]
        needs = get_user_detail(needs_id, ADMIN, self.conn)["data"]
        self.assertEqual("issue", needs["permissionStatus"])
        self.assertIn("未关联教职工号", needs["issues"][0])

    def test_detail_audit_trail_only_contains_account_governance_events(self):
        user_id = self.conn.execute(
            "SELECT user_id FROM sys_user WHERE username='mapped'"
        ).fetchone()[0]
        self.conn.executemany(
            """INSERT INTO sys_security_audit(
                 actor,action,target_type,target_id,result,detail_json,created_at
               ) VALUES(?,?,?,?,?,?,?)""",
            [
                ("mapped", "auth.login", "user", "mapped", "success", "{}",
                 "2026-07-25T09:00:00+08:00"),
                ("admin", "rbac.user.update", "user", str(user_id), "success",
                 '{"reason":"账号核验"}', "2026-07-25T10:00:00+08:00"),
            ],
        )
        detail = get_user_detail(user_id, ADMIN, self.conn)["data"]
        self.assertTrue(detail["lastLoginAt"])
        actions = [item["action"] for item in detail["auditTrail"]]
        self.assertIn("rbac.user.update", actions)
        self.assertNotIn("auth.login", actions)
        self.assertTrue(all(action.startswith("rbac.user.") for action in actions))

    def test_account_edit_rejects_direct_role_change(self):
        user_id = self.conn.execute(
            "SELECT user_id FROM sys_user WHERE username='mapped'"
        ).fetchone()[0]
        with self.assertRaises(ApiError):
            update_user(
                user_id,
                UserUpdateIn(role_id="mentor"),
                ADMIN,
                self.conn,
            )

    def test_archive_preserves_identity_and_deactivates_auth_mapping(self):
        user_id = self.conn.execute(
            "SELECT user_id FROM sys_user WHERE username='mapped'"
        ).fetchone()[0]
        archive_user(
            user_id,
            AccountStatusIn(status="disabled", reason="人员离校归档"),
            ADMIN,
            self.conn,
        )
        user = self.conn.execute(
            "SELECT status,archived_at FROM sys_user WHERE user_id=?", (user_id,)
        ).fetchone()
        self.assertEqual("disabled", user["status"])
        self.assertTrue(user["archived_at"])
        self.assertEqual(
            1,
            self.conn.execute(
                "SELECT COUNT(*) FROM sys_user_role WHERE username='mapped'"
            ).fetchone()[0],
        )
        self.assertEqual(
            0,
            self.conn.execute(
                """SELECT COUNT(*) FROM sys_auth_identity
                   WHERE username='mapped' AND status='active'"""
            ).fetchone()[0],
        )

    def test_legacy_delete_is_safe_archive(self):
        user_id = self.conn.execute(
            "SELECT user_id FROM sys_user WHERE username='user0'"
        ).fetchone()[0]
        delete_user(user_id, ADMIN, self.conn)
        row = self.conn.execute(
            "SELECT status,archived_at FROM sys_user WHERE user_id=?", (user_id,)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual("disabled", row["status"])
        self.assertTrue(row["archived_at"])

    def test_readiness_reports_orphan_mapping(self):
        self.conn.execute(
            """INSERT INTO sys_auth_identity(
                 username,provider,subject_id,status,source
               ) VALUES('missing-user','unified_identity','ORPHAN','active','test')"""
        )
        data = account_readiness(ADMIN, self.conn)["data"]
        self.assertEqual(1, data["orphanMappings"])
        self.assertEqual(1, data["multipleProviderAccounts"])
        self.assertEqual(4, len(data["implementationChecks"]))


if __name__ == "__main__":
    unittest.main()
