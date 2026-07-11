"""元数据组：GET /api/admin/meta/filters。
返回各维度可选值（学期/年级/校区/学院/课程性质/职称/预警枚举），供前端下拉动态加载，
避免前端硬编码。全部数据驱动（读 analytics.sqlite 真实维度），随 ETL 自动更新。
"""
import sqlite3

from fastapi import APIRouter, Depends

from .. import db as dbm
from ..deps import get_db, get_current_user
from ..envelope import ok
from ..settings import CURRENT_SEMESTER

router = APIRouter(prefix="/api/admin/meta", tags=["meta"])


@router.get("/filters")
def filters(user: dict = Depends(get_current_user),
            conn: sqlite3.Connection = Depends(get_db)):
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

    colleges = [{"value": r["college_id"], "label": r["name"]} for r in dbm.query(
        conn, "SELECT college_id, name FROM dim_college ORDER BY college_id")]

    course_nature = [r["course_nature"] for r in dbm.query(
        conn, "SELECT DISTINCT course_nature FROM dim_course "
        "WHERE course_nature IS NOT NULL AND course_nature<>'' ORDER BY course_nature DESC")]

    titles = ["教授", "副教授", "讲师", "助教", "其他"]

    # 专业（带所属学院，供前端按学院联动过滤）
    majors = [{"value": r["major_id"], "label": r["name"], "college": r["college_id"]}
              for r in dbm.query(
        conn, "SELECT major_id, name, college_id FROM dim_major ORDER BY college_id, major_id")]

    # 班级（带专业/年级，量较大但一次性拉取）
    classes = [{"value": r["class_id"], "label": r["name"], "major": r["major_id"],
                "grade": str(r["grade"]) if r["grade"] is not None else ""}
               for r in dbm.query(
        conn, "SELECT class_id, name, major_id, grade FROM dim_class ORDER BY grade DESC, class_id")]

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
