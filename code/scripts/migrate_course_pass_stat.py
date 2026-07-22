"""M1 幂等迁移：课程通过率三分层。

一次性完成两件事，均可安全重复执行：
1. V2 库：创建 agg_course_pass_stat（schema_v2.sql 已含 DDL，init_v2 幂等建表），
   并从 grade_attempt 全量重建课程×学期三分层通过率聚合。
2. V1 库：sys_kpi_config 登记 4 条课程质量指标口径（INSERT OR IGNORE）。

用法：cd code && python -X utf8 scripts/migrate_course_pass_stat.py [v2_db_path] [v1_db_path]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])

from backend.etl import config
from backend.etl.v2_course_pass_builder import build_course_pass_stat

# (kpi_id, module, label, sort_order, calc_type, formula, unit, data_source,
#  grain, update_cycle, management_value)
KPI_ROWS = [
    ("course_first_pass_rate", "course_quality", "课程首次通过率", 1, "rate",
     "首次修读（attempt_type=regular，含缓考）通过人次数 ÷ 首次修读有效人次数；"
     "有效记录=已发布且未作废且is_pass非空；分母为0时不输出比率", "%",
     "agg_course_pass_stat", "课程×学期", "成绩发布后",
     "衡量课程首修教学结果，是课程质量三分层口径的主指标。"),
    ("course_makeup_pass_rate", "course_quality", "课程补考通过率", 2, "rate",
     "补考（attempt_type=makeup）通过人次数 ÷ 补考有效人次数；分母为0时不输出比率", "%",
     "agg_course_pass_stat", "课程×学期", "成绩发布后",
     "观察补考通道的挽救效果，辅助判断考核与帮扶安排。"),
    ("course_retake_pass_rate", "course_quality", "课程重修通过率", 3, "rate",
     "重修（attempt_type=retake）通过人次数 ÷ 重修有效人次数；分母为0时不输出比率", "%",
     "agg_course_pass_stat", "课程×学期", "成绩发布后",
     "观察重修通道的收敛效果，辅助安排重修资源。"),
    ("public_required_first_pass_rate", "course_quality", "公共必修首次通过率", 4, "rate",
     "课程类别为公共必修的课程首次修读通过人次数 ÷ 公共必修首次修读有效人次数；"
     "课程类别由培养方案模块与V1课程类别合并推导", "%",
     "agg_course_pass_stat", "全校/学院×学期", "成绩发布后",
     "公共必修覆盖全体学生，是重点关注的通识基础课质量指标。"),
]


def migrate(v2_db_path: Path | None = None, v1_db_path: Path | None = None) -> dict:
    v2_report = build_course_pass_stat(v2_db_path, v1_db_path)

    v1_path = Path(v1_db_path or config.DB_PATH)
    kpi_report = {"inserted_or_kept": 0, "skipped": "sys_kpi_config 不存在"}
    conn = sqlite3.connect(v1_path)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sys_kpi_config'"
        ).fetchone()
        if exists:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(sys_kpi_config)")}
            for name in ("data_source", "grain", "update_cycle", "version",
                         "management_value"):
                if name not in columns:
                    conn.execute(f"ALTER TABLE sys_kpi_config ADD COLUMN {name} TEXT")
            for (kpi_id, module, label, order, calc_type, formula, unit,
                 data_source, grain, update_cycle, management_value) in KPI_ROWS:
                conn.execute(
                    "INSERT OR IGNORE INTO sys_kpi_config"
                    "(kpi_id,module,label,enabled,sort_order,calc_type,formula,unit,"
                    "scope_applicable,data_source,grain,update_cycle,version,"
                    "management_value) VALUES(?,?,?,1,?,?,?,?,'all',?,?,?,'1.1',?)",
                    (kpi_id, module, label, order, calc_type, formula, unit,
                     data_source, grain, update_cycle, management_value))
            conn.commit()
            kpi_report = {
                "inserted_or_kept": conn.execute(
                    "SELECT COUNT(*) FROM sys_kpi_config WHERE module='course_quality'"
                ).fetchone()[0]
            }
    finally:
        conn.close()
    return {"v2": v2_report, "v1_kpi": kpi_report}


def main() -> None:
    v2 = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    v1 = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    result = migrate(v2, v1)
    print(f"== M1课程通过率三分层迁移: {v2 or config.V2_DB_PATH} ==")
    for key, value in result["v2"].items():
        print(f"v2.{key}: {value}")
    for key, value in result["v1_kpi"].items():
        print(f"v1_kpi.{key}: {value}")
    print("迁移完成，可安全重复执行。")


if __name__ == "__main__":
    main()
