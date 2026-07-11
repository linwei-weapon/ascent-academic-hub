"""任课教师视图：获取所授课堂学生的预警摘要。
V1.1 新增——杨处反馈："让任课老师知道他的课堂里哪些学生需要帮助"。
"""
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends

from .. import db as dbm
from ..deps import get_db, get_current_user, student_data_scope
from ..envelope import ok

router = APIRouter(prefix="/api/teacher", tags=["teacher"])


@router.get("/alerts")
def teacher_alerts(conn: sqlite3.Connection = Depends(get_db),
                   user: dict = Depends(get_current_user)):
    """返回当前教师所授课堂中处于预警状态的学生列表。"""
    # 从 sys_role_scope 获取 teacher_id
    scope_row = dbm.query_one(conn, """
        SELECT scope_id FROM sys_role_scope WHERE role_id=?
    """, (user["role_id"],))
    if not scope_row:
        return ok({"students": [], "courses": []})

    teacher_id = scope_row["scope_id"]

    # 获取该教师当前学期授课课程列表
    courses = []
    for r in dbm.query(conn, """
        SELECT DISTINCT l.course_id, co.name course_name, l.class_names
        FROM fact_lesson l
        LEFT JOIN dim_course co ON l.course_id = co.course_id
        WHERE l.teacher_id = ? AND l.semester_id = (
            SELECT semester_id FROM dim_semester WHERE is_current = 1)
        ORDER BY co.name
    """, (teacher_id,)):
        courses.append({
            "courseId": r["course_id"],
            "courseName": r["course_name"] or r["course_id"],
            "className": r["class_names"] or "—",
        })

    # 获取该教师授课班级中处于预警状态的学生
    students = []
    for r in dbm.query(conn, """
        SELECT DISTINCT a.student_id sid, s.name, a.level, a.type,
               a.trigger_detail detail, a.status, a.created_at time,
               cl.name cls, m.name major
        FROM fact_alert a
        JOIN dim_student s ON a.student_id = s.student_id
        JOIN fact_grade g ON s.student_id = g.student_id
        JOIN fact_lesson l ON g.lesson_id = l.lesson_id AND g.semester_id = l.semester_id
        LEFT JOIN dim_class cl ON s.class_id = cl.class_id
        LEFT JOIN dim_major m ON s.major_id = m.major_id
        WHERE l.teacher_id = ? AND COALESCE(a.is_active,1)=1
        ORDER BY CASE a.level WHEN '严重' THEN 0 WHEN '警告' THEN 1 ELSE 2 END,
                 a.created_at DESC
    """, (teacher_id,)):
        # 该生在此教师课程中的挂科情况
        fail_info = dbm.query_one(conn, """
            SELECT COUNT(*) fc, GROUP_CONCAT(DISTINCT co.name) courses
            FROM fact_grade g
            JOIN fact_lesson l ON g.lesson_id = l.lesson_id AND g.semester_id = l.semester_id
            LEFT JOIN dim_course co ON g.course_id = co.course_id
            WHERE g.student_id = ? AND l.teacher_id = ? AND g.is_pass = 0
        """, (r["sid"], teacher_id)) or {}
        students.append({
            "sid": r["sid"],
            "name": r["name"] or r["sid"],
            "class": r["cls"] or "—",
            "major": r["major"] or "—",
            "level": r["level"],
            "type": r["type"],
            "detail": r["detail"],
            "status": r["status"],
            "time": r["time"],
            "failInMyCourse": fail_info.get("fc", 0),
            "failCourses": fail_info.get("courses", ""),
        })

    return ok({"students": students, "courses": courses})
