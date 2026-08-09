"""Create a compact, anonymized demo dataset for a source-only checkout.

This path is used only when the teaching-source databases are not available.
It creates both local analytics databases and the nine semester source files
needed by the cumulative CET-4 report.  All people and identifiers are
synthetic; production deployments must continue to use ``backend.etl.run_etl``.

Run from ``code/``::

    python -X utf8 scripts/bootstrap_demo_data.py
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.etl import config, db, seed
from backend.etl.extract_ts import SEMESTERS


COURSES = (
    ("C001", "高等数学 A1", 6.0),
    ("C002", "大学英语 1", 3.0),
    ("C003", "工程制图 C", 3.0),
    ("C004", "程序设计基础-Python", 2.5),
)
ORGANIZATIONS = (
    ("ORG001", "地球科学学院"),
    ("ORG002", "信息工程学院"),
)
MAJORS = (
    ("M001", "ORG001", "资源勘查工程", ("资源22-1班", "资源22-2班")),
    ("M002", "ORG001", "地质学", ("地质22-1班", "地质22-2班")),
    ("M003", "ORG002", "人工智能", ("人工智能22-1班", "人工智能22-2班")),
)


def _insert_frame(conn: sqlite3.Connection, table: str, frame: pd.DataFrame) -> None:
    if not frame.empty:
        frame.to_sql(table, conn, if_exists="append", index=False)


def _students() -> list[dict]:
    rows: list[dict] = []
    sequence = 1
    for major_code, organization_id, major_name, classes in MAJORS:
        for class_code in classes:
            for class_index in range(1, 11):
                rows.append({
                    "student_id": f"D{sequence:05d}",
                    "display_name": f"演示学生{sequence:02d}",
                    "gender": "男" if sequence % 2 else "女",
                    "entry_grade": 2022,
                    "education_level": "本科",
                    "organization_id": organization_id,
                    "major_code": major_code,
                    "major_name": major_name,
                    "class_code": class_code,
                    "plan_id": f"PLAN-{major_code}-2022",
                    "student_status": "在校",
                    "valid_from": "2022-09-01",
                    "valid_to": None,
                    "source": "demo",
                    "class_index": class_index,
                })
                sequence += 1
    # 留/降级学生不进入主人数，只按正式异动和当前责任班级进入括号人数。
    for index, (major_code, organization_id, major_name, classes) in enumerate(MAJORS, 1):
        rows.append({
            "student_id": f"R{index:05d}",
            "display_name": f"演示留级生{index}",
            "gender": "男" if index % 2 else "女",
            "entry_grade": 2021,
            "education_level": "本科",
            "organization_id": organization_id,
            "major_code": major_code,
            "major_name": major_name,
            "class_code": classes[0],
            "plan_id": f"PLAN-{major_code}-2022",
            "student_status": "在校",
            "valid_from": "2021-09-01",
            "valid_to": None,
            "source": "demo",
            "class_index": 0,
        })
    return rows


def _attempt_rows(students: list[dict]) -> list[dict]:
    rows: list[dict] = []
    source_row = 1
    for student in students:
        position = int(student["class_index"])
        for course_index, (course_id, course_name, credits) in enumerate(COURSES, 1):
            fail_count = 3 if position % 5 == 0 else 2 if position % 5 == 1 else 1 if position % 5 == 2 else 0
            regular_pass = course_index > fail_count
            score = 78 + ((source_row + course_index) % 16) if regular_pass else 45 + ((source_row + course_index) % 12)
            rows.append({
                "attempt_id": f"A{source_row:07d}", "student_id": student["student_id"],
                "course_id": course_id, "course_name": course_name, "replaced_course_id": None,
                "replaced_course_name": None, "lesson_id": f"L-{course_id}-2025262",
                "semester_id": "2025-2026-2", "attempt_type": "regular",
                "requirement_type": "required", "credits": credits, "score": score,
                "total_score": score, "makeup_score": None, "deferred_score": None,
                "bonus_score": None, "grade_level": None, "gpa": max(0, round((score - 50) / 10, 1)),
                "is_pass": int(regular_pass), "is_published": 1, "publish_status": "published",
                "is_void": 0, "previous_attempt_id": None, "batch_id": "DEMO-2025-2026-2",
                "source_row_no": source_row, "source": "demo",
            })
            regular_id = rows[-1]["attempt_id"]
            source_row += 1
            # 第一门普通考试不及格者有补考；部分通过、部分仍未通过。
            if not regular_pass and course_index == 1:
                makeup_pass = position % 5 in {1, 2}
                makeup_score = 66 if makeup_pass else 52
                rows.append({
                    "attempt_id": f"A{source_row:07d}", "student_id": student["student_id"],
                    "course_id": course_id, "course_name": course_name, "replaced_course_id": None,
                    "replaced_course_name": None, "lesson_id": f"L-{course_id}-2025262",
                    "semester_id": "2025-2026-2", "attempt_type": "makeup",
                    "requirement_type": "required", "credits": credits, "score": makeup_score,
                    "total_score": makeup_score, "makeup_score": makeup_score, "deferred_score": None,
                    "bonus_score": None, "grade_level": None, "gpa": 1.5 if makeup_pass else 0,
                    "is_pass": int(makeup_pass), "is_published": 1, "publish_status": "published",
                    "is_void": 0, "previous_attempt_id": regular_id, "batch_id": "DEMO-2025-2026-2",
                    "source_row_no": source_row, "source": "demo",
                })
                source_row += 1
    return rows


def _create_v2(students: list[dict], attempts: list[dict]) -> None:
    config.V2_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if config.V2_DB_PATH.exists():
        config.V2_DB_PATH.unlink()
    conn = sqlite3.connect(str(config.V2_DB_PATH))
    conn.executescript(config.V2_SCHEMA_SQL.read_text(encoding="utf-8"))
    conn.executemany(
        "INSERT OR REPLACE INTO dim_organization(organization_id,name,parent_id,organization_type,status,valid_from,valid_to,source) VALUES(?,?,?,?,?,?,?,?)",
        [(oid, name, None, "college", "active", "2020-01-01", None, "demo")
         for oid, name in ORGANIZATIONS],
    )
    # schema versions differ in older checkouts; use named columns for stable inserts.
    conn.executemany(
        "INSERT OR REPLACE INTO dim_semester(semester_id,name,academic_year,season,start_date,end_date,status,source) VALUES(?,?,?,?,?,?,?,?)",
        [(sem, sem, sem.rsplit("-", 1)[0], sem[-1], f"{sem[:4]}-09-01", "2026-07-15" if sem == "2025-2026-2" else f"{int(sem[:4]) + 1}-07-15", "closed", "demo") for sem in SEMESTERS],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO dim_course(course_id,name,nature,credits,status,source) VALUES(?,?,?,?,?,?)",
        [(cid, name, "必修", credits, "active", "demo") for cid, name, credits in COURSES],
    )
    student_columns = [key for key in students[0] if key != "class_index"]
    conn.executemany(
        f"INSERT OR REPLACE INTO dim_student({','.join(student_columns)}) VALUES({','.join('?' for _ in student_columns)})",
        [tuple(row[column] for column in student_columns) for row in students],
    )
    attempt_columns = list(attempts[0])
    conn.executemany(
        f"INSERT OR REPLACE INTO grade_attempt({','.join(attempt_columns)}) VALUES({','.join('?' for _ in attempt_columns)})",
        [tuple(row[column] for column in attempt_columns) for row in attempts],
    )
    retained = [row for row in students if row["student_id"].startswith("R")]
    conn.executemany(
        """INSERT OR REPLACE INTO student_status_event(
        event_id,student_id,event_type,before_status,after_status,before_grade,after_grade,
        before_class_code,after_class_code,event_reason,effective_at,batch_id,source_row_no,source)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(f"E-{row['student_id']}", row["student_id"], "留级", "在校", "在校", "2021", "2022",
          None, row["class_code"], "演示口径数据", "2025-09-01", "DEMO-STATUS", index, "demo")
         for index, row in enumerate(retained, 1)],
    )
    conn.execute("INSERT OR REPLACE INTO dim_staff(staff_id,display_name,organization_id,staff_type,status,source) VALUES('T-DEMO','演示导师','ORG001','mentor','active','demo')")
    conn.executemany(
        "INSERT OR REPLACE INTO staff_student_scope(staff_id,student_id,relation_type,valid_from,status,source) VALUES('T-DEMO',?,'mentor','2022-09-01','active','demo')",
        [(row["student_id"],) for row in students[:20]],
    )
    conn.commit()
    conn.close()


def _create_v1(students: list[dict], attempts: list[dict]) -> None:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = db.get_conn()
    db.init_schema(conn)
    colleges = pd.DataFrame([
        {"college_id": oid, "name": name, "source_name": name, "source": "demo"}
        for oid, name in ORGANIZATIONS
    ])
    majors = pd.DataFrame([
        {"major_id": mid, "college_id": oid, "name": name, "source": "demo"}
        for mid, oid, name, _ in MAJORS
    ])
    classes = pd.DataFrame([
        {"class_id": class_code, "major_id": mid, "grade": "2022", "name": class_code, "source": "demo"}
        for mid, _, _, class_codes in MAJORS for class_code in class_codes
    ])
    teachers = pd.DataFrame([{"teacher_id": "T-DEMO", "name": "演示教师", "dept": "ORG001", "title": "讲师", "source": "demo"}])
    for table, frame in (("dim_college", colleges), ("dim_major", majors), ("dim_class", classes), ("dim_teacher", teachers)):
        _insert_frame(conn, table, frame)
    _insert_frame(conn, "dim_course", pd.DataFrame([
        {"course_id": cid, "name": name, "credits": credits, "category": "本科", "course_nature": "必修", "is_required": 1, "dept": "演示开课单位", "source": "demo"}
        for cid, name, credits in COURSES
    ]))
    _insert_frame(conn, "dim_semester", pd.DataFrame([
        {"semester_id": sem, "year": sem.rsplit("-", 1)[0], "term": int(sem[-1]), "is_current": int(sem == "2025-2026-2"), "source": "demo"}
        for sem in SEMESTERS
    ]))
    student_frame = pd.DataFrame([
        {"student_id": row["student_id"], "name": row["display_name"], "college_id": row["organization_id"],
         "major_id": row["major_code"], "class_id": row["class_code"], "grade": str(row["entry_grade"]),
         "enroll_on": row["valid_from"], "status": "在籍", "source": "demo"}
        for row in students
    ])
    _insert_frame(conn, "dim_student", student_frame)
    regular_attempts = [row for row in attempts if row["attempt_type"] == "regular"]
    _insert_frame(conn, "fact_grade", pd.DataFrame([
        {"student_id": row["student_id"], "course_id": row["course_id"], "lesson_id": row["lesson_id"],
         "semester_id": row["semester_id"], "score": row["score"], "level": None, "gpa": row["gpa"],
         "is_pass": row["is_pass"], "is_required": 1, "is_retake": 0, "credits": row["credits"],
         "exam_status": "已发布", "source": "demo"}
        for row in regular_attempts
    ]))
    failed_by_student: dict[str, list[dict]] = {}
    for row in regular_attempts:
        if row["is_pass"] == 0:
            failed_by_student.setdefault(row["student_id"], []).append(row)
    alerts = []
    for student_id, failed in failed_by_student.items():
        if len(failed) >= 2:
            rule_id = "R2" if len(failed) >= 3 else "R2W"
            alerts.append({"student_id": student_id, "rule_id": rule_id, "type": "未解决挂科累积",
                           "level": "严重" if rule_id == "R2" else "警告", "trigger_detail": f"演示数据：未解决课程{len(failed)}门",
                           "status": "待处理", "created_at": "2026-07-16", "semester_id": "2025-2026-2",
                           "source": "demo", "is_active": 1, "rule_version": "demo-v1",
                           "activation_batch_id": "DEMO", "closed_at": None, "close_reason": None})
    _insert_frame(conn, "fact_alert", pd.DataFrame(alerts))
    dims = {"dim_college": colleges, "dim_major": majors, "dim_class": classes, "dim_teacher": teachers}
    for table, frame in seed.build_sys_tables(dims).items():
        _insert_frame(conn, table, frame)
    conn.commit()
    conn.close()


def _create_cet4_sources(students: list[dict]) -> None:
    config.TS_DIR.mkdir(parents=True, exist_ok=True)
    regular = [row for row in students if row["entry_grade"] == 2022]
    pass_groups = {
        "2024-2025-1": regular[0::10],
        "2024-2025-2": regular[1::10],
        "2025-2026-1": regular[2::10] + regular[3::10],
        "2025-2026-2": regular[4::10] + regular[5::10],
    }
    for semester in SEMESTERS:
        path = config.TS_DIR / f"{semester}.db"
        if path.exists():
            path.unlink()
        conn = sqlite3.connect(str(path))
        conn.execute("CREATE TABLE external_exams(student_id TEXT,exam_type TEXT,is_passed INTEGER)")
        conn.executemany(
            "INSERT INTO external_exams VALUES(?,?,1)",
            [(row["student_id"], "全国大学英语四级") for row in pass_groups.get(semester, [])],
        )
        conn.commit()
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="生成基础报表脱敏演示数据")
    parser.add_argument("--force", action="store_true", help="明确覆盖现有本地分析库")
    args = parser.parse_args()
    existing = [path for path in (config.DB_PATH, config.V2_DB_PATH) if path.exists()]
    if existing and not args.force:
        names = "、".join(str(path) for path in existing)
        raise SystemExit(f"检测到现有分析库，未执行覆盖：{names}；确认重建时请使用 --force")
    students = _students()
    attempts = _attempt_rows(students)
    _create_v1(students, attempts)
    _create_v2(students, attempts)
    _create_cet4_sources(students)
    print(f"[OK] 已生成脱敏演示库：{config.DB_PATH}")
    print(f"[OK] 已生成脱敏 V2 库：{config.V2_DB_PATH}")
    print(f"[OK] 已生成四级累计源库：{config.TS_DIR}（{len(SEMESTERS)} 个学期）")
    print(f"[INFO] 演示账号：admin / {seed.DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
