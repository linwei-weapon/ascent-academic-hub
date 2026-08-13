"""元数据组：GET /api/admin/meta/filters。
返回各维度可选值（学期/年级/校区/学院/课程性质/职称/预警枚举），供前端下拉动态加载，
避免前端硬编码。全部数据驱动（读 analytics.sqlite 真实维度），随 ETL 自动更新。
"""
import sqlite3

from fastapi import APIRouter, Depends, Query

from .. import db as dbm
from ..deps import get_db, get_current_user
from ..envelope import ApiError, ok
from ..settings import CURRENT_SEMESTER

router = APIRouter(prefix="/api/admin/meta", tags=["meta"])


@router.get("/filters")
def filters(user: dict = Depends(get_current_user),
            conn: sqlite3.Connection = Depends(get_db)):
    detail = (user.get("permission_context") or {}).get("detailScope") or {}
    scope_type = detail.get("type", "all")
    scope_ids = detail.get("sourceScopeIds") or []
    semesters = [
        {"value": r["semester_id"], "label": r["semester_id"],
         "current": bool(r["is_current"])}
        for r in dbm.query(conn, "SELECT semester_id, is_current FROM dim_semester "
                           "ORDER BY semester_id")]

    grades = [str(r["grade"]) for r in dbm.query(
        conn, "SELECT DISTINCT grade FROM dim_student WHERE grade IS NOT NULL "
        "ORDER BY grade")]

    campuses = [r["campus"] for r in dbm.query(
        conn, "SELECT DISTINCT campus FROM fact_lesson "
        "WHERE campus IS NOT NULL AND campus<>'' ORDER BY campus")]

    college_where, college_params = "", []
    if scope_type == "college":
        college_where = f" WHERE college_id IN ({','.join('?' * len(scope_ids))})"
        college_params = scope_ids
    elif scope_type == "major":
        college_where = f""" WHERE college_id IN (
          SELECT college_id FROM dim_major
          WHERE major_id IN ({','.join('?' * len(scope_ids))})
        )"""
        college_params = scope_ids
    elif scope_type == "class":
        college_where = f""" WHERE college_id IN (
          SELECT DISTINCT m.college_id FROM dim_class b
          JOIN dim_major m ON m.major_id=b.major_id
          WHERE b.class_id IN ({','.join('?' * len(scope_ids))})
        )"""
        college_params = scope_ids
    elif scope_type != "all":
        college_where = " WHERE 1=0"
    colleges = [{"value": r["college_id"], "label": r["name"]} for r in dbm.query(
        conn, f"SELECT college_id, name FROM dim_college{college_where} "
              "ORDER BY college_id", tuple(college_params))]
    comparison = (user.get("permission_context") or {}).get("comparisonScope") or {}
    comparison_colleges = (
        [{"value": r["college_id"], "label": r["name"]} for r in dbm.query(
            conn, "SELECT college_id,name FROM dim_college ORDER BY college_id")]
        if comparison.get("allowOtherOrganizations") else colleges
    )

    course_nature = [r["course_nature"] for r in dbm.query(
        conn, "SELECT DISTINCT course_nature FROM dim_course "
        "WHERE course_nature IS NOT NULL AND course_nature<>'' ORDER BY course_nature DESC")]

    titles = ["教授", "副教授", "讲师", "助教", "其他"]

    # 专业（带所属学院，供前端按学院联动过滤）
    major_where, major_params = "", []
    if scope_type == "college":
        major_where = f" WHERE college_id IN ({','.join('?' * len(scope_ids))})"
        major_params = scope_ids
    elif scope_type == "major":
        major_where = f" WHERE major_id IN ({','.join('?' * len(scope_ids))})"
        major_params = scope_ids
    elif scope_type == "class":
        major_where = f""" WHERE major_id IN (
          SELECT DISTINCT major_id FROM dim_class
          WHERE class_id IN ({','.join('?' * len(scope_ids))})
        )"""
        major_params = scope_ids
    elif scope_type != "all":
        major_where = " WHERE 1=0"
    majors = [{"value": r["major_id"], "label": r["name"], "college": r["college_id"]}
              for r in dbm.query(
        conn, f"SELECT major_id,name,college_id FROM dim_major{major_where} "
              "ORDER BY college_id,major_id", tuple(major_params))]

    # 班级（带专业/年级，量较大但一次性拉取）
    class_where, class_params = "", []
    if scope_type == "college":
        class_where = f""" WHERE major_id IN (
          SELECT major_id FROM dim_major
          WHERE college_id IN ({','.join('?' * len(scope_ids))})
        )"""
        class_params = scope_ids
    elif scope_type == "major":
        class_where = f" WHERE major_id IN ({','.join('?' * len(scope_ids))})"
        class_params = scope_ids
    elif scope_type == "class":
        class_where = f" WHERE class_id IN ({','.join('?' * len(scope_ids))})"
        class_params = scope_ids
    elif scope_type != "all":
        class_where = " WHERE 1=0"
    classes = [{"value": r["class_id"], "label": r["name"], "major": r["major_id"],
                "grade": str(r["grade"]) if r["grade"] is not None else ""}
               for r in dbm.query(
        conn, f"SELECT class_id,name,major_id,grade FROM dim_class{class_where} "
              "ORDER BY grade DESC,class_id", tuple(class_params))]

    # 课程类别 A2（dim_course.category，区别于课程性质 course_nature）
    categories = [r["category"] for r in dbm.query(
        conn, "SELECT DISTINCT category FROM dim_course "
        "WHERE category IS NOT NULL AND category<>'' ORDER BY category")]

    # 教室类型 A7 / 楼栋（agg_classroom_util 已带 room_type/building）
    room_types = [r["room_type"] for r in dbm.query(
        conn, "SELECT DISTINCT room_type FROM agg_classroom_util "
        "WHERE room_type IS NOT NULL AND room_type<>'' ORDER BY room_type")]
    buildings = [r["building"] for r in dbm.query(
        conn, "SELECT DISTINCT building FROM agg_classroom_util "
        "WHERE building IS NOT NULL AND building<>'' ORDER BY building")]

    # 学年 S1（dim_semester.year 去重）
    years = [r["year"] for r in dbm.query(
        conn, "SELECT DISTINCT year FROM dim_semester WHERE year IS NOT NULL ORDER BY year")]

    # 学籍异动类型 S8（与 fact_attrition.kind 对齐，仅取常用四类切片）
    attrition_kinds = ["休学", "复学", "退学", "转专业"]

    # 班额档 A4（前端语义标签，后端按区间过滤）
    size_buckets = ["小班(<30)", "中班(30-60)", "大班(60-120)", "超大班(>120)"]

    alert = {
        "level": [r["level"] for r in dbm.query(
            conn, "SELECT level, COUNT(*) n FROM fact_alert WHERE COALESCE(is_active,1)=1 GROUP BY level "
            "ORDER BY CASE level WHEN '严重' THEN 0 WHEN '警告' THEN 1 ELSE 2 END")],
        "type": [r["type"] for r in dbm.query(
            conn, "SELECT DISTINCT type FROM fact_alert WHERE COALESCE(is_active,1)=1 ORDER BY type")],
        "status": [r["status"] for r in dbm.query(
            conn, "SELECT DISTINCT status FROM fact_alert WHERE COALESCE(is_active,1)=1 ORDER BY status")],
    }

    return ok({
        "current": CURRENT_SEMESTER,
        "semesters": semesters,
        "grades": grades,
        "campuses": campuses,
        "colleges": colleges,
        "comparisonColleges": comparison_colleges,
        "courseNature": course_nature,
        "titles": titles,
        "majors": majors,
        "classes": classes,
        "categories": categories,
        "roomTypes": room_types,
        "buildings": buildings,
        "years": years,
        "attritionKinds": attrition_kinds,
        "sizeBuckets": size_buckets,
        "alert": alert,
        "retake": ["全部", "重修", "非重修"],
    })


@router.get("/college-comparison")
def college_comparison(
    semester: str = Query(default=CURRENT_SEMESTER),
    user: dict = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """跨学院只读聚合；他院行不提供学生标识或明细下钻。"""
    context = user.get("permission_context") or {}
    comparison = context.get("comparisonScope") or {}
    if not comparison.get("allowOtherOrganizations"):
        raise ApiError("当前身份没有跨学院聚合比较权限", code=403, status_code=403)
    if not dbm.query_one(
        conn, "SELECT 1 FROM dim_semester WHERE semester_id=?", (semester,)
    ):
        raise ApiError("学期不存在", code=400, status_code=400)
    minimum = int(comparison.get("minimumGroupSize") or 10)
    detail = context.get("detailScope") or {}
    own_ids = set(detail.get("sourceScopeIds") or [])
    rows = dbm.query(conn, """
        WITH base AS (
          SELECT c.college_id,c.name,COUNT(DISTINCT s.student_id) students
          FROM dim_college c JOIN dim_student s ON s.college_id=c.college_id
          GROUP BY c.college_id,c.name
        ), score AS (
          SELECT s.college_id,
            SUM(CASE WHEN g.score IS NOT NULL AND g.credits>0
                THEN g.score*g.credits END)
              / NULLIF(SUM(CASE WHEN g.score IS NOT NULL AND g.credits>0
                THEN g.credits END),0) avg_score,
            COUNT(DISTINCT CASE WHEN g.is_pass IS NOT NULL
              THEN g.student_id END) result_students,
            COUNT(DISTINCT CASE WHEN g.is_pass=0 THEN g.student_id END) failed_students
          FROM fact_grade g JOIN dim_student s ON s.student_id=g.student_id
          WHERE g.source='real' AND g.semester_id=?
          GROUP BY s.college_id
        ), student_gpa AS (
          SELECT s.college_id,g.student_id,AVG(g.gpa) student_gpa
          FROM fact_grade g JOIN dim_student s ON s.student_id=g.student_id
          WHERE g.source='real' AND g.semester_id=? AND g.gpa IS NOT NULL
          GROUP BY s.college_id,g.student_id
        ), gpa AS (
          SELECT college_id,AVG(student_gpa) avg_gpa
          FROM student_gpa GROUP BY college_id
        ), alerts AS (
          SELECT s.college_id,COUNT(DISTINCT a.student_id) alert_students
          FROM fact_alert a JOIN dim_student s ON s.student_id=a.student_id
          WHERE COALESCE(a.is_active,1)=1 GROUP BY s.college_id
        )
        SELECT b.college_id,b.name,b.students,sc.avg_score,gp.avg_gpa,
          COALESCE(sc.result_students,0) result_students,
          COALESCE(sc.failed_students,0) failed_students,
          COALESCE(a.alert_students,0) alert_students
        FROM base b LEFT JOIN score sc ON sc.college_id=b.college_id
        LEFT JOIN gpa gp ON gp.college_id=b.college_id
        LEFT JOIN alerts a ON a.college_id=b.college_id
        WHERE b.students>=? ORDER BY b.college_id
    """, (semester, semester, minimum))
    items = []
    for row in rows:
        students = row["students"] or 0
        result_students = row["result_students"] or 0
        can_drill = detail.get("type") == "all" or row["college_id"] in own_ids
        items.append({
            "collegeId": row["college_id"],
            "collegeName": row["name"],
            "students": students,
            "weightedAverageScore": (
                round(row["avg_score"], 1) if row["avg_score"] is not None else None
            ),
            "averageGpa": (
                round(row["avg_gpa"], 2) if row["avg_gpa"] is not None else None
            ),
            "currentFailStudentRate": round(
                row["failed_students"] * 100 / result_students, 1
            ) if result_students else None,
            "activeAlertStudentRate": round(
                row["alert_students"] * 100 / students, 1
            ) if students else None,
            "studentsWithValidResults": result_students,
            "validResultCoverageRate": round(
                result_students * 100 / students, 1
            ) if students else None,
            "canDrillDown": can_drill,
            "detailRoute": (
                f"/admin/dashboard/college/{row['college_id']}" if can_drill else None
            ),
        })
    return ok({
        "semester": semester,
        "minimumGroupSize": minimum,
        "items": items,
        "definition": {
            "weightedAverageScore": "当前学期有效成绩按课程学分加权后的学院平均分。",
            "averageGpa": "先计算每名学生当前学期课程GPA均值，再对学院学生求平均，避免课程门数不同造成偏移。",
            "currentFailStudentRate": "当前学期至少一门未通过的去重学生数÷当前学期有有效成绩的去重学生数。",
            "activeAlertStudentRate": "当前有效预警去重学生数÷学院在籍学生数。",
            "validResultCoverageRate": "当前学期有有效成绩的去重学生数÷学院在籍学生数，用于判断成绩指标是否具备解释条件。",
            "boundary": "其他学院仅返回达到最小群体规模的聚合结果，不返回学生标识、名单、档案或明细路由。",
        },
        "period": {"semester": semester},
        "definitionVersion": "dashboard-v2",
    })
