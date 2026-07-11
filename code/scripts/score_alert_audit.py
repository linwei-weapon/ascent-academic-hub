"""审计成绩尝试、最终通过状态和预警命中构成（只读）。"""
import json
import sqlite3
import sys

sys.path.insert(0, __file__.rsplit("scripts", 1)[0])

from backend.api.settings import CURRENT_SEMESTER
from backend.etl.config import DB_PATH


def scalar(conn: sqlite3.Connection, sql: str, *params):
    return conn.execute(sql, params).fetchone()[0]


def rows(conn: sqlite3.Connection, sql: str, *params):
    return [dict(row) for row in conn.execute(sql, params)]


def main() -> None:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = CURRENT_SEMESTER
    recent_semesters = {r[0] for r in conn.execute(
        "SELECT semester_id FROM dim_semester ORDER BY semester_id DESC LIMIT 2")}
    # 一次顺序扫描构建学生×课程状态，避免在 64 万行上反复执行相关子查询。
    course_state: dict[tuple[str, str], list[bool]] = {}
    attempt_fail_students: set[str] = set()
    current_attempt_fail_students: set[str] = set()
    for row in conn.execute(
        """SELECT student_id, course_id, semester_id, is_pass
           FROM fact_grade WHERE source='real'"""
    ):
        sid, cid, semester, passed = row
        if not sid or not cid:
            continue
        state = course_state.setdefault((sid, cid), [False, False, False, False])
        if passed == 0:
            state[0] = True
            attempt_fail_students.add(sid)
            if semester == cur:
                state[2] = True
                current_attempt_fail_students.add(sid)
            if semester in recent_semesters:
                state[3] = True
        elif passed == 1:
            state[1] = True
    resolved_students = {
        sid for (sid, _), (had_fail, had_pass, _, _) in course_state.items()
        if had_fail and had_pass
    }
    unresolved_students = {
        sid for (sid, _), (had_fail, had_pass, _, _) in course_state.items()
        if had_fail and not had_pass
    }
    current_unresolved_students = {
        sid for (sid, _), (_, had_pass, current_fail, _) in course_state.items()
        if current_fail and not had_pass
    }
    recent_unresolved_count: dict[str, int] = {}
    for (sid, _), (_, had_pass, _, recent_fail) in course_state.items():
        if recent_fail and not had_pass:
            recent_unresolved_count[sid] = recent_unresolved_count.get(sid, 0) + 1

    result = {
        "semester": cur,
        "exam_status": rows(
            conn,
            """SELECT COALESCE(exam_status,'(空)') AS name, COUNT(*) AS rows,
                      SUM(CASE WHEN is_pass=0 THEN 1 ELSE 0 END) AS failed
               FROM fact_grade WHERE source='real'
               GROUP BY exam_status ORDER BY rows DESC""",
        ),
        "retake": rows(
            conn,
            """SELECT COALESCE(is_retake,-1) AS is_retake, COUNT(*) AS rows,
                      SUM(CASE WHEN is_pass=0 THEN 1 ELSE 0 END) AS failed,
                      COUNT(DISTINCT student_id) AS students
               FROM fact_grade WHERE source='real'
               GROUP BY is_retake ORDER BY is_retake""",
        ),
        "duplicate_rows": scalar(
            conn,
            """SELECT COALESCE(SUM(n-1),0) FROM (
                 SELECT student_id, course_id, semester_id, lesson_id, COUNT(*) AS n
                 FROM fact_grade WHERE source='real'
                 GROUP BY student_id, course_id, semester_id, lesson_id
                 HAVING COUNT(*)>1
               )""",
        ),
        "attempt_fail_students": len(attempt_fail_students),
        "resolved_after_failure_students": len(resolved_students),
        "unresolved_fail_students": len(unresolved_students),
        "current_attempt_fail_students": len(current_attempt_fail_students),
        "current_unresolved_fail_students": len(current_unresolved_students),
        "r2_new_definition_students": sum(
            1 for count in recent_unresolved_count.values() if count >= 3
        ),
        "r2_warning_exactly_two_students": sum(
            1 for count in recent_unresolved_count.values() if count == 2
        ),
        "failed_attempts_per_student": rows(
            conn,
            """SELECT bucket, COUNT(*) AS students FROM (
                 SELECT student_id,
                        CASE WHEN n=1 THEN '1'
                             WHEN n=2 THEN '2'
                             WHEN n BETWEEN 3 AND 4 THEN '3-4'
                             WHEN n BETWEEN 5 AND 9 THEN '5-9'
                             ELSE '10+' END AS bucket
                 FROM (SELECT student_id, COUNT(*) AS n FROM fact_grade
                       WHERE source='real' AND is_pass=0 GROUP BY student_id)
               ) GROUP BY bucket ORDER BY CASE bucket WHEN '1' THEN 1 WHEN '2' THEN 2
                 WHEN '3-4' THEN 3 WHEN '5-9' THEN 4 ELSE 5 END""",
        ),
        "alerts_by_rule": rows(
            conn,
            """SELECT a.rule_id, r.name, r.level, r.params,
                      COUNT(*) AS alerts, COUNT(DISTINCT a.student_id) AS students
               FROM fact_alert a LEFT JOIN sys_alert_rule r ON a.rule_id=r.rule_id
               WHERE COALESCE(a.is_active,1)=1
               GROUP BY a.rule_id, r.name, r.level, r.params ORDER BY alerts DESC""",
        ),
        "alert_overlap": rows(
            conn,
            """SELECT rule_count, COUNT(*) AS students FROM (
                 SELECT student_id, COUNT(DISTINCT rule_id) AS rule_count
                 FROM fact_alert WHERE COALESCE(is_active,1)=1 GROUP BY student_id
               ) GROUP BY rule_count ORDER BY rule_count""",
        ),
        "alert_by_student_status": rows(
            conn,
            """SELECT COALESCE(s.status,'(空)') AS status,
                      COUNT(DISTINCT a.student_id) AS students
               FROM fact_alert a JOIN dim_student s ON a.student_id=s.student_id
               WHERE COALESCE(a.is_active,1)=1
               GROUP BY s.status ORDER BY students DESC""",
        ),
    }
    total_students = scalar(conn, "SELECT COUNT(*) FROM dim_student") or 1
    for key in (
        "attempt_fail_students",
        "unresolved_fail_students",
        "current_attempt_fail_students",
        "current_unresolved_fail_students",
    ):
        result[key + "_rate"] = round(result[key] / total_students, 4)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
