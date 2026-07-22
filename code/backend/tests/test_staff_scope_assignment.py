"""M2：班主任/导师账号迁移 + 预警按学生关系分派的契约测试。"""
import sqlite3
import unittest
from unittest import mock

from backend.api import deps
from backend.api.deps import student_data_scope
from backend.api.permission_context import build_permission_context, v2_student_scope
from backend.api.routers.alert_assignment import assignees_for_student
from scripts.migrate_alert_assignee_backfill import LEGACY_MARK, backfill
from scripts.migrate_staff_accounts import migrate as migrate_staff_accounts


def make_analytics_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE sys_user(
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT, role_id TEXT, status TEXT DEFAULT 'active'
        );
        CREATE TABLE sys_role(role_id TEXT PRIMARY KEY, name TEXT, data_scope_type TEXT);
        CREATE TABLE sys_user_role(
            user_role_id TEXT PRIMARY KEY, username TEXT, role_id TEXT,
            is_default INTEGER DEFAULT 0, valid_from TEXT, valid_to TEXT,
            status TEXT DEFAULT 'active', source TEXT
        );
        CREATE TABLE sys_user_scope(
            user_scope_id TEXT PRIMARY KEY, user_role_id TEXT, scope_type TEXT,
            scope_id TEXT, valid_from TEXT, valid_to TEXT,
            status TEXT DEFAULT 'active', source TEXT
        );
        CREATE TABLE sys_user_staff(
            username TEXT, staff_id TEXT, valid_from TEXT, valid_to TEXT,
            status TEXT DEFAULT 'active', source TEXT, source_updated_at TEXT,
            PRIMARY KEY(username, staff_id, valid_from)
        );
        CREATE TABLE sys_menu(menu_id TEXT PRIMARY KEY, parent_id TEXT,
            title TEXT, path TEXT, icon TEXT, sort_order INTEGER);
        CREATE TABLE sys_role_menu(role_id TEXT, menu_id TEXT);
        CREATE TABLE sys_role_action(role_id TEXT, action_id TEXT);
        CREATE TABLE sys_role_scope(role_id TEXT, scope_id TEXT);
        CREATE TABLE dim_student(student_id TEXT PRIMARY KEY, name TEXT,
            college_id TEXT, class_id TEXT);
        CREATE TABLE alert_event(event_id INTEGER PRIMARY KEY, student_id TEXT);
        CREATE TABLE alert_assignee(
            event_id INTEGER, username TEXT, role_id TEXT,
            assignment_reason TEXT, assigned_at TEXT, is_primary INTEGER DEFAULT 1,
            PRIMARY KEY(event_id, username)
        );
        INSERT INTO sys_role VALUES
            ('dean','教务处','all'),
            ('counselor','辅导员','class'),
            ('college_secretary','教学秘书','college'),
            ('class_adviser','班主任','staff_relation'),
            ('mentor','学业导师','staff_relation');
        INSERT INTO sys_user(username,password_hash,name,role_id,status) VALUES
            ('dean','x','教务处长','dean','active'),
            ('counselor_a','x','辅导员甲','counselor','active'),
            ('counselor_b','x','辅导员乙','counselor','active'),
            ('secretary_c1','x','甲院秘书','college_secretary','active');
        INSERT INTO sys_user_role VALUES
            ('UR:dean:dean','dean','dean',1,NULL,NULL,'active','test'),
            ('UR:counselor_a:counselor','counselor_a','counselor',1,NULL,NULL,'active','test'),
            ('UR:counselor_b:counselor','counselor_b','counselor',1,NULL,NULL,'active','test'),
            ('UR:secretary_c1:college_secretary','secretary_c1','college_secretary',
             1,NULL,NULL,'active','test');
        INSERT INTO sys_user_scope VALUES
            ('US:1','UR:counselor_a:counselor','class','B01',NULL,NULL,'active','test'),
            ('US:2','UR:counselor_b:counselor','class','B02',NULL,NULL,'active','test'),
            ('US:3','UR:secretary_c1:college_secretary','college','C01',NULL,NULL,'active','test');
        INSERT INTO dim_student VALUES
            ('S01','甲','C01','B01'),
            ('S02','乙','C01','B09'),
            ('S03','丙','C02','B09'),
            ('S04','丁','C01','B01');
    """)
    return conn


def make_v2_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE dim_staff(staff_id TEXT PRIMARY KEY, display_name TEXT,
            organization_id TEXT, staff_type TEXT, title TEXT,
            status TEXT, source TEXT);
        CREATE TABLE staff_student_scope(
            staff_id TEXT, student_id TEXT, relation_type TEXT,
            valid_from TEXT, valid_to TEXT, source TEXT, status TEXT);
        INSERT INTO dim_staff VALUES
            ('T001','张老师','C01','mentor','教授','active','real'),
            ('T002','李老师','C01','mentor','副教授','active','real'),
            ('T003','王老师','C01','class_adviser','讲师','active','real'),
            ('T004','赵老师','C01','class_adviser','讲师','active','real'),
            ('T005','无关系导师','C01','mentor','讲师','active','real');
        INSERT INTO staff_student_scope VALUES
            ('T001','S01','学业导师','2020-01-01',NULL,'real','active'),
            ('T002','S04','学业导师','2020-01-01',NULL,'real','active'),
            ('T003','S01','class_adviser','2020-01-01',NULL,'real','active'),
            ('T003','S04','class_adviser','2020-01-01',NULL,'real','active'),
            ('T004','S04','class_adviser','2020-01-01',NULL,'real','active');
    """)
    return conn


class StaffAccountMigrationTest(unittest.TestCase):
    def test_migration_creates_accounts_and_is_idempotent(self):
        conn, v2 = make_analytics_conn(), make_v2_conn()
        first = migrate_staff_accounts(conn, v2)
        self.assertEqual(2, first["mentorAccounts"])
        self.assertEqual(2, first["classAdviserAccounts"])
        self.assertEqual(4, first["accountsCreated"])
        self.assertEqual(4, first["identitiesCreated"])
        self.assertEqual(4, first["staffMappingsCreated"])
        # 无 active 关系的 T005 不生成账号
        self.assertIsNone(conn.execute(
            "SELECT 1 FROM sys_user WHERE username='T005'").fetchone())
        row = conn.execute(
            "SELECT username,name,role_id,status FROM sys_user WHERE username='T001'"
        ).fetchone()
        self.assertEqual(("T001", "张老师", "mentor", "active"), tuple(row))
        identity = conn.execute("""SELECT role_id,is_default,status,source
            FROM sys_user_role WHERE user_role_id='UR:T001:mentor'""").fetchone()
        self.assertEqual(("mentor", 1, "active", "staff_migration"), tuple(identity))
        # 篡改已有密码后重跑：不覆盖、统计全为跳过
        conn.execute("UPDATE sys_user SET password_hash='changed' WHERE username='T001'")
        second = migrate_staff_accounts(conn, v2)
        self.assertEqual(0, second["accountsCreated"])
        self.assertEqual(0, second["identitiesCreated"])
        self.assertEqual(0, second["staffMappingsCreated"])
        self.assertEqual(4, second["accountsSkipped"])
        self.assertEqual("changed", conn.execute(
            "SELECT password_hash FROM sys_user WHERE username='T001'"
        ).fetchone()[0])
        conn.close(); v2.close()

    def test_generated_identity_grants_staff_relation_scope(self):
        conn, v2 = make_analytics_conn(), make_v2_conn()
        migrate_staff_accounts(conn, v2)
        user = dict(conn.execute(
            "SELECT user_id,username,role_id,status FROM sys_user WHERE username='T001'"
        ).fetchone())
        # v2_student_scope 在传入连接内查 staff_student_scope，直接借用 V2 连接
        context = build_permission_context(conn, user)
        self.assertTrue(context["authorized"])
        self.assertEqual("staff_relation", context["detailScope"]["type"])
        fragment, params = v2_student_scope(context, v2, "s")
        rows = v2.execute(
            f"SELECT DISTINCT student_id FROM staff_student_scope s WHERE {fragment}",
            params).fetchall()
        self.assertEqual(["S01"], [r[0] for r in rows])
        conn.close(); v2.close()


class StaffScopeIsolationTest(unittest.TestCase):
    def test_mentors_only_see_their_own_students(self):
        conn, v2 = make_analytics_conn(), make_v2_conn()
        migrate_staff_accounts(conn, v2)
        expected = {"T001": ["S01"], "T002": ["S04"],
                    "T003": ["S01", "S04"], "T004": ["S04"]}
        for username, student_ids in expected.items():
            user = dict(conn.execute(
                "SELECT user_id,username,role_id,status FROM sys_user WHERE username=?",
                (username,)).fetchone())
            context = build_permission_context(conn, user)
            full_user = {**user, "staff_id": username,
                         "permission_context": context}
            with mock.patch.object(deps.dbm, "get_v2_conn",
                                   return_value=_NoClose(v2)):
                fragment, params = student_data_scope(full_user, conn, "s")
            self.assertTrue(fragment.startswith("s.student_id IN ("))
            self.assertEqual(student_ids, params)
        conn.close()
        v2.close()


class _NoClose:
    """包装连接：deps._staff_student_ids 会 close()，测试内存库不能被关。"""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, item):
        return getattr(self._conn, item)

    def close(self):
        pass


class AssignmentFunctionTest(unittest.TestCase):
    def setUp(self):
        self.conn = make_analytics_conn()
        self.v2 = make_v2_conn()
        migrate_staff_accounts(self.conn, self.v2)

    def tearDown(self):
        self.conn.close(); self.v2.close()

    def test_student_with_relations_gets_three_kinds_of_assignees(self):
        # S01：行政班 B01 → 辅导员 counselor_a 主责；班主任 T003、导师 T001 协同
        assignees = assignees_for_student(self.conn, "S01", self.v2)
        by_resp = {"primary": [], "collaborator": []}
        for a in assignees:
            by_resp[a["responsibility"]].append((a["username"], a["role_id"]))
        self.assertEqual([("counselor_a", "counselor")], by_resp["primary"])
        self.assertEqual([("T001", "mentor"), ("T003", "class_adviser")],
                         sorted(by_resp["collaborator"]))

    def test_student_without_relations_falls_back_to_college_secretary(self):
        # S02：B09 无辅导员配置；学院 C01 有教学秘书 → 秘书主责
        assignees = assignees_for_student(self.conn, "S02", self.v2)
        self.assertEqual(1, len(assignees))
        self.assertEqual(("secretary_c1", "college_secretary", "primary"),
                         (assignees[0]["username"], assignees[0]["role_id"],
                          assignees[0]["responsibility"]))

    def test_student_without_any_match_falls_back_to_first_counselor(self):
        # S03：C02 无秘书、B09 无辅导员 → 保底第一个辅导员
        assignees = assignees_for_student(self.conn, "S03", self.v2)
        self.assertEqual(1, len(assignees))
        self.assertEqual("counselor_a", assignees[0]["username"])
        self.assertEqual("primary", assignees[0]["responsibility"])
        self.assertIn("保底", assignees[0]["reason"])

    def test_adviser_and_counselor_class_scope_consistency(self):
        # 班主任 T003 的学生都在其班级辅导员 counselor_a 的班级范围内（S01/S04 ∈ B01）
        adviser = dict(self.conn.execute(
            "SELECT user_id,username,role_id,status FROM sys_user WHERE username='T003'"
        ).fetchone())
        context = build_permission_context(self.conn, adviser)
        full_user = {**adviser, "staff_id": "T003", "permission_context": context}
        with mock.patch.object(deps.dbm, "get_v2_conn",
                               return_value=_NoClose(self.v2)):
            fragment, params = student_data_scope(full_user, self.conn, "s")
        adviser_students = set(params)
        counselor_classes = {row[0] for row in self.conn.execute(
            "SELECT scope_id FROM sys_user_scope us "
            "JOIN sys_user_role ur ON ur.user_role_id=us.user_role_id "
            "WHERE ur.username='counselor_a' AND us.scope_type='class'")}
        class_students = {row[0] for row in self.conn.execute(
            f"SELECT student_id FROM dim_student WHERE class_id IN "
            f"({','.join('?' * len(counselor_classes))})",
            tuple(counselor_classes))}
        self.assertEqual({"S01", "S04"}, adviser_students)
        self.assertTrue(adviser_students <= class_students)


class AssigneeBackfillTest(unittest.TestCase):
    def setUp(self):
        self.conn = make_analytics_conn()
        self.v2 = make_v2_conn()
        migrate_staff_accounts(self.conn, self.v2)
        self.conn.executescript("""
            INSERT INTO alert_event(event_id,student_id) VALUES
                (1,'S01'),(2,'S02'),(3,'S03');
            INSERT INTO alert_assignee
                (event_id,username,role_id,assignment_reason,assigned_at,is_primary)
            VALUES
                (1,'counselor_a','counselor','按辅导员角色初始化分派','2026-01-01',1),
                (2,'counselor_a','counselor','按辅导员角色初始化分派','2026-01-01',1),
                (3,'counselor_a','counselor','按辅导员角色初始化分派','2026-01-01',1);
        """)

    def tearDown(self):
        self.conn.close(); self.v2.close()

    def _rows(self, event_id):
        return {r["username"]: dict(r) for r in self.conn.execute(
            "SELECT * FROM alert_assignee WHERE event_id=?", (event_id,))}

    def test_backfill_rehangs_relations_and_is_idempotent(self):
        first = backfill(self.conn, self.v2)
        # 事件1：counselor_a 仍是主责（班级匹配），新增班主任+导师协同
        rows = self._rows(1)
        self.assertEqual(1, rows["counselor_a"]["is_primary"])
        self.assertNotIn(LEGACY_MARK, rows["counselor_a"]["assignment_reason"])
        self.assertEqual(0, rows["T001"]["is_primary"])
        self.assertEqual(0, rows["T003"]["is_primary"])
        # 事件2：主责换成学院秘书，原硬编码辅导员降级并标记备查
        rows = self._rows(2)
        self.assertEqual(1, rows["secretary_c1"]["is_primary"])
        self.assertEqual(0, rows["counselor_a"]["is_primary"])
        self.assertIn(LEGACY_MARK, rows["counselor_a"]["assignment_reason"])
        # 事件3：保底仍是第一个辅导员 → 原记录保持不变
        rows = self._rows(3)
        self.assertEqual(["counselor_a"], list(rows))
        self.assertEqual(1, rows["counselor_a"]["is_primary"])
        self.assertNotIn(LEGACY_MARK, rows["counselor_a"]["assignment_reason"])
        # 幂等：第二次运行不再新增/改动
        counts = [self.conn.execute(t).fetchone()[0] for t in (
            "SELECT COUNT(*) FROM alert_assignee",
            "SELECT COUNT(*) FROM alert_assignee WHERE is_primary=1",
        )]
        second = backfill(self.conn, self.v2)
        self.assertEqual(0, second["primariesAdded"])
        self.assertEqual(0, second["collaboratorsAdded"])
        self.assertEqual(0, second["legacyMarked"])
        self.assertEqual(0, second["primaryReassigned"])
        self.assertEqual(counts, [self.conn.execute(t).fetchone()[0] for t in (
            "SELECT COUNT(*) FROM alert_assignee",
            "SELECT COUNT(*) FROM alert_assignee WHERE is_primary=1",
        )])
        self.assertGreater(first["collaboratorsAdded"], 0)
        self.assertGreater(first["primaryReassigned"], 0)


if __name__ == "__main__":
    unittest.main()
