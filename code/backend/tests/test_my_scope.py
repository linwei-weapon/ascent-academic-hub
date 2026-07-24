"""M3：GET /api/admin/students/my-scope 三视角契约测试。

- 导师只见所带学生（staff_relation，学生明细行）；
- 班主任按人员关系学生集合再按行政班分组（班级卡）；
- 辅导员按 sys_user_scope 班级集合逐班聚合，数字与底层 SQL 对账；
- dean 等全校角色返回 scopeKind='other'，不报错；
- 未登录 401。
"""
import sqlite3
import unittest
from unittest import mock

from backend.api import deps
from backend.api.envelope import ApiError
from backend.api.permission_context import build_permission_context
from backend.api.routers.students import my_scope
from backend.api.settings import CURRENT_SEMESTER

CUR = CURRENT_SEMESTER


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(f"""
        CREATE TABLE sys_user(
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
            name TEXT, role_id TEXT, status TEXT DEFAULT 'active');
        CREATE TABLE sys_role(role_id TEXT PRIMARY KEY, name TEXT, data_scope_type TEXT);
        CREATE TABLE sys_user_role(
            user_role_id TEXT PRIMARY KEY, username TEXT, role_id TEXT,
            is_default INTEGER DEFAULT 0, valid_from TEXT, valid_to TEXT,
            status TEXT DEFAULT 'active', source TEXT);
        CREATE TABLE sys_user_scope(
            user_scope_id TEXT PRIMARY KEY, user_role_id TEXT, scope_type TEXT,
            scope_id TEXT, valid_from TEXT, valid_to TEXT,
            status TEXT DEFAULT 'active', source TEXT);
        CREATE TABLE sys_user_staff(
            username TEXT, staff_id TEXT, valid_from TEXT, valid_to TEXT,
            status TEXT DEFAULT 'active', source TEXT, source_updated_at TEXT,
            PRIMARY KEY(username, staff_id, valid_from));
        CREATE TABLE sys_menu(menu_id TEXT PRIMARY KEY, parent_id TEXT,
            title TEXT, path TEXT, icon TEXT, sort_order INTEGER);
        CREATE TABLE sys_role_menu(role_id TEXT, menu_id TEXT);
        CREATE TABLE sys_role_action(role_id TEXT, action_id TEXT);
        CREATE TABLE dim_student(student_id TEXT PRIMARY KEY, name TEXT,
            college_id TEXT, major_id TEXT, class_id TEXT, grade TEXT);
        CREATE TABLE dim_class(class_id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE fact_grade(student_id TEXT, course_id TEXT, semester_id TEXT,
            gpa REAL, is_pass INTEGER, credits REAL, source TEXT);
        CREATE TABLE fact_major_req(major_id TEXT, grade TEXT, total_req REAL);
        CREATE TABLE alert_event(event_id INTEGER PRIMARY KEY, student_id TEXT,
            workflow_status TEXT);

        INSERT INTO sys_role VALUES
            ('dean','教务处','all'),
            ('counselor','辅导员','class'),
            ('class_adviser','班主任','staff_relation'),
            ('mentor','学业导师','staff_relation');
        INSERT INTO sys_user(username,password_hash,name,role_id,status) VALUES
            ('dean','x','教务处长','dean','active'),
            ('counselor_a','x','辅导员甲','counselor','active'),
            ('T001','x','导师一','mentor','active'),
            ('T003','x','班主任一','class_adviser','active');
        INSERT INTO sys_user_role VALUES
            ('UR:dean:dean','dean','dean',1,NULL,NULL,'active','test'),
            ('UR:counselor_a:counselor','counselor_a','counselor',1,NULL,NULL,'active','test'),
            ('UR:T001:mentor','T001','mentor',1,NULL,NULL,'active','test'),
            ('UR:T003:class_adviser','T003','class_adviser',1,NULL,NULL,'active','test');
        INSERT INTO sys_user_scope VALUES
            ('US:1','UR:counselor_a:counselor','class','B01',NULL,NULL,'active','test');
        INSERT INTO sys_user_staff(username,staff_id,valid_from,status,source) VALUES
            ('T001','T001','2020-01-01','active','test'),
            ('T003','T003','2020-01-01','active','test');

        INSERT INTO dim_class VALUES ('B01','一班'),('B02','二班');
        INSERT INTO dim_student VALUES
            ('S01','学生一','C01','M01','B01','2023'),
            ('S02','学生二','C01','M01','B01','2023'),
            ('S03','学生三','C01','M01','B02','2023'),
            ('S04','学生四','C01','M01','B09','2023');
        INSERT INTO fact_major_req VALUES ('M01','2023',100);
        INSERT INTO fact_grade VALUES
            ('S01','K1','{CUR}',3.0,1,10,'real'),
            ('S01','K2','{CUR}',4.0,1,20,'real'),
            ('S02','K1','{CUR}',2.0,0,10,'real'),
            ('S02','K1','2024-2025-1',2.0,1,10,'real'),
            ('S03','K1','{CUR}',3.0,1,10,'real'),
            ('S04','K1','{CUR}',1.0,0,10,'real');
        INSERT INTO alert_event(student_id,workflow_status) VALUES
            ('S01','assigned'),
            ('S02','resolved'),
            ('S04','new');
    """)
    return conn


def make_v2_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE staff_student_scope(
            staff_id TEXT, student_id TEXT, relation_type TEXT,
            valid_from TEXT, valid_to TEXT, source TEXT, status TEXT);
        INSERT INTO staff_student_scope VALUES
            ('T001','S01','学业导师','2020-01-01',NULL,'real','active'),
            ('T001','S02','学业导师','2020-01-01',NULL,'real','active'),
            ('T003','S01','class_adviser','2020-01-01',NULL,'real','active'),
            ('T003','S03','class_adviser','2020-01-01',NULL,'real','active');
    """)
    return conn


class _NoClose:
    """包装连接：deps._staff_student_ids 会 close()，测试内存库不能被关。"""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, item):
        return getattr(self._conn, item)

    def close(self):
        pass


def build_user(conn, username) -> dict:
    user = dict(conn.execute(
        "SELECT user_id,username,role_id,status FROM sys_user WHERE username=?",
        (username,)).fetchone())
    context = build_permission_context(conn, user)
    return {**user, "role_id": context["activeRole"],
            "staff_id": context.get("staffId"), "permission_context": context}


class MyScopeTest(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.v2 = make_v2_conn()
        self._v2_patch = mock.patch.object(
            deps.dbm, "get_v2_conn", return_value=_NoClose(self.v2))
        self._v2_patch.start()

    def tearDown(self):
        self._v2_patch.stop()
        self.conn.close()
        self.v2.close()

    def call(self, username) -> dict:
        result = my_scope(user=build_user(self.conn, username), conn=self.conn)
        self.assertEqual(0, result["code"])
        return result["data"]

    def test_mentor_sees_only_own_students(self):
        data = self.call("T001")
        self.assertEqual("staff_relation", data["scopeKind"])
        self.assertEqual("students", data["view"])
        self.assertEqual([], data["classes"])
        self.assertEqual(["S01", "S02"], [r["sid"] for r in data["students"]])
        self.assertEqual(2, data["summary"]["studentCount"])
        # S02 本学期 1 门真实挂科；S01 无挂科
        rows = {r["sid"]: r for r in data["students"]}
        self.assertEqual(1, rows["S02"]["failCount"])
        self.assertEqual(0, rows["S01"]["failCount"])
        # S01 有 1 件未解除事件；S02 的事件已 resolved
        self.assertEqual(1, rows["S01"]["openAlerts"])
        self.assertEqual(0, rows["S02"]["openAlerts"])
        self.assertEqual(1, data["summary"]["withOpenAlerts"])
        # S04 属其他导师，绝不出现
        self.assertNotIn("S04", {r["sid"] for r in data["students"]})

    def test_class_adviser_groups_students_by_class(self):
        data = self.call("T003")
        self.assertEqual("staff_relation", data["scopeKind"])
        self.assertEqual("classes", data["view"])
        by_class = {c["classId"]: c for c in data["classes"]}
        self.assertEqual({"B01", "B02"}, set(by_class))
        self.assertEqual(["S01"], [r["sid"] for r in by_class["B01"]["students"]])
        self.assertEqual(["S03"], [r["sid"] for r in by_class["B02"]["students"]])
        self.assertEqual("一班", by_class["B01"]["className"])
        self.assertEqual(2, data["summary"]["studentCount"])

    def test_counselor_class_aggregation_matches_sql(self):
        data = self.call("counselor_a")
        self.assertEqual("class", data["scopeKind"])
        self.assertEqual("classes", data["view"])
        self.assertEqual(1, len(data["classes"]))
        card = data["classes"][0]
        self.assertEqual("B01", card["classId"])
        self.assertEqual("一班", card["className"])
        # 对账：班级学生数
        n = self.conn.execute(
            "SELECT COUNT(*) FROM dim_student WHERE class_id='B01'").fetchone()[0]
        self.assertEqual(n, card["studentCount"])
        # 对账：本学期平均GPA=每生学分加权GPA再平均
        # S01=(3*10+4*20)/30=3.6667, S02=2.0 → 2.83
        gpas = self.conn.execute("""
            SELECT AVG(g) FROM (
              SELECT SUM(gpa*credits)/SUM(credits) g FROM fact_grade
              WHERE gpa IS NOT NULL AND credits>0
                AND semester_id=? AND student_id IN
                (SELECT student_id FROM dim_student WHERE class_id='B01')
              GROUP BY student_id)""", (CUR,)).fetchone()[0]
        self.assertEqual(round(gpas, 2), card["avgGpa"])
        # 对账：本学期未通过学生率=本学期有未通过学生/本学期有成绩学生
        failed = self.conn.execute("""
            SELECT COUNT(DISTINCT student_id) FROM fact_grade
            WHERE source='real' AND is_pass=0 AND semester_id=? AND student_id IN
              (SELECT student_id FROM dim_student WHERE class_id='B01')""",
            (CUR,)).fetchone()[0]
        graded = self.conn.execute("""
            SELECT COUNT(DISTINCT student_id) FROM fact_grade
            WHERE source='real' AND is_pass IS NOT NULL AND semester_id=?
              AND student_id IN
                (SELECT student_id FROM dim_student WHERE class_id='B01')""",
            (CUR,)).fetchone()[0]
        self.assertEqual(round(failed / graded * 100, 1), card["failRate"])
        self.assertEqual(graded, card["gradedStudentCount"])
        self.assertEqual(failed, card["failedStudentCount"])
        # 对账：学分完成率中位数 → S01 30%, S02 10%（仅通过记录计入学分）→ 20%
        self.assertEqual(20.0, card["creditMedian"])
        # 对账：未解除预警事件 → 仅 S01 的 assigned 事件
        open_events = self.conn.execute("""
            SELECT COUNT(*) FROM alert_event
            WHERE workflow_status NOT IN ('resolved','closed')
              AND student_id IN
                (SELECT student_id FROM dim_student WHERE class_id='B01')""").fetchone()[0]
        self.assertEqual(open_events, card["openAlerts"])
        self.assertEqual(1, card["withOpenAlerts"])
        # 汇总卡与班级卡一致（单班情形）
        self.assertEqual(card["studentCount"], data["summary"]["studentCount"])
        self.assertEqual(card["avgGpa"], data["summary"]["avgGpa"])
        # B09 的 S04 不在辅导员班级范围内
        all_sids = {r["sid"] for c in data["classes"] for r in c["students"]}
        self.assertNotIn("S04", all_sids)

    def test_dean_gets_other_without_error(self):
        data = self.call("dean")
        self.assertEqual("other", data["scopeKind"])
        self.assertEqual("none", data["view"])
        self.assertIsNone(data["summary"])
        self.assertEqual([], data["classes"])
        self.assertEqual([], data["students"])

    def test_unauthenticated_gets_401(self):
        with self.assertRaises(ApiError) as ctx:
            deps.get_current_user(authorization="", conn=self.conn)
        self.assertEqual(401, ctx.exception.status_code)


if __name__ == "__main__":
    unittest.main()
