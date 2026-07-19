"""入库 load：把 transform 产出的 DataFrame 写入分析库（append 到已建表）。
列名须与 schema.sql 一致；多余列丢弃，缺失列留空。
"""
import sqlite3
import pandas as pd

from . import db as dbmod

# 各表的目标列（与 schema.sql 对齐），写入时按此投影
TABLE_COLS = {
    "dim_college": ["college_id", "name", "source_name", "source"],
    "dim_major": ["major_id", "college_id", "name", "source"],
    "dim_class": ["class_id", "major_id", "grade", "name", "source"],
    "dim_course": ["course_id", "name", "credits", "category", "course_nature",
                   "is_required", "dept", "source"],
    "dim_teacher": ["teacher_id", "name", "dept", "title", "source"],
    "dim_semester": ["semester_id", "year", "term", "is_current", "source"],
    "dim_student": ["student_id", "name", "college_id", "major_id", "class_id",
                    "grade", "enroll_on", "status", "source"],
    "fact_grade": ["student_id", "course_id", "lesson_id", "semester_id", "score",
                   "level", "gpa", "is_pass", "is_required", "is_retake", "credits",
                   "exam_status", "source"],
    "fact_lesson": ["lesson_id", "semester_id", "course_id", "teacher_id", "teacher_ids",
                    "capacity", "enrolled", "retake_count", "total_hours", "theory_hours",
                    "exp_hours", "practice_hours", "lab_hours", "classroom", "utilization",
                    "campus", "class_names", "source"],
    "fact_plan_course": ["major_id", "grade", "course_id", "course_name", "module",
                         "credits", "term", "is_core", "source"],
    "fact_plan_meta": ["major_id", "grade", "major_name", "total_credits",
                       "required_credits", "elective_credits", "practice_credits",
                       "degree_req", "grad_reqs_json", "source"],
    "fact_alert": ["student_id", "rule_id", "type", "level", "trigger_detail",
                   "status", "created_at", "semester_id", "source"],
    # --- 合成业务事实表（R3）---
    "fact_major_req": ["major_id", "grade", "total_req", "general_req", "major_req",
                       "practice_req", "source"],
    "fact_graduation": ["student_id", "grade", "major_id", "college_id",
                        "earned_credits", "req_credits", "graduated", "degree",
                        "grad_status", "goal", "semester_id", "source"],
    "fact_attrition": ["student_id", "grade", "major_id", "college_id", "kind",
                       "reason", "semester_id", "source"],
    "fact_discipline": ["student_id", "college_id", "kind", "detail", "punish",
                        "semester_id", "source"],
    "fact_exam_cert": ["student_id", "college_id", "cet4", "cet6", "ncre2", "ncre3",
                       "source"],
    "fact_attend": ["course_id", "college_id", "semester_id", "attend_rate",
                    "absent_gt3", "absent_gt3_pct", "trend", "source"],
    "fact_teacher_profile": ["teacher_id", "norm_title", "education", "degree",
                             "age", "age_band", "origin", "school", "teach_years",
                             "source"],
    "fact_schedule_change": ["teacher_id", "college_id", "kind", "reason", "month",
                             "hours", "affected", "auto_approved", "review_days",
                             "semester_id", "source"],
    # --- agg_ 预聚合 ---
    "agg_college_term": ["college_id", "semester_id", "students", "avg_score",
                         "fail_rate", "gpa_avg", "alert_rate", "credit_done", "source"],
    "agg_major_term": ["major_id", "semester_id", "grade", "students", "avg_score",
                       "fail_rate", "gpa_avg", "alert_count", "credit_done", "source"],
    "agg_course_term": ["course_id", "semester_id", "avg_score", "fail_rate", "total",
                        "excellent_rate", "retake_rate", "first_pass_rate", "final_pass_rate",
                        "source"],
    "agg_gpa_dist": ["scope_type", "scope_id", "semester_id", "bucket", "count",
                     "percent", "source"],
    "agg_teacher_load": ["teacher_id", "semester_id", "title", "hours", "courses",
                         "classes", "source"],
    "agg_classroom_util": ["building", "room_type", "semester_id", "day", "period",
                           "utilization", "source"],
    "agg_course_category_term": ["category", "semester_id", "course_count",
                                  "lesson_count", "total_hours", "theory_hours",
                                  "exp_hours", "practice_hours", "lab_hours",
                                  "avg_enrolled", "small_count", "medium_count",
                                  "large_count", "xlarge_count", "source"],
    # --- sys_ 元数据 ---
    "sys_alert_rule": ["rule_id", "name", "level", "trigger_type", "params", "enabled"],
    "sys_role": ["role_id", "name", "data_scope_type"],
    "sys_role_scope": ["role_id", "scope_id"],
    "sys_user_staff": ["username", "staff_id", "valid_from", "valid_to",
                       "status", "source", "source_updated_at"],
    "sys_user_role": ["user_role_id", "username", "role_id", "is_default",
                      "valid_from", "valid_to", "status", "source"],
    "sys_user_scope": ["user_scope_id", "user_role_id", "scope_type", "scope_id",
                       "valid_from", "valid_to", "status", "source"],
    "sys_role_action": ["role_id", "action_id"],
    "sys_menu": ["menu_id", "parent_id", "title", "path", "icon", "sort_order"],
    "sys_role_menu": ["role_id", "menu_id"],
    "sys_user": ["username", "password_hash", "name", "role_id", "status"],
    "sys_config": ["config_key", "config_value"],
    "sys_discovered_rule": ["semester_id", "name", "conditions", "level",
                            "confidence", "risk_ratio", "sample_size",
                            "detail_json", "status", "source"],
    "sys_kpi_config": ["kpi_id", "module", "label", "enabled", "sort_order",
                       "calc_type", "formula", "unit", "color_rule",
                       "threshold_warn", "threshold_danger", "scope_applicable"],
}


def write_table(conn: sqlite3.Connection, table: str, df: pd.DataFrame) -> int:
    """按目标列投影后 append 写入。返回写入行数。"""
    cols = TABLE_COLS[table]
    out = df.copy()
    for c in cols:
        if c not in out.columns:
            out[c] = None
    out = out[cols]
    out.to_sql(table, conn, if_exists="append", index=False)
    return len(out)


def load_all(conn: sqlite3.Connection, tables: dict) -> dict:
    """tables: {table_name: DataFrame} → 逐表写入，返回行数统计。"""
    counts = {}
    for name, df in tables.items():
        if df is None or len(df) == 0:
            counts[name] = 0
            continue
        counts[name] = write_table(conn, name, df)
    conn.commit()
    return counts
