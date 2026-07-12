"""把现有原型库中2022级方案学生的真实成绩桥接到V2尝试层。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .init_v2 import init_v2
from .v2_grade_loader import RULE_VERSION
from .v2_master_loader import _hash


def bridge_legacy_grades(db_path: Path | None = None, legacy_path: Path | None = None) -> dict:
    legacy_path = Path(legacy_path or config.DB_PATH)
    file_hash = _hash(legacy_path)
    batch_id = f"legacy-grade-{file_hash[:16]}"
    conn = init_v2(db_path)
    try:
        conn.execute("ATTACH DATABASE ? AS legacy", (str(legacy_path),))
        eligible = conn.execute(
            "SELECT COUNT(*) FROM legacy.fact_grade g JOIN student_plan_assignment a ON a.student_id=g.student_id WHERE g.source='real'"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO grade_attempt(attempt_id,student_id,course_id,course_name,lesson_id,semester_id,attempt_type,requirement_type,credits,score,grade_level,gpa,is_pass,is_published,publish_status,is_void,batch_id,source_row_no,source) "
            "SELECT 'LEGACY-GRADE-'||g.grade_id,g.student_id,g.course_id,c.name,g.lesson_id,g.semester_id,CASE WHEN g.is_retake=1 THEN 'retake' WHEN g.exam_status='补考' THEN 'makeup' WHEN g.exam_status='缓考' THEN 'deferred' ELSE 'regular' END,CASE WHEN g.is_required=1 THEN '必修' ELSE '选修' END,g.credits,g.score,g.level,g.gpa,g.is_pass,1,'已发布',0,?,g.grade_id,'real_legacy' "
            "FROM legacy.fact_grade g JOIN student_plan_assignment a ON a.student_id=g.student_id LEFT JOIN dim_course c ON c.course_id=g.course_id WHERE g.source='real' "
            "ON CONFLICT(attempt_id) DO UPDATE SET score=excluded.score,gpa=excluded.gpa,is_pass=excluded.is_pass,credits=excluded.credits,source='real_legacy'",
            (batch_id,),
        )
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO data_batch(batch_id,source_code,source_file,file_hash,ingested_at,row_count,accepted_count,quality_status) VALUES(?,?,?,?,?,?,?,'accepted') "
            "ON CONFLICT(batch_id) DO UPDATE SET ingested_at=excluded.ingested_at,row_count=excluded.row_count,accepted_count=excluded.accepted_count,quality_status='accepted'",
            (batch_id, "legacy_grade", str(legacy_path), file_hash, now, eligible, eligible),
        )

        # 对全部新旧成绩统一重算同一规则版本。
        conn.execute("DELETE FROM student_course_result WHERE rule_version=?", (RULE_VERSION,))
        conn.execute(
            "INSERT INTO student_course_result(student_id,course_id,rule_version,effective_attempt_id,effective_score,is_pass,earned_credits,result_basis,calculated_at,source) "
            "SELECT student_id,course_id,?,attempt_id,score,is_pass,CASE WHEN is_pass=1 THEN credits ELSE 0 END,CASE WHEN is_pass=1 THEN 'published-pass-highest-score' ELSE 'published-latest-failure' END,?,'derived' "
            "FROM (SELECT g.*,ROW_NUMBER() OVER(PARTITION BY student_id,course_id ORDER BY CASE WHEN is_pass=1 THEN 1 ELSE 0 END DESC,CASE WHEN is_pass=1 THEN COALESCE(score,-999) END DESC,semester_id DESC,source_row_no DESC) rn FROM grade_attempt g WHERE is_published=1 AND is_void=0) ranked WHERE rn=1",
            (RULE_VERSION, now),
        )
        conn.commit()
        report = {
            "legacy_attempts": eligible,
            "plan_students": conn.execute("SELECT COUNT(DISTINCT student_id) FROM student_plan_assignment").fetchone()[0],
            "plan_students_with_results": conn.execute("SELECT COUNT(DISTINCT a.student_id) FROM student_plan_assignment a JOIN student_course_result r ON r.student_id=a.student_id WHERE r.rule_version=?", (RULE_VERSION,)).fetchone()[0],
            "all_grade_attempts": conn.execute("SELECT COUNT(*) FROM grade_attempt").fetchone()[0],
            "all_effective_results": conn.execute("SELECT COUNT(*) FROM student_course_result WHERE rule_version=?", (RULE_VERSION,)).fetchone()[0],
            "legacy_orphan_students": conn.execute("SELECT COUNT(DISTINCT g.student_id) FROM grade_attempt g LEFT JOIN dim_student s ON s.student_id=g.student_id WHERE g.batch_id=? AND s.student_id IS NULL", (batch_id,)).fetchone()[0],
        }
        conn.execute("DETACH DATABASE legacy")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return report


def main() -> None:
    print(json.dumps(bridge_legacy_grades(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
