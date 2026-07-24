"""学生成长分析汇总与查询索引幂等迁移。

在不修改成绩业务事实的前提下，重建学生学期和课程有效结果两个分析汇总，
并补充稳定查询索引。每次完整 ETL 或换批次数据后执行。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])

from backend.etl import config


INDEX_SQL = (
    """CREATE INDEX IF NOT EXISTS idx_grade_student_sem
       ON fact_grade(student_id, semester_id)""",
    """CREATE INDEX IF NOT EXISTS idx_grade_student_course_sem
       ON fact_grade(student_id, course_id, semester_id)""",
    """CREATE INDEX IF NOT EXISTS idx_grade_real_failed_student_sem_course
       ON fact_grade(student_id, semester_id, course_id)
       WHERE source='real' AND is_pass=0""",
    """CREATE INDEX IF NOT EXISTS idx_grade_real_effective_student_course_sem
       ON fact_grade(student_id, course_id, semester_id)
       WHERE source='real' AND is_pass IS NOT NULL""",
)

AGGREGATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS agg_student_term_growth (
    student_id TEXT NOT NULL,
    semester_id TEXT NOT NULL,
    weighted_gpa REAL,
    grade_count INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(student_id, semester_id)
);
CREATE INDEX IF NOT EXISTS idx_student_term_growth_semester
    ON agg_student_term_growth(semester_id, student_id);

CREATE TABLE IF NOT EXISTS agg_student_course_outcome (
    student_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    fail_count INTEGER NOT NULL DEFAULT 0,
    fail_semesters TEXT,
    latest_semester TEXT,
    latest_is_pass INTEGER,
    latest_credits REAL,
    latest_score REAL,
    latest_gpa REAL,
    PRIMARY KEY(student_id, course_id)
);
CREATE INDEX IF NOT EXISTS idx_student_course_outcome_unresolved
    ON agg_student_course_outcome(latest_is_pass, student_id);

CREATE TABLE IF NOT EXISTS agg_student_growth_meta (
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
    refreshed_at TEXT NOT NULL,
    source_grade_rows INTEGER NOT NULL DEFAULT 0,
    source_student_count INTEGER NOT NULL DEFAULT 0,
    semester_min TEXT,
    semester_max TEXT,
    rule_version TEXT NOT NULL
);
"""


def rebuild_growth_aggregates(conn: sqlite3.Connection) -> None:
    """把稳定学期指标与课程有效结果物化为只读分析事实。

    初始化/换批次数据后由本迁移重建；页面请求不再重复扫描完整成绩事实。
    """
    conn.executescript(AGGREGATE_SCHEMA)
    conn.execute("DELETE FROM agg_student_term_growth")
    conn.execute("""
        INSERT INTO agg_student_term_growth(
            student_id,semester_id,weighted_gpa,grade_count,fail_count
        )
        SELECT student_id,semester_id,
               SUM(CASE WHEN gpa IS NOT NULL AND credits>0
                        THEN gpa*credits END)
               /NULLIF(SUM(CASE WHEN gpa IS NOT NULL AND credits>0
                                THEN credits END),0),
               COUNT(*),
               COUNT(DISTINCT CASE WHEN is_pass=0 THEN course_id END)
        FROM fact_grade
        WHERE source='real' AND is_pass IS NOT NULL
        GROUP BY student_id,semester_id
    """)
    conn.execute("DELETE FROM agg_student_course_outcome")
    conn.execute("""
        WITH attempts AS (
            SELECT rowid source_row_id,student_id,course_id,semester_id,
                   is_pass,credits,score,gpa
            FROM fact_grade
            WHERE source='real' AND is_pass IS NOT NULL
        ),
        summaries AS (
            SELECT student_id,course_id,
                   SUM(CASE WHEN is_pass=0 THEN 1 ELSE 0 END) fail_count,
                   GROUP_CONCAT(DISTINCT CASE WHEN is_pass=0
                                              THEN semester_id END) fail_semesters
            FROM attempts
            GROUP BY student_id,course_id
        ),
        ranked AS (
            SELECT attempts.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY student_id,course_id
                       ORDER BY semester_id DESC,source_row_id DESC
                   ) latest_rank
            FROM attempts
        )
        INSERT INTO agg_student_course_outcome(
            student_id,course_id,fail_count,fail_semesters,
            latest_semester,latest_is_pass,latest_credits,latest_score,latest_gpa
        )
        SELECT ranked.student_id,ranked.course_id,summaries.fail_count,
               summaries.fail_semesters,ranked.semester_id,ranked.is_pass,
               ranked.credits,ranked.score,ranked.gpa
        FROM ranked
        JOIN summaries
          ON summaries.student_id=ranked.student_id
         AND summaries.course_id=ranked.course_id
        WHERE ranked.latest_rank=1
    """)
    conn.execute("""
        INSERT INTO agg_student_growth_meta(
            singleton_id,refreshed_at,source_grade_rows,
            source_student_count,semester_min,semester_max,rule_version
        )
        SELECT 1,strftime('%Y-%m-%dT%H:%M:%SZ','now'),
               COUNT(*),COUNT(DISTINCT student_id),
               MIN(semester_id),MAX(semester_id),'student-growth-v1'
        FROM fact_grade
        WHERE source='real' AND is_pass IS NOT NULL
        ON CONFLICT(singleton_id) DO UPDATE SET
            refreshed_at=excluded.refreshed_at,
            source_grade_rows=excluded.source_grade_rows,
            source_student_count=excluded.source_student_count,
            semester_min=excluded.semester_min,
            semester_max=excluded.semester_max,
            rule_version=excluded.rule_version
    """)


def migrate(conn: sqlite3.Connection) -> list[str]:
    for statement in INDEX_SQL:
        conn.execute(statement)
    rebuild_growth_aggregates(conn)
    conn.commit()
    return [
        row[0] for row in conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND name IN (
                'idx_grade_student_sem',
                'idx_grade_student_course_sem',
                'idx_grade_real_failed_student_sem_course',
                'idx_grade_real_effective_student_course_sem'
            ) ORDER BY name""")
    ]


def main(db_path: Path | None = None) -> None:
    path = Path(db_path or config.DB_PATH)
    conn = sqlite3.connect(str(path))
    try:
        indexes = migrate(conn)
    finally:
        conn.close()
    print(f"== 学生成长分析索引迁移: {path} ==")
    print("已确认索引: " + ", ".join(indexes))
    print("迁移完成，可安全重复执行。")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
