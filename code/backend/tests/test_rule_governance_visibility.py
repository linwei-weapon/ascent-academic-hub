"""预警规则治理读取权限：前端隐藏不能替代服务端鉴权。"""
import sqlite3
import unittest

from backend.api.envelope import ApiError
from backend.api.routers.settings import _require_rule_view


def user(role: str, actions=None) -> dict:
    return {
        "role_id": role,
        "permission_context": {
            "actionPermissions": actions or [],
        },
    }


class RuleGovernanceVisibilityTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE sys_rule_governance_permission(
                role_id TEXT NOT NULL,permission TEXT NOT NULL,
                PRIMARY KEY(role_id,permission));
            INSERT INTO sys_rule_governance_permission VALUES
                ('dean','audit'),
                ('quality_office','review'),
                ('school_leader','activate');
        """)

    def tearDown(self):
        self.conn.close()

    def test_governance_roles_can_view(self):
        for role in ("dean", "quality_office", "school_leader"):
            _require_rule_view(self.conn, user(role))

    def test_discovery_manager_can_view(self):
        _require_rule_view(
            self.conn,
            user("dean", ["rule.discovery.manage"]),
        )

    def test_college_and_counselor_are_denied(self):
        for role in ("college_dean", "counselor", "mentor"):
            with self.assertRaises(ApiError) as ctx:
                _require_rule_view(self.conn, user(role))
            self.assertEqual(403, ctx.exception.status_code)


if __name__ == "__main__":
    unittest.main()
