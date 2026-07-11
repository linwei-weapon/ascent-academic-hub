"""输出当前分析库的核心数据质量基线（只读、无第三方依赖）。"""
import json
import sqlite3
import sys

sys.path.insert(0, __file__.rsplit("scripts", 1)[0])

from backend.etl.config import DB_PATH
from backend.api.settings import CURRENT_SEMESTER


def scalar(conn: sqlite3.Connection, sql: str, *params):
    return conn.execute(sql, params).fetchone()[0]


def main() -> None:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = CURRENT_SEMESTER
    result = {
        "semester": cur,
        "students": scalar(conn, "SELECT COUNT(*) FROM dim_student"),
        "current_fail_students": scalar(
            conn,
            """SELECT COUNT(DISTINCT student_id) FROM fact_grade
               WHERE is_pass=0 AND source='real' AND semester_id=?""",
            cur,
        ),
        "history_fail_students": scalar(
            conn,
            """SELECT COUNT(DISTINCT student_id) FROM fact_grade
               WHERE is_pass=0 AND source='real'""",
        ),
        "real_grade_rows": scalar(
            conn, "SELECT COUNT(*) FROM fact_grade WHERE source='real'"
        ),
        "fail_grade_rows": scalar(
            conn,
            "SELECT COUNT(*) FROM fact_grade WHERE source='real' AND is_pass=0",
        ),
        "alert_students": scalar(
            conn, "SELECT COUNT(DISTINCT student_id) FROM fact_alert WHERE COALESCE(is_active,1)=1"
        ),
        "alert_rows": scalar(conn, "SELECT COUNT(*) FROM fact_alert WHERE COALESCE(is_active,1)=1"),
        "repeat_same_course_failures": scalar(
            conn,
            """SELECT COUNT(*) FROM (
                 SELECT student_id, course_id
                 FROM fact_grade
                 WHERE source='real' AND is_pass=0
                 GROUP BY student_id, course_id
                 HAVING COUNT(*)>=2
               )""",
        ),
        "alerts_by_rule": [
            dict(row)
            for row in conn.execute(
                """SELECT rule_id, COUNT(*) AS alerts,
                          COUNT(DISTINCT student_id) AS students
                   FROM fact_alert WHERE COALESCE(is_active,1)=1
                   GROUP BY rule_id ORDER BY alerts DESC"""
            )
        ],
        "anomalous_teachers": [
            dict(row)
            for row in conn.execute(
                """SELECT teacher_id, COUNT(*) AS lessons
                   FROM fact_lesson WHERE semester_id=?
                   GROUP BY teacher_id HAVING COUNT(*)>200
                   ORDER BY lessons DESC""",
                (cur,),
            )
        ],
    }
    result["current_fail_rate"] = round(
        result["current_fail_students"] / result["students"], 4
    )
    result["history_fail_rate"] = round(
        result["history_fail_students"] / result["students"], 4
    )
    result["alert_student_rate"] = round(
        result["alert_students"] / result["students"], 4
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
