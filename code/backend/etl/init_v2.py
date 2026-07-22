"""创建并校验独立的 V2 真实数据接入验证库。"""
import argparse
import sqlite3
from pathlib import Path

from . import config


REQUIRED_TABLES = {
    "data_batch", "code_mapping", "dim_organization", "dim_semester",
    "dim_course", "dim_student", "dim_staff", "dim_building", "dim_room",
    "dim_period", "curriculum_plan", "curriculum_plan_course",
    "curriculum_plan_module_requirement",
    "curriculum_plan_goal", "curriculum_graduation_requirement",
    "curriculum_requirement_indicator", "curriculum_course_requirement_mapping",
    "student_plan_assignment", "teaching_lesson", "lesson_teacher",
    "course_meeting", "grade_attempt", "student_course_result",
    "student_course_substitution", "student_status_event",
    "graduation_outcome", "staff_student_scope", "room_availability",
    "metric_definition",
    "student_plan_course_status", "student_growth_indicator",
    "student_difficulty_flag", "student_timeline_event",
    "agg_course_pass_stat", "agg_course_offering", "agg_course_team", "agg_teacher_schedule_preference",
    "access_scope_mapping", "etl_run",
}

MIGRATION_COLUMNS = {
    "curriculum_plan_module_requirement": {"minimum_courses": "INTEGER"},
    "curriculum_plan": {"major_name": "TEXT", "required_min_credits": "REAL",
        "elective_min_credits": "REAL", "practice_min_credits": "REAL",
        "degree_requirement": "TEXT", "credit_rule_source_file": "TEXT"},
    "graduation_outcome": {
        "education_level": "TEXT", "organization_id": "TEXT", "major_code": "TEXT",
    },
    "student_status_event": {
        "before_grade": "TEXT", "after_grade": "TEXT",
        "before_organization": "TEXT", "after_organization": "TEXT",
        "before_major_name": "TEXT", "after_major_name": "TEXT",
        "before_class_code": "TEXT", "after_class_code": "TEXT",
        "event_reason": "TEXT", "event_note": "TEXT",
    },
    "grade_attempt": {
        "course_name": "TEXT", "replaced_course_id": "TEXT", "replaced_course_name": "TEXT",
        "requirement_type": "TEXT", "credits": "REAL", "total_score": "REAL",
        "makeup_score": "REAL", "deferred_score": "REAL", "bonus_score": "REAL",
        "publish_status": "TEXT",
    },
    "student_course_result": {"result_basis": "TEXT"},
    "student_course_substitution": {
        "original_course_name": "TEXT", "substitute_course_name": "TEXT", "workflow_status": "TEXT",
    },
    "teaching_lesson": {
        "course_name": "TEXT", "total_hours": "REAL", "theory_hours": "REAL",
        "experiment_hours": "REAL", "practice_hours": "REAL", "student_grade": "TEXT",
        "majors_text": "TEXT", "classes_text": "TEXT",
    },
    "course_meeting": {
        "week_pattern": "TEXT", "period_start": "INTEGER", "period_end": "INTEGER",
        "raw_schedule": "TEXT",
    },
    "dim_student": {"major_name": "TEXT"},
    "staff_student_scope": {
        "status": "TEXT NOT NULL DEFAULT 'active'",
        "scope_ref": "TEXT",
        "source_system": "TEXT",
        "source_updated_at": "TEXT",
    },
}


def init_v2(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path or config.V2_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(config.V2_SCHEMA_SQL.read_text(encoding="utf-8"))
    # 轻量前向迁移：开发中的 V2 库可在不删除已装载数据的情况下增加字段。
    for table, wanted in MIGRATION_COLUMNS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, sql_type in wanted.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
    conn.commit()
    return conn


def validate_schema(conn: sqlite3.Connection) -> dict:
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    missing = sorted(REQUIRED_TABLES - tables)
    return {
        "table_count": len(tables),
        "required_count": len(REQUIRED_TABLES),
        "missing": missing,
        "foreign_keys": conn.execute("PRAGMA foreign_keys").fetchone()[0],
        "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=config.V2_DB_PATH)
    args = parser.parse_args()
    conn = init_v2(args.db)
    report = validate_schema(conn)
    conn.close()
    if report["missing"]:
        raise SystemExit(f"V2 Schema 缺表: {report['missing']}")
    print(f"V2 数据库就绪: {args.db}")
    print(f"核心表: {report['required_count']} / 实际表: {report['table_count']}")
    print(f"foreign_keys={report['foreign_keys']} journal_mode={report['journal_mode']}")


if __name__ == "__main__":
    main()
