"""M5：GET /api/admin/alerts/trajectory 同类轨迹分布契约测试。

- 分桶统计正确性：构造已知轨迹小样本（T=2024-2025-2 → T+1=2025-2026-1），
  resolved/escalate/gpa_delta/new_fail/grad_outcome 数字与手工 SQL 对账；
- low_confidence 阈值（样本量 < 10）；
- 受限角色（辅导员班级范围）样本过滤，且不超过全校；
- 未登录 401；待观察（无 T 后成绩学期）不计入后续轨迹统计。
"""
import sqlite3
import unittest
from unittest import mock

from backend.api import deps
from backend.api.envelope import ApiError
from backend.api.permission_context import build_permission_context
from backend.api.routers.alert_trajectory import (
    DISCLAIMER, LOW_CONFIDENCE_SAMPLE, alerts_trajectory, compute_trajectory)

T = "2024-2025-2"
T1 = "2025-2026-1"


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
        CREATE TABLE sys_alert_rule(rule_id TEXT PRIMARY KEY, name TEXT,
            level TEXT, enabled INTEGER);
        CREATE TABLE fact_alert(alert_id INTEGER PRIMARY KEY, student_id TEXT,
            rule_id TEXT, type TEXT, level TEXT, trigger_detail TEXT,
            status TEXT, created_at TEXT, semester_id TEXT, source TEXT,
            is_active INTEGER);
        CREATE TABLE alert_event(event_id INTEGER PRIMARY KEY, alert_id INTEGER,
            student_id TEXT, rule_id TEXT, workflow_status TEXT);
        CREATE TABLE fact_grade(student_id TEXT, course_id TEXT,
            semester_id TEXT, gpa REAL, is_pass INTEGER, credits REAL,
            source TEXT);
        CREATE TABLE fact_graduation(student_id TEXT, grad_status TEXT,
            source TEXT);

        INSERT INTO sys_role VALUES
            ('dean','教务处','all'),
            ('counselor','辅导员','class');
        INSERT INTO sys_user(username,password_hash,name,role_id,status) VALUES
            ('dean','x','教务处长','dean','active'),
            ('counselor_a','x','辅导员甲','counselor','active');
        INSERT INTO sys_user_role VALUES
            ('UR:dean:dean','dean','dean',1,NULL,NULL,'active','test'),
            ('UR:counselor_a:counselor','counselor_a','counselor',1,NULL,NULL,'active','test');
        INSERT INTO sys_user_scope VALUES
            ('US:1','UR:counselor_a:counselor','class','B01',NULL,NULL,'active','test');

        INSERT INTO dim_class VALUES ('B01','一班'),('B02','二班');
        INSERT INTO sys_alert_rule VALUES
            ('R1','GPA持续下降','严重',1),
            ('R2','未解决挂科累积','严重',1),
            ('R4','核心必修风险','提醒',1),
            ('R6','退学风险','严重',1);
    """)
    students = [(f"S{i:02d}", "B01" if i <= 8 else "B02") for i in range(1, 11)]
    students += [("S11", "B01"), ("S12", "B02")]
    for sid, cls in students:
        conn.execute("INSERT INTO dim_student VALUES(?,?,?,?,?,?)",
                     (sid, f"学生{sid}", "C01", "M01", cls, "2023"))

    # R2×严重 桶：S01..S10 各一条 T 学期预警（S03 记录已关闭，仍计入观察点）
    for i in range(1, 11):
        sid = f"S{i:02d}"
        status = "已解决" if i <= 3 else "待处理"
        active = 0 if i == 3 else 1
        conn.execute(
            "INSERT INTO fact_alert VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (i, sid, "R2", "挂科累积", "严重", "链", status,
             "2025-05-01", T, "real", active))
        wf = "resolved" if i <= 3 else "new"
        conn.execute("INSERT INTO alert_event VALUES(?,?,?,?,?)",
                     (i, i, sid, "R2", wf))
    # 后续学期新预警：S02 在 T1 出现 R1×严重（构成升级），S03 出现 R4×提醒（不构成升级）
    conn.execute("INSERT INTO fact_alert VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                 (201, "S02", "R1", "GPA下降", "严重", "链", "待处理",
                  "2026-01-10", T1, "real", 1))
    conn.execute("INSERT INTO fact_alert VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                 (202, "S03", "R4", "必修风险", "提醒", "链", "待处理",
                  "2026-01-10", T1, "real", 1))
    # R6×严重 桶：S11 预警发生在 T1（无后续学期→待观察），S12 在 T（可观察）
    conn.execute("INSERT INTO fact_alert VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                 (301, "S11", "R6", "退学风险", "严重", "链", "待处理",
                  "2026-01-10", T1, "real", 1))
    conn.execute("INSERT INTO fact_alert VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                 (302, "S12", "R6", "退学风险", "严重", "链", "待处理",
                  "2025-05-01", T, "real", 1))
    conn.execute("INSERT INTO alert_event VALUES(?,?,?,?,?)", (301, 301, "S11", "R6", "new"))
    conn.execute("INSERT INTO alert_event VALUES(?,?,?,?,?)", (302, 302, "S12", "R6", "new"))

    # 成绩：每生 T 学期 1 条通过记录（gpa 已知）；T1 按计划构造
    t1_gpa = {"S01": 3.2, "S02": 2.7, "S03": 3.02, "S04": 3.0, "S05": 3.01,
              "S06": 2.99, "S07": 3.0, "S08": 3.0, "S09": 3.0, "S10": None}
    for i in range(1, 13):
        sid = f"S{i:02d}"
        conn.execute("INSERT INTO fact_grade VALUES(?,?,?,?,?,?,?)",
                     (sid, "KT", T, 3.0 if sid != "S12" else 2.0, 1, 3.0, "real"))
        if sid == "S11":
            continue  # S11 预警在 T1，但 T1 之后无学期 → 待观察
        conn.execute("INSERT INTO fact_grade VALUES(?,?,?,?,?,?,?)",
                     (sid, "KT1", T1, t1_gpa.get(sid, 2.5), 1, 3.0, "real"))
    # T1 未通过记录（gpa 为 NULL，不影响 GPA 均值）
    conn.execute("INSERT INTO fact_grade VALUES(?,?,?,?,?,?,?)",
                 ("S02", "K1", T1, None, 0, 3.0, "real"))   # S02 新增 1 门
    conn.execute("INSERT INTO fact_grade VALUES(?,?,?,?,?,?,?)",
                 ("S03", "K1", T1, None, 0, 3.0, "real"))   # S03 新增 2 门
    conn.execute("INSERT INTO fact_grade VALUES(?,?,?,?,?,?,?)",
                 ("S03", "K2", T1, None, 0, 3.0, "real"))
    # S11 也需要 T1 成绩（预警学期本身有成绩，之后没有）
    conn.execute("INSERT INTO fact_grade VALUES(?,?,?,?,?,?,?)",
                 ("S11", "KT1", T1, 2.0, 1, 3.0, "real"))

    # 毕业结果：legacy 合成数据 3 人（S01/S02/S03），V2 真实数据 1 人（S04）
    conn.execute("INSERT INTO fact_graduation VALUES(?,?,?)", ("S01", "按期毕业", "sim"))
    conn.execute("INSERT INTO fact_graduation VALUES(?,?,?)", ("S02", "延期毕业", "sim"))
    conn.execute("INSERT INTO fact_graduation VALUES(?,?,?)", ("S03", "按期毕业", "sim"))
    return conn


def make_v2_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE graduation_outcome(student_id TEXT, graduation_status TEXT,
            source TEXT);
        INSERT INTO graduation_outcome VALUES ('S04','毕业','real');
    """)
    return conn


class _NoClose:
    """包装连接：被测代码会 close()，测试内存库不能被关。"""

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


class TrajectoryComputeTest(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.v2 = make_v2_conn()

    def tearDown(self):
        self.conn.close()
        self.v2.close()

    def bucket(self, rule_id="R2", level="严重"):
        data = compute_trajectory(self.conn, self.v2, rule_id=rule_id, level=level)
        self.assertEqual(1, len(data["buckets"]))
        return data["buckets"][0]

    def test_sample_size_matches_sql(self):
        b = self.bucket()
        n = self.conn.execute(
            "SELECT COUNT(*) FROM fact_alert WHERE rule_id='R2' AND level='严重'"
        ).fetchone()[0]
        self.assertEqual(n, b["sampleSize"])
        self.assertEqual(10, b["sampleSize"])
        self.assertFalse(b["lowConfidence"])
        self.assertEqual("未解决挂科累积", b["ruleName"])

    def test_resolved_ratio_matches_sql(self):
        b = self.bucket()
        n = self.conn.execute("""
            SELECT COUNT(*) FROM fact_alert a JOIN alert_event e ON e.alert_id=a.alert_id
            WHERE a.rule_id='R2' AND a.level='严重'
              AND e.workflow_status IN ('resolved','closed')""").fetchone()[0]
        self.assertEqual(n, b["resolved"]["count"])
        self.assertEqual(3, b["resolved"]["count"])
        self.assertEqual(0.3, b["resolved"]["ratio"])

    def test_gpa_delta_distribution_matches_hand_sql(self):
        b = self.bucket()
        g = b["post"]["gpaDelta"]
        # 手工对账：S01 +0.2 上升；S02 -0.3 下降；S03..S09 持平；S10 T1 gpa 缺失 → unknown
        s01 = self.conn.execute(f"""
            SELECT (SELECT AVG(gpa) FROM fact_grade
                     WHERE student_id='S01' AND semester_id='{T1}' AND gpa IS NOT NULL)
                 - (SELECT AVG(gpa) FROM fact_grade
                     WHERE student_id='S01' AND semester_id='{T}' AND gpa IS NOT NULL)
        """).fetchone()[0]
        self.assertAlmostEqual(0.2, s01, places=6)
        self.assertEqual(1, g["up"])
        self.assertEqual(7, g["flat"])
        self.assertEqual(1, g["down"])
        self.assertEqual(1, g["unknown"])
        self.assertEqual(9, g["valid"])
        # 均值 = (+0.2 -0.3 +0.02 +0 +0.01 -0.01 +0 +0 +0)/9 = -0.0088… → -0.01
        deltas = []
        for i in range(1, 10):
            sid = f"S{i:02d}"
            d = self.conn.execute(f"""
                SELECT (SELECT AVG(gpa) FROM fact_grade
                         WHERE student_id=? AND semester_id=? AND gpa IS NOT NULL)
                     - (SELECT AVG(gpa) FROM fact_grade
                         WHERE student_id=? AND semester_id=? AND gpa IS NOT NULL)
            """, (sid, T1, sid, T)).fetchone()[0]
            deltas.append(d)
        self.assertEqual(round(sum(deltas) / len(deltas), 2), g["mean"])
        self.assertEqual(-0.01, g["mean"])

    def test_new_fail_and_escalate(self):
        b = self.bucket()
        nf = b["post"]["newFail"]
        self.assertEqual(8, nf["zero"])     # S01,S04..S10
        self.assertEqual(1, nf["one"])      # S02 新增 K1
        self.assertEqual(1, nf["twoPlus"])  # S03 新增 K1,K2
        self.assertEqual(0.8, nf["zeroRatio"])
        # 升级：仅 S02 在 T1 出现同级（严重）新预警；S03 的 T1 预警为提醒，不算升级
        esc = self.conn.execute(f"""
            SELECT COUNT(DISTINCT a.student_id) FROM fact_alert a
            JOIN fact_alert o ON o.student_id=a.student_id
            WHERE a.rule_id='R2' AND a.level='严重' AND a.semester_id='{T}'
              AND o.semester_id > a.semester_id
              AND o.level IN ('严重')""").fetchone()[0]
        self.assertEqual(esc, b["post"]["escalate"]["count"])
        self.assertEqual(1, b["post"]["escalate"]["count"])
        self.assertEqual(0.1, b["post"]["escalate"]["ratio"])

    def test_grad_outcome_subset_and_sources(self):
        b = self.bucket()
        go = b["gradOutcome"]
        self.assertEqual(4, go["sample"])  # 仅 S01..S04 有毕业结果数据
        self.assertEqual({"real": 1, "sim": 3}, go["sourceCounts"])
        dist = {d["status"]: d["count"] for d in go["dist"]}
        self.assertEqual({"按期毕业": 2, "延期毕业": 1, "毕业": 1}, dist)

    def test_low_confidence_and_pending(self):
        data = compute_trajectory(self.conn, self.v2, rule_id="R6", level="严重")
        b = data["buckets"][0]
        self.assertEqual(2, b["sampleSize"])
        self.assertTrue(b["sampleSize"] < LOW_CONFIDENCE_SAMPLE)
        self.assertTrue(b["lowConfidence"])
        # S11 预警发生在 T1（无后续学期）→ 待观察；S12 可观察
        self.assertEqual(1, b["post"]["pending"])
        self.assertEqual(1, b["post"]["observable"])
        # S12：T gpa 2.0 → T1 2.5，上升
        self.assertEqual(1, b["post"]["gpaDelta"]["up"])
        self.assertEqual(0.5, b["post"]["gpaDelta"]["mean"])

    def test_all_buckets_and_methodology(self):
        data = compute_trajectory(self.conn, self.v2)
        keys = {(b["ruleId"], b["level"]) for b in data["buckets"]}
        self.assertEqual({("R1", "严重"), ("R2", "严重"),
                          ("R4", "提醒"), ("R6", "严重")}, keys)
        m = data["methodology"]
        self.assertEqual(DISCLAIMER, m["disclaimer"])
        self.assertIn("不构成对任何个体学生的预测", m["text"])
        self.assertIn("source=sim", m["text"])
        self.assertEqual(T, m["dataRange"]["gradeSemesters"]["first"])
        self.assertEqual(T1, m["dataRange"]["gradeSemesters"]["last"])


class TrajectoryScopeTest(unittest.TestCase):
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

    def call(self, username, **kw) -> dict:
        result = alerts_trajectory(
            user=build_user(self.conn, username), conn=self.conn, **kw)
        self.assertEqual(0, result["code"])
        return result["data"]

    def test_counselor_scope_subset_of_school(self):
        full = self.call("dean", rule_id="R2", level="严重")["buckets"][0]
        scoped = self.call("counselor_a", rule_id="R2", level="严重")["buckets"][0]
        # 辅导员只看 B01：S01..S08，全校为 S01..S10
        self.assertEqual(10, full["sampleSize"])
        self.assertEqual(8, scoped["sampleSize"])
        self.assertLessEqual(scoped["sampleSize"], full["sampleSize"])
        n = self.conn.execute("""
            SELECT COUNT(*) FROM fact_alert a JOIN dim_student s
              ON s.student_id=a.student_id
            WHERE a.rule_id='R2' AND a.level='严重' AND s.class_id='B01'
        """).fetchone()[0]
        self.assertEqual(n, scoped["sampleSize"])
        # 范围内 resolved：S01..S03 → 3/8
        self.assertEqual(3, scoped["resolved"]["count"])
        self.assertEqual(0.375, scoped["resolved"]["ratio"])

    def test_unauthenticated_gets_401(self):
        with self.assertRaises(ApiError) as ctx:
            deps.get_current_user(authorization="", conn=self.conn)
        self.assertEqual(401, ctx.exception.status_code)


if __name__ == "__main__":
    unittest.main()
