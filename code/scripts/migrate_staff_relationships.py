"""P2幂等迁移：补齐V2人员—学生关系的状态、范围引用和来源字段。"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])

from backend.etl import config
from backend.etl.init_v2 import init_v2


def migrate(db_path: Path | None = None) -> dict:
    conn = init_v2(db_path)
    try:
        conn.execute("""
            UPDATE staff_student_scope SET
              status=COALESCE(NULLIF(status,''),'active'),
              source_system=COALESCE(NULLIF(source_system,''),
                CASE WHEN relation_type='class_adviser'
                     THEN '行政班班主任' ELSE '学生导师库' END),
              scope_ref=CASE
                WHEN relation_type='class_adviser' THEN COALESCE(
                  NULLIF(scope_ref,''),
                  (SELECT class_code FROM dim_student s
                   WHERE s.student_id=staff_student_scope.student_id)
                )
                ELSE scope_ref
              END
        """)
        conn.commit()
        return {
            "total": conn.execute(
                "SELECT COUNT(*) FROM staff_student_scope"
            ).fetchone()[0],
            "active": conn.execute(
                "SELECT COUNT(*) FROM staff_student_scope WHERE status='active'"
            ).fetchone()[0],
            "classScopeRef": conn.execute("""
                SELECT COUNT(*) FROM staff_student_scope
                WHERE relation_type='class_adviser' AND scope_ref IS NOT NULL
            """).fetchone()[0],
            "sourceSystem": conn.execute("""
                SELECT COUNT(*) FROM staff_student_scope
                WHERE source_system IS NOT NULL
            """).fetchone()[0],
        }
    finally:
        conn.close()


def main(path: Path | None = None) -> None:
    result = migrate(path)
    print(f"== P2人员关系迁移: {path or config.V2_DB_PATH} ==")
    for key, value in result.items():
        print(f"{key}: {value}")
    print("迁移完成，可安全重复执行。")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
